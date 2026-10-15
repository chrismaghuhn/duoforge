"""The preview series (issue #458): the plan of docs/benchmarks/2026-10-14-preview-mixed run against a fake oracle
process (its arm files from a payoff table), with the real merging, summaries, matrices and comparisons. No network,
no checkpoint, no process: preview_series._start is replaced."""
import json
import os
import tempfile
import unittest
from fractions import Fraction
from unittest import mock

from duoforge_search import preview_oracle as oracle
from duoforge_search import preview_series as series

SPECIES = {"ours": ["O0", "O1", "O2", "O3", "O4", "O5"], "foe": ["F0", "F1", "F2", "F3", "F4", "F5"]}
CONDITIONS = {"tool": "preview_oracle", "max_steps": 1000, "step": {"name": "0"}, "foe_preview": "x",
              "ours_sha256_prefix": "a", "foe_sha256_prefix": "b", "left_out": {}, "species": SPECIES,
              "commit": "c0ffee", "dirty": False, "library": "0.45.0", "encoders": {}, "sha256_prefix": {},
              "table_sha256": "t", "foe_lead": None, "cpu": "x", "registry": {"ours": "A", "foe": None}}


class Fake:
    """A stand-in for `python -m duoforge_search.preview_oracle`: from its arguments it writes conditions.json and an
    arm file per arm, our per-game scores from value(our, foe) (a mix's value is its weighted mean)."""

    def __init__(self, value, beside_differs=False, fail=None, workers=None, dirty=False, interrupt=None):
        self.value, self.beside_differs, self.fail, self.workers = value, beside_differs, fail, workers
        self.calls, self.events, self.dirty = [], [], dirty  # events: ("start"|"wait", process number)
        self.interrupt, self.seen = interrupt, 0  # interrupt: the seed whose second process dies (a spot interruption)

    def __call__(self, cmd, log_path, env):
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("fake\n")
        self.calls.append(cmd)
        opt = lambda k, d=None: cmd[cmd.index(k) + 1] if k in cmd else d  # noqa: E731
        out, side, arms = opt("--out"), opt("--side"), opt("--arms").split(",")
        pairs, seed = int(opt("--pairs")), opt("--seed")
        if self.fail and self.fail in arms:
            return Done(1, self)
        if self.interrupt and seed == self.interrupt:
            self.seen += 1
            if self.seen == 2:
                return Done(1, self)
        games = 2 * pairs
        our_arm, our_mix, foe_mix = opt("--our-arm"), opt("--our-mix"), opt("--foe-mix")
        workers = self.workers if self.workers is not None else int(opt("--workers"))
        c = dict(CONDITIONS, seed=seed, pairs=pairs, games=games, side=side, our_arm=our_arm, our_mix=our_mix,
                 foe_mix=foe_mix, workers=workers, dirty=self.dirty)
        os.makedirs(os.path.join(out, "arms"), exist_ok=True)
        with open(os.path.join(out, "conditions.json"), "w", encoding="utf-8") as f:
            json.dump(c, f)
        drawn_rows = [oracle.team_index("01|23")] * games
        for arm in arms:
            if side == "foe":
                ours = [(our_arm or "today", 1)] if not our_mix else oracle.parse_mix(our_mix, "ours")
                foes = [(arm, 1)]
                foe_drawn = drawn_rows if arm == "drawn" else [oracle.team_index(arm)] * games
            else:
                ours = [(arm, 1)]
                foes = [("drawn", 1)] if not foe_mix else oracle.parse_mix(foe_mix, "foe")
                foe_drawn = drawn_rows
            v = sum(Fraction(p) * Fraction(q) * self.value(o, f) for o, p in ours for f, q in foes)
            k = round(v * games)
            scores = [1.0 if g < k else 0.0 for g in range(games)]
            beside = "beside" in out and self.beside_differs
            entry = {"arm": arm, "scores": scores, "unfinished": 0, "unresolved": 0, "foe_drawn": foe_drawn,
                     "own_choice": {"0": "24|03", "1": "24|03"},
                     "our_played": {"0": our_arm or "24|03", "1": our_arm or "24|03"},
                     "our_picked": None, "foe_picked": None, "fallback_share": {"ours": 0.0, "foe": 0.0},
                     "fallback_causes": {"ours": {}, "foe": {}},
                     "decisions_sha256": {"ours": "x" if beside else "d", "foe": "d"}, "commit": "c0ffee",
                     "dirty": False, "seconds": 1.0, "wall_seconds": {"p99": 0.1}}
            if our_mix:
                entry["our_played"] = {"0": ["23|04", "today"], "1": ["23|04", "today"]}
                entry["our_picked"] = ["today", "23|04"] * pairs
            if foe_mix:
                entry["foe_picked"] = ["drawn"] * games
            with open(oracle_arm(out, arm), "w", encoding="utf-8") as f:
                json.dump(entry, f)
        return Done(0, self)


