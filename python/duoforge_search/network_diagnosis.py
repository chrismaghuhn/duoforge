"""Network diagnosis (#451, owner 2026-10-12): which part of the network limits the bot, the policy (which actions
become the search's candidates) or the value (how leaves are scored)? Measurement only: no training, no search
changes. BC6 is measured with params-49333 as the control; every command takes the networks as NAME=PATH.

    python -m duoforge_search.network_diagnosis rows --data DIR... --net NAME=PATH... --out DIR [--player NAME]
    python -m duoforge_search.network_diagnosis arena --logs DIR --net NAME=PATH... --out DIR
    python -m duoforge_search.network_diagnosis outcomes --source FILE... --player NAME --out DIR
    python -m duoforge_search.network_diagnosis report [--rows DIR] [--player-rows DIR] [--arena DIR]
        [--replay NAME=DIR...] --out FILE

- rows: M11 replay dataset rows (private, read only). Without --player, the rows of held-out games (the BC6 split by
  players: duoforge_replay.split.of_game is "test"; BC6 trained on none of them); with --player, the acting player's
  own rows. Per row and network: the rank of the played action in the network's ranking (a joint pair, exactly known
  labels only; a team tuple, the best of the label set), the value, the decision kind and the turn.
- arena: our live client logs (duoforge_live.client; private). Each game runs again through the live Tracker as the
  client fed it (the lines since the last decision as one batch, the sent choice accepted before the next battle
  line); at each decision point the networks' raw rankings and values, the sent choice's rank, and the search's cause
  and choice from the log. A preview-only search (preview_mode "value", no foe network) of each network gives the team
  preview's value table: the spread over our candidate teams and over the worlds. The raw ranking of the log's own
  network is checked against the logged ranking (fidelity).
- outcomes: the result of each replay of one player (for duoforge_search.replay_analysis' decisions, which name their
  replay; private).
- report: aggregates only (no player, room, replay or match id), with 95% intervals from a bootstrap over games.

Every output directory lies outside the repository (dataset.refuse_repository): the row files name dataset games
and the arena files our logs' battles.

Value as a probability: p = (clip(v, -1, 1) + 1) / 2, clipped to [0.001, 0.999] for the log loss; AUC is scale-free.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

from duoforge import _layout

C = _layout.CONSTANTS
TOPS = (1, 4, 8, 16)
KINDS = ("team", "turn", "forced")  # u8 code = index
TURN_CAP = 10  # turn buckets 1..9 and 10+ (the team preview is turn 0)
RATINGS = (1, 1200, 1400, 1600)  # the acting player's rating buckets: unrated (0), below 1200, ..., 1600 and above
BATCH = 512
P_CLIP = 1e-3
BOOTSTRAP = 1000
SEED = 0x451
LOSS_CONFIDENT = 0.5  # a value at or above this (p >= 0.75) before a loss: a confident position that was lost


# --- shared --------------------------------------------------------------------------------------------------------

def decision_kind(domain):
    """team (team selection); forced (no requested slot list offers a move: a switch after a faint); turn."""
    if int(domain["kind"]) == C["DUOFORGE_CHOICE_TEAM_SELECTION"]:
        return "team"
    for s in range(2):
        n = int(domain["slot_count"][s])
        if any(int(k) == C["DUOFORGE_SLOT_MOVE"] for k in domain["slots"][s]["kind"][:n]):
            return "turn"
    return "forced"


def ranks(logp, allowed, target):
    """(B,) 0-based position of each row's target index among its allowed entries by descending log-probability, ties
    to the lower index (duoforge_live.policy._ranked): the target is in the network's top K when the rank is below K."""
    logp, allowed = np.asarray(logp, np.float64), np.asarray(allowed, bool)
    target = np.asarray(target, np.int64)
    rows = np.arange(len(target))
    t = logp[rows, target][:, None]
    index = np.arange(logp.shape[1])[None, :]
    above = allowed & ((logp > t) | ((logp == t) & (index < target[:, None])))
    return above.sum(axis=1)


def best_of_set(logp, label):
    """(B,) the label set's entry the network ranks first (the highest log-probability, ties to the lower index): a set
    is in the top K when this entry is."""
    masked = np.where(np.asarray(label, bool), np.asarray(logp, np.float64), -np.inf)
    return np.argmax(masked, axis=1)


def team_bits(label_team, count):
    """(B, count) bool: the team tuples of each row's label set (bit i in byte i // 8 at i % 8, labels.TEAM_TABLE)."""
    bits = np.unpackbits(np.asarray(label_team, np.uint8), axis=1, bitorder="little")
    return bits[:, :count].astype(bool)


def probability(value):
    """The value as a win probability: (clip(v, -1, 1) + 1) / 2."""
    return (np.clip(np.asarray(value, np.float64), -1.0, 1.0) + 1.0) / 2.0


def rating_name(k):
    """The name of rating bucket k (np.searchsorted(RATINGS, rating, side="right"))."""
    if k == 0:
        return "unrated"
    if k == 1:
        return f"<{RATINGS[1]}"
    if k == len(RATINGS):
        return f">={RATINGS[-1]}"
    return f"{RATINGS[k - 1]}-{RATINGS[k] - 1}"


def turn_bucket(turn):
    return np.minimum(np.asarray(turn, np.int64), TURN_CAP)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_nets(specs):
    """[(name, path)] of NAME=PATH arguments; names are unique identifiers."""
    nets = []
    for spec in specs:
        name, sep, path = spec.partition("=")
        if not sep or not name.isidentifier() or not path:
            raise ValueError(f"--net {spec!r}: NAME=PATH with an identifier name")
        if name in (n for n, _ in nets):
            raise ValueError(f"--net {name!r} given twice")
        nets.append((name, path))
    return nets


