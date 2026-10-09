"""duoforge.python.p1_eval: the stage 3 P1 evaluation games (duoforge_learn.p1_eval, plan C5's runner).

- The schedule mapping, all 12288 rows without play (play_suite replaced): every row is one play_suite game seeded
  with its own seed, the row's arm against the row's opponent checkpoint, the student's team on its seat; the
  records pass expert_eval's checks and complete every gate group.
- Real games on a subset (untrained v2-S networks in temporary directories, CPU, a short cut-off): the records pass
  expert_eval._check_records, the Trick Room fields are integers, a refused game is unfinished with a null score
  and leaves the other games unchanged, the same inputs give the same record bytes, an older format-2 layout plays
  in its own encoder and a format-1 file is refused.
- The CLI end to end into expert_eval's main, its ledger, and its refusals (a checkpoint hash, an output inside the
  repository or existing, an odd --games).

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


def _save(path, ctx, seed, encoder=4):
    """A format-2 checkpoint of an untrained v2-S network of encoder `encoder`'s layout, data of ctx."""
    import jax
    from duoforge_learn import checkpoint, policy
    cfg = policy.v2_config("S")
    names = list(features.feature_names(encoder))
    params = policy.make(cfg, names).init(jax.random.PRNGKey(seed))
    checkpoint.save(path, params, {"model": cfg, "encoder": encoder, "features": names,
                                   "slot_features": list(features.SLOT_FEATURE_NAMES),
                                   "data": {"kind": "pool", "fingerprint": ctx.fingerprint().hex()}, "teams": {},
                                   "update": 0, "decisions": 0, "ids": checkpoint.ids_of(ctx)})


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


def _pairs(rows, blocks):
    """The schedule indices of pair 0 of each (suite, opponent, arm, bucket) block, both seats."""
    out = []
    for suite, opponent, arm, bucket in blocks:
        hit = np.flatnonzero((rows["suite"] == suite) & (rows["opponent"] == opponent) & (rows["arm"] == arm)
                             & (rows["bucket"] == bucket) & (rows["pair"] == 0))
        assert hit.size == 2
        out.extend(hit.tolist())
    return np.array(sorted(out))


def _subset(rows, idx):
    return {k: v[idx] for k, v in rows.items()}


class Schedule(unittest.TestCase):
    """The mapping from make_eval_rows to play_suite games, over the whole schedule (no play)."""

    def test_every_row_is_its_own_seeded_game(self):
        from duoforge_learn import evaluate, p1_eval
        from duoforge_search import expert_eval as ev
        from python.tests.test_expert_eval import HEXES, arms
        pool = _pool()
        manifest = ev.make_manifest(pool, seed=99, first_game_id=10**6, checkpoints=HEXES)
        rows = ev.make_eval_rows(pool, manifest)
        players = {name: evaluate.Player(None, None, 4, name) for name in NAMES}
        calls = []

        def fake(context, pool_, suite_rows, learner, opponent, workers, seed, max_steps=1000, luck=None,
                 observers=()):
            self.assertEqual(suite_rows.shape, (1,))
            self.assertIsNone(luck)
            for o in observers:
                o.start(1, suite_rows["learner_seat"].astype(np.int64))
            calls.append((learner.name, opponent.name, seed, int(suite_rows["side0"][0]),
                          int(suite_rows["side1"][0]), int(suite_rows["learner_seat"][0]), max_steps))
            out = np.zeros(1, dtype=evaluate.RECORD)
            out["result"] = (-1, 0, 1)[len(calls) % 3]
            return out

        class Fields:
            def start(self, n, seats):
                self.n = n

            @property
            def fields(self):
                return {name: np.full(self.n, k, np.int64) for k, name in enumerate(ev.TR_FIELDS)}

        with mock.patch.object(evaluate, "play_suite", fake):
            records = p1_eval.play_rows(None, pool, rows, players, max_steps=77, tracker=Fields())
        n = rows["game_id"].size
        self.assertEqual(len(calls), n)
        for i, (learner, opponent, seed, side0, side1, seat, steps) in enumerate(calls):
            self.assertEqual(learner, rows["arm"][i])
            self.assertEqual(opponent, rows["opponent"][i])
            self.assertEqual(seed, int(rows["seed"][i]))
            self.assertIsInstance(seed, int)
            self.assertEqual(seat, rows["student_seat"][i])
            mine, theirs = (side0, side1) if seat == 0 else (side1, side0)
            self.assertEqual((mine, theirs), (rows["student_team"][i], rows["opponent_team"][i]))
            self.assertEqual(steps, 77)
        # Both seats of a pair: the same seed, the teams swapped.
        self.assertEqual(calls[0][2], calls[1][2])
        self.assertEqual(calls[0][3:5], calls[1][3:5][::-1])
        np.testing.assert_array_equal(records["score"], [(0.0, 0.5, 1.0)[(i + 1) % 3] for i in range(n)])
        self.assertTrue(records["finished"].all())
        for k, name in enumerate(ev.TR_FIELDS):
            np.testing.assert_array_equal(records[name], k)
        for name in ev.SCHEDULE_FIELDS:
            np.testing.assert_array_equal(records[name], rows[name])
        # The JSON records are what expert_eval reads: every block complete, every group decided.
        data = json.loads(p1_eval.records_bytes(records))
        self.assertEqual(sorted(data), sorted(ev.RECORD_FIELDS))
        result = ev.evaluate_records(data, manifest, arms(ev))
        self.assertNotIn(ev.GateStatus.INCOMPLETE, [g["status"] for g in result.groups.values()])
        self.assertEqual(result.provenance["games"], n)


