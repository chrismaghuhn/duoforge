"""duoforge.python.learn_numpy: the learner pipeline's NumPy parts (decision
0014), without JAX.

GAE and the value targets over each seat's own decisions against a hand
computation; the team head's tuple table against the engine's joint ranks;
the seat and reward attribution of evaluation and self-play with stand-in
policies (one attacks the foe, one switches); an evaluation whose episodes
do not end counts them as ties instead of failing; and the learner's input
checks.
"""
import unittest

import numpy as np

import duoforge
from duoforge import _layout, features
from duoforge_learn import evaluate
from duoforge_learn.returns import gae
from duoforge_learn.selfplay import OPTIONS, TEAM_ACTIONS, TEAM_TABLE, SelfPlay

C = _layout.CONSTANTS


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
        strong = evaluate.win_rate(attack, _stand_in, switch, envs=16, workers=2, rounds=2)
        weak = evaluate.win_rate(switch, _stand_in, attack, envs=16, workers=2, rounds=2)
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
        result = evaluate.win_rate(switch, _stand_in, switch, envs=8, workers=2, max_steps=30)
        self.assertEqual(result["episodes"], 8)
        self.assertEqual(result["wins"] + result["losses"] + result["ties"], 8)
        self.assertGreater(result["unfinished"], 0)  # two switchers never end a battle
        self.assertGreaterEqual(result["ties"], result["unfinished"])


class InputTest(unittest.TestCase):
    def test_learner_inputs_are_checked(self):
        with self.assertRaises(ValueError):
            evaluate.win_rate({"prefer": "attack"}, _stand_in, "random", envs=12)
        with duoforge.Context() as ctx, duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 1) as batch:
            batch.query_factored()
            batch.step_factored(_first_tuples(batch))
            batch.query_factored()
            d = batch.domains[0:1].copy()
            ob = batch.observations[0:1].copy()
            d[0, 0]["slot_count"][0] = OPTIONS + 8
            with self.assertRaises(ValueError):
                features.encode_batch(ob[:, 0], d[:, 0])


def _first_tuples(batch):
    choices = np.zeros((batch.envs, 2), dtype=_layout.FACTORED_CHOICE)
    choices["picks"][..., :4] = TEAM_TABLE[0]
    return choices


if __name__ == "__main__":
    unittest.main()
