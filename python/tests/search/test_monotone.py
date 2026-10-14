"""BC6's value under a removed move (duoforge_search.monotone; README docs/benchmarks/2026-10-15-bc6-monotone, #509):
games recorded by label and replayed exactly; an edit (one move of one member removed) built only through the engine,
refused by name where the replay uses the removed move or the engine's events diverge; the aggregates."""
import os
os.environ["JAX_PLATFORMS"] = "cpu"

import unittest
from unittest import mock

import numpy as np

import duoforge
from duoforge import _layout, features
from duoforge_search import monotone

C = _layout.CONSTANTS
TINY = {"embed": 4, "member": 8, "position": 8, "hidden": 16, "layers": 1, "option": 8}


def _tiny():
    import jax
    from duoforge_learn import policy
    model = policy.make(policy.v2_config("S", **TINY), features.feature_names(4))
    return model, model.init(jax.random.PRNGKey(7))


class Games(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, cls.params = _tiny()
        cls.ctx = duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"])
        cls.pool = duoforge.teams.load(cls.ctx, ["A", "B", "C"])
        with duoforge.Batch(cls.ctx, duoforge.reference_setups([0]), 1, 42) as b:
            cls.ext = int(b.observe_ext()[0, 0]["supported"]) & features.version_features(4)
        cls.net = monotone.Net(cls.model, cls.params, 4, cls.ext)
        cls.game = monotone.record_game(cls.ctx, cls.pool, 0, 1, 0x509, cls.net, max_steps=60)

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()

    def test_a_game_is_recorded_by_label_and_deterministic(self):
        again = monotone.record_game(self.ctx, self.pool, 0, 1, 0x509, self.net, max_steps=60)
        self.assertEqual(again, self.game)
        self.assertEqual(self.game["teams"], [0, 1])
        first = self.game["steps"][0]
        self.assertTrue(all("picks" in x for x in first))  # the team preview: both seats pick
        turn = self.game["steps"][1]
        for side in (0, 1):
            if turn[side] is not None:
                self.assertEqual(len(turn[side]), 2)  # one label per active slot
                self.assertTrue(all(isinstance(x, dict) for x in turn[side]))

    def test_the_unedited_replay_reaches_every_turn_boundary(self):
        walk = monotone.walk(self.ctx, self.pool, self.game)
        self.assertIsNone(walk.stop)
        self.assertGreater(len(walk.turns), 0)
        self.assertEqual(len(walk.events), len(self.game["steps"]))
        again = monotone.walk(self.ctx, self.pool, self.game)
        self.assertEqual([e[0].tobytes() + e[1].tobytes() for e in again.events],
                         [e[0].tobytes() + e[1].tobytes() for e in walk.events])

    def test_an_edit_removes_the_move_through_the_engine(self):
        # an active member's move the game has not used by the first turn boundary: the edited replay reaches it
        base = monotone.walk(self.ctx, self.pool, self.game)
        t = min(base.turns)
        side, slot, member, move = next(a for a in base.turns[t]
                                        if base.first_use.get((a[0], a[2], a[3]), len(self.game["steps"])) > t)
        seen = {}

        def at_turn(step, batch):
            if step == t:
                own = batch.observations[0, side]["sides"][side]
                m = own["members"][int(own["occupant"][slot])]
                seen["moves"] = [int(x) for x in m["move_ids"][:int(m["move_count"])]]

        walk = monotone.walk(self.ctx, self.pool, self.game, edit=monotone.Edit(side, member, move),
                             reference=base.events, on_turn=at_turn)
        self.assertTrue(walk.stop is None or walk.stop[1] > t, walk.stop)
        self.assertEqual(seen["moves"], [x for x in base.moves[(side, member)] if x != move])

    def test_events_that_differ_from_the_reference_are_named(self):
        base = monotone.walk(self.ctx, self.pool, self.game)
        k = min(base.turns)
        tampered = [list(e) for e in base.events]
        tampered[k][1] = tampered[k][1].copy()
        tampered[k][1]["kind"][0] ^= 1  # one event of the foe's view, another kind
        walk = monotone.walk(self.ctx, self.pool, self.game, reference=tampered)
        self.assertEqual(walk.stop, ("replay_diverged", k))

    def test_a_used_move_refuses_the_edit_by_name(self):
        # the move the recorded game uses first, removed: the replay stops there, named
        base = monotone.walk(self.ctx, self.pool, self.game)
        used = base.first_use
        self.assertTrue(used, "the recorded game uses no move")
        (side, member, move), step = min(used.items(), key=lambda kv: kv[1])
        walk = monotone.walk(self.ctx, self.pool, self.game, edit=monotone.Edit(side, member, move),
                             reference=base.events)
        self.assertEqual(walk.stop, ("removed_move_used", step))

    def test_a_setup_the_engine_refuses_is_named(self):
        base = monotone.walk(self.ctx, self.pool, self.game)
        (side, member), moves = next(iter(base.moves.items()))
        refusal = duoforge.DuoforgeError("DUOFORGE_E_INVALID_ARGUMENT", np.array([2], np.uint32))
        with mock.patch.object(duoforge.Batch, "reset_setups", side_effect=refusal):
            walk = monotone.walk(self.ctx, self.pool, self.game, edit=monotone.Edit(side, member, moves[0]),
                                 reference=base.events)
        self.assertEqual(walk.stop, ("setup_refused", 0))

    def test_a_move_the_member_lacks_is_no_edit(self):
        base = monotone.walk(self.ctx, self.pool, self.game)
        side, member = next(iter(base.moves))
        with self.assertRaisesRegex(ValueError, "no move"):
            monotone.walk(self.ctx, self.pool, self.game, edit=monotone.Edit(side, member, 0xFFFF))

    def test_the_measured_rows_of_a_game(self):
        rows = list(monotone.measure_game(self.ctx, self.pool, self.game, self.net, game_index=3))
        self.assertGreater(len(rows), 0)
        for r in rows:
            self.assertEqual(r["game"], 3)
            self.assertIn(r["kind"], ("own", "mirror"))
            self.assertEqual(r["kind"] == "own", r["seat"] == r["side"])
            self.assertIn(r["category"], ("physical", "special", "status"))
            if r["refused"] is None:
                self.assertAlmostEqual(r["dp"], r["dv"] / 2, places=6)
            else:
                self.assertIn(r["refused"], monotone.REFUSALS)
                self.assertIsNone(r["dv"])
        again = list(monotone.measure_game(self.ctx, self.pool, self.game, self.net, game_index=3))
        self.assertEqual(again, rows)


def _r(kind, dv, game=0, category="status", refused=None, protect=False, seat=0):
    return {"game": game, "kind": kind, "category": category, "protect_like": protect, "seat": seat,
            "side": seat if kind == "own" else 1 - seat, "refused": refused,
            "dv": dv, "dp": None if dv is None else dv / 2}


class Report(unittest.TestCase):
    def test_the_wrong_way_rule(self):
        self.assertTrue(monotone.wrong_way(_r("own", 0.021)))   # dp 0.0105 > 0.01
        self.assertFalse(monotone.wrong_way(_r("own", 0.02)))   # dp 0.01 is not above
        self.assertTrue(monotone.wrong_way(_r("mirror", -0.021)))
        self.assertFalse(monotone.wrong_way(_r("mirror", 0.5)))
        self.assertTrue(monotone.wrong_way(_r("own", 0.011), scale="value"))  # the comparison reading, |dV| > 0.01
        self.assertFalse(monotone.wrong_way(_r("own", 0.011)))

    def test_wilson(self):
        lo, hi = monotone.wilson(0, 10)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.2775, places=3)
        lo, hi = monotone.wilson(5, 10)
        self.assertAlmostEqual(lo + hi, 1.0, places=9)

    def test_the_report_counts_rates_and_refusals_by_category(self):
        rows = [_r("own", 0.03, game=0), _r("own", 0.0, game=1), _r("own", None, game=1, refused="removed_move_used"),
                _r("mirror", -0.03, game=0, category="physical"), _r("mirror", 0.0, game=2, category="physical"),
                _r("own", None, game=2, category="physical", refused="replay_diverged")]
        rep = monotone.report(rows, bootstrap=200, seed=0x509)
        self.assertEqual(rep["own"]["built"], 2)
        self.assertEqual(rep["own"]["wrong"], 1)
        self.assertEqual(rep["own"]["rate"], 0.5)
        self.assertEqual(rep["mirror"]["wrong"], 1)
        self.assertEqual(rep["refused"], {"removed_move_used": 1, "replay_diverged": 1})
        self.assertEqual(rep["removed_move_used_share"]["own"]["status"], 1 / 3)
        self.assertEqual(rep["removed_move_used_share"]["own"]["physical"], 0.0)
        lo, hi = rep["own"]["cluster_95"]
        self.assertTrue(0.0 <= lo <= rep["own"]["rate"] <= hi <= 1.0)
        self.assertEqual(monotone.report(rows, bootstrap=200, seed=0x509), rep)  # seeded


if __name__ == "__main__":
    unittest.main()