class Play(unittest.TestCase):
    """Real games of a few schedule pairs between untrained networks."""

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
        cls.rows = _subset(rows, _pairs(rows, [("h2h_continuation", "control", "pilot", "PP"),
                                               ("h2h_frozen", "frozen", "pilot", "LL"),
                                               ("panel", "BC", "control", "PP"),
                                               ("ladder", "ladder", "pilot", "LL")]))
        cls.players = p1_eval.make_players(p1_eval.load_checkpoints(cls.paths, cls.manifest), cls.ctx)
        cls.records = cls._play()

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
        self.assertEqual(checked["game_id"].size, 8)
        for name in ev.TR_FIELDS:
            self.assertEqual(r[name].dtype, np.int64)
            self.assertTrue((r[name] >= 0).all())
            self.assertTrue(all(type(v) is int for v in data[name]))
        done = r["finished"]
        self.assertTrue(np.isin(r["score"][done], (0.0, 0.5, 1.0)).all())
        self.assertTrue(np.isnan(r["score"][~done]).all())
        self.assertEqual([v is None for v in data["score"]], (~done).tolist())
        self.assertGreater(int(done.sum()), 0)  # some games end inside the short cut-off
        ev.trick_room_report(data)  # the diagnostic reads them

    def test_the_same_inputs_give_the_same_bytes(self):
        self.assertEqual(self.p1.records_bytes(self._play()), self.p1.records_bytes(self.records))
        # A game depends on its row alone: played alone, in another order, it is the same game.
        for i in (5, 2):
            alone = self._play(_subset(self.rows, [i]))
            for name in self.ev.RECORD_FIELDS:
                np.testing.assert_array_equal(alone[name], self.records[name][[i]])

    def test_a_refused_game_is_unfinished(self):
        from python.tests.test_learn_v2_numpy import _fail_env_once
        with mock.patch.object(duoforge.Batch, "step", _fail_env_once(duoforge.Batch.step, 0)):
            r = self._play()
        self.assertFalse(r["finished"][0])
        self.assertTrue(math.isnan(r["score"][0]))
        for name in self.ev.RECORD_FIELDS:  # every other game as before
            np.testing.assert_array_equal(r[name][1:], self.records[name][1:])
        self.ev._check_records(json.loads(self.p1.records_bytes(r)), self.manifest)

    def test_players_read_their_own_layout(self):
        self.assertEqual({n: p.encoder for n, p in self.players.items()}, {**{n: 4 for n in NAMES}, "BC": 3})
        bc = self.rows["opponent"] == "BC"
        self.assertTrue(bc.any())  # the encoder-3 network played its rows
        old = Path(self.tmp.name) / "format1.npz"
        np.savez(old, config=json.dumps({"encoder": 1}), **{"['t1']['w']": np.zeros((2, 2), np.float32)})
        paths = dict(self.paths, BC=str(old))
        manifest = _manifest(self.pool, paths)
        with self.assertRaisesRegex(ValueError, "format-2"):
            self.p1.load_checkpoints(paths, manifest)

    def test_a_checkpoint_the_manifest_does_not_pin_is_refused(self):
        paths = dict(self.paths, pilot=self.paths["control"])
        with self.assertRaisesRegex(ValueError, "checkpoint pilot: .* SHA-256"):
            self.p1.load_checkpoints(paths, self.manifest)
        with self.assertRaisesRegex(ValueError, "name exactly"):
            self.p1.load_checkpoints({k: v for k, v in self.paths.items() if k != "ladder"}, self.manifest)


