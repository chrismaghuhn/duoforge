"""duoforge.python.learn_numpy: the learner pipeline's NumPy parts (decision
0014), without JAX.

GAE and the value targets over each seat's own decisions against a hand
computation; the team head's tuple table against the engine's joint ranks;
the seat and reward attribution of evaluation and self-play with stand-in
policies (one attacks the foe, one switches); an evaluation whose episodes
do not end counts them as ties instead of failing; the learner's input
checks; a checkpoint of another encoder fails at load; a checkpoint
without an encoder version plays the evaluation and the ladder on the
inputs of encoder 1; and the view-extension mask of encoder 3 (decision
0018): self-play under POOL reads the library's mask and the records, a
checkpoint names its mask, and the live policy refuses a mask that needs
records.
"""
import unittest

import numpy as np

import duoforge
from duoforge import _layout, features
from duoforge_learn import evaluate, ladder
from duoforge_learn.checkpoint import encoder_of, load
from duoforge_learn.returns import gae
from duoforge_learn.selfplay import OPTIONS, TEAM_ACTIONS, TEAM_TABLE, Observation, SelfPlay

C = _layout.CONSTANTS
# obs_part columns of the own roster's present flags (15 global, 8 side,
# 2 * 24 positions, 40 per member).
_OWN_PRESENT = 71 + 40 * np.arange(6)


def _stand_in(params, key, obs, slots, mask, is_team, greedy=True):
    """A NumPy policy with model.act's signature: params["prefer"] scores a
    slot option ("attack": a move at a foe 2, another move 1; "switch": a
    switch 2, a move 1); the best allowed pair wins, team tuple 0."""
    n = obs.shape[0]
    kind = slots[..., 1:5].argmax(axis=-1)  # 0 none, 1 move, 2 switch, 3 pass
    valid = slots[..., 0] > 0
    at_foe = slots[..., 8:10].sum(axis=-1) > 0  # target one-hot: foe slot 0 or 1
    if params["prefer"] == "attack":
        score = np.where(kind == 1, np.where(at_foe, 2.0, 1.0), 0.0)
    else:
        score = np.where(kind == 2, 2.0, np.where(kind == 1, 1.0, 0.0))
    score = np.where(valid, score, -1.0)
    pairs = score[:, 0, :, None] + score[:, 1, None, :]
    pairs = np.where(mask, pairs, -1e9).reshape(n, -1)
    actions = np.where(is_team, 0, pairs.argmax(axis=1))
    return actions, np.zeros(n), np.zeros(n)


class ReturnsTest(unittest.TestCase):
    def test_own_decisions_terminal_reward_and_value_targets(self):
        # One environment, four steps. Seat 0 decides at t = 0, 1, 3; seat 1
        # at t = 0, 2. The episode ends after t = 2, seat 0 winning; t = 3
        # starts the next one, bootstrapped by the values after the rollout.
        values = np.array([[[0.1, 0.2]], [[0.3, 0.0]], [[0.0, 0.4]], [[0.5, 0.0]]], dtype=np.float32)
        rewards = np.zeros((4, 1, 2), dtype=np.float32)
        rewards[2, 0] = (1.0, -1.0)
        done = np.array([[False], [False], [True], [False]])
        acting = np.array([[[True, True]], [[True, False]], [[False, True]], [[True, False]]])
        bootstrap = np.array([[0.6, 0.7]], dtype=np.float32)
        adv, ret, target = gae(values, rewards, done, acting, bootstrap, gamma=0.9, lam=0.8)
        expected = np.array([[[0.674, -0.848]], [[0.7, 0.0]], [[0.0, -1.4]], [[0.04, 0.0]]], dtype=np.float32)
        np.testing.assert_allclose(adv, expected, atol=1e-6)
        np.testing.assert_allclose(ret, np.where(acting, expected + values, 0.0), atol=1e-6)
        # A seat that does not act is worth what its next decision returns,
        # or the episode's end for it, or the bootstrap after the rollout.
        want = np.where(acting, expected + values, 0.0)
        want[1, 0, 1] = -1.0  # seat 1 waits at t = 1: what its decision at t = 2 returns
        want[2, 0, 0] = 1.0   # seat 0 waits at t = 2, the last step of the episode it won
        want[3, 0, 1] = 0.7   # seat 1 waits at t = 3: the bootstrap
        np.testing.assert_allclose(target, want, atol=1e-6)


