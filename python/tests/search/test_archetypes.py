"""The archetype tag table (issue #458) read against the engine: its shape, its ids, the weather setters and Mega Stones
taken from the engine's data, and the tags of team sheets."""
import copy
import json
import os
import tempfile
import unittest

import duoforge
from duoforge import _layout, teams
from duoforge_live.data import ROOT
from duoforge_search import archetypes

C = _layout.CONSTANTS


def member(species="Pikachu", ability="Static", item=None, moves=("Thunderbolt",)):
    return {"species": species, "ability": ability, "item": item, "moves": list(moves)}


class TableShapeTest(unittest.TestCase):
    def write(self, tmp, table):
        path = os.path.join(tmp, "tags.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(table, f)
        return path

    def base(self):
        return archetypes.load()

    def assertRefused(self, pattern, table):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(archetypes.TagError, pattern):
                archetypes.load(self.write(tmp, table))

    def test_the_committed_table_loads(self):
        table = archetypes.load()
        self.assertEqual(table["format"], archetypes.FORMAT)
        self.assertTrue(table["credits"])

    def test_unknown_family_is_refused(self):
        t = self.base()
        t["tags"]["zzz:x"] = {"moves": ["tailwind"]}
        self.assertRefused("unknown family", t)

    def test_unsorted_ids_are_refused(self):
        t = self.base()
        t["tags"]["setup"]["moves"] = ["swordsdance", "nastyplot"]
        self.assertRefused("sorted list", t)

    def test_a_setter_only_on_a_weather_tag(self):
        t = self.base()
        t["tags"]["setup"]["setter"] = "sun"
        self.assertRefused("setter", t)
        t = self.base()
        t["tags"]["weather:sun"]["setter"] = "fog"
        self.assertRefused("setter", t)

    def test_an_empty_tag_is_refused(self):
        t = self.base()
        t["tags"]["support:x"] = {}
        t["tags"] = dict(sorted(t["tags"].items()))
        self.assertRefused("names nothing", t)

    def test_unknown_fields_and_format_are_refused(self):
        t = self.base()
        t["tags"]["setup"]["species"] = ["pikachu"]
        self.assertRefused("unknown fields", t)
        t = self.base()
        t["format"] = 2
        self.assertRefused("format", t)


class EngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"])
        cls.table = archetypes.load()
        cls.resolved = archetypes.resolve(cls.ctx, cls.table)

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()

    def test_unknown_or_unsupported_ids_are_named(self):
        t = copy.deepcopy(self.table)
        t["tags"]["setup"]["moves"] = sorted(t["tags"]["setup"]["moves"] + ["notamove", "tidyup"])
        with self.assertRaisesRegex(archetypes.TagError, "notamove.*unknown.*tidyup.*not supported"):
            archetypes.resolve(self.ctx, t)

    def test_the_setters_are_the_engines(self):
        from duoforge import data
        drought = data.find(self.ctx, data.TABLE_ABILITY, "drought")
        drizzle = data.find(self.ctx, data.TABLE_ABILITY, "drizzle")
        self.assertEqual(self.resolved["abilities"][drought], ["weather:sun"])
        self.assertEqual(self.resolved["abilities"][drizzle], ["weather:rain"])

    def test_a_mega_stone_gives_its_mega_formes_ability_tags(self):
        y = archetypes.member_tags(self.ctx, self.resolved, member("Charizard", "Blaze", "Charizardite Y", ["Protect"]))
        x = archetypes.member_tags(self.ctx, self.resolved, member("Charizard", "Blaze", "Charizardite X", ["Protect"]))
        self.assertEqual(y, ["weather:sun"])
        self.assertEqual(x, [])

    def test_a_mega_stone_of_another_species_gives_no_mega_tags(self):
        tags = archetypes.member_tags(self.ctx, self.resolved,
                                      member("Venusaur", "Overgrow", "Charizardite Y", ["Protect"]))
        self.assertEqual(tags, [])

    def test_the_own_ability_counts_beside_the_mega_ability(self):
        tags = archetypes.member_tags(self.ctx, self.resolved,
                                      member("Staraptor", "Intimidate", "Staraptite", ["Tailwind"]))
        self.assertEqual(tags, ["speed:tailwind", "support:intimidate"])

    def test_an_unknown_name_is_refused(self):
        with self.assertRaisesRegex(archetypes.TagError, "no move 'Not A Move'"):
            archetypes.member_tags(self.ctx, self.resolved, member(moves=["Not A Move"]))

    def test_team_a(self):
        members = teams.parse((ROOT / "data/teams/A.txt").read_text(encoding="utf-8"), "A")
        out = archetypes.team_tags(self.ctx, self.resolved, members)
        self.assertEqual(out["team"], ["setup", "speed:tailwind", "support:fake_out", "support:intimidate",
                                       "support:redirection", "support:sleep"])
        self.assertEqual(len(out["members"]), 6)

    def test_an_untagged_team_has_an_empty_union(self):
        out = archetypes.team_tags(self.ctx, self.resolved, [member(moves=["Thunderbolt"])])
        self.assertEqual(out["team"], [])


if __name__ == "__main__":
    unittest.main()
