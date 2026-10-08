"""Synthetic CPU policy and native worlds; no checkpoints or oracle inputs."""
import unittest
import tempfile
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

import duoforge
from duoforge import _layout, features, teams
from duoforge_learn import evaluate
from duoforge_search import arena, belief, honest, matrix, preview, preview_ab

C = _layout.CONSTANTS


class ToyModel:
    feature_names = features.FEATURE_NAMES
    def check(self, rows):
        pass
    def value(self, params, rows):
        return rows[:, features.FEATURE_NAMES.index("own.pos0.occupant.2")].copy()
    def apply(self, params, obs, slots, mask):
        pairs = np.where(mask.reshape(len(obs), -1), 0., -1e9)
        team = np.full((len(obs), 360), -60.)
        team[:, 0], team[:, 120] = np.log(.6), np.log(.4)
        return pairs, team, self.value(params, obs)
    def act(self, params, key, obs, slots, mask, is_team, greedy=False):
        pair, team, value = self.apply(params, obs, slots, mask)
        return np.where(is_team, team.argmax(axis=1), pair.argmax(axis=1)), np.zeros(len(obs)), value


class PreviewSearchTest(unittest.TestCase):
    def make(self, context, mode="value", capacity=4, workers=1, steps=16, k=2, rule="mix"):
        table = belief.SpreadTable.from_sides(duoforge.reference_setups([0])["sides"].reshape(-1))
        return honest.Honest(context, ToyModel(), None, features.ENCODER, 0, k=k, m=2, s=2,
                             rule=rule, capacity=capacity, workers=workers, table=table,
                             preview_mode=mode, preview_only=mode != "raw", preview_steps=steps)

    def decide(self, search, roots, envs=None, keys=None, seat=0):
        envs = list(range(roots.envs)) if envs is None else envs
        return search.decide(roots, envs, [seat] * len(envs), [9] * len(envs) if keys is None else keys, [False] * len(envs))

    def test_value_preview_changes_choice_and_is_certified_for_each_rule(self):
        for rule in ("nash", "ev", "mix"):
            with self.subTest(rule=rule), duoforge.Context() as context, \
                    duoforge.Batch(context, duoforge.reference_setups([0]), 1, 42) as root, self.make(context, rule=rule) as search:
                original = root.digest(0)
                actions, records = self.decide(search, root)
                self.assertEqual(int(actions[0]), 120)
                self.assertEqual(root.digest(0), original)
                record = records[0]
                self.assertTrue(record["changed"])
                self.assertEqual(record["raw"], 0)
                self.assertEqual(record["preview_eval"], "value")
                self.assertLessEqual(record["certificate_gap"], 1e-9)
                matrix.bayes_certify(np.array(record["tables"]), record["weights"], np.array(record["x"]),
                                     [np.array(y) for y in record["ys"]])
                self.assertEqual(record["own_teams"], [0, 120])

    def test_preview_default_raw_and_top_one_remain_raw(self):
        with duoforge.Context() as context, duoforge.Batch(context, duoforge.reference_setups([0]), 1, 42) as root:
            with self.make(context, mode="raw") as search:
                actions, records = self.decide(search, root)
                self.assertEqual(actions.tolist(), [0])
                self.assertEqual(records[0]["kind"], "team")
            with self.make(context, k=1) as search:
                actions, _ = self.decide(search, root)
                self.assertEqual(actions.tolist(), [0])

    def test_world_and_choice_are_info_safe_and_worker_order_deterministic(self):
        setups = np.repeat(duoforge.reference_setups([0]), 2)
        setups["sides"][1, 1]["members"]["stat_points"] = 0
        with duoforge.Context() as context, duoforge.Batch(context, setups, 2, 42) as root:
            results = []
            for workers, envs in ((1, [0, 1]), (2, [1, 0])):
                with self.make(context, workers=workers) as search, \
                        mock.patch.object(root._lib, "duoforge_battle_hypothesis", side_effect=AssertionError("oracle")), \
                        mock.patch.object(root, "encode", side_effect=AssertionError("true snapshot")):
                    actions, records = self.decide(search, root, envs)
                    results.append(actions.tobytes())
                    self.assertEqual(records[0]["tables"], records[1]["tables"])
                    self.assertEqual(search.last[0]["hypotheses"].tobytes(), search.last[1]["hypotheses"].tobytes())
            self.assertEqual(*results)

    def test_turn1_rollout_reaches_next_turn_and_never_advances_real_root(self):
        with duoforge.Context() as context, duoforge.Batch(context, duoforge.reference_setups([0]), 1, 42) as root, \
                self.make(context, mode="turn1", capacity=8) as search:
            original = root.digest(0)
            actions, records = self.decide(search, root)
            self.assertIn(int(actions[0]), (0, 120))
            self.assertEqual(root.digest(0), original)
            self.assertEqual(records[0]["preview_eval"], "turn1")
            search.leaves.query()
            for e in range(8):
                self.assertTrue(search.leaves.result(e) or int(search.leaves.observations[e, 0]["turn"]) > 1)

    def test_rollout_bound_is_counted_raw_fallback(self):
        with duoforge.Context() as context, duoforge.Batch(context, duoforge.reference_setups([0]), 1, 42) as root, \
                self.make(context, mode="turn1", steps=1) as search:
            # The native turn has a pivot: one prompt cannot finish it.
            actions, records = self.decide(search, root)
            self.assertEqual(actions.tolist(), [0])
            self.assertEqual(records[0]["causes"], ["preview_rollout_limit"])

    def test_preview_only_keeps_battle_decisions_raw(self):
        with duoforge.Context() as context, duoforge.Batch(context, duoforge.reference_setups([0]), 1, 42) as root, self.make(context) as search:
            self.decide(search, root)
            root.query()
            root.step(np.zeros((1, 2), np.uint16))
            actions, records = self.decide(search, root)
            self.assertIn(records[0]["kind"], ("raw", "forced"))
            self.assertEqual(int(actions[0]), records[0]["choice"])

    def test_top_ties_and_invalid_options(self):
        ids, _ = preview.top(np.zeros(360), 8)
        self.assertEqual(ids.tolist(), list(range(8)))
        with self.assertRaises(honest.SearchError):
            preview.top(np.zeros(1024), 8)
        with duoforge.Context() as context:
            with self.assertRaises(ValueError):
                self.make(context, mode="invalid")

    def test_private_measurement_smoke_pairs_modes_and_counts_actual_baseline_changes(self):
        with tempfile.TemporaryDirectory(prefix="duoforge_preview_ab_") as temp, duoforge.Context() as context:
            pool = teams.TeamPool.from_setups(("A", "B"), duoforge.reference_setups([0])["sides"][0])
            table = belief.SpreadTable.from_sides(pool.sides)
            candidate = evaluate.Player(ToyModel(), None, features.ENCODER, "toy")
            args = SimpleNamespace(out=temp, games=2, panel_games=2, workers=1, max_steps=2,
                agents=["E"], worlds=2, capacity=8, rollout_steps=16, resamples=10)
            reports = preview_ab.run(context, pool, candidate, {"R": candidate, "BC": candidate}, table, {}, args)
            self.assertEqual(reports["E-value-vs-R"]["preview_changed_share"], 1.)
            self.assertIn("E-turn1-minus-value-vs-R", reports)
            self.assertIn("E-value-vs-BC", reports)
            self.assertEqual(json.loads(Path(temp, "results.json").read_text()), arena._finite(reports))
            with self.assertRaisesRegex(ValueError, "empty"):
                preview_ab.run(context, pool, candidate, {}, table, {}, args)


if __name__ == "__main__":
    unittest.main()
