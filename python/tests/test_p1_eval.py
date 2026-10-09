"""duoforge.python.p1_eval: the stage 3 P1 evaluation games (duoforge_learn.p1_eval, plan C5's runner).

- The schedule mapping, all 12288 rows without play (play_suite replaced): one play_suite call per (suite,
  opponent, arm, bucket, seat) with the block's pairs in pair order (environment = pair) and the block's one batch
  seed, the row's arm against the row's opponent checkpoint, the student's team on its seat; the records pass
  expert_eval's checks and complete every gate group. A subset that is no pair prefix of its call, or a call
  with two seeds, is refused.
- The smoke: a predeclared stratified selection of 64 games (round robin over the (block, arm, bucket) units, both
  seats, pairs in order), its report and its STOP rules.
- Real games on a subset (untrained v2-S networks in temporary directories, CPU, a short cut-off): the records pass
  expert_eval._check_records, the Trick Room fields are integers, a refused game is unfinished with a null score
  and counted apart from cut-offs, the same inputs give the same record bytes, an older format-2 layout plays in
  its own encoder, and checkpoints that cannot be served are refused (format 1, another layout, a hash, data
  kinds, ids).
- The CLI end to end (the whole schedule) into expert_eval's main, the smoke CLI, the ledger (with and without a
  file, charged on a refusal) and the refusals, including a GPU without deterministic XLA ops.

Synthetic checkpoints and manifests only; nothing is written inside the repository.
"""
import contextlib
import io
import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

import duoforge
from duoforge import _layout, features, teams

C = _layout.CONSTANTS
STEPS = 40  # the tests' cut-off (production: p1_eval.MAX_STEPS)
NAMES = ("pilot", "control", "frozen", "BC", "3600", "11000", "ladder")
REPO = Path(__file__).resolve().parents[2]


def _pool():
    from python.tests.test_expert_eval import pool
    return pool()


def _save(path, ctx, seed, encoder=4, **change):
    """A format-2 checkpoint of an untrained v2-S network of encoder `encoder`'s layout, data of ctx."""
    import jax
    from duoforge_learn import checkpoint, policy
    cfg = policy.v2_config("S")
    names = list(features.feature_names(encoder))
    params = policy.make(cfg, names).init(jax.random.PRNGKey(seed))
    config = {"model": cfg, "encoder": encoder, "features": names, "slot_features": list(features.SLOT_FEATURE_NAMES),
              "data": {"kind": "pool", "fingerprint": ctx.fingerprint().hex()}, "teams": {}, "update": 0,
              "decisions": 0, "ids": checkpoint.ids_of(ctx)}
    checkpoint.save(path, params, {**config, **change})


def _checkpoints(root, ctx):
    """{name: path} of seven distinct checkpoints; BC is an older encoder-3 layout."""
    paths = {}
    for i, name in enumerate(NAMES):
        paths[name] = str(Path(root) / f"{name}.npz")
        _save(paths[name], ctx, seed=11 + i, encoder=3 if name == "BC" else 4)
    return paths


def _manifest(pool, paths):
    from duoforge_learn import p1_eval
    from duoforge_search import expert_eval as ev
    return ev.make_manifest(pool, seed=0x2026100900000001, first_game_id=5 * 10**6,
                            checkpoints={name: p1_eval.file_sha256(path) for name, path in paths.items()})


def _subset(rows, idx):
    return {k: v[idx] for k, v in rows.items()}


def _prefix(rows, pairs):
    """The schedule indices of pairs 0..pairs-1 of every block, arm and seat."""
    return np.flatnonzero(rows["pair"] < pairs)


def _group_key(rows, i):
    return tuple(str(rows[k][i]) for k in ("suite", "opponent", "arm", "bucket")) + (int(rows["student_seat"][i]),)


