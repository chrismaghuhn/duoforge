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

    def test_older_networks_widen_to_the_current_encoder(self):
        # A network of encoder 2 (the 607 columns before encoder 3's block) or 3 (without encoder 4's appended
        # columns) widened by name to the current encoder: every layer that reads encoder columns keeps its old rows
        # exactly and gets zero rows for the new ones, so it gives the same outputs wherever those columns are zero
        # (every kind but POOL; any battle under mask 0). Model v2 places new columns inside its layer inputs, so
        # their products are summed in another order: equal up to f32 rounding (measured: at most 1.5e-6 relative
        # on the log-probabilities).
        obs, slots, mask = self.turn
        self.assertFalse(obs[:, features.BASE_OBS_SIZE:].any())
        for version in (2, 3):
            with self.subTest(encoder=version):
                self._widened_from(version, obs, slots, mask)

    def _widened_from(self, version, obs, slots, mask):
        from duoforge_learn import checkpoint
        old_names = list(features.feature_names(version))
        new_columns = features.OBS_SIZE - features.obs_size(version)
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
            # v1 reads every column in t1; v2 at least one row per new position column (shared by the positions).
            self.assertGreaterEqual(added_rows, new_columns if cfg["version"] == 1 else 2)
            before = old.apply(params, obs[:, :features.obs_size(version)], slots, mask)
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

    def test_bfloat16_opponents_choose_as_float32(self):
        # The opponents' matrix products in bfloat16 (jax.default_matmul_precision) leave the ids, the masks and
        # the sampling in float32: with peaked scores every row chooses as under float32, and an unknown precision
        # is refused.
        import jax
        from duoforge_learn import league
        _, turn = _scenes()
        obs, slots, mask = turn
        is_team = np.zeros(obs.shape[0], dtype=bool)
        m = policy.make(policy.v2_config("S", hidden=32))
        a, b = m.init(jax.random.PRNGKey(10)), m.init(jax.random.PRNGKey(11))
        a["option_out"]["w"] = a["option_out"]["w"] * 1e4
        b["option_out"]["w"] = a["option_out"]["w"] * -1.0
        slot = np.arange(obs.shape[0]) % 2
        key = jax.random.PRNGKey(12)
        got = {}
        for precision in ("float32", "bfloat16"):
            opp = league.Opponents(m, 2, precision=precision)
            opp.set(0, a)
            opp.set(1, b)
            got[precision] = opp.act(key, obs, slots, mask, is_team, slot)
        np.testing.assert_array_equal(got["bfloat16"], got["float32"])
        with self.assertRaisesRegex(ValueError, "precision"):
            league.Opponents(m, 2, precision="float16")

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

    def test_resume_under_other_tables_checks_the_ids(self):
        # Spec 12.4: tables that only grew keep every embedded id, so the run resumes and logs the new fingerprint;
        # a moved id is refused, naming it. The run state and every snapshot carry the id tables.
        import glob
        import os
        from duoforge_learn import checkpoint, runstate
        self.assertEqual(_run(["--envs", "8", "--updates", "1", "--out", self.out] + _SMALL), 0)
        state = runstate.load_state(self.out)
        with duoforge.Context() as ctx:
            self.assertEqual(state["ids"], checkpoint.ids_of(ctx))
        for path in glob.glob(os.path.join(self.out, "params-*.npz")):
            self.assertEqual(checkpoint.load(path)[1]["ids"], state["ids"])
        real = state["data"]["fingerprint"]
        state["data"]["fingerprint"] = "00" * 32
        state["ids"] = {k: v[:-1] for k, v in state["ids"].items()}  # as if the tables grew since
        runstate.save_state(self.out, state)
        self.assertEqual(_run(["--resume", self.out, "--updates", "2"]), 0)
        resume = [r for r in _log(self.out) if "resume" in r][-1]["resume"]
        self.assertEqual(resume["data"], ["00" * 32, real])
        state = runstate.load_state(self.out)
        self.assertEqual(state["data"]["fingerprint"], real)
        with duoforge.Context() as ctx:
            self.assertEqual(state["ids"], checkpoint.ids_of(ctx))  # the resumed run keeps the current names
        moves = state["ids"]["move"]
        moves[1], moves[2] = moves[2], moves[1]
        state["data"]["fingerprint"] = "00" * 32
        runstate.save_state(self.out, state)
        with self.assertRaisesRegex(SystemExit, "move id 1"):
            _run(["--resume", self.out, "--updates", "3"])

    def test_resume_without_names_under_other_tables_is_refused(self):
        # A run state from before the names (2026-10-03) can only be checked under its own fingerprint.
        from duoforge_learn import runstate
        self.assertEqual(_run(["--envs", "8", "--updates", "1", "--out", self.out] + _SMALL), 0)
        state = runstate.load_state(self.out)
        del state["ids"]
        runstate.save_state(self.out, state)
        self.assertEqual(_run(["--resume", self.out, "--updates", "2"]), 0)  # same tables: no check needed
        state = runstate.load_state(self.out)
        del state["ids"]
        state["data"]["fingerprint"] = "00" * 32
        runstate.save_state(self.out, state)
        with self.assertRaisesRegex(SystemExit, "no id tables"):
            _run(["--resume", self.out, "--updates", "3"])

    def test_opponent_precision_is_resumable(self):
        # bfloat16 opponents train end to end, and a resume may switch the precision (logged as a change).
        self.assertEqual(_run(["--envs", "8", "--updates", "1", "--out", self.out, "--opponent-precision",
                               "bfloat16"] + _SMALL), 0)
        self.assertEqual(_run(["--resume", self.out, "--updates", "2", "--opponent-precision", "float32"]), 0)
        resume = [r for r in _log(self.out) if "resume" in r][-1]["resume"]
        self.assertEqual(resume["opponent_precision"], ["bfloat16", "float32"])

    def test_minibatch_is_resumable(self):
        # More learner work per second (owner, 2026-10-04): a resume may change the minibatch, logged as a change.
        self.assertEqual(_run(["--envs", "8", "--updates", "1", "--out", self.out] + _SMALL), 0)
        self.assertEqual(_run(["--resume", self.out, "--updates", "2", "--minibatch", "512"]), 0)
        resume = [r for r in _log(self.out) if "resume" in r][-1]["resume"]
        self.assertEqual(resume["minibatch"], [256, 512])

    def test_run_directories_inside_the_repository_are_refused(self):
        # Runs, checkpoints and league snapshots are private (AGENTS.md): never written inside a work tree.
        import os
        import shutil
        from duoforge_learn import ladder
        inside = os.path.join(os.path.dirname(os.path.abspath(__file__)), "duoforge-run-must-not-exist")
        try:
            with self.assertRaisesRegex(SystemExit, "inside the repository"):
                _run(["--envs", "8", "--updates", "1", "--out", inside] + _SMALL)
            with self.assertRaisesRegex(SystemExit, "inside the repository"):
                _run(["--resume", inside, "--updates", "2"])
            self.assertFalse(os.path.exists(inside))
            with self.assertRaisesRegex(SystemExit, "inside the repository"):
                ladder.main([self.out, "--out", inside])
            self.assertFalse(os.path.exists(inside))
        finally:
            shutil.rmtree(inside, ignore_errors=True)  # a failing run of this test leaves nothing in the repository

    def test_plateau_levers_train_and_resume(self):
        # --learning-rate-schedule (a multiplier over decisions) and --kl-ref/--kl-coef run, are logged per update,
        # and a resume may change them; --kl-coef without --kl-ref is refused.
        import glob
        import os
        self.assertEqual(_run(["--envs", "8", "--updates", "1", "--out", self.out, "--learning-rate-schedule",
                               "0:1,1M:0.1"] + _SMALL), 0)
        ref = sorted(glob.glob(os.path.join(self.out, "params-*.npz")))[0]
        self.assertEqual(_run(["--resume", self.out, "--updates", "2", "--kl-ref", ref, "--kl-coef", "0.02",
                               "--learning-rate-schedule", "0:0.5"]), 0)
        records = [r for r in _log(self.out) if "update" in r]
        self.assertEqual(records[0]["lr_scale"], 1.0)
        self.assertEqual((records[-1]["lr_scale"], records[-1]["kl_coef"]), (0.5, 0.02))
        self.assertIn("kl", records[-1])
        resume = [r for r in _log(self.out) if "resume" in r][-1]["resume"]
        self.assertEqual(resume["kl_coef"], [0.0, 0.02])
        with self.assertRaisesRegex(SystemExit, "kl-ref"):
            _run(["--resume", self.out, "--updates", "3", "--kl-ref", "", "--kl-coef", "0.02"])
        # The magnet (MMD/R-NaD style): the learner's frozen copy, set at the (re)start and every --kl-refresh updates.
        self.assertEqual(_run(["--resume", self.out, "--updates", "5", "--kl-ref", "magnet", "--kl-coef", "0.05",
                               "--kl-refresh", "2"]), 0)
        refreshed = [r["update"] for r in _log(self.out) if "update" in r and r.get("magnet_refreshed")]
        self.assertEqual(refreshed, [3, 4])  # the resume's first update, then every second update

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

    def test_resume_of_an_encoder_2_run_continues_on_the_current_encoder(self):
        self._resume_from(2)

    def test_resume_of_an_encoder_3_run_continues_on_the_current_encoder(self):
        self._resume_from(3)

    def _resume_from(self, version):
        # A run of an older encoder (encoder 2: 607 columns, no mask; encoder 3: without encoder 4's columns, its
        # mask) resumes on the current encoder: parameters, Adam moments, league snapshots and the evaluation
        # opponent widen by name, the mask stays, and the resume says so.
        import os
        import jax
        from duoforge_learn import checkpoint, ppo, runstate
        self.assertEqual(_run(["--envs", "8", "--updates", "2", "--eval-every", "1", "--out", self.out]
                              + [a for a in _SMALL if a not in ("--eval-every", "100")]), 0)
        keep = np.arange(features.obs_size(version))
        old_names = list(features.feature_names(version))

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
        state["features"], state["encoder"] = old_names, version
        if version == 2:
            state.pop("ext_supported")
        runstate.save_state(self.out, state)
        for f in os.listdir(self.out):
            if f.startswith("params-") and f.endswith(".npz"):
                params, config = checkpoint.load(os.path.join(self.out, f))
                if version == 2:
                    config = {k: v for k, v in config.items() if k != "ext_supported"}
                checkpoint.save(os.path.join(self.out, f), narrow(params),
                                dict(config, features=old_names, encoder=version))
        self.assertEqual(_run(["--resume", self.out, "--updates", "4", "--slot-refresh", "1"]), 0)
        records = [r for r in _log(self.out) if "update" in r]
        self.assertEqual(records[-1]["update"], 4)
        self.assertIn("vs_previous", records[-1])
        resume = [r for r in _log(self.out) if "resume" in r][0]["resume"]
        self.assertEqual(resume["encoder"], [version, features.ENCODER])
        state = runstate.load_state(self.out)
        self.assertEqual((state["encoder"], state["ext_supported"]), (features.ENCODER, 0))  # CLOSURE: 0 either way
        self.assertEqual(state["features"], list(features.FEATURE_NAMES))
        params, config = checkpoint.load_current(os.path.join(self.out, "params-0.npz"))  # narrowed above
        self.assertEqual((config["encoder"], params["t1"]["w"].shape[0]), (features.ENCODER, features.OBS_SIZE))

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


