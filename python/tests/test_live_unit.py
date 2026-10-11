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

    def test_recharge_request(self):
        # mustrecharge (step G17): the pin's request offers only Recharge, trapped: the engine's RECHARGE slot command
        import copy
        from duoforge_live import options
        request = copy.deepcopy(self.REQUEST)
        request["active"][0] = {"moves": [{"move": "Recharge", "id": "recharge"}], "trapped": True}
        lists = options.slot_options(request, 0, {"p1: Archaludon": 2, "p1: Farigiraf": 3}, {})
        self.assertEqual([(o.kind, o.move_slot, o.target, o.text) for o in lists[0]],
                         [(options.MOVE, options.RECHARGE, options.TARGET_NONE, "move 1")])

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

    def test_the_record_refuses_folds_it_does_not_write(self):
        # record.py writes the tail of the #334 folds (Throat Chop, Perish, Encore, Aurora Veil, item_now, ability_now);
        # a #342 fold that is up has tail fields the assembler does not write yet, so the point is refused, never a zero
        import collections
        from duoforge_live import record
        t = self.tracker()
        t._hazards = [collections.Counter(), collections.Counter()]
        t._guards = set()
        t._positions[0][0].throat_chop, t._positions[1][1].perish = 2, 3  # recorded folds: no refusal
        self.assertEqual(record.unrecorded_folds(t), [])
        t._positions[1][0].taunt, t._positions[0][1].type_now = 1, (18, 0)
        t._hazards[1]["spikes"] = 2
        t._guards.add(("WIDE_GUARD", 0))
        self.assertEqual(sorted(record.unrecorded_folds(t)),
                         ["side0.position1.type_now", "side0.wide_guard", "side1.hazards", "side1.position0.taunt"])
        with self.assertRaises(record.Refusal) as caught:
            record._tail(t, None, 2)
        self.assertEqual(caught.exception.reason, "fold-not-in-record")

    def test_throat_chop_takes_only_the_pins_silent_form(self):
        from duoforge_live import lines
        t = self.tracker()
        t._throat_chop("|-start|p2a: Salamence|Throat Chop|[silent]".split("|"))
        from duoforge_live.tracker import THROAT_CHOP_TURNS
        self.assertEqual(t._positions[1][0].throat_chop, THROAT_CHOP_TURNS)  # its turns (the record's count)
        t._throat_chop("|-end|p2a: Salamence|Throat Chop|[silent]".split("|"))
        self.assertEqual(t._positions[1][0].throat_chop, 0)
        for line in ("|-start|p2a: Salamence|Throat Chop", "|-start|p2a: Salamence|Throat Chop|[silent]|[of] p1a: X",
                     "|-end|p2: Salamence|Throat Chop|[silent]"):
            with self.assertRaises(lines.Stop, msg=line) as caught:
                t._throat_chop(line.split("|"))
            self.assertEqual(caught.exception.reason, f"line:{line.split('|')[1]} Throat Chop")

    def test_baton_pass_gives_the_copied_volatiles(self):
        # dfi_pass_give (src/combat/turn.c): Throat Chop's, Perish Song's, Taunt's and Heal Block's counters go to the
        # entering member; Encore, Disable, Yawn, Imprison, Glaive Rush (noCopy), the recharge and a changed type stay
        # with the leaver (decision 0042)
        from duoforge_live.data import trace_to_c
        passed = {"throat_chop": 1, "perish": 2, "taunt": 1, "heal_block": 1}
        kept = {"encore_slot": 3, "disable_slot": 2, "yawn": 1, "imprison": 1, "glaive_rush": 1, "must_recharge": 1,
                "type_now": (18, 0)}
        empty = {"encore_slot": 0, "disable_slot": 0, "yawn": 0, "imprison": 0, "glaive_rush": 0, "must_recharge": 0,
                 "type_now": (0, 0)}
        from types import SimpleNamespace
        from duoforge_live.tracker import ROSTER_NONE
        t = self.tracker()
        t._baton_pass = 7
        # the entry bookkeeping of the public record (#344): activation ids, the foe's leads, the own party order, the
        # members' toxic stage; the spectator path, so the own member's display comes from the line
        t._spectator, t._next_activation, t._foe_leads, t._party = True, 1, [ROSTER_NONE, ROSTER_NONE], None
        members = [SimpleNamespace(toxic_stage=0, seen=False, hp_percent=0, hp_flag=0, status=0) for _ in range(6)]
        t._member = lambda side: members
        p = t._positions[0][0]
        for name, value in {**passed, **kept}.items():
            setattr(p, name, value)
        t._event(trace_to_c.ev_tuple(trace_to_c.EV["SWITCH"], 0, trace_to_c.NOPOS, trace_to_c.CAUSE["MOVE"], 4, 7))
        self.assertEqual(p.occupant, 4)
        self.assertEqual({name: getattr(p, name) for name in passed}, passed)
        self.assertEqual({name: getattr(p, name) for name in kept}, empty)
        t._event(trace_to_c.ev_tuple(trace_to_c.EV["SWITCH"], 0, trace_to_c.NOPOS, 0, 5, 0))  # a plain switch
        self.assertEqual((p.occupant, p.throat_chop, p.perish, p.taunt, p.heal_block), (5, 0, 0, 0, 0))

    def test_a_plain_typechange_is_soaks_only_after_a_soak_line(self):
        # Soak and Magic Powder print the same -start|X|typechange|T (no attribute): the converter gives Soak's cause to
        # both, so the tracker folds it only after a Soak move line; after Magic Powder it stops
        from duoforge_live import lines
        from duoforge_live.data import trace_to_c
        moves = data.load(kind="pool").tables["MOVE"]
        t = self.tracker()
        t._soak = moves["SOAK"]
        water, psychic = trace_to_c.TYPE_IDS["Water"], trace_to_c.TYPE_IDS["Psychic"]

        def typechange(type_id):
            return trace_to_c.ev_tuple(trace_to_c.EV["TYPE_CHANGE"], 2, trace_to_c.NOPOS, trace_to_c.CAUSE["MOVE"], 0,
                                       moves["SOAK"], detail=type_id)
        t._last_move = (0, moves["MAGICPOWDER"], 2)
        with self.assertRaises(lines.Stop) as caught:
            t._event(typechange(psychic))
        self.assertEqual(caught.exception.reason, "line:-start typechange (no Soak)")
        self.assertEqual(t._positions[1][0].type_now, (0, 0))
        t._last_move = (0, moves["SOAK"], 2)
        t._event(typechange(water))
        self.assertEqual(t._positions[1][0].type_now, (water + 1, 0))

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


