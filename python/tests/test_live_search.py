"""duoforge.python.live_search: the live play mode --search honest (plan 2026-10-10-live-honest-search, Task 5).

The search itself is faked here (its decisions are test_honest's); under test are the owner's failure classes of
2026-10-10: (a) a named refusal plays that decision raw, logged and counted; (b) an unexpected error plays it raw,
marks the game dirty (the rest of it raw) and the session takes no new challenge until it is reviewed. The deadline is
min(2 s, 10% of the remaining turn time), read from the server's timer line.
"""
import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from duoforge_live import client, data, search, teams, tracker
from python.tests.test_live_client import FIXTURE, FOE, ROOM, FakePolicy, FakeServer, Clock, room

PARTS = {"request": None, "observation": None, "record": None, "status": 0, "causes": 0}


class Searcher:
    """Honest's decide() in shape: one record per decision, scripted by kind."""

    def __init__(self, kind="searched", reason=None, error=None, gate=None, causes=None):
        self.kind, self.reason, self.error, self.gate, self.causes = kind, reason, error, gate, causes
        self.calls = []

    def decide(self, roots, envs, seats, keys, last_step):
        self.calls.append((int(seats[0]), int(keys[0])))
        if self.gate is not None:
            self.gate.wait(5)
        if self.error is not None:
            raise self.error
        record = {"kind": self.kind, "choice": 7}
        if self.reason is not None:
            record["reason"] = self.reason
        if self.causes is not None:
            record["causes"] = self.causes
        return [7], [record]


class Roots:
    def __init__(self):
        self.set_calls = []

    def set(self, env, seat, **parts):
        self.set_calls.append((env, seat, parts))


def _decide(live, budget=1.0):
    observation = {"player": 1}
    with mock.patch.object(search, "_encoded", return_value=("obs", "slots", "pairs")):
        return live.decide({**PARTS, "observation": observation}, None, None, None, key=99, episode=3, budget=budget)


class LiveSearchTest(unittest.TestCase):
    def make(self, searcher):
        live = search.LiveSearch(searcher, roots=Roots())
        self.addCleanup(live.close)
        return live

    def test_a_searched_decision_plays_its_pair(self):
        live = self.make(Searcher())
        outcome = _decide(live)
        self.assertEqual((outcome.action, outcome.cause, outcome.fallback), (7, "searched", None))
        self.assertEqual(live.searcher.calls, [(1, 99)])
        env, seat, parts = live.roots.set_calls[0]
        self.assertEqual((env, seat, parts["episode"], parts["obs"], parts["pairs"]), (0, 1, 3, "obs", "pairs"))

    def test_a_named_refusal_is_class_a(self):
        live = self.make(Searcher("unreconstructible", "no spread prior for foe species [52]"))
        outcome = _decide(live)
        self.assertEqual((outcome.action, outcome.cause, outcome.fallback), (None, "unreconstructible", "a"))
        self.assertEqual(outcome.reason, "no spread prior for foe species [52]")

    def test_a_refusal_names_the_searchs_causes(self):
        # A refused public record says why (Honest's visible causes: a visible sleep or confusion, a possible Illusion,
        # a Substitute, ...); the class (a) count is read by cause, so the reason carries them.
        live = self.make(Searcher("unreconstructible", "DUOFORGE_E_UNSUPPORTED: public record",
                                  causes=["visible_sleep", "substitute"]))
        self.assertEqual(_decide(live).reason, "DUOFORGE_E_UNSUPPORTED: public record (visible_sleep, substitute)")
        same = self.make(Searcher("unreconstructible", "missing team-preview record",
                                  causes=["missing team-preview record"]))
        self.assertEqual(_decide(same).reason, "missing team-preview record")

    def test_forced_and_team_decisions_are_raw_without_fallback(self):
        for kind in ("forced", "raw", "team"):
            outcome = _decide(self.make(Searcher(kind)))
            self.assertEqual((outcome.action, outcome.cause, outcome.fallback), (None, kind, None), kind)

    def test_an_unexpected_error_is_class_b(self):
        for error in (search.SearchError("world 0 refused"), ValueError("bad"), KeyError("x")):
            outcome = _decide(self.make(Searcher(error=error)))
            self.assertEqual((outcome.action, outcome.fallback), (None, "b"))
            self.assertEqual(outcome.cause, "error")
            self.assertIn(type(error).__name__, outcome.reason)

    def test_an_unknown_kind_is_class_b(self):
        outcome = _decide(self.make(Searcher("surprise")))
        self.assertEqual((outcome.action, outcome.cause, outcome.fallback), (None, "error", "b"))

    def test_the_deadline_plays_raw_and_a_running_search_is_waited_for(self):
        gate = threading.Event()
        live = self.make(Searcher(gate=gate))
        late = _decide(live, budget=0.05)
        self.assertEqual((late.action, late.cause, late.fallback), (None, "deadline", "deadline"))
        busy = _decide(live, budget=0.05)  # the late search still runs: no second one beside it
        self.assertEqual((busy.action, busy.cause, busy.fallback), (None, "busy", "deadline"))
        self.assertEqual(len(live.searcher.calls), 1)
        gate.set()
        self.assertEqual(_decide(live).cause, "searched")
        self.assertEqual(len(live.searcher.calls), 2)

    def test_a_late_search_that_failed_is_still_class_b(self):
        gate = threading.Event()
        live = self.make(Searcher(gate=gate, error=search.SearchError("late failure")))
        self.assertEqual(_decide(live, budget=0.05).cause, "deadline")
        gate.set()
        outcome = _decide(live)
        self.assertEqual((outcome.cause, outcome.fallback), ("error", "b"))
        self.assertIn("late failure", outcome.reason)


