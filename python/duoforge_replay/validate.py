"""Validation of the Bo1 belief (M11 Bo1 spec section 6), aggregates only.

(a) sets(): on the test-split games with two sheets, the sets drawn from the log alone (sheets dropped) against the
    true sheets, per member: the move set, the unseen moves, the item, ability and nature where the log did not
    reveal them, and the stat points as the prior assigns them. Replays never show stat points, the sheets neither:
    the true spread is unknown, so the measure is whether the drawn set reaches the same prior key level and the same
    prior stat points as the true set (prior_level.same, prior_points.same), not a stat point distance.
(b) compare_rows(): a sheet build and a drop_sheets build of the same games, row by row (replay, side, point): which
    rows both have, which observation field groups differ, the overlap of the legal pairs, the agreement of labels.

No report names a replay, a player or a game: counts and shares only. Outputs are refused inside the repository.
"""
import collections
import json
from pathlib import Path

import numpy as np

from duoforge_live import teams
from duoforge_live.data import trace_to_c

from . import corpus as corpus_mod, dataset, facts, game, setbelief, source, split
from .prior import Prior

OPTION_FIELDS = ("kind", "move_slot", "target", "mega", "reserve")
MOVE = 1  # DUOFORGE_SLOT_MOVE


def set_recovery(true_sets, drawn_sets, member_facts, levels, prior):
    """The counters of members whose true and drawn sets stand side by side (module docstring, (a))."""
    key = trace_to_c.key
    c = collections.Counter()
    for true, drawn, fact, level in zip(true_sets, drawn_sets, member_facts, levels):
        c["members"] += 1
        c[f"members.level{level}"] += 1
        tm, dm, used = ({key(m) for m in s} for s in (true["moves"], drawn["moves"], fact.moves))
        c["moves.exact"] += tm == dm
        c["moves.unseen"] += len(tm - used)
        c["moves.unseen_hit"] += len((tm - used) & dm)
        c["item.unrevealed"] += fact.item is None
        c["item.hit"] += fact.item is None and key(true["item"]) == key(drawn["item"])
        c["ability.unrevealed"] += fact.ability is None
        c["ability.hit"] += fact.ability is None and key(true["ability"]) == key(drawn["ability"])
        c["nature.hit"] += key(true["nature"]) == key(drawn["nature"])
        (tp, tl), (dp, dl) = prior.lookup(true), prior.lookup(drawn)
        c["prior_level.same"] += tl == dl
        c["prior_points.same"] += list(tp) == list(dp)
    return c


def sets(paths, format_prefix, corpus_path, seed, out, data, prior_path):
    """Validation (a) over the test-split two-sheet games of the sources; writes and returns the report."""
    dataset.refuse_repository(out)
    prefix = (format_prefix,) if isinstance(format_prefix, str) else tuple(format_prefix)
    belief = setbelief.SetBelief(corpus_mod.load(corpus_path), data)
    prior = Prior.load(prior_path)
    counters, skipped, read = collections.Counter(), collections.Counter(), collections.Counter()
    games = 0
    for unit in source.units(paths):
        for replay_id, format_id, log in source.read_unit(unit, prefix, read):
            if not format_id.startswith(prefix):
                continue
            lines = log.split("\n")
            packed = {line.split("|")[2]: line.split("|", 3)[3] for line in lines if line.startswith("|showteam|")}
            if sorted(packed) != ["p1", "p2"]:
                skipped["skip:sheets"] += 1
                continue
            try:
                got = split.of_game(split.players_of(lines))
            except ValueError:
                got = "players"
            if got != "test":
                skipped[f"skip:split-{got}"] += 1
                continue
            if {game._hash8(p) for p in packed.values()} & belief.corpus.sheet_hashes:
                skipped["skip:sheet-in-corpus"] += 1  # a training player's identical team (a rental)
                continue
            bare = [line for line in lines if not line.startswith("|showteam|")]
            try:
                drawn, levels, _ = game.draw_sheets(bare, format_id, data, belief, seed, replay_id, 0)
                members = [facts.side_facts(bare, side, data) for side in (0, 1)]
            except game.Skip as e:
                skipped[e.reason] += 1
                continue

            def base(name):
                return data.base_forme(data.forme(name))
            truth = []
            for side in (0, 1):
                by_base = {base(data.canonical(s["species"])): s for s in teams.unpack(packed[f"p{side + 1}"])}
                truth.append([by_base.get(base(data.canonical(m.species))) for m in members[side]])
            if any(t is None for side in truth for t in side):
                skipped["skip:match"] += 1
                continue
            games += 1
            for side in (0, 1):
                counters += set_recovery(truth[side], drawn[side], members[side], levels[side], prior)
    report = {"games": games, "skipped": dict(sorted(skipped.items())), "counters": dict(sorted(counters.items())),
              "seed": int(seed), "corpus_sha256": belief.corpus.sha256, "format_prefix": list(prefix)}
    dataset.write_json_atomic(Path(out), report)
    return report