class PlateauLeverTest(unittest.TestCase):
    """The learning-rate multiplier and the KL anchor to a reference policy (owner, 2026-10-04: plateau levers)."""

    @classmethod
    def setUpClass(cls):
        import jax
        from duoforge_learn import train
        from duoforge_learn.returns import gae, samples_of
        from duoforge_learn.selfplay import SelfPlay
        env = SelfPlay(8, 1, 0x2026100400000010)
        try:
            cls.net = policy.make(dict(policy.V1_DEFAULT))
            cls.params = cls.net.init(jax.random.PRNGKey(50))
            rollout, bootstrap, _, _ = train.collect(env, cls.params, cls.net.act, jax.random.PRNGKey(51), 12)
        finally:
            env.close()
        adv, _, targets = gae(rollout["values"], rollout["rewards"], rollout["done"], rollout["acting"], bootstrap)
        cls.samples = samples_of(rollout, adv, targets)

    def _flat(self, params):
        import jax
        return np.concatenate([np.ravel(np.asarray(x)) for x in jax.tree_util.tree_leaves(params)])

    def test_lr_scale_scales_the_step(self):
        from duoforge_learn import ppo
        tx = ppo.optimizer(3e-4)
        still, _, _ = ppo.update(self.params, tx.init(self.params), tx, self.samples, np.random.default_rng(1),
                                 self.net.evaluate, epochs=1, minibatch=64, lr_scale=0.0)
        np.testing.assert_array_equal(self._flat(still), self._flat(self.params))
        moved, _, _ = ppo.update(self.params, tx.init(self.params), tx, self.samples, np.random.default_rng(1),
                                 self.net.evaluate, epochs=1, minibatch=64, lr_scale=1.0)
        self.assertGreater(float(np.abs(self._flat(moved) - self._flat(self.params)).max()), 0.0)

    def test_kl_anchor_is_zero_at_the_reference_and_pulls_toward_it(self):
        import jax
        from duoforge_learn import ppo
        o = self.samples
        at_self = dict(o, ref_logp=np.asarray(self.net.evaluate(self.params, o["obs"], o["slots"], o["mask"],
                                                                o["is_team"], o["actions"])[0]))
        tx = ppo.optimizer(3e-4)
        _, _, stats = ppo.update(self.params, tx.init(self.params), tx, at_self, np.random.default_rng(2),
                                 self.net.evaluate, epochs=1, minibatch=64, kl_coef=1.0, lr_scale=0.0)
        self.assertAlmostEqual(float(stats["kl"]), 0.0, places=6)
        # A reference that prefers other actions: the anchored update moves the taken actions' log-probabilities
        # toward the reference's, the unanchored one does not.
        ref = self.net.init(jax.random.PRNGKey(99))
        anchored = dict(o, ref_logp=np.asarray(self.net.evaluate(ref, o["obs"], o["slots"], o["mask"], o["is_team"],
                                                                 o["actions"])[0]))
        gap = lambda p: float(np.abs(np.asarray(self.net.evaluate(p, o["obs"], o["slots"], o["mask"], o["is_team"],
                                                                     o["actions"])[0]) - anchored["ref_logp"]).mean())
        flat = dict(o, advantages=np.zeros_like(o["advantages"]))
        pulled, _, stats = ppo.update(self.params, tx.init(self.params), tx,
                                      dict(anchored, advantages=flat["advantages"]), np.random.default_rng(3),
                                      self.net.evaluate, epochs=4, minibatch=64, kl_coef=1.0)
        self.assertGreater(float(stats["kl"]), 0.0)
        free, _, _ = ppo.update(self.params, tx.init(self.params), tx, flat, np.random.default_rng(3),
                                self.net.evaluate, epochs=4, minibatch=64)
        self.assertLess(gap(pulled), gap(free))

    def test_k3_is_exact_up_to_the_cap_and_linear_beyond(self):
        # The night run of 2026-10-04 met k3 means up to 7.9e6: a rarely drawn action (p ~ 1e-7) that the magnet
        # finds likely gives r = exp(ref_logp - logp) without bound. Up to the cap the estimate is k3; beyond it
        # the estimate goes on linearly, with k3's slope at the cap, so one row's gradient stays bounded.
        import jax
        from duoforge_learn import ppo
        cap = ppo.KL_LOG_RATIO_MAX
        self.assertEqual(cap, 3.0)
        k3 = lambda x: np.exp(x) - 1.0 - x
        below = np.array([-20.0, -5.0, -1.0, 0.0, 0.5, 2.0, 3.0], dtype=np.float32)
        np.testing.assert_allclose(np.asarray(ppo._k3(below)), k3(below.astype(np.float64)), rtol=1e-6, atol=1e-6)
        self.assertAlmostEqual(float(ppo._k3(np.float32(30.0))), k3(cap) + (np.exp(cap) - 1.0) * 27.0, places=3)
        slope = float(jax.grad(ppo._k3)(np.float32(30.0)))
        self.assertAlmostEqual(slope, np.exp(cap) - 1.0, places=4)
        self.assertAlmostEqual(float(jax.grad(ppo._k3)(np.float32(1.0))), np.e - 1.0, places=5)

    def test_kl_stat_stays_bounded_for_a_far_reference(self):
        from duoforge_learn import ppo
        o = self.samples
        logp = np.asarray(self.net.evaluate(self.params, o["obs"], o["slots"], o["mask"], o["is_team"],
                                            o["actions"])[0])
        far = dict(o, ref_logp=logp + 30.0)
        tx = ppo.optimizer(3e-4)
        _, _, stats = ppo.update(self.params, tx.init(self.params), tx, far, np.random.default_rng(4),
                                 self.net.evaluate, epochs=1, minibatch=64, kl_coef=1.0, lr_scale=0.0)
        bound = np.exp(3.0) - 4.0 + (np.exp(3.0) - 1.0) * 27.0
        self.assertTrue(np.isfinite(float(stats["kl"])))
        self.assertAlmostEqual(float(stats["kl"]), bound, delta=1e-2 * bound)

    def test_reference_logp_runs_in_minibatches_and_equals_one_pass(self):
        # The night run's 29k rows in one pass asked 3.4 GiB of an 8 GiB card (2026-10-04): the reference is
        # evaluated in minibatches of a fixed size, the last one padded, and equals the one-pass values.
        from duoforge_learn import ppo
        o = {k: v[:-1] for k, v in self.samples.items()}  # one row short of a multiple of 64 (the padded tail)
        seen = []

        def counting(params, obs, *rest):
            seen.append(obs.shape[0])
            return self.net.evaluate(params, obs, *rest)

        n = o["actions"].shape[0]
        whole = np.asarray(self.net.evaluate(self.params, o["obs"], o["slots"], o["mask"], o["is_team"],
                                             o["actions"])[0])
        chunked = ppo.reference_logp(self.params, o, counting, minibatch=64)
        self.assertGreater(n % 64, 0)
        self.assertEqual(seen, [64] * -(-n // 64))
        self.assertEqual(chunked.shape, (n,))
        self.assertEqual(chunked.dtype, np.float32)
        np.testing.assert_allclose(chunked, whole, rtol=1e-5, atol=1e-5)


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


# Encoder 4 (850 columns) since 2026-10-03: encoder 3's block feeds the global, side, position and member layers,
# and encoder 4's two position columns add 2 x position rows to the position layer (encoder 3: S 392303, M 2089999,
# L 7901839).
PRESET_COUNTS = {"S": 392431, "M": 2090255, "L": 7902351}


if __name__ == "__main__":
    unittest.main()
