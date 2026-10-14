"""The Smogon dex's VGC sets (issue #458) as committed facts, and the archetype tags checked against their named roles.

A set whose name names a role (ROLE_WORDS) must get one of the role's tags from the tag table, over all of the set's
listed alternatives. The role words are Smogon's set names, so this checks the tag table against a source that did
not write it; a set the engine cannot read is named in the refusal, never skipped."""
import json
import os
import tempfile
import unittest

import duoforge
from duoforge import _layout
from duoforge_live.data import ROOT
from duoforge_search import archetypes, smogon_dex

C = _layout.CONSTANTS
# A word of a Smogon set name, and the tags of which the set must have at least one.
ROLE_WORDS = {
    "Rain": {"weather:rain", "weather:rain_abuser"},
    "Sun": {"weather:sun", "weather:sun_abuser"},
    "Chlorophyll": {"weather:sun_abuser"},
    "Sand": {"weather:sand", "weather:sand_abuser"},
    "Snow": {"weather:snow", "weather:snow_abuser"},
    # "Trick Room Attacker" and "Trick Room Sweeper" name slow attackers for a team that sets Trick Room, not setters.
    "Trick Room Support": {"speed:trick_room"},
    "Trick Room Setter": {"speed:trick_room"},
    "Tailwind": {"speed:tailwind"},
    "Redirection": {"support:redirection"},
    "Fake Out": {"support:fake_out"},
    "Setup": {"setup"},
    "Prankster": {"support:screens", "speed:tailwind", "speed:paralysis"},
    "Screens": {"support:screens"},
    "Aurora Veil": {"support:screens"},
}


def page(sets_by_format, formes=()):
    """A minimal cached page: dexSettings with one dump-pokemon call."""
    def strategies(by_format):
        return [{"format": fmt, "overview": "TEXT", "comments": "TEXT",
                 "movesets": [{"name": name, "pokemon": "Pikachu", "description": "ANALYSIS TEXT",
                               "items": ["Light Ball"], "abilities": ["Static"],
                               "moveslots": [[{"move": "Fake Out", "type": None}], [{"move": "Protect", "type": None},
                                                                                    {"move": "Detect", "type": None}]],
                               "evconfigs": [{"hp": 2, "atk": 0, "def": 0, "spa": 32, "spd": 0, "spe": 32}],
                               "natures": ["Timid"]} for name in names]} for fmt, names in by_format.items()]
    dump = {"strategies": strategies(sets_by_format),
            "formeStrategies": [{"formeName": f, "forme": "x", "strategies": strategies(s)} for f, s in formes]}
    settings = {"injectRpcs": [['["dump-gens",{}]', []], ['["dump-pokemon",{"alias":"pikachu"}]', dump]]}
    return "<script>dexSettings = " + json.dumps(settings) + "\n</script>"


class PageTest(unittest.TestCase):
    def test_only_the_vgc_formats_and_no_analysis_text(self):
        text = page({"OU": ["Singles"], "VGC26 Regulation M-B": ["Fast Support"]},
                    formes=[("Pikachu-Mega", {"VGC26 Regulation M-A": ["Mega Set"]})])
        sets = smogon_dex.page_sets(text, "pikachu")
        self.assertEqual([(s["forme"], s["format"], s["name"]) for s in sets],
                         [(None, "VGC26 Regulation M-B", "Fast Support"),
                          ("Pikachu-Mega", "VGC26 Regulation M-A", "Mega Set")])
        self.assertEqual(sets[0]["moves"], [["Fake Out"], ["Protect", "Detect"]])
        self.assertEqual(sets[0]["stat_points"], [[2, 0, 0, 32, 0, 32]])
        self.assertNotIn("TEXT", json.dumps(sets))

    def test_a_page_without_its_data_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no dexSettings"):
            smogon_dex.page_sets("<html></html>", "pikachu")

    def test_build_and_render_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            for slug in ("pikachu", "raichu"):
                with open(os.path.join(tmp, f"{slug}.html"), "w", encoding="utf-8") as f:
                    f.write(page({"VGC26 Regulation M-B": [slug]}))
            table = smogon_dex.build(tmp)
            self.assertEqual(table["slugs"], ["pikachu", "raichu"])
            self.assertEqual(json.loads(smogon_dex.render(table)), table)

    def test_a_cache_inside_the_repository_is_refused(self):
        with self.assertRaisesRegex(SystemExit, "inside the repository"):
            smogon_dex.main(["--cache", str(ROOT / "data")])


class CommittedTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(smogon_dex.TABLE_PATH, encoding="utf-8") as f:
            cls.text = f.read()
        cls.table = json.loads(cls.text)
        cls.ctx = duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"])
        cls.resolved = archetypes.resolve(cls.ctx, archetypes.load())

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()

    def test_credits_and_canonical_text(self):
        self.assertEqual(self.table["credits"], smogon_dex.CREDIT)
        self.assertEqual(smogon_dex.render(self.table), self.text)
        self.assertTrue(all(s["format"] in smogon_dex.FORMATS for s in self.table["sets"]))
        for s in self.table["sets"]:
            self.assertEqual(set(s), {"slug", "forme", "species", "format", "name", "items", "abilities", "moves",
                                      "natures", "stat_points"})

    def set_tags(self, s):
        """The union of the tags over every listed alternative of one set; TagError for a name the engine lacks."""
        tags = set()
        for ability in s["abilities"]:
            for item in [None if x == "No Item" else x for x in s["items"]] or [None]:  # Smogon: "No Item"
                member = {"species": s["species"], "ability": ability, "item": item,
                          "moves": [m for slot in s["moves"] for m in slot]}
                tags.update(archetypes.member_tags(self.ctx, self.resolved, member))
        return tags

    def test_every_named_role_gets_its_tag(self):
        missing, refused = [], []
        for s in self.table["sets"]:
            words = [w for w in ROLE_WORDS if w.lower() in s["name"].lower()]
            if not words:
                continue
            try:
                tags = self.set_tags(s)
            except archetypes.TagError as err:
                refused.append(f"{s['species']} '{s['name']}' ({s['format']}): {err}")
                continue
            for w in words:
                if not tags & ROLE_WORDS[w]:
                    missing.append(f"{s['species']} '{s['name']}' ({s['format']}): no tag of {sorted(ROLE_WORDS[w])}")
        self.assertEqual(refused, [])
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
