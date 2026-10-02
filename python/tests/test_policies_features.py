"""duoforge.python.policies_features: the scripted baseline and the encoder.

32 environments played to the end with ScriptedPolicy choose only indices
below their counts, and two runs end in the same states. encode is pure
(equal inputs, equal arrays; one changed foe HP percent changes obs_part),
its pair mask holds the joint count, and both policies refuse a requested
player with 0 candidates (Review Focus 5). Psychic Terrain and the position
flags of the TEAM_C kinds encode at their documented places and alike in
both encoders; values outside them raise. A member is present exactly when
registered: Team A's Rillaboom (species 0) too, an unregistered slot of a
DEV-kind roster of four or five not.
"""
import unittest

import numpy as np

import duoforge
from duoforge import _layout, features

SEED = 0x2026100200000016
ENVS = 32
# The encoder-1 trajectory hash (test_as_encoder_1_matches_the_recorded_old_encoder).
V1_SEED = 0x2026100200000088
V1_GOLDEN = "f15954182cb6be1707d36447bfd2e513f68d3ff15c564c7cf53e3b561cb76a6a"


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


# obs_part index of roster member k's present flag: own side 71 + 40 k (15
# global, 8 side, 2 * 24 positions), the foe 367 + 40 k (a side is 296).
_OWN_PRESENT = 71 + 40 * np.arange(6)
_FOE_PRESENT = 367 + 40 * np.arange(6)
_DEV_COUNTS = (4, 5)  # registered members of side 0 and side 1 in _dev_setups


def _dev_setups():
    """Pairings 0 and 2, four times, with rosters of four (side 0: Team A
    from Rillaboom) and five (side 1) for a DEV kind, which registers
    brought_count to max_roster members."""
    setups = duoforge.reference_setups([0, 2] * 4)
    for s, count in enumerate(_DEV_COUNTS):
        setups["sides"][:, s]["member_count"] = count
        setups["sides"][:, s]["members"][:, count:] = 0
    return setups


