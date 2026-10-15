"""The role check's pair probe (duoforge_search.role_check; #440, 2026-10-15): the damage of each side's commands read
from the engine's events, the best of each side, the move order and the KO race, and turn 1 that brings a benched
member in through the engine's own switch."""
import os
os.environ["JAX_PLATFORMS"] = "cpu"

import json
import unittest

import numpy as np

import duoforge
from duoforge import _layout
from duoforge_search import lookahead, role_check

C = _layout.CONSTANTS


def first_pair(batch, envs, side):
    """A policy that likes every pair alike: the likeliest pair is the first legal one."""
    return np.zeros((len(envs), lookahead.PAIRS))


def events(*rows):
    out = np.zeros(len(rows), _layout.EVENT)
    for n, row in enumerate(rows):
        for k, v in row.items():
            out[n][k] = v
    return out


def ev(kind, position, **more):
    return {"kind": C[f"DUOFORGE_EVENT_{kind}"], "position": position, **more}


class Events(unittest.TestCase):
    def test_damage_counts_the_users_hits_on_the_target_only(self):
        e = events(ev("MOVE", 0, other=2), ev("DAMAGE", 2, hp=70),  # 0 hits 2: 30
                   ev("MOVE", 1, other=2), ev("DAMAGE", 2, hp=60),  # the partner hits 2: not 0's
                   ev("DAMAGE", 2, hp=55, cause=C["DUOFORGE_CAUSE_RECOIL"]),  # no plain hit
                   ev("MOVE", 0, other=2), ev("DAMAGE", 2, hp=40),  # 0 again: 15
                   ev("UPKEEP", 255), ev("DAMAGE", 2, hp=35))  # residual after the moves
        self.assertEqual(role_check._damage(e, 0, 2, 100), (45, True))
        self.assertEqual(role_check._damage(e, 3, 2, 100), (0, False))
        switched = events(ev("MOVE", 0, other=2), ev("SWITCH", 2, hp=90), ev("DAMAGE", 2, hp=80))
        self.assertEqual(role_check._damage(switched, 0, 2, 100), (0, True))  # another Pokemon stands there
        self.assertEqual(role_check._first(e, 1, 0), 0)
        self.assertIsNone(role_check._first(e, 2, 3))

    def test_the_race(self):
        self.assertEqual(role_check.race(2, 3, "x"), "b")
        self.assertEqual(role_check.race(3, 2, "b"), "x")
        self.assertEqual(role_check.race(2, 2, "x"), "x")  # a tie: the one moving first
        self.assertEqual(role_check.race(None, 4, "b"), "x")
        self.assertEqual(role_check.race(1, None, "x"), "b")
        self.assertIsNone(role_check.race(None, None, "b"))


class Tables(unittest.TestCase):
    def test_a_foe_pokemon_is_answered_where_some_member_wins_its_race(self):
        win, lose = {"winner": "b"}, {"winner": "x"}
        table = {(0, 5): [win, lose, "fainted", lose], (1, 5): [lose, win, lose, "setup_refused"],
                 (0, 6): [lose, lose, lose, lose]}
        self.assertEqual(role_check.answers(table), {5: 0.5, 6: 0.0})
        self.assertEqual(role_check.answers(table, foes={6}), {6: 0.0})

    def test_the_report_sums_the_own_faints_by_phase(self):
        def row(turn, lost, switch, result):
            return {"turn": turn, "phase": role_check.phase(turn), "foes_left": 2, "answered_before": 2,
                    "answered_after": 2 - lost, "lost_last_answer": lost, "switch_candidate": switch, "result": result}
        rows = [row(2, 1, True, -1.0), row(5, 0, False, 1.0), row(8, 2, False, -1.0), row(9, 0, True, None)]
        got = role_check.aggregate(rows)
        self.assertEqual(got["all"], {"own_faints": 4, "lost_last_answer": 2, "lost_last_answer_game_lost": 2,
                                      "lost_last_answer_switch_candidate": 1, "foes_left": 8, "answered_after": 5,
                                      "games_lost": 2})
        self.assertEqual((got["early"]["own_faints"], got["middle"]["own_faints"], got["endgame"]["own_faints"]),
                         (1, 1, 2))
        self.assertEqual([role_check.phase(t) for t in (1, 3, 4, 6, 7, 20)],
                         ["early", "early", "middle", "middle", "endgame", "endgame"])

    def test_the_cli_refuses_before_loading_anything(self):
        import tempfile
        from duoforge_live.data import ROOT
        with self.assertRaises(SystemExit):
            role_check.main(["--logs", "x", "--team", "x", "--checkpoint", "x", "--bot", "b",
                             "--out", os.path.join(str(ROOT), "role-out")])
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(SystemExit, "--limit"):
            role_check.main(["--logs", "x", "--team", "x", "--checkpoint", "x", "--bot", "b", "--limit", "0",
                             "--out", os.path.join(tmp, "o")])


