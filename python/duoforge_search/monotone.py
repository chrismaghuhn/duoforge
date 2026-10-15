"""BC6's value under a removed move (#509; README docs/benchmarks/2026-10-15-bc6-monotone): a measurement, no training.

Self-play games are recorded by label (record_game): each step's choices of both seats as the engine's own labels
(positions.slot_label: the move, target and mega flag, or the species a switch brings in), not slot indices, since
removing a move shifts the slots. An edit removes one move of one member (Edit: side, roster index, move) and is built
only
through the engine: the edited setup goes through the engine's setup check (Batch.reset_setups under the game's seed,
so the RNG stream is the original's), the recorded labels are resolved against the engine's offered options
(positions.resolve), and each step's engine events of both seats (privileged.step_events, decision 0007) are compared
with the unedited replay's. Python rewrites no battle bytes and derives no rule. Named refusals (REFUSALS):
setup_refused, removed_move_used (a recorded choice uses the removed move), replay_diverged (the events of a step, or
its offered options, differ).

    python -m duoforge_search.monotone --checkpoint BC6 --teams-from POOL_NET --out DIR
        [--replace detect --part1-rows PART1_ROWS]

Part 2 (--replace detect, the README's "Part 2"): every edit is also built with Detect in the edited move's slot
(Edit.replace), the member keeping its move count; the rows gain the replaced edit's value change and refusal
(REPLACE_REFUSALS) and whether the member carries Protect (the reading's subset), and keep part 1's fields
(PART1_KEYS) unchanged: each game's part-1 fields must equal part 1's rows (games_digest), or the run stops by name
(games_differ). report_detect gives part 2's aggregates and the predeclared reading.

DIR lies outside the repository: rows.jsonl (one row per edit, position and viewing seat) and report.json (the
aggregates, with the conditions: commit, dirty, the library's, the checkpoint's and the pool config's sha256).
"""
import argparse
import hashlib
import json
import math
import os
from dataclasses import dataclass, field

import numpy as np

import duoforge
from duoforge import _layout, data, privileged

from . import positions

C = _layout.CONSTANTS
REFUSALS = ("setup_refused", "removed_move_used", "replay_diverged")
# Part 2: the replaced edit's refusals. detect_not_allowed: the engine's setup check refuses Detect for the member.
REPLACE_REFUSALS = ("detect_not_allowed", "already_detect", "removed_is_detect", "removed_move_used", "replay_diverged")
PART1_KEYS = ("game", "t", "side", "seat", "kind", "member", "species", "move", "category", "protect_like", "refused",
              "dv", "dp")
READING_MIN = 200  # fewer paired edits in the subset (own or mirror): no conclusion (HauptSession, 2026-10-15)
SMALL, LARGE_SHARE, SMALL_SHARE = 0.02, 0.50, 0.25  # |dV_rd| of one point of win probability; the reading's shares
SEED = 0x2026101500000509
BOOTSTRAP_SEED = 0x509
THRESHOLD = 0.01  # one point of win probability (p = (1 + V) / 2), or of the value in the comparison reading
CATEGORIES = {C["DUOFORGE_MOVE_CATEGORY_PHYSICAL"]: "physical", C["DUOFORGE_MOVE_CATEGORY_SPECIAL"]: "special",
              C["DUOFORGE_MOVE_CATEGORY_STATUS"]: "status"}
# A reporting set, not a rule: the split "Protect-like" of the README, resolved through the engine's names.
PROTECT_LIKE = ("protect", "detect", "spikyshield", "kingsshield", "banefulbunker", "silktrap", "burningbulwark",
                "obstruct", "wideguard", "quickguard")
VALUE_CHUNK = 256
_TURN = C["DUOFORGE_BOUNDARY_TURN"]
_TEAM = C["DUOFORGE_CHOICE_TEAM_SELECTION"]


@dataclass(frozen=True)
class Net:
    """A network as the arena loads it: the model, its parameters, its encoder version and feature mask."""
    model: object
    params: object
    encoder: int
    ext: int


