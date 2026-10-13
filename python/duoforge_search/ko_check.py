"""The KO check (#440, owner 2026-10-13): over every searched decision of the arena's battle logs, in both directions.

1. Own KOs: had we a pair that knocks out a foe Pokemon this turn, surely or likely? Was it played, and was it among
   the search's own candidates?
2. Foe KOs: had the foe a pair that knocks out one of ours against what we were about to play? Did the search know it
   (its foe columns), and did we answer it (Protect, a switch, a faster KO of our own)?

A missed KO falls in one of two groups: "not among the candidates" (the width, ladder step 2w) or "among the
candidates, not chosen" (the evaluation or the rule: 2d, 2e, 2l).

Whether a pair knocks out is the engine's answer, never a rule here: each probe is a search leaf (Batch.expand) of
the decision's own worlds, its one turn stepped by the engine, and a KO is a member whose public HP reached 0 during
that turn (the viewer's observation after the leaf against the one at the root). The probes are the search's own
candidates, the played and the raw pair, and every legal option of each slot with its likeliest partner
(lookahead.select_slots); on the foe side the search's foe columns and every foe slot option with its likeliest partner
under the foe model, per world.

    python -m duoforge_search.ko_check --logs DIR --team PASTE --checkpoint MAIN --out DIR [--step 0]
        [--samples-per-world 4] [--limit N]

The battle logs (match ids) and the per-decision rows stay private, outside the repository; the report holds counts.
"""
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from . import lookahead
from .errors import SearchError

LIKELY, SURE = 0.5, 0.9  # a KO probability at least this is "likely" / "sure" (fixed before the first run)
SAMPLES_PER_WORLD = 4  # engine samples (RNG reseeds) of each probe in each world


def fainted(sides, seen):
    """The members of each side whose public HP is 0: sides (..., 2) of the OBSERVATION's sides, seen the HP kinds that
    state an HP (exact, percent). (..., 2) int."""
    members = sides["members"]
    return ((members["hp"] == 0) & np.isin(members["hp_kind"], seen)).sum(axis=-1)


def probe_plan(own, foe_sets, samples, s):
    """(world, own index, foe pair, sample) of every probe leaf, int64 arrays in that order: each own pair against each
    of its world's foe pairs, `samples` times per world; sample r of world w is w + r * s (r = 0 is the search's own
    leaf seed)."""
    w, i, j, sample = [], [], [], []
    for world, columns in enumerate(foe_sets):
        for index in range(len(own)):
            for column in columns:
                for r in range(samples):
                    w.append(world)
                    i.append(index)
                    j.append(int(column))
                    sample.append(world + r * s)
    return tuple(np.asarray(x, np.int64) for x in (w, i, j, sample))