def _rows(out_dir):
    """(replay id, side, point) -> (observation, domain, label slots, label team) of a dataset's rows."""
    out = {}
    for shard in dataset.read(out_dir):
        games = dataset.read_games(Path(out_dir) / shard["part"])
        for i in range(len(shard["game"])):
            k = (str(games["replay_id"][shard["game"][i]]), int(shard["side"][i]), int(shard["point"][i]))
            if k in out:
                raise ValueError("a row of a game is in the dataset twice (a build with k > 1 draws): compare one draw")
            out[k] = (shard["observation"][i], shard["domain"][i], tuple(int(x) for x in shard["label_slots"][i]),
                      bytes(shard["label_team"][i]))
    return out


def _members(members):
    """The member views with each member's moves (and their PP) in the order of their ids: a drawn sheet lists the
    same moves in another order than the true one, which is no difference of the set."""
    m = members.copy()
    for k in range(len(m)):
        n = int(m[k]["move_count"])
        order = np.argsort(m[k]["move_ids"][:n], kind="stable")
        for field in ("move_ids", "pp", "pp_max"):
            m[k][field][:n] = m[k][field][:n][order]
    return m.tobytes()


def _groups(o):
    player = int(o["player"])
    header = b"".join(o[n].tobytes() for n in o.dtype.names if n != "sides")
    return {"own_members": _members(o["sides"][player]["members"]),
            "foe_members": _members(o["sides"][1 - player]["members"]),
            "positions": o["sides"]["positions"].tobytes(), "header": header}


def _option(o, domain, slot, i):
    """An option by what it does: a move by its move id (the occupant's move_ids at the option's slot), not by the
    slot index, which depends on the order of the sheet's moves."""
    opt = domain["slots"][slot][i]
    fields = [int(opt[f]) for f in OPTION_FIELDS]
    side = o["sides"][int(o["player"])]
    occupant = int(side["occupant"][slot])
    if fields[0] == MOVE and occupant < len(side["members"]) and fields[1] < 4:
        fields[1] = int(side["members"][occupant]["move_ids"][fields[1]])
    return tuple(fields)


def _pairs(o, domain):
    allowed = domain["allowed"]
    return {(_option(o, domain, 0, i), _option(o, domain, 1, j)) for i in range(32) for j in range(32)
            if int(allowed[i]) >> j & 1}


def _label(o, domain, slots):
    return tuple(frozenset(_option(o, domain, s, i) for i in range(32) if slots[s] >> i & 1) for s in (0, 1))


def compare_rows(dir_sheet, dir_drop):
    """Validation (b): the row difference of a sheet build and a drop_sheets build of the same games."""
    a, b = _rows(dir_sheet), _rows(dir_drop)
    both = sorted(set(a) & set(b))
    differs = collections.Counter()
    jaccard, label = [], collections.Counter()
    for k in both:
        (oa, da, la, ta), (ob, db, lb, tb) = a[k], b[k]
        ga, gb = _groups(oa), _groups(ob)
        for group in ga:
            differs[group] += ga[group] != gb[group]
        pa, pb = _pairs(oa, da), _pairs(ob, db)
        jaccard.append(len(pa & pb) / len(pa | pb) if pa | pb else 1.0)
        sa, sb = _label(oa, da, la), _label(ob, db, lb)
        same = sa == sb and ta == tb
        label["same" if same else "differs"] += 1
        label["overlap"] += same or (ta == tb and all((x & y) or not (x or y) for x, y in zip(sa, sb)))
    n = len(both)
    return {"rows_sheet": len(a), "rows_drop": len(b), "both": n, "only_sheet": len(set(a) - set(b)),
            "only_drop": len(set(b) - set(a)),
            "observation_differs": {g: (differs[g] / n if n else 0.0) for g in ("own_members", "foe_members",
                                                                                "positions", "header")},
            "mask_jaccard_mean": float(np.mean(jaccard)) if jaccard else 0.0,
            "label": {"same": label["same"], "differs": label["differs"], "overlap": label["overlap"]}}


def write(report, out):
    dataset.refuse_repository(out)
    dataset.write_json_atomic(Path(out), report)
    return json.dumps(report, indent=1)
