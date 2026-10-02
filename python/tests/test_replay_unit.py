"""duoforge.python.replay_unit: the M11 replay pipeline without Node (spec
docs/superpowers/specs/2026-10-02-m11-replay-data-design.md section 14).

Everything here runs on our own data: the generated tables, the reference
teams and a committed spectator log of one reference battle
(python/tests/data/replay/). No replay of the unlicensed dataset is a test
input.
"""
import re
import unittest

from duoforge_live import data, lines


def _define(header, name):
    return int(re.search(rf"#define {name} (\d+)u", header).group(1))


class DataTest(unittest.TestCase):
    """The POOL tables of the fold (Task 2)."""

    @classmethod
    def setUpClass(cls):
        cls.pool = data.load(kind="pool")
        cls.closure = data.load()
        cls.header = (data.ROOT / "src" / "data" / "pool_tables.h").read_text(encoding="ascii")

    def test_pool_counts(self):
        self.assertEqual(len(self.pool._formes), _define(self.header, "DFI_POOL_FORME_COUNT"))
        self.assertEqual(len(self.pool._pp_max), _define(self.header, "DFI_POOL_MOVE_COUNT"))
        self.assertEqual(len(self.pool._target_class), _define(self.header, "DFI_POOL_MOVE_COUNT"))

    def test_target_types(self):
        moves = self.pool.tables["MOVE"]
        self.assertEqual(self.pool.target_type(moves["TAILWIND"]), "allySide")
        self.assertEqual(self.pool.target_type(moves["PROTECT"]), "self")
        self.assertEqual(self.closure.target_type(moves["PROTECT"]), "self")

    def test_protect_pp(self):
        self.assertEqual(self.pool.pp_max(self.pool.tables["MOVE"]["PROTECT"]), 8)

    def test_closure_prefix_kept(self):
        for forme in range(self.closure.counts["FORME"]):
            self.assertEqual(self.pool.base_forme(forme), self.closure.base_forme(forme))
            self.assertEqual(self.pool.mega_forme(forme), self.closure.mega_forme(forme))
            self.assertEqual(self.pool.ability_of(forme), self.closure.ability_of(forme))
        for move in range(self.closure.counts["MOVE"]):
            self.assertEqual(self.pool.pp_max(move), self.closure.pp_max(move))
            self.assertEqual(self.pool.target_type(move), self.closure.target_type(move))

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            data.load(kind="x")

    def test_unknown_target_class(self):
        pool = data.load(kind="pool")
        pool._target_class = [99]
        with self.assertRaisesRegex(ValueError, "target class 99 has no Showdown target type"):
            pool.target_type(0)


class _View:
    """What lines.check reads of a tracker: the data and, per protocol ident, the sheet and current ability."""

    def __init__(self, members):
        self.data = data.load(kind="pool")
        t = self.data.tables
        self._members = {}
        for ident, (species, item, ability) in members.items():
            self._members[ident] = {"species": t["FORME"][species], "item": t["ITEM"][item] + 1 if item else 0,
                                    "ability": t["ABILITY"][ability] + 1}

    def sheet_of(self, ident):
        return self._members[ident.split(": ")[0][:2] + ": " + ident.split(": ")[1]]

    def ability_now(self, ident):
        return self.sheet_of(ident)["ability"]


class LinesTest(unittest.TestCase):
    """The line classes of the shared fold (Task 3, spec section 5)."""

    @classmethod
    def setUpClass(cls):
        cls.view = _View({"p1: Staraptor": ("STARAPTOR", "SITRUSBERRY", "INTIMIDATE"),
                          "p2: Gholdengo": ("GHOLDENGO", "LIFEORB", "GOODASGOLD")})

    def stop(self, line):
        with self.assertRaises(lines.Stop) as caught:
            lines.check(line, self.view)
        return caught.exception.reason

    def test_feature_lines_stop(self):
        self.assertEqual(self.stop("|-weather|Sandstorm|[from] ability: Sand Stream|[of] p2a: Gholdengo"),
                         "feature:WEATHER_SAND")
        self.assertEqual(self.stop("|-ability|p2a: Gholdengo|Intimidate|[from] ability: Trace|[of] p1a: Staraptor"),
                         "feature:ABILITY_CHANGE")
        self.assertEqual(self.stop("|-enditem|p1a: Staraptor|Sitrus Berry|[from] move: Knock Off|[of] p2a: Gholdengo"),
                         "feature:ITEM_CHANGE")
        self.assertEqual(self.stop("|-status|p1a: Staraptor|tox"), "feature:AILMENT_TOX")
        self.assertEqual(self.stop("|replace|p1a: Zoroark|Zoroark-Hisui, L50, M"), "feature:ILLUSION")

    def test_unknown_lines_stop(self):
        self.assertEqual(self.stop("|-sethp|p1a: Staraptor|50/100"), "line:-sethp")
        self.assertEqual(self.stop("|move|p1a: Staraptor|Baton Pass|p1a: Staraptor"), "line:move Baton Pass")
        self.assertEqual(self.stop("|-activate|p1a: Staraptor|move: Court Change"), "line:-activate move: Court Change")
        self.assertEqual(self.stop("|-ability|p1a: Staraptor|Pressure"), "line:-ability Pressure")

    def test_fold_and_room_lines(self):
        self.assertEqual(lines.check("|-enditem|p1a: Staraptor|Sitrus Berry|[eat]", self.view), "fold")
        self.assertEqual(lines.check("|-ability|p1a: Staraptor|Intimidate|boost", self.view), "fold")
        self.assertEqual(lines.check("|-damage|p2a: Gholdengo|50/100|[from] item: Life Orb", self.view), "fold")
        self.assertIsNone(lines.check("|j|☆x", self.view))
        self.assertIsNone(lines.check("|c|☆x|hi|there", self.view))

    def test_turn_scoped(self):
        self.assertEqual(lines.check("|-singleturn|p1a: Staraptor|move: Rage Powder", self.view), "turn:RAGE_POWDER")
        self.assertEqual(lines.check("|-singleturn|p1a: Staraptor|Wide Guard", self.view), "turn:WIDE_GUARD")

    def test_features_from_the_header(self):
        self.assertEqual(lines.FEATURES["WEATHER_SAND"], 0)
        self.assertEqual(lines.FEATURES["RAGE_POWDER"], 39)
        self.assertEqual(len(lines.FEATURES), 40)
        self.assertEqual(lines.supported(), 0)  # no mechanic of decision 0018 is built yet

    def test_choice_items(self):
        self.assertEqual(lines.CHOICE_ITEMS, ("choiceband", "choicescarf", "choicespecs"))


if __name__ == "__main__":
    unittest.main()
