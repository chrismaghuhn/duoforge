"""duoforge.python.encode_c: the C encoder (decision 0021) against its
reference, python/duoforge/features.py.

For every encoder version and view-extension mask, Batch.query_encoded and
duoforge_encode give exactly the bytes of features.encode_batch with
as_encoder and slots_as_encoder, and refuse exactly the rows the reference
refuses (raising its own ValueError). Covered:
- random play under CLOSURE, TEAM_C and POOL (registry teams with Sand);
- synthetic records with every field set;
- fuzzed rows, one field at a time inside and just outside its known set or range;
- worker counts 1 and 4, and the fused query against duoforge_encode per row;
- a refused encode in self-play stops the run and ends no episode.
"""
import ctypes
import unittest

import numpy as np

import duoforge
from duoforge import _layout, features, teams
from duoforge._lib import load_library, ptr
from duoforge_learn.selfplay import SelfPlay

from python.tests.test_features_ext import _records

C = _layout.CONSTANTS
SEED = 0x2026100300000400
ENVS = 16
STEPS = 30
VERSIONS = (1, 2, 3, 4, 5, 6)
SAND_TEAMS = ("PP_097433EFCC505367", "PP_25161F401C0A2005")  # Sand Stream in the registry
SLOT_VALUES = 2 * _layout.MAX_SLOT_OPTIONS * features.SLOT_FEATURES
PAIR_VALUES = _layout.MAX_SLOT_OPTIONS * _layout.MAX_SLOT_OPTIONS


def reference(version, mask, observations, domains, ext):
    """features.py's inputs of version `version`: (obs, slots, pair_mask), or the ValueError it raises."""
    try:
        obs, slots, pairs = features.encode_batch(observations, domains, ext, mask, encoder=version)
        return (features.as_encoder(obs, observations, version), features.slots_as_encoder(slots, version),
                pairs), None
    except ValueError as err:
        return None, err


def c_encode(version, mask, observation, domain, ext):
    """duoforge_encode of one row: (status, obs, slots, pair_mask)."""
    size = features.obs_size(version)
    obs = np.zeros(size, dtype=np.float32)
    slots = np.zeros(SLOT_VALUES, dtype=np.float32)
    pairs = np.zeros(PAIR_VALUES, dtype=np.uint8)
    ob = np.array(observation, dtype=_layout.OBSERVATION)
    d = np.array(domain, dtype=_layout.FACTORED_DOMAIN)
    x = None if ext is None else np.array(ext, dtype=_layout.OBSERVATION_EXT)
    st = load_library().duoforge_encode(version, ctypes.c_uint64(mask), ptr(ob), ptr(d),
                                        None if x is None else ptr(x), ptr(obs), ptr(slots), ptr(pairs))
    return st, obs, slots.reshape(2, _layout.MAX_SLOT_OPTIONS, features.SLOT_FEATURES), \
        pairs.reshape(_layout.MAX_SLOT_OPTIONS, _layout.MAX_SLOT_OPTIONS).astype(bool)


def masks_for(version, library, rng, count=3):
    """0, the base values, the library's mask and `count` random subsets of it, inside the version's features."""
    top = library & features.version_features(version)
    out = {0, top & features.BASE_VALUE_FEATURES, top}
    for _ in range(count):
        out.add(top & (int(rng.integers(0, 1 << 62)) | int(rng.integers(0, 4)) << 62))  # bits 62 and 63 too
    return sorted(out)


