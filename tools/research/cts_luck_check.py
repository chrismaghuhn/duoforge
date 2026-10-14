"""The mandatory comparison of the luck meter with duoforge_learn.luck (#494, docs/benchmarks/2026-10-14-cts-luck/README.md,
"Before the first live report").

Every fifth committed pool battle by its id (sorted; indices 0, 5, 10, ...), both players. Each is a real Showdown
battle that the engine reproduces; ps_client.js gives each player's stream (STREAMS).

- The meter: the player's stream as a closed-sheet log (tools/research/cts_luck_fixture.log_records), the true foe team as
  the set prior, cts_luck.battle with the checkpoint's search: the luck of every valued turn, keyed by its decision.
- luck.py: at the same decision point the true world, Batch.from_view of the player's public record (the open-sheet
  tracker of the stream with both sheets) and the true hidden parts from the trace's state before the step: the foe's
  stat points (the spec's), its exact HP, its picks (the foe's team choice). duoforge_learn.luck.Luck (unchanged)
  values its alternatives (before(), the trace's joint choice as joint ranks in the true world's domains) and the true
  world of the next decision point (after()); at the battle's end the result. A turn whose state holds a hidden counter
  the hypothesis would have to draw (sleep, confusion, a partial trap, a two-turn charge) gets no silent default: it
  is excluded by name, as is a true world the engine refuses or a choice that matches no option.

Passed when the 95% interval of the mean per-turn difference (meter - luck.py) includes 0, or |mean| < 0.01; the
correlation is reported only. Aggregates only (the battles are the project's own committed ones).

    python tools/research/cts_luck_check.py STREAMS.jsonl CHECKPOINT CHECKPOINT_SHA256 OUT.json [--limit N]
"""
import argparse
import collections
import json
import math
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "python"))
sys.path.append(str(Path(__file__).resolve().parent))

HIDDEN_VOLATILES = {"partiallytrapped", "twoturnmove"}


class Skip(Exception):
    """A turn or battle the comparison leaves out, named."""


def pool_battles(root):
    from duoforge_live.data import trace_to_c
    names = []
    for p in sorted((Path(root) / "tests" / "reference" / "traces").glob("*.json")):
        spec, _ = trace_to_c.load_battle(str(root), p.stem)
        if trace_to_c.spec_data(p.stem, spec) == "pool":
            names.append(p.stem)
    return names[::5]


def read_streams(path):
    out = collections.defaultdict(lambda: ([], []))
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = json.loads(line)
            out[m["battle"]][int(m["to"][1]) - 1].append(m["lines"])
    return out


def state_before(trace, k):
    return trace["start"]["state"] if k == 0 else trace["steps"][k - 1]["state"]


def base_of(data, name):
    return data.base_forme(data.forme(name))


def true_points(messages, own_text, data, trace, player):
    """The open-sheet tracker of the player's stream with both sheets: per ready point its rqid, step k, public record and
    the tracker's foe and own rosters (base formes, the record's order)."""
    from duoforge_live.tracker import Tracker
    t = Tracker(data, own_text)
    pid, points, done = f"p{player + 1}", {}, 0
    for m in messages:
        t.feed(m)
        if not (t.ready and t.epoch > done):
            continue
        done = t.epoch
        k = done - 1
        parts = t.public_parts()
        points[t.request.get("rqid")] = {
            "k": k, "record": np.asarray(parts["record"]).copy(), "status": int(parts["status"]),
            "foe": [data.base_forme(m.sheet["species"]) for m in t._member(1 - player)],
            "own": [data.base_forme(m.sheet["species"]) for m in t._member(player)], "order": len(points)}
        step = trace["steps"][k] if k < len(trace["steps"]) else None
        if step is not None and pid in step["input"]:
            t.accepted(step["input"][pid])
    return points


def hypothesis(point, state, spec_rows, picks, player, data):
    """The true HYPOTHESIS of the point's record: the foe's stat points, exact HP and picks; Skip for a hidden counter."""
    from duoforge import view
    for side in state["sides"]:
        for mon in side["pokemon"]:
            if mon.get("status") == "slp" or mon.get("confusion") or HIDDEN_VOLATILES & set(mon.get("volatiles") or ()):
                raise Skip("hidden-counter")
    foe = 1 - player
    h = view.hypotheses(1)
    by_base = {}
    for j, row in enumerate(spec_rows[foe]):
        by_base.setdefault(data.base_forme(row[0]), []).append(j)
    for i, base in enumerate(point["foe"]):
        rows = by_base.get(base, [])
        if len(rows) != 1:
            raise Skip("roster-unmatched")
        h["stat_points"][0][i] = spec_rows[foe][rows[0]][3]
        mons = [m for m in state["sides"][foe]["pokemon"] if base_of(data, m["set_species"]) == base]
        if len(mons) != 1:
            raise Skip("roster-unmatched")
        h["hp"][0][i] = int(mons[0]["hp"])
    spec_base = [data.base_forme(row[0]) for row in spec_rows[foe]]
    order = [point["foe"].index(spec_base[j]) for j in picks]
    h["pick_order"][0][:len(order)] = order
    return h


