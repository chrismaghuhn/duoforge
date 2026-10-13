"""D1's offline pass tool (duoforge_search.rm_offline): recorded decisions solved again by the LP and by CFR+."""
import json
import os
import tempfile
import unittest
from unittest import mock

import numpy as np

from duoforge_search import matrix, rm_offline


def _record(rng, w=4, k=3, m=3, kind="searched"):
    return {"kind": kind, "tables": rng.random((w, k, m)).astype(np.float32).astype(float).tolist(),
            "weights": (rng.random(w) + 0.1).tolist(), "foe_probs": (rng.random((w, m)) + 0.01).tolist(),
            "own_probs": (rng.random(k) + 0.01).tolist(), "u": float(rng.random()), "lam": 0.5}


class RMOffline(unittest.TestCase):
    def write(self, tmp, records):
        path = os.path.join(tmp, "step-bot-decisions.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return path

    def test_every_searched_decision_is_solved_and_counted(self):
        rng = np.random.default_rng(481)
        records = [_record(rng), {"kind": "team", "choice": 1}, _record(rng, 2, 4, 1), _record(rng, kind="forced"),
                   _record(rng, 16, 8, 8)]
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, records)
            rm_offline.main(["--decisions", path, "--out", os.path.join(tmp, "out")])
            with open(os.path.join(tmp, "out", "report.json"), encoding="utf-8") as f:
                report = json.load(f)
            with open(os.path.join(tmp, "out", "rows.jsonl"), encoding="utf-8") as f:
                rows = [json.loads(line) for line in f]
        self.assertEqual((report["decisions"], report["converged"], report["unconverged"]), (3, 3, 0))
        self.assertEqual([r["line"] for r in rows], [0, 2, 4])  # the searched ones, in order
        self.assertEqual(report["agree"]["ev"], 1.0)  # the ev row does not depend on the solver
        self.assertLessEqual(report["gap"]["q1"], matrix.RM_EPSILON)
        self.assertLessEqual(report["value_gap"]["q1"], matrix.RM_EPSILON + 1e-12)
        self.assertGreaterEqual(report["value_gap"]["q0.5"], -1e-12)  # the averages' guarantee lies below the value
        self.assertEqual(report["shapes"], {"16x8x8": 1, "2x4x1": 1, "4x3x3": 1})
        self.assertEqual(report["solved_by"][str(report["max_iterations"])], 1.0)

    def test_an_unconverged_decision_is_counted_by_name(self):
        rng = np.random.default_rng(7)
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, [_record(rng, 16, 8, 8)])
            rm_offline.main(["--decisions", path, "--out", os.path.join(tmp, "out"), "--max-iterations", "2"])
            with open(os.path.join(tmp, "out", "report.json"), encoding="utf-8") as f:
                report = json.load(f)
        self.assertEqual((report["decisions"], report["converged"], report["unconverged"]), (1, 0, 1))
        self.assertEqual(report["solved_by"]["2"], 0.0)

    def test_workers_give_the_rows_of_one_worker_in_order(self):
        # The pool takes the decisions a block at a time (bounded memory); the rows and their order stay those of one
        # worker, the seconds aside.
        rng = np.random.default_rng(11)
        records = [_record(rng) for _ in range(7)]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(rm_offline, "BLOCK", 2):
            path = self.write(tmp, records)
            runs = []
            for workers in ("1", "2"):
                out = os.path.join(tmp, f"out{workers}")
                rm_offline.main(["--decisions", path, "--out", out, "--workers", workers])
                with open(os.path.join(out, "rows.jsonl"), encoding="utf-8") as f:
                    runs.append([{k: v for k, v in json.loads(line).items() if not k.endswith("seconds")}
                                 for line in f])
        self.assertEqual(len(runs[0]), 7)
        self.assertEqual(runs[0], runs[1])

    def test_the_pool_never_reads_more_than_one_block_ahead(self):
        # Bounded memory: _bounded_map takes the next block of decisions only after the rows of the last one are out.
        read = []

        def items():
            for i in range(10):
                read.append(i)
                yield i

        class Pool:
            def map(self, fn, chunk, *args, chunksize):
                return [x * 10 for x in chunk]

        out = []
        for row in rm_offline._bounded_map(Pool(), items(), 3):
            out.append(row)
            self.assertLessEqual(len(read), len(out) + 3)  # at most the current block beyond the rows given out
        self.assertEqual(out, [x * 10 for x in range(10)])

    def test_every_and_limit_take_a_fixed_subsample(self):
        rng = np.random.default_rng(3)
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, [_record(rng) for _ in range(10)])
            got = [number for _, number, _ in rm_offline.decisions([path], limit=3, every=3)]
        self.assertEqual(got, [0, 3, 6])

    def test_the_output_stays_outside_the_repository(self):
        rng = np.random.default_rng(1)
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, [_record(rng)])
            inside = os.path.join(os.path.dirname(__file__), "rm-offline-out")
            with self.assertRaises(SystemExit):
                rm_offline.main(["--decisions", path, "--out", inside])
            self.assertFalse(os.path.exists(inside))


if __name__ == "__main__":
    unittest.main()
