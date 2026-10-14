"""The luck meter (#494) on the committed pool battle g45_moxie_win as player 1's closed-sheet log
(python/tests/support/data/cts_luck_g45.jsonl), valued by a tiny synthetic checkpoint (no weights of ours): the
replayed honest search's own worlds, the foe's action each world reads from the turn's lines, the engine's leaves."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from duoforge_live import cts, cts_luck, data, options, pkmn_arena, policy as live_policy, search as live_search, teams
from python.tests.live import test_cts_replay
from python.tests.live.test_pkmn_arena import ENV

BATTLE = "g45_moxie_win"
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
        cls.log = os.path.join(cls.tmp.name, f"battle-gen9championsvgc2026regmc-45-{BOT}.jsonl")
        shutil.copyfile(ROOT / "python" / "tests" / "support" / "data" / "cts_luck_g45.jsonl", cls.log)
        spec, cls.trace = trace_to_c.load_battle(str(ROOT), BATTLE)
        cls.own, cls.foe = spec["teams"][0], teams._paste(spec["teams"][1])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def battle(self, samples=cts_luck.SAMPLES, foe=None):
        with mock.patch.dict(os.environ, ENV):
            live = live_search.load(self.path, foe_net=self.path, foe_net_sha256=pkmn_arena.sha256_of(self.path))
        self.addCleanup(live.close)
        live.searcher = cts.Capture(live.searcher)
        net, tables = live_policy.load(self.path), data.for_checkpoint(self.path)
        meter = cts_luck.Meter(live.searcher.searcher, samples)
        self.addCleanup(meter.close)
        played, real = [], meter.expected

        def expected(*args):
            value = real(*args)
            played.append([{f"{text(a, 1)}, {text(b, 1)}" for a, b in pairs} for pairs in meter.last["foe"]])
            return value
        meter.expected = expected
        prior = cts.SetPrior(tables, self.foe if foe is None else foe)
        out = cts_luck.battle(self.log, tables, net, live, self.own, BOT, prior, meter)
        return out, played

    def test_the_meter_values_each_turn_with_the_foes_action_of_the_log_in_every_world(self):
        out, played = self.battle()
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
        self.assertEqual(len(out["turns"]), 3)
        self.assertGreater(out["dropped"][0], 0)
        self.assertLess(out["dropped"][0], out["worlds"])
        self.assertEqual(played[0], [{self.trace["steps"][1]["input"]["p2"]}] * (out["worlds"] - out["dropped"][0]))

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
        with mock.patch.object(ev, "selected", lambda *args: iter([(Path(self.log), records, self.own)])),                 mock.patch.object(cts.SetPrior, "from_table", lambda tables: cts.SetPrior(tables, self.foe)),                 mock.patch.dict(os.environ, ENV):
            got = ev.luck_all(self.tmp.name, BOT, ROOT, self.path, sha, self.path, sha)
        self.assertEqual((got["battles"], got["finished"]), (1, 1))
        self.assertEqual(got["turns_excluded"], {})
        self.assertEqual((got["turns_valued"], got["turns_mixed"]), (3, 1))
        self.assertEqual((got["samples"], got["checkpoint_sha256"]), (cts_luck.SAMPLES, sha))
        self.assertEqual(got["result"]["mean"], 1.0)
        text = json.dumps(got)
        self.assertNotIn("battle-", text)
        with self.assertRaisesRegex(SystemExit, "pinned"):
            ev.luck_all(self.tmp.name, BOT, ROOT, self.path, "0" * 64, self.path, sha)

if __name__ == "__main__":
    unittest.main()