class _FakePlay:
    """play_suite without play: records every call, scores env e by (call, e), drives the observers' start."""

    def __init__(self, end=None):
        self.calls, self.end = [], end

    def __call__(self, context, pool, suite_rows, learner, opponent, workers, seed, max_steps=1000, luck=None,
                 observers=()):
        from duoforge_learn import evaluate
        assert luck is None
        n = suite_rows.shape[0]
        for o in observers:
            o.start(n, suite_rows["learner_seat"].astype(np.int64))
        self.calls.append({"learner": learner.name, "opponent": opponent.name, "seed": seed, "rows": suite_rows.copy(),
                           "max_steps": max_steps, "workers": workers})
        out = np.zeros(n, dtype=evaluate.RECORD)
        out["side0"], out["side1"], out["learner_seat"] = suite_rows["side0"], suite_rows["side1"], \
            suite_rows["learner_seat"]
        out["result"] = [(-1, 0, 1)[(len(self.calls) + e) % 3] for e in range(n)]
        if self.end is not None:
            self.end(out)
        return out


class _Fields:
    """A tracker stand-in: field k of env e is k + e."""

    def start(self, n, seats):
        self.n = n

    @property
    def fields(self):
        from duoforge_search.expert_eval import TR_FIELDS
        return {name: np.arange(self.n, dtype=np.int64) + k for k, name in enumerate(TR_FIELDS)}


