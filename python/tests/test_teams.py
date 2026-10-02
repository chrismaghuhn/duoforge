"""duoforge.python.teams: the team pool (decision 0017).

A pool holds ids, file hashes, weights and side setups; it builds battle
setups for pairs of team indices and refuses weights a sampler cannot use.
"""
import unittest

import numpy as np

import duoforge
from duoforge import teams


def _pool(weights=None):
    return teams.TeamPool.from_setups(("A", "B"), duoforge.reference_setups([0])["sides"][0], weights)


class TeamPoolTest(unittest.TestCase):
    def test_from_setups_and_setups(self):
        pool = _pool()
        self.assertEqual(pool.ids, ("A", "B"))
        self.assertEqual(pool.sha256, ("", ""))
        got = pool.setups(np.array([0, 1]), np.array([1, 1]))
        want = duoforge.reference_setups([0, 3])
        want["rng_initstate"] = 0
        want["rng_initseq"] = 0
        self.assertEqual(got.tobytes(), want.tobytes())

    def test_weights_are_validated(self):
        for bad in ((-1.0, 1.0), (float("nan"), 1.0), (0.0, 0.0), (1.0,), (float("inf"), 1.0)):
            with self.assertRaises(ValueError):
                _pool(bad)
        self.assertEqual(_pool((0.0, 2.0)).weights.tolist(), [0.0, 2.0])
        self.assertEqual(_pool().with_weights((3.0, 1.0)).weights.tolist(), [3.0, 1.0])

    def test_pool_needs_unique_ids_and_matching_sides(self):
        sides = duoforge.reference_setups([0])["sides"][0]
        with self.assertRaises(ValueError):
            teams.TeamPool.from_setups(("A", "A"), sides)
        with self.assertRaises(ValueError):
            teams.TeamPool.from_setups(("A", "B", "C"), sides)


_PASTE = """Rillaboom (M) @ Miracle Seed
Ability: Grassy Surge
Level: 50
EVs: 18 HP / 32 Atk / 2 Def / 6 SpD / 8 Spe
Adamant Nature
- Wood Hammer
- Grassy Glide

Gholdengo @ Life Orb
Ability: Good as Gold
EVs: 17 HP / 2 Def / 17 SpA / 16 SpD / 14 Spe
Modest Nature
- Make It Rain
"""


class ParseTest(unittest.TestCase):
    def test_parse_reads_every_field(self):
        members = teams.parse(_PASTE, "t.txt")
        self.assertEqual(len(members), 2)
        a, b = members
        self.assertEqual((a["species"], a["gender"], a["item"], a["ability"], a["nature"]),
                         ("Rillaboom", "M", "Miracle Seed", "Grassy Surge", "Adamant"))
        self.assertEqual(a["stat_points"], [18, 32, 2, 0, 6, 8])
        self.assertEqual(a["moves"], ["Wood Hammer", "Grassy Glide"])
        self.assertEqual((b["gender"], b["item"]), (None, "Life Orb"))

    def test_parse_errors_name_file_line_and_reason(self):
        cases = {
            "Bob (Rillaboom) (M) @ Miracle Seed": "nickname",
            "Level: 100": "level",
            "IVs: 31 HP": "line",
            "Shiny: Yes": "line",
            "- Protect\n- Fake Out\n- Tailwind": "moves",
            "Happy Nature Feelings": "line",
            "EVs: 18 Health": "EVs",
        }
        for bad, reason in cases.items():
            text = _PASTE.replace("Level: 50", bad) if not bad.startswith("Bob") else \
                _PASTE.replace("Rillaboom (M) @ Miracle Seed", bad)
            with self.assertRaises(teams.TeamError, msg=bad) as caught:
                teams.parse(text, "t.txt")
            self.assertIn("t.txt:", str(caught.exception))
            self.assertIn(reason, str(caught.exception))

    def test_crlf_and_trailing_spaces_parse_and_hash_like_lf(self):
        crlf = "\r\n".join(line + "  " for line in _PASTE.split("\n"))
        self.assertEqual(teams.parse(crlf, "t.txt"), teams.parse(_PASTE, "t.txt"))
        self.assertEqual(teams.text_sha256(_PASTE.replace("\n", "\r\n").encode()),
                         teams.text_sha256(_PASTE.encode()))
        self.assertNotEqual(teams.text_sha256(b"a"), teams.text_sha256(b"b"))


if __name__ == "__main__":
    unittest.main()
