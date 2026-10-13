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

from duoforge_live import cts, data, pkmn_arena, policy as live_policy, search as live_search
from python.tests.live.test_live_client import FIXTURE
from python.tests.live.test_pkmn_arena import CTS, ENV, NAME, OTS, ROOM, battle_messages, request_of

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

    def play(self, search=None, fmt=OTS, messages=None):
        net, tables = live_policy.load(self.path), data.for_checkpoint(self.path)
        bot = pkmn_arena.ArenaBot(NAME, tables, net, self.logs.name, fmt, team_text=FIXTURE["team"], search=search,
                                  mode="raw" if search is None else "honest")
        self.addCleanup(bot.close)

        async def send(text):
            self.sent.append(text)

        async def go():
            bot.connection = type("Socket", (), {"send": staticmethod(send)})()
            for m in messages or battle_messages():
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
        live = live_search.load(self.path, foe_net=None)  # the search alone; the next test adds the foe net
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

    def test_the_recommended_search_models_the_foe_with_the_same_bc_file(self):
        # Owner, 2026-10-12: the honest search with foe_net = BC6, the same file as the network (M7: F 0.892 against
        # M 0.862). The search's worlds take the foe's policy from the foe network, encoded with its own encoder.
        foe, check = pkmn_arena.load_foe_net(self.path, pkmn_arena.sha256_of(self.path))
        self.assertEqual(foe[2:], (6, self.mask))
        self.assertEqual(check["ids"], "same tables")
        with self.assertRaisesRegex(ValueError, "pinned"):
            pkmn_arena.load_foe_net(self.path, "0" * 64)
        live = live_search.load(self.path, dict(live_search.HONEST_SETTINGS, foe_net=foe))
        self.assertIsNotNone(live.searcher.foe_net)
        self.assertEqual(live.searcher.foe_net[2:], (6, self.mask))
        with mock.patch.object(live_search, "DEADLINE_CAP", 120.0):
            bot = self.play(search=live)
        text = Path(self.logs.name, f"{ROOM}-tiansuan.jsonl").read_text(encoding="utf-8")
        outcomes = [json.loads(line)["search"] for line in text.splitlines() if '"search"' in line]
        self.assertIn("searched", [o["cause"] for o in outcomes], outcomes)
        self.assertFalse([o for o in outcomes if o["fallback"] == "b"], outcomes)
        self.assertEqual(dict(bot.run_log.fallback_battles), {})
        self.assertNotIn("default", " ".join(self.chosen()))

    def test_an_honest_search_over_the_particles_of_a_closed_sheet_battle(self):
        # Decision 0081 (#385 step 4): the CTS format played with the live search, its 16 worlds built from the 16
        # particles' own records (assembled by the tracker, each checked by the search's round trip), the foe modelled
        # by the foe network: the turns are searched and nothing falls back.
        foe, _ = pkmn_arena.load_foe_net(self.path, pkmn_arena.sha256_of(self.path))
        live = live_search.load(self.path, dict(live_search.HONEST_SETTINGS, foe_net=foe))
        self.assertEqual(live.searcher.s, cts.PARTICLES)
        room_id = f"battle-{CTS}-8"
        messages = [m.replace(ROOM, room_id) for m in battle_messages()]
        messages = ["\n".join(line for line in m.split("\n") if not line.startswith("|showteam|")) for m in messages]
        with mock.patch.object(live_search, "DEADLINE_CAP", 120.0):  # the first decisions compile the networks
            bot = self.play(search=live, fmt=CTS, messages=messages)
        text = Path(self.logs.name, f"{room_id}-tiansuan.jsonl").read_text(encoding="utf-8")
        outcomes = [json.loads(line)["search"] for line in text.splitlines() if '"search"' in line]
        self.assertEqual(len(outcomes), 4)
        self.assertEqual(outcomes[0]["cause"], "team")
        self.assertIn("searched", [o["cause"] for o in outcomes[1:]], outcomes)
        self.assertFalse([o for o in outcomes if o["fallback"] == "b"], outcomes)
        self.assertIsNone(bot.paused)
        self.assertEqual(dict(bot.run_log.fallback_battles), {})
        self.assertEqual(bot.run_log.cts["battles"], 1)
        self.assertNotIn("default", " ".join(self.chosen()))


BC6 = os.environ.get("DUOFORGE_BC6", "/mnt/c/Dev/datasets/m11-bc-runs/bc6-M/bc.npz" if os.name != "nt"
                     else r"C:\Dev\datasets\m11-bc-runs\bc6-M\bc.npz")


@unittest.skipUnless(os.path.exists(BC6), "the private BC6 file is not on this machine (never committed)")
class PrivateBc6Test(unittest.TestCase):
    def test_bc6_starts_on_the_current_library(self):
        # BC6 was trained on older pool tables (another fingerprint); its embedded ids carry over to today's tables
        net, tables = live_policy.load(BC6), data.for_checkpoint(BC6)
        self.assertEqual((net.encoder, tables.kind), (6, "pool"))
        self.assertIn(tables.checkpoint_check["ids"], ("same tables", "carried over"))
        foe, check = pkmn_arena.load_foe_net(BC6)
        self.assertEqual(check, tables.checkpoint_check)
        self.assertEqual(pkmn_arena.sha256_of(BC6), live_search.FOE_NET_SHA256)  # the live default's full pin


if __name__ == "__main__":
    unittest.main()