class Net:
    """A checkpoint's raw network (duoforge_live.policy.load) on fixed-size batches: the pair head's and the team
    head's log-probabilities and the value, from the inputs of its own encoder and view-extension mask."""

    def __init__(self, name, path):
        from duoforge_live import policy
        self.name, self.path = name, path
        self.sha256 = sha256_of(path)
        self.policy = policy.load(path)
        self.encoder, self.ext_supported = self.policy.encoder, self.policy.ext_supported

    def encode(self, observation, domain, ext):
        """(obs, slots, mask) of one decision in this network's inputs; ValueError when its encoder refuses it."""
        from duoforge import features
        o, s, m = features.encode(observation, domain, ext, self.ext_supported)
        return (features.as_encoder(o, observation, self.encoder), features.slots_as_encoder(s, self.encoder),
                np.asarray(m, bool))

    def forward(self, obs, slots, masks):
        """(pair logp (B, 1024), team logp (B, 360), value (B,)) as float64, in batches of BATCH (padded: one shape)."""
        n = len(obs)
        out = ([], [], [])
        for start in range(0, n, BATCH):
            k = min(BATCH, n - start)
            o = np.zeros((BATCH,) + obs.shape[1:], np.float32)
            s = np.zeros((BATCH,) + slots.shape[1:], np.float32)
            m = np.zeros((BATCH,) + masks.shape[1:], bool)
            o[:k], s[:k], m[:k] = obs[start:start + k], slots[start:start + k], masks[start:start + k]
            pairs, team, value = self.policy._forward(o, s, m)
            for acc, x in zip(out, (pairs, team, value)):
                acc.append(np.asarray(x, np.float64)[:k])
        return tuple(np.concatenate(acc) if acc else np.zeros((0,)) for acc in out)


# --- rows: M11 replay dataset rows ---------------------------------------------------------------------------------

def played_pair(domain, label_slots, label_reason):
    """The one played pair index (i * 32 + j) of a row whose label names exactly one allowed pair, or None
    (duoforge_search.replay_analysis.played_pair on the row's arrays)."""
    from duoforge_replay import labels
    reasons = [int(r) for r in label_reason]
    if any(r not in (labels.EXACT, labels.NOT_REQUESTED) for r in reasons) or \
            all(r == labels.NOT_REQUESTED for r in reasons):
        return None
    pairs = []
    n0, n1 = int(domain["slot_count"][0]), int(domain["slot_count"][1])
    for i in range(n0):
        if reasons[0] == labels.EXACT and not (int(label_slots[0]) >> i) & 1:
            continue
        for j in range(n1):
            if reasons[1] == labels.EXACT and not (int(label_slots[1]) >> j) & 1:
                continue
            if (int(domain["allowed"][i]) >> j) & 1:
                pairs.append(i * 32 + j)
    return pairs[0] if len(pairs) == 1 else None


def _part_dir(data, part):
    path = Path(data) / part
    return path if path.is_dir() else Path(data)


