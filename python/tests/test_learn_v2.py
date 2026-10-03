"""duoforge.python.learn_v2: the JAX parts of Learner v2 (decision 0017).

Model v2 (masking, preset sizes, equivariance to roster and move order),
checkpoint widening, the league's opponent forward, resume and the ladder
across model versions. The NumPy parts are in test_learn_v2_numpy.py.
"""
import unittest

import numpy as np

import duoforge
from duoforge import features
from duoforge_learn import columns, policy
from duoforge_learn.selfplay import TEAM_TABLE

SEED = 0x2026100200000173


def _scenes():
    """(team-selection rows, turn rows) of real observations: obs, slots,
    mask and is_team of every player of 4 environments (A-B, A-A)."""
    with duoforge.Context() as ctx, duoforge.Batch(ctx, duoforge.reference_setups([0, 2, 0, 2]), 1, SEED) as b:
        b.query_factored()
        team = features.encode_batch(b.observations.reshape(-1), b.domains.reshape(-1))
        b.step_factored(duoforge.RandomPolicy(SEED, 4).choose_factored(b))
        b.query_factored()
        turn = features.encode_batch(b.observations.reshape(-1), b.domains.reshape(-1))
    return team, turn


def _permute_roster(obs, slots, perm):
    """The own roster permuted: old member k becomes member perm[k]."""
    cols = columns.columns()
    out = obs.copy()
    for group in (cols.member, cols.present, cols.species, cols.item, cols.ability, cols.nature, cols.moves,
                  cols.pp, cols.move_count):
        for k in range(6):
            out[:, group[0, perm[k]]] = obs[:, group[0, k]]
    for p in range(2):
        for k in range(6):
            out[:, cols.occupant[0, p, perm[k]]] = obs[:, cols.occupant[0, p, k]]
    s = slots.copy()
    r = cols.slot_reserve[0]
    switch = slots[..., features.SLOT_FEATURE_NAMES.index("kind.SWITCH")] == 1.0
    old = np.rint(slots[..., r] * 5).astype(np.int64)
    s[..., r] = np.where(switch, np.asarray(perm)[np.clip(old, 0, 5)] / 5, slots[..., r]).astype(np.float32)
    return out, s


class ModelV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import jax
        cls.jax = jax
        cls.team, cls.turn = _scenes()
        cls.model = policy.make(policy.v2_config("S"))
        cls.params = cls.model.init(jax.random.PRNGKey(3))

    def _apply(self, obs, slots, mask):
        return [np.asarray(x) for x in self.model.apply(self.params, obs, slots, mask)]

    def test_masked_pairs_get_no_probability(self):
        obs, slots, mask = self.turn
        one = np.zeros_like(mask)
        one[:, 2, 5] = True
        logp, _, _ = self._apply(obs, slots, one)
        prob = np.exp(logp.astype(np.float64))
        np.testing.assert_allclose(prob[:, 2 * 32 + 5], 1.0, atol=1e-6)
        self.assertEqual(float(prob.sum() - prob[:, 2 * 32 + 5].sum()), 0.0)

    def test_preset_parameter_counts(self):
        counts = {p: policy.make(policy.v2_config(p)).count(policy.make(policy.v2_config(p)).init(
            self.jax.random.PRNGKey(0))) for p in ("S", "M", "L")}
        self.assertEqual(counts, PRESET_COUNTS)
        for p, target in (("S", 0.35e6), ("M", 2e6), ("L", 8e6)):
            self.assertLess(abs(counts[p] - target) / target, 0.25, p)

    def test_roster_permutation_is_equivariant(self):
        perm = [3, 0, 5, 1, 4, 2]
        index = {tuple(t): i for i, t in enumerate(TEAM_TABLE.tolist())}
        moved = np.array([index[tuple(perm[k] for k in t)] for t in TEAM_TABLE.tolist()])
        for obs, slots, mask in (self.team, self.turn):
            pairs, team, value = self._apply(obs, slots, mask)
            obs2, slots2 = _permute_roster(obs, slots, perm)
            pairs2, team2, value2 = self._apply(obs2, slots2, mask)
            np.testing.assert_allclose(pairs2, pairs, atol=1e-4)
            np.testing.assert_allclose(team2[:, moved], team, atol=1e-4)
            np.testing.assert_allclose(value2, value, atol=1e-5)

    def test_move_permutation_is_equivariant(self):
        obs, slots, mask = self.turn
        cols = columns.columns()
        sigma = [2, 0, 3, 1]
        obs2, slots2 = obs.copy(), slots.copy()
        rows = np.flatnonzero(obs[:, cols.occupant[0, 0, :6]].max(axis=1) == 1.0)
        actor = np.argmax(obs[:, cols.occupant[0, 0, :6]], axis=1)
        for n in rows:
            a = actor[n]
            for k in range(4):
                obs2[n, cols.moves[0, a, sigma[k]]] = obs[n, cols.moves[0, a, k]]
                obs2[n, cols.pp[0, a, sigma[k]]] = obs[n, cols.pp[0, a, k]]
            m = cols.slot_move[0]
            move = slots[n, 0, :, features.SLOT_FEATURE_NAMES.index("kind.MOVE")] == 1.0
            k = np.rint(slots[n, 0, :, m] * 4).astype(np.int64)
            regular = move & (k < 4)
            slots2[n, 0, regular, m] = np.asarray(sigma)[k[regular]] / 4
        self.assertGreater(len(rows), 0)
        pairs, _, value = self._apply(obs, slots, mask)
        pairs2, _, value2 = self._apply(obs2, slots2, mask)
        np.testing.assert_allclose(pairs2, pairs, atol=1e-4)
        np.testing.assert_allclose(value2, value, atol=1e-5)

    def test_v1_still_acts(self):
        v1 = policy.make(dict(policy.V1_DEFAULT))
        params = v1.init(self.jax.random.PRNGKey(1))
        obs, slots, mask = self.turn
        is_team = np.zeros(obs.shape[0], dtype=bool)
        actions, logp, value = v1.act(params, self.jax.random.PRNGKey(2), obs, slots, mask, is_team)
        self.assertEqual(np.asarray(actions).shape, (obs.shape[0],))
        self.assertTrue(np.isfinite(np.asarray(logp)).all())

    def test_out_of_capacity_id_is_refused_before_the_forward(self):
        obs, slots, mask = self.turn
        bad = obs.copy()
        bad[0, columns.columns().species[1, 2]] = np.float32(2000 / 65535)
        with self.assertRaisesRegex(ValueError, "species id 2000"):
            self.model.act(self.params, self.jax.random.PRNGKey(0), bad, slots, mask,
                           np.zeros(obs.shape[0], dtype=bool))


class WideningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import jax
        cls.jax = jax
        cls.team, cls.turn = _scenes()

    def _widened_outputs(self, cfg):
        from duoforge_learn import checkpoint
        flags = [n for n in features.FEATURE_NAMES if n.endswith(".flag.follow_me")]
        keep = np.array([i for i, n in enumerate(features.FEATURE_NAMES) if n not in flags])
        old_names = [features.FEATURE_NAMES[i] for i in keep]
        old = policy.make(cfg, old_names, features.SLOT_FEATURE_NAMES)
        params = old.init(self.jax.random.PRNGKey(4))
        config = {"model": cfg, "features": old_names, "slot_features": list(features.SLOT_FEATURE_NAMES)}
        wide, _ = checkpoint.widen(params, config, features.FEATURE_NAMES, features.SLOT_FEATURE_NAMES)
        new = policy.make(cfg)
        obs, slots, mask = self.turn
        self.assertFalse(obs[:, [features.FEATURE_NAMES.index(n) for n in flags]].any())
        before = old.apply(params, obs[:, keep], slots, mask)
        after = new.apply(wide, obs, slots, mask)
        return before, after

    def test_widened_network_gives_identical_outputs(self):
        for cfg in (dict(policy.V1_DEFAULT), policy.v2_config("S")):
            before, after = self._widened_outputs(cfg)
            for x, y in zip(before, after):
                # Equal up to float32 rounding: a longer dot product may sum in another order.
                np.testing.assert_allclose(np.asarray(x), np.asarray(y), rtol=1e-6, atol=1e-6)

    def test_encoder_2_network_widens_to_encoder_3(self):
        # A network of encoder 2 (the 607 columns before encoder 3's block) widened by name to encoder 3: every
        # layer that reads encoder columns keeps its old rows exactly and gets zero rows for the block, so it gives
        # the same outputs wherever the block is zero (every kind but POOL; any battle under mask 0). Model v2
        # places the block's columns inside its layer inputs, so their products are summed in another order:
        # equal up to f32 rounding (measured: at most 1.5e-6 relative on the log-probabilities).
        from duoforge_learn import checkpoint
        old_names = list(features.feature_names(2))
        obs, slots, mask = self.turn
        self.assertFalse(obs[:, features.BASE_OBS_SIZE:].any())
        for cfg in (dict(policy.V1_DEFAULT), policy.v2_config("S")):
            old = policy.make(cfg, old_names, features.SLOT_FEATURE_NAMES)
            params = old.init(self.jax.random.PRNGKey(7))
            config = {"model": cfg, "features": old_names, "slot_features": list(features.SLOT_FEATURE_NAMES)}
            wide, _ = checkpoint.widen(params, config, features.FEATURE_NAMES, features.SLOT_FEATURE_NAMES)
            rows_old = checkpoint._rows(cfg, old_names, features.SLOT_FEATURE_NAMES)
            rows_new = checkpoint._rows(cfg, features.FEATURE_NAMES, features.SLOT_FEATURE_NAMES)
            added_rows = 0
            for path, labels in rows_old.items():
                index = {label: i for i, label in enumerate(rows_new[path])}
                w_new = np.asarray(checkpoint._get(wide, path)["w"])
                np.testing.assert_array_equal(w_new[[index[label] for label in labels]],
                                              np.asarray(checkpoint._get(params, path)["w"]))
                added = [i for label, i in index.items() if label not in set(labels)]
                self.assertFalse(w_new[added].any(), path)
                added_rows += len(added)
            self.assertGreaterEqual(added_rows, features.EXT_SIZE if cfg["version"] == 1 else 5 + 7 + 36 + 6)
            before = old.apply(params, obs[:, :features.BASE_OBS_SIZE], slots, mask)
            after = policy.make(cfg).apply(wide, obs, slots, mask)
            for x, y in zip(before, after):
                np.testing.assert_allclose(np.asarray(x), np.asarray(y), rtol=1e-5, atol=1e-6)

    def test_raised_capacity_appends_rows_and_keeps_outputs(self):
        from duoforge_learn import checkpoint
        cfg = policy.v2_config("S")
        m = policy.make(cfg)
        params = m.init(self.jax.random.PRNGKey(5))
        config = {"model": cfg, "features": list(features.FEATURE_NAMES),
                  "slot_features": list(features.SLOT_FEATURE_NAMES)}
        caps = dict(cfg["capacities"], species=1100)
        wide, wcfg = checkpoint.widen(params, config, features.FEATURE_NAMES, features.SLOT_FEATURE_NAMES,
                                      capacities=caps, seed=6)
        self.assertEqual(wide["species"].shape[0], 1100)
        np.testing.assert_array_equal(np.asarray(wide["species"][:1024]), np.asarray(params["species"]))
        obs, slots, mask = self.turn
        for x, y in zip(m.apply(params, obs, slots, mask), policy.make(wcfg["model"]).apply(wide, obs, slots, mask)):
            np.testing.assert_array_equal(np.asarray(x), np.asarray(y))
        zeros = self.jax.tree_util.tree_map(np.zeros_like, params)
        moments, _ = checkpoint.widen(zeros, config, features.FEATURE_NAMES, features.SLOT_FEATURE_NAMES,
                                      capacities=caps, fill="zeros")
        self.assertFalse(np.asarray(moments["species"][1024:]).any())


