"""duoforge.python.policies_features: the scripted baseline and the encoder.

32 environments played to the end with ScriptedPolicy choose only indices
below their counts, and two runs end in the same states. encode is pure
(equal inputs, equal arrays; one changed foe HP percent changes obs_part),
its pair mask holds the joint count, and both policies refuse a requested
player with 0 candidates (Review Focus 5). Psychic Terrain and the position
flags of the TEAM_C kinds encode at their documented places and alike in
both encoders; values outside them raise.
"""
import unittest

import numpy as np

import duoforge
from duoforge import _layout, features

SEED = 0x2026100200000016
ENVS = 32


def _setups():
    return duoforge.reference_setups([e % 4 for e in range(ENVS)])


def _reference_choice(batch, e, p):
    """The spec section 4 scoring, one candidate at a time (the reference
    for the vectorized ScriptedPolicy)."""
    c = _layout.CONSTANTS
    foe = batch.observations[e, p]["sides"][1 - p]
    best, best_score = 0, None
    for i in range(int(batch.counts[e, p])):
        score = 0
        for cmd in batch.candidates[e, p, i]["slots"]:
            kind, target = int(cmd["kind"]), int(cmd["target"])
            if kind == c["DUOFORGE_SLOT_MOVE"]:
                occupant = int(foe["occupant"][target & 1]) if target < 4 and target >> 1 == 1 - p else 0xFF
                if occupant < 6:
                    m = foe["members"][occupant]
                    if int(m["hp_kind"]) == c["DUOFORGE_HP_PERCENT"]:
                        shown = int(m["hp"])
                    elif int(m["hp_kind"]) == c["DUOFORGE_HP_EXACT"] and int(m["hp_max"]) > 0:
                        shown = int(m["hp"]) * 100 // int(m["hp_max"])
                    else:
                        shown = 100
                    score += 100 - shown
                else:
                    score += 10
            elif kind == c["DUOFORGE_SLOT_SWITCH"]:
                score -= 50
        if best_score is None or score > best_score:
            best, best_score = i, score
    return best


def _play_scripted(ctx, test, check_reference=False):
    policy = duoforge.ScriptedPolicy()
    with duoforge.Batch(ctx, _setups(), 4, SEED) as batch:
        for _ in range(2000):
            batch.query()
            requested = batch.requests["requested"] != 0
            if not requested.any():
                break
            idx = policy.choose(batch)
            test.assertTrue((idx[requested] < batch.counts[requested]).all())
            test.assertTrue((idx[~requested] == _layout.NO_CHOICE).all())
            if check_reference:
                for e, p in zip(*np.nonzero(requested[:8])):
                    test.assertEqual(int(idx[e, p]), _reference_choice(batch, e, p))
            batch.step(idx)
        else:
            test.fail("the scripted battles did not end")
        test.assertTrue(all(batch.result(e) != 0 for e in range(ENVS)))
        return [batch.digest(e) for e in range(ENVS)]


class _Scene:
    """A one-environment stand-in for a Batch: player 0 requested, the foe
    (side 1) with members 0 and 1 active, and hand-made candidates."""

    def __init__(self, candidates, foe=((100, 100, 2), (100, 100, 2)), empty_slot=None):
        c = _layout.CONSTANTS
        self.envs = 1
        self.requests = np.zeros((1, 2), dtype=_layout.REQUEST)
        self.requests[0, 0]["requested"] = 1
        self.counts = np.zeros((1, 2), dtype=np.uint32)
        self.counts[0, 0] = len(candidates)
        self.observations = np.zeros((1, 2), dtype=_layout.OBSERVATION)
        side = self.observations[0, 0]["sides"][1]
        for k, (hp, hp_max, kind) in enumerate(foe):
            side["occupant"][k] = c["DUOFORGE_ROSTER_NONE"] if k == empty_slot else k
            side["members"][k]["hp"], side["members"][k]["hp_max"], side["members"][k]["hp_kind"] = hp, hp_max, kind
        self.candidates = np.zeros((1, 2, _layout.MAX_CANDIDATES), dtype=_layout.SIDE_CHOICE)
        for i, pair in enumerate(candidates):
            for s, (kind, target) in enumerate(pair):
                self.candidates[0, 0, i]["slots"][s]["kind"] = c[f"DUOFORGE_SLOT_{kind}"]
                self.candidates[0, 0, i]["slots"][s]["target"] = target


class PoliciesFeaturesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = duoforge.Context()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()

    def test_scripted_is_legal_and_deterministic(self):
        self.assertEqual(_play_scripted(self.ctx, self, check_reference=True), _play_scripted(self.ctx, self))

    def test_scripted_scores(self):
        choose = duoforge.ScriptedPolicy().choose
        none, foe0, foe1 = ("NONE", 0xFF), ("MOVE", 2), ("MOVE", 3)
        untargeted = ("MOVE", 0xFF)
        # switches -50 each against 0 for a move at a full foe
        self.assertEqual(choose(_Scene([(("SWITCH", 0), ("SWITCH", 0)), (foe0, ("PASS", 0xFF))]))[0, 0], 1)
        # a move without a foe target scores 10
        self.assertEqual(choose(_Scene([(foe0, none), (untargeted, none)]))[0, 0], 1)
        # 100 minus the shown HP percent: the weaker foe wins
        self.assertEqual(choose(_Scene([(foe0, none), (foe1, none)], foe=((100, 100, 2), (40, 100, 2))))[0, 0], 1)
        # exact HP is shown as hp * 100 // hp_max: 50 of 200 is 25 percent
        self.assertEqual(choose(_Scene([(foe1, none), (foe0, none)], foe=((50, 200, 1), (30, 100, 2))))[0, 0], 1)
        # an empty foe position counts as a move without a target (10 against 5)
        self.assertEqual(choose(_Scene([(foe1, none), (foe0, none)], foe=((95, 100, 2), (100, 100, 2)),
                                       empty_slot=1))[0, 0], 0)
        # ties go to the lowest index
        self.assertEqual(choose(_Scene([(untargeted, none), (untargeted, none)]))[0, 0], 0)

    def test_encode_is_pure(self):
        with duoforge.Batch(self.ctx, _setups(), 1, SEED) as batch:
            policy = duoforge.RandomPolicy(SEED, ENVS)
            for e in range(ENVS):
                policy.start_episode(e, 0)
            batch.query_factored()
            batch.step_factored(policy.choose_factored(batch))
            batch.query_factored()
            ob = batch.observations[0, 0].copy()
            d = batch.domains[0, 0].copy()
            a = features.encode(ob, d)
            b = features.encode(ob.copy(), d.copy())
            for x, y in zip(a, b):
                self.assertTrue(np.array_equal(x, y))
            self.assertEqual(a[0].shape, (features.OBS_SIZE,))
            self.assertEqual(a[1].shape, (2, 32, features.SLOT_FEATURES))
            self.assertEqual(a[2].shape, (32, 32))
            self.assertTrue(((a[0] >= 0) & (a[0] <= 1)).all())
            changed = ob.copy()
            foe = changed["sides"][1]
            occupant = int(foe["occupant"][0])
            foe["members"][occupant]["hp"] = int(foe["members"][occupant]["hp"]) - 1
            self.assertFalse(np.array_equal(features.encode(changed, d)[0], a[0]))
            unknown = ob.copy()
            unknown["sides"][0]["members"][0]["status"] = 99  # an ailment this encoder does not know
            with self.assertRaises(ValueError):
                features.encode(unknown, d)
            for e in range(ENVS):
                for p in range(2):
                    if batch.requests[e, p]["requested"]:
                        mask = features.encode(batch.observations[e, p], batch.domains[e, p])[2]
                        self.assertEqual(int(mask.sum()), int(batch.requests[e, p]["candidate_count"]))

    def test_encode_refuses_a_domain_of_another_boundary(self):
        with duoforge.Batch(self.ctx, _setups(), 1, SEED) as batch:
            policy = duoforge.RandomPolicy(SEED, ENVS)
            for e in range(ENVS):
                policy.start_episode(e, 0)
            batch.query_factored()
            batch.step_factored(policy.choose_factored(batch))
            batch.query()  # fresh observations, the domains stay at the old boundary
            with self.assertRaises(ValueError):
                features.encode(batch.observations[0, 0], batch.domains[0, 0])
            odd = batch.domains[0, 0].copy()
            odd["kind"] = 7
            with self.assertRaises(ValueError):
                duoforge.joint_counts(odd)

    def test_encode_knows_poison(self):
        with duoforge.Batch(self.ctx, _setups(), 1, SEED) as batch:
            batch.query_factored()
            ob = np.array(batch.observations[0, 0])
            d = batch.domains[0, 0]
            before = features.encode(ob, d)[0]
            ob["sides"][0]["members"][0]["status"] = _layout.CONSTANTS["DUOFORGE_AILMENT_POISON"]
            self.assertFalse(np.array_equal(features.encode(ob, d)[0], before))

    def test_encode_batch_equals_the_reference(self):
        # Every player of 32 environments at every step of a battle, both
        # forms of domain (team selection, slots, no request).
        from python.tests import _reference_features as reference
        policy = duoforge.RandomPolicy(SEED, ENVS)
        compared = 0
        with duoforge.Batch(self.ctx, _setups(), 4, SEED) as batch:
            policy.start_episodes(np.arange(ENVS), np.zeros(ENVS, dtype=np.uint64))
            for _ in range(200):
                batch.query_factored()
                obs, slots, masks = features.encode_batch(batch.observations.reshape(-1), batch.domains.reshape(-1))
                self.assertEqual(obs.shape, (2 * ENVS, features.OBS_SIZE))
                for n, (ob, d) in enumerate(zip(batch.observations.reshape(-1), batch.domains.reshape(-1))):
                    want = reference.encode(ob, d)
                    self.assertTrue(np.array_equal(obs[n], want[0]))
                    self.assertTrue(np.array_equal(slots[n], want[1]))
                    self.assertTrue(np.array_equal(masks[n], want[2]))
                    compared += 1
                if not (batch.requests["requested"] != 0).any():
                    break
                batch.step_factored(policy.choose_factored(batch))
        self.assertGreater(compared, 1000)

    def test_encode_position_flags(self):
        # Each DUOFORGE_POSITION_FLAG_* bit (the TEAM_C kinds, decision 0009
        # section 4.2) sets one feature after a position's seven older
        # flags: own slot 0 at 37..39 (15 global, 8 side, 7 stages, 7
        # flags), foe slot 1 at 357..359 (a side is 8 + 2 * 24 + 6 * 40).
        # A bit outside the three raises.
        c = _layout.CONSTANTS
        self.assertEqual(features.OBS_SIZE, 607)
        with duoforge.Batch(self.ctx, _setups(), 1, SEED) as batch:
            batch.query_factored()
            ob = np.array(batch.observations[0, 0])
            d = batch.domains[0, 0]
            me = int(ob["player"])
            before = features.encode(ob, d)[0]
            for k, name in enumerate(("FOLLOW_ME", "HELPING_HAND", "UNBURDEN")):
                for side, slot, first in ((me, 0, 37), (1 - me, 1, 357)):
                    changed = ob.copy()
                    changed["sides"][side]["positions"][slot]["reserved"] = c[f"DUOFORGE_POSITION_FLAG_{name}"]
                    diff = features.encode(changed, d)[0] - before
                    self.assertEqual(np.flatnonzero(diff).tolist(), [first + k])
                    self.assertEqual(float(diff[first + k]), 1.0)
            ob["sides"][me]["positions"][0]["reserved"] = 8
            with self.assertRaisesRegex(ValueError, "position flags"):
                features.encode(ob, d)

    def test_encode_psychic_terrain(self):
        # Psychic Terrain (TEAM_C) is the third entry of the terrain one-hot
        # (obs_part[10:13], before the terrain turns); another terrain raises.
        with duoforge.Batch(self.ctx, _setups(), 1, SEED) as batch:
            batch.query_factored()
            ob = np.array(batch.observations[0, 0])
            d = batch.domains[0, 0]
            ob["terrain"] = _layout.CONSTANTS["DUOFORGE_TERRAIN_PSYCHIC"]
            ob["terrain_turns"] = 5
            self.assertEqual(features.encode(ob, d)[0][10:14].tolist(), [0.0, 0.0, 1.0, 0.625])
            ob["terrain"] = 3
            with self.assertRaisesRegex(ValueError, "terrain"):
                features.encode(ob, d)

    def test_team_c_values_equal_the_reference(self):
        # Psychic Terrain and every position flag, set at random on the
        # observations of real battles, encode alike in both encoders.
        from python.tests import _reference_features as reference
        rng = np.random.default_rng(0x2026100216)
        policy = duoforge.RandomPolicy(SEED, ENVS)
        compared = 0
        with duoforge.Batch(self.ctx, _setups(), 4, SEED) as batch:
            policy.start_episodes(np.arange(ENVS), np.zeros(ENVS, dtype=np.uint64))
            for step in range(12):
                batch.query_factored()
                if step % 4 == 3:
                    obs = np.array(batch.observations.reshape(-1))
                    domains = batch.domains.reshape(-1)
                    obs["terrain"] = rng.integers(0, 3, obs.shape)
                    positions = obs["sides"]["positions"]
                    positions["reserved"] = rng.integers(0, 8, positions.shape)
                    got = features.encode_batch(obs, domains)
                    for n in range(obs.shape[0]):
                        want = reference.encode(obs[n], domains[n])
                        for g, w in zip(got, want):
                            self.assertTrue(np.array_equal(g[n], w))
                        compared += 1
                batch.step_factored(policy.choose_factored(batch))
        self.assertEqual(compared, 3 * 2 * ENVS)

    def test_zero_count_raises(self):
        with duoforge.Batch(self.ctx, _setups(), 1, SEED) as batch:
            batch.query()
            batch.counts[0, 0] = 0
            with self.assertRaises(ValueError):
                duoforge.ScriptedPolicy().choose(batch)
            with self.assertRaises(ValueError):
                duoforge.RandomPolicy(SEED, ENVS).choose(batch)
            batch.query_factored()
            batch.requests[0, 0]["candidate_count"] = 0
            with self.assertRaises(ValueError):
                duoforge.RandomPolicy(SEED, ENVS).choose_factored(batch)


if __name__ == "__main__":
    unittest.main()