class Probe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"])
        cls.pool = duoforge.teams.load(cls.ctx, ["A", "B"])

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()

    def turn_one(self, envs=1):
        batch = duoforge.Batch(self.ctx, np.resize(self.pool.setups(np.array([0]), np.array([1])), envs), 1, 7)
        self.addCleanup(batch.close)
        batch.query()
        batch.query_factored()
        choices = np.zeros((envs, 2), _layout.FACTORED_CHOICE)
        choices["picks"][:, :, :4] = np.arange(4, dtype=np.uint8)
        batch.step_factored(choices)
        batch.query()
        batch.query_factored()
        return batch

    def test_the_probe_of_two_actives_reads_the_engines_damage(self):
        batch = self.turn_one()
        b, x = role_check.occupants(batch, 0, 0)[0], role_check.occupants(batch, 0, 1)[0]
        rng = duoforge.search_seeds(1, 2, role_check.PROBE_SAMPLE)
        got = role_check.probe_pair(batch, 0, 0, b, x, first_pair, rng)
        self.assertEqual(got, role_check.probe_pair(batch, 0, 0, b, x, first_pair, rng))  # one seed: deterministic
        self.assertEqual((got["hp_b"], got["hp_x"]), (role_check.hp_of(batch, 0, 0, b), role_check.hp_of(batch, 0, 1, x)))
        self.assertTrue(got["best_b"] is None or 0 <= got["best_b"] <= got["hp_x"])
        self.assertTrue(got["best_x"] is None or 0 <= got["best_x"] <= got["hp_b"])
        self.assertTrue(got["best_b"] or got["best_x"])  # A and B's leads hurt each other
        if got["best_b"]:
            self.assertEqual(got["turns_b"], -(-got["hp_x"] // got["best_b"]))
        self.assertEqual(got["winner"], role_check.race(got["turns_b"], got["turns_x"], got["first"]))
        self.assertIn(got["first"], ("b", "x", None))
        # the probe changed nothing of the batch
        self.assertEqual(role_check.hp_of(batch, 0, 1, x), got["hp_x"])
        with self.assertRaises(role_check.Unprobed) as caught:
            bench = next(m for m in range(4) if m not in role_check.occupants(batch, 0, 0))
            role_check.probe_pair(batch, 0, 0, bench, x, first_pair, rng)
        self.assertEqual(caught.exception.args[0], "not_active")

    def test_turn_one_brings_a_benched_member_in_through_the_engine(self):
        batch = self.turn_one()
        ours, theirs = role_check.occupants(batch, 0, 0), role_check.occupants(batch, 0, 1)
        bench = next(m for m in range(4) if m not in ours)
        choices, need = role_check.setup_choices(batch, [0], 0, [(bench, theirs[0])], first_pair)
        self.assertEqual(need.tolist(), [True])
        keep = role_check.switch_keep(batch, 0, 0, bench)
        self.assertTrue(keep(tuple(int(v) for v in choices["slot"][0, 0])))
        batch.step_factored(choices)
        batch.query()
        batch.query_factored()
        if role_check.hp_of(batch, 0, 0, bench) > 0:
            self.assertIn(bench, role_check.occupants(batch, 0, 0))
        _, need = role_check.setup_choices(self.turn_one(), [0], 0, [(ours[0], theirs[0])], first_pair)
        self.assertEqual(need.tolist(), [False])  # both active: no turn 1



class OnTheLog(unittest.TestCase):
    """The role check on the closed-sheet fixture log of the KO check's tests (the arena bot's own log), with the
    bot's particles: every decision's role table holds a probe or a named reason for each pair in each world."""
    setUpClass = classmethod(lambda cls: _closed().setUpClass.__func__(cls))
    tearDownClass = classmethod(lambda cls: cls.tmp.cleanup())

    def test_every_decision_gets_a_role_table(self):
        import io
        from collections import Counter
        from python.tests.live.test_live_client import FIXTURE
        from python.tests.live.test_pkmn_arena import NAME
        live, net, tables = _closed().load(self)
        pairs = io.StringIO()
        rows = role_check.battle(self.log, tables, net, live, FIXTURE["team"], NAME, self.prior, Counter(), pairs)
        tables_seen = [json.loads(line) for line in pairs.getvalue().splitlines()]
        self.assertTrue(tables_seen)
        reasons = {"fainted", "not_active", "not_a_turn", "cannot_switch_in", "setup_refused", "step_refused"}
        probes = 0
        for t in tables_seen:
            self.assertEqual(len(t["worlds"]), live.searcher.searcher.s)
            for got in t["worlds"]:
                if isinstance(got, dict):
                    probes += 1
                    self.assertEqual(got["winner"], role_check.race(got["turns_b"], got["turns_x"], got["first"]))
                else:
                    self.assertIn(got, reasons)
        self.assertGreater(probes, 0)
        for r in rows:  # an own faint in the fixture's few turns is possible, not required
            self.assertIn(r["phase"], ("early", "middle", "endgame"))


def _closed():
    from python.tests.search.test_ko_check import ClosedReplayTest
    return ClosedReplayTest


if __name__ == "__main__":
    unittest.main()
