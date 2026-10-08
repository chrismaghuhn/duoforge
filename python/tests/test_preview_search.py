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


class FoeSensitiveModel(ToyModel):
    """Public foe HP/stages affect value; world-own stats affect the foe model."""
    def value(self, params, rows):
        col = features.FEATURE_NAMES.index
        return .5 * super().value(params, rows) + .25 * rows[:, col("foe.member0.hp")] + \
               .1 * rows[:, col("foe.pos0.stage.atk")]
    def apply(self, params, obs, slots, mask):
        pair, team, value = super().apply(params, obs, slots, mask)
        stat = obs[:, features.FEATURE_NAMES.index("own.member0.stat.atk")]
        team[:, 0] += stat
        team[:, 120] -= stat
        team -= np.log(np.exp(team).sum(axis=1))[:, None]
        return pair, team, value


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
                with mock.patch.object(preview, "decide", side_effect=AssertionError("k=1 must skip table")):
                    actions, _ = self.decide(search, root)
                self.assertEqual(actions.tolist(), [0])

    def test_world_and_choice_are_info_safe_and_worker_order_deterministic(self):
        setups = np.repeat(duoforge.reference_setups([0]), 2)
        setups["sides"][1, 1]["members"]["stat_points"] = 0
        with duoforge.Context() as context, duoforge.Batch(context, setups, 2, 42) as root:
            for mode in ("value", "turn1"):
                results = []
                for workers, envs in ((1, [0, 1]), (2, [1, 0])):
                    with self.make(context, mode=mode, workers=workers) as search, \
                            mock.patch.object(root._lib, "duoforge_battle_hypothesis", side_effect=AssertionError("oracle")), \
                            mock.patch.object(root, "encode", side_effect=AssertionError("true snapshot")):
                        search.model = FoeSensitiveModel()
                        per_env = {}
                        for e in envs:
                            actions, records = self.decide(search, root, [e])
                            per_env[e] = (actions.tobytes(), records[0]["tables"], records[0]["foe_probs"],
                                tuple(search.worlds.digest(w) for w in range(search.s)),
                                tuple(search.leaves.digest(w) for w in range(search.capacity)))
                        self.assertEqual(per_env[0], per_env[1])
                        results.append(per_env[0])
                self.assertEqual(*results)

    def test_foe_sensitive_model_reacts_to_known_stat_and_hp_changes(self):
        model = FoeSensitiveModel()
        rows = np.zeros((2, len(features.FEATURE_NAMES)), np.float32)
        rows[1, features.FEATURE_NAMES.index("foe.member0.hp")] = .5
        rows[1, features.FEATURE_NAMES.index("own.member0.stat.atk")] = .5
        pair, team, value = model.apply(None, rows, np.zeros((2, 2, 32, features.SLOT_FEATURES)), np.ones((2,32,32),bool))
        self.assertNotEqual(value[0], value[1])
        self.assertNotEqual(team[0,0], team[1,0])

    def test_digest_audit_detects_deliberately_injected_true_spread(self):
        setups = np.repeat(duoforge.reference_setups([0]), 2)
        setups["sides"][1,1]["members"]["stat_points"] = 0
        with duoforge.Context() as context, duoforge.Batch(context,setups,2,42) as roots:
            digests = []
            for e in (0,1):
                with self.make(context) as search:
                    search.model = FoeSensitiveModel()
                    build = search._build
                    def injected(record,hypotheses):
                        bad = hypotheses.copy()
                        bad["stat_points"] = setups["sides"][e,1]["members"]["stat_points"]
                        return build(record,bad)
                    with mock.patch.object(search,"_build",side_effect=injected):
                        self.decide(search,roots,[e])
                    digests.append(tuple(search.worlds.digest(w) for w in range(search.s)))
            self.assertNotEqual(*digests, "world comparison must expose an injected true-spread leak")

    def test_summary_reports_candidate_score_and_candidate_minus_raw(self):
        baseline = np.zeros(4,evaluate.RECORD)
        candidate = baseline.copy()
        candidate["result"] = 1
        baseline["result"] = -1
        result = preview_ab.summary(candidate,baseline,[],{},10)
        self.assertEqual(result["score"],1.)
        self.assertEqual(result["score_95"],[1.,1.])
        self.assertEqual(result["paired_vs_raw"]["score"],1.)
        self.assertEqual(result["paired_vs_raw"]["score_95"],[1.,1.])

    def test_both_searched_cohort_retains_partial_seat_clusters(self):
        value = np.zeros(4,evaluate.RECORD)
        turn1 = value.copy()
        turn1["result"] = [1,-1,0,1]
        def decisions(ids):
            return [{"env":e,"kind":"searched","boundary":"TEAM_SELECTION"} for e in ids]
        result = preview_ab.both_searched_difference(value,turn1,decisions(range(4)),decisions((0,2)),10)
        self.assertEqual(result["games"],2)
        self.assertEqual(result["score"],.25)
        self.assertEqual(result["status"],"conditional_on_both_modes_searched")
        empty = preview_ab.both_searched_difference(value,turn1,[],[],10)
        self.assertIsNone(empty["score_95"])

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

    def test_rollout_policy_padding_is_zero_at_fixed_capacity(self):
        with duoforge.Context() as context,duoforge.Batch(context,duoforge.reference_setups([0]),1,42) as roots, \
                self.make(context,mode="turn1",capacity=16) as search:
            apply = search.model.apply
            checked = []
            def capture(params,obs,slots,mask):
                if len(obs) == 32:
                    self.assertFalse(obs[16:].any())
                    self.assertFalse(slots[16:].any())
                    self.assertFalse(mask[16:].any())
                    checked.append(True)
                return apply(params,obs,slots,mask)
            with mock.patch.object(search.model,"apply",side_effect=capture):
                self.decide(search,roots)
            self.assertTrue(checked)

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
