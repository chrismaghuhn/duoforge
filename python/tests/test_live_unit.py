"""duoforge.python.live_unit: the Showdown live adapter without Node.

Teams (packing, the open team sheets, the match against Team A and B) and
the data the adapter reads from the converter's tables, checked against the
library.
"""
import random
import unittest

from duoforge_live import data, teams

# The |showteam| payload of Team A as the pinned Showdown sends it at team
# preview (open team sheets: no names, no EVs), from ps_client.js on
# m5_real_ab_1, whose team lists the members in another order.
SHOWTEAM_A = ("Ceruledge||GrassySeed|FlashFire|BitterBlade,ShadowSneak,SwordsDance,Protect|Adamant||M|||50|]"
              "Gholdengo||LifeOrb|GoodasGold|MakeItRain,ShadowBall,NastyPlot,Protect|Modest|||||50|]"
              "Milotic||SitrusBerry|Competitive|MuddyWater,Coil,IceBeam,Hypnosis|Calm||F|||50|]"
              "Staraptor||Staraptite|Intimidate|BraveBird,CloseCombat,Tailwind,Protect|Jolly||F|||50|]"
              "Raichu||RaichuniteY|LightningRod|ZapCannon,FocusBlast,FakeOut,Protect|Timid||F|||50|]"
              "Rillaboom||MiracleSeed|GrassySurge|WoodHammer,GrassyGlide,FakeOut,HighHorsepower|Adamant||M|||50|")
# Team B's, from the same battle.
SHOWTEAM_B = ("Grimmsnarl||LightClay|Prankster|SpiritBreak,Reflect,LightScreen,PartingShot|Sassy||M|||50|]"
              "Farigiraf||SitrusBerry|ArmorTail|Psychic,GrassKnot,TrickRoom,Protect|Bold||F|||50|]"
              "Politoed||MysticWater|Drizzle|WeatherBall,MuddyWater,IceBeam,Protect|Modest||M|||50|]"
              "Golisopod||Golisopite|EmergencyExit|LeechLife,IronHead,DrillRun,Protect|Adamant||F|||50|]"
              "Archaludon||Leftovers|Stamina|DragonPulse,ElectroShot,Snarl,Protect|Bold||M|||50|]"
              "Charizard||CharizarditeY|Blaze|HeatWave,WeatherBall,Hurricane,Protect|Timid||M|||50|")


class TeamsTest(unittest.TestCase):
    def test_pack_unpack_round_trip(self):
        for name in ("A", "B"):
            packed = teams.pack(teams.text(name))
            self.assertEqual(teams.pack(teams.to_text(teams.unpack(packed))), packed, name)

    def test_showteam_line_unpacks(self):
        sets = teams.unpack(SHOWTEAM_A)
        self.assertEqual([s["species"] for s in sets],
                         ["Ceruledge", "Gholdengo", "Milotic", "Staraptor", "Raichu", "Rillaboom"])
        first = sets[0]
        self.assertEqual((first["item"], first["ability"], first["nature"], first["gender"], first["level"]),
                         ("GrassySeed", "FlashFire", "Adamant", "M", 50))
        self.assertEqual(first["moves"], ["BitterBlade", "ShadowSneak", "SwordsDance", "Protect"])
        self.assertEqual(first["evs"], [0] * 6)
        self.assertEqual(sets[1]["gender"], "")  # Gholdengo is genderless

    def test_match(self):
        a = teams.unpack(SHOWTEAM_A)
        self.assertTrue(teams.match(a, teams.text("A")))
        self.assertTrue(teams.match(teams.unpack(SHOWTEAM_B), teams.text("B")))
        self.assertFalse(teams.match(teams.unpack(SHOWTEAM_B), teams.text("A")))
        shuffled = [dict(s, moves=list(reversed(s["moves"]))) for s in a]
        random.Random(1).shuffle(shuffled)
        self.assertTrue(teams.match(shuffled, teams.text("A")))
        for field, value in (("species", "Pikachu"), ("item", "Leftovers"), ("ability", "Blaze"),
                             ("nature", "Bold"), ("gender", "F"), ("level", 100)):
            changed = [dict(s) for s in a]
            changed[0][field] = value
            self.assertFalse(teams.match(changed, teams.text("A")), field)
        changed = [dict(s) for s in a]
        changed[0]["moves"] = ["BitterBlade", "ShadowSneak", "SwordsDance", "Tailwind"]
        self.assertFalse(teams.match(changed, teams.text("A")))
        self.assertFalse(teams.match(a, teams.text("B")))
        self.assertFalse(teams.match(a[:5], teams.text("A")))


    def test_unsupported_input_raises(self):
        with self.assertRaises(ValueError):
            teams.pack("Leafy (Rillaboom) (M) @ Miracle Seed\nAbility: Grassy Surge\nLevel: 50\nAdamant Nature\n"
                       "- Protect")  # a nickname: Showdown packs it apart from the species; the paste reader does not
        with self.assertRaises(ValueError):
            teams.unpack(SHOWTEAM_A.split("]")[0].rsplit("|", 1)[0])  # eleven fields, not twelve


class DataTest(unittest.TestCase):
    def test_data_equals_the_library(self):
        import duoforge
        d = data.load()
        context = duoforge.Context()
        batch = duoforge.Batch(context, duoforge.reference_setups([0]), 1, 1)  # Team A (side 0) against Team B
        try:
            batch.query_factored()
            for side, name in ((0, "A"), (1, "B")):
                view = batch.observations[0, side]["sides"][side]["members"]
                for m, mon in enumerate(d.team(teams.text(name))):
                    v = view[m]
                    count = len(mon["moves"])
                    where = (name, m)
                    self.assertEqual(int(v["species_id"]), mon["species"], where)
                    self.assertEqual([int(x) for x in v["move_ids"][:count]], mon["moves"], where)
                    self.assertEqual([int(x) for x in v["pp_max"][:count]], [d.pp_max(x) for x in mon["moves"]], where)
                    self.assertEqual(bool(v["mega_capable"]), d.mega_capable(mon["species"], mon["item"]), where)
                    self.assertEqual((int(v["ability"]), int(v["item"]), int(v["gender"]), int(v["nature"])),
                                     (mon["ability"], mon["item"], mon["gender"], mon["nature"]), where)
                    self.assertEqual(int(v["ability"]), d.ability_of(mon["species"]), where)
                    mega = d.mega_forme(mon["species"])
                    if mega is not None:
                        self.assertEqual(d.base_forme(mega), mon["species"], where)
        finally:
            batch.close()
            context.close()

    def test_unknown_names_raise(self):
        d = data.load()
        with self.assertRaises(ValueError):
            d.forme("Pikachu")
        self.assertEqual(d.forme("Charizard-Mega-Y"), d.mega_forme(d.forme("Charizard")))


if __name__ == "__main__":
    unittest.main()