class Schedule(unittest.TestCase):
    """The mapping from make_eval_rows to play_suite calls, over the whole schedule (no play)."""

    @classmethod
    def setUpClass(cls):
        from duoforge_search import expert_eval as ev
        from python.tests.test_expert_eval import HEXES
        cls.ev = ev
        cls.pool = _pool()
        cls.manifest = ev.make_manifest(cls.pool, seed=99, first_game_id=10**6, checkpoints=HEXES)
        cls.rows = ev.make_eval_rows(cls.pool, cls.manifest)

    def _run(self, rows, fake=None):
        from duoforge_learn import evaluate, p1_eval
        players = {name: evaluate.Player(None, None, 4, name) for name in NAMES}
        fake = fake or _FakePlay()
        with mock.patch.object(evaluate, "play_suite", fake):
            records, counts = p1_eval.play_rows(None, self.pool, rows, players, max_steps=77, tracker=_Fields())
        return records, counts, fake

    def test_one_call_per_block_arm_bucket_and_seat(self):
        from python.tests.test_expert_eval import arms
        ev, rows = self.ev, self.rows
        records, counts, fake = self._run(rows)
        self.assertEqual(len(fake.calls), sum(len(a) for _, _, a, _ in ev.SCHEDULE) * len(ev.BUCKETS) * 2)  # 40
        self.assertEqual(counts, {"cutoffs": 0, "refused": 0})
        from duoforge_learn import p1_eval
        groups = p1_eval.call_groups(rows)
        self.assertEqual(len(groups), len(fake.calls))
        np.testing.assert_array_equal(np.sort(np.concatenate(groups)), np.arange(rows["pair"].size))
        keys = [_group_key(rows, g[0]) for g in groups]
        self.assertEqual(len(set(keys)), len(keys))
        self.assertEqual([g[0] for g in groups], sorted(g[0] for g in groups))  # in game-id order
        for idx, key, call in zip(groups, keys, fake.calls):
            n = call["rows"].shape[0]
            self.assertTrue(all(_group_key(rows, i) == key for i in idx))
            self.assertEqual(n, idx.size)
            self.assertEqual((call["learner"], call["opponent"]), (key[2], key[1]))
            np.testing.assert_array_equal(rows["pair"][idx], np.arange(n))  # environment = pair, in pair order
            self.assertEqual(call["seed"], int(rows["seed"][idx[0]]))
            self.assertIsInstance(call["seed"], int)
            seat = key[4]
            np.testing.assert_array_equal(call["rows"]["learner_seat"], seat)
            mine, theirs = (call["rows"]["side0"], call["rows"]["side1"])[::1 if seat == 0 else -1]
            np.testing.assert_array_equal(mine, rows["student_team"][idx])
            np.testing.assert_array_equal(theirs, rows["opponent_team"][idx])
            self.assertEqual(call["max_steps"], 77)
            # The call's tracker fields land in its rows, env e on pair e.
            np.testing.assert_array_equal(records["tr_turns"][idx], np.arange(n) + ev.TR_FIELDS.index("tr_turns"))
        # Both arms and both seats of a block share its one seed (#307), so pair p plays one battle RNG throughout.
        for i in range(0, rows["pair"].size, 97):
            same = (rows["suite"] == rows["suite"][i]) & (rows["opponent"] == rows["opponent"][i]) &                 (rows["bucket"] == rows["bucket"][i])
            self.assertEqual(len(set(rows["seed"][same].tolist())), 1)
        self.assertTrue(records["finished"].all())
        for name in ev.SCHEDULE_FIELDS:
            np.testing.assert_array_equal(records[name], rows[name])
        data = json.loads(p1_eval.records_bytes(records))
        result = ev.evaluate_records(data, self.manifest, arms(ev))
        self.assertNotIn(ev.GateStatus.INCOMPLETE, [g["status"] for g in result.groups.values()])
        self.assertEqual(result.provenance["games"], rows["pair"].size)

    def test_cutoffs_and_refusals_are_unfinished_and_counted_apart(self):
        def end(out):
            out["unfinished"][0] = True  # a cut-off, resolved by the tiebreak
            out["unfinished"][1] = out["unresolved"][1] = True  # a cut-off the tiebreak cannot resolve
            out["unresolved"][2], out["result"][2] = True, -1  # the engine refused it
        records, counts, fake = self._run(_subset(self.rows, _prefix(self.rows, 3)), _FakePlay(end))
        calls = len(fake.calls)
        self.assertEqual(counts, {"cutoffs": 2 * calls, "refused": calls})
        self.assertEqual(int((~records["finished"]).sum()), 3 * calls)
        self.assertTrue(np.isnan(records["score"][~records["finished"]]).all())

    def test_a_subset_must_be_a_pair_prefix_of_its_call(self):
        from duoforge_learn import p1_eval
        rows = self.rows
        with self.assertRaisesRegex(ValueError, "pairs 0"):
            self._run(_subset(rows, np.flatnonzero(rows["pair"] == 1)))
        two = _subset(rows, _prefix(rows, 2))
        two["seed"] = two["seed"].copy()
        two["seed"][1::4] += np.uint64(1)
        with self.assertRaisesRegex(ValueError, "one seed"):
            self._run(two)
        self.assertGreater(len(p1_eval.call_groups(_subset(rows, _prefix(rows, 1)))), 0)

    def test_the_smoke_is_a_predeclared_stratified_selection(self):
        from duoforge_learn import p1_eval
        ev, rows = self.ev, self.rows
        idx = p1_eval.smoke_indices(rows)
        self.assertEqual(idx.size, p1_eval.SMOKE_GAMES)
        self.assertEqual(p1_eval.SMOKE_GAMES, 64)
        np.testing.assert_array_equal(idx, p1_eval.smoke_indices(rows))
        np.testing.assert_array_equal(idx, np.sort(idx))
        sub = _subset(rows, idx)
        # Every block, arm and bucket (so PP and LL, every opponent and both arms), both seats of every pair.
        units = {(str(s), str(o), str(a), str(b)) for s, o, a, b in zip(sub["suite"], sub["opponent"], sub["arm"],
                                                                         sub["bucket"])}
        self.assertEqual(units, {tuple(b.split("/")) for b in ev.BLOCKS})
        # Round robin: pair 0 of all 20 units, then pair 1 of the first 12 in schedule order.
        self.assertEqual(int((sub["pair"] == 0).sum()), 40)
        self.assertEqual(int((sub["pair"] == 1).sum()), 24)
        self.assertEqual(sorted({str(s) for s in sub["suite"][sub["pair"] == 1]}), ["h2h_continuation", "h2h_frozen",
                                                                                    "panel"])
        p1_eval.call_groups(sub)  # pair prefixes of every call
        records, _, _ = self._run(sub)
        ev._check_records(json.loads(p1_eval.records_bytes(records)), self.manifest)

    def test_the_smoke_report_and_its_stops(self):
        from duoforge_learn import p1_eval
        ok = {"cutoffs": 0, "refused": 0}
        go = p1_eval.smoke_report(64, ok, 30.0, jit_seconds=40.0, warm_games_per_second=20.0)
        self.assertEqual(go["status"], "GO")
        self.assertEqual(go["games"], 64)
        self.assertAlmostEqual(go["games_per_second"], 64 / 30.0)  # every smoke call, JIT included (reported only)
        self.assertEqual(go["warm_games_per_second"], 20.0)
        self.assertEqual(go["jit_seconds"], 40.0)
        self.assertAlmostEqual(go["forecast_seconds"], 40.0 + 12288 / 20.0)
        self.assertTrue(go["forecast_is_upper_bound"])
        self.assertTrue(go["jit_is_estimate"])  # extrapolated from the smoke's small shapes
        self.assertEqual(go["stop_reasons"], [])
        self.assertEqual((go["cutoffs"], go["refused"]), (0, 0))
        # Only the forecast rule fires: the warm rate is at the floor, JIT and games together exceed 60 minutes.
        only = p1_eval.smoke_report(64, ok, 12.8, jit_seconds=1300.0, warm_games_per_second=5.0)
        self.assertEqual(only["status"], "STOP")
        self.assertEqual(len(only["stop_reasons"]), 1)
        self.assertIn("forecast", only["stop_reasons"][0])
        # A large smoke JIT is no false STOP: the smoke took 60 s (about 1 game/s with its compiles), warm play
        # runs at 25 games/s and the full run's estimated JIT is 300 s.
        slow_start = p1_eval.smoke_report(64, ok, 60.0, jit_seconds=300.0, warm_games_per_second=25.0)
        self.assertEqual(slow_start["status"], "GO", slow_start["stop_reasons"])
        for counts, warm, reason in (({"cutoffs": 1, "refused": 0}, 20.0, "cut-off"),
                                     ({"cutoffs": 0, "refused": 2}, 20.0, "refused"),
                                     (ok, 4.9, "games/s"),
                                     (ok, None, "warm")):
            with self.subTest(reason=reason):
                stop = p1_eval.smoke_report(64, counts, 30.0, jit_seconds=40.0, warm_games_per_second=warm)
                self.assertEqual(stop["status"], "STOP")
                self.assertTrue(any(reason in r for r in stop["stop_reasons"]), stop["stop_reasons"])

    def test_the_smoke_clock_separates_jit_from_warm_play(self):
        """A mocked clock: a network's first pass at a row count costs 10 s (a compile), later ones 0.01 s; the
        engine 0.1 s per game. The JIT excess, the warm rate and the full run's JIT estimate follow exactly."""
        from duoforge_learn import evaluate, p1_eval
        now = [0.0]
        clock = p1_eval.SmokeClock(now=lambda: now[0])

        class Net:
            def __init__(self):
                self.seen = set()

            def act(self, params, key, obs, *rest, **kw):
                now[0] += 0.01 if obs.shape[0] in self.seen else 10.0
                self.seen.add(obs.shape[0])
                return np.zeros(obs.shape[0], np.int64)

        players = {name: evaluate.Player(clock.wrap(name, Net()), None, 4, name) for name in NAMES}

        def fake(context, pool_, suite_rows, learner, opponent, workers, seed, max_steps=1000, luck=None,
                 observers=()):
            n = suite_rows.shape[0]
            for o in observers:
                o.start(n, suite_rows["learner_seat"].astype(np.int64))
            for p in (learner, opponent):
                p.model.act(None, None, np.zeros((2 * n, 3)))
            now[0] += 0.1 * n
            return np.zeros(n, dtype=evaluate.RECORD)

        smoke = _subset(self.rows, p1_eval.smoke_indices(self.rows))
        with mock.patch.object(evaluate, "play_suite", fake):
            p1_eval.play_rows(None, self.pool, smoke, players, tracker=_Fields(), clock=clock)
        self.assertEqual(clock.compiles, len(clock.acts))
        excess = clock.jit_excess()
        self.assertEqual(set(excess), set(NAMES))
        for value in excess.values():
            self.assertAlmostEqual(value, 10.0 - 0.01)
        warm = [c for c in clock.calls if not c[2]]
        self.assertGreater(len(warm), 0)
        self.assertTrue(clock.calls[0][2])  # the first call compiles
        games, seconds = sum(c[0] for c in warm), sum(c[1] for c in warm)
        self.assertAlmostEqual(clock.warm_rate(), games / seconds)
        self.assertAlmostEqual(seconds, sum(0.02 + 0.1 * c[0] for c in warm))
        shapes = p1_eval.full_shapes(self.rows)
        self.assertEqual(shapes, {"pilot": {1024, 512}, "control": {1024, 512}, "frozen": {1024},
                                  "BC": {512}, "3600": {512}, "11000": {512}, "ladder": {512}})
        self.assertAlmostEqual(clock.jit_estimate(shapes), (10.0 - 0.01) * 9)
        with self.assertRaisesRegex(ValueError, "no smoke measurement"):  # never a silent 0 for an unmeasured player
            clock.jit_estimate({**shapes, "stranger": {512}})

    def test_a_pair_shares_its_seed_and_teams_across_seats_and_arms(self):
        rows = _subset(self.rows, _prefix(self.rows, 2))
        for name in ("opponent_team", "student_team"):
            with self.subTest(field=name):
                bad = {k: v.copy() for k, v in rows.items()}
                seat1 = np.flatnonzero(bad["student_seat"] == 1)[0]
                bad[name][seat1] = (bad[name][seat1] + 1) % 6
                with self.assertRaisesRegex(ValueError, "share"):
                    self._run(bad)
        bad = {k: v.copy() for k, v in rows.items()}
        control = np.flatnonzero((bad["arm"] == "control") & (bad["pair"] == 0))
        bad["opponent_team"][control] = (bad["opponent_team"][control] + 1) % 6  # both seats: the arms differ
        with self.assertRaisesRegex(ValueError, "share"):
            self._run(bad)

