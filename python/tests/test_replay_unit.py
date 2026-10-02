"""duoforge.python.replay_unit: the M11 replay pipeline without Node (spec
docs/superpowers/specs/2026-10-02-m11-replay-data-design.md section 14).

Everything here runs on our own data: the generated tables, the reference
teams and a committed spectator log of one reference battle
(python/tests/data/replay/). No replay of the unlicensed dataset is a test
input.
"""
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from duoforge_live import data, lines


def _define(header, name):
    return int(re.search(rf"#define {name} (\d+)u", header).group(1))


class DataTest(unittest.TestCase):
    """The POOL tables of the fold (Task 2)."""

    @classmethod
    def setUpClass(cls):
        cls.pool = data.load(kind="pool")
        cls.closure = data.load()
        cls.header = (data.ROOT / "src" / "data" / "pool_tables.h").read_text(encoding="ascii")

    def test_pool_counts(self):
        self.assertEqual(len(self.pool._formes), _define(self.header, "DFI_POOL_FORME_COUNT"))
        self.assertEqual(len(self.pool._pp_max), _define(self.header, "DFI_POOL_MOVE_COUNT"))
        self.assertEqual(len(self.pool._target_class), _define(self.header, "DFI_POOL_MOVE_COUNT"))

    def test_target_types(self):
        moves = self.pool.tables["MOVE"]
        self.assertEqual(self.pool.target_type(moves["TAILWIND"]), "allySide")
        self.assertEqual(self.pool.target_type(moves["PROTECT"]), "self")
        self.assertEqual(self.closure.target_type(moves["PROTECT"]), "self")

    def test_protect_pp(self):
        self.assertEqual(self.pool.pp_max(self.pool.tables["MOVE"]["PROTECT"]), 8)

    def test_closure_prefix_kept(self):
        for forme in range(self.closure.counts["FORME"]):
            self.assertEqual(self.pool.base_forme(forme), self.closure.base_forme(forme))
            self.assertEqual(self.pool.mega_forme(forme), self.closure.mega_forme(forme))
            self.assertEqual(self.pool.ability_of(forme), self.closure.ability_of(forme))
        for move in range(self.closure.counts["MOVE"]):
            self.assertEqual(self.pool.pp_max(move), self.closure.pp_max(move))
            self.assertEqual(self.pool.target_type(move), self.closure.target_type(move))

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            data.load(kind="x")

    def test_unknown_target_class(self):
        pool = data.load(kind="pool")
        pool._target_class = [99]
        with self.assertRaisesRegex(ValueError, "target class 99 has no Showdown target type"):
            pool.target_type(0)


class _View:
    """What lines.check reads of a tracker: the data and, per protocol ident, the sheet and current ability."""

    def __init__(self, members):
        self.data = data.load(kind="pool")
        t = self.data.tables
        self._members = {}
        for ident, (species, item, ability) in members.items():
            self._members[ident] = {"species": t["FORME"][species], "item": t["ITEM"][item] + 1 if item else 0,
                                    "ability": t["ABILITY"][ability] + 1}

    def sheet_of(self, ident):
        return self._members[ident.split(": ")[0][:2] + ": " + ident.split(": ")[1]]

    def known_sheet(self, ident):
        return self._members.get(ident.split(": ")[0][:2] + ": " + ident.split(": ")[1])

    def ability_now(self, ident):
        return self.sheet_of(ident)["ability"]


