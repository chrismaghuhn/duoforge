#!/usr/bin/env python3
"""Offline tests of the P1 run tooling (tools/cloud/p1_pilot): p1_manifest.freeze and run.sh's
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

BASH = os.environ.get("DUOFORGE_BASH") or shutil.which("bash")


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
