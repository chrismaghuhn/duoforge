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

    # --- part 2, the Detect probe (README "Part 2"): the edited move's slot holds another move instead

    def test_a_replacement_keeps_the_slot_and_the_count(self):
        setups = monotone._setup(self.pool, self.game, None)
        m = setups[0]["sides"][1]["members"][2]
        moves = [int(x["move_id"]) for x in m["moves"][:int(m["move_count"])]]
        edit = monotone.Edit(1, 2, moves[1], replace=(0xBEEF, 7))
        got = monotone._setup(self.pool, self.game, edit)[0]["sides"][1]["members"][2]
        self.assertEqual(int(got["move_count"]), len(moves))
        self.assertEqual([int(x["move_id"]) for x in got["moves"][:len(moves)]], [moves[0], 0xBEEF, *moves[2:]])
        self.assertEqual(int(got["moves"][1]["pp_max"]), 7)
        self.assertEqual([int(x["pp_max"]) for x in got["moves"][:len(moves)] if int(x["move_id"]) != 0xBEEF],
                         [int(x["pp_max"]) for x in m["moves"][:len(moves)] if int(x["move_id"]) != moves[1]])
        with self.assertRaisesRegex(ValueError, "already has"):
            monotone._setup(self.pool, self.game, monotone.Edit(1, 2, moves[1], replace=(moves[0], 7)))
        with self.assertRaisesRegex(ValueError, "no move"):
            monotone._setup(self.pool, self.game, monotone.Edit(1, 2, 0xFFFF, replace=(0xBEEF, 7)))

    def test_a_replacement_the_engine_refuses_is_named_detect_not_allowed(self):
        base = monotone.walk(self.ctx, self.pool, self.game)
        (side, member), moves = next(iter(base.moves.items()))
        refusal = duoforge.DuoforgeError("DUOFORGE_E_INVALID_ARGUMENT", np.array([2], np.uint32))
        with mock.patch.object(duoforge.Batch, "reset_setups", side_effect=refusal):
            walk = monotone.walk(self.ctx, self.pool, self.game,
                                 edit=monotone.Edit(side, member, moves[0], replace=(0xBEEF, 8)), reference=base.events)
        self.assertEqual(walk.stop, ("detect_not_allowed", 0))

    def test_a_replaced_edit_is_replayed_through_the_engine(self):
        # The engine accepts the setup (a member's own move put back in its slot, the identity replacement): the replay
        # reaches the turn boundary and the observed moves keep their slots. A real Detect's legality is the engine's.
        base = monotone.walk(self.ctx, self.pool, self.game)
        t = min(base.turns)
        side, slot, member, move = next(a for a in base.turns[t]
                                        if base.first_use.get((a[0], a[2], a[3]), len(self.game["steps"])) > t)
        m = monotone._setup(self.pool, self.game, None)[0]["sides"][side]["members"][member]
        pp = next(int(x["pp_max"]) for x in m["moves"][:int(m["move_count"])] if int(x["move_id"]) == move)
        seen = {}

        def at_turn(step, batch):
            if step == t:
                seen["moves"] = monotone._moves_of(batch, side, member)

        walk = monotone.walk(self.ctx, self.pool, self.game, edit=monotone.Edit(side, member, move, replace=(move, pp)),
                             reference=base.events, on_turn=at_turn)
        self.assertTrue(walk.stop is None or walk.stop[1] > t, walk.stop)
        self.assertEqual(seen["moves"], base.moves[(side, member)])

    def test_the_replaced_rows_keep_part_ones_fields_and_pair_the_two_edits(self):
        plain = list(monotone.measure_game(self.ctx, self.pool, self.game, self.net, game_index=3))
        detect = monotone.detect_slot(self.ctx, self.pool, required=False) or (0xBEEF, 8)
        rows = list(monotone.measure_game(self.ctx, self.pool, self.game, self.net, game_index=3, replace=detect))
        self.assertEqual([{k: r[k] for k in monotone.PART1_KEYS} for r in rows], plain)
        self.assertEqual(monotone.games_digest(rows), monotone.games_digest(plain))
        for r in rows:
            self.assertIn(r["refused_replaced"], (None, *monotone.REPLACE_REFUSALS))
            self.assertIsInstance(r["subset"], bool)
            if r["refused"] is None and r["refused_replaced"] is None:
                self.assertAlmostEqual(r["dv_rd"], r["dv_replaced"] - r["dv"], places=6)
            else:
                self.assertIsNone(r["dv_rd"])


def _p2(kind, dv, dv_replaced, game=0, subset=True, refused=None, refused_replaced=None, category="status"):
    row = _r(kind, dv, game=game, category=category, refused=refused)
    built = refused is None and refused_replaced is None
    row.update({"subset": subset, "carries_protect": subset, "refused_replaced": refused_replaced,
                "dv_replaced": dv_replaced, "dv_rd": dv_replaced - dv if built else None})
    return row