def probe(search, p, key, own, foe_columns, samples=SAMPLES_PER_WORLD):
    """The KO probes of the decision `search` (honest.Honest) just searched for seat p, on its worlds as they stand.
    own: the own pairs to probe (flat indices); foe_columns: the search's foe pairs per world (its record's foe_pairs).
    Returns a dict: the own pairs; per world the foe pairs probed; own_ko and foe_ko (W, K, max columns) means over the
    samples of "a foe member / an own member went to 0 HP this turn" (NaN where a world has fewer columns or every
    sample was refused); q (W, max columns), the foe model's probability of each column renormalized in its world;
    refused, the leaves the engine refused."""
    from duoforge import _layout
    C = _layout.CONSTANTS
    seen = (C["DUOFORGE_HP_EXACT"], C["DUOFORGE_HP_PERCENT"])
    s, foe = search.s, 1 - p
    search.worlds.query()
    root = fainted(search.worlds.observations[:, p]["sides"], seen)  # (W, 2): public, the same in every world
    if not (root == root[0]).all():
        raise SearchError("the worlds' public faint counts differ")
    pp, _, _, masks, _, _, _ = search._world_policy()  # leaves the worlds' domains as the search's leaves need them
    asked = bool(search.worlds.requests[0, foe]["requested"])
    foe_sets, q = [], []
    for w in range(s):
        if asked:
            wide, _ = lookahead.select_slots(pp[w, foe], masks[w, foe], 1)
            columns = np.union1d(wide, np.asarray(foe_columns[w], np.int64))
            probabilities = np.exp(pp[w, foe][columns].astype(np.float64))
            q.append(probabilities / probabilities.sum())
        else:
            columns, q = np.array([lookahead.NO_FOE], np.int64), q + [np.ones(1)]
        foe_sets.append(columns)
    own = np.asarray(own, np.int64)
    w, i, j, sample = probe_plan(own, foe_sets, samples, s)
    total = w.size
    choices = np.zeros((total, 2), _layout.FACTORED_CHOICE)
    choices["slot"][:, p, 0], choices["slot"][:, p, 1] = np.divmod(own[i], lookahead.OPTIONS)
    named = j != lookahead.NO_FOE
    choices["slot"][named, foe, 0], choices["slot"][named, foe, 1] = np.divmod(j[named], lookahead.OPTIONS)
    own_hit, foe_hit = np.zeros(total, bool), np.zeros(total, bool)
    refused = np.zeros(total, bool)
    keys, viewers = np.full(s, key, np.uint64), np.full(s, p, np.uint8)
    leaves = search.leaves
    for start in range(0, total, leaves.envs):
        end = min(total, start + leaves.envs)
        _, step, _, _, _ = leaves.expand(search.worlds, search.encoder, search.ext_supported, search.seed, keys,
                                         viewers, w[start:end].astype(np.uint32), sample[start:end].astype(np.uint32),
                                         choices[start:end])
        step = np.array(step, copy=True)
        leaves.query()
        after = fainted(leaves.observations[:end - start, p]["sides"], seen)
        refused[start:end] = step != 0
        own_hit[start:end] = after[:, foe] > root[0, foe]
        foe_hit[start:end] = after[:, p] > root[0, p]
    width = max(len(c) for c in foe_sets)
    shape = (s, own.size, width)
    sums = {name: np.zeros(shape) for name in ("own", "foe", "n")}
    position = np.concatenate([np.searchsorted(foe_sets[world], j[w == world]) for world in range(s)])  # w-major
    cell, ok = (w, i, position), ~refused
    np.add.at(sums["own"], cell, own_hit & ok)
    np.add.at(sums["foe"], cell, foe_hit & ok)
    np.add.at(sums["n"], cell, ok)
    with np.errstate(invalid="ignore", divide="ignore"):
        own_ko = np.where(sums["n"] > 0, sums["own"] / sums["n"], np.nan)
        foe_ko = np.where(sums["n"] > 0, sums["foe"] / sums["n"], np.nan)
    q_padded = np.zeros((s, width))
    for world in range(s):
        q_padded[world, :len(q[world])] = q[world]
    return {"own": own.tolist(), "foe_sets": [c.tolist() for c in foe_sets], "own_ko": own_ko, "foe_ko": foe_ko,
            "q": q_padded, "refused": int(refused.sum()), "leaves": int(total)}


def summarize(probes, weights):
    """Per own pair: ko, the probability of a foe KO this turn under the foe model (worlds by weight, columns by q);
    threat, the probability of losing a member against the foe's worst pair (per world the column with the highest
    KO mean, worlds by weight), with that column per world."""
    weights = np.asarray(weights, np.float64)
    own_ko, foe_ko, q = probes["own_ko"], probes["foe_ko"], probes["q"]
    ko = np.einsum("w,wkj,wj->k", weights, np.nan_to_num(own_ko), q)
    worst = np.nanargmax(np.where(np.isnan(foe_ko), -1.0, foe_ko), axis=2)  # (W, K)
    per_world = np.take_along_axis(np.nan_to_num(foe_ko), worst[:, :, None], axis=2)[:, :, 0]
    threat = weights @ per_world
    worst_pairs = np.array([[probes["foe_sets"][w][worst[w, k]] for k in range(worst.shape[1])]
                            for w in range(worst.shape[0])])
    return {"ko": ko, "threat": threat, "worst": worst_pairs, "worst_ko": per_world}