def _play_encoded(ctx, setups, test):
    """Plays the setups to the end with RandomPolicy; per step the
    observations and factored domains (2E,) and encode_batch's obs_part
    (2E, OBS_SIZE), which the reference encoder equals."""
    from python.tests import _reference_features as reference
    envs = setups.shape[0]
    policy = duoforge.RandomPolicy(SEED, envs)
    policy.start_episodes(np.arange(envs), np.zeros(envs, dtype=np.uint64))
    steps = []
    with duoforge.Batch(ctx, setups, 1, SEED) as batch:
        for _ in range(400):
            batch.query_factored()
            obs, domains = batch.observations.reshape(-1).copy(), batch.domains.reshape(-1).copy()
            got = features.encode_batch(obs, domains)[0]
            for n in range(obs.shape[0]):
                test.assertTrue(np.array_equal(got[n], reference.encode(obs[n], domains[n])[0]))
            steps.append((obs, domains, got))
            if not (batch.requests["requested"] != 0).any():
                return steps
            batch.step_factored(policy.choose_factored(batch))
    test.fail("the battles did not end")


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
        # Every bit outside the three raises, in both encoders.
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
            from python.tests import _reference_features as reference
            for bad in (8, 16, 32, 64, 128):
                ob["sides"][me]["positions"][0]["reserved"] = bad
                for encoder in (features, reference):
                    with self.assertRaisesRegex(ValueError, "position flags"):
                        encoder.encode(ob, d)

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

    def test_encode_present_marks_every_registered_member(self):
        # Team A registers Rillaboom (species 0) at roster 0: in pairings 0
        # (A-B) and 2 (A-A) all six members of both sides are present, at
        # every boundary of the battles, in both encoders.
        steps = _play_encoded(self.ctx, duoforge.reference_setups([0, 2] * 4), self)
        self.assertEqual(steps[0][0]["sides"][:, 0]["members"][:, 0]["species_id"].tolist(), [0] * 16)
        for _, _, got in steps:
            self.assertTrue((got[:, _OWN_PRESENT] == 1).all())
            self.assertTrue((got[:, _FOE_PRESENT] == 1).all())

    def test_encode_present_of_unregistered_slots(self):
        # Every registered member of the DEV rosters (four and five) is
        # present, the one not brought too, and an unregistered slot is
        # not, in both encoders.
        with duoforge.Context(data_kind=3) as dev:  # DUOFORGE_DATA_KIND_CLOSURE_DEV
            steps = _play_encoded(dev, _dev_setups(), self)
        registered = np.array([[1.0] * c + [0.0] * (6 - c) for c in _DEV_COUNTS], dtype=np.float32)
        not_brought = 0
        for obs, _, got in steps:
            me = obs["player"].astype(np.int64)
            self.assertTrue(np.array_equal(got[:, _OWN_PRESENT], registered[me]))
            self.assertTrue(np.array_equal(got[:, _FOE_PRESENT], registered[1 - me]))
            location = obs["sides"][np.arange(obs.shape[0]), me]["members"]["location"]
            not_brought += int((location == _layout.CONSTANTS["DUOFORGE_LOCATION_NOT_BROUGHT"]).sum())
        self.assertGreater(not_brought, 0)

    def test_as_encoder_1_is_the_old_encoder(self):
        # A network of encoder 1 gets exactly that encoder's inputs: present
        # from species_id != 0, everything else as encoder 2. At every step
        # of the CLOSURE pairings 0 and 2 and of the DEV rosters, byte for
        # byte the reference encoder's encoder=1; only Rillaboom's present
        # differs from encoder 2 (Team A at roster 0, own side and foe).
        from python.tests import _reference_features as reference
        steps = _play_encoded(self.ctx, duoforge.reference_setups([0, 2] * 4), self)
        with duoforge.Context(data_kind=3) as dev:  # DUOFORGE_DATA_KIND_CLOSURE_DEV
            steps += _play_encoded(dev, _dev_setups(), self)
        for obs, domains, got in steps:
            self.assertIs(features.as_encoder(got, obs, features.ENCODER), got)
            old = features.as_encoder(got, obs, 1)
            for n in range(obs.shape[0]):
                self.assertTrue(np.array_equal(old[n], reference.encode(obs[n], domains[n], encoder=1)[0]))
            self.assertTrue(set(np.flatnonzero((old != got).any(axis=0))) <= {71, 367})
        # Pairing 0 at team selection, player 0 (Team A): the old encoder's
        # [0, 1, 1, 1, 1, 1] against all six.
        obs, _, got = steps[0]
        self.assertEqual(features.as_encoder(got, obs, 1)[0, _OWN_PRESENT].tolist(), [0.0] + [1.0] * 5)
        self.assertEqual(got[0, _OWN_PRESENT].tolist(), [1.0] * 6)

    def test_as_encoder_refuses_what_it_does_not_know(self):
        with duoforge.Batch(self.ctx, duoforge.reference_setups([0]), 1, SEED) as batch:
            batch.query_factored()
            ob, d = batch.observations[0, 0], batch.domains[0, 0]
            part = features.encode(ob, d)[0]
            self.assertEqual(features.as_encoder(part, ob, 1)[_OWN_PRESENT].tolist(), [0.0] + [1.0] * 5)
            self.assertEqual(part[_OWN_PRESENT].tolist(), [1.0] * 6)  # one record, untouched
            for bad in (0, 3, "2", None, True, 1.0):  # only ints count: True == 1, 1.0 == 1
                with self.assertRaisesRegex(ValueError, "encoder"):
                    features.as_encoder(part, ob, bad)
            for odd in (part[:-1], part.astype(np.float64), np.stack([part, part])):
                with self.assertRaises(TypeError):
                    features.as_encoder(odd, ob, 1)

    def test_as_encoder_1_matches_the_recorded_old_encoder(self):
        # SHA-256 of encoder 1's obs_part over a fixed trajectory, recorded
        # with the encoder from before the present fix (main 2fb40d6, whose
        # encode_batch was version 1). The reference encoder changes with
        # features.py, so this pins version 1 against drifting with both.
        import hashlib
        h = hashlib.sha256()
        rows = 0
        policy = duoforge.RandomPolicy(V1_SEED, 8)
        policy.start_episodes(np.arange(8), np.zeros(8, dtype=np.uint64))
        with duoforge.Batch(self.ctx, duoforge.reference_setups([0, 2] * 4), 2, V1_SEED) as batch:
            for _ in range(60):
                batch.query_factored()
                observations = batch.observations.reshape(-1)
                obs = features.encode_batch(observations, batch.domains.reshape(-1))[0]
                h.update(np.ascontiguousarray(features.as_encoder(obs, observations, 1)).tobytes())
                rows += obs.shape[0]
                if not (batch.requests["requested"] != 0).any():
                    break
                batch.step_factored(policy.choose_factored(batch))
        self.assertEqual((h.hexdigest(), rows), (V1_GOLDEN, 464))

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
