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
              "ours_sha256_prefix": "a", "foe_sha256_prefix": "b", "registry": {}, "left_out": {}, "species": SPECIES,
              "commit": "c0ffee", "dirty": False, "library": "0.45.0", "encoders": {}, "sha256_prefix": {},
              "table_sha256": "t", "foe_lead": None, "cpu": "x"}


class Fake:
    """A stand-in for `python -m duoforge_search.preview_oracle`: from its arguments it writes conditions.json and an
    arm file per arm, our per-game scores from value(our, foe) (a mix's value is its weighted mean)."""

    def __init__(self, value, beside_differs=False, fail=None, workers=None):
        self.value, self.beside_differs, self.fail, self.workers = value, beside_differs, fail, workers
        self.calls, self.running, self.most = [], 0, 0

    def __call__(self, cmd, log_path, env):
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("fake\n")
        self.calls.append(cmd)
        opt = lambda k, d=None: cmd[cmd.index(k) + 1] if k in cmd else d  # noqa: E731
        out, side, arms = opt("--out"), opt("--side"), opt("--arms").split(",")
        pairs, seed = int(opt("--pairs")), opt("--seed")
        if self.fail and self.fail in arms:
            return Done(1)
        games = 2 * pairs
        our_arm, our_mix, foe_mix = opt("--our-arm"), opt("--our-mix"), opt("--foe-mix")
        workers = self.workers if self.workers is not None else int(opt("--workers"))
        c = dict(CONDITIONS, seed=seed, pairs=pairs, games=games, side=side, our_arm=our_arm, our_mix=our_mix,
                 foe_mix=foe_mix, workers=workers)
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
        return Done(0)


def oracle_arm(out, arm):
    return os.path.join(out, "arms", arm.replace("|", "-") + ".json")


class Done:
    def __init__(self, code):
        self.code = code

    def wait(self):
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
    def run_series(self, fake, parallel=3, cpus=16):
        tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        out = os.path.join(tmp, "series")
        argv = ["--plan", "preview-mixed-2026-10-14", "--checkpoint", "n/c.npz", "--foe-net", "n/c.npz", "--ours",
                "data/teams/A.txt", "--foe", "t/f.txt", "--out", out, "--parallel", str(parallel),
                "--cpus-per-process", str(cpus)]
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
        self.assertTrue("below 3" in record["stop"] and last["gap_points"] < 3 or "nothing" in record["stop"]
                        or "last round" in record["stop"], record["stop"])
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
            with self.assertRaisesRegex(SystemExit, "never resumed"):
                series.main(base + ["--out", tmp])
            with self.assertRaisesRegex(SystemExit, "1 to 3"):
                series.main(base + ["--out", os.path.join(tmp, "x"), "--parallel", "4"])
            with self.assertRaises(SystemExit):
                series.main(["--plan", "other"] + base[2:] + ["--out", os.path.join(tmp, "y")])
            from duoforge_live.data import ROOT
            with self.assertRaisesRegex(SystemExit, "inside the repository"):
                series.main(base + ["--out", os.path.join(str(ROOT), "series-guard-test")])

    def test_split_is_round_robin_and_keeps_order(self):
        self.assertEqual(series.split(list("abcdefg"), 3), [list("adg"), list("be"), list("cf")])
        self.assertEqual(series.split(["a"], 3), [["a"]])
        self.assertEqual(series.split([], 3), [])


if __name__ == "__main__":
    unittest.main()