@dataclass(frozen=True)
class Edit:
    """One move (id) of the member at roster index `member` of `side` (the setup's member order), removed; or, with
    replace = (move id, pp_max), replaced by that move in the same slot (part 2)."""
    side: int
    member: int
    move: int
    replace: tuple = None


@dataclass
class Walk:
    """A replay: stop (reason, step) where it stopped early, else None; events, per replayed step the engine events of
    both seats; turns, per TURN boundary step the active members (side, slot, member, move) a move of which could be
    removed (at least 2 moves, not fainted); moves, (side, member) -> its move ids; first_use, (side, member, move)
    -> the first step whose recorded choice uses it."""
    stop: tuple = None
    events: list = field(default_factory=list)
    turns: dict = field(default_factory=dict)
    moves: dict = field(default_factory=dict)
    first_use: dict = field(default_factory=dict)


def _key(seed, game, step):
    import jax
    key = jax.random.fold_in(jax.random.PRNGKey(seed & 0xFFFFFFFF), seed >> 32)
    return jax.random.fold_in(jax.random.fold_in(key, game), step)


def _choose(batch, net, key):
    """Both seats' choices sampled from the network's policy (team head at the team preview, pair head at turns),
    as FACTORED_CHOICE (1, 2), with the requested seats' labels."""
    from duoforge_learn import evaluate
    o = evaluate.Observation(batch, net.encoder, net.ext)
    actions, _, _ = net.model.act(net.params, key, o.obs.reshape(2, -1), o.slots.reshape((2,) + o.slots.shape[2:]),
                                  o.mask.reshape((2,) + o.mask.shape[2:]), o.is_team.reshape(-1), greedy=False)
    choices = np.zeros((1, 2), _layout.FACTORED_CHOICE)
    evaluate.choices_of(batch, np.asarray(actions).reshape(1, 2), choices)
    labels = [None, None]
    for side in (0, 1):
        if not batch.requests["requested"][0, side]:
            continue
        d = batch.domains[0, side]
        if int(d["kind"]) == _TEAM:
            labels[side] = {"picks": [int(x) for x in choices["picks"][0, side, :int(d["pick_count"])]]}
        else:
            ik = tuple(int(x) for x in choices["slot"][0, side])
            labels[side] = [dict(x) for x in dict(positions.pairs(batch, 0, side))[ik]]
    return choices, labels


def _query(batch):
    batch.query()
    batch.query_factored()
    return batch.requests["requested"][0] != 0


def record_game(ctx, pool, side0, side1, seed, net, game=0, max_steps=1000):
    """One self-play game of `net` against itself, teams side0 and side1 of pool, the battle seeded with seed: {"teams",
    "seed", "steps" (per step the labels of both seats, None for an unrequested seat), "end" ("terminal", "cut_off"
    or "refused")}. Deterministic in its arguments."""
    steps, end = [], "cut_off"
    with duoforge.Batch(ctx, pool.setups(np.array([side0]), np.array([side1])), 1, seed) as batch:
        for t in range(max_steps):
            if not _query(batch).any():
                end = "terminal"
                break
            choices, labels = _choose(batch, net, _key(seed, game, t))
            steps.append(labels)
            try:
                batch.step_factored(choices)
            except duoforge.DuoforgeError:
                end = "refused"
                break
    return {"teams": [int(side0), int(side1)], "seed": int(seed), "steps": steps, "end": end}


def _setup(pool, game, edit):
    setups = pool.setups(np.array([game["teams"][0]]), np.array([game["teams"][1]])).copy()
    if edit is None:
        return setups
    side = setups[0]["sides"][edit.side]
    member = side["members"][edit.member]
    moves = [member["moves"][j].copy() for j in range(int(member["move_count"]))]
    kept = [x for x in moves if int(x["move_id"]) != edit.move]
    if len(kept) != len(moves) - 1:
        raise ValueError(f"member {edit.member} of side {edit.side} has no move {edit.move} to remove")
    if edit.replace is not None:
        move, pp_max = (int(x) for x in edit.replace)
        if move != edit.move and any(int(x["move_id"]) == move for x in moves):
            raise ValueError(f"member {edit.member} of side {edit.side} already has move {move}")
        j = next(j for j, x in enumerate(moves) if int(x["move_id"]) == edit.move)
        member["moves"][j]["move_id"], member["moves"][j]["pp_max"] = move, pp_max
        side["members"][edit.member] = member
        setups[0]["sides"][edit.side] = side
        return setups
    member["moves"][:] = np.zeros(1, _layout.MOVE_SETUP)
    for j, x in enumerate(kept):
        member["moves"][j] = x
    member["move_count"] = len(kept)
    side["members"][edit.member] = member
    setups[0]["sides"][edit.side] = side
    return setups