class LinesTest(unittest.TestCase):
    """The line classes of the shared fold (Task 3, spec section 5)."""

    @classmethod
    def setUpClass(cls):
        cls.view = _View({"p1: Staraptor": ("STARAPTOR", "SITRUSBERRY", "INTIMIDATE"),
                          "p2: Gholdengo": ("GHOLDENGO", "LIFEORB", "GOODASGOLD")})

    def stop(self, line):
        with self.assertRaises(lines.Stop) as caught:
            lines.check(line, self.view)
        return caught.exception.reason

    def test_feature_lines_stop(self):
        self.assertEqual(self.stop("|-weather|Sandstorm|[from] ability: Sand Stream|[of] p2a: Gholdengo"),
                         "feature:WEATHER_SAND")
        self.assertEqual(self.stop("|-ability|p2a: Gholdengo|Intimidate|[from] ability: Trace|[of] p1a: Staraptor"),
                         "feature:ABILITY_CHANGE")
        self.assertEqual(self.stop("|-enditem|p1a: Staraptor|Sitrus Berry|[from] move: Knock Off|[of] p2a: Gholdengo"),
                         "feature:ITEM_CHANGE")
        self.assertEqual(self.stop("|-status|p1a: Staraptor|tox"), "feature:AILMENT_TOX")
        self.assertEqual(self.stop("|replace|p1a: Zoroark|Zoroark-Hisui, L50, M"), "feature:ILLUSION")

    def test_unknown_lines_stop(self):
        self.assertEqual(self.stop("|-sethp|p1a: Staraptor|50/100"), "line:-sethp")
        self.assertEqual(self.stop("|move|p1a: Staraptor|Baton Pass|p1a: Staraptor"), "line:move Baton Pass")
        self.assertEqual(self.stop("|-activate|p1a: Staraptor|move: Court Change"), "line:-activate move: Court Change")
        self.assertEqual(self.stop("|-ability|p1a: Staraptor|Pressure"), "line:-ability Pressure")

    def test_fold_and_room_lines(self):
        self.assertEqual(lines.check("|-enditem|p1a: Staraptor|Sitrus Berry|[eat]", self.view), "fold")
        self.assertEqual(lines.check("|-ability|p1a: Staraptor|Intimidate|boost", self.view), "fold")
        self.assertEqual(lines.check("|-damage|p2a: Gholdengo|50/100|[from] item: Life Orb", self.view), "fold")
        self.assertEqual(lines.check("|-item|p1a: Staraptor|Sitrus Berry", self.view), "fold")  # own item announced
        self.assertEqual(self.stop("|-item|p1a: Staraptor|Life Orb"), "line:-item Life Orb")
        self.assertIsNone(lines.check("|j|☆x", self.view))
        self.assertIsNone(lines.check("|c|☆x|hi|there", self.view))

    def test_turn_scoped(self):
        self.assertEqual(lines.check("|-singleturn|p1a: Staraptor|move: Rage Powder", self.view), "turn:RAGE_POWDER")
        self.assertEqual(lines.check("|-singleturn|p1a: Staraptor|Wide Guard", self.view), "turn:WIDE_GUARD")

    def test_guard_blocks_are_turn_scoped(self):
        self.assertEqual(lines.check("|-activate|p1a: Staraptor|move: Wide Guard", self.view), "turn:WIDE_GUARD")
        self.assertEqual(lines.check("|-activate|p1a: Staraptor|move: Quick Guard", self.view), "turn:QUICK_GUARD")
        self.assertEqual(lines.check("|-activate|p2a: Gholdengo|ability: Storm Drain", self.view), "fold")

    def test_features_from_the_header(self):
        self.assertEqual(lines.FEATURES["WEATHER_SAND"], 0)
        self.assertEqual(lines.FEATURES["RAGE_POWDER"], 39)
        self.assertEqual(len(lines.FEATURES), 40)

    def test_supported_mask_forms(self):
        f = lines.FEATURES
        self.assertEqual(lines.parse_supported("0u"), 0)
        self.assertEqual(lines.parse_supported("(1ull << DUOFORGE_VIEWEXT_FEATURE_WEATHER_SNOW)"), 1 << f["WEATHER_SNOW"])
        self.assertEqual(lines.parse_supported("((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_THROAT_CHOP) | "
                                               "((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_HEAL_BLOCK)"),
                         1 << f["THROAT_CHOP"] | 1 << f["HEAL_BLOCK"])
        with self.assertRaisesRegex(ValueError, "not understood"):
            lines.parse_supported("SOMETHING_ELSE")
        self.assertEqual(lines.LIBRARY_SUPPORTED, lines.supported())

    def test_a_feature_the_tracker_does_not_fold_stops(self):
        # the library may support a feature (G8: Throat Chop), but rows carry no view extension until the tracker
        # folds it: the line still stops the perspective
        self.assertEqual(lines.SUPPORTED & ~lines.TRACKER_FOLDS, 0)
        self.assertEqual(self.stop("|-start|p1a: Staraptor|Throat Chop|[silent]"), "feature:THROAT_CHOP")

    def test_choice_items(self):
        self.assertEqual(lines.CHOICE_ITEMS, ("choiceband", "choicescarf", "choicespecs"))


TEAMS = data.ROOT / "tests" / "reference" / "teams"