class Cli(unittest.TestCase):
    """python -m duoforge_learn.p1_eval into python -m duoforge_search.expert_eval, registry teams."""

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
        cls.manifest = cls.dir / "manifest.json"
        cls.manifest.write_text(json.dumps(ev.manifest_mapping(_manifest(pool, cls.paths))))
        for arm in ("pilot", "control"):
            (cls.dir / f"{arm}-ledger.json").write_text(json.dumps(
                {"schema": 1, "cpu_core_seconds": 100.0, "gpu_seconds": 10.0, "processes": 1,
                 "phases": {"distill": {"cpu_core_seconds": 100.0, "gpu_seconds": 10.0}}}))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _main(self, out, *extra, checkpoints=None, games=4):
        from duoforge_learn import p1_eval
        argv = ["--manifest", str(self.manifest), "--teams", ",".join(self.teams),
                "--teams-root", str(REPO / "data" / "teams"), "--out", str(out), *extra]
        if games is not None:
            argv += ["--games", str(games)]
        for name, path in (checkpoints or self.paths).items():
            argv += ["--checkpoint", f"{name}={path}"]
        err, std = io.StringIO(), io.StringIO()
        with mock.patch.object(p1_eval, "MAX_STEPS", STEPS), contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(std):
            code = p1_eval.main(argv)
        return code, err.getvalue(), std.getvalue()

    def test_cli_end_to_end(self):
        out, ledger = self.dir / "baseline.json", self.dir / "eval-ledger.json"
        code, err, std = self._main(out, "--ledger", str(ledger))
        self.assertEqual(code, 0, err)
        summary = json.loads(std)
        self.assertEqual(summary["games"], 4)
        self.assertEqual(summary["encoders"]["BC"], 3)
        baseline = json.loads(out.read_text())
        self.assertEqual(sorted(baseline), ["ledger", "records"])
        self.assertEqual(len(baseline["records"]["game_id"]), 4)
        self.assertEqual(baseline["ledger"], json.loads(ledger.read_text()))
        self.assertEqual(baseline["ledger"]["gpu_seconds"], 0.0)  # CPU JAX: no device sections
        self.assertGreater(baseline["ledger"]["phases"]["evaluate"]["cpu_core_seconds"], 0.0)
        report = self.dir / "report.json"
        args = ["--manifest", str(self.manifest), "--pilot", str(self.dir / "pilot-ledger.json"),
                "--control", str(self.dir / "control-ledger.json"), "--baseline", str(out), "--out", str(report)]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(self.ev.main(args), 0, err.getvalue())
        result = json.loads(report.read_text())
        self.assertEqual(result["status"], "INCOMPLETE")  # four games of 12288
        self.assertEqual(result["provenance"]["games"], 4)
        self.assertIn("trick_room", result)
        # The same inputs again: the same record bytes; the ledger file sums both processes.
        again = self.dir / "baseline-again.json"
        code, err, _ = self._main(again, "--ledger", str(ledger))
        self.assertEqual(code, 0, err)
        second = json.loads(again.read_text())
        self.assertEqual(json.dumps(second["records"], sort_keys=True), json.dumps(baseline["records"], sort_keys=True))
        self.assertEqual(second["ledger"]["processes"], 2)

    def test_cli_refusals_exit_2(self):
        cases = {
            "checkpoint pilot": dict(checkpoints=dict(self.paths, pilot=self.paths["control"])),
            "inside the repository": dict(out=REPO / "p1-eval-out.json"),
            "--games": dict(games=3),
            "exists": dict(out=self.manifest),
        }
        for cause, change in cases.items():
            with self.subTest(cause=cause):
                out = change.pop("out", self.dir / "refused.json")
                code, err, _ = self._main(out, **change)
                self.assertEqual(code, 2)
                self.assertIn(cause, err)
                self.assertFalse((self.dir / "refused.json").exists())
        self.assertFalse((REPO / "p1-eval-out.json").exists())


if __name__ == "__main__":
    unittest.main()