def _events_equal(a, b):
    return all(x.tobytes() == y.tobytes() for x, y in zip(a, b))


def _uses(label, ctx, move):
    return any(isinstance(x, dict) and x.get("move") == data.name(ctx, data.TABLE_MOVE, move) for x in label)


def walk(ctx, pool, game, edit=None, reference=None, on_turn=None):
    """The replay of a recorded game, with `edit` applied to its setup (None: unedited). reference: the unedited
    replay's events, compared step by step. on_turn(step, batch): called at each TURN boundary before its step, the
    batch queried. Returns a Walk."""
    out = Walk()
    with duoforge.Batch(ctx, _setup(pool, game, None), 1, game["seed"]) as batch:
        try:
            batch.reset_setups(np.array([0], np.uint32), np.array([0], np.uint32), _setup(pool, game, edit))
        except duoforge.DuoforgeError:
            out.stop = ("detect_not_allowed" if edit is not None and edit.replace is not None else "setup_refused", 0)
            return out
        for t, labels in enumerate(game["steps"]):
            requested = _query(batch)
            choices = np.zeros((1, 2), _layout.FACTORED_CHOICE)
            for side in (0, 1):
                label = labels[side]
                if (label is None) != (not requested[side]):
                    out.stop = ("replay_diverged", t)
                    return out
                if label is None:
                    continue
                if isinstance(label, dict) and "picks" in label:
                    choices["picks"][0, side, :len(label["picks"])] = label["picks"]
                    continue
                try:
                    choices["slot"][0, side] = positions.resolve(batch, 0, side, label)
                except positions.PositionError:
                    if edit is not None and side == edit.side and _uses(label, ctx, edit.move):
                        out.stop = ("removed_move_used", t)
                    else:
                        out.stop = ("replay_diverged", t)
                    return out
            if int(batch.requests["boundary_kind"][0, 0]) == _TURN or int(batch.requests["boundary_kind"][0, 1]) == _TURN:
                out.turns[t] = _actives(batch)
                for side, _, member, _ in out.turns[t]:
                    if (side, member) not in out.moves:
                        out.moves[(side, member)] = _moves_of(batch, side, member)
                        if edit is None:
                            _check_roster(pool, game, side, member, out.moves[(side, member)])
                if on_turn is not None:
                    on_turn(t, batch)
            for side in (0, 1):
                label = labels[side]
                if isinstance(label, list):
                    for slot, x in enumerate(label):
                        if "move" in x and x["move"] != "struggle_or_recharge":
                            member = _occupant(batch, side, slot)
                            out.first_use.setdefault((side, member, data.find(ctx, data.TABLE_MOVE, x["move"])), t)
            step = privileged.step_events(batch, 0, choices[0], rng=None)
            events = step["events"]
            if step["status"] != 0 or events[0] is None:
                out.stop = ("replay_diverged", t)
                return out
            if reference is not None and (t >= len(reference) or not _events_equal(events, reference[t])):
                out.stop = ("replay_diverged", t)
                return out
            out.events.append(events)
            batch.step_factored(choices)
    return out


def _actives(batch):
    """(side, slot, member, move) for every move of every occupied, not fainted active member with at least 2 moves,
    as the engine's observation of its own side shows it."""
    out = []
    for side in (0, 1):
        own = batch.observations[0, side]["sides"][side]
        for slot in range(2):
            occupant = int(own["occupant"][slot])
            if occupant >= int(own["member_count"]):
                continue
            member = own["members"][occupant]
            count = int(member["move_count"])
            if int(member["hp"]) == 0 or count < 2:
                continue
            for j in range(count):
                out.append((side, slot, occupant, int(member["move_ids"][j])))
    return out


