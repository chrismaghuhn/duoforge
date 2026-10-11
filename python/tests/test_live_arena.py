"""duoforge.python.live_arena: the pure parts of the live-path arena (issue #362): the predeclared pairs and gates.

The arena itself runs the real live client against a local Showdown server (python -m duoforge_live.arena); its
result is a private report. Under test here: the pairs are a pure function of the pool and the seed, every pair is
played with the seats' teams swapped, a game's log is read as the search bot saw it, and the gates are the owner's.
"""
import json
import tempfile
import unittest
from pathlib import Path

from duoforge_live import arena


def _game(pair, game, result, summary=None, **extra):
    return {"pair": pair, "game": game, "result": result,
            "summary": summary or {"causes": {"team": 1, "searched": 19}, "fallback": {}}, "seconds": [0.5] * 19,
            **extra}


class Arena(unittest.TestCase):
    def test_pairs_are_drawn_from_the_seed_and_played_swapped(self):
        ids = [f"T{i}" for i in range(20)]
        pairs = arena.draw_pairs(ids, 50, 7)
        self.assertEqual(pairs, arena.draw_pairs(ids, 50, 7))
        self.assertNotEqual(pairs, arena.draw_pairs(ids, 50, 8))
        self.assertTrue(all(a != b for a, b in pairs))
        games = arena.schedule(pairs[:2])
        self.assertEqual(games, [(0, 0, pairs[0][0], pairs[0][1]), (0, 1, pairs[0][1], pairs[0][0]),
                                 (1, 0, pairs[1][0], pairs[1][1]), (1, 1, pairs[1][1], pairs[1][0])])

    def test_the_gates_are_the_owners(self):
        self.assertEqual(arena.GATES, {"lower_bound": 0.50, "crashes": 0, "class_b": 0, "raw_fallback_share": 0.05,
                                       "deadline_share": 0.01, "tracker_stop_share": 0.01, "timer_losses": 0,
                                       "p99_seconds": 2.0})
        strong = [_game(k, g, "win" if (k + g) % 4 else "loss") for k in range(100) for g in (0, 1)]
        report = arena.evaluate(strong, planned=200)
        self.assertTrue(report["pass"], report)
        self.assertGreater(report["lower_bound"], 0.5)
        for broken, gate in ((dict(forfeit="ValueError: boom"), "crashes"), (dict(dirty="SearchError: x"), "class_b"),
                             (dict(timer_loss=True), "timer_losses"), (dict(crash="lane"), "crashes")):
            games = list(strong)
            games[0] = {**games[0], **broken}
            with self.subTest(gate=gate):
                self.assertFalse(arena.evaluate(games, planned=200)["gates"][gate])
        stops = list(strong)
        for i in range(3):  # 3 of 200 games stop the tracker: above 1%
            stops[i] = {**stops[i], "forfeit": "stop:feature:TAUNT"}
        report = arena.evaluate(stops, planned=200)
        self.assertEqual((report["tracker_stops"], report["crashes"]), (3, 0))
        self.assertFalse(report["gates"]["tracker_stop_share"])
        fallback = [_game(k, g, "win", {"causes": {"searched": 9, "unreconstructible": 1}, "fallback": {"a": 1}})
                    for k in range(100) for g in (0, 1)]
        self.assertFalse(arena.evaluate(fallback, planned=200)["gates"]["raw_fallback_share"])  # 10% of the decisions
        even = [_game(k, g, "win" if g == 0 else "loss") for k in range(100) for g in (0, 1)]
        self.assertFalse(arena.evaluate(even, planned=200)["gates"]["lower_bound"])  # 0.5 exactly is no pass

    def test_every_planned_game_must_be_scored(self):
        # Review of #401: a game that never ends, a missing game (a lane stopped) or a pair with one scored game fails
        # the arena; none of them may drop out of the score in silence.
        strong = [_game(k, g, "win" if (k + g) % 4 else "loss") for k in range(100) for g in (0, 1)]
        self.assertTrue(arena.evaluate(strong, planned=200)["pass"])
        unfinished = list(strong)
        unfinished[5] = {**unfinished[5], "result": "not_finished"}
        report = arena.evaluate(unfinished, planned=200)
        self.assertEqual((report["not_finished"], report["incomplete_pairs"]), (1, 1))
        self.assertFalse(report["gates"]["all_played"])
        self.assertFalse(arena.evaluate(strong[:150], planned=200)["gates"]["all_played"])  # a lane stopped early

    def test_the_arena_plays_on_a_local_server_only(self):
        # Review of #401: the arena never logs in, challenges or turns timers on at a public server.
        for host in ("localhost", "127.0.0.1", "::1", "172.22.224.1", "192.168.1.5", "10.0.0.2"):
            arena.check_host(host)
        for host in ("sim3.psim.us", "play.pokemonshowdown.com", "8.8.8.8", "example.org", ""):
            with self.subTest(host=host), self.assertRaises(SystemExit):
                arena.check_host(host)

    def test_a_game_is_read_from_the_search_bots_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp, "battle-x-dfarena0sbot.jsonl")
            lines = [{"in": "|turn|1"}, {"decision": 3, "search": {"cause": "searched", "seconds": 0.4}},
                     {"decision": 1, "search": {"cause": "team", "seconds": 0.01}},
                     {"in": "|win|dfarena0sbot"}, {"end": "|win|dfarena0sbot"},
                     {"summary": {"causes": {"searched": 1}, "fallback": {}}}]
            log.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
            game = arena.read_game(log, "dfarena0sbot")
        self.assertEqual((game["result"], game["seconds"], game["forfeit"]), ("win", [0.4], None))
        self.assertEqual(game["summary"]["causes"], {"searched": 1})


if __name__ == "__main__":
    unittest.main()