def classify(own, ko, threat, candidates, played, raw, threshold, worst=None, worst_ko=None, foe_columns=None,
             weights=None):
    """One decision's KO facts at a threshold, as plain values. own: the probed pairs, ko and threat per own pair
    (summarize); candidates: the search's own candidates; played: the pair played; raw: the raw top pair.

    own side: available (some probed pair reaches the threshold), played (the played pair does), and for a missed one
    "not_candidate" (no candidate reaches it) or "candidate_not_chosen".
    foe side: threatened (the raw pair loses a member at the threshold), answered (the played pair stays below it),
    and for an unanswered one "unavoidable" (no probed pair stays below), "not_candidate" (none of the candidates
    does) or "candidate_not_chosen"; known: the weight share of the threatening worlds whose worst foe pair is a
    column of the search (needs worst, worst_ko, foe_columns, weights)."""
    index = {pair: k for k, pair in enumerate(own)}
    for pair in [played, raw, *candidates]:
        if pair not in index:
            raise ValueError(f"pair {pair} was not probed")
    ko, threat = np.asarray(ko), np.asarray(threat)
    cand = np.array([index[c] for c in candidates])
    out = {"own": {"available": bool(ko.max() >= threshold), "played": bool(ko[index[played]] >= threshold)},
           "foe": {"threatened": bool(threat[index[raw]] >= threshold),
                   "answered": bool(threat[index[played]] < threshold)}}
    if out["own"]["available"] and not out["own"]["played"]:
        out["own"]["missed"] = "candidate_not_chosen" if (ko[cand] >= threshold).any() else "not_candidate"
    if out["foe"]["threatened"] and not out["foe"]["answered"]:
        if not (threat < threshold).any():
            out["foe"]["missed"] = "unavoidable"
        else:
            out["foe"]["missed"] = "candidate_not_chosen" if (threat[cand] < threshold).any() else "not_candidate"
    if out["foe"]["threatened"] and worst is not None:
        k = index[raw]
        hot = np.asarray(worst_ko)[:, k] >= threshold
        mass = np.asarray(weights)[hot]
        known = [worst[w, k] in set(foe_columns[w]) for w in np.flatnonzero(hot)]
        out["foe"]["known"] = float(mass @ np.asarray(known, float) / mass.sum()) if mass.sum() > 0 else None
    return out


# --- the battle logs ---------------------------------------------------------------------------------------------

class _Capture:
    """The searcher of a LiveSearch, keeping the records of its last decide() (the live Outcome keeps only the choice)."""

    def __init__(self, searcher):
        self.searcher, self.records = searcher, None

    def __getattr__(self, name):
        return getattr(self.searcher, name)

    def decide(self, *args, **kwargs):
        actions, records = self.searcher.decide(*args, **kwargs)
        self.records = records
        return actions, records


class Refused(Exception):
    """A game the replay does not follow, named (its reason is counted)."""


def room_of(path):
    """The battle room of a log file battle-<format>-<number>-<bot>.jsonl."""
    parts = Path(path).stem.split("-")
    if len(parts) < 4 or parts[0] != "battle":
        raise Refused("file_name")
    return "-".join(parts[:3])


def pair_texts(game, policy):
    """{choice text: flat pair index} of the allowed pairs of the game's current request (the texts the bot sends)."""
    from duoforge import features
    from duoforge_live import options
    observation = game.tracker.observation()
    domain, lists = game.tracker.domain()
    _, _, pair_mask = features.encode(observation, domain, game.tracker.observation_ext(),
                                      getattr(policy, "ext_supported", 0))
    n = pair_mask.shape[1]
    if n != lookahead.OPTIONS:
        raise SearchError(f"a pair mask of {n} options, the search's flat pairs have {lookahead.OPTIONS}")
    return {options.pair_text(lists[0][a], lists[1][b]): int(a * n + b)
            for a, b in zip(*np.nonzero(np.asarray(pair_mask, bool)))}