def _moves_of(batch, side, member):
    m = batch.observations[0, side]["sides"][side]["members"][member]
    return [int(x) for x in m["move_ids"][:int(m["move_count"])]]


def _occupant(batch, side, slot):
    return int(batch.observations[0, side]["sides"][side]["occupant"][slot])


def _check_roster(pool, game, side, member, moves):
    """The engine's roster index is the setup's member index: the observed moves are the setup's."""
    m = _setup(pool, game, None)[0]["sides"][side]["members"][member]
    if [int(x["move_id"]) for x in m["moves"][:int(m["move_count"])]] != moves:
        raise RuntimeError(f"side {side}: roster index {member} shows moves {moves}, not its setup's")


def _species(pool, game, side, member):
    return int(_setup(pool, game, None)[0]["sides"][side]["members"][member]["species_id"])


class _Values:
    """BC6's values of encoded rows, in padded chunks of VALUE_CHUNK rows (one shape for the value call)."""

    def __init__(self, net):
        self.net = net

    def __call__(self, rows):
        rows = np.asarray(rows, np.float32)
        out = np.zeros(len(rows), np.float32)
        for start in range(0, len(rows), VALUE_CHUNK):
            part = rows[start:start + VALUE_CHUNK]
            padded = np.zeros((VALUE_CHUNK, rows.shape[1]), np.float32)
            padded[:len(part)] = part
            out[start:start + len(part)] = np.asarray(self.net.model.value(self.net.params, padded))[:len(part)]
        return out


def _rows_at(batch, net):
    obs, _, _ = batch.query_encoded(net.encoder, net.ext)
    return np.array(obs[0, 0], copy=True), np.array(obs[0, 1], copy=True)


def _category(ctx, move, protect_ids):
    return CATEGORIES[int(data.move_static(ctx, move)["category"])], move in protect_ids


def protect_ids(ctx):
    """The Protect-like reporting set's move ids in the context, and the names it lacks."""
    ids, missing = set(), []
    for name in PROTECT_LIKE:
        try:
            ids.add(int(data.find(ctx, data.TABLE_MOVE, name)))
        except duoforge.DuoforgeError:
            missing.append(name)
    return ids, missing


def detect_slot(ctx, pool, required=True):
    """(Detect's move id, pp_max) for part 2's replacement: the pp_max copied from the pool's own Detect slots, which
    must all agree (no PP rule is derived here). None, or ValueError when required, if the pool has none."""
    detect = int(data.find(ctx, data.TABLE_MOVE, "detect"))
    pps = set()
    for side in pool.sides:
        for m in side["members"][:int(side["member_count"])]:
            for x in m["moves"][:int(m["move_count"])]:
                if int(x["move_id"]) == detect:
                    pps.add(int(x["pp_max"]))
    if len(pps) > 1:
        raise ValueError(f"the pool's Detect slots have pp_max {sorted(pps)}: no single one to copy")
    if not pps:
        if required:
            raise ValueError("the pool has no Detect slot to copy its pp_max from")
        return None
    return detect, pps.pop()


def replace_refusal(move, have, detect):
    """The replaced edit's refusal known before any build: the edited move is Detect itself, or the member already
    carries Detect (a duplicate move); else None."""
    if move == detect:
        return "removed_is_detect"
    if detect in have:
        return "already_detect"
    return None


def in_subset(move, have, protect):
    """The reading's subset (HauptSession, 2026-10-15): the member carries Protect and the edited move is not Protect."""
    return protect in have and move != protect


def games_digest(rows):
    """game -> sha256 of its rows' part-1 fields (PART1_KEYS) in order: part 2's games must give part 1's."""
    out = {}
    for r in rows:
        h = out.setdefault(r["game"], hashlib.sha256())
        h.update((json.dumps({k: r[k] for k in PART1_KEYS}, sort_keys=True) + "\n").encode("utf-8"))
    return {g: h.hexdigest() for g, h in out.items()}


