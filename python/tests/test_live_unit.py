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


class OptionsTest(unittest.TestCase):
    REQUEST = {"active": [{"moves": [{"move": "Electro Shot", "id": "electroshot"}], "trapped": True},
                          {"moves": [{"move": "Protect", "id": "protect", "pp": 8, "maxpp": 8, "target": "self",
                                      "disabled": False}]}],
               "side": {"id": "p1", "pokemon": [
                   {"ident": "p1: Archaludon", "condition": "100/197", "active": True,
                    "moves": ["dragonpulse", "electroshot", "snarl", "protect"]},
                   {"ident": "p1: Farigiraf", "condition": "100/224", "active": True,
                    "moves": ["psychic", "grassknot", "trickroom", "protect"]}]}}

    def test_locked_slot_without_target_raises(self):
        from duoforge_live import options
        roster = {"p1: Archaludon": 2, "p1: Farigiraf": 3}
        lists = options.slot_options(self.REQUEST, 0, roster, {0: 3})
        self.assertEqual([(o.kind, o.move_slot, o.target, o.text) for o in lists[0]], [(1, 1, 3, "move 1")])
        with self.assertRaises(ValueError):
            options.slot_options(self.REQUEST, 0, roster, {})

    def test_unknown_target_type_raises(self):
        import copy
        from duoforge_live import options
        request = copy.deepcopy(self.REQUEST)
        request["active"][1]["moves"][0]["target"] = "somewhereNew"
        with self.assertRaises(ValueError):
            options.slot_options(request, 0, {"p1: Archaludon": 2, "p1: Farigiraf": 3}, {0: 3})


class TrackerRequestTest(unittest.TestCase):
    """The tracker reads a request member's baseAbility (the sheet's or its Mega forme's, which the member view
    shows), not its current ability, which Trace or Skill Swap may have changed; the pin always sends it."""

    @classmethod
    def setUpClass(cls):
        import json
        cls.fixture = json.loads((data.ROOT / "python" / "tests" / "data" / "live_stream_ab.json")
                                 .read_text(encoding="utf-8"))
        cls.data = data.load()

    def feed(self, change):
        """A tracker fed the fixture's messages up to its first request, `change` applied to that request."""
        import json
        from duoforge_live.tracker import Tracker
        tracker = Tracker(self.data, self.fixture["team"])
        for message in self.fixture["messages"]:
            out = []
            for line in message:
                if line.startswith("|request|"):
                    request = json.loads(line[len("|request|"):])
                    change(request["side"]["pokemon"][0])
                    line = "|request|" + json.dumps(request)
                out.append(line)
            tracker.feed(out)
            if tracker.request is not None:
                return tracker
        raise AssertionError("no request in the fixture")

    def test_base_ability_is_read(self):
        def changed(mon):
            self.assertEqual((mon["ident"], mon["baseAbility"]), ("p1: Ceruledge", "flashfire"))
            mon["ability"] = "intimidate"  # as a Trace or a Skill Swap would leave it
        tracker = self.feed(changed)
        member = tracker._own_members[tracker._names[0]["Ceruledge"]]
        self.assertEqual(member.ability, self.data.tables["ABILITY"]["FLASHFIRE"] + 1)

    def test_a_request_without_base_ability_fails(self):
        with self.assertRaisesRegex(ValueError, "without baseAbility"):
            self.feed(lambda mon: mon.pop("baseAbility"))


