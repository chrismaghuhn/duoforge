"""duoforge.python.learn_v2_numpy: the NumPy parts of Learner v2 (decision 0017).

Column groups and the host id check of model v2, the team pool's weighted
pairings, the league state machine, schedules, the evaluation suite and
the per-team ladder fits. The JAX parts are in test_learn_v2.py.
"""
import os
import tempfile
import unittest

import numpy as np

import duoforge
from duoforge import _layout, features, teams
from duoforge_learn import checkpoint, columns, evaluate, ladder, league, pairing, runstate, schedule, suite
from duoforge_learn.selfplay import SelfPlay


def _config(**extra):
    """A complete format-2 config of a small v1 network."""
    return {"model": {"version": 1, "hidden": 8, "option_hidden": 4}, "encoder": features.ENCODER,
            "features": list(features.FEATURE_NAMES), "slot_features": list(features.SLOT_FEATURE_NAMES),
            "data": {"kind": "closure", "fingerprint": "00"}, "teams": {"ids": ["A", "B"], "sha256": ["", ""],
                                                                        "weights": [1.0, 1.0]},
            "update": 3, "decisions": 99, **extra}


def _v1_params(rng, obs=features.OBS_SIZE, slot=features.SLOT_FEATURES, hidden=8, option=4):
    shapes = {"t1": (obs, hidden), "t2": (hidden, hidden), "option_torso": (hidden, option),
              "option_features": (slot, option), "option_out": (option, 2), "team": (hidden, 360),
              "value": (hidden, 1)}
    return {k: {"w": rng.standard_normal(s).astype(np.float32), "b": rng.standard_normal(s[1]).astype(np.float32)}
            for k, s in shapes.items()}


class ColumnsTest(unittest.TestCase):
    def test_groups_partition_the_observation(self):
        cols = columns.columns()
        parts = [cols.glob, cols.side, cols.position, cols.occupant, cols.member, cols.species, cols.item,
                 cols.ability, cols.nature, cols.moves, cols.pp, cols.move_count, cols.present]
        every = np.concatenate([p.reshape(-1) for p in parts])
        self.assertEqual(sorted(every.tolist()), list(range(features.OBS_SIZE)))
        names = features.FEATURE_NAMES
        self.assertTrue(all(names[i].startswith(("global.", "ext.global.")) for i in cols.glob))
        self.assertTrue(all(".occupant." in names[i] for i in cols.occupant.reshape(-1)))
        self.assertEqual(names[cols.species[1, 3]], "foe.member3.species")
        self.assertEqual(names[cols.moves[0, 2, 1]], "own.member2.move1")
        self.assertEqual(names[cols.position[1, 0, 0]], "foe.pos0.stage.atk")
        # Encoder 3's block joins the scalars of its global, side, position and member.
        self.assertEqual(cols.glob.shape, (15 + 5,))
        self.assertEqual(cols.position.shape, (2, 2, 17 + 36))
        self.assertEqual(names[cols.position[1, 0, 17]], "ext.foe.pos0.volatile.substitute")
        self.assertEqual(names[cols.side[1, -1]], "ext.foe.quick_guard")
        self.assertEqual(names[cols.member[0, 3, -1]], "ext.own.mem3.item_now")
        for groups in (cols.side, cols.position, cols.member):
            for s, side in enumerate(("own", "foe")):
                self.assertTrue(all(names[i].startswith((f"{side}.", f"ext.{side}.")) for i in groups[s].reshape(-1)))
        self.assertEqual([features.SLOT_FEATURE_NAMES[i] for i in cols.slot_move], ["move_slot"])
        self.assertEqual([features.SLOT_FEATURE_NAMES[i] for i in cols.slot_reserve], ["reserve"])
        self.assertEqual(cols.slot_scalar.shape, (10,))

    def test_unknown_column_name_is_refused(self):
        with self.assertRaisesRegex(ValueError, "own.member0.weight"):
            columns.columns(features.FEATURE_NAMES + ("own.member0.weight",))

    def test_check_ids_refuses_an_id_at_capacity(self):
        cols = columns.columns()
        obs = np.zeros((2, features.OBS_SIZE), dtype=np.float32)
        caps = {"species": 1024, "move": 1024, "item": 256, "ability": 256, "nature": 25}
        obs[1, cols.species[0, 0]] = np.float32(1023 / 65535)
        columns.check_ids(obs, cols, caps)
        obs[1, cols.species[0, 0]] = np.float32(1024 / 65535)
        with self.assertRaisesRegex(ValueError, "species id 1024 is outside the model's capacity 1024"):
            columns.check_ids(obs, cols, caps)