def measure_game(ctx, pool, game, net, game_index=0, protect=None, replace=None):
    """The rows of one recorded game: per TURN boundary position, per edit of an active member's move and per viewing
    seat, the value change (dv on the value scale, dp = dv / 2 on the win-probability scale) or its refusal. With
    replace = (Detect's id, pp_max) (part 2), each edit is also built with Detect in the move's slot: the row adds
    dv_replaced, refused_replaced, dv_rd = dv_replaced - dv where both were built, carries_protect and subset."""
    protect = protect_ids(ctx)[0] if protect is None else protect
    protect_id = int(data.find(ctx, data.TABLE_MOVE, "protect")) if replace is not None else None
    values = _Values(net)
    base_rows = {}
    base = walk(ctx, pool, game, on_turn=lambda t, b: base_rows.__setitem__(t, _rows_at(b, net)))
    if base.stop is not None:
        raise RuntimeError(f"the unedited replay of a recorded game stopped: {base.stop}")
    steps = sorted(base_rows)
    base_v = dict(zip(steps, values([r for t in steps for r in base_rows[t]]).reshape(-1, 2))) if steps else {}
    edits = sorted({Edit(side, member, move) for t in base.turns for side, _, member, move in base.turns[t]},
                   key=lambda e: (e.side, e.member, e.move))
    for edit in edits:
        at = [t for t in steps if any((s, mb, m) == (edit.side, edit.member, edit.move)
                                      for s, _, mb, m in base.turns[t])]
        edited_rows = {}
        w = walk(ctx, pool, game, edit=edit, reference=base.events,
                 on_turn=lambda t, b: edited_rows.__setitem__(t, _rows_at(b, net)) if t in at else None)
        built = [t for t in at if t in edited_rows]
        v = dict(zip(built, values([r for t in built for r in edited_rows[t]]).reshape(-1, 2))) if built else {}
        if replace is not None:
            have = base.moves[(edit.side, edit.member)]
            before = replace_refusal(edit.move, have, int(replace[0]))
            v2, w2 = {}, None
            if before is None:
                replaced = Edit(edit.side, edit.member, edit.move, replace=tuple(int(x) for x in replace))
                rows2 = {}
                w2 = walk(ctx, pool, game, edit=replaced, reference=base.events,
                          on_turn=lambda t, b: rows2.__setitem__(t, _rows_at(b, net)) if t in at else None)
                built2 = [t for t in at if t in rows2]
                if built2:
                    v2 = dict(zip(built2, values([r for t in built2 for r in rows2[t]]).reshape(-1, 2)))
            subset = in_subset(edit.move, have, protect_id)
        category, protect_like = _category(ctx, edit.move, protect)
        for t in at:
            for seat in (0, 1):
                row = {"game": game_index, "t": t, "side": edit.side, "seat": seat,
                       "kind": "own" if seat == edit.side else "mirror", "member": edit.member,
                       "species": _species(pool, game, edit.side, edit.member), "move": edit.move,
                       "category": category, "protect_like": protect_like, "refused": None, "dv": None, "dp": None}
                if t in v:
                    dv = float(v[t][seat]) - float(base_v[t][seat])
                    row["dv"], row["dp"] = dv, dv / 2
                else:
                    row["refused"] = w.stop[0] if w.stop is not None else "replay_diverged"
                if replace is not None:
                    row.update({"carries_protect": protect_id in have, "subset": subset, "refused_replaced": None,
                                "dv_replaced": None, "dv_rd": None})
                    if t in v2:
                        row["dv_replaced"] = float(v2[t][seat]) - float(base_v[t][seat])
                        if row["dv"] is not None:
                            row["dv_rd"] = row["dv_replaced"] - row["dv"]
                    else:
                        row["refused_replaced"] = before or (w2.stop[0] if w2.stop is not None else "replay_diverged")
                yield row


def wrong_way(row, scale="p"):
    """Whether a built row moved the wrong way: an own edit raising X's value, a mirror edit lowering it, by more than
    THRESHOLD on the win-probability scale (the README's reading) or, scale "value", on the value scale (the
    comparison reading)."""
    d = row["dp"] if scale == "p" else row["dv"]
    return d > THRESHOLD if row["kind"] == "own" else d < -THRESHOLD