class TrackerPartialTrapTest(unittest.TestCase):
    """Step G90 (decision 0060): the partial trap of Bind, Wrap, Fire Spin, Sand Tomb and Infestation, folded
    from the three public line forms exactly as the engine keeps it per position: the source (flat position + 1, 0 once
    the source left), the move, the Binding Band of the start and the elapsed count (TRAP_ELAPSED: 0 at the start, +1 at
    each residual damage line, 0 at the end and when the trapped Pokemon leaves). The drawn turns are never known."""

    @classmethod
    def setUpClass(cls):
        from duoforge_live import tracker
        cls.tracker, cls.D = tracker, data.load(kind="pool")
        cls.M, cls.I = cls.D.tables["MOVE"], cls.D.tables["ITEM"]

    def setUp(self):
        from types import SimpleNamespace
        tr, D = self.tracker, self.D
        t = tr.Tracker.__new__(tr.Tracker)
        t.data, t.side, t._spectator = D, 0, True  # the spectator path: every display comes from its line
        t._baton_pass = self.M["BATONPASS"]
        t._trap_moves = {self.M[k] for k in ("BIND", "WRAP", "FIRESPIN", "SANDTOMB", "INFESTATION")}
        t._next_activation, t._foe_leads, t._party, t._after_upkeep = 1, [tr.ROSTER_NONE] * 2, None, False
        band = self.I["BINDINGBAND"] + 1
        # side 0 member 0 and side 1 member 1 hold the band: the occupants of flat positions 0 and 3
        self.members = [[SimpleNamespace(sheet={"item": band if (s, m) in ((0, 0), (1, 1)) else 0}, item_used=0,
                                         item_now=0, toxic_stage=0, seen=False, hp_percent=0, hp_flag=0, status=0,
                                         revealed=0) for m in range(6)] for s in (0, 1)]
        t._member = lambda side: self.members[side]
        t._positions = [[tr._Position(), tr._Position()] for _ in (0, 1)]
        for side in t._positions:
            for k, p in enumerate(side):
                p.occupant = k
        self.t = t

    def trap(self, flat):
        p = self.t._positions[flat // 2][flat % 2]
        return (p.trap, p.trap_source, p.trap_move, p.trap_band, p.trap_elapsed)

    def start(self, target, source, move):
        from duoforge_live.data import trace_to_c
        self.t._event(trace_to_c.ev_tuple(trace_to_c.EV["ACTIVATE"], target, source, trace_to_c.CAUSE["MOVE"], 0,
                                          self.M[move.upper().replace(" ", "")]))

    def end(self, target, move):
        from duoforge_live.data import trace_to_c
        self.t._event(trace_to_c.ev_tuple(trace_to_c.EV["VOLATILE_END"], target, detail=trace_to_c.VOLATILE_PARTIAL_TRAP,
                                          ident=self.M[move.upper().replace(" ", "")]))

    def leave(self, flat, kind="SWITCH", cause=0, id2=0):
        from duoforge_live.data import trace_to_c
        if kind == "FAINT":
            self.t._event(trace_to_c.ev_tuple(trace_to_c.EV["FAINT"], flat))
        else:
            self.t._event(trace_to_c.ev_tuple(trace_to_c.EV[kind], flat, trace_to_c.NOPOS, cause, 4, id2, 100, 100, 1))

    def residual(self, flat, move, hp="83/100"):
        ident = "p%d%s: Mon" % (flat // 2 + 1, "ab"[flat % 2])
        self.t._trap_residual(f"|-damage|{ident}|{hp}|[from] move: {move}|[partiallytrapped]".split("|"))

    def test_the_start_sets_source_move_band_and_a_zero_count(self):
        self.start(2, 0, "Bind")  # p1a (holds the band) traps p2a
        self.assertEqual(self.trap(2), (1, 1, self.M["BIND"] + 1, 1, 0))
        self.start(1, 3, "Wrap")  # p2b (holds the band) traps p1b
        self.assertEqual(self.trap(1), (1, 4, self.M["WRAP"] + 1, 1, 0))
        self.start(3, 1, "Infestation")  # p1b holds nothing
        self.assertEqual(self.trap(3), (1, 2, self.M["INFESTATION"] + 1, 0, 0))
        self.assertEqual(self.trap(0), (0, 0, 0, 0, 0))
        # the band is the source's held item as far as the lines showed: one seen used up or taken is not held
        self.members[1][1].item_used = 1
        self.start(0, 3, "Fire Spin")
        self.assertEqual(self.trap(0), (1, 4, self.M["FIRESPIN"] + 1, 0, 0))

    def test_a_start_on_a_trapped_target_is_a_stop(self):
        from duoforge_live import lines
        self.start(2, 0, "Bind")
        with self.assertRaises(lines.Stop) as caught:
            self.start(2, 1, "Wrap")  # the engine refuses it with no line, so no line can show it
        self.assertEqual(caught.exception.reason, "trap-start-on-trapped")
        self.assertEqual(self.trap(2), (1, 1, self.M["BIND"] + 1, 1, 0))

    def test_a_start_from_an_empty_or_own_position_is_a_stop(self):
        from duoforge_live import lines
        for source in (2, self.tracker.NOPOS):
            with self.assertRaises(lines.Stop, msg=source) as caught:
                self.start(2, source, "Bind")
            self.assertEqual(caught.exception.reason, "trap-start-source")
        self.t._positions[0][0].occupant = self.tracker.ROSTER_NONE
        with self.assertRaises(lines.Stop) as caught:
            self.start(2, 0, "Bind")
        self.assertEqual(caught.exception.reason, "trap-start-source")

    def test_each_residual_damage_line_counts_one(self):
        self.start(2, 0, "Bind")
        for n in range(1, 6):
            self.residual(2, "Bind")
            self.assertEqual(self.trap(2)[4], n)
        self.assertEqual(self.trap(2), (1, 1, self.M["BIND"] + 1, 1, 5))

    def test_a_sixth_residual_damage_line_is_a_stop(self):
        # the engine's trap lasts 5 or 6 residual phases and the last one ends it with no damage: at most 5 damage lines
        from duoforge_live import lines
        self.start(2, 0, "Bind")
        for _ in range(5):
            self.residual(2, "Bind")
        with self.assertRaises(lines.Stop) as caught:
            self.residual(2, "Bind")
        self.assertEqual(caught.exception.reason, "trap-residual-count")
        self.assertEqual(self.trap(2)[4], 5)

    def test_a_residual_line_that_is_not_the_traps_is_a_stop(self):
        from duoforge_live import lines
        good = "|-damage|p2a: Mon|83/100|[from] move: Bind|[partiallytrapped]"
        for trapped, line, reason in (
                (False, good, "trap-residual-untrapped"),
                (True, "|-damage|p2a: Mon|83/100|[from] move: Wrap|[partiallytrapped]", "trap-residual-move"),
                (True, "|-damage|p2a: Mon|83/100|[from] move: Whirlpool|[partiallytrapped]", "trap-residual-move"),
                (True, "|-damage|p2: Mon|83/100|[from] move: Bind|[partiallytrapped]", "trap-residual-line"),
                (True, good + "|[silent]", "trap-residual-line"),
                (True, "|-damage|p2a: Mon|[from] move: Bind|[partiallytrapped]", "trap-residual-line"),
                (True, "|-heal|p2a: Mon|83/100|[from] move: Bind|[partiallytrapped]", "trap-residual-line")):
            self.setUp()
            if trapped:
                self.start(2, 0, "Bind")
            with self.assertRaises(lines.Stop, msg=line) as caught:
                self.t._trap_residual(line.split("|"))
            self.assertEqual(caught.exception.reason, reason, line)
            self.assertEqual(self.trap(2)[4], 0, line)

    def test_the_end_line_clears_everything_and_names_its_move(self):
        from duoforge_live import lines
        self.start(2, 0, "Bind")
        self.residual(2, "Bind")
        with self.assertRaises(lines.Stop) as caught:
            self.end(2, "Wrap")
        self.assertEqual(caught.exception.reason, "trap-end-move")
        self.end(2, "Bind")
        self.assertEqual(self.trap(2), (0, 0, 0, 0, 0))
        with self.assertRaises(lines.Stop) as caught:
            self.end(2, "Bind")  # nothing to end
        self.assertEqual(caught.exception.reason, "trap-end-untrapped")

    def test_the_silent_end_clears_everything_in_the_pins_forms_only(self):
        from duoforge_live import lines
        for end in ("Bind", "move: Bind"):
            self.setUp()
            self.start(2, 0, "Bind")
            self.residual(2, "Bind")
            self.t._trap_silent_end(f"|-end|p2a: Mon|{end}|[partiallytrapped]|[silent]".split("|"))
            self.assertEqual(self.trap(2), (0, 0, 0, 0, 0), end)
        self.start(2, 0, "Bind")
        for line, reason in (("|-end|p2a: Mon|Wrap|[partiallytrapped]|[silent]", "trap-end-move"),
                             ("|-end|p2: Mon|Bind|[partiallytrapped]|[silent]", "trap-end-line"),
                             ("|-end|p2a: Mon|Bind|[partiallytrapped]|[silent]|[of] p1a: Mon", "trap-end-line"),
                             ("|-end|p2a: Mon|Bind|[silent]|[partiallytrapped]", "trap-end-line"),
                             ("|-end|p2b: Mon|Bind|[partiallytrapped]|[silent]", "trap-end-untrapped")):
            with self.assertRaises(lines.Stop, msg=line) as caught:
                self.t._trap_silent_end(line.split("|"))
            self.assertEqual(caught.exception.reason, reason, line)
        self.assertEqual(self.trap(2)[0], 1)

    def test_the_trapped_pokemon_leaving_clears_the_trap_and_the_count(self):
        for kind in ("SWITCH", "DRAG", "FAINT"):
            self.setUp()
            self.start(2, 0, "Bind")
            self.residual(2, "Bind")
            self.leave(2, kind)
            self.assertEqual(self.trap(2), (0, 0, 0, 0, 0), kind)

    def test_the_source_leaving_keeps_the_trap_and_the_count_with_no_source(self):
        # dfi_tail_clear_occupant: the source becomes 0, the turns, the move, the band and the count stay; the residual
        # then ends it silently (the silent end line)
        for kind in ("SWITCH", "DRAG", "FAINT"):
            self.setUp()
            self.start(2, 0, "Bind")
            self.start(3, 0, "Infestation")  # one source, two targets
            self.start(0, 3, "Wrap")  # a trap on the leaver itself, sourced elsewhere
            self.residual(2, "Bind")
            self.leave(0, kind)
            self.assertEqual(self.trap(2), (1, 0, self.M["BIND"] + 1, 1, 1), kind)
            self.assertEqual(self.trap(3), (1, 0, self.M["INFESTATION"] + 1, 1, 0), kind)
            self.assertEqual(self.trap(0), (0, 0, 0, 0, 0), kind)  # the leaver's own trap went with it
            self.t._trap_silent_end("|-end|p2a: Mon|Bind|[partiallytrapped]|[silent]".split("|"))
            self.assertEqual(self.trap(2), (0, 0, 0, 0, 0), kind)

    def test_another_position_leaving_changes_no_trap(self):
        self.start(2, 0, "Bind")
        self.leave(1)
        self.leave(3, "FAINT")
        self.assertEqual(self.trap(2), (1, 1, self.M["BIND"] + 1, 1, 0))

    def test_a_baton_pass_of_a_trapped_leaver_is_a_stop(self):
        # dfi_pass_give copies the turns, the source, the move and the band but not the elapsed count, which leaves the
        # engine's receiver with turns + elapsed outside {5, 6}: no honest fold of it exists
        from duoforge_live import lines
        from duoforge_live.data import trace_to_c
        self.start(2, 0, "Bind")
        self.residual(2, "Bind")
        with self.assertRaises(lines.Stop) as caught:
            self.leave(2, cause=trace_to_c.CAUSE["MOVE"], id2=self.M["BATONPASS"])
        self.assertEqual(caught.exception.reason, "trap-baton-pass")
        # an untrapped leaver passes as before
        self.setUp()
        self.leave(2, cause=trace_to_c.CAUSE["MOVE"], id2=self.M["BATONPASS"])
        self.assertEqual(self.trap(2), (0, 0, 0, 0, 0))

    def test_a_new_occupant_can_be_trapped_at_once(self):
        self.start(2, 0, "Bind")
        self.leave(2)
        self.start(2, 1, "Wrap")
        self.assertEqual(self.trap(2), (1, 2, self.M["WRAP"] + 1, 0, 0))

    def test_the_record_writes_the_public_trap_fields_and_hides_the_turns(self):
        # dfi_view_encode: the drawn turns are DUOFORGE_VIEW_HIDDEN for both viewers; the source (0 once it left), the move,
        # the band and the elapsed count are public and written as the engine keeps them
        import collections
        from duoforge_live import record
        C = self.tracker.C
        t = self.t
        t._conditions, t._hazards, t._guards = [[0] * 4, [0] * 4], [collections.Counter(), collections.Counter()], set()
        self.start(2, 0, "Bind")
        self.residual(2, "Bind")
        self.residual(2, "Bind")
        self.start(1, 3, "Wrap")
        self.leave(3, "FAINT")  # the source of the second trap left
        self.assertEqual(record.unrecorded_folds(t), [])
        size = max(start + length for start, length in record._FIELDS.values())
        s = record._State(size)
        record._tail(t, s, C["DUOFORGE_BOUNDARY_PIVOT"])

        def field(flat, name):
            start, length = record._FIELDS[f"tail.side{flat // 2}.position{flat % 2}.{name}"]
            return int.from_bytes(s.bytes[start:start + length], "little")
        hidden = C["DUOFORGE_VIEW_HIDDEN"]
        self.assertEqual([field(2, n) for n in ("trap_turns", "trap_source", "trap_move", "trap_band", "trap_elapsed")],
                         [hidden, 1, self.M["BIND"] + 1, 1, 2])
        self.assertEqual([field(1, n) for n in ("trap_turns", "trap_source", "trap_move", "trap_band", "trap_elapsed")],
                         [hidden, 0, self.M["WRAP"] + 1, 1, 0])
        for flat in (0, 3):
            self.assertEqual([field(flat, n) for n in ("trap_turns", "trap_source", "trap_move", "trap_band",
                                                       "trap_elapsed")], [0] * 5, flat)

    def test_the_view_extension_shows_the_presence_and_the_count(self):
        from types import SimpleNamespace
        from duoforge_live import tracker
        C = tracker.C
        t = self.t
        t.request, t.epoch, t._conditions, t._guards = {}, 3, [[0] * 4, [0] * 4], set()
        t._hazards = [tracker.collections.Counter(), tracker.collections.Counter()]
        t.data = SimpleNamespace(kind="pool", tables=self.D.tables)
        for side in (0, 1):
            for m in self.members[side]:
                m.ability = 0
        self.start(2, 0, "Bind")
        for _ in range(3):
            self.residual(2, "Bind")
        self.start(1, 3, "Wrap")
        ext = t.observation_ext()
        bit = C["DUOFORGE_POSITION_EXT_PARTIAL_TRAP"]
        self.assertEqual(ext["sides"][1]["positions"]["volatiles"].tolist(), [bit, 0])
        self.assertEqual(ext["sides"][0]["positions"]["volatiles"].tolist(), [0, bit])
        self.assertEqual(ext["volatiles2"].tolist(), [[0, 0], [3 << 4, 0]])  # POSITION_EXT2 bits 4 to 6: the count
        self.leave(2)
        again = t.observation_ext()
        self.assertEqual(again["volatiles2"].tolist(), [[0, 0], [0, 0]])
        self.assertEqual(again["sides"][1]["positions"]["volatiles"].tolist(), [0, 0])


if __name__ == "__main__":
    unittest.main()
