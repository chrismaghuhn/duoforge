"""duoforge.python.live_unit: the Showdown live adapter without Node.

Teams (packing, the open team sheets, the match against Team A and B) and
the data the adapter reads from the converter's tables, checked against the
library.
"""
import collections
import random
import unittest

from duoforge_live import data, lines, teams

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
        cls.fixture = json.loads((data.ROOT / "python" / "tests" / "support" / "data" / "live_stream_ab.json")
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
        t._action = None  # no move action open (Tracker._segment)
        t._healing_wish = None  # no Healing Wish in the tables (G82)
        t._herb_end = None
        t._positions = [[tracker._Position(), tracker._Position()] for _ in (0, 1)]
        for side in t._positions:
            for k, p in enumerate(side):
                p.occupant = k
        return t

    def test_the_record_writes_the_folds_of_342(self):
        # record.py writes the tail fields of the #342 folds exactly per the engine's layout: the hazard layers and their
        # creation order (2 bits per slot), Wide Guard, the counts of Taunt, Heal Block, Yawn and Disable, the 0/1 bytes,
        # Soak's type (soak_type, type2 0) and Double Shock's (soak_type ???, type2 the remaining type); Rage Powder is
        # the Follow Me flag of the position (_position)
        import collections
        from duoforge._state_layout import VALUES
        from duoforge_live import record
        t = self.tracker()
        t._party, t._conditions = None, [[0] * 4, [0] * 4]
        t._member = lambda side: []
        t._hazards = [collections.Counter(), collections.Counter()]
        t._guards = {("WIDE_GUARD", 0)}
        t._hazards[1]["toxic_spikes"] = 2
        t._hazards[1]["stealth_rock"] = 1
        t._hazards[0]["spikes"] = 1
        t._hazards[0]["sticky_web"] = 1
        t._hazards[0].pop("spikes")  # an ended kind leaves; one put up again goes last
        t._hazards[0]["spikes"] = 3
        a, b = t._positions[1][0], t._positions[0][1]
        a.taunt, a.heal_block, a.yawn, a.disable_slot, a.disable_turns = 4, 2, 1, 3, 5
        a.imprison, a.must_recharge, a.glaive_rush = 1, 1, 1
        a.type_now, a.type2 = (0, 7), 7  # Double Shock: the ??? slot and the remaining type + 1
        b.type_now, b.type2 = (18, 0), 0  # Soak: Water + 1
        st = record._State(max(start + size for start, size in record._FIELDS.values()))
        record._tail(t, st, 2)

        def get(name):
            start, size = record._FIELDS[name]
            return int.from_bytes(st.bytes[start:start + size], "little")
        hz = {n: VALUES[f"DFI_HAZARD_{n.upper()}"] for n in ("stealth_rock", "spikes", "toxic_spikes", "sticky_web")}
        self.assertEqual([get(f"tail.side1.{n}") for n in ("toxic_spikes", "stealth_rock", "spikes", "sticky_web")],
                         [2, 1, 0, 0])
        self.assertEqual(get("tail.side1.hazard_order"), hz["toxic_spikes"] | hz["stealth_rock"] << 2)
        self.assertEqual(get("tail.side0.hazard_order"), hz["sticky_web"] | hz["spikes"] << 2)
        self.assertEqual(get("tail.side0.spikes"), 3)
        self.assertEqual((get("tail.side0.wide_guard"), get("tail.side1.wide_guard")), (VALUES["DFI_TAIL_WIDE_GUARD_MAX"], 0))
        pre = "tail.side1.position0."
        self.assertEqual([get(pre + n) for n in ("taunt_turns", "heal_block_turns", "yawn_turns", "disable_slot",
                                                 "disable_turns", "imprison", "must_recharge", "glaive_rush")],
                         [4, 2, 1, 3, 5] + [VALUES["DFI_TAIL_FLAG_MAX"]] * 3)
        self.assertEqual((get("tail.side1.member0.soak_type"), get("tail.side1.member0.type2")),
                         (VALUES["DFI_TAIL_TYPE2_TYPELESS"], 7))
        self.assertEqual((get("tail.side0.member1.soak_type"), get("tail.side0.member1.type2")), (18, 0))

    def test_healing_wish_is_a_slot_condition(self):
        # G82 (decision 0045, dfi_run_healing_wish and dfi_wish_heal): a Healing Wish that runs sets its slot's wish, which
        # the user's faint and the next occupant keep (the position's flags bit 0, the view's HEALING_WISH bit); the heal of
        # an entrant (-heal ... [from] move: Healing Wish) ends it and the entrant's status with it (clearStatus, no line).
        # A wish refused for no reserve ([still] -fail) sets nothing.
        from types import SimpleNamespace
        from duoforge._state_layout import VALUES
        from duoforge_live import record
        from duoforge_live.data import trace_to_c
        from duoforge_live.tracker import EXT_FIELDS
        t = self.tracker()
        t._move_pivots, t._guard_moves, t._choice_items, t._struggle, t._last_move = {}, set(), set(), None, None
        t._healing_wish = 9
        t._item_of = lambda member: None
        t._pressure_extra = lambda pos, move, target, flags: 0
        members = [SimpleNamespace(sheet={"moves": [9, 8]}, uses=[0, 0], item_used=0, status=3, freeze_turns=0, toxic=0,
                                   toxic_stage=0, hp_percent=40, hp_flag=0) for _ in range(6)]
        t._member = lambda side: members
        EV, CAUSE, FLAG = trace_to_c.EV, trace_to_c.CAUSE, trace_to_c.FLAG
        p = t._positions[0][1]
        t._fold_event(trace_to_c.ev_tuple(EV["MOVE"], 1, cause=CAUSE["NONE"], ident=9, flags=FLAG["STILL"]))
        self.assertEqual(p.wish, 0)  # no reserve: -fail [still]
        t._fold_event(trace_to_c.ev_tuple(EV["MOVE"], 1, cause=CAUSE["NONE"], ident=9))
        self.assertEqual(p.wish, 1)
        p.reset()  # the faint and the next occupant's entry clear the position's conditions, not the slot's wish
        self.assertEqual(p.wish, 1)
        t._spectator = True
        t._fold_event(trace_to_c.ev_tuple(EV["HEAL"], 1, cause=CAUSE["MOVE"], ident2=9, hp=100))
        self.assertEqual((p.wish, members[p.occupant].status), (0, 0))
        self.assertEqual(record.POSFLAG_HEALING_WISH, VALUES["DFI_POSFLAG_HEALING_WISH"])
        self.assertIn("HEALING_WISH", EXT_FIELDS)

    def test_a_bounced_move_is_no_action_of_the_holder(self):
        # c1_cover_b step 2: |move|p2b: Espeon|Glare|p1b: Serperior|[from] ability: Magic Bounce is Magic Bounce's reflection
        # (useMove), no action of the holder: acted (move_actions != 0, only dfi_run_move counts, as runMove's
        # activeMoveActions++) stays 0; the user's own move line sets it. Dancer's copy, which runMove would count, is no line
        # the converter takes (an unknown move attribute raises)
        from types import SimpleNamespace
        from duoforge_live.data import trace_to_c
        t = self.tracker()
        t._move_pivots, t._guard_moves, t._choice_items, t._struggle, t._last_move = {}, set(), set(), None, None
        t._item_of = lambda member: None
        t._pressure_extra = lambda pos, move, target, flags: 0
        members = [SimpleNamespace(sheet={"moves": [7, 8]}, uses=[0, 0], item_used=0) for _ in range(6)]
        t._member = lambda side: members
        bounce = trace_to_c.ev_tuple(trace_to_c.EV["MOVE"], 3, 1, trace_to_c.CAUSE["ABILITY"], 8, 5)
        t._fold_event(bounce)
        self.assertEqual(t._positions[1][1].acted, 0)
        t._fold_event(trace_to_c.ev_tuple(trace_to_c.EV["MOVE"], 3, 1, trace_to_c.CAUSE["NONE"], 7))
        self.assertEqual(t._positions[1][1].acted, 1)

    def test_turn_history_bits_follow_the_engine(self):
        # G88 (decision 0046): LOWERED for a stage that really fell, HURT for a spread damage that leaves its target
        # standing; not for the directDamage of a user's own cost (Struggle's recoil, Substitute's and Clangorous Soul's
        # -damage); a plain -damage on the user of another move stops; the turn boundary (not turn 1) clears all three
        from duoforge_live import lines
        from duoforge_live.data import trace_to_c
        t = self.tracker()
        t._struggle, t._direct_costs, t._last_move = 900, {901, 902}, None
        CAUSE = trace_to_c.CAUSE
        p, q = t._positions[0][0], t._positions[1][0]
        t._hurt(2, CAUSE["NONE"])  # a hit of no move line: hurt
        self.assertEqual(q.hurt, 1)
        t._last_move = (0, 900, 2)
        t._hurt(0, CAUSE["RECOIL"])  # Struggle's recoil: directDamage
        self.assertEqual(p.hurt, 0)
        t._last_move = (0, 901, 0)
        t._hurt(0, CAUSE["NONE"])  # Substitute's or Clangorous Soul's cost
        self.assertEqual(p.hurt, 0)
        t._last_move = (0, 5, 2)
        t._hurt(0, CAUSE["RECOIL"])  # another move's recoil is applyRecoilDamage, a spread damage
        self.assertEqual(p.hurt, 1)
        p.hurt = 0
        for cause in ("POISON", "WEATHER", "CONFUSION"):
            t._hurt(0, CAUSE[cause])
            self.assertEqual(p.hurt, 1)
            p.hurt = 0
        with self.assertRaises(lines.Stop):
            t._hurt(0, CAUSE["NONE"])  # a plain -damage on its own user that no engine cost explains

    def test_the_direct_costs_are_the_engines_dfi_deal_direct_sites(self):
        # G86: Belly Drum's half-HP cost is directDamage like Substitute's and Clangorous Soul's (src/combat/turn.c
        # dfi_run_belly_drum), and G84b's Ghost Curse cost is too (dfi_run_curse); the four are the plain -damage of the
        # user's own move that sets no HURT. The engine's dfi_deal(..., DFI_DMG_DIRECT) sites on batch 8: dfi_run_clangorous_soul,
        # dfi_run_curse, dfi_run_substitute, dfi_run_belly_drum, and Struggle's recoil (DFI_MOVE_FLAG_STRUGGLE_RECOIL, folded apart)
        from duoforge_live import tracker
        self.assertEqual(set(tracker.DIRECT_COST_MOVES), {"SUBSTITUTE", "CLANGOROUSSOUL", "BELLYDRUM", "CURSE"})

    def test_leech_seed_source_comes_from_the_move_line_and_the_drain_must_agree(self):
        # G84 (decision 0047): -start|X|move: Leech Seed has no [of]; the seed's source is the user of the move line before
        # (the engine's leech_seed_source is its flat position + 1) and the drain's [of] must name it; any other form stops
        from duoforge_live import lines, tracker
        from duoforge_live.data import trace_to_c
        EV, CAUSE = trace_to_c.EV, trace_to_c.CAUSE
        t = self.tracker()
        t._leech_seed, t._struggle, t._direct_costs = 77, 900, set()
        from types import SimpleNamespace
        t._member = lambda side: [SimpleNamespace(hp_percent=100, hp_flag=0, toxic=0) for _ in range(2)]
        start = trace_to_c.ev_tuple(EV["VOLATILE_START"], 3, trace_to_c.NOPOS, detail=trace_to_c.VOLATILE_LEECH_SEED)
        t._last_move = (0, 78, 3)  # another move's line before the start
        with self.assertRaises(lines.Stop) as caught:
            t._fold_event(start)
        self.assertEqual(caught.exception.reason, "leech-seed-source-unknown")
        t._last_move = (3, 77, 3)  # the holder's own move line (never the seed's source)
        with self.assertRaises(lines.Stop):
            t._fold_event(start)
        t._last_move = (1, 77, 3)
        t._fold_event(start)
        holder = t._positions[1][1]
        self.assertEqual(holder.leech_source, 2)
        drain = trace_to_c.ev_tuple(EV["DAMAGE"], 3, 1, CAUSE["LEECH_SEED"], hp=40, hp_kind=0)
        t._last_move = None
        t._fold_event(drain)  # the source named
        other = trace_to_c.ev_tuple(EV["DAMAGE"], 3, 0, CAUSE["LEECH_SEED"], hp=30, hp_kind=0)
        with self.assertRaises(lines.Stop) as caught:
            t._fold_event(other)
        self.assertEqual(caught.exception.reason, "leech-seed-drain-source")
        holder.reset()  # the occupant leaves or faints: the volatile goes with it
        self.assertEqual(holder.leech_source, 0)
        self.assertIn("leech_source", tracker._PASSED)  # Baton Pass copies it (no noCopy; dfi_pass_give)

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
        passed = {"throat_chop": 1, "perish": 2, "taunt": 3, "heal_block": 2}  # the counts of the record
        kept = {"encore_slot": 3, "disable_slot": 2, "disable_turns": 4, "yawn": 1, "imprison": 1, "glaive_rush": 1,
                "must_recharge": 1, "type_now": (0, 7), "type2": 7}
        empty = {"encore_slot": 0, "disable_slot": 0, "disable_turns": 0, "yawn": 0, "imprison": 0, "glaive_rush": 0,
                 "must_recharge": 0, "type_now": (0, 0), "type2": 0}
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

    def test_a_natural_end_needs_a_count_of_one(self):
        # the residual's -end of Taunt, Disable or Heal Block (no [from], not Mental Herb's row) comes where the count runs
        # out: any other count of the tracker stops it (a wrong duration rule or move_queued is never written silently)
        from types import SimpleNamespace
        from duoforge_live import lines
        from duoforge_live.data import trace_to_c
        t = self.tracker()
        t._mental_herb, t._eject_button, t._unburden, t._spectator = 3, None, None, True
        members = [SimpleNamespace(revealed=0, item_consumed=0, item_used=0, item_now=0) for _ in range(6)]
        t._member = lambda side: members
        EV = trace_to_c.EV

        def end(detail, cause=0):
            t._event(trace_to_c.ev_tuple(EV["VOLATILE_END"], 2, cause=cause, detail=detail))
        p = t._positions[1][0]
        for field, detail, name in (("taunt", trace_to_c.VOLATILE_TAUNT, "taunt"),
                                    ("disable_turns", trace_to_c.VOLATILE_DISABLE, "disable"),
                                    ("heal_block", trace_to_c.VOLATILE_HEAL_BLOCK, "heal_block")):
            setattr(p, field, 1)
            end(detail)  # the residual's end at the count's last turn
            self.assertEqual(getattr(p, field), 0)
            setattr(p, field, 2)
            with self.assertRaises(lines.Stop) as caught:
                end(detail)
            self.assertEqual(str(caught.exception).split(" ")[0], f"count:{name}")
        # Mental Herb (-enditem, then its -end lines in a row) ends them at any count
        p.taunt, p.disable_slot, p.disable_turns, p.heal_block = 3, 1, 4, 2
        t._event(trace_to_c.ev_tuple(EV["ITEM_END"], 2, ident2=4))
        for detail in (trace_to_c.VOLATILE_TAUNT, trace_to_c.VOLATILE_DISABLE, trace_to_c.VOLATILE_HEAL_BLOCK):
            end(detail)
        self.assertEqual((p.taunt, p.disable_slot, p.disable_turns, p.heal_block), (0, 0, 0, 0))
        p.taunt = 2  # the row ends with the first other line
        t._event(trace_to_c.ev_tuple(EV["FLASH_FIRE"], 0))  # a line of another position
        with self.assertRaises(lines.Stop):
            end(trace_to_c.VOLATILE_TAUNT)

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


class AttractFoldTest(unittest.TestCase):
    """Step G71 (decision 0034): the tracker folds Attract per position. The source is the holder's member code (1 + side *
    6 + roster index) on the infatuated position, set by the start line; the visible ends (Mental Herb, Oblivious), the silent
    end (-end|X|Attract|[silent]: the source left) and the occupant's leaving (a switch or a faint, no line) clear it; the Baton
    Pass copy does not carry it (noCopy, data/moves.ts attract). The record's tail writes the four bytes by flat position."""

    tracker = staticmethod(TrackerStopTest.tracker)

    @staticmethod
    def members(n=6):
        from types import SimpleNamespace
        return [SimpleNamespace(toxic_stage=0, seen=False, hp_percent=0, hp_flag=0, status=0, freeze_turns=0, toxic=0,
                                item_now=0, hp=0, hp_max=0) for _ in range(n)]

    def attracted(self, t):
        """Position 0 (side 0, slot 0) infatuated by the member at position 2 (side 1, slot 0, roster 0): code 1 + 6 = 7."""
        from duoforge_live.data import trace_to_c
        t._event(trace_to_c.ev_tuple(trace_to_c.EV["VOLATILE_START"], 0, 2, trace_to_c.CAUSE["ABILITY"], 0, 11,
                                     detail=trace_to_c.VOLATILE_ATTRACT))
        return t._positions[0][0]

    def test_the_start_keeps_the_source_member_code(self):
        from duoforge_live.data import trace_to_c
        t = self.tracker()
        t._spectator, t._mental_herb = True, 3
        t._member = lambda side: self.members()
        p = self.attracted(t)
        self.assertEqual(p.attract, 1 + 1 * 6 + 0)  # side 1, roster 0 of the holder at position 2
        t._positions[1][1].occupant = 4  # side 1, slot 1 holds roster 4: its code is 1 + 6 + 4
        t._event(trace_to_c.ev_tuple(trace_to_c.EV["VOLATILE_START"], 1, 3, trace_to_c.CAUSE["ABILITY"], 0, 11,
                                     detail=trace_to_c.VOLATILE_ATTRACT))
        self.assertEqual(t._positions[0][1].attract, 1 + 6 + 4)

    def test_the_visible_ends_clear_it(self):
        from duoforge_live.data import trace_to_c
        EV, CAUSE = trace_to_c.EV, trace_to_c.CAUSE
        t = self.tracker()
        t._spectator, t._mental_herb = True, 3
        t._member = lambda side: self.members()
        p = self.attracted(t)
        t._event(trace_to_c.ev_tuple(EV["VOLATILE_END"], 0, cause=CAUSE["ITEM"], ident2=4,
                                     detail=trace_to_c.VOLATILE_ATTRACT))  # Mental Herb's row
        self.assertEqual(p.attract, 0)
        self.attracted(t)
        t._event(trace_to_c.ev_tuple(EV["VOLATILE_END"], 0, cause=CAUSE["ABILITY"], ident2=2,
                                     detail=trace_to_c.VOLATILE_ATTRACT))  # Oblivious's cure
        self.assertEqual(p.attract, 0)

    def test_the_silent_end_clears_it_and_only_its_own_form_folds(self):
        from duoforge_live import lines
        t = self.tracker()
        t._member = lambda side: self.members()
        p = self.attracted(t)
        t._silent_attract_end("|-end|p1a: Ceruledge|Attract|[silent]".split("|"))  # the source left the field
        self.assertEqual(p.attract, 0)
        for line in ("|-end|p1a: Ceruledge|Attract", "|-end|p1a: Ceruledge|Attract|[silent]|[of] p2a: X",
                     "|-end|p1: Ceruledge|Attract|[silent]"):
            with self.assertRaises(lines.Stop, msg=line) as caught:
                t._silent_attract_end(line.split("|"))
            self.assertEqual(caught.exception.reason, "line:-end Attract", line)

    def test_the_occupant_leaving_clears_it_with_no_line(self):
        from duoforge_live.data import trace_to_c
        from duoforge_live.tracker import ROSTER_NONE
        t = self.tracker()
        t._spectator, t._after_upkeep, t._next_activation = True, False, 1
        t._foe_leads, t._party, t._baton_pass = [ROSTER_NONE, ROSTER_NONE], None, 7
        t._member = lambda side: self.members()
        p = self.attracted(t)
        t._event(trace_to_c.ev_tuple(trace_to_c.EV["SWITCH"], 0, trace_to_c.NOPOS, 0, 5, 0))  # a plain switch
        self.assertEqual((p.occupant, p.attract), (5, 0))
        self.attracted(t)
        t._event(trace_to_c.ev_tuple(trace_to_c.EV["FAINT"], 0))  # a faint
        self.assertEqual(p.attract, 0)

    def test_baton_pass_does_not_copy_it(self):
        from duoforge_live.data import trace_to_c
        t = self.tracker()
        t._spectator, t._next_activation, t._baton_pass = True, 1, 7
        t._foe_leads, t._party = [0xff, 0xff], None
        t._member = lambda side: self.members()
        p = self.attracted(t)
        t._event(trace_to_c.ev_tuple(trace_to_c.EV["SWITCH"], 0, trace_to_c.NOPOS, trace_to_c.CAUSE["MOVE"], 4, 7))
        self.assertEqual((p.occupant, p.attract), (4, 0))

    def test_a_cant_marks_the_action_taken(self):
        from duoforge_live.data import trace_to_c
        t = self.tracker()
        t._member = lambda side: self.members()
        p = t._positions[0][0]
        t._event(trace_to_c.ev_tuple(trace_to_c.EV["CANT"], 0, trace_to_c.NOPOS, trace_to_c.CAUSE["ATTRACT"]))
        self.assertEqual((p.acted, p.turn_done, p.move_queued), (1, True, False))

    def test_the_check_before_an_action_belongs_to_it(self):
        # the Attract check comes before the action's roll: its -activate is the action's first event (_pre_action), so the
        # previous action's result never counts it
        from duoforge_live.data import trace_to_c
        t = self.tracker()
        t._attract, t._struggle = 40, 900
        check = trace_to_c.ev_tuple(trace_to_c.EV["ACTIVATE"], 0, 2, trace_to_c.CAUSE["MOVE"], 0, 40)
        self.assertTrue(t._pre_action([check], 0))
        self.assertFalse(t._pre_action([check], 1))  # another position's check
        other = trace_to_c.ev_tuple(trace_to_c.EV["ACTIVATE"], 0, 2, trace_to_c.CAUSE["MOVE"], 0, 41)
        self.assertFalse(t._pre_action([other], 0))

    def test_the_record_writes_the_attract_sources_by_flat_position(self):
        from duoforge_live import record
        t = self.tracker()
        t._member = lambda side: self.members()
        t._party, t._conditions = None, [[0] * 4, [0] * 4]
        t._hazards = [collections.Counter(), collections.Counter()]
        t._guards = set()
        p = self.attracted(t)  # position 0: side 0 slot 0, source code 7
        t._positions[1][1].attract = 3  # side 1 slot 1 (flat 3): the source code of side 0's roster 2
        st = record._State(max(start + size for start, size in record._FIELDS.values()))
        record._tail(t, st, 2)
        start, size = record._FIELDS["tail5.attract_source"]
        self.assertEqual(size, 4)
        self.assertEqual(list(st.bytes[start:start + size]), [p.attract, 0, 0, 3])

    def test_the_presence_bit_and_its_field(self):
        from duoforge_live import tracker as tracker_module
        bit = tracker_module.C["DUOFORGE_POSITION_EXT_ATTRACT"]
        self.assertIn(("attract", bit), tracker_module._PRESENCE_BITS)
        self.assertEqual(tracker_module.EXT_FIELDS["RESERVE_VOLATILES"], (("bit", bit),))


class AttractConfusionTest(unittest.TestCase):
    """Step G71: a confused Pokemon that is infatuated shows its confusion line, the Attract check of the user, then the roll's
    [cant] or [move] (src/combat/turn.c). The library classifies the action as the engine does (duoforge_move_result); the
    check is no line of the result. Needs the library (the POOL tables)."""

    @classmethod
    def setUpClass(cls):
        cls.data = data.load(kind="pool")

    def test_confusion_then_attract_is_one_classified_action(self):
        from duoforge._state_layout import VALUES
        from duoforge_live import record
        from duoforge_live.data import trace_to_c
        EV, CAUSE, NOPOS = trace_to_c.EV, trace_to_c.CAUSE, trace_to_c.NOPOS
        moves = self.data.tables["MOVE"]
        confused = trace_to_c.ev_tuple(EV["CONFUSED"], 2)
        check = trace_to_c.ev_tuple(EV["ACTIVATE"], 2, 0, CAUSE["MOVE"], 0, moves["ATTRACT"])
        cant = trace_to_c.ev_tuple(EV["CANT"], 2, NOPOS, CAUSE["ATTRACT"])
        self.assertEqual(record.move_result_of(self.data, 2, [confused, check, cant]), VALUES["DFI_MOVE_RESULT_FALSE"])
        move = trace_to_c.ev_tuple(EV["MOVE"], 2, 0, CAUSE["NONE"], moves["THUNDERBOLT"])
        hit = trace_to_c.ev_tuple(EV["DAMAGE"], 0, NOPOS, CAUSE["NONE"])
        self.assertEqual(record.move_result_of(self.data, 2, [confused, check, move, hit]), VALUES["DFI_MOVE_RESULT_TRUE"])
        # the check of another move is no Attract's check: the action's result is not determined (None), and record.py
        # refuses the record with a named reason (move-result-not-determined), never a silent value
        other = trace_to_c.ev_tuple(EV["ACTIVATE"], 2, 0, CAUSE["MOVE"], 0, moves["TAILWIND"])
        self.assertIsNone(record.move_result_of(self.data, 2, [confused, other, cant]))

    def test_an_event_whose_position_the_log_does_not_name_determines_no_result(self):
        # replay rebuild 2026-10-11: Shell Bell after a hit that made its target faint names it without a slot
        # (-heal|p2a: X|45/100|[from] item: Shell Bell|[of] p1: Y), so the event's other position is unknown (None);
        # the action's result is then not determined (None), never a crash in the library binding
        from duoforge_live import record
        from duoforge_live.data import trace_to_c
        EV, CAUSE, NOPOS = trace_to_c.EV, trace_to_c.CAUSE, trace_to_c.NOPOS
        move = trace_to_c.ev_tuple(EV["MOVE"], 2, 0, CAUSE["NONE"], self.data.tables["MOVE"]["THUNDERBOLT"])
        hit = trace_to_c.ev_tuple(EV["DAMAGE"], 0, NOPOS, CAUSE["NONE"])
        heal = list(trace_to_c.ev_tuple(EV["HEAL"], 2, 0, CAUSE["ITEM"]))
        heal[2] = None
        self.assertIsNone(record.move_result_of(self.data, 2, [move, hit, tuple(heal)]))


class HpDisplayTest(unittest.TestCase):
    """duoforge.view.hp_display: the library's display (duoforge_hp_display) and its refusals as DuoforgeError."""

    def test_values_and_refusals(self):
        from duoforge import view
        from duoforge.errors import DuoforgeError
        self.assertEqual(view.hp_display(150, 193), (77, 0))
        self.assertEqual(view.hp_display(1, 181), (1, 0))
        self.assertEqual(view.hp_display(0, 181), (0, 0))
        for hp, hp_max in ((3, 2), (0, 0), (1, 0x10000)):
            with self.assertRaisesRegex(DuoforgeError, "INVALID_ARGUMENT"):
                view.hp_display(hp, hp_max)


class CheckpointTablesTest(unittest.TestCase):
    """The live tables come from the checkpoint (data.for_config): its data kind, its fingerprint checked against the
    library's context of that kind; anything else raises before a game."""

    def config(self, kind, fingerprint=None):
        import duoforge
        from duoforge import _layout
        if fingerprint is None:
            name = {"closure": "DUOFORGE_DATA_KIND_CLOSURE", "pool": "DUOFORGE_DATA_KIND_POOL"}[kind]
            with duoforge.Context(data_kind=_layout.CONSTANTS[name]) as ctx:
                fingerprint = ctx.fingerprint().hex()
        return {"format": 2, "data": {"kind": kind, "fingerprint": fingerprint}}

    def test_a_pool_checkpoint_gives_pool_tables_and_records(self):
        from duoforge import state_layout
        tables = data.for_config(self.config("pool"))
        self.assertEqual(tables.kind, "pool")
        head, size = tables.record_head()
        self.assertEqual(size, 1357)  # the POOL encoding (DUOFORGE_VIEW_STATE_MAX)
        start, length = next((s, n) for name, s, n in state_layout.fields(pool=False) if name == "fingerprint")
        self.assertEqual(head[start:start + length].hex(), self.config("pool")["data"]["fingerprint"])
        self.assertEqual(data.for_config(self.config("closure")).record_head()[1], 1009)

    def test_a_mismatch_raises_at_construction(self):
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            data.for_config(self.config("pool", "00" * 32))
        closure = self.config("closure")["data"]["fingerprint"]
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            data.for_config(self.config("pool", closure))  # closure tables named as pool
        with self.assertRaisesRegex(ValueError, "no live tables"):
            data.for_config({"format": 2, "data": {"kind": "team_c", "fingerprint": closure}})
        for config in ({"format": 2}, {"format": 2, "data": {"kind": "pool"}}, None):
            with self.assertRaisesRegex(ValueError, "names no data kind"):
                data.for_config(config)
        self.assertEqual(data.for_config({"format": 1}).kind, "closure")  # a format-1 network names no data: closure
        self.assertEqual(data.for_config({"seed": 1}).kind, "closure")  # train.save's format-1 config names no format
        for form in (3, 0, "2"):
            with self.assertRaisesRegex(ValueError, "is not 1 or 2"):
                data.for_config({"format": form})
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
        t._action, t._herb_end, t._last_move = None, None, None  # Tracker.__init__ sets them; _segment reads them
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

    def test_a_baton_pass_gives_the_trap_with_its_source_and_count(self):
        # dfi_pass_give: the partial trap has no noCopy in the pin, so the receiver is trapped by the same source, with the
        # same move, band and elapsed count (the turns stay hidden); a plain switch of the trapped one clears it
        from duoforge_live.data import trace_to_c
        self.start(2, 0, "Bind")
        self.residual(2, "Bind")
        self.residual(2, "Bind")
        self.leave(2, cause=trace_to_c.CAUSE["MOVE"], id2=self.M["BATONPASS"])
        self.assertEqual(self.trap(2), (1, 1, self.M["BIND"] + 1, 1, 2))
        self.residual(2, "Bind")  # it goes on counting
        self.assertEqual(self.trap(2)[4], 3)
        self.leave(2)
        self.assertEqual(self.trap(2), (0, 0, 0, 0, 0))
        # an untrapped leaver passes nothing, and the source's own leaving still ends the copy's source
        self.setUp()
        self.leave(2, cause=trace_to_c.CAUSE["MOVE"], id2=self.M["BATONPASS"])
        self.assertEqual(self.trap(2), (0, 0, 0, 0, 0))
        self.setUp()
        self.start(2, 0, "Bind")
        self.leave(2, cause=trace_to_c.CAUSE["MOVE"], id2=self.M["BATONPASS"])
        self.leave(0)
        self.assertEqual(self.trap(2), (1, 0, self.M["BIND"] + 1, 1, 0))

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
        # (record.unrecorded_folds is gone since #342: the assembler writes every fold, so no refusal list is left to check)
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


class AllySwitchStateTest(unittest.TestCase):
    """Step G80 (decision 0044 section 10, lane A's H17): the tracker's Ally Switch fold mirrors dfi_swap_position_state
    (src/combat/turn.c) field by field. What belongs to the Pokemon moves (the slot record and the whole tail position,
    position flags 1, 2-3, 4 and 5-7, the attract byte); what is a slot's stays (Leech Seed's source slot, Healing Wish bit 0,
    the locked target); the trap source of every position that names a swapped position follows the trapper, and so does the
    Attract source position (derived from the member code in the engine, a tracker field here). A swap onto a pending Healing
    Wish is E_UNSUPPORTED in the engine and an explicit stop here."""

    @classmethod
    def setUpClass(cls):
        from duoforge_live import tracker
        cls.tracker, cls.D = tracker, data.load(kind="pool")

    def setUp(self):
        t = TrackerStopTest.tracker()  # the positions hold the roster indexes 0 and 1 of both sides
        t.data, t._spectator = self.D, True
        self.t = t

    def swap(self, user=0, other=1):
        from duoforge_live.data import trace_to_c
        self.t._event(trace_to_c.ev_tuple(trace_to_c.EV["SWAP"], user, other, trace_to_c.CAUSE["MOVE"], 0,
                                          self.D.tables["MOVE"]["ALLYSWITCH"]))

    def at(self, flat):
        return self.t._positions[flat // 2][flat % 2]

    def test_every_field_of_a_position_is_classified(self):
        # a field added to _Position must be put on one of the two lists, deliberately: it moves or it is the slot's
        tr = self.tracker
        moving, slot = set(tr._SWAP_MOVES), set(tr._SWAP_SLOT)
        self.assertFalse(moving & slot)
        self.assertEqual(moving | slot, set(vars(tr._Position())))

    def test_the_pokemons_state_moves_with_it(self):
        # one distinct value per moving field on each of the two positions; the trap source and the Attract source position
        # name a foe here (the relinks have their own tests)
        tr = self.tracker
        a, c = self.at(0), self.at(1)
        values = {}
        for n, name in enumerate(tr._SWAP_MOVES):
            values[name] = (100 + n, 200 + n)
            setattr(a, name, values[name][0])
            setattr(c, name, values[name][1])
        a.trap_source, c.trap_source = 3, 4  # the flat positions 2 and 3 of the foe, + 1
        a.attract_from, c.attract_from = 2, 3
        a.ally_level = a.ally_turns = 0  # the swap's own passed roll sets the user's counter to level 1, 2 turns first
        c.ally_level, c.ally_turns = 3, 1
        values["trap_source"], values["attract_from"] = (3, 4), (2, 3)
        values["ally_level"], values["ally_turns"] = (1, 3), (2, 1)
        self.swap(0, 1)
        for name in tr._SWAP_MOVES:
            self.assertEqual((getattr(a, name), getattr(c, name)), values[name][::-1], name)

    def test_the_slots_own_state_stays(self):
        # Leech Seed's source slot (the drain goes to whoever stands there), the locked target (a slot location in the pin)
        a, c = self.at(0), self.at(1)
        a.leech_source, c.leech_source = 3, 0
        a.locked_target, c.locked_target = 2, 3
        a.confused, c.confused = 1, 0  # a field that moves, for the contrast
        self.swap(0, 1)
        self.assertEqual((a.leech_source, c.leech_source), (3, 0))
        self.assertEqual((a.locked_target, c.locked_target), (2, 3))
        self.assertEqual((a.confused, c.confused), (0, 1))

    def test_the_trap_source_of_every_position_follows_the_trapper(self):
        a, c, f0, f1 = self.at(0), self.at(1), self.at(2), self.at(3)
        f0.trap, f0.trap_source = 1, 1  # trapped by the Pokemon at flat 0 (+ 1)
        f1.trap, f1.trap_source = 1, 2  # trapped by the one at flat 1
        a.trap, a.trap_source = 1, 4  # trapped by the foe at flat 3: moves with the trapped Pokemon, names the same trapper
        self.swap(0, 1)
        self.assertEqual((f0.trap_source, f1.trap_source), (2, 1))
        self.assertEqual((c.trap, c.trap_source), (1, 4))
        self.assertEqual((a.trap, a.trap_source), (0, 0))

    def test_an_ally_trapped_by_its_partner_follows_it(self):
        # the trapped Pokemon moves to the trapper's slot and the trapper to its: the source names the other flat position
        a, c = self.at(0), self.at(1)
        c.trap, c.trap_source = 1, 1  # the Pokemon at flat 1 is trapped by the one at flat 0
        self.swap(0, 1)
        self.assertEqual((a.trap, a.trap_source), (1, 2))
        self.assertEqual((c.trap, c.trap_source), (0, 0))

    def test_the_attract_source_position_follows_the_source(self):
        # the byte (the member code) moves with the infatuated Pokemon and does not change; the source's flat position follows
        # the source to its new slot (the engine derives it from the code), also when the source is the swapped partner
        a, c, f0 = self.at(0), self.at(1), self.at(2)
        f0.attract, f0.attract_from = 1 + 0, 0  # infatuated by the member code 1 (side 0 roster 0), standing at flat 0
        c.attract, c.attract_from = 1 + 0, 0  # the partner is infatuated by the same source: the swap moves both
        a.attract, a.attract_from = 1 + 7, 3  # infatuated by the foe at flat 3
        self.swap(0, 1)
        self.assertEqual((f0.attract, f0.attract_from), (1, 1))  # the source now stands at flat 1
        self.assertEqual((a.attract, a.attract_from), (1, 1))  # c's state moved to flat 0; its source stands at flat 1
        self.assertEqual((c.attract, c.attract_from), (8, 3))  # a's state moved to flat 1; the foe source stays at flat 3

    def test_a_pending_healing_wish_stops(self):
        # dfi_ally_swap_wish_blocked: E_UNSUPPORTED when either slot holds the wish (the onSwap heal is not modelled)
        for flat in (0, 1):
            with self.subTest(wish_at=flat):
                self.setUp()
                self.at(flat).wish = 1
                with self.assertRaises(lines.Stop) as caught:
                    self.swap(0, 1)
                self.assertEqual(caught.exception.reason, "ally-switch-healing-wish")
                self.assertEqual((self.at(0).occupant, self.at(1).occupant, self.at(0).ally_level), (0, 1, 0))

    def test_the_foes_swap_is_the_same_swap(self):
        a, c = self.at(2), self.at(3)
        a.taunt, c.taunt = 3, 0
        a.leech_source, c.leech_source = 1, 2
        self.at(0).trap, self.at(0).trap_source = 1, 3  # our Pokemon at flat 0 is trapped by the foe at flat 2
        self.swap(2, 3)
        self.assertEqual((a.taunt, c.taunt, a.leech_source, c.leech_source), (0, 3, 1, 2))
        self.assertEqual(self.at(0).trap_source, 4)


if __name__ == "__main__":
    unittest.main()