class EncodeCTest(unittest.TestCase):
    def assert_same(self, got, want, what):
        for g, w, name in zip(got, want, ("obs", "slots", "pair_mask")):
            g, w = np.asarray(g), np.asarray(w)
            self.assertEqual(g.shape, w.shape, f"{what}: {name} shape")
            if not np.array_equal(g.view(np.uint8), w.view(np.uint8)):
                bad = np.argwhere(g.reshape(-1) != w.reshape(-1))[:5].ravel().tolist()
                self.fail(f"{what}: {name} differs at {bad}")

    def play_and_compare(self, ctx, setups, steps=STEPS, pool_mask=True):
        rng = np.random.default_rng(SEED)
        with duoforge.Batch(ctx, setups, 2, SEED) as batch:
            policy = duoforge.RandomPolicy(SEED, batch.envs)
            policy.start_episodes(np.arange(batch.envs), np.zeros(batch.envs, dtype=np.uint64))
            batch.query_factored()
            library = int(batch.observe_ext()[0, 0]["supported"])
            if pool_mask:
                self.assertNotEqual(library, 0)
            refused = accepted = 0
            for _ in range(steps):
                for version in VERSIONS:
                    for mask in masks_for(version, library, rng):
                        batch.query_factored()
                        ob = batch.observations.reshape(-1).copy()
                        d = batch.domains.reshape(-1).copy()
                        ext = batch.observe_ext().reshape(-1).copy() if mask & features.RECORD_FEATURES else None
                        want, err = reference(version, mask, ob, d, ext)
                        if err is not None:
                            refused += 1
                            with self.assertRaises(ValueError, msg=f"version {version} mask {mask:#x}"):
                                batch.query_encoded(version, mask)
                            continue
                        accepted += 1
                        got = batch.query_encoded(version, mask)
                        n = 2 * batch.envs
                        self.assert_same((got[0].reshape(n, -1), got[1].reshape(n, 2, 32, 12),
                                          got[2].reshape(n, 32, 32)), want, f"version {version} mask {mask:#x}")
                batch.query_factored()
                live = batch.requests["requested"] != 0
                if not live.any():
                    break
                batch.step_factored(policy.choose_factored(batch))
                ended = np.flatnonzero(batch.results["boundary_kind"] == C["DUOFORGE_BOUNDARY_TERMINAL"])
                for e in ended:
                    batch.reset(int(e), batch.episode(int(e)) + 1)
                    policy.start_episodes(np.array([e]), np.array([batch.episode(int(e))], dtype=np.uint64))
            return accepted, refused

    def test_closure_play_matches_the_reference(self):
        with duoforge.Context() as ctx:
            accepted, _ = self.play_and_compare(ctx, duoforge.reference_setups([e % 4 for e in range(ENVS)]),
                                               pool_mask=False)
        self.assertGreater(accepted, 0)

    def test_team_c_play_matches_the_reference(self):
        with duoforge.Context(data_kind=C["DUOFORGE_DATA_KIND_TEAM_C"]) as ctx:
            pool = teams.load(ctx, ["A", "B", "C"])
            setups = pool.setups(np.arange(ENVS) % 3, (np.arange(ENVS) // 3) % 3)
            accepted, _ = self.play_and_compare(ctx, setups, pool_mask=False)
        self.assertGreater(accepted, 0)

    def test_pool_play_matches_the_reference(self):
        # Sand Stream teams make Sand appear: versions 1 and 2 and masks without its bit must refuse those rows.
        with duoforge.Context(data_kind=C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            pool = teams.load(ctx, ["A", "B", "C", *SAND_TEAMS])
            n = len(pool.ids)
            setups = pool.setups(np.arange(ENVS) % n, (np.arange(ENVS) * 2 + 3) % n)
            accepted, refused = self.play_and_compare(ctx, setups, steps=40)
        self.assertGreater(accepted, 0)
        self.assertGreater(refused, 0)

    def test_synthetic_records_match_the_reference(self):
        # Every record field set (test_features_ext._records), on the reference battles' first turn.
        with duoforge.Context() as ctx, duoforge.Batch(ctx, duoforge.reference_setups(list(range(4))), 1,
                                                       SEED) as batch:
            policy = duoforge.RandomPolicy(SEED, 4)
            policy.start_episodes(np.arange(4), np.zeros(4, dtype=np.uint64))
            batch.query_factored()
            batch.step_factored(policy.choose_factored(batch))
            batch.query_factored()
            ob, d = batch.observations.reshape(-1).copy(), batch.domains.reshape(-1).copy()
        rng = np.random.default_rng(SEED + 1)
        # every field set, and empty records (revision 0: the "none" of Encore and Disable)
        for ext in (_records(ob), np.zeros(ob.shape, dtype=_layout.OBSERVATION_EXT)):
            for version in (3, 4, 5, 6):
                for mask in masks_for(version, features.ALL_FEATURES, rng, count=32):
                    want, err = reference(version, mask, ob, d, ext)
                    self.assertIsNone(err)
                    for row in range(ob.shape[0]):
                        st, *got = c_encode(version, mask, ob[row], d[row], ext[row])
                        self.assertEqual(st, 0, f"version {version} mask {mask:#x} row {row}")
                        self.assert_same(got, (want[0][row], want[1][row], want[2][row]),
                                         f"version {version} mask {mask:#x} row {row}")

    def test_reserve_records_match_the_reference(self):
        # Encoder 6's reserve (decision 0050): every family filled, shown by version 6, refused by 3 to 5.
        from python.tests.test_encoder6 import _reserve
        with duoforge.Context() as ctx, duoforge.Batch(ctx, duoforge.reference_setups(list(range(4))), 1,
                                                       SEED) as batch:
            policy = duoforge.RandomPolicy(SEED, 4)
            policy.start_episodes(np.arange(4), np.zeros(4, dtype=np.uint64))
            batch.query_factored()
            batch.step_factored(policy.choose_factored(batch))
            batch.query_factored()
            ob, d = batch.observations.reshape(-1).copy(), batch.domains.reshape(-1).copy()
        ext, ob = _reserve(_records(ob), ob)
        rng = np.random.default_rng(SEED + 3)
        for version in (3, 4, 5, 6):
            for mask in masks_for(version, features.ALL_FEATURES, rng, count=32):
                want, err = reference(version, mask, ob, d, ext)
                self.assertEqual(err is None, version == 6, f"version {version}: {err}")
                for row in range(ob.shape[0]):
                    st, *got = c_encode(version, mask, ob[row], d[row], ext[row])
                    what = f"version {version} mask {mask:#x} row {row}"
                    if err is not None:  # a value encoders 3 to 5 cannot show: E_UNSUPPORTED, EncoderAwaitingBit
                        self.assertIsInstance(err, features.EncoderAwaitingBit, what)
                        self.assertEqual(st, C["DUOFORGE_E_UNSUPPORTED"], what)
                        continue
                    self.assertEqual(st, 0, what)
                    self.assert_same(got, (want[0][row], want[1][row], want[2][row]), what)

    def test_fuzzed_rows_refuse_as_the_reference(self):
        with duoforge.Context() as ctx, duoforge.Batch(ctx, duoforge.reference_setups(list(range(4))), 1,
                                                       SEED) as batch:
            policy = duoforge.RandomPolicy(SEED, 4)
            policy.start_episodes(np.arange(4), np.zeros(4, dtype=np.uint64))
            batch.query_factored()
            batch.step_factored(policy.choose_factored(batch))
            batch.query_factored()
            base_ob, base_d = batch.observations.reshape(-1).copy(), batch.domains.reshape(-1).copy()
        base_ext = _records(base_ob)
        rng = np.random.default_rng(SEED + 2)
        small = (0, 1, 2, 3, 4, 5, 6, 7, 8, 18, 19, 254, 255)
        fields = [
            ("ob", ("boundary_kind",), small), ("ob", ("weather",), small), ("ob", ("terrain",), small),
            ("ob", ("player",), (0, 1, 2)), ("ob", ("epoch",), (0, 1, 7)),
            ("ob", ("sides", "members", "location"), small), ("ob", ("sides", "members", "status"), small),
            ("ob", ("sides", "positions", "reserved"), (0, 1, 2, 4, 7, 8, 16, 128)),
            ("ob", ("sides", "occupant"), (0, 5, 6, 7, 254, 255)),
            ("d", ("kind",), (0, 1, 2, 3)), ("d", ("slot_count",), (0, 1, 31, 32, 33, 255)),
            ("d", ("slots", "kind"), (0, 1, 2, 3, 4)), ("d", ("slots", "move_slot"), (0, 3, 4, 5, 6, 255)),
            ("d", ("slots", "target"), (0, 3, 4, 254, 255)),
            ("x", ("revision",), (0, 1, 2)), ("x", ("player",), (0, 1, 2)), ("x", ("epoch",), (0, 1, 7)),
            ("x", ("supported",), (0, features.BASE_VALUE_FEATURES, features.ALL_FEATURES)),
            ("x", ("field", "gravity_turns"), (0, 5, 6)), ("x", ("sides", "spikes"), (3, 4)),
            ("x", ("sides", "guard_flags"), (0, 1, 2, 3, 4, 128)),
            ("x", ("sides", "conditions"), (0, 1, 128)), ("x", ("field", "flags"), (0, 1, 1 << 15)),
            ("x", ("volatiles2",), (0, 1, 1 << 31)),
            ("x", ("sides", "positions", "volatiles"), (0, 1 << 19, 1 << 20, 1 << 21, 1 << 22, 1 << 31)),
            ("x", ("sides", "positions", "type_now"), (0, 1, 18, 19)),
            ("x", ("sides", "positions", "move_failed"), (0, 1, 2)),
            ("x", ("sides", "positions", "encore_slot"), (0, 4, 5)),
            ("x", ("sides", "positions", "ability_now"), (0, 255, 256)),
            # values, no refusal: the recipes at their edges
            ("ob", ("turn",), (0, 99, 100, 101, 65535)), ("ob", ("weather_turns",), (0, 1, 8, 255)),
            ("ob", ("sides", "positions", "protect_chain"), (0, 3, 4, 255)),
            ("ob", ("sides", "positions", "stages"), (0, 6, 12, 255)),
            ("ob", ("sides", "members", "stats"), (0, 999, 1000, 1001, 65535)),
            ("ob", ("sides", "members", "hp"), (0, 1, 65535)), ("ob", ("sides", "members", "hp_max"), (0, 1, 65535)),
            ("ob", ("sides", "members", "pp_max"), (0, 1, 255)), ("ob", ("sides", "members", "pp"), (0, 1, 255)),
            ("ob", ("sides", "members", "species_id"), (0, 1, 1234, 65535)),
            ("ob", ("sides", "members", "move_ids"), (0, 1, 40000, 65535)),
            ("ob", ("sides", "members", "move_count"), (0, 4, 5, 255)),
            ("ob", ("sides", "members", "stat_points"), (0, 32, 255)),
            ("ob", ("sides", "requested_slots"), (0, 1, 2, 3, 255)), ("ob", ("sides", "member_count"), (0, 6, 255)),
            ("d", ("slots", "mega"), (0, 1, 2)), ("d", ("slots", "reserve"), (0, 5, 6, 255)),
            ("d", ("allowed",), (0, 1, 0xFFFFFFFF)),
            ("x", ("sides", "members", "forme"), (0, 1, 65535)), ("x", ("sides", "members", "item_now"), (0, 1, 254, 255)),
            ("x", ("sides", "aurora_veil_turns"), (0, 8, 9)), ("x", ("sides", "stealth_rock"), (1, 2)),
            ("x", ("sides", "toxic_spikes"), (2, 3)), ("x", ("sides", "sticky_web"), (1, 2)),
            ("x", ("sides", "positions", "disable_slot"), (0, 4, 5)),
            ("x", ("sides", "positions", "stockpile"), (3, 4)), ("x", ("sides", "positions", "perish"), (3, 4)),
        ]
        agreements = {"accept": 0, "refuse": 0}
        for trial in range(3000):
            row = int(rng.integers(0, base_ob.shape[0]))
            ob, d, ext = base_ob[row:row + 1].copy(), base_d[row:row + 1].copy(), base_ext[row:row + 1].copy()
            for _ in range(int(rng.integers(1, 3))):  # one or two faults
                where, path, values = fields[int(rng.integers(0, len(fields)))]
                target = {"ob": ob, "d": d, "x": ext}[where]
                field = target[path[0]]  # field views of a structured array write through
                for name in path[1:]:
                    field = field[name]
                at = np.unravel_index(int(rng.integers(0, field.size)), field.shape)
                field[at] = values[int(rng.integers(0, len(values)))]
            version = VERSIONS[int(rng.integers(0, len(VERSIONS)))]
            choices = masks_for(version, features.ALL_FEATURES, rng, count=2)
            mask = choices[int(rng.integers(0, len(choices)))]
            use_ext = ext if (mask & features.RECORD_FEATURES or rng.integers(0, 2)) else None
            want, err = reference(version, mask, ob, d, use_ext)
            st, *got = c_encode(version, mask, ob[0], d[0], None if use_ext is None else use_ext[0])
            what = f"trial {trial}: version {version} mask {mask:#x}"
            if err is not None:
                self.assertNotEqual(st, 0, f"{what}: the reference refuses ({err}), C accepts")
                self.assertTrue(all(not np.asarray(g).any() for g in got), f"{what}: a refused row is all zero")
                agreements["refuse"] += 1
            else:
                self.assertEqual(st, 0, f"{what}: C refuses ({st}), the reference accepts")
                self.assert_same(got, (want[0][0], want[1][0], want[2][0]), what)
                agreements["accept"] += 1
        self.assertGreater(agreements["accept"], 100)
        self.assertGreater(agreements["refuse"], 100)

    def test_worker_counts_and_rows_agree(self):
        with duoforge.Context(data_kind=C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            pool = teams.load(ctx, ["A", "B", "C", *SAND_TEAMS])
            n = len(pool.ids)
            setups = pool.setups(np.arange(ENVS) % n, (np.arange(ENVS) + 1) % n)
            # 1, 2, 3 (16 environments split unevenly) and 8 workers against one
            others = [duoforge.Batch(ctx, setups, w, SEED) for w in (2, 3, 8)]
            with duoforge.Batch(ctx, setups, 1, SEED) as one, others[0], others[1], others[2]:
                policy = duoforge.RandomPolicy(SEED, ENVS)
                policy.start_episodes(np.arange(ENVS), np.zeros(ENVS, dtype=np.uint64))
                mask = int(one.observe_ext()[0, 0]["supported"]) & features.version_features(4)
                for _ in range(12):
                    a = [x.copy() for x in one.query_encoded(4, mask)]
                    for other in others:
                        self.assert_same(a, other.query_encoded(4, mask), "workers 1 and more")
                    ext = one.observe_ext()
                    for e in range(ENVS):
                        for p in range(2):
                            st, *row = c_encode(4, mask, one.observations[e, p], one.domains[e, p], ext[e, p])
                            self.assertEqual(st, 0)
                            self.assert_same(row, (a[0][e, p], a[1][e, p], a[2][e, p]), f"env {e} player {p}")
                    if not (one.requests["requested"] != 0).any():
                        break
                    choices = policy.choose_factored(one)
                    one.step_factored(choices)
                    for other in others:
                        other.step_factored(choices)

    def test_recorded_rows_match_the_reference(self):
        # Rows the replay pipeline (decision 0019) makes from a committed spectator log: tracker observations, not a
        # battle's, so they reach the encoder through duoforge_encode. No records: the tracker keeps none.
        from duoforge_live import data
        from duoforge_replay import game, prior
        from python.tests.test_replay_unit import FIXTURE, _Stats
        result = game.process("fixture-1", "gen9championsvgc2026regmcbo3", FIXTURE.read_text(encoding="utf-8"),
                              data.load(kind="pool"),
                              prior.Prior({"version": 1, "pastes": 0, "skipped": {}, "levels": [{}, {}, {}, {}]}),
                              _Stats())
        self.assertGreater(len(result.rows), 10)
        compared = 0
        for row in result.rows:
            for version in VERSIONS:
                masks = (0,) if version < 3 else (0, features.BASE_VALUE_FEATURES)
                for mask in masks:
                    ob, d = np.array(row.observation).reshape(1), np.array(row.domain).reshape(1)
                    want, err = reference(version, mask, ob, d, None)
                    st, *got = c_encode(version, mask, ob[0], d[0], None)
                    if err is not None:
                        self.assertNotEqual(st, 0)
                    else:
                        self.assertEqual(st, 0)
                        self.assert_same(got, (want[0][0], want[1][0], want[2][0]), f"row {row.point} v{version}")
                        compared += 1
        self.assertGreater(compared, 10)

    def test_refused_encode_stops_self_play_and_ends_no_episode(self):
        # A network of encoder 2 cannot show Sand: the encode refuses, observe() raises the reference's ValueError,
        # and nothing is counted as a game result (decision 0021: encoder refusals are not engine refusals).
        with duoforge.Context(data_kind=C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            pool = teams.load(ctx, list(SAND_TEAMS))
            env = SelfPlay(ENVS, 2, SEED, pool=pool, context=ctx, encoder=2, ext_supported=0)
            rng = np.random.default_rng(SEED)
            try:
                for _ in range(200):
                    episodes, unsupported = env.episodes.copy(), env.engine_unsupported
                    try:
                        o = env.observe()
                    except ValueError as err:
                        self.assertIn("weather", str(err))
                        self.assertTrue(np.array_equal(env.episodes, episodes))
                        self.assertEqual(env.engine_unsupported, unsupported)
                        return
                    m = o.mask.reshape(-1, PAIR_VALUES)
                    acts = np.array([rng.choice(np.flatnonzero(r)) if r.any() else 0 for r in m])
                    acts = np.where(o.is_team.reshape(-1), rng.integers(0, 360, acts.shape), acts)
                    env.step(acts.reshape(ENVS, 2))
            finally:
                env.close()
        self.fail("Sand never appeared in 200 steps")


if __name__ == "__main__":
    unittest.main()
