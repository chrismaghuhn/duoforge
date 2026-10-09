"""duoforge.python.expert_eval: the P1 evaluation gate and compute ledger (plan C5).

Synthetic pools, scores and ledgers in temporary directories only; no games
are played and no real results, checkpoints or ledgers are read.
"""
import contextlib
import dataclasses
import io
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

import duoforge
from duoforge import teams

IDS = ("A", "B", "PP_one", "LL_one", "LL_two", "C")


def pool():
    return teams.TeamPool.from_setups(IDS, duoforge.reference_setups([0, 1, 2])["sides"].reshape(-1))


HEXES = {name: f"{i:x}" * 64 for i, name in enumerate(("pilot", "control", "frozen", "BC", "3600", "11000",
                                                        "ladder"), start=1)}


def manifest(ev, seed=99, **kw):
    """The manifest make_manifest pins for the synthetic pool; kw replaces fields (validated again)."""
    base = ev.make_manifest(pool(), seed=seed, first_game_id=10**6, checkpoints=HEXES)
    return dataclasses.replace(base, **kw) if kw else base


def ledger_map(cpu, gpu, phases=None):
    phases = phases or {"generation": {"cpu_core_seconds": cpu * 0.75, "gpu_seconds": 0.0},
                        "distill": {"cpu_core_seconds": cpu * 0.25, "gpu_seconds": gpu}}
    return {"schema": 1, "cpu_core_seconds": cpu, "gpu_seconds": gpu, "processes": 2, "phases": phases}


def arms(ev):
    same = ev.ComputeLedger.from_mapping(ledger_map(1000.0, 200.0))
    return same, same


def scored(rows, rule):
    """Records: the schedule with a student score from rule(suite, opponent, arm, bucket, pair) per pair."""
    out = {k: v.copy() for k, v in rows.items()}
    score = np.zeros(rows["game_id"].size)
    for i in range(score.size):
        score[i] = rule(rows["suite"][i], rows["opponent"][i], rows["arm"][i], rows["bucket"][i], int(rows["pair"][i]))
    out["score"], out["finished"] = score, np.ones(score.size, bool)
    return out


def strong(suite, opponent, arm, bucket, pair):
    """The pilot wins 60% of pairs against everything; the control scores 0.5."""
    if arm == "control":
        return 1.0 if pair % 2 else 0.0
    return 1.0 if pair % 10 < 6 else 0.0