def replay(path, data, policy, live, team_text, episode, budget=1e9):
    """The searched turn decisions of one battle log, replayed: yields (game, log record, search record) after each
    decision point's lines are fed and the search (live, a LiveSearch whose searcher is a _Capture) has decided it.
    The lines between two decision records are fed as one batch, the previous choice accepted first, as the bot does.
    Refused (named) for a log the replay cannot follow: a fallback, a rejected choice, a reconnect's replayed log."""
    from duoforge_live.client import _room_line
    from duoforge_live.game import Game
    from duoforge_live.lines import line_kind
    room = room_of(path)
    with open(path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    game = Game(data, policy, team_text, search=live, room=room, episode=episode)
    batch, pending, inits = [], None, 0
    for record in records:
        if "in" in record:
            line = record["in"]
            if line_kind(line) == "sentchoice":
                continue
            if line.startswith("|init|battle"):
                inits += 1
                if inits > 1:
                    raise Refused("resync")
            batch.append(line)
            continue
        if "fallback" in record:
            raise Refused("fallback")
        if "rejected" in record or "unavailable" in record:
            raise Refused("rejected")
        if "decision" not in record:
            continue
        lines = [line for line in batch if not line.startswith("|error|")]
        batch = []
        if pending is not None and not all(_room_line(line) for line in lines):
            game.accepted(pending)
        game.feed(lines)
        if not game.asked():
            raise Refused("not_asked")
        live.searcher.records = None
        game.candidates(budget)
        pending = record["sent"]
        outcome = game.outcomes[-1] if game.outcomes else None
        if outcome is not None and outcome.cause == "searched" and not game.request.get("teamPreview"):
            yield game, record, live.searcher.records[0]


def decision_row(game, policy, live, record, searched, samples, thresholds=(LIKELY, SURE), played_from="log"):
    """The KO facts of one replayed searched decision (private row: no ids). played_from: "log", the pair the bot sent
    (the baseline), or "search", the replayed search's own choice (an arm on the logged games)."""
    if played_from not in ("log", "search"):
        raise ValueError(f"played_from must be log or search (got {played_from!r})")
    search = live.searcher.searcher
    p = int(searched["seat"])
    texts = pair_texts(game, policy)
    if record["sent"] not in texts:
        raise Refused("sent_not_allowed")
    sent, candidates = texts[record["sent"]], [int(x) for x in searched["own_pairs"]]
    raw, chosen = int(searched["raw"]), int(searched["choice"])
    played = sent if played_from == "log" else chosen
    roots = live.roots
    obs, slots, pairs = roots.query_encoded(search.encoder, search.ext_supported)
    logp, _, _ = search._policy(obs[:1, p], slots[:1, p], pairs[:1, p])
    legal = np.asarray(pairs[0, p], bool).reshape(-1) & search._engine_pairs(p).reshape(-1)
    wide, _ = lookahead.select_slots(logp[0], legal, 1)
    own = sorted(set(wide.tolist()) | set(candidates) | {sent, raw, chosen})
    probes = probe(search, p, int(searched["key"]), own, searched["foe_pairs"], samples)
    facts = summarize(probes, searched["weights"])
    row = {"turn": int(game.tracker.observation()["turn"]), "played_is_search": sent == chosen, "played": played_from,
           "k": len(candidates), "probed": len(own), "leaves": probes["leaves"], "refused": probes["refused"],
           "ko_played": float(facts["ko"][own.index(played)]), "ko_best": float(facts["ko"].max()),
           "threat_raw": float(facts["threat"][own.index(raw)]),
           "threat_played": float(facts["threat"][own.index(played)])}
    for threshold in thresholds:
        row[str(threshold)] = classify(own, facts["ko"], facts["threat"], candidates, played, raw, threshold,
                                       facts["worst"], facts["worst_ko"], searched["foe_pairs"], searched["weights"])
    return row


def aggregate(rows, thresholds=(LIKELY, SURE)):
    """The counts of the report: per threshold and side, the decisions in each group."""
    out = {"decisions": len(rows), "played_is_search": sum(r["played_is_search"] for r in rows)}
    for threshold in thresholds:
        own, foe = Counter(), Counter()
        known = []
        for r in rows:
            facts = r[str(threshold)]
            own["available"] += facts["own"]["available"]
            own["played"] += facts["own"]["available"] and facts["own"]["played"]
            if "missed" in facts["own"]:
                own[facts["own"]["missed"]] += 1
            foe["threatened"] += facts["foe"]["threatened"]
            foe["answered"] += facts["foe"]["threatened"] and facts["foe"]["answered"]
            if "missed" in facts["foe"]:
                foe[facts["foe"]["missed"]] += 1
            if facts["foe"].get("known") is not None:
                known.append(facts["foe"]["known"])
        out[str(threshold)] = {"own": dict(own), "foe": dict(foe),
                               "foe_known_mean": float(np.mean(known)) if known else None}
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m duoforge_search.ko_check", description=__doc__.split("\n\n")[0])
    p.add_argument("--logs", required=True, help="a directory of the arena's battle logs (private)")
    p.add_argument("--team", required=True, help="our team's paste, the one the logged games played")
    p.add_argument("--checkpoint", required=True, help="the live network (BC6)")
    p.add_argument("--foe-net", default=None, help="the foe model (default: the checkpoint itself)")
    p.add_argument("--step", default="0", help="the ladder step whose search is replayed (ladder.STEPS)")
    p.add_argument("--samples-per-world", type=int, default=SAMPLES_PER_WORLD)
    p.add_argument("--limit", type=int, default=None, help="at most this many log files (a smoke run)")
    p.add_argument("--out", required=True, help="the report directory, outside the repository")
    args = p.parse_args(argv)
    from duoforge_replay.dataset import refuse_repository
    try:
        refuse_repository(args.out)  # the rows come from logs with match ids (AGENTS.md)
    except ValueError as err:
        raise SystemExit(str(err)) from None
    if args.samples_per_world < 1:
        raise SystemExit("--samples-per-world must be at least 1")
    from . import ladder
    try:
        settings = ladder.step_settings(args.step)
    except ValueError as err:
        raise SystemExit(str(err)) from None
    from duoforge_live import data, pkmn_arena, policy, search as live_search
    team_text = Path(args.team).read_text(encoding="utf-8")
    files = sorted(Path(args.logs).glob("battle-*.jsonl"))[:args.limit]
    if not files:
        raise SystemExit(f"no battle logs in {args.logs}")
    foe_path = args.foe_net or args.checkpoint
    net, tables = policy.load(args.checkpoint), data.for_checkpoint(args.checkpoint)
    live = live_search.load(args.checkpoint, settings=settings, foe_net=foe_path,
                            foe_net_sha256=pkmn_arena.sha256_of(foe_path))
    live.searcher = _Capture(live.searcher)
    os.makedirs(args.out, exist_ok=True)
    rows, games, refused = [], Counter(), Counter()
    try:
        with open(os.path.join(args.out, "decisions.jsonl"), "w", encoding="utf-8") as f:
            for episode, path in enumerate(files):
                first = _first_request(path)
                if first is None or not pkmn_arena.request_matches(first.get("side", {}).get("pokemon", []),
                                                                     team_text):
                    refused["other_team"] += 1
                    continue
                try:
                    for game, record, searched in replay(path, tables, net, live, team_text, episode):
                        row = decision_row(game, net, live, record, searched, args.samples_per_world,
                                           played_from="log" if args.step == "0" else "search")
                        rows.append(row)
                        f.write(json.dumps(row) + "\n")
                    games["followed"] += 1
                except Refused as err:
                    refused[str(err)] += 1
                print(f"{episode + 1}/{len(files)} games, {len(rows)} decisions", file=sys.stderr, flush=True)
    finally:
        live.close()
    report = {"step": args.step, "played": "log" if args.step == "0" else "search", "settings": {k: v for k, v in settings.items() if k != "foe_net"},
              "samples_per_world": args.samples_per_world, "thresholds": {"likely": LIKELY, "sure": SURE},
              "games": {"files": len(files), **games, "refused": dict(refused)}, **aggregate(rows)}
    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(json.dumps(report, indent=1))
    return 0


def _first_request(path):
    """The first request of a battle log (its side's sets), or None."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            text = record.get("in", "")
            if text.startswith("|request|"):
                request = json.loads(text[len("|request|"):])
                if request.get("side"):
                    return request
    return None


if __name__ == "__main__":
    sys.exit(main())
