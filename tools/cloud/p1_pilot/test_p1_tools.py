#!/usr/bin/env python3
"""Offline tests of the P1 run tooling (tools/cloud/p1_pilot): p1_match.solve, p1_manifest.freeze and run.sh's
RUN_ID/RUN_PREFIX guard (run.sh --check-env: no file, no aws call). Standard library only; the guard tests need
bash on the PATH (Git Bash on Windows) and are skipped without it.

    python tools/cloud/p1_pilot/test_p1_tools.py
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import p1_manifest  # noqa: E402
import p1_match  # noqa: E402

BASH = os.environ.get("DUOFORGE_BASH") or shutil.which("bash")


def calibration(c_cpu=170.0, c_gpu=30.0, g_gpu=4.5, n=6, start_cpu=200.0, jit_gpu=10.0):
    """Synthetic log records of a calibration: n updates on the CPU (process 1), then n on the GPU (process 2)."""
    records, cpu, gpu, decisions = [], 0.0, 0.0, 0
    for u in range(1, 2 * n + 1):
        on_gpu = u > n
        first = u in (1, n + 1)
        cpu += (start_cpu if first else 0.0) + (c_gpu if on_gpu else c_cpu)
        gpu += (g_gpu + (jit_gpu if first else 0.0)) if on_gpu else 0.0
        decisions += 10000
        records.append({"update": u, "update_device": "default" if on_gpu else "cpu", "restart": first,
                        "ledger": {"cpu_core_seconds": cpu, "gpu_seconds": gpu}, "collect_s": 20.0,
                        "update_s": 1.0 if on_gpu else 9.0, "decisions": decisions})
    return records, {"cpu_core_seconds": cpu, "gpu_seconds": gpu}


class MatchSolveTest(unittest.TestCase):
    def test_feasible_share_hits_both_axes_together(self):
        records, spent = calibration()
        pilot = {"cpu_core_seconds": 40000.0, "gpu_seconds": 800.0}
        out, code = p1_match.solve(pilot, spent, records)
        self.assertEqual(code, 0, out["status"])
        q = out["q"]
        self.assertTrue(0.0 <= q <= 1.0)
        per_c = q * 30.0 + (1 - q) * 170.0
        updates = (pilot["cpu_core_seconds"] - spent["cpu_core_seconds"]) / per_c
        gpu_at_stop = spent["gpu_seconds"] + updates * q * 4.5
        self.assertAlmostEqual(gpu_at_stop, pilot["gpu_seconds"], places=6)
        self.assertAlmostEqual(out["forecast_gpu_at_cpu_stop"], pilot["gpu_seconds"], places=6)
        self.assertTrue(out["calibration_cap"]["ok"])
        flags = out["resume_flags"]
        self.assertEqual(flags[flags.index("--stop-cpu-core-seconds") + 1], "40000.000")
        self.assertEqual(flags[flags.index("--act-gpu-share") + 1], "0")
        self.assertIn("--minutes", flags)
        decay = int(flags[flags.index("--learning-rate-schedule") + 1].split(",")[1].split(":")[0])
        self.assertEqual(decay, int(0.9 * (12 + updates) * 10000))

    def test_warm_updates_skip_each_process_first_update(self):
        records, spent = calibration()
        out, _ = p1_match.solve({"cpu_core_seconds": 40000.0, "gpu_seconds": 800.0}, spent, records)
        self.assertEqual(out["per_update"]["warm_updates"], [5, 5])
        self.assertAlmostEqual(out["per_update"]["cpu_on_cpu"], 170.0)
        self.assertAlmostEqual(out["per_update"]["gpu_on_gpu"], 4.5)

    def test_q_above_one_is_infeasible(self):
        records, spent = calibration()
        # A GPU target far above what all-GPU updates reach before the CPU target: acting on the GPU would be needed.
        out, code = p1_match.solve({"cpu_core_seconds": 40000.0, "gpu_seconds": 30000.0}, spent, records)
        self.assertEqual(code, p1_match.INFEASIBLE)
        self.assertTrue(out["status"].startswith("INFEASIBLE"))

    def test_calibration_share_is_reported_not_a_stop(self):
        # Owner decision 2026-10-09 (the AWS run on 2be0afe3 stopped with 33): the calibration is the control's own compute,
        # charged in full; its share of the pilot is reported, and only the 5 % match of both totals binds.
        records, spent = calibration()
        # spent CPU ~2560 core-s and GPU ~47 s: a 10000/200 pilot makes both exceed 10 %.
        out, code = p1_match.solve({"cpu_core_seconds": 10000.0, "gpu_seconds": 200.0}, spent, records)
        self.assertEqual(code, p1_match.OK)
        self.assertEqual(out["calibration_cap"]["over"], ["cpu_core_seconds", "gpu_seconds"])
        self.assertFalse(out["calibration_cap"]["ok"])
        self.assertEqual(out["calibration_cap"]["binding"], False)
        self.assertEqual(out["status"], "OK")

    def test_no_warm_update_asks_for_more_calibration(self):
        records, spent = calibration()
        pilot = {"cpu_core_seconds": 4e4, "gpu_seconds": 800.0}
        out, code = p1_match.solve(pilot, spent, records[:6])  # no GPU block yet
        self.assertEqual((code, out["calibrate_more"]), (p1_match.CALIBRATE_MORE, ["gpu"]))
        # Every update a process's first (interrupts after each): no warm update on either device.
        cut = [dict(r, restart=True) for r in records]
        out, code = p1_match.solve(pilot, spent, cut)
        self.assertEqual((code, out["calibrate_more"]), (p1_match.CALIBRATE_MORE, ["cpu", "gpu"]))
        self.assertTrue(out["status"].startswith("CALIBRATE MORE"))

    def test_more_calibration_even_over_the_reported_share(self):
        records, spent = calibration()
        out, code = p1_match.solve({"cpu_core_seconds": 1e4, "gpu_seconds": 800.0}, spent, records[:6])
        self.assertEqual((code, out["calibrate_more"]), (p1_match.CALIBRATE_MORE, ["gpu"]))
        self.assertFalse(out["calibration_cap"]["ok"])

    def test_extra_calibration_decision(self):
        more = {"calibrate_more": ["cpu", "gpu"]}
        self.assertEqual(p1_match.extra_calibration(more, {}),
                         {"device": "cpu", "update_gpu_share": 0, "updates": 2})
        self.assertEqual(p1_match.extra_calibration({"calibrate_more": ["gpu"]}, {"cpu": 3, "gpu": 2}),
                         {"device": "gpu", "update_gpu_share": 1, "updates": 2})
        self.assertEqual(p1_match.extra_calibration(more, {"cpu": p1_match.MAX_EXTRA}), {"exhausted": "cpu"})
        self.assertEqual(p1_match.MAX_EXTRA, 3)

    def test_an_extra_block_gives_a_warm_update(self):
        # A CPU block cut after its first (JIT) update, then one extra block of EXTRA_UPDATES on the CPU.
        records, spent = calibration()
        cut = [dict(records[0])] + [dict(r, restart=True) if r["update"] == 7 else r for r in records[6:]]
        for i, r in enumerate(cut):
            r["update"] = i + 1
        _, code = p1_match.solve({"cpu_core_seconds": 4e4, "gpu_seconds": 800.0}, spent, cut)
        self.assertEqual(code, p1_match.CALIBRATE_MORE)
        extra = []
        for k in range(p1_match.EXTRA_UPDATES):
            last = cut[-1]
            extra.append({"update": last["update"] + 1, "update_device": "cpu", "restart": k == 0,
                          "ledger": {"cpu_core_seconds": last["ledger"]["cpu_core_seconds"] + 170.0,
                                     "gpu_seconds": last["ledger"]["gpu_seconds"]},
                          "collect_s": 20.0, "update_s": 9.0, "decisions": last["decisions"] + 10000})
            cut.append(extra[-1])
        out, code = p1_match.solve({"cpu_core_seconds": 4e4, "gpu_seconds": 800.0}, spent, cut)
        self.assertEqual(code, 0, out["status"])
        self.assertEqual(out["per_update"]["warm_updates"][0], 1)

    def test_main_writes_the_next_extra_block(self):
        d = tempfile.mkdtemp()
        try:
            records, spent = calibration()
            os.makedirs(os.path.join(d, "run"))
            with open(os.path.join(d, "run", "log.jsonl"), "w") as f:
                f.write(json.dumps({"init": {}}) + "\n")
                for r in records[:6]:
                    f.write(json.dumps({k: v for k, v in r.items() if k != "restart"}) + "\n")
            for name, value in (("pilot.json", {"cpu_core_seconds": 4e4, "gpu_seconds": 800.0}),
                                ("control.json", spent), ("extras.json", {"gpu": 1})):
                with open(os.path.join(d, name), "w") as f:
                    json.dump(value, f)
            out_path = os.path.join(d, "match.json")
            code = p1_match.main(["--pilot-ledger", os.path.join(d, "pilot.json"), "--control-run",
                                  os.path.join(d, "run"), "--control-ledger", os.path.join(d, "control.json"),
                                  "--extras", os.path.join(d, "extras.json"), "--out", out_path])
            with open(out_path) as f:
                out = json.load(f)
            self.assertEqual(code, p1_match.CALIBRATE_MORE)
            self.assertEqual(out["next_extra"], {"device": "gpu", "update_gpu_share": 1, "updates": 2})
            self.assertEqual(out["extra_calibration_blocks"], {"gpu": 1})
        finally:
            shutil.rmtree(d)


class FreezeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def freeze(self, smoke, ledger_cpu=None):
        path = os.path.join(self.dir, "smoke.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"complete": False, "games": 0, "targets": 0}) + "\n" + json.dumps(smoke) + "\n")
        ledger = None
        if ledger_cpu is not None:
            ledger = os.path.join(self.dir, "pilot.json")
            with open(ledger, "w") as f:
                json.dump({"cpu_core_seconds": ledger_cpu, "gpu_seconds": 0.0,
                           "phases": {"generate": {"cpu_core_seconds": ledger_cpu, "gpu_seconds": 0.0}}}, f)
        out = os.path.join(self.dir, "freeze.json")
        args = argparse.Namespace(smoke_json=path, ledger=ledger, cpu_budget=p1_manifest.CPU_BUDGET, out=out)
        code = p1_manifest.freeze(args)
        with open(out) as f:
            return code, json.load(f)

    def smoke(self, **kw):
        return {"complete": True, "games": 512, "targets": 534, "selected": 552, "work_exhausted": 0,
                "public_refusals": 18, "cuts": 0, "engine_unsupported": 0} | kw

    def test_go_freezes_the_rounds_formula(self):
        code, out = self.freeze(self.smoke(), ledger_cpu=200.0)
        self.assertEqual((code, out["status"]), (0, "GO"))
        t = 534 / 512
        self.assertEqual(out["rounds"], math.ceil(1.25 * 16384 / (512 * t)))
        self.assertEqual(out["rounds"], 39)
        self.assertAlmostEqual(out["forecast_generation_cpu_core_seconds"], 200.0 + 200.0 / 512 * 512 * 39)

    def test_t_zero_stops(self):
        code, out = self.freeze(self.smoke(targets=0))
        self.assertEqual((code, out["status"]), (20, "STOP"))

    def test_budget_forecast_stops(self):
        code, out = self.freeze(self.smoke(), ledger_cpu=1000.0)  # 1000 * 40 > 28800
        self.assertEqual((code, out["status"]), (21, "STOP"))

    def test_work_fallbacks_above_one_percent_stop(self):
        code, out = self.freeze(self.smoke(work_exhausted=6), ledger_cpu=200.0)  # 6/552 > 1 %
        self.assertEqual((code, out["status"]), (22, "STOP"))
        code, _ = self.freeze(self.smoke(work_exhausted=5), ledger_cpu=200.0)  # 5/552 < 1 %
        self.assertEqual(code, 0)

    def test_incomplete_smoke_is_refused(self):
        with self.assertRaises(SystemExit):
            self.freeze(self.smoke(complete=False))


@unittest.skipIf(BASH is None, "bash is not on the PATH")
class RunIdGuardTest(unittest.TestCase):
    def check(self, run_id, prefix, bucket="example-bucket"):
        env = {k: v for k, v in os.environ.items() if k not in ("BUCKET", "RUN_PREFIX", "RUN_ID")}
        env |= {"BUCKET": bucket, "RUN_PREFIX": prefix, "RUN_ID": run_id, "PATH": os.environ.get("PATH", "")}
        r = subprocess.run([BASH, os.path.join(HERE, "run.sh"), "--check-env"], env=env, capture_output=True,
                           text=True, timeout=60)
        return r.returncode

    def test_earlier_starts_must_be_this_run(self):
        work = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(work, "out", "run-info"))
            bash_path = subprocess.run([BASH, "-c", 'cd "$1" && pwd -P', "_", work], capture_output=True,
                                       text=True).stdout.strip()

            def check(**info):
                with open(os.path.join(work, "out", "run-info", "run-info-20261010T000000Z.json"), "w") as f:
                    json.dump({"mode": "run", "run_id": "run1", "work_dir": bash_path} | info, f, indent=1,
                              sort_keys=True)
                env = {k: v for k, v in os.environ.items()} | {"BUCKET": "b", "RUN_PREFIX": "p1/run1/",
                                                                 "RUN_ID": "run1", "WORK_DIR": work}
                return subprocess.run([BASH, os.path.join(HERE, "run.sh"), "--check-env"], env=env,
                                      capture_output=True, text=True, timeout=60).returncode

            self.assertEqual(check(), 0)
            self.assertEqual(check(run_id="run0"), 11)
            self.assertEqual(check(mode="dry", run_id="dry"), 11)
            self.assertEqual(check(work_dir="/elsewhere"), 11)
        finally:
            shutil.rmtree(work)

    def test_valid(self):
        self.assertEqual(self.check("20261010-a1", "p1/20261010-a1/"), 0)
        self.assertEqual(self.check("run.2", "p1/run.2/"), 0)

    def test_refused(self):
        for run_id, prefix in ((".hidden", "p1/.hidden/"), (".", "p1/./"), ("..", "p1/../"),
                               ("inputs", "p1/inputs/"), ("a/b", "p1/a/b/"), ("", "p1//"),
                               ("run1", "p1/run2/"), ("run1", "p1/run1"), ("run1", "run1/"), ("ru n", "p1/ru n/")):
            with self.subTest(run_id=run_id, prefix=prefix):
                self.assertEqual(self.check(run_id, prefix), 2)
        self.assertEqual(self.check("run1", "p1/run1/", bucket=""), 2)


if __name__ == "__main__":
    unittest.main()
