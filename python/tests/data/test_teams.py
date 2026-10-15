"""duoforge.python.teams: the team pool (decision 0017).

A pool holds ids, file hashes, weights and side setups; it builds battle
setups for pairs of team indices and refuses weights a sampler cannot use.
"""
import os
import shutil
import tempfile
import unittest

import numpy as np

import duoforge
from duoforge import _layout, data, teams

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data", "teams")
TEAM_C = _layout.CONSTANTS["DUOFORGE_DATA_KIND_TEAM_C"]
INVALID = "DUOFORGE_E_INVALID_ARGUMENT"


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
        for bad in ((-1.0, 1.0), (float("nan"), 1.0), (0.0, 0.0), (1.0,), (float("inf"), 1.0), (1e308, 1e308)):
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


class DataTest(unittest.TestCase):
    def test_names_and_ids_round_trip(self):
        with duoforge.Context() as closure, duoforge.Context(data_kind=TEAM_C) as team_c:
            self.assertEqual(data.count(closure, data.TABLE_SPECIES), 16)
            self.assertEqual(data.count(team_c, data.TABLE_SPECIES), 23)
            move = data.find(team_c, data.TABLE_MOVE, "closecombat")
            self.assertEqual(data.name(team_c, data.TABLE_MOVE, move), "closecombat")
            with self.assertRaises(duoforge.DuoforgeError):
                data.find(closure, data.TABLE_SPECIES, "sneasler")  # a Team C species is outside the closure
        self.assertEqual(data.to_id("Indeedee-F"), "indeedeef")
        self.assertEqual(data.to_id("U-turn"), "uturn")


