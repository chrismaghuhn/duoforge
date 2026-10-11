"""duoforge.python.positions: the test positions are what they claim (M12 bundle 7, data/positions).

Every position is reached from its teams, seed and prefix, and its claim is checked against the engine in all of
positions.SAMPLES reseeded copies of the step (positions.verify; statistical, 256 of 256 samples): Fake Out keeps the
partner standing and nothing else that keeps it in and acting does, Protect is the only escape from a knockout, Trick
Room is up (or gone) after the step whatever the foe does, the endgame's exact solution is the expected answer set.
A check over damage needs critical hits on the Pokemon it is about in its sample. The answers
of a checkpoint are not tested here: they are a diagnosis, kept private.
"""
import dataclasses
import unittest

import duoforge
from duoforge import _layout
from duoforge_search import positions

C = _layout.CONSTANTS


class Labels(unittest.TestCase):
    def test_expected_answers_match_by_label(self):
        fake_out = {"move": "fakeout", "target": 2}
        self.assertTrue(positions.accepted([[fake_out, {"any": True}]], ({"move": "fakeout", "target": 2},
                                                                         {"switch": "milotic"})))
        self.assertFalse(positions.accepted([[fake_out, {"any": True}]], ({"move": "fakeout", "target": 3},
                                                                          {"pass": True})))
        self.assertTrue(positions.accepted([[{"not": {"move": "fakeout"}}, {"any": True}]],
                                           ({"move": "woodhammer", "target": 2}, {"pass": True})))
        self.assertFalse(positions.accepted([[{"not": {"move": "fakeout"}}, {"any": True}]],
                                            ({"move": "fakeout", "target": 3}, {"pass": True})))


class Positions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"])
        cls.all = positions.load_all()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()

    def test_every_position_proves_its_claim(self):
        self.assertTrue(self.all, "no position in data/positions")
        for position in self.all:
            with self.subTest(position=position.name):
                report = positions.verify(self.ctx, position)
                self.assertGreater(report["expected"], 0)
                self.assertLess(report["expected"], report["pairs"])  # a position with a wrong answer

    def test_every_kind_refuses_a_position_that_is_not_one(self):
        # Review of #353: each kind's check refuses a position whose claim does not hold, the kinds without a file in
        # data/positions included. The Protect position, relabeled, is no Trick Room position (no Trick Room is up)
        # and no endgame (a pair leaves the battle going).
        base = next(p for p in self.all if p.kind == "protect_vs_ko")
        for kind, claim, message in (("undo_trick_room", {"setter": 0}, "Trick Room has 0 turns left"),
                                     ("endgame", {}, "does not end the battle")):
            with self.subTest(kind=kind), self.assertRaisesRegex(positions.PositionError, message):
                positions.verify(self.ctx, dataclasses.replace(base, kind=kind, claim=claim), n=16)

    def test_a_wrong_expected_answer_is_refused(self):
        # The proof checks the answers, not only the reachability: taking an answer away, or adding a wrong one, fails.
        position = self.all[0]
        wrong = dataclasses.replace(position, expected=(({"any": True}, {"any": True}),))
        with self.assertRaises(positions.PositionError):
            positions.verify(self.ctx, wrong, n=16)


if __name__ == "__main__":
    unittest.main()
