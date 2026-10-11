"""duoforge.python.pkmn_arena_net: the PKMN Arena mode with a real network (JAX), a fake websocket only.

A tiny synthetic checkpoint in the BC file format (duoforge_learn.bc: model v2, encoder 6, the BC extension mask, pool
data with the library's fingerprint) stands in for the private BC6 weights, which are never committed. The live client
loads it as its own network in its trained layout, and the arena bot plays the open-team-sheet fixture with it raw and
with the honest search: the revealed sheets go to the network and the search, and no decision falls back.
"""
import asyncio
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import duoforge
from duoforge import _layout, features

from duoforge_live import data, pkmn_arena, policy as live_policy, search as live_search
from python.tests.test_live_client import FIXTURE
from python.tests.test_pkmn_arena import ENV, NAME, OTS, ROOM, battle_messages, request_of

C = _layout.CONSTANTS


class ArenaNetworkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import jax
        from duoforge_learn import bc_data, checkpoint, policy
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "bc.npz")
        model_config = policy.v2_config("S")
        params = policy.make(model_config).init(jax.random.PRNGKey(6))
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            cls.mask = bc_data.bc_mask(ctx)
            config = {"model": model_config, "encoder": features.ENCODER, "ext_supported": cls.mask,
                      "features": list(features.FEATURE_NAMES), "slot_features": list(features.SLOT_FEATURE_NAMES),
                      "data": {"kind": "pool", "fingerprint": ctx.fingerprint().hex()}, "teams": [], "update": 0,
                      "decisions": 0, "ids": checkpoint.ids_of(ctx)}
        checkpoint.save(cls.path, params, config)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        patch = mock.patch.dict(os.environ, ENV)
        patch.start()
        self.addCleanup(patch.stop)
        self.logs = tempfile.TemporaryDirectory()
        self.addCleanup(self.logs.cleanup)
        self.sent = []

    def play(self, search=None):
        net, tables = live_policy.load(self.path), data.for_checkpoint(self.path)
        bot = pkmn_arena.ArenaBot(NAME, tables, net, self.logs.name, OTS, team_text=FIXTURE["team"], search=search,
                                  mode="raw" if search is None else "honest")
        self.addCleanup(bot.close)

        async def send(text):
            self.sent.append(text)

        async def go():
            bot.connection = type("Socket", (), {"send": staticmethod(send)})()
            for m in battle_messages():
                await bot.handle(m)
        with contextlib.redirect_stderr(io.StringIO()):
            asyncio.run(go())
        return bot

    def chosen(self):
        return [s for s in self.sent if "/choose" in s]

    def test_a_bc_checkpoint_of_encoder_6_loads_as_its_own_network(self):
        net = live_policy.load(self.path)
        self.assertIsInstance(net, live_policy.ModelPolicy)
        self.assertEqual(net.encoder, 6)
        self.assertEqual(features.ENCODER, 6)
        self.assertEqual(net.ext_supported, self.mask)
        self.assertEqual(data.for_checkpoint(self.path).kind, "pool")

    def test_raw_play_of_an_ots_battle(self):
        bot = self.play()
        rqids = [request_of(k)["rqid"] for k in (2, 5, 7, 9)]
        sent = self.chosen()
        self.assertEqual([s.rsplit("|", 1)[1] for s in sent], [str(r) for r in rqids])
        self.assertTrue(all(s.startswith(f"{ROOM}|/choose ") and "default" not in s for s in sent), sent)
        self.assertEqual(dict(bot.run_log.fallback_battles), {})
        self.assertEqual(bot.run_log.counts["decisions"], 4)

    def test_an_honest_search_decision_with_the_revealed_sheets(self):
        live = live_search.load(self.path)
        with mock.patch.object(live_search, "DEADLINE_CAP", 120.0):  # the first decision compiles the network
            bot = self.play(search=live)
        text = Path(self.logs.name, f"{ROOM}-tiansuan.jsonl").read_text(encoding="utf-8")
        game_log = [json.loads(line) for line in text.splitlines()]
        outcomes = [r["search"] for r in game_log if "search" in r]
        self.assertEqual(len(outcomes), 4)
        self.assertEqual(outcomes[0]["cause"], "team")  # the team preview stays raw
        self.assertIn("searched", [o["cause"] for o in outcomes[1:]], outcomes)
        self.assertFalse([o for o in outcomes if o["fallback"] == "b"], outcomes)
        self.assertIsNone(bot.paused)
        self.assertEqual(dict(bot.run_log.fallback_battles), {})
        self.assertNotIn("default", " ".join(self.chosen()))
        self.assertGreaterEqual(bot.run_log.search["searched"], 1)


if __name__ == "__main__":
    unittest.main()