class TrainingV2Test(unittest.TestCase):
    def test_training_runs_with_model_v2(self):
        import json
        import os
        import shutil
        import tempfile
        from duoforge_learn import checkpoint, train
        out = tempfile.mkdtemp(prefix="duoforge-learn-v2-")
        try:
            code = train.main(["--envs", "8", "--workers", "2", "--rollout", "8", "--updates", "2", "--minutes", "0",
                               "--eval-every", "1", "--minibatch", "256", "--model", "v2",
                               "--preset", "S", "--hidden", "64", "--out", out])
            self.assertEqual(code, 0)
            with open(os.path.join(out, "log.jsonl"), encoding="utf-8") as f:
                records = [json.loads(line) for line in f]
            self.assertEqual([r["update"] for r in records], [1, 2])
            for r in records:
                for k in ("t_engine", "t_encode", "t_policy", "t_other", "t_transfer", "t_compute"):
                    self.assertGreaterEqual(r[k], 0.0, k)
                self.assertLessEqual(r["t_engine"] + r["t_encode"] + r["t_policy"], r["collect_s"] + 1e-3)
            params, config = checkpoint.load(os.path.join(out, "params-2.npz"))
            self.assertEqual(config["format"], 2)
            self.assertEqual(config["model"]["version"], 2)
            self.assertEqual(config["model"]["hidden"], 64)
            self.assertEqual(config["encoder"], features.ENCODER)
            self.assertEqual(config["ext_supported"], 0)  # CLOSURE: the library supports no feature there
            self.assertEqual(config["features"], list(features.FEATURE_NAMES))
            model = policy.make(config["model"], config["features"], config["slot_features"])
            self.assertEqual(model.count(params), model.count(model.init(__import__("jax").random.PRNGKey(0))))
        finally:
            shutil.rmtree(out, ignore_errors=True)