class SeatTest(unittest.TestCase):
    def test_team_table_is_the_joint_rank(self):
        with duoforge.Context() as ctx, duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 1) as batch:
            batch.query_factored()
            domain = batch.domains[0, 0]
            self.assertEqual(int(duoforge.joint_counts(domain)[0]), TEAM_ACTIONS)
            for k in range(TEAM_ACTIONS):
                self.assertEqual(list(duoforge.factored_choice(domain, k)["picks"][:4]), list(TEAM_TABLE[k]))

    def test_evaluation_credits_the_right_seat(self):
        attack, switch = {"prefer": "attack"}, {"prefer": "switch"}
        strong = evaluate.win_rate(attack, _stand_in, switch, envs=16, workers=2, rounds=2, encoder=2, opponent_encoder=2)
        weak = evaluate.win_rate(switch, _stand_in, attack, envs=16, workers=2, rounds=2, encoder=2, opponent_encoder=2)
        self.assertGreater(strong["win_rate"], 0.75)
        self.assertLess(weak["win_rate"], 0.25)
        self.assertEqual(strong["episodes"], 32)

    def test_selfplay_rewards_the_winner(self):
        env = SelfPlay(16, 2, 0x2026100200000023)
        totals = np.zeros(2)
        try:
            for _ in range(400):
                o = env.observe()
                actions = np.zeros((16, 2), dtype=np.int64)
                for seat, prefer in ((0, "attack"), (1, "switch")):
                    a, _, _ = _stand_in({"prefer": prefer}, None, o.obs[:, seat], o.slots[:, seat], o.mask[:, seat],
                                        o.is_team[:, seat])
                    actions[:, seat] = a
                rewards, _ = env.step(actions)
                totals += rewards.sum(axis=0)
        finally:
            env.close()
        self.assertGreater(totals[0], 0)
        self.assertEqual(totals[0], -totals[1])

    def test_endless_evaluation_counts_ties(self):
        switch = {"prefer": "switch"}
        result = evaluate.win_rate(switch, _stand_in, switch, envs=8, workers=2, max_steps=30, encoder=2,
                                   opponent_encoder=2)
        self.assertEqual(result["episodes"], 8)
        self.assertEqual(result["wins"] + result["losses"] + result["ties"], 8)
        self.assertGreater(result["unfinished"], 0)  # two switchers never end a battle
        self.assertGreaterEqual(result["ties"], result["unfinished"])