class EvalGate(unittest.TestCase):
    def test_eval_pairings_groups_and_ci_stop(self):
        from duoforge_search import expert_eval as ev
        m = manifest(ev)
        rows = ev.make_eval_rows(pool(), m)
        n = rows["game_id"].size
        self.assertEqual(n, 12288)
        self.assertEqual(sorted(rows), sorted(ev.SCHEDULE_FIELDS))
        counts = {}
        for suite, opp, arm in zip(rows["suite"], rows["opponent"], rows["arm"]):
            counts[(str(suite), str(opp), str(arm))] = counts.get((str(suite), str(opp), str(arm)), 0) + 1
        self.assertEqual(counts, {("h2h_continuation", "control", "pilot"): 2048, ("h2h_frozen", "frozen", "pilot"): 2048,
                                  **{("panel", o, a): 1024 for o in ("BC", "3600", "11000") for a in ("pilot", "control")},
                                  **{("ladder", "ladder", a): 1024 for a in ("pilot", "control")}})
        self.assertEqual(len(set(rows["game_id"].tolist())), n)
        self.assertTrue(((rows["game_id"] >= 10**6) & (rows["game_id"] < 10**6 + n)).all())
        # Every suite is half PP_/A/B/C and half LL_, teams drawn from the row's own bucket.
        ll = np.array([IDS[t].startswith("LL_") for t in rows["student_team"]])
        self.assertTrue((ll == (rows["bucket"] == "LL")).all())
        self.assertTrue((np.array([IDS[t].startswith("LL_") for t in rows["opponent_team"]]) == ll).all())
        self.assertEqual(int((rows["bucket"] == "LL").sum()), n // 2)
        # Swapped seats: each pair is two games with the same teams and seed, one per seat.
        key = list(zip(rows["suite"], rows["opponent"], rows["arm"], rows["bucket"], rows["pair"]))
        groups = {}
        for i, k in enumerate(key):
            groups.setdefault(k, []).append(i)
        self.assertTrue(all(len(g) == 2 for g in groups.values()))
        for g in list(groups.values())[:50]:
            a, b = g
            self.assertEqual({int(rows["student_seat"][a]), int(rows["student_seat"][b])}, {0, 1})
            for name in ("student_team", "opponent_team", "seed"):
                self.assertEqual(rows[name][a], rows[name][b])
        # Pilot and control face each panel/ladder opponent on mirrored rows (paired arms).
        for suite, opp in (("panel", "BC"), ("ladder", "ladder")):
            p = (rows["suite"] == suite) & (rows["opponent"] == opp) & (rows["arm"] == "pilot")
            c = (rows["suite"] == suite) & (rows["opponent"] == opp) & (rows["arm"] == "control")
            for name in ("bucket", "pair", "student_seat", "student_team", "opponent_team", "seed"):
                np.testing.assert_array_equal(rows[name][p], rows[name][c])
        again = ev.make_eval_rows(pool(), m)
        for name in rows:
            np.testing.assert_array_equal(again[name], rows[name])
        self.assertFalse(np.array_equal(ev.make_eval_rows(pool(), manifest(ev, seed=100))["student_team"],
                                        rows["student_team"]))
        no_ll = teams.TeamPool.from_setups(("A", "B", "C"), duoforge.reference_setups([0, 1])["sides"].reshape(-1)[:3])
        with self.assertRaisesRegex(ValueError, "LL_"):
            ev.make_eval_rows(no_ll, m)
        with self.assertRaisesRegex(ValueError, "pool"):
            ev.make_eval_rows(pool().with_weights(np.arange(1, 7)), m)  # another pool than the manifest pins
        # Gates on synthetic results: a clear win passes every group, the ladder is reported, not gated.
        result = ev.evaluate_records(scored(rows, strong), m, arms(ev))
        self.assertIs(result.status, ev.GateStatus.PASS)
        self.assertEqual(set(result.groups), {"h2h_continuation", "h2h_frozen", "panel", "panel_PP", "panel_LL"})
        self.assertAlmostEqual(result.groups["h2h_continuation"]["point"], 308 / 512, places=12)  # i % 10 < 6, 512 pairs
        self.assertGreater(result.groups["h2h_continuation"]["low"], 0.5)
        self.assertIn("ladder", result.scores)
        self.assertEqual(ev.evaluate_records(scored(rows, strong), m, arms(ev)), result)  # fixed bootstrap seeds
        shuffled = scored(rows, strong)
        order = np.random.default_rng(3).permutation(n)
        shuffled = {k: v[order] for k, v in shuffled.items()}
        self.assertEqual(ev.evaluate_records(shuffled, m, arms(ev)), result)  # row order is irrelevant

        def variant(over):
            def rule(suite, opponent, arm, bucket, pair):
                for (s, a, b), fn in over.items():
                    if s == suite and a in (None, arm) and b in (None, bucket):
                        return fn(pair)
                return strong(suite, opponent, arm, bucket, pair)
            return rule

        cases = {
            # 264/512 = 0.516: below the 0.52 point bar, its interval still reaching above 0.50: inconclusive.
            "borderline": (variant({("h2h_continuation", "pilot", None): lambda i: 1.0 if i < 264 else 0.0}),
                           ev.GateStatus.INCONCLUSIVE, "h2h_continuation"),
            # 268/512 = 0.523 meets the point bar, but its lower bound stays at or below 0.50.
            "ci stop": (variant({("h2h_continuation", "pilot", None): lambda i: 1.0 if i < 268 else 0.0}),
                        ev.GateStatus.INCONCLUSIVE, "h2h_continuation"),
            "lost": (variant({("h2h_continuation", "pilot", None): lambda i: 1.0 if i % 10 < 4 else 0.0}),
                     ev.GateStatus.FAIL, "h2h_continuation"),
            "frozen bar": (variant({("h2h_frozen", "pilot", None): lambda i: 1.0 if i < 266 else 0.0}),
                           ev.GateStatus.INCONCLUSIVE, "h2h_frozen"),
            "LL inferior": (variant({("panel", "pilot", "LL"): lambda i: 1.0 if i % 10 < 4 else 0.0}),
                            ev.GateStatus.FAIL, "panel_LL"),
        }
        for name, (rule, status, group) in cases.items():
            with self.subTest(name):
                got = ev.evaluate_records(scored(rows, rule), m, arms(ev))
                self.assertIs(got.groups[group]["status"], status)
                self.assertIs(got.status, status)
        # Unfinished or nonfinite results and an absent required bucket leave the result incomplete.
        unfinished = scored(rows, strong)
        unfinished["finished"][5] = False
        self.assertIs(ev.evaluate_records(unfinished, m, arms(ev)).status, ev.GateStatus.INCOMPLETE)
        nan = scored(rows, strong)
        nan["score"][7] = math.nan
        self.assertIs(ev.evaluate_records(nan, m, arms(ev)).status, ev.GateStatus.INCOMPLETE)
        null = {k: v.tolist() for k, v in scored(rows, strong).items()}  # as JSON lists, an unfinished null
        null["score"][7], null["finished"][7] = None, False
        self.assertIs(ev.evaluate_records(null, m, arms(ev)).status, ev.GateStatus.INCOMPLETE)
        records = scored(rows, strong)
        keep = records["bucket"] != "LL"
        without_ll = {k: v[keep] for k, v in records.items()}
        got = ev.evaluate_records(without_ll, m, arms(ev))
        self.assertIs(got.status, ev.GateStatus.INCOMPLETE)
        self.assertIs(got.groups["panel_LL"]["status"], ev.GateStatus.INCOMPLETE)
        # Pairing and schedule errors are refused, never repaired or re-chosen.
        broken = scored(rows, strong)
        broken["student_seat"][1] = broken["student_seat"][0]  # both games of a pair on one seat
        def changed(rule):
            records = scored(rows, strong)
            rule(records)
            return records

        first_pp = np.flatnonzero((rows["suite"] == "panel") & (rows["bucket"] == "PP"))[:2]
        ll_team = IDS.index("LL_one")

        def relabel(records):  # both seats and the mirrored arm: consistent, but not the predeclared draw
            same = ((records["suite"] == "panel") & (records["opponent"] == records["opponent"][first_pp[0]])
                    & (records["bucket"] == "PP") & (records["pair"] == records["pair"][first_pp[0]]))
            records["student_team"][same] = ll_team

        def reseed(records):
            pair = (records["suite"] == "h2h_frozen") & (records["pair"] == 3) & (records["bucket"] == "LL")
            records["seed"][pair] += 1

        def mirror(records):
            pair = ((records["suite"] == "ladder") & (records["arm"] == "control") & (records["pair"] == 0)
                    & (records["bucket"] == "PP"))
            records["opponent_team"][pair] = (records["opponent_team"][pair] + 1) % len(IDS)

        refusals = {
            "relabelled teams": changed(relabel),
            "other seed": changed(reseed),
            "mirror": changed(mirror),
            "game id": changed(lambda r: r["game_id"].__setitem__(9, r["game_id"][9] + 1)),
            "fractional pair": {**scored(rows, strong), "pair": rows["pair"] + 0.4},
            "text finished": {**scored(rows, strong), "finished": np.array(["no"] * n)},
            "text score": {**scored(rows, strong), "score": np.array(["1.0"] * n)},
            "same seat": broken,
            "half pair": {k: v[1:] for k, v in scored(rows, strong).items()},
            "extra suite": {**scored(rows, strong), "suite": np.where(rows["suite"] == "ladder", "best_of", rows["suite"])},
            "score range": {**scored(rows, strong), "score": np.full(n, 2.0)},
            "missing field": {k: v for k, v in scored(rows, strong).items() if k != "seed"},
        }
        for name, bad in refusals.items():
            with self.subTest(name), self.assertRaises(ValueError):
                ev.evaluate_records(bad, m, arms(ev))
        with self.assertRaises(TypeError):
            ev.evaluate_records(scored(rows, strong), m)  # the compute ledgers are required
        for bad in ({"play": "search"}, {"book": True}, {"preview_search": True}, {"resamples": 1000},
                    {"checkpoints": {**m.checkpoints, "BC": "no"}}, {"seed": -1}, {"first_game_id": 2**63},
                    {"schedule": {**m.schedule, "panel/BC/pilot/PP": "no"}},
                    {"schedule": {k: v for k, v in m.schedule.items() if k != "ladder/ladder/control/LL"}}):
            with self.subTest(manifest=bad), self.assertRaises(ValueError):
                manifest(ev, **bad)


class ComputeLedger(unittest.TestCase):
    ledger = staticmethod(ledger_map)

    def test_eval_compute_tolerance_cost_and_privacy(self):
        from duoforge_search import expert_eval as ev
        load = ev.ComputeLedger.from_mapping
        pilot = load(self.ledger(1000.0, 200.0))
        ev.validate_compute(pilot, load(self.ledger(1050.0, 190.0)))  # 5.0% and 5.0%
        for control, axis in ((self.ledger(1051.0, 200.0), "cpu_core_seconds"), (self.ledger(949.0, 200.0), "cpu_core_seconds"),
                              (self.ledger(1000.0, 210.2), "gpu_seconds")):
            with self.subTest(axis=axis, control=control["cpu_core_seconds"]), self.assertRaisesRegex(ValueError, axis):
                ev.validate_compute(pilot, load(control))
        ev.validate_compute(load(self.ledger(10.0, 0.0)), load(self.ledger(10.0, 0.0)))
        with self.assertRaisesRegex(ValueError, "gpu_seconds"):
            ev.validate_compute(load(self.ledger(10.0, 0.0)), load(self.ledger(10.0, 0.1)))
        # Only measured axes count: caps or step counts are not ledger fields.
        for bad in ({**self.ledger(1.0, 1.0), "cap_seconds": 1.0}, {**self.ledger(1.0, 1.0), "schema": 2},
                    {**self.ledger(1.0, -1.0)}, {**self.ledger(math.nan, 1.0)},
                    self.ledger(1.0, 1.0, {"x": {"cpu_core_seconds": 2.0, "gpu_seconds": 0.0}}),  # phases exceed total
                    self.ledger(1.0, 1.0, {"x": {"cpu_core_seconds": 0.5}}),
                    {**self.ledger(1.0, 1.0), "schema": 1.0}, {**self.ledger(1.0, 1.0), "processes": 0}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                load(bad)
        # The shared evaluation is charged half to each arm.
        shared = load(self.ledger(400.0, 100.0))
        a, b = ev.charge_shared(pilot, load(self.ledger(1000.0, 200.0)), shared)
        self.assertEqual((a.cpu_core_seconds, a.gpu_seconds), (1200.0, 250.0))
        self.assertEqual(a.phases["evaluation_share"], {"cpu_core_seconds": 200.0, "gpu_seconds": 50.0})
        self.assertEqual((b.cpu_core_seconds, b.gpu_seconds), (1200.0, 250.0))
        with self.assertRaises(ValueError):
            ev.charge_shared(a, b, shared)  # charged once only
        # A ledger.py file as the learner writes it loads unchanged.
        from duoforge_learn.ledger import Ledger
        with tempfile.TemporaryDirectory(prefix="duoforge_synthetic_ledger_") as temp:
            written = Ledger(Path(temp) / "arm.json")
            with written.phase("generation"):
                sum(i * i for i in range(20000))
            written.save()
            real = load(json.loads((Path(temp) / "arm.json").read_text()))
            self.assertGreaterEqual(real.cpu_core_seconds, real.phases["generation"]["cpu_core_seconds"])
        # CLI: private paths in, a structured report out; strength failures still exit 0.
        m = manifest(ev)
        rows = ev.make_eval_rows(pool(), m)
        with tempfile.TemporaryDirectory(prefix="duoforge_synthetic_eval_") as temp:
            d = Path(temp)

            def write(name, value):
                (d / name).write_text(json.dumps(value), encoding="utf-8")
                return str(d / name)

            def baseline(records, ledger=None):
                return {"records": {k: v.tolist() for k, v in records.items()},
                        "ledger": ledger or self.ledger(400.0, 100.0)}

            paths = {"--manifest": write("manifest.json", ev.manifest_mapping(m)),
                     "--pilot": write("pilot.json", self.ledger(1000.0, 200.0)),
                     "--control": write("control.json", self.ledger(1020.0, 205.0)),
                     "--baseline": write("baseline.json", baseline(scored(rows, strong)))}

            def run(out, **change):
                args = []
                for flag, path in {**paths, **change, "--out": str(d / out)}.items():
                    args += [flag, path]
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    code = ev.main(args)
                return code, err.getvalue()

            code, _ = run("report.json")
            self.assertEqual(code, 0)
            report = json.loads((d / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["compute"]["pilot"]["cpu_core_seconds"], 1200.0)
            lost = scored(rows, lambda s, o, a, b, i: 0.0 if a == "pilot" else 1.0)
            code, _ = run("lost.json", **{"--baseline": write("lost_baseline.json", baseline(lost))})
            self.assertEqual(code, 0)
            self.assertEqual(json.loads((d / "lost.json").read_text(encoding="utf-8"))["status"], "FAIL")
            broken = scored(rows, strong)
            broken["student_seat"][1] = broken["student_seat"][0]
            # The 5% match is on the arms' own use: a large shared charge cannot dilute it.
            paths_far = {"--pilot": write("p28800.json", self.ledger(28800.0, 1800.0)),
                         "--control": write("c30300.json", self.ledger(30300.0, 1980.0)),
                         "--baseline": write("big_shared.json", baseline(scored(rows, strong), self.ledger(3600.0, 3600.0)))}
            for name, change, cause in (
                    ("diluted", paths_far, "cpu_core_seconds"),
                    ("compute", {"--control": write("far.json", self.ledger(2000.0, 200.0))}, "cpu_core_seconds"),
                    ("pairing", {"--baseline": write("broken.json", baseline(broken))}, "seat"),
                    ("manifest", {"--manifest": write("bad_manifest.json", {**ev.manifest_mapping(m), "book": True})},
                     "book"),
                    ("missing", {"--pilot": str(d / "absent.json")}, "absent.json")):
                with self.subTest(name):
                    code, err = run(f"out_{name}.json", **change)
                    self.assertEqual(code, 2)
                    self.assertIn(cause, err)
                    self.assertFalse((d / f"out_{name}.json").exists())
            code, err = run("report.json")  # never overwrites a report
            self.assertEqual(code, 2)
            inside = Path(__file__).with_name("private-eval-report.json")
            with contextlib.redirect_stderr(io.StringIO()):
                code = ev.main(sum(([k, v] for k, v in {**paths, "--out": str(inside)}.items()), []))
            self.assertEqual(code, 2)
            self.assertFalse(inside.exists())
            # No CLI option can alter seeds, panel or budgets.
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                ev.main(sum(([k, v] for k, v in paths.items()), []) + ["--out", str(d / "x.json"), "--seed", "1"])


if __name__ == "__main__":
    unittest.main()
