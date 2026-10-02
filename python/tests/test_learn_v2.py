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


PRESET_COUNTS = {"S": 384751, "M": 2072463, "L": 7871631}


if __name__ == "__main__":
    unittest.main()