class LeagueJaxTest(unittest.TestCase):
    def test_opponents_use_each_rows_slot(self):
        import jax
        from duoforge_learn import league
        _, turn = _scenes()
        obs, slots, mask = turn
        is_team = np.zeros(obs.shape[0], dtype=bool)
        m = policy.make(policy.v2_config("S", hidden=32))
        a, b = m.init(jax.random.PRNGKey(10)), m.init(jax.random.PRNGKey(11))
        # Peaked, opposite option scores, so the two slots choose differently.
        a["option_out"]["w"] = a["option_out"]["w"] * 1e4
        b["option_out"]["w"] = a["option_out"]["w"] * -1.0
        opp = league.Opponents(m, 2)
        opp.set(0, a)
        opp.set(1, b)
        slot = np.arange(obs.shape[0]) % 2
        key = jax.random.PRNGKey(12)
        got = opp.act(key, obs, slots, mask, is_team, slot)
        want_a = np.asarray(m.act(a, key, obs, slots, mask, is_team)[0])
        want_b = np.asarray(m.act(b, key, obs, slots, mask, is_team)[0])
        self.assertGreater(int((want_a != want_b).sum()), obs.shape[0] // 4)
        np.testing.assert_array_equal(got, np.where(slot == 0, want_a, want_b))

    def test_training_with_league_excludes_opponent_rows(self):
        import json
        import os
        import shutil
        import tempfile
        from duoforge_learn import train
        out = tempfile.mkdtemp(prefix="duoforge-league-")
        try:
            code = train.main(["--envs", "8", "--workers", "2", "--rollout", "8", "--updates", "3", "--minutes", "0",
                               "--eval-every", "3", "--minibatch", "256", "--self-play-share",
                               "0.5", "--league-slots", "2", "--snapshot-every", "1", "--slot-refresh", "1",
                               "--out", out])
            self.assertEqual(code, 0)
            with open(os.path.join(out, "log.jsonl"), encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.startswith('{"update"')]
            for r in records:
                self.assertGreater(r["policy_rows"], 0)
                self.assertLess(r["policy_rows"], r["acted_rows"])
            self.assertTrue(os.path.isfile(os.path.join(out, "params-0.npz")))
            self.assertIn("league", records[-1])
        finally:
            shutil.rmtree(out, ignore_errors=True)


class ScheduleTrainingTest(unittest.TestCase):
    def test_entropy_schedule_is_logged(self):
        import json
        import os
        import shutil
        import tempfile
        from duoforge_learn import schedule, train
        out = tempfile.mkdtemp(prefix="duoforge-schedule-")
        try:
            code = train.main(["--envs", "8", "--workers", "2", "--rollout", "8", "--updates", "3", "--minutes", "0",
                               "--eval-every", "3", "--minibatch", "256",
                               "--entropy", "0:0.05,1K:0", "--out", out])
            self.assertEqual(code, 0)
            with open(os.path.join(out, "log.jsonl"), encoding="utf-8") as f:
                records = [json.loads(line) for line in f]
            plan = schedule.Schedule.parse("0:0.05,1K:0")
            seen = 0
            for r in records:
                self.assertAlmostEqual(r["entropy_coef"], plan(seen), places=6)
                seen = r["decisions"]
            self.assertGreater(records[0]["entropy_coef"], records[-1]["entropy_coef"])
        finally:
            shutil.rmtree(out, ignore_errors=True)


class RunStateJaxTest(unittest.TestCase):
    def test_adam_state_round_trip(self):
        import tempfile
        import jax
        from duoforge_learn import ppo, runstate
        m = policy.make(policy.v2_config("S", hidden=32))
        params = m.init(jax.random.PRNGKey(20))
        tx = ppo.optimizer(3e-4)
        opt = tx.init(params)
        grads = jax.tree_util.tree_map(lambda x: x * 0 + 0.5, params)
        _, opt = tx.update(grads, opt, params)
        state = {"params": params, "opt_leaves": jax.tree_util.tree_leaves(opt),
                 "episodes_seen": np.zeros(2, dtype=np.int64), "jax_key": np.asarray(jax.random.PRNGKey(1))}
        with tempfile.TemporaryDirectory() as d:
            runstate.save_state(d, state)
            back = runstate.load_state(d)
        restored = runstate.restore_opt(tx, back["params"], back["opt_leaves"])
        for a, b in zip(jax.tree_util.tree_leaves(opt), jax.tree_util.tree_leaves(restored)):
            np.testing.assert_array_equal(np.asarray(a), np.asarray(b))
        with self.assertRaisesRegex(ValueError, "does not fit"):
            runstate.restore_opt(tx, back["params"], back["opt_leaves"][:-1])


_SMALL = ["--workers", "2", "--rollout", "8", "--minutes", "0", "--eval-every", "100", "--minibatch", "256", "--snapshot-every", "1", "--slot-refresh", "1", "--league-slots", "2"]


def _run(argv, pool=None, on_start=None):
    from duoforge_learn import train
    return train.run(train.parse(argv), pool=pool, on_start=on_start)


def _log(out):
    import json
    import os
    with open(os.path.join(out, "log.jsonl"), encoding="utf-8") as f:
        return [json.loads(line) for line in f]


class ResumeTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.out = tempfile.mkdtemp(prefix="duoforge-resume-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.out, ignore_errors=True)

    def test_resume_continues_counters(self):
        from duoforge_learn import runstate
        self.assertEqual(_run(["--envs", "8", "--updates", "2", "--out", self.out] + _SMALL), 0)
        first = runstate.load_state(self.out)["counters"]
        self.assertEqual(first["update"], 2)
        self.assertEqual(_run(["--resume", self.out, "--updates", "3"]), 0)
        records = _log(self.out)
        self.assertEqual([r.get("update") for r in records if "update" in r], [1, 2, 3])
        resume = [r for r in records if "resume" in r]
        self.assertEqual(len(resume), 1)
        self.assertEqual(resume[0]["resume"]["updates"], [2, 3])
        last = [r for r in records if "update" in r][-1]
        self.assertGreater(last["decisions"], first["decisions"])

    def test_shrinking_then_growing_envs_never_repeats_an_episode(self):
        seen = []

        def hook(envs, episodes):
            seen.extend(zip(np.asarray(envs).tolist(), np.asarray(episodes).tolist()))

        self.assertEqual(_run(["--envs", "8", "--updates", "2", "--out", self.out] + _SMALL, on_start=hook), 0)
        self.assertEqual(_run(["--resume", self.out, "--envs", "4", "--updates", "3"], on_start=hook), 0)
        self.assertEqual(_run(["--resume", self.out, "--envs", "8", "--updates", "4"], on_start=hook), 0)
        self.assertEqual(len(seen), len(set(seen)))
        self.assertTrue(any(e >= 4 for e, k in seen[-40:]))

    def test_changed_team_is_refused(self):
        from duoforge_learn import runstate
        self.assertEqual(_run(["--envs", "8", "--updates", "1", "--out", self.out] + _SMALL), 0)
        state = runstate.load_state(self.out)
        state["teams"]["sha256"][0] = "0" * 64
        runstate.save_state(self.out, state)
        with self.assertRaisesRegex(SystemExit, "team A"):
            _run(["--resume", self.out, "--updates", "2"])

    def test_changed_ext_supported_is_refused(self):
        # A resumed run keeps the view-extension mask it trained with; another one on the command line is refused.
        self.assertEqual(_run(["--envs", "8", "--updates", "1", "--out", self.out] + _SMALL), 0)
        with self.assertRaisesRegex(SystemExit, "ext_supported"):
            _run(["--resume", self.out, "--updates", "2", "--ext-supported", "0x1"])

    def test_resume_keeps_its_ext_supported(self):
        # A plain resume uses the mask the run resolved when it started, not the library's current one (here a
        # strict subset of it, as if the library had gained a bit since); an explicit --ext-supported equal to it
        # is no change. A stored mask with a bit the library lacks is refused like a given one.
        from duoforge_learn import runstate
        pool = ["--teams", "A,B", "--data-kind", "pool"]
        self.assertEqual(_run(["--envs", "8", "--updates", "1", "--out", self.out] + pool + _SMALL), 0)
        state = runstate.load_state(self.out)
        library = state["ext_supported"]
        self.assertTrue(library)  # POOL: the library supports features
        subset = library & ~(library & -library)
        state["ext_supported"] = subset
        runstate.save_state(self.out, state)
        self.assertEqual(_run(["--resume", self.out, "--updates", "2"]), 0)
        self.assertEqual(runstate.load_state(self.out)["ext_supported"], subset)
        self.assertEqual(_run(["--resume", self.out, "--updates", "3", "--ext-supported", hex(subset)]), 0)
        self.assertNotIn("ext_supported", [r for r in _log(self.out) if "resume" in r][-1]["resume"])
        state = runstate.load_state(self.out)
        lacking = features.ALL_FEATURES & ~library
        state["ext_supported"] = library | (lacking & -lacking)
        runstate.save_state(self.out, state)
        with self.assertRaisesRegex(ValueError, "does not support"):
            _run(["--resume", self.out, "--updates", "4"])

    def test_refused_option_names_itself(self):
        self.assertEqual(_run(["--envs", "8", "--updates", "1", "--out", self.out] + _SMALL), 0)
        with self.assertRaisesRegex(SystemExit, "learning_rate"):
            _run(["--resume", self.out, "--updates", "2", "--learning-rate", "0.001"])

    def test_added_team_is_sampled(self):
        sides = duoforge.reference_setups([0])["sides"][0]
        two = duoforge.teams.TeamPool.from_setups(("A", "B"), sides)
        three = duoforge.teams.TeamPool.from_setups(("A", "B", "A2"), np.concatenate([sides, sides[:1]]))
        self.assertEqual(_run(["--envs", "8", "--updates", "1", "--out", self.out] + _SMALL, pool=two), 0)
        self.assertEqual(_run(["--resume", self.out, "--updates", "4"], pool=three), 0)
        records = [r for r in _log(self.out) if "update" in r]
        self.assertEqual(len(records[-1]["team_episodes"]), 3)
        self.assertGreater(sum(r["team_episodes"][2] for r in records[1:]), 0)
        resume = [r for r in _log(self.out) if "resume" in r][0]["resume"]
        self.assertEqual(resume["teams"], [["A", "B"], ["A", "B", "A2"]])

    def test_resume_with_a_wider_layout(self):
        import jax
        from duoforge_learn import ppo, train
        flags = [n for n in features.FEATURE_NAMES if n.endswith(".flag.follow_me")]
        old_names = [n for n in features.FEATURE_NAMES if n not in flags]
        cfg = dict(policy.V1_DEFAULT)
        net = policy.make(cfg, old_names, features.SLOT_FEATURE_NAMES)
        params = net.init(jax.random.PRNGKey(30))
        tx = ppo.optimizer(3e-4)
        opt = tx.init(params)
        grads = jax.tree_util.tree_map(lambda x: x * 0 + 1.0, params)
        _, opt = tx.update(grads, opt, params)
        wide, wide_opt = train._widen_state(params, jax.tree_util.tree_leaves(opt), cfg, old_names,
                                            features.SLOT_FEATURE_NAMES, tx)
        rows = [features.FEATURE_NAMES.index(n) for n in flags]
        self.assertFalse(np.asarray(wide["t1"]["w"])[rows].any())
        mu = wide_opt[1][0].mu["t1"]["w"]
        self.assertFalse(np.asarray(mu)[rows].any())
        self.assertTrue(np.asarray(mu).any())
        self.assertEqual(int(wide_opt[1][0].count), int(opt[1][0].count))

    def test_resume_from_a_run_without_league_into_a_league(self):
        self.assertEqual(_run(["--envs", "8", "--updates", "1", "--self-play-share", "1.0", "--out", self.out]
                              + _SMALL), 0)
        self.assertEqual(_run(["--resume", self.out, "--updates", "3", "--self-play-share", "0.5"]), 0)
        records = [r for r in _log(self.out) if "update" in r]
        self.assertEqual(records[-1]["update"], 3)
        self.assertLess(records[-1]["policy_rows"], records[-1]["acted_rows"])

    def test_unclean_stop_moves_newer_snapshots_aside(self):
        import os
        import shutil
        self.assertEqual(_run(["--envs", "8", "--updates", "2", "--out", self.out] + _SMALL), 0)
        # As if the run had gone on to update 7 and died without saving its state.
        shutil.copy(os.path.join(self.out, "params-2.npz"), os.path.join(self.out, "params-7.npz"))
        self.assertEqual(_run(["--resume", self.out, "--updates", "3"]), 0)
        self.assertFalse(os.path.exists(os.path.join(self.out, "params-7.npz")))
        resume = [r for r in _log(self.out) if "resume" in r][0]
        self.assertEqual(resume["abandoned_snapshots"], [7])
        self.assertTrue(os.path.isfile(os.path.join(self.out, resume["abandoned_dir"], "params-7.npz")))

    def test_resume_after_a_narrower_layout_plays_league_and_evaluation(self):
        import os
        import jax
        from duoforge_learn import checkpoint, ppo, runstate
        self.assertEqual(_run(["--envs", "8", "--updates", "2", "--eval-every", "1", "--out", self.out]
                              + [a for a in _SMALL if a not in ("--eval-every", "100")]), 0)
        flags = [n for n in features.FEATURE_NAMES if n.endswith(".flag.follow_me")]
        keep = np.array([i for i, n in enumerate(features.FEATURE_NAMES) if n not in flags])
        old_names = [features.FEATURE_NAMES[i] for i in keep]

        def narrow(tree):
            out = jax.tree_util.tree_map(np.asarray, tree)
            out["t1"]["w"] = out["t1"]["w"][keep]
            return out

        # Turn the run into one of an encoder that lacked the four follow_me columns.
        state = runstate.load_state(self.out)
        tx = ppo.optimizer(state["train"]["learning_rate"])
        opt = runstate.restore_opt(tx, state["params"], state["opt_leaves"])
        like = jax.tree_util.tree_structure(state["params"])
        opt = jax.tree_util.tree_map(lambda n: narrow(n) if jax.tree_util.tree_structure(n) == like else n, opt,
                                     is_leaf=lambda n: jax.tree_util.tree_structure(n) == like)
        state["params"] = narrow(state["params"])
        state["opt_leaves"] = jax.tree_util.tree_leaves(opt)
        state["features"] = old_names
        runstate.save_state(self.out, state)
        for f in os.listdir(self.out):
            if f.startswith("params-") and f.endswith(".npz"):
                params, config = checkpoint.load(os.path.join(self.out, f))
                checkpoint.save(os.path.join(self.out, f), narrow(params), dict(config, features=old_names))
        self.assertEqual(_run(["--resume", self.out, "--updates", "4", "--slot-refresh", "1"]), 0)
        records = [r for r in _log(self.out) if "update" in r]
        self.assertEqual(records[-1]["update"], 4)
        self.assertIn("vs_previous", records[-1])

    def test_resume_of_an_encoder_2_run_continues_on_encoder_3(self):
        # A run of encoder 2 (607 columns, no mask) resumes on encoder 3: parameters, Adam moments, league
        # snapshots and the evaluation opponent widen by name, the mask stays 0, and the resume says so.
        import os
        import jax
        from duoforge_learn import checkpoint, ppo, runstate
        self.assertEqual(_run(["--envs", "8", "--updates", "2", "--eval-every", "1", "--out", self.out]
                              + [a for a in _SMALL if a not in ("--eval-every", "100")]), 0)
        keep = np.arange(features.BASE_OBS_SIZE)
        old_names = list(features.feature_names(2))

        def narrow(tree):
            out = jax.tree_util.tree_map(np.asarray, tree)
            out["t1"]["w"] = out["t1"]["w"][keep]
            return out

        state = runstate.load_state(self.out)
        tx = ppo.optimizer(state["train"]["learning_rate"])
        opt = runstate.restore_opt(tx, state["params"], state["opt_leaves"])
        like = jax.tree_util.tree_structure(state["params"])
        opt = jax.tree_util.tree_map(lambda n: narrow(n) if jax.tree_util.tree_structure(n) == like else n, opt,
                                     is_leaf=lambda n: jax.tree_util.tree_structure(n) == like)
        state["params"] = narrow(state["params"])
        state["opt_leaves"] = jax.tree_util.tree_leaves(opt)
        state["features"], state["encoder"] = old_names, 2
        state.pop("ext_supported")
        runstate.save_state(self.out, state)
        for f in os.listdir(self.out):
            if f.startswith("params-") and f.endswith(".npz"):
                params, config = checkpoint.load(os.path.join(self.out, f))
                config = {k: v for k, v in config.items() if k != "ext_supported"}
                checkpoint.save(os.path.join(self.out, f), narrow(params), dict(config, features=old_names, encoder=2))
        self.assertEqual(_run(["--resume", self.out, "--updates", "4", "--slot-refresh", "1"]), 0)
        records = [r for r in _log(self.out) if "update" in r]
        self.assertEqual(records[-1]["update"], 4)
        self.assertIn("vs_previous", records[-1])
        resume = [r for r in _log(self.out) if "resume" in r][0]["resume"]
        self.assertEqual(resume["encoder"], [2, 3])
        state = runstate.load_state(self.out)
        self.assertEqual((state["encoder"], state["ext_supported"]), (3, 0))
        self.assertEqual(state["features"], list(features.FEATURE_NAMES))
        params, config = checkpoint.load_current(os.path.join(self.out, "params-0.npz"))  # narrowed above
        self.assertEqual((config["encoder"], params["t1"]["w"].shape[0]), (3, features.OBS_SIZE))

    def test_sigterm_leaves_a_loadable_state(self):
        import os
        import signal
        import subprocess
        import sys
        from duoforge_learn import runstate
        env = dict(os.environ)
        proc = subprocess.Popen([sys.executable, "-m", "duoforge_learn.train", "--envs", "8", "--minutes", "5",
                                 "--out", self.out] + [a for a in _SMALL if a not in ("--minutes", "0")],
                                stdout=subprocess.PIPE, text=True, env=env)
        try:
            for line in proc.stdout:
                if line.startswith('{"update"'):
                    break
            proc.send_signal(signal.SIGTERM)
            self.assertEqual(proc.wait(timeout=60), 0)
        finally:
            if proc.poll() is None:
                proc.kill()
        self.assertGreaterEqual(runstate.load_state(self.out)["counters"]["update"], 1)


class LadderV2Test(unittest.TestCase):
    def test_ladder_over_v1_and_v2_writes_both_files(self):
        import json
        import os
        import shutil
        import tempfile
        from duoforge_learn import ladder, train
        root = tempfile.mkdtemp(prefix="duoforge-ladder-v2-")
        try:
            runs = []
            for name, extra in (("v1", ["--model", "v1"]), ("v2", ["--model", "v2", "--hidden", "32"])):
                out = os.path.join(root, name)
                self.assertEqual(train.main(["--envs", "8", "--workers", "2", "--rollout", "8", "--updates", "2",
                                             "--minutes", "0", "--eval-every", "2", "--minibatch", "256",
                                             "--out", out] + extra), 0)
                runs.append(out)
            report = os.path.join(root, "report")
            self.assertEqual(ladder.main(runs + ["--pick", "2", "--games", "1", "--workers", "2", "--out", report]), 0)
            with open(os.path.join(report, "ladder.json"), encoding="utf-8") as f:
                table = json.load(f)
            self.assertEqual(len(table["players"]), 5)
            for row in table["players"]:
                self.assertEqual(len(row["elo_by_team"]), 2)
                self.assertLessEqual(row["elo_low"], row["elo"] + 1e-6)
            self.assertEqual(len(table["team_matrix"]), 2)
            self.assertTrue(os.path.isfile(os.path.join(report, "ladder.md")))
        finally:
            shutil.rmtree(root, ignore_errors=True)


class DeviceUpdateTest(unittest.TestCase):
    def test_device_resident_update_equals_host_path(self):
        """The parameters are compared under ppo.optimizer's chain with Adam's eps at 1e-2: the same state
        (count, mu, nu), threaded through every minibatch, but linear in a near-zero gradient. With eps 1e-8, f32
        rounding noise becomes a step of +-lr wherever g ~ 0 (seen when encoder 3 widened the input from 607 to
        842 columns; under x64 the two paths agree to 7e-13). The losses are compared under ppo.optimizer."""
        import jax
        import optax
        from duoforge_learn import ppo, train
        from duoforge_learn.returns import gae, samples_of
        from duoforge_learn.selfplay import SelfPlay
        env = SelfPlay(8, 1, 0x2026100200000177)
        try:
            net = policy.make(dict(policy.V1_DEFAULT))
            params = net.init(jax.random.PRNGKey(40))
            rollout, bootstrap, _, _ = train.collect(env, params, net.act, jax.random.PRNGKey(41), 12)
        finally:
            env.close()
        adv, _, targets = gae(rollout["values"], rollout["rewards"], rollout["done"], rollout["acting"], bootstrap)
        samples = samples_of(rollout, adv, targets)
        self.assertGreater(samples["actions"].shape[0] % 80, 0)  # a padded last minibatch

        def both(tx):
            results = []
            for fn in (ppo.update, ppo._update_host):
                out, _, stats = fn(params, tx.init(params), tx, samples, np.random.default_rng(9), net.evaluate,
                                   epochs=2, minibatch=80, entropy_coef=0.01)
                results.append((out, stats))
            return results

        stateful = optax.chain(optax.clip_by_global_norm(0.5), optax.adam(3e-4, eps=1e-2))
        device, host = both(stateful)
        for a, b in zip(jax.tree_util.tree_leaves(device[0]), jax.tree_util.tree_leaves(host[0])):
            np.testing.assert_allclose(np.asarray(a), np.asarray(b), rtol=1e-5, atol=1e-6)
        device, host = both(ppo.optimizer(3e-4))
        for k in ("loss", "policy_loss", "value_loss", "entropy"):
            self.assertAlmostEqual(float(device[1][k]), float(host[1][k]), places=4)
        self.assertIn("t_transfer", device[1])
        self.assertIn("t_compute", device[1])


class CutOffTest(unittest.TestCase):
    def test_cut_off_episodes_are_logged(self):
        out = __import__("tempfile").mkdtemp(prefix="duoforge-cut-")
        try:
            self.assertEqual(_run(["--envs", "8", "--updates", "2", "--max-steps", "5", "--out", out] + _SMALL), 0)
            records = [r for r in _log(out) if "update" in r]
            self.assertTrue(all(r["cut_episodes"] >= 0 for r in records))
            self.assertGreater(sum(r["cut_episodes"] for r in records), 0)
            self.assertLessEqual(records[-1]["cut_episodes"], records[-1]["episodes"])
        finally:
            __import__("shutil").rmtree(out, ignore_errors=True)


class RegistryTrainingTest(unittest.TestCase):
    def test_training_on_registry_teams_a_b_c(self):
        import os
        import shutil
        import tempfile
        from duoforge_learn import ladder, runstate
        out = tempfile.mkdtemp(prefix="duoforge-abc-")
        try:
            self.assertEqual(_run(["--envs", "12", "--updates", "2", "--teams", "A,B,C", "--data-kind", "team_c",
                                   "--team-weights", "1,1,2", "--eval-every", "2", "--out", out]
                                  + [a for a in _SMALL if a not in ("--eval-every", "100")]), 0)
            records = [r for r in _log(out) if "update" in r]
            self.assertEqual(len(records[-1]["vs_random_by_team"]), 3)
            self.assertEqual(len(records[-1]["team_episodes"]), 3)
            state = runstate.load_state(out)
            self.assertEqual(state["teams"]["ids"], ["A", "B", "C"])
            self.assertTrue(all(len(h) == 64 for h in state["teams"]["sha256"]))
            self.assertEqual(state["teams"]["weights"], [1.0, 1.0, 2.0])
            self.assertEqual(state["data"]["kind"], "team_c")
            self.assertEqual(_run(["--resume", out, "--updates", "3"]), 0)
            self.assertEqual(ladder._pool_of(out)[0].ids, ("A", "B", "C"))
            report = os.path.join(out, "ladder")
            self.assertEqual(ladder.main([out, "--pick", "2", "--games", "1", "--workers", "2", "--out", report]), 0)
            self.assertTrue(os.path.isfile(os.path.join(report, "ladder.json")))
            with self.assertRaisesRegex(SystemExit, "data_kind"):
                _run(["--resume", out, "--updates", "4", "--data-kind", "closure"])
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_a_team_the_kind_refuses_stops_the_run(self):
        import shutil
        import tempfile
        from duoforge import teams
        out = tempfile.mkdtemp(prefix="duoforge-refused-")
        try:
            with self.assertRaisesRegex(teams.TeamError, "team C"):
                _run(["--envs", "8", "--updates", "1", "--teams", "A,C", "--out", out] + _SMALL)
        finally:
            shutil.rmtree(out, ignore_errors=True)


# Encoder 3 (842 columns) since 2026-10-03: its block feeds the global, side, position and member layers.
PRESET_COUNTS = {"S": 392303, "M": 2089999, "L": 7901839}


if __name__ == "__main__":
    unittest.main()
