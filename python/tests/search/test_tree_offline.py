"""D2's offline pass (duoforge_search.tree_offline; README docs/benchmarks/2026-10-14-depth-d2, plan step 10): the
predeclared bounds from streamed rows, and the shadow, which builds and solves each searched turn decision's depth-2
tree beside the played search without changing a move or a record of it."""
import os
os.environ["JAX_PLATFORMS"] = "cpu"

import json
import tempfile
import unittest

import numpy as np

import duoforge
from duoforge import _layout
from duoforge_search import foe_arena, honest, tree_offline
from python.tests.search.test_depth import DEPTH2, Depth, timeless

C = _layout.CONSTANTS


def _row(width, iterations, seconds=0.01, kind="searched", reason=None, converged=True):
    return {"width": width, "kind": kind, "reason": reason, "converged": converged, "iterations": iterations,
            "solve_seconds": seconds, "nodes": 4, "information_sets": 2, "merge_share": 0.5, "gap": 1e-4}


class Bounds(unittest.TestCase):
    def test_the_predeclared_rule(self):
        # seconds per iteration of exact powers of two, so the division is exact
        rows = [_row(2, 120, 0.001), _row(2, 333, 0.002), _row(4, 870, 870 * 2.0 ** -14), _row(4, 40, 40 * 2.0 ** -14)]
        b = tree_offline.bounds(rows, budget=0.4, timing_width=4)
        self.assertEqual(b["t_acc"], 1740)  # twice the largest count, up to a multiple of 10
        # p99 of the solve seconds per iteration at width 4: 2^-14 s; 0.4 s / 2^-14 = 6553.6, down to 6550
        self.assertEqual(b["t_time"], 6550)
        self.assertEqual(b["default"], 1740)
        self.assertEqual(b["iterations"]["2"]["max"], 333)
        self.assertEqual(b["decisions"], 4)

    def test_no_default_when_the_accuracy_bound_is_above_the_time_bound(self):
        rows = [_row(4, 900, 900 * 2.0 ** -10), _row(4, 100, 100 * 2.0 ** -10)]  # t_time 409.6 -> 400 < t_acc 1800
        b = tree_offline.bounds(rows, budget=0.4, timing_width=4)
        self.assertEqual((b["t_acc"], b["t_time"], b["default"]), (1800, 400, None))

    def test_an_unconverged_decision_leaves_the_accuracy_bound_undefined(self):
        rows = [_row(2, 100), _row(2, 50000, kind="unreconstructible", reason="solver_unconverged", converged=False)]
        b = tree_offline.bounds(rows, budget=0.4, timing_width=2)
        self.assertIsNone(b["t_acc"])
        self.assertIsNone(b["default"])
        self.assertEqual(b["unconverged"], 1)

    def test_refused_keys_are_counted_and_left_out(self):
        rows = [_row(2, 100), _row(2, None, kind="unreconstructible", reason="observation_key_refused",
                                   converged=None)]
        b = tree_offline.bounds(rows, budget=0.4, timing_width=2)
        self.assertEqual((b["observation_key_refused"], b["observation_key_refused_share"]), (1, 0.5))
        self.assertEqual(b["t_acc"], 200)

    def test_rows_are_read_streamed(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rows.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                for r in (_row(2, 10), _row(4, 20)):
                    f.write(json.dumps(r) + "\n")
            self.assertEqual([r["iterations"] for r in tree_offline.read_rows(path)], [10, 20])


class ShadowPlay(Depth):
    def turn(self, ctx, search):
        """The A/B/C preview and turn decisions of search (a decide wrapper): (actions, records)."""
        pool = duoforge.teams.load(ctx, ["A", "B", "C"])
        with duoforge.Batch(ctx, pool.setups(np.array([0, 1, 2]), np.array([1, 2, 0])), 2, 42) as roots:
            left = [honest.NO_STEP_LIMIT] * 3
            search.decide(roots, np.arange(3), np.zeros(3, np.int64), np.full(3, 123, np.uint64),
                          np.zeros(3, bool), steps_left=np.asarray(left))
            roots.query_factored()
            choices = np.zeros((3, 2), _layout.FACTORED_CHOICE)
            choices["picks"][:, :, :4] = np.arange(4, dtype=np.uint8)
            roots.step_factored(choices)
            roots.query_factored()
            return search.decide(roots, np.arange(3), np.zeros(3, np.int64), np.array([456, 457, 458], np.uint64),
                                 np.zeros(3, bool), steps_left=np.asarray(left))

    def searches(self, ctx, **settings):
        pool = duoforge.teams.load(ctx, ["A", "B", "C"])
        from duoforge_search import belief
        table = belief.SpreadTable.from_sides(pool.sides)
        return self.make(ctx, table=table, excluded=[1, 2, 0], **settings)

    def test_the_shadow_changes_no_move_and_streams_a_row_per_width(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, tempfile.TemporaryDirectory() as d:
            with self.searches(ctx, rule="ev") as alone:
                plain = self.turn(ctx, foe_arena.Timed(alone))
            path = os.path.join(d, "rows.jsonl")
            with self.searches(ctx, rule="ev") as primary, \
                    self.searches(ctx, rule="ev", **DEPTH2, k2=2, m2=2) as two, \
                    self.searches(ctx, rule="ev", **DEPTH2, k2=3, m2=3) as three, \
                    open(path, "w", encoding="utf-8") as out:
                shadow = tree_offline.Shadow(foe_arena.Timed(primary), {2: two, 3: three}, out)
                played = self.turn(ctx, shadow)
            rows = list(tree_offline.read_rows(path))
        self.assertEqual(played[0].tolist(), plain[0].tolist())  # the moves are the played search's
        self.assertEqual([{k: v for k, v in r.items() if k != "wall"} for r in timeless(played[1])],
                         [{k: v for k, v in r.items() if k != "wall"} for r in timeless(plain[1])])
        searched = [r for r in plain[1] if r["kind"] == "searched"]
        self.assertEqual(len(rows), 2 * len(searched))  # one row per width and searched turn decision
        self.assertEqual(sorted({r["width"] for r in rows}), [2, 3])
        for r in rows:
            self.assertIn(r["kind"], ("searched", "unreconstructible"))
            if r["kind"] == "searched":
                self.assertTrue(r["converged"])
                self.assertGreater(r["iterations"], 0)
                self.assertGreater(r["solve_seconds"], 0.0)
                for name in ("policy_seconds", "evaluate_seconds", "nodes", "information_sets", "merge_share",
                             "gap", "leaves", "choice_differs"):
                    self.assertIn(name, r)
            else:
                self.assertEqual(r["reason"], "observation_key_refused")

    def test_every_shadows_a_fixed_subsample(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rows.jsonl")
            with self.searches(ctx, rule="ev") as primary, \
                    self.searches(ctx, rule="ev", **DEPTH2) as two, open(path, "w", encoding="utf-8") as out:
                shadow = tree_offline.Shadow(foe_arena.Timed(primary), {2: two}, out, every=2)
                _, played = self.turn(ctx, shadow)
            rows = list(tree_offline.read_rows(path))
        searched = sum(r["kind"] == "searched" for r in played)
        self.assertEqual(len(rows), (searched + 1) // 2)  # the 1st, 3rd, ... searched decision


class TreeCosts(Depth):
    def test_a_depth_two_record_times_its_phases_and_depth_one_does_not(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            _, two = self.abc_turn(ctx, steps_left=honest.NO_STEP_LIMIT, **DEPTH2)
            _, one = self.abc_turn(ctx)
        for r in two:
            for name in tree_offline.PHASES:
                self.assertIn(name, r["cost"])
            if r["kind"] == "searched":
                self.assertGreater(r["cost"]["tree_solve"], 0.0)
                self.assertGreater(r["cost"]["tree_evaluate"], 0.0)
                self.assertGreater(r["cost"]["tree_policy"], 0.0)
        for r in one:
            self.assertFalse(any(name in r["cost"] for name in tree_offline.PHASES))


if __name__ == "__main__":
    unittest.main()