def wilson(k, n, z=1.959963984540054):
    """The Wilson score interval of k successes in n trials."""
    if n == 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def _cluster(rows, bootstrap, seed, scale):
    by_game = {}
    for r in rows:
        k, n = by_game.get(r["game"], (0, 0))
        by_game[r["game"]] = (k + int(wrong_way(r, scale)), n + 1)
    games = sorted(by_game)
    if not games:
        return None
    k = np.array([by_game[g][0] for g in games], np.float64)
    n = np.array([by_game[g][1] for g in games], np.float64)
    draws = np.random.default_rng(seed).integers(0, len(games), size=(bootstrap, len(games)))
    rates = k[draws].sum(axis=1) / n[draws].sum(axis=1)
    return float(np.percentile(rates, 2.5)), float(np.percentile(rates, 97.5))


def _rate(rows, bootstrap, seed, scale="p"):
    built = [r for r in rows if r["refused"] is None]
    wrong = sum(wrong_way(r, scale) for r in built)
    out = {"built": len(built), "wrong": wrong, "rate": wrong / len(built) if built else None,
           "wilson_95": wilson(wrong, len(built)), "cluster_95": _cluster(built, bootstrap, seed, scale)}
    return out


QUANTILES = (1, 5, 25, 50, 75, 95, 99)


def report(rows, bootstrap=2000, seed=BOOTSTRAP_SEED):
    """The README's aggregates of measured rows."""
    rows = list(rows)
    out = {"rows": len(rows), "refused": {}}
    for r in rows:
        if r["refused"] is not None:
            out["refused"][r["refused"]] = out["refused"].get(r["refused"], 0) + 1
    shares = {}
    for kind in ("own", "mirror"):
        part = [r for r in rows if r["kind"] == kind]
        out[kind] = _rate(part, bootstrap, seed)
        out[kind]["comparison_value_scale"] = _rate(part, bootstrap, seed, scale="value")
        dps = [r["dp"] for r in part if r["refused"] is None]
        out[kind]["dp_quantiles"] = {str(q): float(np.percentile(dps, q)) for q in QUANTILES} if dps else None
        groups = {c: [r for r in part if r["category"] == c] for c in ("physical", "special", "status")}
        groups["protect_like"] = [r for r in part if r["protect_like"]]
        out[kind]["by_category"] = {c: _rate(g, bootstrap, seed) for c, g in groups.items()}
        out[kind]["by_seat"] = {str(s): _rate([r for r in part if r["seat"] == s], bootstrap, seed) for s in (0, 1)}
        shares[kind] = {c: (sum(r["refused"] == "removed_move_used" for r in g) / len(g) if g else None)
                        for c, g in groups.items()}
    out["removed_move_used_share"] = shares
    return out


def _bootstrap_stat(values_by_game, bootstrap, seed, stat):
    games = sorted(values_by_game)
    if not games:
        return None
    draws = np.random.default_rng(seed).integers(0, len(games), size=(bootstrap, len(games)))
    stats = [stat(np.concatenate([values_by_game[games[g]] for g in draw])) for draw in draws]
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def _detect_part(rows, bootstrap, seed):
    """Part 2's aggregates of one group's paired rows of one kind (own or mirror)."""
    paired = [r for r in rows if r["dv_rd"] is not None]
    out = {"paired": len(paired)}
    if not paired:
        return out
    a = np.abs(np.array([r["dv_rd"] for r in paired]))
    by_game = {}
    for r in paired:
        by_game.setdefault(r["game"], []).append(abs(r["dv_rd"]))
    by_game = {g: np.array(x) for g, x in by_game.items()}
    above = int((a > SMALL).sum())
    shares = {g: (x > SMALL).astype(np.float64) for g, x in by_game.items()}
    out["abs_dv_rd"] = {"quantiles": {str(q): float(np.percentile(a, q)) for q in QUANTILES},
                        "median": float(np.median(a)), "mean": float(a.mean()),
                        "median_cluster_95": _bootstrap_stat(by_game, bootstrap, seed, np.median),
                        "mean_cluster_95": _bootstrap_stat(by_game, bootstrap, seed, np.mean)}
    out["share_above"] = {"threshold": SMALL, "above": above, "share": above / len(paired),
                          "wilson_95": wilson(above, len(paired)),
                          "cluster_95": _bootstrap_stat(shares, bootstrap, seed, np.mean)}
    signed = np.array([r["dv_rd"] for r in paired])
    out["signed_dv_rd_quantiles"] = {str(q): float(np.percentile(signed, q)) for q in QUANTILES}
    # descriptive only: part 1's wrong way on the same rows, removed and replaced, and their paired difference
    removed = np.array([wrong_way(r) for r in paired], np.float64)
    replaced = np.array([wrong_way(dict(r, dp=r["dv_replaced"] / 2)) for r in paired], np.float64)
    diff = {}
    for r, x, y in zip(paired, removed, replaced):
        diff.setdefault(r["game"], []).append(x - y)
    out["wrong_way"] = {"removed": float(removed.mean()), "replaced": float(replaced.mean()),
                        "difference": float((removed - replaced).mean()),
                        "difference_cluster_95": _bootstrap_stat({g: np.array(x) for g, x in diff.items()}, bootstrap,
                                                                 seed, np.mean)}
    return out