class TimerTest(unittest.TestCase):
    def test_parse_timer(self):
        self.assertEqual(search.parse_timer("|inactive|Time left: 45 sec this turn | 300 sec total"), 45)
        self.assertEqual(search.parse_timer("|inactive|Time left: 7 sec this turn | 7 sec total | 20 sec grace"), 7)
        self.assertIsNone(search.parse_timer("|inactive|chris has 30 seconds left this turn."))
        self.assertIsNone(search.parse_timer("|c|chris|Time left: 45 sec this turn | 300 sec total"))
        self.assertTrue(search.timer_on("|inactive|Battle timer is ON: inactive players will automatically lose when "
                                        "time's up."))
        self.assertFalse(search.timer_on("|inactive|chris also wants the timer to be on."))

    def test_deadline(self):
        self.assertEqual(search.deadline_seconds(None, 0.0, 5.0), search.DEADLINE_CAP)
        self.assertEqual(search.deadline_seconds(45, 100.0, 101.0), 2.0)
        self.assertAlmostEqual(search.deadline_seconds(10, 100.0, 101.0), 0.9)
        self.assertEqual(search.deadline_seconds(3, 100.0, 104.0), 0.0)
        self.assertEqual((search.DEADLINE_CAP, search.DEADLINE_SHARE), (2.0, 0.10))


class ExtensionRecordTest(unittest.TestCase):
    def test_the_game_encodes_the_trackers_extension_record(self):
        # HauptSession, 2026-10-10: a network that reads view-extension record features (params-49333) plays live; the
        # Game encodes the tracker's OBSERVATION_EXT. A feature the tracker does not fold stops it at the line that
        # would set it (lines._feature), so until then its fields are truly zero.
        import numpy as np
        from duoforge import _layout, features
        from duoforge_live.game import Game
        from duoforge_live.policy import Policy
        rng = np.random.default_rng(2)
        shapes = {"t1": (features.OBS_SIZE, 8), "t2": (8, 8), "option_torso": (8, 4),
                  "option_features": (features.SLOT_FEATURES, 4), "option_out": (4, 2), "team": (8, 360),
                  "value": (8, 1)}
        params = {k: {"w": rng.normal(0, 1, s).astype(np.float32), "b": np.zeros(s[1], np.float32)}
                  for k, s in shapes.items()}
        mask = features.BASE_VALUE_FEATURES | (1 << features.FEATURE_BITS["PERISH"]) | \
            (1 << features.FEATURE_BITS["ENCORE"])
        game = Game(data.load(), Policy(params, features.ENCODER, mask), teams.text("A"))
        with mock.patch.object(features, "encode", wraps=features.encode) as encode:
            for lines in FIXTURE["messages"][:6]:
                game.feed(lines)
            game.candidates()
        call = encode.call_args_list[-1]
        self.assertEqual(call.args[3], mask)
        self.assertEqual(call.args[2].dtype, _layout.OBSERVATION_EXT)
        self.assertEqual(call.args[2].tobytes(), game.tracker.observation_ext().tobytes())