class PriorTest(unittest.TestCase):
    """The stat point prior (Task 4, spec section 10), on pastes of our reference teams."""

    @classmethod
    def setUpClass(cls):
        from duoforge_replay import prior
        cls.prior_module = prior
        cls.tmp = Path(tempfile.mkdtemp(prefix="duoforge_prior_"))
        team_a = (TEAMS / "team_a.txt").read_text(encoding="utf-8")
        shutil.copy(TEAMS / "team_a.txt", cls.tmp / "a.txt")
        shutil.copy(TEAMS / "team_b.txt", cls.tmp / "b.txt")
        # Team A again, its Rillaboom with another spread: a tie of two spreads, the smaller tuple wins
        other = team_a.replace("EVs: 18 HP / 32 Atk / 2 Def / 6 SpD / 8 Spe", "EVs: 32 HP / 32 Atk / 2 Spe", 1)
        assert other != team_a
        head = "Nick (Rillaboom) (M) @ Miracle Seed  " + chr(10) + "Shiny: Yes" + chr(10)
        (cls.tmp / "c.txt").write_text(head + other.split(chr(10), 1)[1], encoding="utf-8")
        cls.prior = prior.Prior(prior.build(cls.tmp))
        cls.rillaboom = {"species": "Rillaboom", "item": "MiracleSeed", "ability": "GrassySurge", "nature": "Adamant",
                         "moves": ["WoodHammer", "GrassyGlide", "FakeOut", "HighHorsepower"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def lookup(self, **change):
        return self.prior.lookup({**self.rillaboom, **change})

    def test_levels(self):
        self.assertEqual(self.lookup(), ([18, 32, 2, 0, 6, 8], 0))  # tie of two: (18, ...) < (32, ...)
        self.assertEqual(self.lookup(moves=["WoodHammer", "Protect"])[1], 1)
        self.assertEqual(self.lookup(moves=["Protect"], item="Leftovers")[1], 2)
        self.assertEqual(self.lookup(moves=["Protect"], item="Leftovers", nature="Jolly")[1], 3)
        self.assertEqual(self.lookup(species="Pikachu"), ([0] * 6, 4))

    def test_move_order_does_not_matter(self):
        self.assertEqual(self.lookup(moves=list(reversed(self.rillaboom["moves"])))[1], 0)

    def test_pastes_counted(self):
        self.assertEqual(self.prior.data["pastes"], 3)

    def test_evs_are_refused(self):
        with self.assertRaisesRegex(ValueError, "EVs, not stat points"):
            self.prior_module.parse_paste("Rillaboom @ Miracle Seed\nAbility: Grassy Surge\nEVs: 252 Atk\n"
                                          "Adamant Nature\n- Fake Out")

    def test_unknown_line_refused(self):
        with self.assertRaisesRegex(ValueError, "unknown paste line"):
            self.prior_module.parse_paste("Rillaboom @ Miracle Seed\nWeird: line\n- Fake Out")



class LabelsTest(unittest.TestCase):
    """Label sets (Task 7, spec section 9) on hand-made turn segments of side 0 (p1)."""

    @classmethod
    def setUpClass(cls):
        from duoforge_live import options
        from duoforge_replay import labels, points
        cls.L, cls.P, cls.O = labels, points, options
        cls.tables = data.load(kind="pool").tables
        mv = cls.tables["MOVE"]
        # slot 0: Staraptor with Brave Bird (normal), Close Combat (normal), Tailwind (allySide), Protect (self);
        # Mega possible; reserves 2 and 3. Slot 1: Gholdengo with one move (Make It Rain, allAdjacentFoes).
        cls.moves = ([mv["BRAVEBIRD"], mv["CLOSECOMBAT"], mv["TAILWIND"], mv["PROTECT"]], [mv["MAKEITRAIN"]])
        request = {"side": {"id": "p1", "pokemon": [
            {"ident": "p1: a", "active": True, "condition": "100/100", "moves": ["bravebird", "closecombat", "tailwind", "protect"]},
            {"ident": "p1: b", "active": True, "condition": "100/100", "moves": ["makeitrain"]},
            {"ident": "p1: c", "active": False, "condition": "100/100", "moves": []},
            {"ident": "p1: d", "active": False, "condition": "100/100", "moves": []}]},
            "active": [{"moves": [{"id": "bravebird", "pp": 8, "target": "any", "disabled": False},
                                  {"id": "closecombat", "pp": 8, "target": "normal", "disabled": False},
                                  {"id": "tailwind", "pp": 8, "target": "allySide", "disabled": False},
                                  {"id": "protect", "pp": 8, "target": "self", "disabled": False}], "canMegaEvo": True},
                       {"moves": [{"id": "makeitrain", "pp": 8, "target": "allAdjacentFoes", "disabled": False}]}]}
        cls.lists = options.slot_options(request, 0, {"p1: a": 1, "p1: b": 0, "p1: c": 2, "p1: d": 3}, {})
        cls.point = points.Point(1, 0, points.TURN, (), 0)
        cls.species = {"Staraptor": 1, "Gholdengo": 0, "Rillaboom": 2, "Milotic": 3}

    def label(self, log, stop_line=None):
        point = self.P.Point(1, 0, self.P.TURN, (), len(log))
        return self.L.turn_label(log, point, 0, self.lists, self.moves,
                                 lambda details: self.species[details.split(",")[0]], self.tables,
                                 len(log) if stop_line is None else stop_line)

    def options_of(self, label, slot):
        return [self.lists[slot][i] for i in range(len(self.lists[slot])) if label.slots[slot] >> i & 1]

    def test_plain_move_exact(self):
        got = self.label(["|move|p1a: Staraptor|Close Combat|p2a: Foe", "|move|p1b: Gholdengo|Make It Rain|p2a: Foe|[spread] p2a,p2b"])
        self.assertEqual(got.reasons, (self.L.EXACT, self.L.EXACT))
        [o] = self.options_of(got, 0)
        self.assertEqual((o.kind, o.move_slot, o.target, o.mega), (self.O.MOVE, 1, 2, 0))

    def test_mega_shown(self):
        got = self.label(["|detailschange|p1a: Staraptor|Staraptor-Mega, L50, F", "|-mega|p1a: Staraptor|Staraptor|Staraptite",
                          "|move|p1a: Staraptor|Protect|p1a: Staraptor"])
        [o] = self.options_of(got, 0)
        self.assertEqual((o.move_slot, o.mega), (3, 1))

    def test_follow_me_makes_the_target_unknown(self):
        got = self.label(["|move|p2b: Foe2|Follow Me|p2b: Foe2", "|-singleturn|p2b: Foe2|move: Follow Me",
                          "|move|p1a: Staraptor|Close Combat|p2b: Foe2"])
        self.assertEqual(got.reasons[0], self.L.TARGET_UNKNOWN)
        self.assertEqual({o.target for o in self.options_of(got, 0)}, {1, 2, 3})
        self.assertEqual({(o.move_slot, o.mega) for o in self.options_of(got, 0)}, {(1, 0)})

    def test_faint_earlier_makes_the_target_unknown(self):
        got = self.label(["|move|p1b: Gholdengo|Make It Rain|p2a: Foe|[spread] p2a,p2b", "|faint|p2a: Foe",
                          "|move|p1a: Staraptor|Brave Bird|p2b: Foe2"])
        self.assertEqual(got.reasons[0], self.L.TARGET_UNKNOWN)

    def test_paralysis_hides_the_move(self):
        got = self.label(["|cant|p1a: Staraptor|par"])
        self.assertEqual(got.reasons[0], self.L.MOVE_HIDDEN)
        self.assertEqual({o.kind for o in self.options_of(got, 0)}, {self.O.MOVE})
        self.assertEqual({o.mega for o in self.options_of(got, 0)}, {0})
        self.assertEqual(len(self.options_of(got, 0)), 3 + 3 + 1 + 1)  # every move option without Mega

    def test_cant_naming_the_move(self):
        got = self.label(["|cant|p1a: Staraptor|move: Taunt|Tailwind"])
        self.assertEqual(got.reasons[0], self.L.TARGET_UNKNOWN)
        self.assertEqual([o.move_slot for o in self.options_of(got, 0)], [2])

    def test_locked_move_is_forced(self):
        got = self.label(["|move|p1a: Staraptor|Brave Bird|p2a: Foe|[from]lockedmove"])
        self.assertEqual(got.reasons[0], self.L.FORCED)
        self.assertEqual(got.slots[0], (1 << len(self.lists[0])) - 1)

    def test_switch_action_exact(self):
        got = self.label(["|switch|p1a: Rillaboom|Rillaboom, L50, M|100/100", "|move|p1b: Gholdengo|Make It Rain|p2a: Foe"])
        [o] = self.options_of(got, 0)
        self.assertEqual((o.kind, o.reserve), (self.O.SWITCH, 2))

    def test_stop_before_the_move_is_unknown(self):
        log = ["|move|p1b: Gholdengo|Make It Rain|p2a: Foe", "|-sethp|p2a: Foe|50/100", "|move|p1a: Staraptor|Protect|p1a: Staraptor"]
        got = self.label(log, stop_line=1)
        self.assertEqual(got.reasons, (self.L.UNKNOWN, self.L.EXACT))
        self.assertEqual(got.slots[0], (1 << len(self.lists[0])) - 1)

    def test_team_label(self):
        from duoforge_live.game import TEAM_TABLE
        one = self.L.team_label((1, 0), {3})
        none = self.L.team_label((1, 0), set())
        bits = lambda label: [i for i in range(len(TEAM_TABLE)) if label.team[i // 8] >> (i % 8) & 1]  # noqa: E731
        self.assertEqual(len(bits(one)), 6)
        self.assertEqual(len(bits(none)), 12)
        self.assertTrue(all(TEAM_TABLE[i][:2] == (1, 0) and 3 in TEAM_TABLE[i][2:] for i in bits(one)))
        self.assertEqual(len(one.team), 45)



FIXTURE = Path(__file__).resolve().parent / "data" / "replay" / "c12_real_cb_4.log"


class _Stats:
    """A stand-in for the Showdown stat source (the unit tests run without Node): fixed stats per forme."""

    def stats(self, species, nature, stat_points):
        return [100 + len(species), 90, 80, 70, 60, 50]


class GameTest(unittest.TestCase):
    """One game end to end (Task 8) on the committed spectator log of c12_real_cb_4 (a reference battle)."""

    @classmethod
    def setUpClass(cls):
        from duoforge_replay import game, prior
        cls.game = game
        cls.data = data.load(kind="pool")
        cls.prior = prior.Prior({"version": 1, "pastes": 0, "skipped": {}, "levels": [{}, {}, {}, {}]})
        cls.log = FIXTURE.read_text(encoding="utf-8").splitlines()

    def run_game(self, lines):
        return self.game.process("fixture-1", "gen9championsvgc2026regmcbo3", "\n".join(lines), self.data,
                                 self.prior, _Stats())

    def skip_reason(self, lines):
        with self.assertRaises(self.game.Skip) as caught:
            self.run_game(lines)
        return caught.exception.reason

    def insert_after(self, prefix, new):
        i = next(i for i, line in enumerate(self.log) if line.startswith(prefix))
        return self.log[:i + 1] + [new] + self.log[i + 1:]

    def test_clean_game(self):
        result = self.run_game(self.log)
        self.assertEqual(result.counters["perspectives.kept"], 2)
        self.assertEqual(result.counters["points.written"], len(result.rows))
        for side in (0, 1):
            rows = [r for r in result.rows if r.side == side]
            self.assertGreater(len(rows), 10)
            epochs = [int(r.observation["epoch"]) for r in rows]
            self.assertEqual(epochs, sorted(set(epochs)))
            self.assertTrue(all(int(r.observation["player"]) == side for r in rows))
            self.assertTrue(all(r.prior_level == (4,) * 6 for r in rows))
        self.assertEqual(result.record.winner, 1)
        self.assertEqual(result.record.turns, 10)

    def test_sandstorm_stops_after_turn_two(self):
        clean = self.run_game(self.log)
        result = self.run_game(self.insert_after("|turn|2", "|-weather|Sandstorm|[from] ability: Sand Stream|[of] p2a: Politoed"))
        self.assertEqual(result.counters["perspectives.stopped.feature:WEATHER_SAND"], 2)
        self.assertGreater(result.counters["points.dropped.feature:WEATHER_SAND"], 0)
        turn2 = [int(r.observation["epoch"]) for r in clean.rows if int(r.observation["turn"]) == 2
                 and r.observation["boundary_kind"] == 2]
        self.assertTrue(all(int(r.observation["epoch"]) <= max(turn2) for r in result.rows))
        self.assertLess(len(result.rows), len(clean.rows))

    def test_illusion_sheet_skips(self):
        lines = [line.replace("|Defiant|", "|Illusion|", 1) if line.startswith("|showteam|p1|") else line
                 for line in self.log]
        self.assertEqual(self.skip_reason(lines), "skip:illusion")

    def test_session_line_skips_game(self):
        self.assertEqual(self.skip_reason(self.insert_after("|turn|3", "|init|battle")), "skip:session")

    def test_unknown_name_skips_with_reason(self):
        lines = [line.replace("ChopleBerry", "BogusBerry", 1) if line.startswith("|showteam|p1|") else line
                 for line in self.log]
        self.assertEqual(self.skip_reason(lines), "name:ITEM BogusBerry")

    def test_no_win_line(self):
        result = self.run_game([line for line in self.log if not line.startswith("|win|")])
        self.assertEqual(result.record.winner, -1)
        self.assertGreater(len(result.rows), 20)

    def test_player_ratings(self):
        lines = [line.replace("|player|p1|p1||", "|player|p1|Alice|1|1350").replace("|player|p2|p2||",
                                                                                      "|player|p2|Bob|2|abc")
                 for line in self.log]
        lines = [line.replace("|win|p2", "|win|Bob") for line in lines]
        record = self.run_game(lines).record
        self.assertEqual(record.ratings, (1350, -1))
        self.assertEqual(record.winner, 1)
        self.assertNotEqual(record.players[0], record.players[1])

    def test_rage_powder_without_pivot_passes(self):
        result = self.run_game(self.insert_after("|turn|3", "|-singleturn|p2a: Politoed|move: Rage Powder"))
        self.assertEqual(result.counters["turn-scoped.RAGE_POWDER"], 2)
        self.assertEqual(result.counters["perspectives.kept"], 2)

    def test_rage_powder_before_an_own_pivot_stops(self):
        # turn 2: p1's Parting Shot switch is a PIVOT point of side 0
        result = self.run_game(self.insert_after("|turn|2", "|-singleturn|p2a: Politoed|move: Rage Powder"))
        self.assertEqual(result.counters["perspectives.stopped.feature:RAGE_POWDER"], 1)
        self.assertEqual(result.counters["perspectives.kept"], 1)

    def test_picks_incomplete(self):
        # cut before p1's fourth member (Salamence) ever enters
        cut = next(i for i, line in enumerate(self.log) if line.startswith("|switch|p1a: Salamence"))
        result = self.run_game(self.log[:cut] + ["|win|p2"])
        side0 = [r for r in result.rows if r.side == 0]
        self.assertEqual(len(side0), 1)
        self.assertEqual(int(side0[0].observation["boundary_kind"]), 1)
        self.assertEqual(result.counters["perspectives.stopped.picks-incomplete"], 1)

    def test_forfeit_hides_nothing_it_cannot_know(self):
        # review C1: the game ends while players choose: no action ran, a switch was as possible as a move
        cut = next(i for i, line in enumerate(self.log) if line.startswith("|turn|5")) + 1
        result = self.run_game(self.log[:cut] + ["|-message|p1 forfeited.", "|win|p2"])
        last = [r for r in result.rows if int(r.observation["turn"]) == 5]
        self.assertTrue(last)
        from duoforge_replay import labels
        for row in last:
            self.assertNotIn(labels.MOVE_HIDDEN, row.label.reasons, row.side)

    def test_weather_extended_by_an_item_stops(self):
        # review C2: Politoed's Drizzle with Damp Rock lasts 8 turns, and no line says so
        lines = [line.replace("|MysticWater|", "|DampRock|", 1) if line.startswith("|showteam|p2|") else line
                 for line in self.log]
        result = self.run_game(lines)
        self.assertEqual(result.counters["perspectives.stopped.line:-weather RainDance Damp Rock"], 2)
        self.assertTrue(all(int(r.observation["boundary_kind"]) == 1 for r in result.rows))

    def test_sheet_the_converter_refuses_skips(self):
        # review I2: a refusal of the converter is a counted skip, not an escaping SystemExit
        lines = [line.replace("|Modest|", "||", 1) if line.startswith("|showteam|p2|") else line for line in self.log]
        reason = self.skip_reason(lines)
        self.assertTrue(reason.startswith("sheet:"), reason)

    def test_wide_guard_raises_the_stall_counter(self):
        # review I4: Wide Guard adds the stall volatile (data/moves.ts wideguard onHitSide): the chain shows 1
        lines = self.insert_after("|turn|5", "|-singleturn|p2a: Farigiraf|Wide Guard")
        lines = self.insert_after_in(lines, "|turn|5", "|move|p2a: Farigiraf|Wide Guard|p2a: Farigiraf")
        turn6 = [r for r in self.run_game(lines).rows if r.side == 0 and int(r.observation["turn"]) == 6
                 and int(r.observation["boundary_kind"]) == 2]
        self.assertEqual(int(turn6[0].observation["sides"][1]["positions"][0]["protect_chain"]), 1)

    def test_failed_detect_resets_the_stall_counter(self):
        # review I4: Detect shows "-singleturn|Protect"; its failure resets the counter like Protect's. The reset is
        # visible inside the turn (at a PIVOT); by the next TURN the stall duration ends the chain anyway.
        from duoforge_live import teams
        from duoforge_replay.spectator import SpectatorTracker
        lines = self.insert_after("|turn|1", "|-singleturn|p2a: Politoed|Protect")
        lines = self.insert_after_in(lines, "|turn|1", "|move|p2a: Politoed|Detect|p2a: Politoed")
        lines = self.insert_after_in(lines, "|turn|2", "|-fail|p2a: Politoed")
        lines = self.insert_after_in(lines, "|turn|2", "|move|p2a: Politoed|Detect||[still]")
        sheets = tuple(teams.unpack(line.split("|", 3)[3]) for line in lines if line.startswith("|showteam|"))
        tracker = SpectatorTracker(self.data, sheets, 0, None, lambda m, f: ([100] * 6, [0] * 6), lines)
        fail = lines.index("|-fail|p2a: Politoed")
        tracker.feed(lines[:fail])
        self.assertEqual(tracker._positions[1][0].chain, 1)  # Detect succeeded in turn 1
        tracker.feed([lines[fail]])
        self.assertEqual(tracker._positions[1][0].chain, 0)

    def insert_after_in(self, lines, prefix, new):
        i = next(i for i, line in enumerate(lines) if line.startswith(prefix))
        return lines[:i + 1] + [new] + lines[i + 1:]

    def test_forme_changed_on_the_bench_stops(self):
        # full run: Zero to Hero turns Palafin into Palafin-Hero on its way out, silently; its next switch line
        # shows the new forme (decision 0018 FORME_CHANGE), never an internal error
        i = max(i for i, line in enumerate(self.log) if line.startswith("|switch|p2a: Politoed|"))
        lines = list(self.log)
        lines[i] = lines[i].replace("Politoed, L50, M", "Politoed-Hero, L50, M")
        result = self.run_game(lines)
        self.assertEqual(result.counters["perspectives.stopped.feature:FORME_CHANGE"], 2)
        self.assertGreater(len(result.rows), 4)

    def test_charge_target_hidden_when_its_side_has_a_vacancy(self):
        from duoforge_live import teams
        from duoforge_replay.spectator import HIDDEN_TARGET, SpectatorTracker
        sheets = tuple(teams.unpack(line.split("|", 3)[3]) for line in self.log if line.startswith("|showteam|"))
        tracker = SpectatorTracker(self.data, sheets, 0, None, lambda m, f: ([100] * 6, [0] * 6), self.log)
        faint = self.log.index("|faint|p2b: Charizard")
        tracker.feed(self.log[:faint + 1])  # p2b fainted, not replaced yet
        tracker._log = self.log[:tracker._fed + 1] + ["|move|p1a: Salamence|Draco Meteor|p2a: Politoed|[from]lockedmove"]
        self.assertEqual(tracker._own_target(0), HIDDEN_TARGET)

    def test_two_games_in_one_log_skip(self):
        # a Bo3 log with a second game's lines: one game per row, so the log is skipped and counted
        start = self.log.index("|start")
        self.assertEqual(self.skip_reason(self.log + self.log[start:]), "skip:two-games")

    def test_a_failure_the_converter_does_not_parse_stops(self):
        # -fail|X|unboost (Clear Body stopped a drop): the converter decides which -fail forms it reads (main reads
        # "heal" since G8); the one it cannot read is a named stop, never an internal error
        lines = self.insert_after("|turn|3", "|-fail|p2a: Politoed|unboost|[from] ability: Clear Body|[of] p2a: Politoed")
        result = self.run_game(lines)
        stops = [k for k in result.counters if k.startswith("perspectives.stopped.converter:untyped -fail")]
        self.assertEqual(sum(result.counters[k] for k in stops), 2, result.counters)

    def test_bo3_game_number(self):
        lines = ['|uhtml|bestof|<h2><strong>Game 2</strong> of <a href="/game-bestof3-x">a best-of-3</a></h2>'] + self.log
        self.assertEqual(self.run_game(lines).record.bo3_game, 2)



class SupersetTest(unittest.TestCase):
    """Superset lists on the fixture (Task 6); duoforge.python.replay checks them against DuoForge."""

    def test_replacement_list(self):
        from duoforge_live import options, teams
        from duoforge_replay import points, spectator, superset
        log = FIXTURE.read_text(encoding="utf-8").splitlines()
        pool = data.load(kind="pool")
        sheets = tuple(teams.unpack(line.split("|", 3)[3]) for line in log if line.startswith("|showteam|"))
        picks = spectator.hindsight_picks(log, 0, pool, sheets)
        tracker = spectator.SpectatorTracker(pool, sheets, 0, picks, lambda m, f: ([100] * 6, [0] * 6), log)
        seen = []
        for point in spectator.walk(tracker, log, points.find(log)):
            if point.boundary == points.REPLACEMENT and spectator.own_requested(tracker):
                _, lists = superset.domain(tracker)
                seen.append([o.kind for o in lists[0]])
        # after turn 5 p1a fainted: the alive bench members, then pass
        self.assertTrue(seen)
        self.assertTrue(all(kinds[-1] == options.PASS and set(kinds[:-1]) <= {options.SWITCH} for kinds in seen), seen)

    def test_struggle_beside_every_move_list(self):
        # an effect outside the view can disable every move (two or more too), and then the request is Struggle
        from duoforge_live import options, teams
        from duoforge_replay import points, spectator, superset
        log = FIXTURE.read_text(encoding="utf-8").splitlines()
        pool = data.load(kind="pool")
        sheets = tuple(teams.unpack(line.split("|", 3)[3]) for line in log if line.startswith("|showteam|"))
        picks = spectator.hindsight_picks(log, 0, pool, sheets)
        tracker = spectator.SpectatorTracker(pool, sheets, 0, picks, lambda m, f: ([100] * 6, [0] * 6), log)
        moving = 0
        for point in spectator.walk(tracker, log, points.find(log)):
            if point.boundary == points.TURN and spectator.own_requested(tracker):
                _, lists = superset.domain(tracker)
                for slot in lists:
                    if any(o.kind == options.MOVE for o in slot):
                        moving += 1
                        self.assertTrue(any(o.move_slot == options.STRUGGLE for o in slot), slot)
        self.assertGreater(moving, 10)


def stats_factory():
    """The stat source of the build tests' workers (a module-level function, so spawned workers import it)."""
    return _Stats()


def _sha(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DatasetTest(unittest.TestCase):
    """Shards, games table, manifest, counters, determinism (Task 9, spec section 11)."""

    @classmethod
    def setUpClass(cls):
        import json
        from duoforge_replay import game, prior
        cls.data = data.load(kind="pool")
        cls.log = FIXTURE.read_text(encoding="utf-8")
        cls.empty_prior = {"version": 1, "pastes": 0, "skipped": {}, "levels": [{}, {}, {}, {}]}
        cls.results = [game.process(f"fixture-{i}", "gen9championsvgc2026regmc", cls.log, cls.data,
                                    prior.Prior(cls.empty_prior), _Stats()) for i in range(2)]
        cls.tmp = Path(tempfile.mkdtemp(prefix="duoforge_dataset_"))
        cls.prior_path = cls.tmp / "prior.json"
        cls.prior_path.write_text(json.dumps(cls.empty_prior), encoding="utf-8")
        source = cls.tmp / "source.jsonl"
        with open(source, "w", encoding="utf-8", newline="\n") as f:
            for i in range(3):
                f.write(json.dumps({"id": f"fixture-{i}", "formatid": "gen9championsvgc2026regmcbo3",
                                    "log": cls.log}) + "\n")
            f.write(json.dumps({"id": "other", "formatid": "gen9ou", "log": cls.log}) + "\n")
        cls.source = source

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def write(self, name, shard_rows=40):
        from duoforge_replay import dataset
        writer = dataset.Writer(self.tmp / name, {"test": True}, shard_rows=shard_rows)
        for result in self.results:
            writer.add(result)
        return writer.close()

    def test_round_trip(self):
        from duoforge_replay import dataset
        counters = self.write("round")
        shards = list(dataset.read(self.tmp / "round"))
        self.assertGreater(len(shards), 1)  # 40 rows per shard
        rows = sum(len(s["side"]) for s in shards)
        self.assertEqual(rows, sum(len(r.rows) for r in self.results))
        self.assertEqual(counters["points.written"], rows)
        first = shards[0]
        want = self.results[0].rows[0]
        self.assertEqual(first["observation"][0].tobytes(), want.observation.tobytes())
        self.assertEqual(first["domain"][0].tobytes(), want.domain.tobytes())
        self.assertEqual(tuple(first["label_slots"][0]), want.label.slots)
        self.assertEqual(bytes(first["label_team"][0]), want.label.team)
        games = dataset.read_games(self.tmp / "round")
        self.assertEqual(list(games["replay_id"]), ["fixture-0", "fixture-1"])
        self.assertEqual(games["winner"].tolist(), [1, 1])

    def test_same_bytes_twice(self):
        self.write("a")
        self.write("b")
        for path in sorted((self.tmp / "a").iterdir()):
            self.assertEqual(_sha(path), _sha(self.tmp / "b" / path.name), path.name)

    def test_refuses_the_repository(self):
        import subprocess
        from duoforge_replay import dataset
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            dataset.Writer(data.ROOT / "build" / "replay-out", {})
        # review I3: any work tree of this repository (the main checkout of a worktree too), and the prior file
        common = subprocess.run(["git", "-C", str(data.ROOT), "rev-parse", "--path-format=absolute",
                                 "--git-common-dir"], capture_output=True, text=True, check=True).stdout.strip()
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            dataset.Writer(Path(common).parent / "replay-out", {})
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            dataset.refuse_repository(Path(common).parent / "prior.json")

    def test_refuses_a_used_directory(self):
        from duoforge_replay import dataset
        self.write("used")
        with self.assertRaisesRegex(ValueError, "not empty"):
            dataset.Writer(self.tmp / "used", {})

    def test_counters_add_up(self):
        from duoforge_replay import build
        out = self.tmp / "counted"
        c = build.build([self.source], self.prior_path, out, workers=1, chunk=2, stats_factory=stats_factory)
        skipped = sum(v for k, v in c.items() if k.startswith("games.skipped."))
        internal = sum(v for k, v in c.items() if k.startswith("internal:"))
        self.assertEqual(c["games.read"], c["games.processed"] + skipped + internal)
        stopped = sum(v for k, v in c.items() if k.startswith("perspectives.stopped."))
        self.assertEqual(c["perspectives.kept"] + stopped, 2 * c["games.processed"])

    def test_workers_same_bytes(self):
        from duoforge_replay import build
        outs = []
        for workers in (1, 2):
            out = self.tmp / f"w{workers}"
            counters = build.build([self.source], self.prior_path, out, workers=workers, chunk=1,
                                   stats_factory=stats_factory)
            self.assertEqual(counters["games.skipped.skip:format"], 1)
            self.assertEqual(counters["games.processed"], 3)
            outs.append(out)
        for path in sorted(outs[0].iterdir()):
            if path.name != "manifest.json":
                self.assertEqual(_sha(path), _sha(outs[1] / path.name), path.name)


class _FakeParquet:
    """pyarrow.parquet for one fake file: two row groups, the first of another format."""

    class _Column:
        def __init__(self, values):
            self.values = values

        def to_pylist(self):
            return list(self.values)

    class _Table:
        def __init__(self, rows, columns):
            self.cols = {c: [r[c] for r in rows] for c in columns}

        def column(self, c):
            return _FakeParquet._Column(self.cols[c] if isinstance(c, str) else list(self.cols.values())[c])

    class ParquetFile:
        groups = [[{"id": "a", "formatid": "gen9ou", "log": ""}, {"id": "b", "formatid": "gen9ou", "log": ""}],
                  [{"id": "c", "formatid": "gen9championsvgc2026regmc", "log": "x"}]]

        def __init__(self, path):
            self.metadata = type("M", (), {"num_row_groups": 2})()

        def read_row_group(self, group, columns):
            return _FakeParquet._Table(self.groups[group], columns)


class SourceTest(unittest.TestCase):
    def test_skipped_row_groups_are_counted(self):
        import collections
        import types
        from duoforge_replay import source
        fake = types.ModuleType("pyarrow.parquet")
        fake.ParquetFile = _FakeParquet.ParquetFile
        package = types.ModuleType("pyarrow")
        package.parquet = fake
        saved = {k: sys.modules.get(k) for k in ("pyarrow", "pyarrow.parquet")}
        sys.modules.update({"pyarrow": package, "pyarrow.parquet": fake})
        try:
            tmp = Path(tempfile.mkdtemp(prefix="duoforge_source_"))
            (tmp / "x.parquet").write_bytes(b"")
            counters = collections.Counter()
            rows = list(source.select(source.games([tmp], "gen9championsvgc2026regmc", counters),
                                      "gen9championsvgc2026regmc", counters))
            shutil.rmtree(tmp, ignore_errors=True)
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        self.assertEqual(counters["games.read"], 3)
        self.assertEqual(counters["games.skipped.skip:format"], 2)
        self.assertEqual(counters["games.skipped.skip:sheets"], 1)
        self.assertEqual(rows, [])

    def test_select(self):
        import collections
        from duoforge_replay import source
        log2 = "|showteam|p1|x\n|showteam|p2|y"
        rows = [("a", "gen9championsvgc2026regmc", log2), ("b", "gen9ou", log2),
                ("c", "gen9championsvgc2026regmcbo3", "|showteam|p1|x"), ("d", "gen9championsvgc2026regmcbo3", log2)]
        counters = collections.Counter()
        kept = list(source.select(rows, "gen9championsvgc2026regmc", counters))
        self.assertEqual([r[0] for r in kept], ["a", "d"])
        self.assertEqual(counters["games.skipped.skip:format"], 1)
        self.assertEqual(counters["games.skipped.skip:sheets"], 1)


if __name__ == "__main__":
    unittest.main()
