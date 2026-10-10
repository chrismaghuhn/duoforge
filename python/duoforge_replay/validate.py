"""Validation of the Bo1 belief (M11 Bo1 spec section 6), aggregates only.

(a) sets(): on the test-split games with two sheets, the sets drawn from the log alone (sheets dropped) against the
    true sheets, per member: the move set, the unseen moves, the item, ability and nature where the log did not
    reveal them, and the stat points as the prior assigns them. Replays never show stat points, the sheets neither:
    the true spread is unknown, so the measure is whether the drawn set reaches the same prior key level and the same
    prior stat points as the true set (prior_level.same, prior_points.same), not a stat point distance.
(b) compare_rows(): a sheet build and a drop_sheets build of the same games, row by row (replay, side, point): which
    rows both have, which observation field groups differ, the overlap of the legal pairs, the agreement of labels.

hypotheses(): the validation of the pick hypotheses (M11 pick hypotheses spec, Validation) on the test-split games
with two sheets. In each perspective whose four brought members the log shows, each seen back pick is hidden once
from the hypothesis builder (hindsight.hypotheses_of without it), and the perspective is folded per hypothesis as a
build folds one (game.hypothesis_rows). Compared are the points whose label lines end before the hidden member's
first switch-in, so that the labels are complete in every fold:
- (1) correctness: the true hypothesis's rows against the real rows, byte for byte (observation, domain, extension
  record, label); any difference is a bug;
- (2) effect: the other hypotheses' rows against the real rows: the share of rows whose observation field group,
  domain or extension record differs, the Jaccard of the legal pairs, and the share of informative label slots
  whose logged action is no option of the hypothesis (label_lost: UNKNOWN where the real row knew it);
- the share of points at which all H rows are byte-equal: in full, beyond the pick fields (the own brought_order
  and the own members' location, which differ by construction), and in the domain; for the hidden picks and for
  the real hypothesis perspectives (picks-incomplete) of the same games.

No report names a replay, a player or a game: counts and shares only. Outputs are refused inside the repository.
"""
import collections
import json
from pathlib import Path

import numpy as np

from duoforge_live import teams
from duoforge_live.data import trace_to_c

from duoforge_live.lines import line_kind

from . import corpus as corpus_mod, dataset, facts, game, hindsight, labels, points as points_mod, setbelief, source
from . import split
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


def _row_bytes(row):
    label = row.label
    return (row.observation.tobytes(), row.domain.tobytes(), row.ext.tobytes(), tuple(label.slots),
            bytes(label.team), tuple(label.reasons))


def _beyond_picks(row):
    """A row's observation and extension record without the pick fields: the own brought_order and the own members'
    location (BENCH or NOT_BROUGHT follows the picks)."""
    o = row.observation.copy()
    player = int(o["player"])
    o["sides"]["brought_order"][player] = 0
    o["sides"]["members"]["location"][player] = 0
    return o.tobytes(), row.ext.tobytes()


def _all_equal(c, prefix, rows):
    """Counts the points at which all rows (one per hypothesis) are byte-equal: in full; in the observation beyond
    the pick fields, the extension record and the label; in the domain."""
    c[f"{prefix}points"] += 1
    c[f"{prefix}all_equal.rows"] += len({_row_bytes(r) for r in rows}) == 1
    c[f"{prefix}all_equal.beyond_picks"] += len({(_beyond_picks(r), _row_bytes(r)[3:]) for r in rows}) == 1
    c[f"{prefix}all_equal.domain"] += len({r.domain.tobytes() for r in rows}) == 1


def _first_switch(lines, side, data, sheets, member):
    """The index of the line at which a member of a side first switches in after |start|."""
    roster = [data.base_forme(data.forme(m["species"])) for m in sheets[side]]
    started = False
    for i, line in enumerate(lines):
        kind = line_kind(line)
        if kind == "start":
            started = True
        elif kind == "switch" and started and line.split("|")[2][:2] == f"p{side + 1}":
            try:
                base = data.base_forme(data.forme(line.split("|")[3].split(",")[0]))
            except ValueError:
                continue
            if roster.index(base) == member:
                return i
    raise ValueError(f"member {member} of p{side + 1} never switches in")