class LadderTest(unittest.TestCase):
    def test_ratings_follow_the_scores(self):
        # A beats B 9 of 10, B beats C 9 of 10, A beats C 10 of 10.
        score = np.array([[0, 9, 10], [1, 0, 9], [0, 1, 0]], dtype=float)
        games = np.where(np.eye(3) == 1, 0.0, 10.0)
        elo = ladder.ratings(score, games)
        self.assertEqual(elo[0], 0.0)
        self.assertTrue(elo[0] > elo[1] > elo[2])
        even = ladder.ratings(np.full((2, 2), 5.0) * (1 - np.eye(2)), np.full((2, 2), 10.0) * (1 - np.eye(2)))
        self.assertAlmostEqual(float(even[1]), 0.0, places=6)

    def test_round_robin_ranks_stand_ins(self):
        players = [("switch", {"prefer": "switch"}, features.ENCODER),
                   ("attack", {"prefer": "attack"}, features.ENCODER)]
        score, games = ladder.round_robin(players, _stand_in, envs=16, workers=2)
        self.assertEqual(games[0, 1], 16)
        self.assertEqual(score[0, 1] + score[1, 0], 16)
        self.assertGreater(ladder.ratings(score, games)[1], 100.0)

    def test_checkpoint_round_trip(self):
        import json
        import os
        import tempfile
        params = {"t1": {"w": np.arange(6, dtype=np.float32).reshape(2, 3), "b": np.zeros(3, np.float32)},
                  "value": {"w": np.ones((3, 1), np.float32), "b": np.zeros(1, np.float32)}}
        arrays = {f"['{a}']['{b}']": v for a, d in params.items() for b, v in d.items()}
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "params-7.npz")
            np.savez(path, config=json.dumps({"seed": 5}), **arrays)
            back, config = load(path)
            self.assertEqual(config, {"seed": 5})
            self.assertTrue(np.array_equal(back["t1"]["w"], params["t1"]["w"]))
            self.assertEqual(sorted(back), ["t1", "value"])
            np.savez(path, config="{}", **{"odd name": np.zeros(1)})
            with self.assertRaises(ValueError):
                load(path)

    def test_checkpoint_of_another_encoder_is_refused(self):
        # The checkpoints of 2026-10-02 take 594 observation features; with
        # obs_size, load refuses a network of another encoder by name.
        import os
        import tempfile
        arrays = {"['t1']['w']": np.zeros((594, 3), np.float32), "['t1']['b']": np.zeros(3, np.float32)}
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "params-1.npz")
            np.savez(path, config="{}", **arrays)
            self.assertEqual(load(path, obs_size=594)[0]["t1"]["w"].shape, (594, 3))
            with self.assertRaisesRegex(ValueError, "594 observation features.*607"):
                load(path, obs_size=features.BASE_OBS_SIZE)

    def test_checkpoint_names_its_encoder(self):
        # A config without "encoder" is a checkpoint of encoder 1 (present
        # from the species); a version the encoder does not serve raises.
        self.assertEqual(encoder_of({"seed": 5}), 1)
        self.assertEqual(encoder_of({"encoder": 1}), 1)
        self.assertEqual(encoder_of({"encoder": 2}), 2)
        self.assertEqual(encoder_of({"encoder": 3}), 3)
        self.assertEqual(encoder_of({"encoder": features.ENCODER}), 4)
        for bad in (0, 5, "2", None, True, 1.0, 2.0):  # True == 1, 2.0 == 2: only ints count
            with self.assertRaisesRegex(ValueError, "encoder"):
                encoder_of({"encoder": bad})

    def test_old_checkpoints_play_on_their_inputs(self):
        # The evaluation and the ladder give each network the present flags
        # of its encoder: encoder 1 sees Team A's Rillaboom (roster 0) as
        # absent, encoder 2 all six members, in every call.
        seen = {}

        def act(params, key, obs, slots, mask, is_team, greedy=True):
            seen.setdefault(params["name"], []).append(np.asarray(obs)[:, _OWN_PRESENT].copy())
            return _stand_in(params, key, obs, slots, mask, is_team, greedy)

        old, new = {"prefer": "attack", "name": "old"}, {"prefer": "switch", "name": "new"}
        evaluate.win_rate(old, act, new, envs=8, workers=2, encoder=1, opponent_encoder=2)
        evaluate.win_rate(new, act, old, envs=8, workers=2, encoder=2, opponent_encoder=1)
        ladder.round_robin([("old", old, 1), ("new", new, 2)], act, envs=8, workers=2)
        self.assertGreater(len(seen["old"]), 3)
        self.assertGreater(len(seen["new"]), 3)
        for present in seen["old"]:
            # pairings e % 4 on both seats: Team A sits at rows of every call
            self.assertTrue((present[:, 0] == 0).any())
            self.assertTrue((present[:, 1:] == 1).all())
        for present in seen["new"]:
            self.assertTrue((present == 1).all())


class InputTest(unittest.TestCase):
    def test_learner_inputs_are_checked(self):
        with self.assertRaises(ValueError):
            evaluate.win_rate({"prefer": "attack"}, _stand_in, "random", envs=12, encoder=2)
        with duoforge.Context() as ctx, duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 1) as batch:
            batch.query_factored()
            batch.step_factored(_first_tuples(batch))
            batch.query_factored()
            d = batch.domains[0:1].copy()
            ob = batch.observations[0:1].copy()
            d[0, 0]["slot_count"][0] = OPTIONS + 8
            with self.assertRaises(ValueError):
                features.encode_batch(ob[:, 0], d[:, 0])

    def test_encoder_versions_are_named_where_a_network_plays(self):
        # Review of #88: no default may pick a version for a network. The
        # evaluation needs the network's version, and the opponent's when
        # it is parameters; the policy's inputs need the version too.
        attack, switch = {"prefer": "attack"}, {"prefer": "switch"}
        with self.assertRaises(TypeError):
            evaluate.win_rate(attack, _stand_in, "random", envs=8)
        with self.assertRaisesRegex(ValueError, "opponent_encoder"):
            evaluate.win_rate(attack, _stand_in, switch, envs=8, encoder=2)
        with duoforge.Context() as ctx, duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 1) as batch:
            batch.query_factored()
            with self.assertRaises(TypeError):
                Observation(batch)
            self.assertEqual(Observation(batch, features.ENCODER).obs.shape, (1, 2, features.OBS_SIZE))


