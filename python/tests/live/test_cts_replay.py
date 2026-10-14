"""The replay helpers of duoforge_live.cts (moved from the Search lane's ko_check, search/ko-check-cts b148e309): the
replay of a battle log the arena bot wrote with the honest search, open and closed team sheets (the open-team-sheet
fixture, a tiny synthetic checkpoint; no private log or weights)."""
import asyncio
import contextlib
import io
import json
import os
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

import duoforge
from duoforge import _layout, features

from duoforge_live import cts, data, pkmn_arena, policy as live_policy, search as live_search
from python.tests.live.test_live_client import FIXTURE
from python.tests.live.test_pkmn_arena import CTS, ENV, NAME, OTS, ROOM, battle_messages, room

C = _layout.CONSTANTS


class ReplayTest(unittest.TestCase):
    """The arena bot plays the fixture with the honest search and writes its log; the replay follows the log and its
    search decides every searched decision as the bot did."""

    @staticmethod
    def checkpoint(directory):
        """A tiny synthetic checkpoint (no weights of ours) in directory: its path."""
        import jax
        from duoforge_learn import bc_data, checkpoint, policy
        path = os.path.join(directory, "bc.npz")
        model_config = policy.v2_config("S")
        params = policy.make(model_config).init(jax.random.PRNGKey(6))
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            mask = bc_data.bc_mask(ctx)
            config = {"model": model_config, "encoder": features.ENCODER, "ext_supported": mask,
                      "features": list(features.FEATURE_NAMES), "slot_features": list(features.SLOT_FEATURE_NAMES),
                      "data": {"kind": "pool", "fingerprint": ctx.fingerprint().hex()}, "teams": [], "update": 0,
                      "decisions": 0, "ids": checkpoint.ids_of(ctx)}
        checkpoint.save(path, params, config)
        return path

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = cls.checkpoint(cls.tmp.name)
        cls.logs = os.path.join(cls.tmp.name, "logs")
        with mock.patch.dict(os.environ, ENV):
            live = live_search.load(cls.path, foe_net=cls.path, foe_net_sha256=pkmn_arena.sha256_of(cls.path))
            net, tables = live_policy.load(cls.path), data.for_checkpoint(cls.path)
            bot = pkmn_arena.ArenaBot(NAME, tables, net, cls.logs, OTS, team_text=FIXTURE["team"], search=live,
                                      mode="honest+foe_net")
            try:
                async def send(text):
                    pass

                async def go():
                    bot.connection = type("Socket", (), {"send": staticmethod(send)})()
                    for m in battle_messages():
                        await bot.handle(m)
                with mock.patch.object(live_search, "DEADLINE_CAP", 120.0), contextlib.redirect_stderr(io.StringIO()):
                    asyncio.run(go())
            finally:
                bot.close()
        cls.log = Path(cls.logs, f"{ROOM}-tiansuan.jsonl")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def load(self):
        live = live_search.load(self.path, foe_net=self.path, foe_net_sha256=pkmn_arena.sha256_of(self.path))
        self.addCleanup(live.close)
        live.searcher = cts.Capture(live.searcher)
        return live, live_policy.load(self.path), data.for_checkpoint(self.path)

    def test_the_replay_decides_each_searched_decision_as_the_bot_did(self):
        logged = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        searched = [r for r in logged if r.get("search", {}).get("cause") == "searched"]
        self.assertTrue(searched, "the fixture has no searched decision")
        live, net, tables = self.load()
        replayed = list(cts.replay(self.log, tables, net, live, FIXTURE["team"], 0))
        self.assertEqual([r["decision"] for _, r, _ in replayed], [r["decision"] for r in searched])
        for game, record, search_record in replayed:
            texts = cts.pair_texts(game, net)
            self.assertEqual(texts[record["sent"]], search_record["choice"])  # the logged choice, reproduced

    def test_each_replay_refuses_the_other_sheets_log_by_name(self):
        live, net, tables = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, f"battle-{OTS}-8-tiansuan.jsonl")
            path.write_text(json.dumps({"feed": ["|init|battle"]}) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(cts.Refused, "closed_sheets_log"):
                list(cts.replay(path, tables, net, live, FIXTURE["team"], 0))
            with self.assertRaisesRegex(cts.Refused, "open_sheets_log"):
                list(cts.replay_closed(self.log, tables, net, live, FIXTURE["team"], NAME, None, Counter()))
            with self.assertRaisesRegex(cts.Refused, "other_bot"):
                list(cts.replay_closed(path, tables, net, live, FIXTURE["team"], "Ling-Ce", None, Counter()))


def closed_messages(room_id, upto):
    """The open-sheet fixture's messages as a closed-sheet battle (test_pkmn_arena's closed_messages): no |showteam|."""
    return [room(["|init|battle"], room_id)] + \
        [room([l for l in m if not l.startswith("|showteam|")], room_id) for m in FIXTURE["messages"][:upto]]


def point(game):
    """A decision point as the bot and a replay see it: epoch, rqid, every particle's sets and record bytes."""
    return (game.epoch, game.request["rqid"], [p.sets for p in game.tracker.particles],
            [p["record"].tobytes() for p in game.tracker.public_parts()])


class ClosedReplayTest(unittest.TestCase):
    """Closed team sheets (#483; HS, 2026-10-14): the arena bot plays the fixture as a closed-sheet battle with the
    honest search over its particles; replay_closed replays its log through cts.LogReplay, the one replay core of the
    live evaluation, and draws the bot's particles at every decision point."""

    @classmethod
    def setUpClass(cls):
        from duoforge_live import game as game_module
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = ReplayTest.checkpoint(cls.tmp.name)
        cls.logs = os.path.join(cls.tmp.name, "logs")
        cls.room = f"battle-{CTS}-12"
        cls.seen, real = [], game_module.Game.candidates

        def candidates(g, *args, **kwargs):  # what the bot decided on, at every decision point
            cls.seen.append(point(g))
            return real(g, *args, **kwargs)
        with mock.patch.dict(os.environ, ENV):
            live = live_search.load(cls.path, foe_net=cls.path, foe_net_sha256=pkmn_arena.sha256_of(cls.path))
            net, tables = live_policy.load(cls.path), data.for_checkpoint(cls.path)
            bot = pkmn_arena.ArenaBot(NAME, tables, net, cls.logs, CTS, team_text=FIXTURE["team"], search=live,
                                      mode="honest+foe_net")
            cls.prior = bot.prior
            try:
                async def send(text):
                    pass

                async def go():
                    bot.connection = type("Socket", (), {"send": staticmethod(send)})()
                    for m in closed_messages(cls.room, 9):
                        await bot.handle(m)
                with mock.patch.object(live_search, "DEADLINE_CAP", 120.0), \
                        mock.patch.object(game_module.Game, "candidates", candidates), \
                        contextlib.redirect_stderr(io.StringIO()):
                    asyncio.run(go())
            finally:
                bot.close()
        cls.log = Path(cls.logs, f"{cls.room}-tiansuan.jsonl")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def load(self):
        live = live_search.load(self.path, foe_net=self.path, foe_net_sha256=pkmn_arena.sha256_of(self.path))
        self.addCleanup(live.close)
        live.searcher = cts.Capture(live.searcher)
        return live, live_policy.load(self.path), data.for_checkpoint(self.path)

    def records(self):
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_the_closed_replay_and_the_live_evaluation_draw_the_bots_particles_at_every_decision(self):
        # The acceptance test (HS): on the same log, seed and set prior, replay_closed and cts_live_eval (cts.LogReplay
        # with no policy, as its --replay runs it) draw the bot's particles and records at every decision point.
        from duoforge_live import game as game_module
        self.assertGreaterEqual(len(self.seen), 3)
        live, net, tables = self.load()
        evaluation = cts.LogReplay(self.records(), tables, None, FIXTURE["team"], self.prior,
                                   cts.room_of_log(self.log, NAME))
        self.assertEqual([point(g) for g, _ in evaluation], self.seen)
        self.assertIsNone(evaluation.stopped)
        replayed, real = [], game_module.Game.candidates

        def candidates(g, *args, **kwargs):
            replayed.append(point(g))
            return real(g, *args, **kwargs)
        counts = Counter()
        with mock.patch.object(game_module.Game, "candidates", candidates):
            rows = list(cts.replay_closed(self.log, tables, net, live, FIXTURE["team"], NAME, self.prior, counts))
        self.assertEqual(replayed, self.seen)
        self.assertTrue(rows)
        self.assertEqual(counts, Counter())  # every point has the bot's decision record

    def test_the_closed_replay_reproduces_every_searched_choice(self):
        logged = [r for r in self.records() if r.get("search", {}).get("cause") == "searched"]
        self.assertTrue(logged, "the closed fixture has no searched decision")
        live, net, tables = self.load()
        replayed = list(cts.replay_closed(self.log, tables, net, live, FIXTURE["team"], NAME, self.prior,
                                          Counter()))
        self.assertEqual([r["decision"] for _, r, _ in replayed], [r["decision"] for r in logged])
        for game, record, search_record in replayed:
            self.assertTrue(game.closed)
            texts = cts.pair_texts(game, net)
            self.assertEqual(texts[cts.logged_choice(record)], search_record["choice"])


if __name__ == "__main__":
    unittest.main()