class CheckpointTest(unittest.TestCase):
    def test_format2_round_trip(self):
        params = _v1_params(np.random.default_rng(1))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "params-3.npz")
            checkpoint.save(path, params, _config())
            back, config = checkpoint.load(path)
        self.assertEqual(config["format"], 2)
        self.assertEqual(config["features"], list(features.FEATURE_NAMES))
        self.assertEqual(config["update"], 3)
        for layer in params:
            for k in ("w", "b"):
                self.assertTrue(np.array_equal(back[layer][k], params[layer][k]))

    def test_save_requires_the_format2_keys(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaisesRegex(ValueError, "teams"):
            cfg = _config()
            del cfg["teams"]
            checkpoint.save(os.path.join(d, "p.npz"), _v1_params(np.random.default_rng(1)), cfg)

    def test_dropped_column_is_refused(self):
        cfg = _config(features=list(features.FEATURE_NAMES) + ["own.member0.weight"])
        params = _v1_params(np.random.default_rng(1), obs=features.OBS_SIZE + 1)
        with self.assertRaisesRegex(ValueError, "own.member0.weight"):
            checkpoint.widen(params, cfg, features.FEATURE_NAMES, features.SLOT_FEATURE_NAMES)

    def test_widening_inserts_zero_rows_by_name(self):
        flags = [n for n in features.FEATURE_NAMES if n.endswith(".flag.follow_me")]
        old = [n for n in features.FEATURE_NAMES if n not in flags]
        params = _v1_params(np.random.default_rng(2), obs=len(old))
        wide, cfg = checkpoint.widen(params, _config(features=old), features.FEATURE_NAMES,
                                     features.SLOT_FEATURE_NAMES)
        self.assertEqual(cfg["features"], list(features.FEATURE_NAMES))
        w = wide["t1"]["w"]
        for n in flags:
            self.assertFalse(w[features.FEATURE_NAMES.index(n)].any())
        for i, n in enumerate(old):
            self.assertTrue(np.array_equal(w[features.FEATURE_NAMES.index(n)], params["t1"]["w"][i]))


class IdTablesTest(unittest.TestCase):
    """checkpoint.ids_of and check_ids (spec 12.4): the names behind the embedded ids, so that a checkpoint
    is never read under tables whose ids mean something else."""

    def setUp(self):
        self.ctx = duoforge.Context(data_kind=_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"])
        self.ids = checkpoint.ids_of(self.ctx)

    def tearDown(self):
        self.ctx.close()

    def test_ids_of_lists_every_table_in_id_order(self):
        from duoforge import data
        self.assertEqual(sorted(self.ids), sorted(checkpoint.EMBEDDINGS))
        for kind, table in (("species", data.TABLE_SPECIES), ("move", data.TABLE_MOVE), ("item", data.TABLE_ITEM),
                            ("ability", data.TABLE_ABILITY), ("nature", data.TABLE_NATURE)):
            self.assertEqual(len(self.ids[kind]), data.count(self.ctx, table))
            last = len(self.ids[kind]) - 1
            self.assertEqual(self.ids[kind][last], data.name(self.ctx, table, last))
            self.assertEqual(self.ids[kind][1], data.name(self.ctx, table, 1))

    def test_same_and_appended_names_pass(self):
        checkpoint.check_ids({"ids": self.ids}, self.ctx)
        checkpoint.check_ids({"ids": {k: v[:-1] for k, v in self.ids.items()}}, self.ctx)

    def test_a_moved_id_is_refused_naming_it(self):
        moves = list(self.ids["move"])
        moves[3], moves[4] = moves[4], moves[3]
        with self.assertRaisesRegex(ValueError, f"move id 3: {moves[3]} -> {self.ids['move'][3]}"):
            checkpoint.check_ids({"ids": {**self.ids, "move": moves}}, self.ctx)

    def test_a_removed_id_is_refused(self):
        with self.assertRaisesRegex(ValueError, "nature"):
            checkpoint.check_ids({"ids": {**self.ids, "nature": self.ids["nature"] + ["extra"]}}, self.ctx)

    def test_a_config_without_tables_or_a_kind_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no id tables"):
            checkpoint.check_ids({}, self.ctx)
        with self.assertRaisesRegex(ValueError, "ability"):
            checkpoint.check_ids({"ids": {k: v for k, v in self.ids.items() if k != "ability"}}, self.ctx)


class PairingTest(unittest.TestCase):
    def test_pairings_are_pure_and_uniform(self):
        envs = np.repeat(np.arange(100), 90)
        episodes = np.tile(np.arange(90), 100)
        weights = np.ones(3)
        a0, a1 = pairing.pairings(7, envs, episodes, weights)
        b0, b1 = pairing.pairings(7, envs, episodes, weights)
        self.assertTrue(np.array_equal(a0, b0) and np.array_equal(a1, b1))
        alone = [pairing.pairings(7, envs[i:i + 1], episodes[i:i + 1], weights) for i in range(0, 9000, 997)]
        for k, i in enumerate(range(0, 9000, 997)):
            self.assertEqual((int(alone[k][0][0]), int(alone[k][1][0])), (int(a0[i]), int(a1[i])))
        counts = np.bincount(a0 * 3 + a1, minlength=9)
        self.assertTrue(((counts > 880) & (counts < 1120)).all(), counts.tolist())
        c0, _ = pairing.pairings(8, envs, episodes, weights)
        self.assertFalse(np.array_equal(a0, c0))

    def test_zero_weight_is_never_drawn(self):
        envs = np.arange(4000)
        side0, side1 = pairing.pairings(11, envs, np.zeros(4000, dtype=np.int64), np.array([1.0, 0.0, 3.0]))
        both = np.concatenate([side0, side1])
        self.assertFalse((both == 1).any())
        ratio = (both == 2).sum() / (both == 0).sum()
        self.assertTrue(2.6 <= ratio <= 3.4, ratio)

    def test_trailing_zero_weight_is_never_drawn_even_at_the_top_draw(self):
        rng = np.random.default_rng(3)
        top = np.array([np.iinfo(np.uint64).max], dtype=np.uint64)
        for n in range(9, 41):
            w = np.concatenate([rng.random(n - 1), [0.0]])
            self.assertLess(int(pairing.pick(top, w)[0]), n - 1)
        self.assertEqual(int(pairing.pick(top, np.array([1.0, 0.0, 2.0, 0.0, 0.0]))[0]), 2)

    def test_draw_is_the_documented_formula(self):
        mask = (1 << 64) - 1

        def mix(x):
            z = (x + 0x9E3779B97F4A7C15) & mask
            z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & mask
            z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & mask
            return z ^ (z >> 31)

        want = mix((mix((mix((5 + pairing.PAIR_SIDE1) & mask) + 3) & mask) + 9) & mask)
        got = pairing.draw(5, pairing.PAIR_SIDE1, np.array([3]), np.array([9]))
        self.assertEqual(int(got[0]), want)


def _first_legal(o):
    """Actions (E, 2): the first allowed pair, or team tuple 0."""
    flat = o.mask.reshape(o.mask.shape[0], 2, -1)
    return np.where(o.is_team, 0, np.argmax(flat, axis=-1))


class SelfPlayPoolTest(unittest.TestCase):
    def test_ended_environment_gets_its_drawn_pairing(self):
        seed = 0x2026100200000174
        pool = teams.TeamPool.from_setups(("A", "B"), duoforge.reference_setups([0])["sides"][0], (1.0, 2.0))
        env = SelfPlay(6, 1, seed, pool=pool, max_steps=40)
        try:
            for _ in range(200):
                _, done = env.step(_first_legal(env.observe()))
                if done.any():
                    break
            e = int(np.flatnonzero(done)[0])
            k = int(env.episodes[e])
            self.assertEqual(k, 1)
            p0, p1 = pairing.pairings(seed, [e], [k], pool.weights)
            self.assertEqual(env.pairing[e].tolist(), [int(p0[0]), int(p1[0])])
            setups = pool.setups(np.zeros(6, dtype=np.int64), np.zeros(6, dtype=np.int64))
            setups[e] = pool.setups(p0, p1)[0]
            with duoforge.Batch(env.context, setups, 1, seed) as fresh:
                fresh.reset(e, k)
                self.assertEqual(env.batch.digest(e), fresh.digest(e))
        finally:
            env.close()

    def test_start_episodes_are_used(self):
        seed = 0x2026100200000175
        starts = []
        env = SelfPlay(2, 1, seed, start_episodes=np.array([5, 9], dtype=np.uint32),
                       on_start=lambda envs, eps: starts.append((list(envs), list(eps))))
        try:
            self.assertEqual([env.batch.episode(0), env.batch.episode(1)], [5, 9])
            p0, p1 = pairing.pairings(seed, [0, 1], [5, 9], env.pool.weights)
            self.assertEqual(env.pairing.tolist(), [[int(p0[0]), int(p1[0])], [int(p0[1]), int(p1[1])]])
            self.assertEqual(starts, [([0, 1], [5, 9])])
        finally:
            env.close()


def _started(state, envs, episodes):
    state.start(np.asarray(envs), np.asarray(episodes))


class LeagueTest(unittest.TestCase):
    def test_groups_and_seats(self):
        st = league.LeagueState(8, 0.5, 4, 50, 1)
        self.assertEqual(st.self_play.tolist(), [True] * 4 + [False] * 4)
        self.assertEqual(st.learner_seat.tolist(), [-1, -1, -1, -1, 0, 1, 0, 1])
        rows = st.learner_rows()
        self.assertEqual(rows[:4].tolist(), [[True, True]] * 4)
        self.assertEqual(rows[4:].tolist(), [[True, False], [False, True], [True, False], [False, True]])
        with self.assertRaisesRegex(ValueError, "at least 2 slots"):
            league.LeagueState(8, 0.5, 1, 50, 1)
        self.assertFalse(league.LeagueState(8, 1.0, 0, 50, 1).learner_rows().sum() != 16)

    def test_slots_change_only_at_episode_starts(self):
        st = league.LeagueState(8, 0.5, 4, 1, 1)
        _started(st, range(8), [0] * 8)
        self.assertEqual((st.slot_of[:4] == -1).all(), True)
        self.assertTrue((st.slot_of[4:] >= 0).all())
        before = st.slot_of.copy()
        st.tick(1)
        st.load(1, "update 9") if st.ready() == 1 else None
        self.assertEqual(st.slot_of.tolist(), before.tolist())
        self.assertEqual(int(st.active.sum()), 4)

    def test_draining_slot_takes_no_new_episodes_and_reloads_when_empty(self):
        st = league.LeagueState(20, 0.0, 2, 1, 3)
        _started(st, range(20), [0] * 20)
        st.tick(1)
        self.assertEqual(st.draining, 0)
        on_zero = np.flatnonzero(st.slot_of == 0)
        for k, e in enumerate(range(20)):
            st.end(np.array([e]), np.array([0]))
            _started(st, [e], [1])
            self.assertEqual(int(st.slot_of[e]), 1)
            expect = 0 if k == 19 or set(on_zero) <= set(range(k + 1)) else -1
            self.assertEqual(st.ready(), expect)
        st.load(0, "update 1")
        self.assertEqual((st.draining, st.snapshots[0]), (-1, "update 1"))

    def test_one_slot_drains_at_a_time(self):
        st = league.LeagueState(6, 0.0, 3, 2, 1)
        _started(st, range(6), [0] * 6)
        st.tick(2)
        st.tick(4)
        self.assertEqual(st.draining, 0)
        st.tick(5)
        self.assertEqual(st.draining, 0)

    def test_stats_count_wins_and_ties(self):
        st = league.LeagueState(4, 0.0, 2, 50, 1)
        _started(st, range(4), [0] * 4)
        snaps = [st.snapshots[s] for s in st.slot_of]
        st.end(np.arange(4), np.array([1, -1, 0, 1]))
        self.assertEqual(sum(v[0] for v in st.stats.values()), 4)
        self.assertEqual(sum(v[1] for v in st.stats.values()), 2)
        self.assertEqual(sum(v[2] for v in st.stats.values()), 1)
        self.assertEqual(set(st.stats), set(snaps))
        self.assertEqual(int(st.active.sum()), 0)

    def test_state_round_trip(self):
        st = league.LeagueState(10, 0.4, 3, 7, 5)
        _started(st, range(10), [2] * 10)
        st.tick(7)
        st.end(np.array([9]), np.array([1]))
        back = league.LeagueState.from_dict(st.to_dict())
        for k in ("self_play", "learner_seat", "slot_of", "active"):
            self.assertEqual(getattr(back, k).tolist(), getattr(st, k).tolist())
        self.assertEqual((back.snapshots, back.draining, back.stats), (st.snapshots, st.draining, st.stats))

    def test_cut_off_episodes_release_their_slot(self):
        st = league.LeagueState(6, 0.0, 2, 1, 4)
        env = SelfPlay(6, 1, 0x2026100200000176, max_steps=5, on_start=st.start,
                       on_end=lambda envs, rewards: st.end(envs, league.learner_results(st, envs, rewards)))
        try:
            st.tick(1)
            loaded = False
            for _ in range(30):
                env.step(_first_legal(env.observe()))
                if st.ready() == 0:
                    st.load(0, "update 1")
                    loaded = True
                    break
            self.assertTrue(loaded)
            self.assertEqual(int(st.active.sum()), 6)
        finally:
            env.close()

    def test_samples_keep_only_learner_rows(self):
        from duoforge_learn.returns import samples_of
        t, e = 3, 4
        rollout = {"obs": np.zeros((t, e, 2, 5)), "slots": np.zeros((t, e, 2, 2, 32, 12)),
                   "mask": np.zeros((t, e, 2, 32, 32), bool), "is_team": np.zeros((t, e, 2), bool),
                   "acting": np.ones((t, e, 2), bool), "actions": np.arange(t * e * 2).reshape(t, e, 2),
                   "logp": np.zeros((t, e, 2)), "values": np.zeros((t, e, 2))}
        rows = np.array([[True, True], [True, True], [True, False], [False, True]])
        samples = samples_of(rollout, np.zeros((t, e, 2)), np.zeros((t, e, 2)), rows)
        keep = np.broadcast_to(rows, (t, e, 2)).reshape(-1)
        self.assertEqual(samples["actions"].tolist(), np.arange(t * e * 2)[keep].tolist())


class ScheduleTest(unittest.TestCase):
    def test_constant(self):
        s = schedule.Schedule.parse("0.01")
        self.assertEqual((s(0), s(10 ** 9)), (0.01, 0.01))

    def test_interpolates_and_holds(self):
        s = schedule.Schedule.parse("0:0.02,500M:0.01,2G:0.003")
        self.assertAlmostEqual(s(250_000_000), 0.015)
        self.assertAlmostEqual(s(500_000_000), 0.01)
        self.assertAlmostEqual(s(1_250_000_000), 0.0065)
        self.assertAlmostEqual(s(5_000_000_000), 0.003)
        self.assertEqual(schedule.Schedule.parse(str(s)).points, s.points)
        self.assertEqual(schedule.Schedule.parse("0:1,2K:0")(1000), 0.5)

    def test_refusals(self):
        for bad in ("", "5:0.1", "0:0.1,0:0.2", "0:-1", "0:0.1,1X:0.2", "0:nan", "abc", "0:0.1,,1M:0.2"):
            with self.assertRaises(ValueError, msg=bad):
                schedule.Schedule.parse(bad)


def _state(rng):
    return {"params": _v1_params(rng), "opt_leaves": [np.arange(3.0), rng.standard_normal((2, 2))],
            "counters": {"update": 7, "decisions": 1234, "episodes": 56},
            "episodes_seen": np.array([3, -1, 9], dtype=np.int64), "jax_key": np.array([1, 2], dtype=np.uint32),
            "league": league.LeagueState(4, 0.5, 2, 3, 1).to_dict(),
            "numpy_rng": np.random.default_rng(5).bit_generator.state,
            "teams": {"ids": ["A", "B"], "sha256": ["", ""], "weights": [1.0, 1.0]},
            "data": {"kind": "closure", "fingerprint": "ab"}, "model": {"version": 1, "hidden": 8, "option_hidden": 4},
            "features": list(features.FEATURE_NAMES), "slot_features": list(features.SLOT_FEATURE_NAMES),
            "encoder": 2, "train": {"envs": 4}}


class RunStateTest(unittest.TestCase):
    def _same(self, a, b):
        self.assertEqual(sorted(a), sorted(b))
        for k in a:
            if k == "params":
                for layer in a[k]:
                    for f in ("w", "b"):
                        self.assertTrue(np.array_equal(a[k][layer][f], b[k][layer][f]))
            elif k == "opt_leaves":
                self.assertEqual(len(a[k]), len(b[k]))
                for x, y in zip(a[k], b[k]):
                    self.assertTrue(np.array_equal(x, y))
            elif isinstance(a[k], np.ndarray):
                self.assertTrue(np.array_equal(a[k], b[k]) and a[k].dtype == b[k].dtype, k)
            else:
                self.assertEqual(a[k], b[k], k)

    def test_state_round_trip(self):
        state = _state(np.random.default_rng(1))
        with tempfile.TemporaryDirectory() as d:
            runstate.save_state(d, state)
            self._same(state, runstate.load_state(d))

    def test_missing_state_names_the_run(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaisesRegex(FileNotFoundError, "no run state"):
            runstate.load_state(d)

    def test_previous_state_rotates(self):
        with tempfile.TemporaryDirectory() as d:
            first, second = _state(np.random.default_rng(1)), _state(np.random.default_rng(2))
            second["counters"] = dict(second["counters"], update=8)
            runstate.save_state(d, first)
            runstate.save_state(d, second)
            self.assertEqual(runstate.load_state(d)["counters"]["update"], 8)
            self.assertEqual(runstate.load_state(d, previous=True)["counters"]["update"], 7)

    def test_interrupted_write_keeps_the_previous_state(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            runstate.save_state(d, _state(np.random.default_rng(1)))
            broken = _state(np.random.default_rng(2))
            broken["counters"] = dict(broken["counters"], update=99)
            with mock.patch.object(runstate, "_write", side_effect=OSError("disk full")), \
                    self.assertRaises(OSError):
                runstate.save_state(d, broken)
            self.assertEqual(runstate.load_state(d)["counters"]["update"], 7)


def _learner_team(rows):
    return np.where(rows["learner_seat"] == 0, rows["side0"], rows["side1"]).astype(np.int64)


def _opponent_team(rows):
    return np.where(rows["learner_seat"] == 0, rows["side1"], rows["side0"]).astype(np.int64)


class SuiteTest(unittest.TestCase):
    def test_small_pool_is_complete(self):
        rows = suite.make_suite(3, 7)
        self.assertEqual(rows.shape, (36,))
        keys = list(zip(_learner_team(rows).tolist(), _opponent_team(rows).tolist(), rows["learner_seat"].tolist()))
        for i in range(3):
            for j in range(3):
                for seat in (0, 1):
                    self.assertEqual(keys.count((i, j, seat)), 2)

    def test_large_pool_is_stratified(self):
        rows = suite.make_suite(12, 7, budget=512)
        self.assertEqual(rows.shape, (512,))
        mine = _learner_team(rows)
        per_team = np.bincount(mine, minlength=12)
        self.assertTrue(set(per_team.tolist()) <= {42, 43}, per_team.tolist())
        for i in range(12):
            opp = np.bincount(_opponent_team(rows[mine == i]), minlength=12)
            self.assertLessEqual(int(opp.max() - opp.min()), 1)
        seats = np.bincount(rows["learner_seat"], minlength=2)
        self.assertLessEqual(abs(int(seats[0] - seats[1])), 12)

    def test_suite_is_deterministic(self):
        self.assertEqual(suite.make_suite(12, 7).tobytes(), suite.make_suite(12, 7).tobytes())
        self.assertNotEqual(suite.make_suite(12, 7).tobytes(), suite.make_suite(12, 8).tobytes())
        self.assertEqual(suite.make_suite(3, 7).tobytes(), suite.make_suite(3, 7).tobytes())


class _StandIn:
    """A NumPy model with policy.Model's act: prefer "attack" (moves at a
    foe) or "switch"; records the observations it was given."""

    def __init__(self, prefer):
        self.prefer, self.seen = prefer, []

    def check(self, obs):
        pass

    def act(self, params, key, obs, slots, mask, is_team, greedy=False):
        self.seen.append(np.array(obs))
        n = obs.shape[0]
        kind = slots[..., 1:5].argmax(axis=-1)
        valid = slots[..., 0] > 0
        at_foe = slots[..., 8:10].sum(axis=-1) > 0
        if self.prefer == "attack":
            score = np.where(kind == 1, np.where(at_foe, 2.0, 1.0), 0.0)
        else:
            score = np.where(kind == 2, 2.0, np.where(kind == 1, 1.0, 0.0))
        score = np.where(valid, score, -1.0)
        pairs = np.where(mask, score[:, 0, :, None] + score[:, 1, None, :], -1e9).reshape(n, -1)
        return np.where(is_team, 0, pairs.argmax(axis=1)), np.zeros(n), np.zeros(n)


def _ab_pool():
    return teams.TeamPool.from_setups(("A", "B"), duoforge.reference_setups([0])["sides"][0])


class SuitePlayTest(unittest.TestCase):
    def test_records_credit_the_learner_seat(self):
        pool = _ab_pool()
        rows = suite.make_suite(2, 3, games=2)
        attack = evaluate.Player(_StandIn("attack"), None, features.ENCODER, "attack")
        switch = evaluate.Player(_StandIn("switch"), None, features.ENCODER, "switch")
        with duoforge.Context() as ctx:
            strong = evaluate.play_suite(ctx, pool, rows, attack, switch, workers=2, seed=5)
            weak = evaluate.play_suite(ctx, pool, rows, switch, attack, workers=2, seed=5)
        self.assertEqual(strong.shape, rows.shape)
        self.assertEqual(strong["learner_seat"].tolist(), rows["learner_seat"].tolist())
        a, b = evaluate.scores(strong, 2), evaluate.scores(weak, 2)
        self.assertGreater(a["score"], 0.5)
        self.assertLess(b["score"], 0.5)
        for seat in (0, 1):
            self.assertGreater(float((strong["result"][strong["learner_seat"] == seat] > 0).mean()), 0.5)
        self.assertEqual(len(a["by_team"]), 2)
        self.assertAlmostEqual(a["score"] + b["score"], 1.0, places=6)

    def test_each_seat_uses_its_players_encoder_setting(self):
        pool = teams.TeamPool.from_setups(("A",), duoforge.reference_setups([0])["sides"][0][:1])
        rows = suite.make_suite(1, 3, games=1)
        old, new = _StandIn("attack"), _StandIn("attack")
        with duoforge.Context() as ctx:
            evaluate.play_suite(ctx, pool, rows, evaluate.Player(old, None, 1, "old"),
                                evaluate.Player(new, None, 2, "new"), workers=1, seed=5, max_steps=3)
        column = features.FEATURE_NAMES.index("own.member0.present")  # Rillaboom, forme 0
        self.assertTrue(old.seen and new.seen)
        self.assertTrue(all((x[:, column] == 0.0).all() for x in old.seen))
        self.assertTrue(all((x[:, column] == 1.0).all() for x in new.seen))

    def test_scores_count_ties_half(self):
        rec = np.zeros(4, dtype=evaluate.RECORD)
        rec["side0"], rec["side1"], rec["learner_seat"] = [0, 0, 1, 1], [1, 1, 0, 0], [0, 1, 0, 1]
        rec["result"] = [1, 0, -1, 1]
        got = evaluate.scores(rec, 2)
        self.assertAlmostEqual(got["score"], 2.5 / 4)
        self.assertEqual(got["by_team"], [1.0, 0.25])


def _records(pairs):
    """{(i, j): RECORD array} from {(i, j): [(learner team, opponent team, result), ...]}."""
    out = {}
    for key, games in pairs.items():
        rec = np.zeros(len(games), dtype=evaluate.RECORD)
        for k, (mine, other, result) in enumerate(games):
            rec[k] = (mine, other, 0, result, False, False)
        out[key] = rec
    return out


class LadderPerTeamTest(unittest.TestCase):
    def test_per_team_fit_separates_teams(self):
        # Player 1 beats player 0 whenever it pilots team 0 and loses whenever it pilots team 1.
        games = [(0, 0, 1)] * 10 + [(1, 1, -1)] * 10
        records = _records({(1, 0): games})
        team0, team1 = ladder.fit(records, 2, team=0), ladder.fit(records, 2, team=1)
        self.assertGreater(team0[1], team0[0])
        self.assertLess(team1[1], team1[0])
        overall = ladder.fit(records, 2)
        self.assertAlmostEqual(overall[1] - overall[0], 0.0, places=6)

    def test_bootstrap_contains_the_estimate_and_is_deterministic(self):
        games = [(0, 1, 1)] * 14 + [(0, 1, -1)] * 6 + [(1, 0, 0)] * 4
        records = _records({(1, 0): games})
        point = ladder.fit(records, 2)
        low, high = ladder.bootstrap(records, 2, resamples=200)
        self.assertTrue((low <= point + 1e-9).all() and (point <= high + 1e-9).all())
        self.assertGreater(high[1] - low[1], 0.0)
        again = ladder.bootstrap(records, 2, resamples=200)
        self.assertTrue(np.array_equal(low, again[0]) and np.array_equal(high, again[1]))


class TiebreakTest(unittest.TestCase):
    def test_cut_offs_are_scored_by_tiebreak(self):
        from duoforge_learn import selfplay
        seen = []
        env = [None]

        def ended(envs, rewards):
            for e, r in zip(envs.tolist(), rewards.tolist()):
                if env[0]._steps[e] >= env[0].max_steps:  # a cut-off, before the reset
                    try:
                        want = selfplay._REWARDS[env[0].batch.tiebreak(e)]
                    except duoforge.DuoforgeError:
                        want = (-1.0, -1.0)
                    seen.append((tuple(r), tuple(want)))

        env[0] = SelfPlay(8, 1, 0x2026100200000178, max_steps=5, on_end=ended)
        try:
            for _ in range(25):
                env[0].step(_first_legal(env[0].observe()))
        finally:
            env[0].close()
        self.assertGreater(len(seen), 8)
        self.assertTrue(all(got == want for got, want in seen), seen[:5])
        self.assertTrue(any(got != (0.0, 0.0) for got, _ in seen))

    def test_unfinished_suite_games_are_scored_by_tiebreak(self):
        rows = suite.make_suite(2, 3, games=1)
        attack = evaluate.Player(_StandIn("attack"), None, features.ENCODER, "attack")
        switch = evaluate.Player(_StandIn("switch"), None, features.ENCODER, "switch")
        with duoforge.Context() as ctx:
            rec = evaluate.play_suite(ctx, _ab_pool(), rows, attack, switch, workers=1, seed=5, max_steps=4)
        self.assertTrue(rec["unfinished"].all())
        self.assertTrue((rec["result"] != 0).any())
        self.assertFalse(rec["unresolved"].any())


class UnresolvedTiebreakTest(unittest.TestCase):
    def _unsupported(self, *args):
        raise duoforge.DuoforgeError("DUOFORGE_E_UNSUPPORTED")

    def test_unresolved_cut_off_is_a_loss_for_both_and_counted(self):
        from unittest import mock
        ends = []
        env = SelfPlay(4, 1, 0x2026100200000179, max_steps=3,
                       on_end=lambda envs, rewards: ends.extend(rewards.tolist()))
        try:
            with mock.patch.object(duoforge.Batch, "tiebreak", self._unsupported):
                for _ in range(3):
                    env.step(_first_legal(env.observe()))
        finally:
            env.close()
        self.assertEqual(env.unresolved, env.cuts)
        self.assertGreater(env.cuts, 0)
        self.assertTrue(all(r == [-1.0, -1.0] for r in ends), ends)

    def test_unresolved_suite_game_is_the_learners_loss(self):
        from unittest import mock
        rows = suite.make_suite(2, 3, games=1)
        attack = evaluate.Player(_StandIn("attack"), None, features.ENCODER, "attack")
        with duoforge.Context() as ctx, mock.patch.object(duoforge.Batch, "tiebreak", self._unsupported):
            rec = evaluate.play_suite(ctx, _ab_pool(), rows, attack, attack, workers=1, seed=5, max_steps=2)
        self.assertTrue(rec["unresolved"].all())
        self.assertTrue((rec["result"] == -1).all())


UNSUPPORTED = 11  # DUOFORGE_E_UNSUPPORTED


def _fail_env_once(method, env):
    """A Batch method that runs as usual but reports E_UNSUPPORTED for one
    environment on its first call (as the engine does where a residual order
    would depend on unstored state, #154)."""
    calls = []

    def wrapped(self, *args, **kwargs):
        method(self, *args, **kwargs)
        if not calls:
            calls.append(1)
            statuses = np.zeros(self.envs, dtype=np.uint32)
            statuses[env] = UNSUPPORTED
            self.statuses[:] = statuses
            raise duoforge.DuoforgeError("DUOFORGE_E_UNSUPPORTED", statuses)
    return wrapped


class EngineUnsupportedTest(unittest.TestCase):
    def test_selfplay_ends_an_unsupported_environment_as_unresolved(self):
        from unittest import mock
        ends = []
        env = SelfPlay(4, 1, 0x2026100300000001, on_end=lambda envs, rewards: ends.append((envs.tolist(),
                                                                                         rewards.tolist())))
        try:
            with mock.patch.object(duoforge.Batch, "step_factored",
                                   _fail_env_once(duoforge.Batch.step_factored, 2)):
                rewards, done = env.step(_first_legal(env.observe()))
            self.assertTrue(done[2])
            self.assertEqual(rewards[2].tolist(), [-1.0, -1.0])
            self.assertEqual(env.engine_unsupported, 1)
            self.assertEqual(int(env.episodes[2]), 1)
            env.step(_first_legal(env.observe()))  # the loop goes on
        finally:
            env.close()
        self.assertIn(([2], [[-1.0, -1.0]]), ends)

    def test_selfplay_still_raises_other_failures(self):
        from unittest import mock

        def broken(self, *args, **kwargs):
            statuses = np.zeros(self.envs, dtype=np.uint32)
            statuses[1] = 8  # E_INVARIANT
            raise duoforge.DuoforgeError("DUOFORGE_E_INVARIANT", statuses)

        env = SelfPlay(4, 1, 0x2026100300000002)
        try:
            with mock.patch.object(duoforge.Batch, "step_factored", broken), \
                    self.assertRaises(duoforge.DuoforgeError):
                env.step(_first_legal(env.observe()))
        finally:
            env.close()

    def test_suite_game_the_engine_cannot_run_is_the_learners_loss(self):
        from unittest import mock
        rows = suite.make_suite(2, 3, games=1)
        attack = evaluate.Player(_StandIn("attack"), None, features.ENCODER, "attack")
        with duoforge.Context() as ctx, mock.patch.object(duoforge.Batch, "step",
                                                          _fail_env_once(duoforge.Batch.step, 0)):
            rec = evaluate.play_suite(ctx, _ab_pool(), rows, attack, attack, workers=1, seed=5)
        self.assertTrue(rec["unresolved"][0])
        self.assertEqual(int(rec["result"][0]), -1)
        self.assertFalse(rec["unresolved"][1:].any())


if __name__ == "__main__":
    unittest.main()