def rows_main(args):
    from duoforge_learn.selfplay import TEAM_TABLE
    from duoforge_replay import split
    from duoforge_replay.dataset import read, read_games
    from duoforge_replay.game import _hash8, _to_id
    nets = [Net(name, path) for name, path in parse_nets(args.net)]
    player = _hash8(_to_id(args.player)) if args.player else None
    counts = Counter()
    cols = {k: [] for k in ("source", "game", "side", "kind", "turn", "z", "acting_test", "exact", "label_size",
                            "options", "rating")}
    for net in nets:
        cols[f"rank_{net.name}"], cols[f"value_{net.name}"] = [], []
    game_ids = {}
    for source, data in enumerate(args.data):
        games_of = {}
        for shard in read(data):
            part = shard["part"]
            if part not in games_of:
                games_of[part] = read_games(_part_dir(data, part))
            g = games_of[part]
            keep = []
            for r in range(len(shard["game"])):
                counts["rows"] += 1
                game, side = int(shard["game"][r]), int(shard["side"][r])
                players = tuple(int(x) for x in g["players"][game])
                if player is not None:
                    if players[side] != player:
                        counts["skipped.other_player"] += 1
                        continue
                elif split.of_game(players) != "test":
                    counts["skipped.training_games"] += 1
                    continue
                if int(shard["picks_hypotheses"][r]) > 1:
                    counts["skipped.pick_hypotheses"] += 1
                    continue
                keep.append(r)
            if not keep:
                continue
            encoded = {net.name: ([], [], [], []) for net in nets}  # row positions, obs, slots, masks
            meta = []
            for r in keep:
                game, side = int(shard["game"][r]), int(shard["side"][r])
                dom = shard["domain"][r]
                kind = decision_kind(dom)
                if kind == "team":
                    label = team_bits(shard["label_team"][r:r + 1], len(TEAM_TABLE))[0]
                    exact, size, options = bool(label.any()), int(label.sum()), len(TEAM_TABLE)
                    target = label
                else:
                    pair = played_pair(dom, shard["label_slots"][r], shard["label_reason"][r])
                    exact, size = pair is not None, 1 if pair is not None else 0
                    options = sum(bin(int(dom["allowed"][i])).count("1") for i in range(int(dom["slot_count"][0])))
                    target = pair
                winner = int(g["winner"][game])
                key = (source, part, game)
                gid = game_ids.setdefault(key, len(game_ids))
                players = tuple(int(x) for x in g["players"][game])
                meta.append((gid, side, KINDS.index(kind), int(shard["observation"][r]["turn"]),
                             0 if winner < 0 else (1 if winner == side else -1), split.is_test_player(players[side]),
                             exact, size, options, target, int(g["ratings"][game, side])))
                for net in nets:
                    try:
                        o, s, m = net.encode(shard["observation"][r], dom, shard["ext"][r])
                    except ValueError:
                        counts[f"encode_refused.{net.name}"] += 1
                        continue
                    pos, os_, ss, ms = encoded[net.name]
                    pos.append(len(meta) - 1)
                    os_.append(o)
                    ss.append(s)
                    ms.append(m)
            n = len(meta)
            for net in nets:
                rank = np.full(n, -1, np.int32)
                value = np.full(n, np.nan, np.float32)
                pos, os_, ss, ms = encoded[net.name]
                if pos:
                    pair_logp, team_logp, v = net.forward(np.stack(os_), np.stack(ss), np.stack(ms))
                    masks = np.stack(ms).reshape(len(pos), -1)
                    for k, p in enumerate(pos):
                        value[p] = v[k]
                    team_rows = [k for k, p in enumerate(pos) if meta[p][2] == 0 and meta[p][6]]
                    if team_rows:
                        labels_ = np.stack([meta[pos[k]][9] for k in team_rows])
                        lp = team_logp[team_rows]
                        best = best_of_set(lp, labels_)
                        rank[[pos[k] for k in team_rows]] = ranks(lp, np.ones_like(labels_), best)
                    pair_rows = [k for k, p in enumerate(pos) if meta[p][2] != 0 and meta[p][6]]
                    if pair_rows:
                        targets = np.array([meta[pos[k]][9] for k in pair_rows])
                        rank[[pos[k] for k in pair_rows]] = ranks(pair_logp[pair_rows], masks[pair_rows], targets)
                cols[f"rank_{net.name}"].append(rank)
                cols[f"value_{net.name}"].append(value)
            for name, k in (("game", 0), ("side", 1), ("kind", 2), ("turn", 3), ("z", 4), ("acting_test", 5),
                            ("exact", 6), ("label_size", 7), ("options", 8), ("rating", 10)):
                cols[name].append(np.array([m[k] for m in meta]))
            cols["source"].append(np.full(n, source, np.int8))
            counts["kept"] += n
            if args.max_rows and counts["kept"] >= args.max_rows:
                break
        if args.max_rows and counts["kept"] >= args.max_rows:
            break
    arrays = {k: (np.concatenate(v) if v else np.zeros(0)) for k, v in cols.items()}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / "rows.npz", **arrays)
    meta = {"command": "rows", "sources": [Path(d).name for d in args.data], "one_player": player is not None,
            "nets": {net.name: {"file": os.path.basename(net.path), "sha256": net.sha256, "encoder": net.encoder}
                     for net in nets},
            "counts": dict(sorted(counts.items())), "games": len(game_ids)}
    (out / "meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(meta, indent=1))
    return 0


# --- arena: our live client logs -----------------------------------------------------------------------------------

def read_log(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def battle_steps(records):
    """The client's feed of one battle log, in order: ("accept", text) where the client accepts its last choice,
    ("feed", lines) for the battle lines since the last decision (error lines are not fed), ("decision", record),
    ("stop", reason) where the replay cannot follow the client (a rejected choice: the next candidate is not logged;
    a second battle start: a reconnect's replayed log), and ("end", line)."""
    from duoforge_live.client import _room_line
    pending = None  # the choice sent last, accepted before the next non-room battle line
    lines, starts = [], 0
    for rec in records:
        if "in" in rec:
            line = rec["in"]
            if line.startswith("|error|"):
                continue
            if line == "|start":
                starts += 1
                if starts > 1:
                    yield "stop", "second_start"
                    return
            if pending is not None and not _room_line(line):
                if lines:
                    yield "feed", lines
                    lines = []
                yield "accept", pending
                pending = None
            lines.append(line)
        elif "decision" in rec:
            if lines:
                yield "feed", lines
                lines = []
            yield "decision", rec
            pending = rec["sent"]
        elif "unavailable" in rec:
            pending = None
        elif "rejected" in rec:
            yield "stop", "rejected_choice"
            return
        elif "end" in rec:
            if lines:
                yield "feed", lines
            yield "end", rec["end"]
            return
        elif "forfeit" in rec:
            yield "stop", "forfeit"
            return


def own_team(records, own_id):
    """Team A or B: the team whose sheets the own |showteam| line shows (None: neither)."""
    from duoforge_live import teams
    from duoforge_live.client import toid
    side = None
    for rec in records:
        line = rec.get("in", "")
        if line.startswith("|player|"):
            parts = line.split("|")
            if len(parts) > 3 and toid(parts[3]) == own_id:
                side = parts[2]
        elif side and line.startswith(f"|showteam|{side}|"):
            sets = teams.unpack(line.split("|", 3)[3])
            for name in ("A", "B"):
                if teams.match(sets, teams.text(name)):
                    return name
            return None
    return None


def team_index(text):
    """TEAM_TABLE's index of a "team 5314" choice."""
    from duoforge_live.game import TEAM_TABLE
    picks = tuple(int(c) - 1 for c in text.split()[1])
    return TEAM_TABLE.index(picks)


def preview_table(record):
    """The preview search's value table read for the diagnosis: per own candidate team the value against the foe's
    menu (each world's foe probabilities normalised, worlds by their weights), the spread over the distinct own
    candidates, and the mean standard deviation of a cell over the worlds (table (S, K, M))."""
    tables = np.asarray(record["tables"], np.float64)
    weights = np.asarray(record["weights"], np.float64)
    weights = weights / weights.sum()
    q = np.asarray(record["foe_probs"], np.float64)  # (S, M)
    q = q / q.sum(axis=1, keepdims=True)
    own = np.einsum("w,wij,wj->i", weights, tables, q)
    cell = np.einsum("w,wij->ij", weights, tables)
    world_sd = np.sqrt(np.einsum("w,wij->ij", weights, (tables - cell[None]) ** 2))
    distinct = np.unique(np.round(cell, 6), axis=0)
    distinct_own = np.einsum("ij,j->i", distinct, np.einsum("w,wj->j", weights, q))
    return {"own": own.tolist(), "spread": float(distinct_own.max() - distinct_own.min()),
            "distinct": int(len(distinct)), "candidates": int(tables.shape[1]), "world_sd": float(world_sd.mean()),
            "changed": bool(record.get("changed"))}


def arena_game(path, records, tables, nets, previews, own_id):
    """The decision rows of one battle log and its result (1 won, -1 lost), or (None, reason) when it is left out."""
    from duoforge import features
    from duoforge_live import options, search as live_search, teams
    from duoforge_live.game import TEAM_TABLE
    from duoforge_live.tracker import Tracker
    team = own_team(records, own_id)
    if team is None:
        return None, "own_team_unknown"
    tracker = Tracker(tables, teams.text(team))
    rows, result = [], None
    for step, item in battle_steps(records):
        if step == "feed":
            tracker.feed(item)
        elif step == "accept":
            tracker.accepted(item)
        elif step == "stop":
            return None, item
        elif step == "end":
            winner = item.split("|")[2] if item.startswith("|win|") else None
            from duoforge_live.client import toid
            result = 0 if winner is None else (1 if toid(winner) == own_id else -1)
        elif step == "decision":
            if not tracker.ready or tracker.request.get("wait"):
                return None, "not_asked_at_decision"
            observation = tracker.observation()
            domain, lists = tracker.domain()
            ext = tracker.observation_ext()
            kind = "team" if tracker.request.get("teamPreview") else decision_kind(domain)
            search = item.get("search") or {}
            row = {"turn": int(observation["turn"]), "kind": kind, "cause": search.get("cause"),
                   "logged_top": item["top"], "sent": item["sent"]}
            for net in nets:
                o, s, m = net.encode(observation, domain, ext)
                pair_logp, team_logp, value = (x[0] for x in net.forward(o[None], s[None], m[None]))
                row[f"value_{net.name}"] = float(value)
                if kind == "team":
                    order = np.argsort(-team_logp, kind="stable")
                    ranked = [(options.team_text(TEAM_TABLE[i]), float(np.exp(team_logp[i]))) for i in order]
                    row[f"rank_{net.name}"] = int(np.flatnonzero(order == team_index(item["sent"]))[0])
                else:
                    allowed = m.reshape(-1)
                    order = [int(i) for i in np.argsort(-np.where(allowed, pair_logp, -np.inf), kind="stable")
                             if allowed[i]]
                    n = m.shape[1]
                    ranked = [(options.pair_text(lists[0][i // n], lists[1][i % n]), float(np.exp(pair_logp[i])))
                              for i in order]
                    texts = [t for t, _ in ranked]
                    row[f"rank_{net.name}"] = texts.index(item["sent"]) if item["sent"] in texts else None
                    if search.get("action") is not None:
                        row[f"search_rank_{net.name}"] = order.index(int(search["action"])) \
                            if int(search["action"]) in order else None
                row[f"raw_top_{net.name}"] = ranked[0][0]
                row[f"top3_{net.name}"] = ranked[:3]
            if kind == "team":
                parts = tracker.public_parts()
                for net_name, live in previews.items():
                    seat = int(observation["player"])
                    o, s, m = features.encode(observation, domain, ext, live.searcher.ext_supported)
                    obs, slots, pairs = live_search._encoded(live.searcher, observation, o, None, None)
                    live.roots.set(0, seat, request=parts["request"], observation=observation, obs=obs, slots=slots,
                                   pairs=pairs, record=parts["record"], status=parts["status"], episode=0,
                                   causes=parts["causes"])
                    key = live_search.decision_key(Path(path).stem, int(observation["epoch"]))
                    _, (record,) = live.searcher.decide(live.roots, [0], [seat], [key], [False])
                    row[f"preview_{net_name}"] = preview_table(record) if record.get("kind") == "searched" else \
                        {"kind": record.get("kind"), "reason": record.get("reason")}
            rows.append(row)
    if result is None:
        return None, "no_end"
    for r in rows:
        r["z"] = result
    return rows, None


def fidelity(row, net_name):
    """Whether the logged ranking is this network's raw ranking (texts, probabilities to 1e-5): the logged top three
    for a decision played raw (the team preview, a forced or refused one); for a searched one, the logged entries after
    the search's choice (duoforge_live.game: the raw ranking without that choice)."""
    logged = [(t, p) for t, p in row["logged_top"]]
    mine = row[f"top3_{net_name}"]
    if row["cause"] == "searched":
        logged, mine = logged[1:], [(t, p) for t, p in mine if t != logged[0][0]][:len(logged) - 1]
    return len(logged) == len(mine) and all(a == c and abs(b - d) <= 1e-5 for (a, b), (c, d) in zip(logged, mine))


def arena_main(args):
    from duoforge_live import data as live_data, search as live_search
    nets = [Net(name, path) for name, path in parse_nets(args.net)]
    tables = live_data.for_checkpoint(nets[0].path)  # the log's own network's tables, as the client read the battle
    for net in nets[1:]:
        live_data.for_checkpoint(net.path)  # every network reads these tables as trained (ValueError otherwise)
    previews = {}
    if not args.no_preview:
        settings = dict(live_search.HONEST_SETTINGS, preview_mode="value", preview_only=True)
        previews = {net.name: live_search.load(net.path, settings=settings, foe_net=None) for net in nets}
    counts, games = Counter(), []
    start = time.perf_counter()
    try:
        for path in sorted(Path(args.logs).glob("battle-*.jsonl")):
            counts["logs"] += 1
            if not any(path.name.startswith(f"battle-{f}-") for f in args.format):
                counts["skipped.format"] += 1
                continue
            records = read_log(path)
            rows, reason = arena_game(path, records, tables, nets, previews, args.own)
            if rows is None:
                counts[f"skipped.{reason}"] += 1
                continue
            counts["games"] += 1
            games.append(rows)
    finally:
        for live in previews.values():
            live.close()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "arena.jsonl", "w", encoding="utf-8") as f:
        for g, rows in enumerate(games):
            for r in rows:
                f.write(json.dumps({"game": g, **r}) + "\n")
    meta = {"command": "arena", "nets": {net.name: {"file": os.path.basename(net.path), "sha256": net.sha256,
                                                    "encoder": net.encoder} for net in nets},
            "previews": sorted(previews), "counts": dict(sorted(counts.items())),
            "seconds": time.perf_counter() - start}
    (out / "meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(meta, indent=1))
    return 0


# --- outcomes: the results of one player's replays ------------------------------------------------------------------

def outcomes_main(args):
    from duoforge_replay import source, split
    from duoforge_replay.game import _hash8, _to_id
    player = _hash8(_to_id(args.player))
    result = {}
    for replay_id, format_id, log in source.games(args.source, ""):
        lines = log.split("\n")
        try:
            players = split.players_of(lines)
        except ValueError:
            continue
        if player not in players:
            continue
        side = players.index(player)
        wins = [line.rstrip("\r").split("|")[2] for line in lines if line.startswith("|win|")]
        if len(wins) != 1:
            result[replay_id] = 0
            continue
        result[replay_id] = 1 if players.index(_hash8(_to_id(wins[0]))) == side else -1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "outcomes.json").write_text(json.dumps(result) + "\n", encoding="utf-8")
    print(json.dumps({"replays": len(result), "results": dict(Counter(result.values()))}))
    return 0


# --- statistics ---------------------------------------------------------------------------------------------------

def replicate_weights(groups, b=BOOTSTRAP, seed=SEED, chunk=100):
    """Bootstrap over groups (games): yields (k, G) multiplicities, b rows in all, each a draw of G groups with
    replacement."""
    rng = np.random.default_rng(seed)
    for start in range(0, b, chunk):
        k = min(chunk, b - start)
        yield rng.multinomial(groups, np.full(groups, 1.0 / groups), size=k).astype(np.float64)


def interval(samples):
    lo, hi = np.percentile(np.asarray(samples, np.float64), [2.5, 97.5])
    return [float(lo), float(hi)]


def ratio(num, den, group, groups, b=BOOTSTRAP, seed=SEED):
    """sum(num) / sum(den) with its 95% bootstrap interval over the groups (num, den per row)."""
    g_num = np.bincount(group, weights=num, minlength=groups)
    g_den = np.bincount(group, weights=den, minlength=groups)
    point = g_num.sum() / g_den.sum() if g_den.sum() else float("nan")
    samples = []
    for w in replicate_weights(groups, b, seed):
        d = w @ g_den
        samples.append(np.where(d > 0, (w @ g_num) / np.where(d > 0, d, 1), np.nan))
    samples = np.concatenate(samples)
    return {"value": float(point), "ci": interval(samples[np.isfinite(samples)]), "n": int(np.sum(den > 0))}


def auc(score, positive, weight=None):
    """The weighted Mann-Whitney AUC: the chance that a positive row scores above a negative one (ties half)."""
    score, positive = np.asarray(score, np.float64), np.asarray(positive, bool)
    weight = np.ones(len(score)) if weight is None else np.asarray(weight, np.float64)
    order = np.argsort(score, kind="stable")
    s, pos, w = score[order], positive[order], weight[order]
    wp, wn = np.where(pos, w, 0.0), np.where(pos, 0.0, w)
    # per tie block: the negatives below it and the negatives inside it
    first = np.r_[True, s[1:] != s[:-1]]
    block = np.cumsum(first) - 1
    neg_in = np.bincount(block, weights=wn)
    neg_below = np.cumsum(neg_in) - neg_in
    total = wp.sum() * wn.sum()
    if total == 0:
        return float("nan")
    return float(np.sum(wp * (neg_below[block] + 0.5 * neg_in[block])) / total)


def auc_ci(score, positive, group, groups, b=BOOTSTRAP, seed=SEED):
    point = auc(score, positive)
    samples = [auc(score, positive, w[group]) for ws in replicate_weights(groups, b, seed) for w in ws]
    samples = np.asarray(samples)
    return {"value": point, "ci": interval(samples[np.isfinite(samples)]), "n": int(len(score))}


def value_metrics(value, z, group, groups, b=BOOTSTRAP, seed=SEED, bins=10):
    """Brier score, log loss, AUC (each with its interval), the expected calibration error and the reliability curve of
    values against results z (+1 won, -1 lost)."""
    p = probability(value)
    y = (np.asarray(z) > 0).astype(np.float64)
    pc = np.clip(p, P_CLIP, 1 - P_CLIP)
    ones = np.ones(len(p))
    edges = np.minimum((p * bins).astype(int), bins - 1)
    curve = []
    ece = 0.0
    for k in range(bins):
        sel = edges == k
        if sel.any():
            curve.append({"bin": [k / bins, (k + 1) / bins], "n": int(sel.sum()), "p": float(p[sel].mean()),
                          "won": float(y[sel].mean())})
            ece += sel.mean() * abs(p[sel].mean() - y[sel].mean())
    return {"n": int(len(p)), "games": int(len(np.unique(group))), "won": float(y.mean()),
            "brier": ratio((p - y) ** 2, ones, group, groups, b, seed),
            "log_loss": ratio(-(y * np.log(pc) + (1 - y) * np.log(1 - pc)), ones, group, groups, b, seed),
            "auc": auc_ci(value, y > 0, group, groups, b, seed), "ece": float(ece), "reliability": curve}


def paired_difference(a, b_, group, groups, b=BOOTSTRAP, seed=SEED):
    """mean(a) - mean(b_) over the same rows with its interval (a, b_ per row)."""
    return ratio(np.asarray(a, np.float64) - np.asarray(b_, np.float64), np.ones(len(a)), group, groups, b, seed)


def auc_difference(score_a, score_b, positive, group, groups, b=BOOTSTRAP, seed=SEED):
    point = auc(score_a, positive) - auc(score_b, positive)
    samples = []
    for ws in replicate_weights(groups, b, seed):
        for w in ws:
            samples.append(auc(score_a, positive, w[group]) - auc(score_b, positive, w[group]))
    samples = np.asarray(samples)
    return {"value": point, "ci": interval(samples[np.isfinite(samples)])}


# --- report -------------------------------------------------------------------------------------------------------

def _dense(group):
    _, inverse = np.unique(np.asarray(group), return_inverse=True)
    return inverse, int(inverse.max()) + 1 if len(inverse) else 0


def recall_report(rank, kind, turn, exact, options, group, select, b, seed):
    """Top-K hit rates by decision kind and, for turns, by turn bucket; the share of rows whose menu has at most K
    entries (a trivial hit)."""
    out = {}
    for k_name in KINDS:
        sel = select & exact & (kind == KINDS.index(k_name)) & (rank >= 0)
        if not sel.any():
            continue
        g, groups = _dense(group[sel])
        r, o = rank[sel], options[sel]
        out[k_name] = {f"top{t}": ratio((r < t).astype(float), np.ones(len(r)), g, groups, b, seed) for t in TOPS}
        out[k_name]["trivial"] = {f"top{t}": float((o <= t).mean()) for t in TOPS}
        out[k_name]["rows"] = int(sel.sum())
    by_turn = {}
    for t in range(1, TURN_CAP + 1):
        sel = select & exact & (kind == KINDS.index("turn")) & (rank >= 0) & (turn_bucket(turn) == t)
        if sel.any():
            g, groups = _dense(group[sel])
            by_turn[str(t)] = {f"top{k}": ratio((rank[sel] < k).astype(float), np.ones(int(sel.sum())), g, groups,
                                                b, seed) for k in (1, 8)}
    out["turn_by_turn"] = by_turn
    return out


def rows_report(path, b, seed):
    meta = json.loads((Path(path) / "meta.json").read_text(encoding="utf-8"))
    with np.load(Path(path) / "rows.npz") as z:
        a = {k: z[k] for k in z.files}
    nets = sorted(meta["nets"])
    group = a["game"].astype(np.int64)
    kind, turn, exact, options = a["kind"], a["turn"], a["exact"].astype(bool), a["options"]
    acting = a["acting_test"].astype(bool) if not meta["one_player"] else np.ones(len(group), bool)
    out = {"meta": {k: meta[k] for k in ("sources", "one_player", "counts", "games")},
           "nets": {n: {"file": meta["nets"][n]["file"], "sha256": meta["nets"][n]["sha256"][:12]} for n in nets}}
    policy = {}
    for n in nets:
        rank = a[f"rank_{n}"]
        policy[n] = {"all": recall_report(rank, kind, turn, exact, options, group, acting, b, seed),
                     "by_source": {}}
        for s, name in enumerate(meta["sources"]):
            sel = acting & (a["source"] == s) & exact & (rank >= 0) & (kind == KINDS.index("turn"))
            if sel.any():
                g, groups = _dense(group[sel])
                policy[n]["by_source"][name] = {f"top{t}": ratio((rank[sel] < t).astype(float),
                                                                 np.ones(int(sel.sum())), g, groups, b, seed)
                                                for t in (1, 8)}
        policy[n]["by_rating"] = {}
        bucket = np.searchsorted(RATINGS, a["rating"], side="right")
        for k in range(len(RATINGS) + 1):
            sel = acting & (bucket == k) & exact & (rank >= 0) & (kind == KINDS.index("turn"))
            if sel.any():
                g, groups = _dense(group[sel])
                policy[n]["by_rating"][rating_name(k)] = {f"top{t}": ratio((rank[sel] < t).astype(float),
                                                                 np.ones(int(sel.sum())), g, groups, b, seed)
                                                for t in (1, 8)}
    out["policy"] = policy
    if len(nets) == 2:  # the paired difference of the top-8 hit rate on turn decisions both networks encode
        n0, n1 = nets
        sel = acting & exact & (kind == KINDS.index("turn")) & (a[f"rank_{n0}"] >= 0) & (a[f"rank_{n1}"] >= 0)
        g, groups = _dense(group[sel])
        out["policy_difference"] = {f"top{t}": {"of": f"{n0} - {n1}", **paired_difference(
            (a[f"rank_{n0}"][sel] < t), (a[f"rank_{n1}"][sel] < t), g, groups, b, seed)} for t in (1, 8)}
    value = {}
    finite = np.ones(len(group), bool)
    for n in nets:
        finite &= np.isfinite(a[f"value_{n}"])
    has_z = a["z"] != 0
    for n in nets:
        v = a[f"value_{n}"]
        sel = finite & has_z
        g, groups = _dense(group[sel])
        value[n] = {"all": value_metrics(v[sel], a["z"][sel], g, groups, b, seed), "by_turn": {}}
        for t in range(0, TURN_CAP + 1):
            s2 = sel & (turn_bucket(turn) == t) & ((kind == 0) if t == 0 else (kind != 0))
            if s2.sum() > 50:
                g2, groups2 = _dense(group[s2])
                p = probability(v[s2])
                y = (a["z"][s2] > 0).astype(float)
                value[n]["by_turn"][str(t)] = {"n": int(s2.sum()),
                                               "auc": auc_ci(v[s2], y > 0, g2, groups2, b, seed),
                                               "brier": ratio((p - y) ** 2, np.ones(len(p)), g2, groups2, b, seed)}
    out["value"] = value
    if len(nets) == 2:
        n0, n1 = nets
        sel = finite & has_z
        g, groups = _dense(group[sel])
        y = a["z"][sel] > 0
        out["value_difference"] = {"auc": {"of": f"{n0} - {n1}", **auc_difference(
            a[f"value_{n0}"][sel], a[f"value_{n1}"][sel], y, g, groups, b, seed)}}
        early = sel & (kind != 0) & (turn >= 1) & (turn <= 3)
        g, groups = _dense(group[early])
        out["value_difference"]["auc_turns_1_3"] = {"of": f"{n0} - {n1}", **auc_difference(
            a[f"value_{n0}"][early], a[f"value_{n1}"][early], a["z"][early] > 0, g, groups, b, seed)}
        for n in nets:
            out["value"][n]["turns_1_3"] = auc_ci(a[f"value_{n}"][early], a["z"][early] > 0, g, groups, b, seed)
    return out


def arena_report(path, b, seed):
    meta = json.loads((Path(path) / "meta.json").read_text(encoding="utf-8"))
    with open(Path(path) / "arena.jsonl", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    nets = sorted(meta["nets"])
    group = np.array([r["game"] for r in rows])
    g, groups = _dense(group)
    z = np.array([r["z"] for r in rows])
    out = {"meta": {"counts": meta["counts"], "decisions": len(rows), "games": groups,
                    "won": int(len({r["game"] for r in rows if r["z"] > 0}))},
           "nets": {n: {"file": meta["nets"][n]["file"], "sha256": meta["nets"][n]["sha256"][:12]} for n in nets},
           "kinds": dict(Counter(r["kind"] for r in rows)), "causes": dict(Counter(str(r["cause"]) for r in rows))}
    out["fidelity"] = {n: {"raw_checked": sum(1 for r in rows if r["cause"] != "searched"),
                           "raw_match": sum(1 for r in rows if r["cause"] != "searched" and fidelity(r, n))}
                       for n in nets}
    out["value"] = {n: value_metrics(np.array([r[f"value_{n}"] for r in rows]), z, g, groups, b, seed) for n in nets}
    # the sent choice's rank in each network's raw ranking (the live search's play; the team preview is raw)
    out["sent_rank"] = {}
    for n in nets:
        out["sent_rank"][n] = {}
        for k_name in KINDS:
            sel = [i for i, r in enumerate(rows) if r["kind"] == k_name and r.get(f"rank_{n}") is not None]
            if sel:
                r_ = np.array([rows[i][f"rank_{n}"] for i in sel])
                gg, gs = _dense(group[sel])
                out["sent_rank"][n][k_name] = {f"top{t}": ratio((r_ < t).astype(float), np.ones(len(r_)), gg, gs, b,
                                                                seed) for t in (1, 8)}
    searched = [r for r in rows if r["cause"] == "searched"]
    out["search_changed_raw"] = {n: sum(1 for r in searched if r["sent"] != r[f"raw_top_{n}"]) / max(1, len(searched))
                                 for n in nets}
    out["search_changed_raw"]["searched"] = len(searched)
    # value traces of the lost games: confident (a value >= LOSS_CONFIDENT after the preview) or never ahead (no value
    # above 0 after the preview); the same for the won games (a comeback: never ahead; lost the lead: none, they won)
    traces = {}
    for n in nets:
        by_game = {}
        for r in rows:
            if r["kind"] != "team":
                by_game.setdefault(r["game"], (r["z"], []))[1].append((r["turn"], r[f"value_{n}"]))
        lost = [vals for zz, vals in by_game.values() if zz < 0]
        won = [vals for zz, vals in by_game.values() if zz > 0]
        traces[n] = {"lost": len(lost),
                     "lost_confident": sum(1 for v in lost if max(x for _, x in v) >= LOSS_CONFIDENT),
                     "lost_never_ahead": sum(1 for v in lost if max(x for _, x in v) <= 0.0),
                     "lost_first_value_mean": float(np.mean([v[0][1] for v in lost])) if lost else None,
                     "won": len(won), "won_never_ahead": sum(1 for v in won if max(x for _, x in v) <= 0.0),
                     "won_confident": sum(1 for v in won if max(x for _, x in v) >= LOSS_CONFIDENT),
                     "won_first_value_mean": float(np.mean([v[0][1] for v in won])) if won else None}
    out["loss_traces"] = traces
    previews = {}
    for n in meta.get("previews", []):
        cells = [r[f"preview_{n}"] for r in rows if r["kind"] == "team" and f"preview_{n}" in r]
        ok = [c for c in cells if "spread" in c]
        if not ok:
            previews[n] = {"decisions": len(cells), "searched": 0}
            continue
        spread = np.array([c["spread"] for c in ok])
        previews[n] = {"decisions": len(cells), "searched": len(ok),
                       "not_searched": dict(Counter(str(c.get("kind")) for c in cells if "spread" not in c)),
                       "spread_p50": float(np.median(spread)), "spread_mean": float(spread.mean()),
                       "spread_p90": float(np.percentile(spread, 90)), "spread_max": float(spread.max()),
                       "spread_below_0.02": float((spread < 0.02).mean()),
                       "world_sd_mean": float(np.mean([c["world_sd"] for c in ok])),
                       "distinct_mean": float(np.mean([c["distinct"] for c in ok])),
                       "candidates": int(ok[0]["candidates"]),
                       "changed_raw": float(np.mean([c["changed"] for c in ok]))}
        # the scale: how far the preview value itself moves between games
        values = np.array([r[f"value_{n}"] for r in rows if r["kind"] == "team"])
        previews[n]["preview_value_sd_between_games"] = float(values.std())
    out["preview"] = previews
    return out


def replay_report(decisions_path, outcomes_path, b, seed):
    """Search against raw play on a player's replays (replay_analysis' decisions): where the search's choice differs
    from the main network's raw first choice, which one the player played; the searched value against the result."""
    outcomes = json.loads(Path(outcomes_path).read_text(encoding="utf-8"))
    with open(decisions_path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    searched = [r for r in rows if r["kind"] == "searched"]
    for r in searched:
        r["z"] = outcomes.get(r["replay"], 0)
    group = np.array([r["game"] for r in searched])
    g, groups = _dense(group)
    out = {"decisions": len(rows), "searched": len(searched), "games": groups}
    scored = [i for i, r in enumerate(searched) if r.get("played") is not None]
    differ = [i for i in scored if searched[i]["choice"] != searched[i]["raw"]]
    if differ:
        gg, gs = _dense(group[differ])
        human_search = np.array([searched[i]["played"] == searched[i]["choice"] for i in differ], float)
        human_raw = np.array([searched[i]["played"] == searched[i]["raw"] for i in differ], float)
        out["search_vs_raw"] = {"scored": len(scored), "differ": len(differ),
                                "player_plays_search": ratio(human_search, np.ones(len(differ)), gg, gs, b, seed),
                                "player_plays_raw": ratio(human_raw, np.ones(len(differ)), gg, gs, b, seed),
                                "difference": paired_difference(human_search, human_raw, gg, gs, b, seed),
                                "neither": float(1 - human_search.mean() - human_raw.mean())}
    if scored:
        gg, gs = _dense(group[scored])
        r1 = np.array([searched[i]["agree"] for i in scored], float)
        r8 = np.array([searched[i]["played_rank"] is not None and searched[i]["played_rank"] < 8 for i in scored],
                      float)
        raw1 = np.array([searched[i]["played"] == searched[i]["raw"] for i in scored], float)
        out["agreement"] = {"search_top1": ratio(r1, np.ones(len(r1)), gg, gs, b, seed),
                            "search_top8": ratio(r8, np.ones(len(r8)), gg, gs, b, seed),
                            "raw_top1": ratio(raw1, np.ones(len(raw1)), gg, gs, b, seed)}
    known = [i for i, r in enumerate(searched) if r["z"] != 0 and r.get("value") is not None]
    if known:
        gg, gs = _dense(group[known])
        out["value"] = value_metrics(np.array([searched[i]["value"] for i in known]),
                                     np.array([searched[i]["z"] for i in known]), gg, gs, b, seed)
    return out


def report_main(args):
    out = {"issue": 451, "bootstrap": {"replicates": args.bootstrap, "seed": SEED, "over": "games"}}
    if args.rows:
        out["held_out"] = rows_report(args.rows, args.bootstrap, SEED)
    if args.player_rows:
        out["top_player_rows"] = rows_report(args.player_rows, args.bootstrap, SEED)
    if args.arena:
        out["arena"] = arena_report(args.arena, args.bootstrap, SEED)
    for spec in args.replay or []:
        name, _, path = spec.partition("=")
        out.setdefault("top_player_search", {})[name] = replay_report(
            Path(path) / "decisions.jsonl", Path(args.outcomes) / "outcomes.json", args.bootstrap, SEED)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"report: {args.out}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m duoforge_search.network_diagnosis", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("rows", help="M11 dataset rows: recall and value per network")
    r.add_argument("--data", nargs="+", required=True)
    r.add_argument("--net", nargs="+", required=True, help="NAME=PATH")
    r.add_argument("--out", required=True)
    r.add_argument("--player", default=None, help="only this player's own rows (hashed; never stored)")
    r.add_argument("--max-rows", type=int, default=0)
    a = sub.add_parser("arena", help="our live client logs, replayed through the live tracker")
    a.add_argument("--logs", required=True)
    a.add_argument("--net", nargs="+", required=True, help="NAME=PATH; the first is the log's own network")
    a.add_argument("--out", required=True)
    a.add_argument("--own", default="tiansuan", help="the bot's user id in the logs")
    a.add_argument("--format", nargs="+", default=["gen9championsvgc2026regmcots"],
                   help="the battle formats replayed (a random-team format has no Team A or B)")
    a.add_argument("--no-preview", action="store_true")
    o = sub.add_parser("outcomes", help="the results of one player's replays")
    o.add_argument("--source", nargs="+", required=True)
    o.add_argument("--player", required=True)
    o.add_argument("--out", required=True)
    q = sub.add_parser("report", help="aggregates only, with bootstrap intervals over games")
    q.add_argument("--rows")
    q.add_argument("--player-rows")
    q.add_argument("--arena")
    q.add_argument("--replay", nargs="*", help="NAME=DIR of replay_analysis runs")
    q.add_argument("--outcomes", help="the outcomes command's directory (with --replay)")
    q.add_argument("--bootstrap", type=int, default=BOOTSTRAP)
    q.add_argument("--out", required=True, help="report.json (private directory; aggregates only)")
    args = p.parse_args(sys.argv[1:] if argv is None else list(argv))
    from duoforge_replay.dataset import refuse_repository
    try:
        refuse_repository(args.out if args.command != "report" else str(Path(args.out).parent))
    except ValueError:
        raise SystemExit(f"--out {args.out} is inside the repository (AGENTS.md)") from None
    commands = {"rows": rows_main, "arena": arena_main, "outcomes": outcomes_main, "report": report_main}
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