_INFORMATIVE = (labels.EXACT, labels.TARGET_UNKNOWN, labels.MOVE_HIDDEN)


def _effect(c, real, row):
    ga, gb = _groups(real.observation), _groups(row.observation)
    for group in ga:
        c[f"other.differs.{group}"] += ga[group] != gb[group]
    c["other.differs.domain"] += real.domain.tobytes() != row.domain.tobytes()
    c["other.differs.ext"] += real.ext.tobytes() != row.ext.tobytes()
    pa, pb = _pairs(real.observation, real.domain), _pairs(row.observation, row.domain)
    c["other.jaccard_sum"] += len(pa & pb) / len(pa | pb) if pa | pb else 1.0
    for a, b in zip(real.label.reasons, row.label.reasons):
        if a in _INFORMATIVE:
            c["other.label_slots"] += 1
            c["other.label_lost"] += b == labels.UNKNOWN


def hypotheses_game(replay_id, format_id, log, data, prior, stats):
    """The counters of one open-sheet game (module docstring, hypotheses()); Skip as game.process raises it."""
    c = collections.Counter()
    result = game.process(replay_id, format_id, log, data, prior, stats, pick_hypotheses=True)
    c["games"] += 1
    lines = [line.rstrip("\r") for line in log.split("\n")]
    _, sheets = game._prepass(replay_id, format_id, lines, data)
    points = points_mod.find(lines)
    real_hyp = collections.defaultdict(list)
    for r in result.rows:
        if r.picks_hypotheses > 1:
            real_hyp[(r.side, r.point)].append(r)
    c["real.perspectives"] += len({side for side, _ in real_hyp})
    for rows in real_hyp.values():
        _all_equal(c, "real.", rows)
    for side in (0, 1):
        picks = hindsight.hindsight_picks(lines, side, data, sheets)
        if picks is None:
            continue
        c["perspectives.seen4"] += 1
        leads, back = hindsight.hindsight(lines, side, data, sheets)
        real = {r.point: r for r in result.rows if r.side == side and r.picks_hypotheses == 1}
        for hidden in sorted(back):
            c["cases"] += 1
            end = _first_switch(lines, side, data, sheets, hidden)
            hyps = hindsight.hypotheses_of(leads, back - {hidden}, len(sheets[side]))
            truth = hyps.index(picks)
            per_hypothesis, _ = game.hypothesis_rows(lines, points, side, sheets, data, prior, stats, hyps)
            by_point = [{r.point: r for r in rows} for rows in per_hypothesis]
            region = [p.index for p in points if p.end <= end and p.boundary != points_mod.TEAM_SELECTION
                      and p.index in real]
            for index in region:
                for k, rows in enumerate(by_point):
                    who = "true" if k == truth else "other"
                    if index not in rows:
                        c[f"{who}.missing"] += 1
                        continue
                    c[f"{who}.rows"] += 1
                    if k == truth:
                        same = _row_bytes(rows[index]) == _row_bytes(real[index])
                        c["true.identical" if same else "true.differs"] += 1
                    else:
                        _effect(c, real[index], rows[index])
                if all(index in rows for rows in by_point):
                    _all_equal(c, "", [rows[index] for rows in by_point])
    return c


def _share(n, d):
    return n / d if d else 0.0