class Play(unittest.TestCase):
    """Real games of the first two pairs of every call between untrained networks."""

    @classmethod
    def setUpClass(cls):
        from duoforge_learn import p1_eval
        from duoforge_search import expert_eval as ev
        cls.p1, cls.ev = p1_eval, ev
        cls.tmp = tempfile.TemporaryDirectory(prefix="duoforge-p1-eval-")
        cls.ctx = duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"])
        cls.pool = _pool()
        cls.paths = _checkpoints(cls.tmp.name, cls.ctx)
        cls.manifest = _manifest(cls.pool, cls.paths)
        rows = ev.make_eval_rows(cls.pool, cls.manifest)
        cls.rows = _subset(rows, _prefix(rows, 2))
        cls.players = p1_eval.make_players(p1_eval.load_checkpoints(cls.paths, cls.manifest), cls.ctx)
        cls.records, cls.counts = cls._play()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()
        cls.tmp.cleanup()

    @classmethod
    def _play(cls, rows=None):
        return cls.p1.play_rows(cls.ctx, cls.pool, cls.rows if rows is None else rows, cls.players, max_steps=STEPS)

    def test_records_pass_expert_eval_and_hold_the_trick_room_fields(self):
        r, ev = self.records, self.ev
        data = json.loads(self.p1.records_bytes(r))
        self.assertEqual(sorted(data), sorted(ev.RECORD_FIELDS))
        checked = ev._check_records(data, self.manifest)
        self.assertEqual(checked["game_id"].size, 80)
        for name in ev.TR_FIELDS:
            self.assertEqual(r[name].dtype, np.int64)
            self.assertTrue((r[name] >= 0).all())
            self.assertTrue(all(type(v) is int for v in data[name]))
        self.assertGreater(int(r["tr_setter_student"].sum() + r["tr_setter_opponent"].sum()), 0)
        done = r["finished"]
        self.assertTrue(np.isin(r["score"][done], (0.0, 0.5, 1.0)).all())
        self.assertTrue(np.isnan(r["score"][~done]).all())
        self.assertEqual([v is None for v in data["score"]], (~done).tolist())
        self.assertGreater(int(done.sum()), 0)  # some games end inside the short cut-off
        self.assertEqual(self.counts["cutoffs"] + self.counts["refused"], int((~done).sum()))
        ev.trick_room_report(data)  # the diagnostic reads them

    def test_the_same_inputs_give_the_same_bytes(self):
        again, counts = self._play()
        self.assertEqual(self.p1.records_bytes(again), self.p1.records_bytes(self.records))
        self.assertEqual(counts, self.counts)

    def test_a_refused_game_is_unfinished(self):
        from python.tests.test_learn_v2_numpy import _fail_env_once
        with mock.patch.object(duoforge.Batch, "step", _fail_env_once(duoforge.Batch.step, 1)):
            r, counts = self._play()
        # The first call's env 1 (pair 1 of the first block) was refused.
        first = np.flatnonzero(r["pair"] == 1)[0]
        self.assertFalse(r["finished"][first])
        self.assertTrue(math.isnan(r["score"][first]))
        self.assertEqual(counts["refused"], self.counts["refused"] + 1)
        others = np.arange(r["pair"].size) != first
        for name in self.ev.RECORD_FIELDS:  # every other game as before
            np.testing.assert_array_equal(r[name][others], self.records[name][others])
        self.ev._check_records(json.loads(self.p1.records_bytes(r)), self.manifest)

    def test_players_read_their_own_layout(self):
        self.assertEqual({n: p.encoder for n, p in self.players.items()}, {**{n: 4 for n in NAMES}, "BC": 3})
        self.assertTrue((self.rows["opponent"] == "BC").any())  # the encoder-3 network played its rows

    def _refused(self, pattern, change_paths=None, **save):
        paths = dict(self.paths)
        if save:
            paths["BC"] = str(Path(self.tmp.name) / f"bad-{len(os.listdir(self.tmp.name))}.npz")
            _save(paths["BC"], self.ctx, seed=3, **save)
        paths.update(change_paths or {})
        with self.assertRaisesRegex(ValueError, pattern):
            loaded = self.p1.load_checkpoints(paths, _manifest(self.pool, paths))
            self.p1.make_players(loaded, self.ctx) if self.p1.data_kind(loaded) else None

    def test_checkpoints_that_cannot_be_served_are_refused(self):
        old = Path(self.tmp.name) / "format1.npz"
        np.savez(old, config=json.dumps({"encoder": 1}), **{"['t1']['w']": np.zeros((2, 2), np.float32)})
        self._refused("BC: .*format-2", {"BC": str(old)})
        self._refused("BC: .*not encoder 4's layout", features=list(features.feature_names(3)))  # layout mismatch
        self._refused("one data kind", data={"kind": "closure", "fingerprint": "00"})
        self._refused("one data kind", data={})
        # Another fingerprint and ids that moved: refused by name.
        from duoforge_learn import checkpoint
        ids = checkpoint.ids_of(self.ctx)
        moved = {**ids, "move": list(reversed(ids["move"]))}
        self._refused("checkpoint BC: move id 0", data={"kind": "pool", "fingerprint": "00"}, ids=moved)
        self._refused("checkpoint BC: .*no id tables", data={"kind": "pool", "fingerprint": "00"}, ids=None)
        broken = Path(self.tmp.name) / "broken.npz"
        broken.write_bytes(b"PK\x03\x04" + b"\x00" * 64)  # a zip header and nothing behind it
        self._refused("checkpoint BC: .*zip", {"BC": str(broken)})
        # A compressed member whose deflate stream is damaged (zlib.error while reading it): a refusal too.
        import struct
        from duoforge_learn import checkpoint
        params, config = checkpoint.load_trained(self.paths["BC"])
        damaged = Path(self.tmp.name) / "damaged.npz"
        np.savez_compressed(damaged, config=json.dumps(config), **checkpoint.flatten(params))
        data = bytearray(damaged.read_bytes())
        name_len, extra_len = struct.unpack("<HH", data[26:30])  # the first member's local header
        start = 30 + name_len + extra_len
        data[start:start + 16] = b"\xff" * 16  # BTYPE 11: an invalid deflate block
        damaged.write_bytes(bytes(data))
        self._refused("checkpoint BC: .*(invalid|Error -3)", {"BC": str(damaged)})

    def test_a_checkpoint_the_manifest_does_not_pin_is_refused(self):
        paths = dict(self.paths, pilot=self.paths["control"])
        with self.assertRaisesRegex(ValueError, "checkpoint pilot: .* SHA-256"):
            self.p1.load_checkpoints(paths, self.manifest)
        with self.assertRaisesRegex(ValueError, "name exactly"):
            self.p1.load_checkpoints({k: v for k, v in self.paths.items() if k != "ladder"}, self.manifest)

    def test_the_hashed_bytes_are_the_loaded_bytes(self):
        """Each file is read once: load_trained gets the very bytes whose SHA-256 the manifest pins."""
        import hashlib
        from duoforge_learn import checkpoint
        real, given = checkpoint.load_trained, []

        def spy(source):
            self.assertNotIsInstance(source, (str, os.PathLike))
            data = source.getvalue()
            given.append(hashlib.sha256(data).hexdigest())
            return real(io.BytesIO(data))
        with mock.patch.object(checkpoint, "load_trained", spy):
            self.p1.load_checkpoints(self.paths, self.manifest)
        self.assertEqual(given, [self.manifest.checkpoints[n] for n in NAMES])