def reading(subset):
    """The predeclared reading (README "Part 2", HauptSession 2026-10-15) of the subset's own and mirror parts."""
    parts = [subset[kind] for kind in ("own", "mirror")]
    if any(p["paired"] < READING_MIN for p in parts):
        return "no_conclusion_too_few"
    if any(p["abs_dv_rd"]["median"] > SMALL or p["share_above"]["share"] > LARGE_SHARE for p in parts):
        return "missing_slot_moves_value"
    if all(p["abs_dv_rd"]["median"] <= SMALL and p["share_above"]["share"] <= SMALL_SHARE for p in parts):
        return "missing_slot_not_driving"
    return "no_conclusion"


def report_detect(rows, bootstrap=2000, seed=BOOTSTRAP_SEED):
    """Part 2's aggregates: per group (the subset; the other edits, descriptive only) and kind, the paired rows'
    |dV_rd| and the share above SMALL; the replaced edits' refusals per group; the reading, on the subset only."""
    rows = list(rows)
    out = {"refused_replaced": {"subset": {}, "other": {}}}
    for r in rows:
        if r["refused_replaced"] is not None:
            group = out["refused_replaced"]["subset" if r["subset"] else "other"]
            group[r["refused_replaced"]] = group.get(r["refused_replaced"], 0) + 1
    for group, keep in (("subset", True), ("other", False)):
        part = [r for r in rows if r["subset"] == keep]
        out[group] = {kind: _detect_part([r for r in part if r["kind"] == kind], bootstrap, seed)
                      for kind in ("own", "mirror")}
        out[group]["by_category"] = {
            c: {kind: _detect_part([r for r in part if r["kind"] == kind and (r["category"] == c if c != "protect_like"
                                                                             else r["protect_like"])], bootstrap, seed)
                for kind in ("own", "mirror")} for c in ("physical", "special", "status", "protect_like")}
    out["reading"] = reading(out["subset"])
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m duoforge_search.monotone", description=__doc__.split("\n\n")[0])
    p.add_argument("--checkpoint", required=True, help="BC6")
    p.add_argument("--teams-from", required=True, help="a pool network: its config's teams are the ladder's pool")
    p.add_argument("--out", required=True, help="the output directory, outside the repository")
    p.add_argument("--pairs", type=int, default=50, help="team pairs, each played with both seat assignments")
    p.add_argument("--seed", type=lambda text: int(text, 0), default=SEED)
    p.add_argument("--max-steps", type=int, default=1000)
    p.add_argument("--bootstrap", type=int, default=2000)
    p.add_argument("--replace", choices=("detect",), default=None,
                   help="part 2: also build every edit with Detect in the edited move's slot (README, Part 2)")
    p.add_argument("--part1-rows", default=None,
                   help="part 1's rows.jsonl: with --replace, each game's part-1 fields must equal them (games_differ)")
    args = p.parse_args(argv)
    if (args.replace is None) != (args.part1_rows is None):
        raise SystemExit("--replace and --part1-rows go together")
    from duoforge_learn import checkpoint as ck
    from . import arena, foe_arena
    repo = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    out_dir = os.path.realpath(args.out)
    if out_dir == repo or out_dir.startswith(repo + os.sep):
        raise SystemExit("--out must lie outside the repository (the rows stay private)")
    library = os.environ.get("DUOFORGE_LIBRARY")
    if not library:
        raise SystemExit("DUOFORGE_LIBRARY must name the library (its sha256 is part of the report)")
    params, config = ck.load_trained(args.checkpoint)
    net = Net(ck.trained_model(config, params), params, ck.encoder_of(config), ck.ext_supported_of(config))
    _, teams_config = ck.load_trained(args.teams_from)
    if teams_config.get("data", {}).get("kind") != "pool":
        raise SystemExit("--teams-from's teams are no pool (its config's data kind must be pool)")
    os.makedirs(out_dir, exist_ok=True)
    conditions = {"commit": os.environ.get("DUOFORGE_COMMIT"), "dirty": os.environ.get("DUOFORGE_DIRTY", "true") == "true",
                  "sha256": {"library": arena._sha256(library), "checkpoint": arena._sha256(args.checkpoint),
                             "teams_from": arena._sha256(args.teams_from)},
                  "seed": args.seed, "pairs": args.pairs, "max_steps": args.max_steps, "threshold": THRESHOLD,
                  "bootstrap": args.bootstrap, "bootstrap_seed": BOOTSTRAP_SEED, "encoder": net.encoder,
                  "replace": args.replace}
    part1 = None
    if args.part1_rows is not None:
        with open(args.part1_rows, encoding="utf-8") as f:
            part1 = games_digest(json.loads(line) for line in f)
        conditions["sha256"]["part1_rows"] = arena._sha256(args.part1_rows)
    rows_path = os.path.join(out_dir, "rows.jsonl")
    ends, written = {}, set()
    with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, open(rows_path, "w", encoding="utf-8") as f:
        pool = duoforge.teams.load(ctx, teams_config["teams"]["ids"])
        protect, missing = protect_ids(ctx)
        conditions["protect_like_missing"] = missing
        replace = None
        if args.replace is not None:
            try:
                replace = detect_slot(ctx, pool)
            except ValueError as err:
                raise SystemExit(str(err)) from None
            conditions["replace_slot"] = {"move": replace[0], "pp_max": replace[1]}
        games = foe_arena.games(len(pool.ids), args.pairs, args.seed)
        for g, row in enumerate(games):
            side0, side1 = (int(row["side0"]), int(row["side1"])) if row["learner_seat"] == 0 else \
                (int(row["side1"]), int(row["side0"]))
            game = record_game(ctx, pool, side0, side1, (args.seed + g) & 0xFFFFFFFFFFFFFFFF, net, game=g,
                               max_steps=args.max_steps)
            ends[game["end"]] = ends.get(game["end"], 0) + 1
            if game["end"] == "refused":
                continue
            rows = list(measure_game(ctx, pool, game, net, game_index=g, protect=protect, replace=replace))
            if part1 is not None and games_digest(rows).get(g) != part1.get(g):
                raise SystemExit(f"games_differ: game {g}'s part-1 rows are not part 1's")
            for r in rows:
                f.write(json.dumps(r) + "\n")
                written.add(r["game"])
            f.flush()
    with open(rows_path, encoding="utf-8") as f:
        rep = report((json.loads(line) for line in f), bootstrap=args.bootstrap)
    rep["games"] = {"count": len(games), "ends": ends}
    rep["conditions"] = conditions
    if args.replace is not None:
        if written != set(part1):
            raise SystemExit("games_differ: the games with rows are not part 1's")
        with open(rows_path, encoding="utf-8") as f:
            rep["detect"] = report_detect((json.loads(line) for line in f), bootstrap=args.bootstrap)
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, sort_keys=True)
    print(json.dumps({k: rep[k] for k in ("games", "refused")}, sort_keys=True))
    print(json.dumps({k: {x: rep[k][x] for x in ("built", "wrong", "rate", "wilson_95")} for k in ("own", "mirror")}))


if __name__ == "__main__":
    main()
