"""duoforge.python.vgcpastes_engine: import_vgcpastes.engine_check against the library (POOL), on Team A of the registry.

The stand-in check of duoforge.reference.import_vgcpastes bypasses exactly this: the engine's status mapped to pool,
pending (with blockers) or illegal (with the rules named).
"""
import re
import sys
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "reference"))
sys.dont_write_bytecode = True

import duoforge  # noqa: E402
from duoforge import _layout, data, teams  # noqa: E402

import import_vgcpastes as ivp  # noqa: E402

TEAM_A = (ROOT / "data" / "teams" / "A.txt").read_text(encoding="utf-8")


def with_set(text, species, old, new):
    """Team A with one line of `species`'s set replaced."""
    blocks = text.strip("\n").split("\n\n")
    for i, block in enumerate(blocks):
        if block.startswith(species):
            assert old in block, (species, old)
            blocks[i] = block.replace(old, new, 1)
    return "\n\n".join(blocks) + "\n"


class EngineCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = duoforge.Context(data_kind=_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"])
        cls.check = staticmethod(ivp.engine_check(cls.ctx))

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()

    def test_team_a_is_pool(self):
        self.assertEqual(self.check(TEAM_A), ("pool", None))

    def test_an_unsupported_learnable_move_is_pending_with_its_blocker(self):
        rilla = data.find(self.ctx, data.TABLE_SPECIES, "rillaboom")
        move = next((m for m in data.forme_moves(self.ctx, rilla) if not data.supported(self.ctx, data.TABLE_MOVE, m)),
                    None)
        if move is None:
            self.skipTest("Rillaboom learns no unsupported move under this library")
        name = data.name(self.ctx, data.TABLE_MOVE, move)
        old = re.search(r"- .+", TEAM_A[TEAM_A.index("Rillaboom"):]).group(0)
        verdict, blockers = self.check(with_set(TEAM_A, "Rillaboom", old, "- " + name))
        self.assertEqual(verdict, "pending")
        self.assertTrue(any(b.endswith("move " + name) for b in blockers), blockers)

    def test_an_ability_the_species_cannot_have_is_illegal_and_named(self):
        old = re.search(r"Ability: .+", TEAM_A[TEAM_A.index("Rillaboom"):]).group(0)
        verdict, detail = self.check(with_set(TEAM_A, "Rillaboom", old, "Ability: Drought"))
        self.assertEqual(verdict, "illegal")
        self.assertIn("Rillaboom cannot have Drought", detail)

    def test_an_unsupported_second_stone_is_a_named_blocker(self):
        # Raichu has two stones (Raichunite X and Y); Team A holds Y. If X's Mega is not supported, X is pending with the
        # Mega named (forme_info covers only the first stone; the blocker must come from mega_at)
        raichu = data.find(self.ctx, data.TABLE_SPECIES, "raichu")
        stones = [data.mega_at(self.ctx, raichu, i) for i in range(data.mega_count(self.ctx, raichu))]
        unsupported = [s for s in stones if not s["supported"]]
        if not unsupported:
            self.skipTest("every Raichu Mega is supported under this library")
        item = data.name(self.ctx, data.TABLE_ITEM, unsupported[0]["stone"])
        line = re.search(r"Raichu.*@ .+", TEAM_A).group(0)
        name = next(n for n in ("Raichunite X", "Raichunite Y") if data.to_id(n) == item)
        verdict, blockers = self.check(with_set(TEAM_A, "Raichu", line, re.sub(r"@ .+", "@ " + name, line)))
        self.assertEqual(verdict, "pending")
        self.assertTrue(any("Mega Evolution of Raichu" in b for b in blockers), blockers)


    def test_the_held_stone_is_found_beyond_the_first(self):
        # A stand-in for mega_at: Raichu's first stone is another, supported one, the held Raichunite Y is the second
        # and unsupported. The blocker must name it (forme_info.mega_stone, the first stone only, would miss it).
        raichu = data.find(self.ctx, data.TABLE_SPECIES, "raichu")
        held = data.find(self.ctx, data.TABLE_ITEM, "raichunitey")
        other = data.find(self.ctx, data.TABLE_ITEM, "raichunitex")
        real_count, real_at = data.mega_count, data.mega_at

        def count(ctx, species):
            return 2 if species == raichu else real_count(ctx, species)

        def at(ctx, species, i):
            if species != raichu:
                return real_at(ctx, species, i)
            return {"stone": (other, held)[i], "supported": i == 0}

        unsupported = _layout.CONSTANTS["DUOFORGE_E_UNSUPPORTED"]
        with mock.patch.object(data, "mega_count", count), mock.patch.object(data, "mega_at", at), \
                mock.patch.object(teams, "check", return_value=unsupported):
            verdict, blockers = self.check(TEAM_A)
        self.assertEqual(verdict, "pending")
        self.assertEqual([b for b in blockers if "Mega" in b],
                         ["set %d: Mega Evolution of Raichu with Raichunite Y" % self.set_of("Raichu")])

    @staticmethod
    def set_of(species):
        return 1 + [b.startswith(species) for b in TEAM_A.strip("\n").split("\n\n")].index(True)


if __name__ == "__main__":
    unittest.main()