class Cli(unittest.TestCase):
    """python -m duoforge_learn.p1_eval (the whole schedule, and the smoke) into python -m duoforge_search.expert_eval,
    registry teams."""

    @classmethod
    def setUpClass(cls):
        from duoforge_search import expert_eval as ev
        cls.ev = ev
        cls.tmp = tempfile.TemporaryDirectory(prefix="duoforge-p1-eval-cli-")
        cls.dir = Path(cls.tmp.name)
        with open(REPO / "data" / "teams" / "index.json", encoding="utf-8") as f:
            ll = sorted(t["id"] for t in json.load(f)["teams"] if t["id"].startswith("LL_"))[:2]
        cls.teams = ["A", "B", "C", *ll]
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            cls.paths = _checkpoints(cls.dir, ctx)
            pool = teams.load(ctx, cls.teams, root=str(REPO / "data" / "teams"))
        manifest = _manifest(pool, cls.paths)
        cls.rows = ev.make_eval_rows(pool, manifest)
        cls.manifest = cls.dir / "manifest.json"
        cls.manifest.write_text(json.dumps(ev.manifest_mapping(manifest)))
        for arm in ("pilot", "control"):
            (cls.dir / f"{arm}-ledger.json").write_text(json.dumps(
                {"schema": 1, "cpu_core_seconds": 100.0, "gpu_seconds": 10.0, "processes": 1,
                 "phases": {"distill": {"cpu_core_seconds": 100.0, "gpu_seconds": 10.0}}}))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _main(self, out, *extra, checkpoints=None):
        from duoforge_learn import p1_eval
        argv = ["--manifest", str(self.manifest), "--teams", ",".join(self.teams),
                "--teams-root", str(REPO / "data" / "teams"), "--out", str(out), "--workers", "4", *extra]
        for name, path in (checkpoints or self.paths).items():
            argv += ["--checkpoint", f"{name}={path}"]
        err, std = io.StringIO(), io.StringIO()
        with mock.patch.object(p1_eval, "MAX_STEPS", STEPS), contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(std):
            code = p1_eval.main(argv)
        return code, err.getvalue(), std.getvalue()

    def test_cli_end_to_end(self):
        """The whole schedule (12288 games, cut at STEPS), its records into expert_eval main; no ledger file."""
        out = self.dir / "baseline.json"
        code, err, std = self._main(out)
        self.assertEqual(code, 0, err)
        summary = json.loads(std)
        self.assertEqual(summary["games"], 12288)
        self.assertEqual(summary["encoders"]["BC"], 3)
        self.assertEqual(summary["cutoffs"] + summary["refused"], summary["games"] - summary["finished"])
        baseline = json.loads(out.read_text())
        self.assertEqual(sorted(baseline), ["ledger", "records"])
        self.assertEqual(len(baseline["records"]["game_id"]), 12288)
        self.assertEqual(baseline["ledger"]["processes"], 1)  # no --ledger: this process, in memory
        self.assertEqual(baseline["ledger"]["gpu_seconds"], 0.0)  # CPU JAX: no device sections
        self.assertGreater(baseline["ledger"]["phases"]["evaluate"]["cpu_core_seconds"], 0.0)
        report = self.dir / "report.json"
        args = ["--manifest", str(self.manifest), "--pilot", str(self.dir / "pilot-ledger.json"),
                "--control", str(self.dir / "control-ledger.json"), "--baseline", str(out), "--out", str(report)]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(self.ev.main(args), 0, err.getvalue())
        result = json.loads(report.read_text())
        self.assertEqual(result["provenance"]["games"], 12288)
        self.assertIn(result["status"], ("PASS", "FAIL", "INCONCLUSIVE", "INCOMPLETE"))
        self.assertIn("trick_room", result)

    def test_cli_smoke(self):
        from duoforge_learn import p1_eval
        out, ledger = self.dir / "smoke.json", self.dir / "smoke-ledger.json"
        played, real = [], p1_eval.play_rows

        def spy(context, pool, rows, players, **kw):
            played.append(np.asarray(rows["game_id"]).copy())
            self.assertIsNotNone(kw.get("clock"))
            return real(context, pool, rows, players, **kw)
        with mock.patch.object(p1_eval, "play_rows", spy):
            code, err, _ = self._main(out, "--smoke", "--ledger", str(ledger))
        self.assertEqual(code, 0, err)
        self.assertEqual(len(played), 1)  # the predeclared selection, nothing else
        np.testing.assert_array_equal(played[0], self.rows["game_id"][p1_eval.smoke_indices(self.rows)])
        report = json.loads(out.read_text())
        self.assertGreater(report["jit_seconds"], 0.0)
        self.assertGreater(report["warm_games_per_second"], 0.0)
        self.assertTrue(report["forecast_is_upper_bound"])
        for key in ("games", "seconds", "games_per_second", "forecast_seconds", "cutoffs", "refused", "status",
                    "stop_reasons", "ledger"):
            self.assertIn(key, report)
        self.assertEqual(report["games"], 64)
        self.assertEqual(report["status"], "STOP" if report["stop_reasons"] else "GO")
        self.assertEqual(report["ledger"], json.loads(ledger.read_text()))  # charged to the evaluation ledger
        self.assertGreater(report["ledger"]["phases"]["evaluate"]["cpu_core_seconds"], 0.0)
        # The same smoke again: the ledger sums both processes.
        code, err, _ = self._main(self.dir / "smoke-again.json", "--smoke", "--ledger", str(ledger))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(ledger.read_text())["processes"], 2)

    def test_cli_refusals_exit_2(self):
        dup = [*sum((["--checkpoint", f"{n}={p}"] for n, p in self.paths.items()), []),
               "--checkpoint", f"pilot={self.paths['pilot']}"]
        cases = {
            "checkpoint pilot": dict(checkpoints=dict(self.paths, pilot=self.paths["control"])),
            "inside the repository": dict(out=REPO / "p1-eval-out.json"),
            "exists": dict(out=self.manifest),
            "--workers": dict(extra=["--workers", "0"]),
            "named twice": dict(extra=dup[-2:]),
        }
        for cause, change in cases.items():
            with self.subTest(cause=cause):
                out = change.pop("out", self.dir / "refused.json")
                code, err, _ = self._main(out, *change.pop("extra", []), **change)
                self.assertEqual(code, 2)
                self.assertIn(cause, err)
                self.assertFalse((self.dir / "refused.json").exists())
        self.assertFalse((REPO / "p1-eval-out.json").exists())

    def test_a_refusal_after_the_ledger_exists_is_charged(self):
        ledger = self.dir / "refused-ledger.json"
        code, err, _ = self._main(self.dir / "refused.json", "--ledger", str(ledger),
                                  checkpoints=dict(self.paths, pilot=self.paths["control"]))
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(ledger.read_text())["processes"], 1)
        self.assertFalse((self.dir / "refused.json").exists())

    def test_a_gpu_without_deterministic_ops_is_refused(self):
        import jax
        ledger = self.dir / "gpu-ledger.json"
        env = {k: v for k, v in os.environ.items() if k != "XLA_FLAGS"}
        from duoforge_learn import evaluate

        def never(*args, **kwargs):
            raise AssertionError("refused before play: play_suite must not run")
        with mock.patch.object(jax, "default_backend", return_value="gpu"), \
                mock.patch.dict(os.environ, env, clear=True), mock.patch.object(evaluate, "play_suite", never):
            code, err, _ = self._main(self.dir / "refused.json", "--ledger", str(ledger))
        self.assertEqual(code, 2)
        self.assertIn("xla_gpu_deterministic_ops", err)
        self.assertTrue(ledger.exists())
        self.assertFalse((self.dir / "refused.json").exists())


if __name__ == "__main__":
    unittest.main()
