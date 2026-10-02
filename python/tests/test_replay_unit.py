"""duoforge.python.replay_unit: the M11 replay pipeline without Node (spec
docs/superpowers/specs/2026-10-02-m11-replay-data-design.md section 14).

Everything here runs on our own data: the generated tables, the reference
teams and a committed spectator log of one reference battle
(python/tests/data/replay/). No replay of the unlicensed dataset is a test
input.
"""
import re
import unittest

from duoforge_live import data


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


if __name__ == "__main__":
    unittest.main()
