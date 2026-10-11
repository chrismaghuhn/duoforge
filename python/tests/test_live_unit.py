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
        t._action = None  # no move action open (Tracker._segment)
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


if __name__ == "__main__":
    unittest.main()