class DetectParts(unittest.TestCase):
    def test_the_pre_build_refusals_and_the_subset(self):
        protect, detect = 10, 20
        self.assertEqual(monotone.replace_refusal(detect, [detect, 1], detect), "removed_is_detect")
        self.assertEqual(monotone.replace_refusal(1, [detect, 1], detect), "already_detect")
        self.assertIsNone(monotone.replace_refusal(1, [protect, 1], detect))
        self.assertTrue(monotone.in_subset(1, [protect, 1], protect))
        self.assertFalse(monotone.in_subset(protect, [protect, 1], protect))  # Protect itself edited
        self.assertFalse(monotone.in_subset(1, [2, 1], protect))  # no Protect

    def test_detect_slot_copies_the_pools_own_detect_slot(self):
        ctx = duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"])
        try:
            detect = int(duoforge.data.find(ctx, duoforge.data.TABLE_MOVE, "detect"))

            class Pool:
                sides = np.zeros(2, _layout.SIDE_SETUP)

            Pool.sides["member_count"] = 1
            for i, pp in enumerate((8, 8)):
                Pool.sides[i]["members"][0]["move_count"] = 2
                Pool.sides[i]["members"][0]["moves"][1] = (detect, pp)
            self.assertEqual(monotone.detect_slot(ctx, Pool), (detect, 8))
            Pool.sides[1]["members"][0]["moves"][1] = (detect, 5)
            with self.assertRaisesRegex(ValueError, "pp_max"):
                monotone.detect_slot(ctx, Pool)
            Pool.sides["members"][:, 0]["moves"] = 0
            with self.assertRaisesRegex(ValueError, "no Detect"):
                monotone.detect_slot(ctx, Pool)
            self.assertIsNone(monotone.detect_slot(ctx, Pool, required=False))
        finally:
            ctx.close()

    def test_the_games_digest_names_a_differing_game(self):
        rows = [dict(_r(kind, dv, game=g), t=3, member=1, species=7, move=9)
                for kind, dv, g in (("own", 0.03, 0), ("mirror", 0.0, 0), ("own", 0.01, 1))]
        digest = monotone.games_digest(rows)
        self.assertEqual(sorted(digest), [0, 1])
        changed = [dict(r) for r in rows]
        changed[2]["dv"] = 0.02
        other = monotone.games_digest(changed)
        self.assertEqual([g for g in digest if digest[g] != other[g]], [1])
        extra = [dict(r, subset=True, dv_rd=0.5) for r in rows]  # part 2's fields do not enter it
        self.assertEqual(monotone.games_digest(extra), digest)

    def test_the_report_reads_the_subset_only(self):
        small = [_p2(kind, 0.0, 0.001 * (g % 3), game=g) for g in range(250) for kind in ("own", "mirror")]
        large = [_p2(kind, 0.0, 0.5, game=g, subset=False) for g in range(50) for kind in ("own", "mirror")]
        refused = [_p2("own", 0.0, None, game=1, refused_replaced="detect_not_allowed"),
                   _p2("own", 0.0, None, game=2, subset=False, refused_replaced="detect_not_allowed")]
        rep = monotone.report_detect(small + large + refused, bootstrap=200, seed=0x509)
        self.assertEqual(rep["reading"], "missing_slot_not_driving")  # the large others do not count
        self.assertEqual(rep["subset"]["own"]["paired"], 250)
        self.assertEqual(rep["other"]["own"]["paired"], 50)
        self.assertEqual(rep["refused_replaced"], {"subset": {"detect_not_allowed": 1},
                                                   "other": {"detect_not_allowed": 1}})
        self.assertLessEqual(rep["subset"]["own"]["abs_dv_rd"]["median"], 0.02)
        self.assertEqual(rep["subset"]["own"]["share_above"]["share"], 0.0)
        self.assertEqual(monotone.report_detect(small + large + refused, bootstrap=200, seed=0x509), rep)

    def test_the_reading_rule(self):
        def rows(value, n=250, kinds=("own", "mirror")):
            return [_p2(kind, 0.0, value, game=g) for g in range(n) for kind in kinds]
        read = lambda r: monotone.report_detect(r, bootstrap=50, seed=0x509)["reading"]  # noqa: E731
        self.assertEqual(read(rows(0.01)), "missing_slot_not_driving")
        self.assertEqual(read(rows(0.05)), "missing_slot_moves_value")
        self.assertEqual(read(rows(0.01) [:250 * 2:2] + rows(0.05, kinds=("mirror",))), "missing_slot_moves_value")
        self.assertEqual(read(rows(0.01, n=150)), "no_conclusion_too_few")
        # median above nothing, share between 25 and 50 %: no conclusion
        mixed = [_p2(kind, 0.0, 0.05 if g % 10 < 4 else 0.0, game=g) for g in range(250) for kind in ("own", "mirror")]
        self.assertEqual(read(mixed), "no_conclusion")


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