def _first_tuples(batch):
    choices = np.zeros((batch.envs, 2), dtype=_layout.FACTORED_CHOICE)
    choices["picks"][..., :4] = TEAM_TABLE[0]
    return choices


def _random_params(obs_size, seed):
    """Parameters of model.init's shapes (hidden 256, option 128) with random values, in NumPy."""
    rng = np.random.default_rng(seed)
    shapes = {"t1": (obs_size, 256), "t2": (256, 256), "option_torso": (256, 128),
              "option_features": (features.SLOT_FEATURES, 128), "option_out": (128, 2), "team": (256, TEAM_ACTIONS),
              "value": (256, 1)}
    return {k: {"w": rng.normal(0, 0.1, s).astype(np.float32), "b": rng.normal(0, 0.1, s[1]).astype(np.float32)}
            for k, s in shapes.items()}


def _closure_inputs(steps=120):
    """(observations, obs_part, slot_part, pair_mask) of both seats of 16 reference battles over `steps` batch
    steps, the first allowed pair (team tuple 0) played."""
    env = SelfPlay(16, 2, 0x2026100200000016)
    rows = []
    try:
        for _ in range(steps):
            o = env.observe()  # refreshes the batch's observations and domains (one query per step)
            observations = env.batch.observations.reshape(-1).copy()
            obs, slots, mask = features.encode_batch(observations, env.batch.domains.reshape(-1))
            rows.append((observations, obs, slots, mask))
            flat = o.mask.reshape(16, 2, -1)
            env.step(np.where(o.is_team, 0, flat.argmax(axis=-1)))
    finally:
        env.close()
    return tuple(np.concatenate([r[i] for r in rows]) for i in range(4))