def joint_rank(domain, a, b):
    """The joint rank (factored_choices' index) of the pair (a, b) in a domain; Skip when the pair is not allowed."""
    from duoforge import batch as _batch
    from duoforge_search import lookahead
    bits = np.asarray(_batch._pair_bits(np.asarray([domain])))[0]
    flat = a * lookahead.OPTIONS + b
    if not bits[flat]:
        raise Skip("choice-not-allowed")
    return int(bits[:flat].sum())


def option_of(domain, slot, cmd, roster_map):
    """The index of a converted slot command in a world's domain (the reserve mapped to the world's roster)."""
    kind, move_slot, target, mega, reserve = cmd
    if kind in (2, 4):
        reserve = roster_map[reserve]
    found = [i for i in range(int(domain["slot_count"][slot]))
             if (int(domain["slots"][slot][i]["kind"]), int(domain["slots"][slot][i]["move_slot"]),
                 int(domain["slots"][slot][i]["target"]), int(domain["slots"][slot][i]["mega"]),
                 int(domain["slots"][slot][i]["reserve"])) == (kind, move_slot, target, mega, reserve)]
    if len(found) != 1:
        raise Skip("choice-unmatched")
    return found[0]


def world(context, point, h):
    import duoforge
    from duoforge import _layout
    b = duoforge.Batch(context, np.resize(duoforge.reference_setups([0]), 1), 1, 7)
    st = b.from_view(np.asarray([point["record"]]).astype(_layout.PUBLIC_STATE), h)
    if int(st[0]) != 0:
        b.close()
        raise Skip(f"true-world-refused:{duoforge.status_name(int(st[0]))}")
    b.query_factored()
    return b