class TrackerStopTest(unittest.TestCase):
    """Explicit stops of the view-extension folds that the committed battles never reach."""

    @staticmethod
    def tracker():
        from duoforge_live import tracker
        t = tracker.Tracker.__new__(tracker.Tracker)
        t.side, t._spectator = 0, False
        t._positions = [[tracker._Position(), tracker._Position()] for _ in (0, 1)]
        for side in t._positions:
            for k, p in enumerate(side):
                p.occupant = k
        return t

    def test_throat_chop_takes_only_the_pins_silent_form(self):
        from duoforge_live import lines
        t = self.tracker()
        t._throat_chop("|-start|p2a: Salamence|Throat Chop|[silent]".split("|"))
        self.assertEqual(t._positions[1][0].throat_chop, 1)
        t._throat_chop("|-end|p2a: Salamence|Throat Chop|[silent]".split("|"))
        self.assertEqual(t._positions[1][0].throat_chop, 0)
        for line in ("|-start|p2a: Salamence|Throat Chop", "|-start|p2a: Salamence|Throat Chop|[silent]|[of] p1a: X",
                     "|-end|p2: Salamence|Throat Chop|[silent]"):
            with self.assertRaises(lines.Stop, msg=line) as caught:
                t._throat_chop(line.split("|"))
            self.assertEqual(caught.exception.reason, f"line:{line.split('|')[1]} Throat Chop")

    def test_encore_takes_the_slot_of_the_last_move_line(self):
        from duoforge_live import lines
        from duoforge_live.data import trace_to_c
        t = self.tracker()
        start, end = (trace_to_c.ev_tuple(trace_to_c.EV[k], 2, detail=trace_to_c.VOLATILE_ENCORE)
                      for k in ("VOLATILE_START", "VOLATILE_END"))
        p = t._positions[1][0]
        p.last_slot = 3
        t._event(start)
        self.assertEqual(p.encore_slot, 3)
        t._event(end)
        self.assertEqual(p.encore_slot, 0)
        for last in (0, 5, None):  # no move line yet, Struggle, a move not on the sheet
            p.last_slot = last
            with self.assertRaises(lines.Stop, msg=last) as caught:
                t._event(start)
            self.assertEqual(caught.exception.reason, "encore-slot-unknown")



class _TablesData:
    """The converter's pool tables without the library: what the tracker reads of its data (the tables, pp_max and
    mega_capable of a member)."""
    kind = "pool"

    def __init__(self):
        from duoforge_live.data import trace_to_c
        self.tables = trace_to_c.load_tables(str(data.ROOT), True)

    def pp_max(self, move):
        return 5

    def mega_capable(self, species, item):
        return False