class FakeLive:
    """LiveSearch in shape: picks the highest allowed pair, or answers with a scripted outcome."""

    def __init__(self, outcomes=()):
        self.outcomes = list(outcomes)
        self.calls = []

    def decide(self, parts, obs_part, slot_part, pair_mask, *, key, episode, budget):
        self.calls.append({"key": key, "episode": episode, "budget": budget, "preview": pair_mask is None})
        if self.outcomes:
            return self.outcomes.pop(0)
        if pair_mask is None:
            return search.Outcome(None, "team", None, None, 0.01)
        return search.Outcome(int(pair_mask.reshape(-1).nonzero()[0][-1]), "searched", None, None, 0.01)

    def close(self):
        pass


class ClientSearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = FakeServer()
        self.clock = Clock()
        self.live = FakeLive()
        config = client.Config(name="DuoForgeBot", team="A", log_dir=self.tmp.name, team_link=None)
        self.bot = client.Bot(config, data.load(), FakePolicy(), login=lambda *a: "A", clock=self.clock,
                              team_texts={"A": FIXTURE["team"], "B": teams.text("B")}, search=self.live)
        self.bot.connection = self.server
        patch = mock.patch.object(tracker.Tracker, "public_parts", create=True, return_value=PARTS)
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        self.bot.close()
        self.tmp.cleanup()

    def feed(self, message):
        asyncio.run(self.bot.handle(message))

    def tick(self):
        asyncio.run(self.bot.tick())

    def start(self, upto=6, extra=None):
        self.feed(f"|pm| {FOE}| DuoForgeBot|/challenge gen9championsvgc2026regmc|gen9championsvgc2026regmc")
        self.server.take()
        self.feed(room(["|init|battle"] + (extra or [])))
        for lines in FIXTURE["messages"][:upto]:
            self.feed(room(lines))

    def chosen(self):
        return [s for s in self.server.take() if "/choose" in s]

    def log(self):
        (path,) = Path(self.tmp.name).iterdir()
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_the_searched_pair_is_sent_first_and_raw_order_follows(self):
        self.start()
        b = self.bot.battles[ROOM]
        raw = b.game.last_raw
        sent = self.chosen()[-1]
        self.assertEqual(sent, f"{ROOM}|/choose {raw[-1].text}|3")  # FakeLive takes the highest allowed pair
        self.assertEqual([c.text for c in b.candidates], [raw[-1].text] + [c.text for c in raw[:-1]])
        self.assertTrue(self.live.calls[0]["preview"])  # the team preview record is shown to the search, played raw
        self.assertEqual(self.live.calls[-1]["budget"], search.DEADLINE_CAP)  # no timer: the cap
        decisions = [r for r in self.log() if "search" in r]
        self.assertEqual(decisions[-1]["search"]["cause"], "searched")

    def test_class_a_plays_raw_and_counts(self):
        self.live.outcomes = [search.Outcome(None, "team", None, None, 0.0),
                              search.Outcome(None, "unreconstructible", "a", "no spread prior for foe species [52]", 0.1)]
        self.start()
        b = self.bot.battles[ROOM]
        self.assertEqual(self.chosen()[-1], f"{ROOM}|/choose {b.game.last_raw[0].text}|3")
        self.assertFalse(b.game.dirty)
        self.assertEqual(b.game.summary()["fallback"], {"a": 1})
        self.assertEqual(b.game.summary()["causes"]["unreconstructible"], 1)

    def test_class_b_marks_the_game_dirty_and_pauses_the_session(self):
        self.live.outcomes = [search.Outcome(None, "team", None, None, 0.0),
                              search.Outcome(None, "error", "b", "SearchError: world 0 refused", 0.1)]
        self.start(upto=8)
        b = self.bot.battles[ROOM]
        self.assertTrue(b.game.dirty)
        self.assertEqual(len(self.live.calls), 2)  # the rest of the game is raw: no further search
        self.assertGreater(b.game.summary()["causes"].get("dirty", 0), 0)
        self.assertTrue(self.bot.paused)
        self.assertTrue(any(r.get("dirty") == "SearchError: world 0 refused" for r in self.log()))
        self.feed(room([f"|win|{FOE}"]))
        summary = [r["summary"] for r in self.log() if "summary" in r]
        self.assertEqual(summary[-1]["fallback"], {"b": 1})
        self.server.take()
        self.feed(f"|pm| other| DuoForgeBot|/challenge gen9championsvgc2026regmc|gen9championsvgc2026regmc")
        self.assertEqual(self.server.take(), ["|/reject other", "|/pm other, " + client.PAUSED])

    def test_with_the_timer_on_the_decision_waits_for_its_timer_line(self):
        self.start(upto=5, extra=["|inactive|Battle timer is ON: inactive players will automatically lose when "
                                  "time's up."])
        self.server.take()
        self.feed(room(FIXTURE["messages"][5]))  # the move request: no choice before its timer line
        self.assertFalse(self.chosen())
        self.clock.now += 0.25
        self.feed(room(["|inactive|Time left: 10 sec this turn | 300 sec total"]))
        self.assertTrue(self.chosen())
        self.assertAlmostEqual(self.live.calls[-1]["budget"], 1.0)

    def test_a_missing_timer_line_is_waited_for_once_then_the_cap_is_logged(self):
        self.start(upto=5, extra=["|inactive|Battle timer is ON: inactive players will automatically lose when "
                                  "time's up."])
        self.server.take()
        self.feed(room(FIXTURE["messages"][5]))
        self.clock.now += client.TIMER_WAIT / 2
        self.tick()
        self.assertFalse(self.chosen())
        self.clock.now += client.TIMER_WAIT
        self.tick()
        self.assertTrue(self.chosen())
        self.assertEqual(self.live.calls[-1]["budget"], search.DEADLINE_CAP)
        self.assertTrue(any(r.get("timer") == "missing" for r in self.log()))

    def test_a_tracker_stop_forfeits_counted_by_its_reason(self):
        # Owner, 2026-10-10: a line the tracker cannot represent (an unfolded feature) ends the game with an explicit
        # forfeit, counted as stop:<reason> (the arena gate's own category), never played on.
        from duoforge_live import lines
        self.start(upto=4)
        with mock.patch.object(tracker.Tracker, "feed", side_effect=lines.Stop("feature:STEALTH_ROCK")):
            self.feed(room(FIXTURE["messages"][4]))
        self.assertEqual(self.server.take()[-2:], [f"{ROOM}|{client.INTERNAL}", f"{ROOM}|/forfeit"])
        self.assertIn({"forfeit": "stop:feature:STEALTH_ROCK"}, self.log())

    def test_the_search_option(self):
        import contextlib
        import io
        from duoforge_live import __main__ as cli
        base = ["--checkpoint", "x.npz", "--name", "DuoForgeBot"]
        self.assertEqual(cli._arguments(base).search, "raw")
        self.assertEqual(cli._arguments(base + ["--search", "honest"]).search, "honest")
        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stderr(io.StringIO()):
            cli._arguments(base + ["--search", "nash"])
        self.assertEqual(caught.exception.code, 2)
        # The live search's settings are the approved spec's: X (mix, lambda 0.5), K = M = 8, 16 worlds, the pinned
        # live spread table, a missing spread prior refused.
        self.assertEqual(search.HONEST_SETTINGS, {"k": 8, "m": 8, "s": 16, "rule": "mix", "lam": 0.5,
                                                  "species_prior": True})

    def test_raw_mode_is_unchanged(self):
        bot = client.Bot(client.Config(name="DuoForgeBot", team="A", log_dir=self.tmp.name, team_link=None), data.load(),
                         FakePolicy(), login=lambda *a: "A", clock=self.clock,
                         team_texts={"A": FIXTURE["team"], "B": teams.text("B")})
        self.assertIsNone(bot.search)
        bot.close()


if __name__ == "__main__":
    unittest.main()