def oracle(name, player, messages, spec, trace, data, search, decisions):
    """luck.py's luck on the true worlds at the meter's valued decisions: {rqid: luck}, Counter of skips."""
    from duoforge_learn.luck import Luck
    from duoforge_live.data import trace_to_c
    skips = collections.Counter()
    own_text = spec["teams"][player]
    points = true_points(messages, own_text, data, trace, player)
    ordered = sorted(points.items(), key=lambda kv: kv[1]["order"])
    tables = trace_to_c.load_tables(str(ROOT), True)
    spec_rows = trace_to_c.convert_battle(name, spec, trace, tables)["members"]
    picks = [int(c) - 1 for c in trace["steps"][0]["input"][f"p{2 - player}"][len("team "):]]
    names = [{trace_to_c.name_of(m): j for j, m in enumerate(trace["start"]["state"]["sides"][s]["pokemon"])}
             for s in (0, 1)]
    spec_base = [[data.base_forme(row[0]) for row in spec_rows[s]] for s in (0, 1)]
    out = {}
    with Luck(search.worlds.context, search.model, search.params, search.encoder, search.ext_supported) as luck:
        luck.start(1, np.array([player]))
        for rqid in decisions:
            if rqid not in points:
                skips["no-true-point"] += 1
                continue
            p = points[rqid]
            nxt = next((q for _, q in ordered if q["order"] == p["order"] + 1), None)
            batch = batch_next = None
            try:
                state = state_before(trace, p["k"])
                h = hypothesis(p, state, spec_rows, picks, player, data)
                batch = world(search.worlds.context, p, h)
                indices = np.zeros((1, 2), np.int64)
                for side in (0, 1):
                    if not int(batch.requests[0, side]["requested"]):
                        continue
                    text = trace["steps"][p["k"]]["input"].get(f"p{side + 1}")
                    if text is None:
                        raise Skip("no-input")
                    kind, cmds = trace_to_c.convert_choice(text, side, state, names)
                    roster = p["own"] if side == player else p["foe"]
                    roster_map = {j: roster.index(spec_base[side][j]) for j in range(len(spec_base[side]))}
                    domain = batch.domains[0, side]
                    a, b = (option_of(domain, s, cmds[s], roster_map) for s in (0, 1))
                    indices[0, side] = joint_rank(domain, a, b)
                luck.before(batch, indices, np.array([True]), p["k"], False)
                if nxt is None:  # the battle ended in the turn: its result
                    winner = trace.get("winner") or next((s["state"].get("winner") for s in trace["steps"][::-1]
                                                          if s.get("state", {}).get("winner")), None)
                    if winner is None:
                        raise Skip("no-end")
                    result = 1.0 if winner == f"p{player + 1}" else (0.0 if winner == "tie" else -1.0)
                    envs, means = luck._pending
                    luck._pending = None
                    out[rqid] = result - float(means[0])
                    continue
                state_next = state_before(trace, nxt["k"])
                h_next = hypothesis(nxt, state_next, spec_rows, picks, player, data)
                batch_next = world(search.worlds.context, nxt, h_next)
                before = len(luck.step_terms)
                luck.after(batch_next, np.array([False]))
                out[rqid] = float(luck.step_terms[before])
            except Skip as s:
                skips[str(s)] += 1
                luck._pending = None
            finally:
                for x in (batch, batch_next):
                    if x is not None:
                        x.close()
    return out, skips


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("streams")
    p.add_argument("checkpoint")
    p.add_argument("checkpoint_sha256")
    p.add_argument("out")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args(argv)
    from duoforge_live import cts, cts_luck, data, pkmn_arena, policy as live_policy, search as live_search, teams
    from duoforge_live.arena import provenance
    from duoforge_live.data import trace_to_c
    from duoforge_replay.dataset import refuse_repository
    import cts_luck_fixture
    refuse_repository(Path(args.out).parent)
    if pkmn_arena.sha256_of(args.checkpoint) != args.checkpoint_sha256:
        raise SystemExit("not the pinned checkpoint")
    tables = data.for_checkpoint(args.checkpoint)
    net = live_policy.load(args.checkpoint)
    live = live_search.load(args.checkpoint, foe_net=args.checkpoint, foe_net_sha256=args.checkpoint_sha256)
    live.searcher = cts.Capture(live.searcher)
    search = live.searcher.searcher
    streams = read_streams(args.streams)
    pairs, skipped, meter_excluded, oracle_skips = [], collections.Counter(), collections.Counter(), collections.Counter()
    names = pool_battles(ROOT)[:args.limit]
    try:
        with cts_luck.Meter(search) as meter, tempfile.TemporaryDirectory() as tmp:
            for n, name in enumerate(names):
                if name not in streams:
                    skipped["no-stream"] += 1
                    continue
                spec, trace = trace_to_c.load_battle(str(ROOT), name)
                for player in (0, 1):
                    messages = streams[name][player]
                    log = Path(tmp, f"battle-gen9championsvgc2026regmc-{n}-p{player + 1}.jsonl")
                    log.write_text("".join(json.dumps(r) + "\n" for r in
                                           cts_luck_fixture.log_records(messages, trace, f"p{player + 1}")),
                                   encoding="utf-8")
                    prior = cts.SetPrior(tables, teams._paste(spec["teams"][1 - player]))
                    try:
                        got = cts_luck.battle(log, tables, net, live, spec["teams"][player], f"p{player + 1}", prior,
                                              meter)
                    except (cts.Refused, Exception) as err:  # a battle the meter cannot replay: named, counted
                        skipped[f"meter:{type(err).__name__}:{str(err).split(' ')[0][:40]}"] += 1
                        continue
                    meter_excluded.update(got["excluded"])
                    try:
                        truth, sk = oracle(name, player, messages, spec, trace, tables, search, got["decisions"])
                    except Exception as err:
                        skipped[f"oracle:{type(err).__name__}"] += 1
                        continue
                    oracle_skips.update(sk)
                    for rqid, luck, mixed in zip(got["decisions"], got["turns"], got["mixed"]):
                        if rqid in truth:
                            pairs.append({"meter": luck, "luck_py": truth[rqid], "mixed": mixed})
    finally:
        live.close()
    diffs = np.array([x["meter"] - x["luck_py"] for x in pairs])
    n = len(diffs)
    mean = float(diffs.mean()) if n else None
    half = float(1.96 * diffs.std(ddof=1) / math.sqrt(n)) if n > 1 else None
    corr = float(np.corrcoef([x["meter"] for x in pairs], [x["luck_py"] for x in pairs])[0, 1]) if n > 2 else None
    unmixed = np.array([x["meter"] - x["luck_py"] for x in pairs if not x["mixed"]])
    result = {"battles": len(names), "player_battles_skipped": dict(skipped), "turns_compared": n,
              "mean_difference": mean, "half_width": half, "correlation": corr,
              "passed": None if mean is None or half is None else bool(abs(mean) < 0.01 or abs(mean) <= half),
              "unmixed": {"turns": int(unmixed.size), "mean_difference": float(unmixed.mean()) if unmixed.size else None,
                          "half_width": float(1.96 * unmixed.std(ddof=1) / math.sqrt(unmixed.size))
                          if unmixed.size > 1 else None},
              "meter_excluded": dict(meter_excluded), "luck_py_skipped": dict(oracle_skips),
              "checkpoint_sha256": args.checkpoint_sha256, "code": provenance(ROOT)}
    Path(args.out).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("meter_excluded",)}, indent=1))


if __name__ == "__main__":
    main()