def oracle_arm(out, arm):
    return os.path.join(out, "arms", arm.replace("|", "-") + ".json")


class Done:
    """A finished fake process; its start and its wait are recorded in order (a block's processes all start before the
    first is waited for: they run side by side)."""

    def __init__(self, code, fake):
        self.code, self.fake = code, fake
        self.number = len(fake.calls)
        fake.events.append(("start", self.number))

    def wait(self):
        self.fake.events.append(("wait", self.number))
        return self.code


def table(default_today=0.9, default_cand=0.9, default_other=0.1, extra=None):
    """value(our, foe): the start matrix of the README's arms, the other foe answers bad for the foe."""
    cells = {("today", "drawn"): 0.64, ("today", "15|23"): 0.34, ("today", "12|35"): 0.5,
             ("23|04", "drawn"): 0.70, ("23|04", "15|23"): 0.45, ("23|04", "12|35"): 0.27, **(extra or {})}

    def value(our, foe):
        if (our, foe) in cells:
            return Fraction(cells[(our, foe)]).limit_denominator(1000)
        return Fraction({"today": default_today, "23|04": default_cand}.get(our, default_other)).limit_denominator(1000)
    return value


class SeriesTest(unittest.TestCase):
    def run_series(self, fake, parallel=3, cpus=16, deadline=0):
        tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        out = os.path.join(tmp, "series")
        argv = ["--plan", "preview-mixed-2026-10-14", "--checkpoint", "n/c.npz", "--foe-net", "n/c.npz", "--ours",
                "data/teams/A.txt", "--foe", "t/f.txt", "--out", out, "--parallel", str(parallel),
                "--cpus-per-process", str(cpus), "--deadline-seconds", str(deadline)]
        with mock.patch.object(series, "_start", fake), mock.patch("sys.stdout"):
            code = series.main(argv)
        with open(os.path.join(out, "series.json"), encoding="utf-8") as f:
            return code, json.load(f), out

    def test_nothing_new_stops_after_round_one_and_the_final_measurement_runs(self):
        fake = Fake(table())
        code, record, out = self.run_series(fake)
        self.assertEqual(code, 0, record)
        self.assertEqual(record["status"], "done")
        self.assertTrue(record["equality"]["equal"])
        self.assertEqual(record["equality"]["beside"], ["15|23", "12|35"])
        self.assertIn("nothing beyond the matrix", record["stop"])
        self.assertEqual([r["round"] for r in record["rounds"]], [0, 1])
        self.assertTrue(all("seconds" in r for r in record["rounds"]))  # the measured time of every round
        self.assertEqual(record["rounds"][1]["screen_seeds"], ["0x2026101300000465", "0x2026101300000466"])
        final = record["final"]
        self.assertEqual(final["pairing"], "passed")
        self.assertEqual(len(final["answers"]), 5)
        self.assertIn(final["worst_case"]["result"].split(":")[0], ("holds", "fails"))
        self.assertIn("exploitability_minus_today", final["beside_without_reading"])
        # every process: at most three at once, each pinned to 16 CPUs of its own, 8 workers, the plan's seeds
        for cmd in fake.calls:
            self.assertEqual(cmd[:2], ["taskset", "-c"])
            self.assertIn(cmd[2], ("0-15", "16-31", "32-47"))
            self.assertEqual(cmd[cmd.index("--workers") + 1], "8")
            self.assertIn(cmd[cmd.index("--seed") + 1], ("0x2026101300000464", "0x2026101300000465",
                                                          "0x2026101300000466", "0x202610130000046d",
                                                          "0x202610130000046e"))
        pairs = {cmd[cmd.index("--seed") + 1]: cmd[cmd.index("--pairs") + 1] for cmd in fake.calls}
        self.assertEqual(pairs, {"0x2026101300000464": "64", "0x2026101300000465": "32", "0x2026101300000466": "32",
                                 "0x202610130000046d": "32", "0x202610130000046e": "256"})
        # the start matrix is the README's, merged from the parts; no part directory is left
        m0 = oracle.ladder._load_json(os.path.join(out, "matrix", "m0.json"))
        self.assertEqual((m0["rows"], m0["columns"]), (["today", "23|04"], ["drawn", "12|35", "15|23"]))
        self.assertEqual(m0["conditions"]["workers"], 8)
        self.assertFalse([d for d in os.listdir(os.path.join(out, "runs")) if d.endswith(".parts")])
        screen = oracle.ladder._load_json(os.path.join(out, "runs", "r1-foe", "oracle.json"))
        self.assertEqual(len(screen["ranking"]), 90)

    def test_a_better_answer_of_ours_is_added_and_the_gap_decides(self):
        # 01|23 is good against every foe answer but 45|23, which beats it: the rounds add both
        extra = {("01|23", f): 0.8 for f in ("drawn", "15|23", "12|35")}
        extra.update({("01|23", "45|23"): 0.05, ("today", "45|23"): 0.9, ("23|04", "45|23"): 0.9})
        fake = Fake(table(extra=extra))
        code, record, out = self.run_series(fake)
        self.assertEqual(code, 0, record)
        r1 = record["rounds"][1]
        self.assertEqual(r1["our_answer"], "01|23")
        self.assertIn("01|23", r1["rows"])
        for r in record["rounds"][1:]:
            if "gap_points" in r:
                self.assertGreaterEqual(r["gap_points"], 0.0)
        last = record["rounds"][-1]
        if "below 3" in record["stop"]:
            self.assertLess(last["gap_points"], 3)
        elif "nothing" in record["stop"]:
            self.assertEqual(last["new"], [])
        else:
            self.assertEqual((record["stop"], last["round"]), ("round 4: the last round", 4))
        # a new row plays every column, a new column every row: each cell once
        for row in last.get("rows", record["rounds"][-2].get("rows", [])):
            done = series.done_arms(os.path.join(out, "runs", "row-" + row.replace("|", "-")))
            self.assertEqual(done, set(last.get("columns", record["rounds"][-2].get("columns"))))

    def test_alone_and_beside_that_differ_stop_the_series(self):
        fake = Fake(table(), beside_differs=True)
        code, record, out = self.run_series(fake)
        self.assertEqual(code, series.EQUALITY_EXIT)
        self.assertEqual((record["status"], record["reason"]), ("refused", "beside_differs"))
        with open(os.path.join(out, "equality.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["differs"], ["decisions_sha256"])
        self.assertNotIn("rounds", [k for k, v in record.items() if v])  # no round ran

    def test_a_failing_run_and_another_worker_count_are_refused(self):
        code, record, _ = self.run_series(Fake(table(), fail="12|35"))
        self.assertEqual((code, record["reason"]), (series.FAILED_EXIT, "oracle_failed"))
        code, record, _ = self.run_series(Fake(table(), workers=4))
        self.assertEqual((code, record["reason"]), (series.FAILED_EXIT, "workers"))

    def test_one_process_without_pins(self):
        fake = Fake(table())
        code, record, _ = self.run_series(fake, parallel=1, cpus=0)
        self.assertEqual(code, 0, record)
        self.assertTrue(all(cmd[0] != "taskset" for cmd in fake.calls))
        self.assertEqual(record["equality"]["beside"], [])

    def test_the_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = ["--plan", "preview-mixed-2026-10-14", "--checkpoint", "c", "--foe-net", "c", "--ours", "o",
                    "--foe", "f"]
            with self.assertRaisesRegex(SystemExit, "give --resume"):
                series.main(base + ["--out", tmp])
            with self.assertRaisesRegex(SystemExit, "1 to 3"):
                series.main(base + ["--out", os.path.join(tmp, "x"), "--parallel", "4"])
            with self.assertRaises(SystemExit):
                series.main(["--plan", "other"] + base[2:] + ["--out", os.path.join(tmp, "y")])
            from duoforge_live.data import ROOT
            with self.assertRaisesRegex(SystemExit, "inside the repository"):
                series.main(base + ["--out", os.path.join(str(ROOT), "series-guard-test")])

    def test_the_beside_block_starts_its_three_processes_before_waiting_for_any(self):
        fake = Fake(table())
        code, record, _ = self.run_series(fake)
        self.assertEqual(code, 0, record)
        beside = [i for i, cmd in enumerate(fake.calls, 1) if "equality-beside" in cmd[cmd.index("--out") + 1]]
        (b,) = beside
        block = [b, b + 1, b + 2]  # the beside run, then the first row's two other cells: one batch
        starts = [fake.events.index(("start", n)) for n in block]
        waits = [fake.events.index(("wait", n)) for n in block]
        self.assertLess(max(starts), min(waits))  # all three run at once
        alone = [i for i, cmd in enumerate(fake.calls, 1) if "equality-alone" in cmd[cmd.index("--out") + 1]]
        (a,) = alone
        self.assertLess(fake.events.index(("wait", a)), fake.events.index(("start", a + 1)))  # alone: nothing beside

    def test_the_final_numbers_are_the_readmes_differences(self):
        import numpy as np
        fake = Fake(table())
        code, record, out = self.run_series(fake)
        self.assertEqual(code, 0, record)
        final = record["final"]
        mean = lambda run, arm: float(np.mean(oracle.ladder._load_json(  # noqa: E731
            oracle_arm(os.path.join(out, "runs", run), arm))["scores"]))
        best = final["answers"][0]
        self.assertAlmostEqual(final["worst_case"]["points"],
                               100 * (mean("final-confirm", best) - mean("final-today", "15|23")))
        self.assertAlmostEqual(final["gain"]["points"],
                               100 * (mean("final-confirm", "drawn") - mean("final-today", "drawn")))
        self.assertAlmostEqual(final["exploitability"]["points"],
                               100 * (mean("final-confirm", "drawn") - mean("final-confirm", best)))
        self.assertAlmostEqual(final["beside_without_reading"]["worst_case_vs_candidate"]["points"],
                               100 * (mean("final-confirm", best) - mean("final-23-04", "12|35")))
        self.assertEqual(final["book_candidate"], final["worst_case"]["95"][0] > -5 and final["gain"]["95"][0] > 0)
        self.assertEqual(final["best_confirmed"]["note"], "selected on stage-2 games, biased upward")
        self.assertIn("mix.foe", final["fallbacks"])

    def test_the_rounds_stop_exactly_by_the_rule(self):
        # The loop alone, with scripted screens and gaps: a gap of exactly 3 points does not stop it, one below does,
        # and without a stop the fourth round is the last.
        class Scripted(series.Series):
            def __init__(self, gaps, answers):
                self.gaps, self.answers, self.record, self.finals = list(gaps), list(answers), {"rounds": []}, []
                self.plan = series.PLANS["preview-mixed-2026-10-14"]

            def equality(self):
                pass

            def fill(self, name, rows, columns):
                pass

            def save(self):
                pass

            def mark(self, text):
                pass

            def matrix(self, rows, columns, name, previous=None):
                out = {"value_points": 50.0, "our_mix_text": "today:1", "foe_mix_text": "drawn:1"}
                if previous:
                    gap = self.gaps.pop(0)
                    out["previous"] = {"gap_exact": str(gap), "gap_points": float(gap) * 100}
                return out

            def screen(self, name, side, flag, mix, seed):
                foe, ours = self.answers[int(name.split("-")[0][1:]) - 1]
                return {"ranking": [foe if side == "foe" else ours]}, 0.0

            def final(self, mix):
                self.finals.append(mix)

        new = [("0%d|12" % k, "0%d|34" % k) for k in range(1, 6)]
        run = Scripted([Fraction(3, 100), Fraction(299, 10000)], new)
        run.run()
        self.assertEqual(run.record["stop"], "round 2: gap 2.99 points, below 3")
        run = Scripted([Fraction(3, 100)] * 4, new)
        run.run()
        self.assertEqual(run.record["stop"], "round 4: the last round")
        self.assertEqual([r["round"] for r in run.record["rounds"]], [0, 1, 2, 3, 4])
        self.assertEqual(run.record["final_matrix"], "m4")
        run = Scripted([], [("15|23", "23|04")])
        run.run()
        self.assertEqual(run.record["stop"], "round 1: the screens found nothing beyond the matrix")
        self.assertEqual(run.record["final_matrix"], "m0")

    def test_a_refusal_of_the_oracle_or_another_error_is_recorded(self):
        real = oracle.summarize
        calls = []

        def refusing(run_dir):
            calls.append(run_dir)
            if "row-23-04" in run_dir:
                raise SystemExit("the arms' foe previews differ: the arms are not paired")
            return real(run_dir)
        with mock.patch.object(series.oracle, "summarize", refusing):
            code, record, _ = self.run_series(Fake(table()))
        self.assertEqual((code, record["status"], record["reason"]), (series.FAILED_EXIT, "refused", "oracle_refused"))
        self.assertIn("not paired", record["message"])

        def failing(run_dir):
            raise KeyError("member 3: move 'Some Move' is not in the tables")
        with mock.patch.object(series.oracle, "summarize", failing):
            code, record, out = self.run_series(Fake(table()))
        self.assertEqual((code, record["status"], record["reason"], record["message"]),
                         (series.FAILED_EXIT, "failed", "error", "KeyError"))
        with open(os.path.join(out, "series.json"), encoding="utf-8") as f:
            self.assertNotIn("Some Move", f.read())  # an error's text could name a member of a team

    def test_a_dirty_checkout_or_the_deadline_is_refused(self):
        code, record, _ = self.run_series(Fake(table(), dirty=True))
        self.assertEqual((code, record["reason"]), (series.FAILED_EXIT, "dirty"))
        with mock.patch.object(series.time, "monotonic", side_effect=[0.0] + [10_000.0] * 1000):
            code, record, _ = self.run_series(Fake(table()), deadline=60)
        self.assertEqual((code, record["reason"]), (series.FAILED_EXIT, "deadline"))
        self.assertEqual(record["blocks"], [])  # no block started after the deadline

    def series_in(self, out, fake, resume=False):
        argv = ["--plan", "preview-mixed-2026-10-14", "--checkpoint", "n/c.npz", "--foe-net", "n/c.npz", "--ours",
                "data/teams/A.txt", "--foe", "t/f.txt", "--out", out, "--parallel", "3", "--cpus-per-process", "16"]
        with mock.patch.object(series, "_start", fake), mock.patch("sys.stdout"):
            code = series.main(argv + (["--resume"] if resume else []))
        with open(os.path.join(out, "series.json"), encoding="utf-8") as f:
            return code, json.load(f)

    def test_a_series_interrupted_after_a_round_and_resumed_ends_as_an_uninterrupted_one(self):
        # A spot interruption, simulated: the box dies in a block (its processes fail), the state is kept, a new launch
        # resumes. Same seeds, the finished arms are not played again, and the end is exactly the uninterrupted one's.
        extra = {("01|23", f): 0.8 for f in ("drawn", "15|23", "12|35")}
        extra.update({("01|23", "45|23"): 0.05, ("today", "45|23"): 0.9, ("23|04", "45|23"): 0.9})
        value = table(extra=extra)
        tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        whole = os.path.join(tmp, "whole")
        code, reference = self.series_in(whole, Fake(value))
        self.assertEqual(code, 0, reference)
        for seed in ("0x2026101300000466", "0x202610130000046d"):  # in round 1's second screen, in the final screen
            with self.subTest(seed=seed):
                out = os.path.join(tmp, "cut-" + seed[-3:])
                first = Fake(value, interrupt=seed)
                code, record = self.series_in(out, first)
                self.assertEqual((code, record["reason"]), (series.FAILED_EXIT, "oracle_failed"))
                runs = os.path.join(out, "runs")
                kept = {(d, a) for d in os.listdir(runs) if not d.endswith(".parts")
                        for a in series.done_arms(os.path.join(runs, d))}
                second = Fake(value)
                code, record = self.series_in(out, second, resume=True)
                self.assertEqual(code, 0, record)
                self.assertEqual(record["launches"][0]["reason"], "oracle_failed")
                for key in ("stop", "final_mix", "final_matrix"):
                    self.assertEqual(record[key], reference[key], key)
                self.assertEqual({k: v for k, v in record["final"].items() if k != "seconds"},
                                 {k: v for k, v in reference["final"].items() if k != "seconds"})
                self.assertEqual([{k: v for k, v in r.items() if k != "seconds"} for r in record["rounds"]],
                                 [{k: v for k, v in r.items() if k != "seconds"} for r in reference["rounds"]])
                for sub in ("matrix", "runs"):
                    for root, _, files in os.walk(os.path.join(whole, sub)):
                        for name in files:
                            if not name.endswith(".json"):
                                continue
                            rel = os.path.relpath(os.path.join(root, name), whole)
                            with open(os.path.join(whole, rel), encoding="utf-8") as a, \
                                    open(os.path.join(out, rel), encoding="utf-8") as b:
                                self.assertEqual(json.load(a), json.load(b), rel)
                # no arm kept from before the interruption is played again
                played = {(os.path.basename(os.path.dirname(c[c.index("--out") + 1]))[:-len(".parts")], arm)
                          for c in second.calls for arm in c[c.index("--arms") + 1].split(",")}
                self.assertTrue(kept)
                self.assertFalse(played & kept)
                self.assertFalse([d for d in os.listdir(os.path.join(out, "runs")) if d.endswith(".parts")])

    def test_resume_refuses_another_series_or_a_finished_one(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        out = os.path.join(tmp, "s")
        code, _ = self.series_in(out, Fake(table()))
        self.assertEqual(code, 0)
        with self.assertRaisesRegex(SystemExit, "is done"):
            self.series_in(out, Fake(table()), resume=True)
        with self.assertRaisesRegex(SystemExit, "holds no series.json"):
            self.series_in(os.path.join(tmp, "empty"), Fake(table()), resume=True)
        with self.assertRaisesRegex(SystemExit, "give --resume"):
            self.series_in(out, Fake(table()))
        with open(os.path.join(out, "series.json"), encoding="utf-8") as f:
            record = json.load(f)
        with open(os.path.join(out, "series.json"), "w", encoding="utf-8") as f:
            json.dump(dict(record, status="refused", parallel=1), f)
        with self.assertRaisesRegex(SystemExit, "parallel=1, not 3"):
            self.series_in(out, Fake(table()), resume=True)

    def test_a_batch_starts_only_if_one_as_long_as_the_longest_ends_before_the_deadline(self):
        args = series.parser().parse_args(["--plan", "preview-mixed-2026-10-14", "--checkpoint", "c", "--foe-net", "c",
                                           "--ours", "o", "--foe", "f", "--out", "unused", "--deadline-seconds", "60"])
        run = series.Series(args, series.PLANS[args.plan])
        run.save = lambda: None
        run.started, run.longest = 0.0, 20.0
        with mock.patch.object(series.time, "monotonic", return_value=30.0):
            run.run_jobs("ok", [])  # 30 s gone + 20 s at most: ends by 50 s
            run.longest = 40.0
            with self.assertRaisesRegex(series.SeriesError, "could end after the deadline"):
                run.run_jobs("late", [])  # 30 + 40 > 60: refused before it starts

    def test_the_plan_fixes_workers_and_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = ["--plan", "preview-mixed-2026-10-14", "--checkpoint", "c", "--foe-net", "c", "--ours", "o",
                    "--foe", "f"]
            for extra in (["--workers", "16"], ["--max-steps", "500"]):
                with self.assertRaisesRegex(SystemExit, "fixes --workers 8 and --max-steps 1000"):
                    series.main(base + ["--out", os.path.join(tmp, "x")] + extra)

    def test_the_aws_conf_builds_a_command_line_the_series_takes(self):
        import importlib.util
        from duoforge_live.data import ROOT
        spec = importlib.util.spec_from_file_location("oracle_conf", ROOT / "tools" / "cloud" / "aws_fuzz" / "oracle_conf.py")
        conf_tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(conf_tool)
        self.assertEqual(sorted(conf_tool.PLANS), sorted(series.PLANS))
        for name, fixed in conf_tool.PLANS.items():
            for key, value in fixed.items():
                self.assertEqual(series.PLANS[name][key], value, (name, key))
        with open(ROOT / "tools" / "cloud" / "aws_fuzz" / "campaigns" / "preview-mixed" / "campaign.conf",
                  encoding="utf-8") as f:
            conf = conf_tool.parse(f.read())
        argv = conf_tool.argv(conf, "/n", "/t", "/o") + ["--parallel", "3", "--cpus-per-process", "16",
                                                         "--deadline-seconds", "41400"]
        args = series.parser().parse_args(argv)
        self.assertEqual((args.plan, args.workers, args.max_steps, args.ours, args.parallel),
                         ("preview-mixed-2026-10-14", 8, 1000, "data/teams/A.txt", 3))

    def test_split_is_round_robin_and_keeps_order(self):
        self.assertEqual(series.split(list("abcdefg"), 3), [list("adg"), list("be"), list("cf")])
        self.assertEqual(series.split(["a"], 3), [["a"]])
        self.assertEqual(series.split([], 3), [])


if __name__ == "__main__":
    unittest.main()