class LastResortUsedTest(unittest.TestCase):
    """Step G94 (decision 0061): the used bits of Last Resort's four move slots, per position (volatiles2 bits 0 to 3,
    slot k at bit k-1). The bit of slot k is set by the occupant's own move line of slot k: deductPP sets the flag before
    TryMove, so a move that fails still counts; a locked turn deducts no PP; a Magic Bounce reflection (cause ABILITY) is
    no use of its holder. The bits end with the occupant (a switch-in, a faint). The view shows them only for an occupant
    with Last Resort on its sheet; the state keeps them for every occupant."""

    def setUp(self):
        from duoforge_live import tracker
        from duoforge_live.data import trace_to_c
        self.tracker, self.trace_to_c = tracker, trace_to_c
        self.D = _TablesData()
        self.M = self.D.tables["MOVE"]
        holder = {"species": 1, "item": 0, "ability": 0, "gender": "", "nature": 0, "sp": [0] * 6,
                  "moves": [self.M["LASTRESORT"], self.M["DOUBLEEDGE"], self.M["PROTECT"], self.M["EARTHQUAKE"]]}
        plain = dict(holder, moves=[self.M["DOUBLEEDGE"], self.M["PROTECT"], self.M["EARTHQUAKE"]])
        t = tracker.Tracker.__new__(tracker.Tracker)
        t.data, t.side, t._spectator, t.epoch = self.D, 0, False, 1
        t.request = {"rqid": 1}
        t._guard_moves, t._choice_items, t._pressure = set(), set(), None
        t._struggle, t._baton_pass, t._last_move = self.M["STRUGGLE"], -1, None
        t._conditions = [[0] * 4, [0] * 4]
        t._names = [{}, {}]
        t._positions = [[tracker._Position(), tracker._Position()] for _ in (0, 1)]
        t._own_members = [tracker._Member(s, self.D) for s in (holder, plain)]
        t._foe_members = [tracker._Member(s, self.D) for s in (holder, plain)]
        for side in t._positions:
            side[0].occupant, side[1].occupant = 0, 1
        self.t = t

    def move(self, pos, name, cause=0, flags=0):
        tt = self.trace_to_c
        self.t._event(tt.ev_tuple(tt.EV["MOVE"], pos, tt.NOPOS, cause, self.M[name], flags=flags))

    def used(self, pos):
        return self.t._positions[pos // 2][pos % 2].used

    def shown(self):
        """volatiles2 as the view extension holds it: [own slot 0, own slot 1] and [foe slot 0, foe slot 1]."""
        return self.t.observation_ext()["volatiles2"].tolist()

    def test_a_holder_shows_the_slots_its_moves_used(self):
        self.move(0, "PROTECT")  # slot 3
        self.move(0, "EARTHQUAKE")  # slot 4
        self.assertEqual(self.shown()[0][0], 0b1100)

    def test_a_move_that_fails_still_uses_its_slot(self):
        self.move(0, "LASTRESORT", flags=self.trace_to_c.FLAG["STILL"])  # deductPP runs before TryMove
        self.assertEqual(self.shown()[0][0], 0b0001)

    def test_a_locked_turn_deducts_no_pp_and_sets_no_bit(self):
        self.move(0, "DOUBLEEDGE", flags=self.trace_to_c.FLAG["LOCKED"])
        self.assertEqual(self.used(0), 0)
        self.move(0, "DOUBLEEDGE")
        self.assertEqual(self.used(0), 0b0010)

    def test_a_magic_bounce_reflection_is_no_use_of_its_holder(self):
        self.move(0, "PROTECT", cause=self.trace_to_c.CAUSE["ABILITY"])
        self.assertEqual(self.used(0), 0)
        self.assertEqual(self.shown()[0][0], 0)

    def test_a_foe_holder_shows_its_slots(self):
        self.move(2, "PROTECT")
        self.assertEqual(self.shown(), [[0, 0], [0b0100, 0]])

    def test_a_non_holder_keeps_its_bits_but_shows_none(self):
        self.move(1, "PROTECT")  # the plain sheet has no Last Resort: PROTECT is its second move
        self.assertEqual(self.used(1), 0b0010)
        self.assertEqual(self.shown()[0][1], 0)

    def test_a_switch_in_clears_the_slots(self):
        tt = self.trace_to_c
        self.move(0, "PROTECT")
        self.t._event(tt.ev_tuple(tt.EV["SWITCH"], 0, tt.NOPOS, 0, 1, 0, 100, 100, 1))  # the plain member comes in
        self.assertEqual((self.used(0), self.shown()[0][0]), (0, 0))
        self.move(0, "PROTECT")
        self.t._event(tt.ev_tuple(tt.EV["SWITCH"], 0, tt.NOPOS, 0, 0, 0, 100, 100, 1))  # the holder comes back
        self.assertEqual((self.used(0), self.shown()[0][0]), (0, 0))

    def test_a_faint_clears_the_slots_and_keeps_the_occupant(self):
        tt = self.trace_to_c
        self.move(2, "PROTECT")
        self.t._event(tt.ev_tuple(tt.EV["FAINT"], 2))  # the tail ends with the faint (dfi_process_faints)
        self.assertEqual((self.t._positions[1][0].occupant, self.used(2), self.shown()[1][0]), (0, 0, 0))

    def test_struggle_uses_no_slot(self):
        self.move(0, "STRUGGLE")
        self.assertEqual(self.used(0), 0)

    def test_a_move_off_the_sheet_stops(self):
        from duoforge_live import lines
        with self.assertRaises(lines.Stop) as caught:
            self.move(0, "ICEBEAM")
        self.assertTrue(caught.exception.reason.startswith("structure:"), caught.exception.reason)

    def test_a_cant_nopp_line_stops(self):
        from types import SimpleNamespace
        from duoforge_live import lines
        with self.assertRaises(lines.Stop):
            lines.check("|cant|p1a: Holder|nopp|Last Resort", SimpleNamespace(data=self.D))

    def test_an_ally_switch_stops(self):
        from types import SimpleNamespace
        from duoforge_live import lines
        with self.assertRaises(lines.Stop):
            lines.check("|move|p1a: Holder|Ally Switch||", SimpleNamespace(data=self.D))

    def test_restrict_ext_keeps_the_slot_bits(self):
        from duoforge_live import lines
        self.move(0, "PROTECT")
        kept = self.tracker.restrict_ext(self.t.observation_ext(), 1 << lines.FEATURES["LAST_RESORT_USED"])
        self.assertEqual(kept["volatiles2"].tolist(), [[0b0100, 0], [0, 0]])


if __name__ == "__main__":
    unittest.main()