class WidenTest(unittest.TestCase):
    """The night checkpoint (594 features) on the encoder of 607 (decision 0016, spec section 5)."""

    def test_widened_columns_are_the_new_features(self):
        from duoforge_learn.checkpoint import WIDEN_594_COLUMNS
        ob = np.zeros((), dtype=_layout.OBSERVATION)
        ob["boundary_kind"] = C["DUOFORGE_BOUNDARY_TURN"]
        ob["sides"]["occupant"] = C["DUOFORGE_ROSTER_NONE"]
        dom = np.zeros((), dtype=_layout.FACTORED_DOMAIN)
        base = features.encode(ob, dom)[0]
        for terrain in ("NONE", "GRASSY", "PSYCHIC"):
            o = ob.copy()
            o["terrain"] = C[f"DUOFORGE_TERRAIN_{terrain}"]
            self.assertEqual(features.encode(o, dom)[0][12], 1.0 if terrain == "PSYCHIC" else 0.0)
        changed = set()
        for side in (0, 1):
            for slot in (0, 1):
                for bit in features.POSITION_FLAGS:
                    o = ob.copy()
                    o["sides"][side]["positions"][slot]["reserved"] = bit
                    diff = np.flatnonzero(features.encode(o, dom)[0] != base)
                    self.assertEqual(len(diff), 1, (side, slot, bit))
                    changed.add(int(diff[0]))
        self.assertEqual(WIDEN_594_COLUMNS[0], 12)
        self.assertEqual(sorted(changed), list(WIDEN_594_COLUMNS[1:]))

    def test_widened_columns_are_zero_under_closure(self):
        from duoforge_learn.checkpoint import WIDEN_594_COLUMNS
        _, obs, _, _ = _closure_inputs()
        self.assertFalse(obs[:, list(WIDEN_594_COLUMNS)].any())

    def test_widened_network_matches_the_original(self):
        from duoforge_learn.checkpoint import WIDEN_594_COLUMNS, widen_594
        from duoforge_live.policy import forward
        _, obs, slots, mask = _closure_inputs(40)
        obs = obs[:, :features.BASE_OBS_SIZE]  # a network of encoder 1: the 607 columns before the block
        params = _random_params(594, 3)
        wide = widen_594(params)
        self.assertEqual(wide["t1"]["w"].shape, (features.BASE_OBS_SIZE, 256))
        self.assertFalse(wide["t1"]["w"][list(WIDEN_594_COLUMNS)].any())
        self.assertEqual(params["t1"]["w"].shape, (594, 256))  # the original is not changed
        narrow = np.delete(obs, WIDEN_594_COLUMNS, axis=1)
        a = forward(wide, obs, slots, mask)
        b = forward(params, narrow, slots, mask)
        for x, y in zip(a, b):
            self.assertTrue(np.allclose(x, y, rtol=1e-5, atol=1e-5))
        self.assertTrue((a[0].argmax(axis=1) == b[0].argmax(axis=1)).all())
        self.assertTrue((a[1].argmax(axis=1) == b[1].argmax(axis=1)).all())

    def test_widen_refuses_other_sizes(self):
        from duoforge_learn.checkpoint import widen_594
        with self.assertRaises(ValueError):
            widen_594(_random_params(features.OBS_SIZE, 1))

    def test_widen_command(self):
        import json
        import os
        import tempfile
        from duoforge_learn import checkpoint
        params = _random_params(594, 4)
        arrays = {f"['{a}']['{b}']": v for a, d in params.items() for b, v in d.items()}
        with tempfile.TemporaryDirectory() as folder:
            src, dst = os.path.join(folder, "params-25000.npz"), os.path.join(folder, "wide.npz")
            np.savez(src, config=json.dumps({"seed": 7}), **arrays)
            self.assertEqual(checkpoint.main(["widen", src, dst]), 0)
            back, config = load(dst, obs_size=features.BASE_OBS_SIZE)
            self.assertEqual(config, {"seed": 7, "encoder": 1})
            self.assertTrue(np.array_equal(np.delete(back["t1"]["w"], checkpoint.WIDEN_594_COLUMNS, axis=0),
                                           params["t1"]["w"]))
            with self.assertRaises(ValueError):
                load(src, obs_size=features.BASE_OBS_SIZE)
            with self.assertRaises(SystemExit):
                checkpoint.main(["widen", src, dst])  # OUT exists

    def test_v1_checkpoint_uses_the_legacy_encoding(self):
        import json
        import os
        import tempfile
        from duoforge_live import policy

        def arrays(width):
            return {f"['{a}']['{b}']": v for a, d in _random_params(width, 5).items() for b, v in d.items()}

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "p.npz")
            for config, encoder in (({"encoder": 1}, 1), ({}, 1), ({"encoder": 2}, 2), ({"encoder": 3}, 3),
                                    ({"encoder": 4}, 4)):
                np.savez(path, config=json.dumps(config), **arrays(features.obs_size(encoder)))
                self.assertEqual(policy.load(path).encoder, encoder)
            # An unknown version, and a network of another width than its version's (607 for 1 and 2, 842 for 3,
            # 850 for 4).
            for config, width in (({"encoder": 5}, features.OBS_SIZE), ({"encoder": 3}, features.OBS_SIZE),
                                  ({"encoder": 4}, features.obs_size(3)), ({"encoder": 3}, features.BASE_OBS_SIZE),
                                  ({"encoder": 2}, features.OBS_SIZE)):
                np.savez(path, config=json.dumps(config), **arrays(width))
                with self.assertRaises(ValueError):
                    policy.load(path)

    def test_policy_ranks_with_its_encoder(self):
        # A network that reads only the own roster-0 present flag: Team A's Rillaboom (forme 0) is absent under
        # encoder 1 and present under 2, so the team head's probabilities differ.
        from duoforge_live.policy import Policy
        observations, obs, _, _ = _closure_inputs(1)
        rows = [r for r in range(len(observations)) if
                int(observations[r]["sides"][int(observations[r]["player"])]["members"][0]["species_id"]) == 0]
        r = rows[0]
        params = _random_params(features.BASE_OBS_SIZE, 6)  # the width of encoders 1 and 2
        params["t1"]["w"][:] = 0
        params["t1"]["w"][_OWN_PRESENT[0], :] = 1.0
        teams1 = Policy(params, 1).rank_teams(observations[r], obs[r])
        teams2 = Policy(params, 2).rank_teams(observations[r], obs[r])
        self.assertNotEqual([p for _, p in teams1], [p for _, p in teams2])
        probs = dict(teams2)
        order = [i for i, _ in teams2]
        self.assertEqual(order, sorted(order, key=lambda i: (-probs[i], i)))  # best first, ties to the lower index

    def test_rank_pairs(self):
        # Every allowed pair once, best first by the forward pass's log-probability, ties to the lower flat
        # index, (i, j) as row and column of the 32 x 32 mask; a mask without a pair raises.
        from duoforge_live.policy import Policy, forward
        observations, obs, slots, mask = _closure_inputs(30)
        params = _random_params(features.OBS_SIZE, 7)
        policy = Policy(params, features.ENCODER)
        rows = [r for r in range(len(mask)) if mask[r].sum() > 1][:20]
        self.assertTrue(rows)
        for r in rows:
            ranked = policy.rank_pairs(observations[r], obs[r], slots[r], mask[r])
            self.assertEqual(sorted((i, j) for i, j, _ in ranked), sorted(zip(*np.nonzero(mask[r]))))
            logp = forward(params, obs[r][None], slots[r][None], mask[r][None])[0][0]
            best = int(np.where(mask[r].reshape(-1), logp, -np.inf).argmax())
            self.assertEqual(ranked[0][:2], (best // 32, best % 32))
            keys = [(-logp[i * 32 + j], i * 32 + j) for i, j, _ in ranked]
            self.assertEqual(keys, sorted(keys))
            self.assertAlmostEqual(ranked[0][2], float(np.exp(logp[best])), places=6)
        tied = Policy({k: {"w": np.zeros_like(v["w"]), "b": np.zeros_like(v["b"])} for k, v in params.items()},
                      features.ENCODER)
        r = rows[0]
        flat = [i * 32 + j for i, j, _ in tied.rank_pairs(observations[r], obs[r], slots[r], mask[r])]
        self.assertEqual(flat, sorted(flat))  # all equal: the lower flat index first
        with self.assertRaises(ValueError):
            policy.rank_pairs(observations[r], obs[r], slots[r], np.zeros_like(mask[r]))



class ExtSupportedTest(unittest.TestCase):
    """The view-extension mask (decision 0018 section 10) from self-play to a checkpoint and the live policy."""

    def _pool(self, ctx):
        import os
        from duoforge import teams
        sides = []
        for name in ("sand.txt", "snow.txt"):
            with open(os.path.join("tools", "cloud", "aws_fuzz", "campaigns", "weather-sand-snow", name),
                      encoding="utf-8") as f:
                sides.append(teams.side_setup(ctx, teams.parse(f.read(), name), name))
        return teams.TeamPool.from_setups(("sand", "snow"), sides)

    def test_self_play_under_pool_reads_the_library_mask_and_the_records(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            env = SelfPlay(4, 1, 0x2026100300000031, pool=self._pool(ctx), context=ctx)
            try:
                library = int(env.batch.observe_ext()[0, 0]["supported"])
                self.assertEqual(env.ext_supported, library)
                self.assertTrue(library & features.RECORD_FEATURES)
                sand = features.FEATURE_NAMES.index("ext.global.weather_sand")
                snow = features.FEATURE_NAMES.index("ext.global.weather_snow")
                weathers = set()
                for _ in range(20):
                    o = env.observe()
                    self.assertEqual(o.obs.shape, (4, 2, features.OBS_SIZE))
                    weathers |= {k for k, col in (("sand", sand), ("snow", snow)) if o.obs[..., col].any()}
                    flat = o.mask.reshape(4, 2, -1)
                    env.step(np.where(o.is_team, 0, flat.argmax(axis=-1)))
                self.assertTrue(weathers)
            finally:
                env.close()
            blind = SelfPlay(2, 1, 0x2026100300000031, pool=self._pool(ctx), context=ctx, ext_supported=0)
            old = SelfPlay(2, 1, 0x2026100300000031, pool=self._pool(ctx), context=ctx, encoder=2)
            try:
                self.assertEqual((blind.ext_supported, old.ext_supported), (0, 0))
                with self.assertRaisesRegex(ValueError, "encoder 2"):
                    Observation(old.batch, 2, features.BASE_VALUE_FEATURES)
            finally:
                blind.close()
                old.close()

    def test_closure_self_play_has_no_mask(self):
        env = SelfPlay(2, 1, 0x2026100300000032)
        try:
            self.assertEqual(env.ext_supported, 0)
        finally:
            env.close()

    def test_self_play_refuses_a_mask_the_library_cannot_produce(self):
        # A run never records a feature it could not see: a given mask must lie in the library's mask under the
        # context, before anything is played or saved. A strict subset is fine.
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            probe = SelfPlay(2, 1, 0x2026100300000033, pool=self._pool(ctx), context=ctx)
            library = probe.ext_supported
            probe.close()
            lacking = features.ALL_FEATURES & ~library
            self.assertTrue(lacking)  # some feature is not built yet
            first = (lacking & -lacking).bit_length() - 1
            name = next(n for n, b in features.FEATURE_BITS.items() if b == first)
            for mask in (library | (1 << first), features.BASE_VALUE_FEATURES | (1 << first)):
                with self.assertRaisesRegex(ValueError, name):
                    SelfPlay(2, 1, 0x2026100300000033, pool=self._pool(ctx), context=ctx, ext_supported=mask)
            for bad in (-1, 1 << features.ALL_FEATURES.bit_length(), 1.0):  # beyond every feature bit, not a fixed 40
                with self.assertRaisesRegex(ValueError, "ext_supported"):
                    SelfPlay(2, 1, 0x2026100300000033, pool=self._pool(ctx), context=ctx, ext_supported=bad)
            low = library & -library
            subset = SelfPlay(2, 1, 0x2026100300000033, pool=self._pool(ctx), context=ctx, ext_supported=library & ~low)
            try:
                self.assertEqual(subset.ext_supported, library & ~low)
            finally:
                subset.close()
        for mask in (features.BASE_VALUE_FEATURES, 1 << features.FEATURE_BITS["AURORA_VEIL"]):
            with self.assertRaisesRegex(ValueError, "does not support"):
                SelfPlay(2, 1, 0x2026100300000032, ext_supported=mask)  # CLOSURE: the library supports none
            with self.assertRaisesRegex(ValueError, "does not support"):
                SelfPlay(2, 1, 0x2026100300000032, encoder=2, ext_supported=mask)

    def test_checkpoint_names_its_mask(self):
        from duoforge_learn.checkpoint import ext_supported_of
        self.assertEqual(ext_supported_of({"encoder": 3}), 0)
        self.assertEqual(ext_supported_of({"encoder": 3, "ext_supported": 0x15}), 0x15)
        self.assertEqual(ext_supported_of({"encoder": 2}), 0)
        for bad in ({"encoder": 3, "ext_supported": 1 << 40}, {"encoder": 3, "ext_supported": -1},
                    {"encoder": 3, "ext_supported": "1"}, {"encoder": 3, "ext_supported": True},
                    {"encoder": 2, "ext_supported": 1}, {"ext_supported": 1}):
            with self.assertRaisesRegex(ValueError, "ext_supported"):
                ext_supported_of(bad)

    def test_live_policy_refuses_a_mask_that_needs_records(self):
        from duoforge_live.policy import Policy
        params = _random_params(features.OBS_SIZE, 8)
        self.assertEqual(Policy(params, features.ENCODER, features.BASE_VALUE_FEATURES).ext_supported,
                         features.BASE_VALUE_FEATURES)
        for name in ("AURORA_VEIL", "ENCORE"):
            with self.assertRaisesRegex(ValueError, "records"):
                Policy(params, features.ENCODER, 1 << features.FEATURE_BITS[name])


if __name__ == "__main__":
    unittest.main()
