"""Stage 3 P1 distillation, Learner v2 side (plan 2026-10-08-stage3-p1-learner). Synthetic shards only, written
to temporary directories through M12's expert_data."""
import dataclasses
import tempfile
import unittest
from pathlib import Path

import numpy as np

from duoforge import features


def _manifest(ed):
    return ed.DataManifest(source_commit="a" * 40, checkpoint_hash="b" * 64, model_hash="c" * 64, encoder=4,
                           ids_hash="d" * 64, pool_hash="e" * 64, belief_hash="f" * 64, seed=7, split_seed=9,
                           key_version=1, device="cpu", runtime="synthetic", compiler="synthetic", capacity=1024,
                           workers=4, parallel_games=512, game_count=1024, rounds=2, first_game_id=0,
                           obs_width=features.obs_size(4), slot_width=features.SLOT_FEATURES,
                           teacher_config={"k": 8, "m": 8, "worlds": 16, "lam": .5}, budget={"labels": 16384},
                           evaluation={"synthetic": True})


class _Rows:
    """Builds valid ExpertRows of one game and seat, tick by tick."""

    def __init__(self, ed, m, game, seat=0):
        self.ed, self.m, self.game, self.seat, self.tick, self.epoch = ed, m, game, seat, 0, 0

    def _base(self, **kw):
        ed, m = self.ed, self.m
        row = dict(key=ed.DecisionKey(self.game, self.seat, self.epoch), logical_tick=self.tick, boundary="TURN",
                   obs=np.zeros(m.obs_width, np.float32), slots=np.zeros((2, 32, m.slot_width), np.float32),
                   legal_mask=None, sparse_policy=None, status=ed.RowStatus.UNREQUESTED, raw_action=None,
                   action=None, behavior_logp=None, requested=False, acting=False, learner=True, value_mask=True,
                   admitted=False, reward=0., done=False, collector_value=0., bootstrap=0., cause=None, work={},
                   audit={})
        row.update(kw)
        if row["legal_mask"] is None:
            mask = np.zeros((32, 32), bool)
            mask.flat[[0, 1, 33]] = True
            row["legal_mask"] = mask
        self.tick += 1
        return ed.ExpertRow(**row)

    def wait(self, value, **kw):
        return self._base(collector_value=value, **kw)

    def act(self, status, value, **kw):
        self.epoch += 1
        ed = self.ed
        kw = dict(status=status, requested=True, acting=True, raw_action=1, action=1,
                  behavior_logp=float(np.log(.5)), collector_value=value, key=ed.DecisionKey(self.game, self.seat,
                                                                                              self.epoch)) | kw
        if status is ed.RowStatus.TARGET:
            kw |= dict(admitted=True, sparse_policy=ed.SparsePolicy(np.array([1, 33], np.int64),
                                                                     np.array([.5, .5], np.float64)))
        if status is ed.RowStatus.FORCED:
            mask = np.zeros((32, 32), bool)
            mask.flat[1] = True
            kw |= dict(legal_mask=mask, behavior_logp=0.)
        return self._base(**kw)

    def team(self, value):
        self.epoch += 1
        ed = self.ed
        mask = np.ones(360, bool)
        return self._base(boundary="TEAM_SELECTION", legal_mask=mask, status=ed.RowStatus.UNSELECTED,
                          requested=True, acting=True, raw_action=5, action=5, behavior_logp=float(np.log(1 / 360)),
                          collector_value=value, key=ed.DecisionKey(self.game, self.seat, self.epoch))


def _games(ed, split_seed, train, held):
    """train game ids and held game ids under split_seed."""
    tr, he = [], []
    for g in range(1024):
        (he if ed.is_held_out(g, split_seed) else tr).append(g)
    return tr[:train], he[:held]