class LoadTest(unittest.TestCase):
    def test_registry_teams_a_and_b_equal_the_reference_setups(self):
        with duoforge.Context() as ctx:
            pool = teams.load(ctx, ["A", "B"], root=ROOT)
        want = duoforge.reference_setups([0])["sides"][0]
        self.assertEqual(pool.ids, ("A", "B"))
        self.assertEqual(pool.sides.tobytes(), want.tobytes())
        self.assertEqual(len(pool.sha256[0]), 64)

    def test_team_c_accepted_under_team_c_refused_under_closure(self):
        with duoforge.Context(data_kind=TEAM_C) as ctx:
            pool = teams.load(ctx, ["A", "B", "C"], root=ROOT)
        self.assertEqual(pool.ids, ("A", "B", "C"))
        with duoforge.Context() as ctx, self.assertRaises(teams.TeamError) as caught:
            teams.load(ctx, ["C"], root=ROOT)
        self.assertIn("team C", str(caught.exception))

    def _registry(self, edit):
        """A copy of the registry with team A's text edited; the index hash is updated."""
        import json
        d = tempfile.mkdtemp(prefix="duoforge-teams-")
        self.addCleanup(shutil.rmtree, d, True)
        for f in os.listdir(ROOT):
            shutil.copy(os.path.join(ROOT, f), d)
        path = os.path.join(d, "A.txt")
        with open(path, encoding="utf-8") as f:
            text = edit(f.read())
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        index_path = os.path.join(d, "index.json")
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)
        index["teams"][0]["sha256"] = teams.text_sha256(text.encode("utf-8"))
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f)
        return d

    def test_unknown_name_is_refused(self):
        root = self._registry(lambda t: t.replace("- Wood Hammer", "- Not A Move"))
        with duoforge.Context() as ctx, self.assertRaises(teams.TeamError) as caught:
            teams.load(ctx, ["A"], root=root)
        self.assertIn("move", str(caught.exception))
        self.assertIn("notamove", str(caught.exception))

    def test_missing_gender_refused_for_a_gendered_species(self):
        root = self._registry(lambda t: t.replace("Rillaboom (M)", "Rillaboom"))
        with duoforge.Context() as ctx, self.assertRaises(teams.TeamError) as caught:
            teams.load(ctx, ["A"], root=root)
        self.assertIn(INVALID, str(caught.exception))

    def test_changed_file_against_the_index_is_refused(self):
        root = self._registry(lambda t: t)
        with open(os.path.join(root, "A.txt"), "a", encoding="utf-8") as f:
            f.write("\n")
        with duoforge.Context() as ctx, self.assertRaisesRegex(teams.TeamError, "sha256"):
            teams.load(ctx, ["A"], root=root)

    def test_load_accepted_leaves_a_refused_team_out_by_name(self):
        # A registry team the engine refuses under POOL since #406 (exactly 0 Stat Points with Serious): load stops on
        # it; load_accepted leaves it out, named with the engine's status, and keeps the others in order with their
        # weights (the ladder's pool filter, HauptSession 2026-10-15).
        refused_id = "LL_6A5E4489937230B102D4026E_110"
        pool_kind = _layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]
        ids = ["A", refused_id, "B"]
        with duoforge.Context(data_kind=pool_kind) as ctx:
            with self.assertRaisesRegex(teams.TeamError, refused_id):
                teams.load(ctx, ids, root=ROOT)
            pool, refused = teams.load_accepted(ctx, ids, root=ROOT, weights=[1.0, 5.0, 3.0])
            alone = teams.load(ctx, ["A", "B"], root=ROOT)
            with self.assertRaisesRegex(teams.TeamError, "every team of 1"):
                teams.load_accepted(ctx, [refused_id], root=ROOT)
            with self.assertRaisesRegex(teams.TeamError, "MC999"):  # other faults still stop the load
                teams.load_accepted(ctx, ["A", "MC999"], root=ROOT)
        self.assertEqual(refused, [(refused_id, INVALID)])
        self.assertEqual(pool.ids, ("A", "B"))
        self.assertEqual(pool.sides.tobytes(), alone.sides.tobytes())
        self.assertEqual(pool.sha256, alone.sha256)
        np.testing.assert_array_equal(pool.weights, [1.0, 3.0])

    def test_the_pool_record_names_the_kept_teams_and_every_refusal(self):
        pool = teams.TeamPool.from_setups(("A", "B"), duoforge.reference_setups([0])["sides"][0])
        got = teams.pool_record(pool, [("X", INVALID)])
        import hashlib
        self.assertEqual(got, {"teams": 2, "ids_sha256": hashlib.sha256(b"A\nB").hexdigest(), "refused_count": 1,
                               "refused": [{"id": "X", "status": INVALID}]})

    def test_every_pool_user_filters_by_name(self):
        # The pool users the HauptSession named after #558 (foe_arena, tree_offline, the learn ladder): a pool with a
        # team the engine refuses loads without it, the refusal named; the learn ladder's other callers stay strict.
        from unittest import mock
        from duoforge_learn import checkpoint, ladder as learn_ladder
        from duoforge_search import foe_arena
        refused_id = "LL_6A5E4489937230B102D4026E_110"
        pool_kind = _layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]
        ids = ["A", refused_id, "B"]
        with duoforge.Context(data_kind=pool_kind) as ctx:
            real = teams.load_accepted  # load_pool reads the repository's registry; here the test's root
            with mock.patch.object(teams, "load_accepted", side_effect=lambda c, i: real(c, i, root=ROOT)):
                pool, record = foe_arena.load_pool(ctx, ids)
        self.assertEqual(pool.ids, ("A", "B"))
        self.assertEqual((record["teams"], record["refused"]), (2, [{"id": refused_id, "status": INVALID}]))
        import json
        with open(os.path.join(ROOT, "index.json"), encoding="utf-8") as f:
            sha = {t["id"]: t["sha256"] for t in json.load(f)["teams"]}
        config = {"format": 2, "data": {"kind": "pool"}, "train": {"teams_root": ROOT},
                  "teams": {"ids": ids, "sha256": [sha[t] for t in ids], "weights": [1.0, 2.0, 3.0]}}
        with mock.patch.object(learn_ladder, "_checkpoints", return_value=[(0, "ckpt.npz")]), \
                mock.patch.object(checkpoint, "load", return_value=(None, config)):
            with self.assertRaisesRegex(teams.TeamError, refused_id):  # no list: strict, as before
                learn_ladder._pool_of("run")
            refused = []
            pool, kind = learn_ladder._pool_of("run", refused=refused)
            self.assertEqual((pool.ids, kind), (("A", "B"), pool_kind))
            self.assertEqual(refused, [(refused_id, INVALID)])
            np.testing.assert_array_equal(pool.weights, [1.0, 3.0])
            config["teams"]["sha256"][0] = "0" * 64  # a kept team's file changed since the run
            with self.assertRaisesRegex(SystemExit, "a team file changed"):
                learn_ladder._pool_of("run", refused=[])
        import inspect
        from duoforge_search import arena, book_ab, preview_ab, tree_offline
        for source, needles in ((inspect.getsource(tree_offline.main), ('foe_arena.load_pool(', '"pool": pool_info')),
                                (inspect.getsource(arena.main), ('refused=refused', '"pool": teams.pool_record')),
                                (inspect.getsource(book_ab.main), ('refused=refused', '"pool": teams.pool_record')),
                                (inspect.getsource(preview_ab.main), ('refused=refused', '"pool": teams.pool_record')),
                                (inspect.getsource(foe_arena.main), ('load_pool(', 'report["conditions"]["pool"]')),
                                (inspect.getsource(learn_ladder.main), ('refused=refused', '"pool": teams.pool_record'))):
            for needle in needles:
                self.assertIn(needle, source)

    def test_unknown_id_is_refused(self):
        with duoforge.Context() as ctx, self.assertRaisesRegex(teams.TeamError, "MC999"):
            teams.load(ctx, ["MC999"], root=ROOT)


if __name__ == "__main__":
    unittest.main()