def hypotheses_summary(c):
    """The report of one format's counters of hypotheses_game."""
    other = c["other.rows"]
    return {
        "games": c["games"], "perspectives_seen4": c["perspectives.seen4"], "cases": c["cases"],
        "true": {"rows": c["true.rows"], "identical": c["true.identical"], "differs": c["true.differs"],
                 "missing": c["true.missing"], "identical_share": _share(c["true.identical"], c["true.rows"])},
        "other": {"rows": other, "missing": c["other.missing"],
                  "differs": {g: _share(c[f"other.differs.{g}"], other)
                              for g in ("own_members", "foe_members", "positions", "header", "domain", "ext")},
                  "mask_jaccard_mean": _share(c["other.jaccard_sum"], other),
                  "label_lost": _share(c["other.label_lost"], c["other.label_slots"])},
        "hidden_points": c["points"],
        "hidden_all_equal": {k: _share(c[f"all_equal.{k}"], c["points"]) for k in ("rows", "beyond_picks", "domain")},
        "real_perspectives": c["real.perspectives"], "real_points": c["real.points"],
        "real_all_equal": {k: _share(c[f"real.all_equal.{k}"], c["real.points"])
                           for k in ("rows", "beyond_picks", "domain")},
    }


_HYP = {}


def _hyp_init(prior_path, stats_factory, node, ps_dir, prefix):
    from duoforge_live import data as live_data
    from .stats import StatSource
    _HYP["data"] = live_data.load(kind="pool")
    _HYP["prior"] = Prior.load(prior_path)
    _HYP["stats"] = stats_factory() if stats_factory is not None else StatSource(node, ps_dir)
    _HYP["prefix"] = prefix


def _hyp_unit(unit):
    """(counters per format id, skipped) of the test-split open-sheet games of one source unit."""
    per, skipped, read = collections.defaultdict(collections.Counter), collections.Counter(), collections.Counter()
    for replay_id, format_id, log in source.read_unit(unit, _HYP["prefix"], read):
        if not format_id.startswith(_HYP["prefix"]):
            continue
        lines = log.split("\n")
        if sum(1 for line in lines if line.startswith("|showteam|")) != 2:
            skipped["skip:sheets"] += 1
            continue
        try:
            got = split.of_game(split.players_of(lines))
        except ValueError:
            got = "players"
        if got != "test":
            skipped[f"skip:split-{got}"] += 1
            continue
        try:
            per[format_id] += hypotheses_game(replay_id, format_id, log, _HYP["data"], _HYP["prior"], _HYP["stats"])
        except game.Skip as e:
            skipped[e.reason] += 1
        except game.line_classes.Stop as e:
            skipped[f"stop:{e.reason}"] += 1
    return {k: dict(v) for k, v in per.items()}, dict(skipped)


def hypotheses(paths, format_prefix, out, prior_path, workers=1, node="node", ps_dir=None, stats_factory=None):
    """The validation of the pick hypotheses over the sources (module docstring); writes and returns the report."""
    import concurrent.futures
    import multiprocessing
    import os
    dataset.refuse_repository(out)
    prefix = (format_prefix,) if isinstance(format_prefix, str) else tuple(format_prefix)
    ps_dir = ps_dir or os.environ.get("DUOFORGE_PS_REFERENCE_DIR")
    initargs = (prior_path, stats_factory, node, ps_dir, prefix)
    units = source.units(paths)
    per, skipped = collections.defaultdict(collections.Counter), collections.Counter()

    def take(result):
        counters, skips = result
        for fid, c in counters.items():
            per[fid].update(c)
        skipped.update(skips)
    if workers == 1:
        _hyp_init(*initargs)
        for unit in units:
            take(_hyp_unit(unit))
    else:
        context = multiprocessing.get_context("spawn")
        with concurrent.futures.ProcessPoolExecutor(workers, mp_context=context, initializer=_hyp_init,
                                                    initargs=initargs) as pool:
            for result in pool.map(_hyp_unit, units):
                take(result)
    report = {"formats": {fid: hypotheses_summary(c) for fid, c in sorted(per.items())},
              "skipped": dict(sorted(skipped.items())), "format_prefix": list(prefix)}
    dataset.write_json_atomic(Path(out), report)
    return report


def write(report, out):
    dataset.refuse_repository(out)
    dataset.write_json_atomic(Path(out), report)
    return json.dumps(report, indent=1)