class DataTest(unittest.TestCase):
    def setUp(self):
        from duoforge_search import expert_data as ed
        self.ed = ed
        self.m = _manifest(ed)
        self.tmp = tempfile.TemporaryDirectory(prefix="duoforge_synthetic_distill_")
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name, rows):
        (self.dir / name).unlink(missing_ok=True)  # write_shard never overwrites
        self.ed.write_shard(self.dir / name, rows, self.m)

    def test_strata_split_and_value_targets(self):
        from duoforge_learn import distill_data
        ed, m = self.ed, self.m
        (a, b, c), (d,) = _games(ed, m.split_seed, 3, 1)
        S = ed.RowStatus
        ga = _Rows(ed, m, a)  # target, wait, unselected end with +1
        a_rows = [ga.act(S.TARGET, .5), ga.wait(.4), ga.act(S.UNSELECTED, .2, reward=1., done=True)]
        gb = _Rows(ed, m, b, seat=1)  # truncated: the stored bootstrap on its last row
        b_rows = [gb.act(S.UNSELECTED, .3, bootstrap=.9), gb.act(S.UNSELECTED, .6, bootstrap=.37)]
        gc = _Rows(ed, m, c)  # the learner never acts; the game ends -1
        c_rows = [gc.wait(.1), gc.wait(.2, reward=-1., done=True)]
        gd = _Rows(ed, m, d)  # held out: preview, target, forced
        d_rows = [gd.team(.0), gd.act(S.TARGET, .5), gd.act(S.FORCED, .5, reward=1., done=True)]
        # Game a spans two shards; the files are read in name order.
        self._write("0.json", [a_rows[0], *b_rows])
        self._write("1.json", [*a_rows[1:], *c_rows, *d_rows])
        data = distill_data.load(self.dir, m)
        self.assertEqual(len(data.game_id), 10)
        idx = distill_data.strata(data)
        sets = {k: set(v.tolist()) for k, v in idx.items()}
        names = list(sets)
        for i, x in enumerate(names):
            for y in names[i + 1:]:
                self.assertFalse(sets[x] & sets[y], (x, y))
        held = set(np.flatnonzero(data.game_id == d).tolist())
        self.assertTrue(held and held <= sets["held_target"] | sets["held_non"])
        self.assertFalse(held & (sets["train_target"] | sets["train_non"]))
        self.assertTrue(data.held_out[list(held)].all() and not data.held_out[data.game_id != d].any())

        def rows_of(g):
            return np.flatnonzero(data.game_id == g)

        # Hand-computed GAE (gamma 0.99, lambda 0.95): a waiting row takes its seat's next decision's return.
        np.testing.assert_allclose(data.value_target[rows_of(a)], [0.9504, 1.0, 1.0], atol=1e-5)
        np.testing.assert_allclose(data.value_target[rows_of(b)], [0.37421, 0.3663], atol=1e-4)
        np.testing.assert_allclose(data.value_target[rows_of(c)], [-1.0, -1.0], atol=1e-6)
        self.assertTrue(data.value_row[rows_of(c)].all() and not data.policy_row[rows_of(c)].any())
        # Strata: targets, policy rows (acting, >= 2 legal, no target), value-only rows (waiting, forced).
        ra, rd = rows_of(a), rows_of(d)
        self.assertEqual(data.has_target[ra].tolist(), [True, False, False])
        self.assertEqual(data.policy_row[ra].tolist(), [False, False, True])
        self.assertEqual(data.target_ids[ra[0]].tolist(), [1, 33, -1, -1, -1, -1, -1, -1])
        np.testing.assert_allclose(data.target_probs[ra[0], :2], [.5, .5])
        self.assertEqual(data.is_team[rd].tolist(), [True, False, False])
        self.assertTrue(data.policy_row[rd[0]] and data.team_mask[rd[0]].all() and not data.mask[rd[0]].any())
        self.assertEqual((data.policy_row[rd[2]], data.value_row[rd[2]], data.has_target[rd[2]]), (False, True, False))
        self.assertEqual(sets["held_target"], {int(rd[1])})

    def test_truncation_uses_the_stored_bootstrap(self):
        from duoforge_learn import distill_data
        ed, m = self.ed, self.m
        (b,), _ = _games(ed, m.split_seed, 1, 0)
        S = ed.RowStatus
        gb = _Rows(ed, m, b)
        self._write("0.json", [gb.act(S.UNSELECTED, .3), gb.act(S.UNSELECTED, .6, bootstrap=.37)])
        cut = distill_data.load(self.dir, m).value_target
        gb = _Rows(ed, m, b)
        self._write("0.json", [gb.act(S.UNSELECTED, .3), gb.act(S.UNSELECTED, .6, bootstrap=0.)])
        terminal = distill_data.load(self.dir, m).value_target
        np.testing.assert_allclose(cut, [0.37421, 0.3663], atol=1e-4)
        self.assertGreater(float(np.abs(cut - terminal).min()), 0.3)

    def test_load_refuses_incomplete_trajectories(self):
        from duoforge_learn import distill_data
        ed, m = self.ed, self.m
        (g,), _ = _games(ed, m.split_seed, 1, 0)
        S = ed.RowStatus
        with self.assertRaisesRegex(ValueError, "no shard"):
            distill_data.load(self.dir, m)
        rows = _Rows(ed, m, g)
        first, second = rows.act(S.UNSELECTED, .3), rows.act(S.UNSELECTED, .6)
        self._write("0.json", [first, dataclasses.replace(second, logical_tick=2)])
        with self.assertRaisesRegex(ValueError, "gap"):
            distill_data.load(self.dir, m)
        self._write("0.json", [dataclasses.replace(first, done=True), second])
        with self.assertRaisesRegex(ValueError, "ends before"):
            distill_data.load(self.dir, m)
        self._write("0.json", [first])
        self._write("1.json", [dataclasses.replace(first, key=dataclasses.replace(first.key, request_epoch=5))])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            distill_data.load(self.dir, m)
        other = _Rows(ed, m, g, seat=1)  # one learner seat per game
        self._write("1.json", [other.wait(.1), other.wait(.2)])
        with self.assertRaisesRegex(ValueError, "more than one learner seat"):
            distill_data.load(self.dir, m)


if __name__ == "__main__":
    unittest.main()
