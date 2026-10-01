"""duoforge.python.policies_features: the scripted baseline and the encoder.

32 environments played to the end with ScriptedPolicy choose only indices
below their counts, and two runs end in the same states. encode is pure
(equal inputs, equal arrays; one changed foe HP percent changes obs_part),
its pair mask holds the joint count, and both policies refuse a requested
player with 0 candidates (Review Focus 5).
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
