"""The luck meter (#494) on the committed pool battle g45_moxie_win as player 1's closed-sheet log
(python/tests/support/data/cts_luck_g45.jsonl), valued by a tiny synthetic checkpoint (no weights of ours): the
replayed honest search's own worlds, the foe's action each world reads from the turn's lines, the engine's leaves."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from duoforge_live import cts, cts_luck, data, options, pkmn_arena, policy as live_policy, search as live_search, teams
from python.tests.live import test_cts_replay
from python.tests.live.test_pkmn_arena import ENV

BATTLE = "g45_moxie_win"
SWITCH = "g90_end_fz90_195"  # the foe switches by choice on turn 9
PIVOT = "g71_faint_source_herb"  # the foe's pivot inside a turn: player 1 waits
BOT = "p1"  # the stream's player name


def text(option, side):
    """An option's Showdown text, as the foe would have sent it (moves and passes: what this battle holds)."""
    if option.kind == options.PASS:
        return "pass"
    if option.kind != options.MOVE:
        raise ValueError(f"option kind {option.kind} in a test of moves")
    aim = "" if option.target == options.TARGET_NONE else " " + options._location(side, option.target)
    return f"move {option.move_slot + 1}{aim}" + (" mega" if option.mega else "")


class MeterTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from duoforge_live.data import ROOT, trace_to_c
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = test_cts_replay.ReplayTest.checkpoint(cls.tmp.name)
        cls.battles = {}
        for number, (name, fixture) in enumerate(((BATTLE, "cts_luck_g45.jsonl"), (SWITCH, "cts_luck_g90.jsonl"),
                                                  (PIVOT, "cts_luck_g71.jsonl"))):
            log = os.path.join(cls.tmp.name, f"battle-gen9championsvgc2026regmc-{45 + number}-{BOT}.jsonl")
            shutil.copyfile(ROOT / "python" / "tests" / "support" / "data" / fixture, log)
            spec, trace = trace_to_c.load_battle(str(ROOT), name)
            cls.battles[name] = (log, spec["teams"][0], teams._paste(spec["teams"][1]), trace)
        cls.log, cls.own, cls.foe, cls.trace = cls.battles[BATTLE]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def battle(self, samples=cts_luck.SAMPLES, foe=None, name=BATTLE):
        log, own, true_foe, _ = self.battles[name]
        with mock.patch.dict(os.environ, ENV):
            live = live_search.load(self.path, foe_net=self.path, foe_net_sha256=pkmn_arena.sha256_of(self.path))
        self.addCleanup(live.close)
        live.searcher = cts.Capture(live.searcher)
        net, tables = live_policy.load(self.path), data.for_checkpoint(self.path)
        meter = cts_luck.Meter(live.searcher.searcher, samples)
        self.addCleanup(meter.close)
        played, rosters, real = [], [], meter.expected

        def expected(*args):
            value = real(*args)
            played.append(list(meter.last["foe"]))
            rosters.append(list(meter.last["rosters"]))
            return value
        meter.expected = expected
        prior = cts.SetPrior(tables, true_foe if foe is None else foe)
        out = cts_luck.battle(log, tables, net, live, own, BOT, prior, meter)
        self.rosters = rosters
        return out, played

    @staticmethod
    def texts(played):
        """Per turn, per world: the set of the foe's pairs as Showdown text."""
        return [[{f"{text(a, 1)}, {text(b, 1)}" for a, b in pairs} for pairs in worlds] for worlds in played]

    def test_the_meter_values_each_turn_with_the_foes_action_of_the_log_in_every_world(self):
        out, played = self.battle()
        played = self.texts(played)
        self.assertEqual(dict(out["excluded"]), {})
        self.assertEqual(out["result"], 1.0)
        # turn 1 (its state: the foe's replacement, a wait point), turn 2, and turn 3, which ends the battle: the foe's
        # Ampharos faints before it moves, its move never shows, and the turn is mixed over its move options
        self.assertEqual(len(out["turns"]), 3)
        self.assertEqual(out["mixed"], [False, False, True])
        self.assertEqual(out["dropped"], [0, 0, 0])  # the true team: no world the turns refute
        for luck in out["turns"]:
            self.assertTrue(-2.0 <= luck <= 2.0, luck)
        foe_inputs = [self.trace["steps"][k]["input"]["p2"] for k in (1, 3, 4)]
        self.assertEqual(len(played), 3)
        for turn, worlds in zip(foe_inputs[:2], played[:2]):
            self.assertEqual(worlds, [{turn}] * len(worlds))  # every world: the trace's foe choice, alone
        for pairs in played[2]:  # every world: a set of more than one pair that holds the trace's choice
            self.assertIn(foe_inputs[2], pairs)
            self.assertGreater(len(pairs), 1)


    def test_a_world_the_turn_refutes_is_left_out(self):
        # A second Pikachu set without Thunderbolt: the worlds that drew it cannot play turn 1, where Pikachu uses
        # Thunderbolt for the first time (the particle filter draws them anew after the turn); the turn is valued on the
        # others, every one with the trace's foe choice.
        other = teams._paste("Pikachu (M) @ Light Clay\nAbility: Static\nLevel: 50\nTimid Nature\n- Grass Knot\n"
                             "- Protect\n")
        out, played = self.battle(foe=self.foe + other)
        played = self.texts(played)
        self.assertEqual(len(out["turns"]), 3)
        self.assertGreater(out["dropped"][0], 0)
        self.assertLess(out["dropped"][0], out["worlds"])
        self.assertEqual(played[0], [{self.trace["steps"][1]["input"]["p2"]}] * (out["worlds"] - out["dropped"][0]))


    def test_a_foes_switch_is_the_switch_option_of_every_world(self):
        # A world's engine roster is its own order (not the particle's): the switched-in member's option is found by its
        # species in the world's roster, so the switch turn is valued, never "unknown".
        out, played = self.battle(name=SWITCH)
        self.assertNotIn("foe-action-unknown", out["excluded"])
        switches = [worlds for worlds in played if any(o.kind == options.SWITCH for pairs in worlds
                                                       for pair in pairs for o in pair)]
        self.assertTrue(switches)
        log = self.battles[SWITCH][0]
        tables = data.load(kind="pool")
        shown = {tables.base_forme(tables.forme(line.split("|")[3].split(",")[0])) for line in
                 (json.loads(x).get("in", "") for x in Path(log).read_text(encoding="utf-8").splitlines())
                 if line.startswith("|switch|p2")}
        for worlds in switches:  # the worlds that played it, each with the shown member's switch
            # A world draws the foe's hidden bring (its pick order) itself: the worlds whose bench lacks the member the
            # log shows switching in cannot play the turn and are left out, the others play it.
            turn = played.index(worlds)
            self.assertTrue(0 < len(worlds) == out["worlds"] - out["dropped"][turn])
            for pairs, roster in zip(worlds, self.rosters[turn]):
                for k in (0, 1):
                    if pairs[0][k].kind == options.SWITCH:
                        self.assertEqual(len({(pair[k].kind, pair[k].reserve) for pair in pairs}), 1)
                        # the reserve, a roster index of the world, is a member the log shows switching in
                        self.assertIn(roster[pairs[0][k].reserve], shown)

    def test_the_rest_of_a_turn_after_a_foes_pivot_is_counted(self):
        out, _ = self.battle(name=PIVOT)
        self.assertGreater(out["partial"]["rest-after-foe-pivot"], 0)
        self.assertNotIn("rest-after-foe-pivot", out["excluded"])  # a valued turn, not an excluded one
        self.assertTrue(out["turns"])

    def test_the_meter_is_deterministic_and_takes_its_samples(self):
        first, _ = self.battle()
        self.assertEqual(first, self.battle()[0])
        self.assertNotEqual(first["turns"], self.battle(samples=2)[0]["turns"])

    def test_a_foe_slot_the_log_tells_nothing_of_is_excluded_and_a_hidden_move_is_a_set(self):
        ctx = type("Ctx", (), {"moves": (None, None), "member_of": staticmethod(lambda d: -1), "vacant": frozenset(),
                               "barred": ((), ()), "data": data.load(kind="pool")})()
        lists = [[options.Option(options.MOVE, 0, 0, 0, 0, ""), options.Option(options.MOVE, 1, 0, 0, 0, "")]] * 2
        with self.assertRaisesRegex(cts_luck.Excluded, "foe-action-unknown"):
            cts_luck.foe_shown([], 1, lists, ctx)  # no line: the game ended before anyone acted
        # the bot's move shows, the foe's never do (they fainted or left first): every move option, a set
        shown, reasons = cts_luck.foe_shown(["|move|p1a: Krookodile|Earthquake|p2b: Raichu|[spread] p2a,p2b"], 1, lists,
                                            ctx)
        self.assertEqual((shown, reasons), ([[0, 1], [0, 1]], ("move-hidden", "move-hidden")))


    def test_the_tool_aggregates_the_battles_luck_without_a_room_or_a_name(self):
        import importlib.util
        import json
        from pathlib import Path
        from duoforge_live.data import ROOT
        spec = importlib.util.spec_from_file_location("cts_live_eval", ROOT / "tools" / "research" / "cts_live_eval.py")
        ev = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ev)
        records = [json.loads(line) for line in Path(self.log).read_text(encoding="utf-8").splitlines() if line.strip()]
        sha = pkmn_arena.sha256_of(self.path)
        logs = os.path.join(self.tmp.name, "series")  # a series of 1ffa6a03's process: its run log, no code in the logs
        os.makedirs(logs, exist_ok=True)
        Path(logs, "arena-run-20261013T192334Z.json").write_text(json.dumps({"started": "2026-10-13T19:23:34Z"}),
                                                                 encoding="utf-8")
        with mock.patch.object(ev, "selected", lambda *args: iter([(Path(self.log), records, self.own)])), \
                mock.patch.object(cts.SetPrior, "from_table", lambda tables: cts.SetPrior(tables, self.foe)), \
                mock.patch.dict(os.environ, ENV):
            got = ev.luck_all(logs, BOT, ROOT, self.path, sha, self.path, sha, bot_commit="1ffa6a03")
        self.assertEqual((got["battles"], got["finished"]), (1, 1))
        self.assertEqual(got["turns_excluded"], {})
        self.assertEqual((got["turns_valued"], got["turns_mixed"]), (3, 1))
        self.assertEqual((got["samples"], got["checkpoint_sha256"]), (cts_luck.SAMPLES, sha))
        self.assertEqual(got["result"]["mean"], 1.0)
        text = json.dumps(got)
        self.assertNotIn("battle-", text)
        self.assertEqual((got["search_step"], got["bot_commit"]), ("0", "1ffa6a03"))
        # the fixture's decision records name no real search ({"cause": "fixture"}): every replayed one differs
        self.assertEqual(got["search_differs"], got["searches"])
        self.assertTrue(got["report_blocked"])
        with self.assertRaisesRegex(SystemExit, "pinned"):
            ev.luck_all(logs, BOT, ROOT, self.path, "0" * 64, self.path, sha, bot_commit="1ffa6a03")
        with self.assertRaisesRegex(SystemExit, "no process start"):
            ev.luck_all(logs, BOT, ROOT, self.path, sha, self.path, sha, bot_commit="deadbeef")
        with self.assertRaisesRegex(SystemExit, "--bot-commit"):
            ev.luck_all(logs, BOT, ROOT, self.path, sha, self.path, sha)

if __name__ == "__main__":
    unittest.main()
