"""The KO check (#440): the pure parts on literals, and the replay of a battle log the arena bot wrote with the honest
search (the open-team-sheet fixture, a tiny synthetic checkpoint; no private log or weights)."""
import asyncio
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

import duoforge
from duoforge import _layout, features

from duoforge_live import data, pkmn_arena, policy as live_policy, search as live_search
from duoforge_search import ko_check, lookahead
from python.tests.live.test_live_client import FIXTURE
from python.tests.live.test_pkmn_arena import ENV, NAME, OTS, ROOM, battle_messages

C = _layout.CONSTANTS
EXACT, PERCENT = C["DUOFORGE_HP_EXACT"], C["DUOFORGE_HP_PERCENT"]


class PureTest(unittest.TestCase):
    def test_constants_fixed_before_the_first_run(self):
        self.assertEqual((ko_check.LIKELY, ko_check.SURE, ko_check.SAMPLES_PER_WORLD), (0.5, 0.9, 4))

    def test_fainted_counts_zero_hp_with_a_stated_kind_only(self):
        sides = np.zeros(2, _layout.OBSERVATION.fields["sides"][0].base)
        sides["members"]["hp"] = [[0, 5, 0, 7, 0, 0], [0, 0, 3, 3, 3, 3]]
        sides["members"]["hp_kind"] = [[EXACT, EXACT, EXACT, EXACT, 0, 0], [PERCENT, PERCENT, PERCENT, 0, 0, 0]]
        self.assertEqual(ko_check.fainted(sides, (EXACT, PERCENT)).tolist(), [2, 2])  # an unstated 0 is no faint

    def test_probe_plan_is_world_major_with_the_searchs_own_seed_first(self):
        w, i, j, sample = ko_check.probe_plan([10, 11], [[1, 2], [3]], 2, 2)
        self.assertEqual(list(zip(w.tolist(), i.tolist(), j.tolist(), sample.tolist())),
                         [(0, 0, 1, 0), (0, 0, 1, 2), (0, 0, 2, 0), (0, 0, 2, 2), (0, 1, 1, 0), (0, 1, 1, 2),
                          (0, 1, 2, 0), (0, 1, 2, 2), (1, 0, 3, 1), (1, 0, 3, 3), (1, 1, 3, 1), (1, 1, 3, 3)])

    def test_summarize_weights_worlds_and_columns(self):
        probes = {"own_ko": np.array([[[1.0, 0.0], [0.0, 0.0]], [[1.0, np.nan], [0.5, np.nan]]]),
                  "foe_ko": np.array([[[0.0, 1.0], [0.0, 0.25]], [[0.0, np.nan], [0.0, np.nan]]]),
                  "q": np.array([[0.75, 0.25], [1.0, 0.0]]), "foe_sets": [[7, 8], [9]]}
        facts = ko_check.summarize(probes, [0.5, 0.5])
        np.testing.assert_allclose(facts["ko"], [0.5 * 0.75 + 0.5 * 1.0, 0.5 * 0.5])
        np.testing.assert_allclose(facts["threat"], [0.5 * 1.0, 0.5 * 0.25])
        self.assertEqual(facts["worst"].tolist(), [[8, 8], [9, 9]])

    def test_classify_names_each_group(self):
        own, candidates = [1, 2, 3, 4], [1, 2]
        # a KO only by pair 3, not a candidate; played 1
        got = ko_check.classify(own, [0.1, 0.2, 0.95, 0.0], [0, 0, 0, 0], candidates, 1, 1, 0.9)
        self.assertEqual(got["own"], {"available": True, "played": False, "missed": "not_candidate"})
        # a KO by candidate 2, not chosen
        got = ko_check.classify(own, [0.1, 0.6, 0.0, 0.0], [0, 0, 0, 0], candidates, 1, 1, 0.5)
        self.assertEqual(got["own"]["missed"], "candidate_not_chosen")
        # played the KO
        got = ko_check.classify(own, [0.6, 0.0, 0.0, 0.0], [0, 0, 0, 0], candidates, 1, 1, 0.5)
        self.assertEqual(got["own"], {"available": True, "played": True})
        # the foe threatens the raw pair; only pair 4 (no candidate) stays below; played 1
        got = ko_check.classify(own, [0] * 4, [1.0, 0.8, 0.9, 0.1], candidates, 1, 1, 0.5)
        self.assertEqual(got["foe"], {"threatened": True, "answered": False, "missed": "not_candidate"})
        got = ko_check.classify(own, [0] * 4, [1.0, 0.1, 0.9, 0.9], candidates, 1, 1, 0.5)
        self.assertEqual(got["foe"]["missed"], "candidate_not_chosen")
        got = ko_check.classify(own, [0] * 4, [1.0, 0.9, 0.9, 0.9], candidates, 1, 1, 0.5)
        self.assertEqual(got["foe"]["missed"], "unavoidable")
        got = ko_check.classify(own, [0] * 4, [1.0, 0.1, 0.9, 0.9], candidates, 2, 1, 0.5)
        self.assertEqual(got["foe"], {"threatened": True, "answered": True})
        with self.assertRaisesRegex(ValueError, "not probed"):
            ko_check.classify(own, [0] * 4, [0] * 4, candidates, 9, 1, 0.5)

    def test_known_is_the_weight_share_of_threatening_worlds_with_a_known_worst_column(self):
        worst = np.array([[5], [6], [7]])
        worst_ko = np.array([[1.0], [1.0], [0.0]])
        got = ko_check.classify([1], [0.0], [1.0], [1], 1, 1, 0.5, worst, worst_ko, [[5], [8], [7]], [0.25, 0.5, 0.25])
        self.assertAlmostEqual(got["foe"]["known"], 0.25 / 0.75)

    def test_aggregate_counts_each_group(self):
        def row(own, foe):
            return {"played_is_search": True, "0.5": {"own": own, "foe": foe}, "0.9": {"own": own, "foe": foe}}
        rows = [row({"available": True, "played": False, "missed": "not_candidate"},
                    {"threatened": True, "answered": False, "missed": "unavoidable", "known": 1.0}),
                row({"available": True, "played": True}, {"threatened": False, "answered": True})]
        got = ko_check.aggregate(rows)
        self.assertEqual(got["0.5"]["own"], {"available": 2, "played": 1, "not_candidate": 1})
        self.assertEqual(got["0.5"]["foe"], {"threatened": 1, "answered": 0, "unavoidable": 1})
        self.assertEqual(got["0.5"]["foe_known_mean"], 1.0)

    def test_room_of_a_log_file(self):
        self.assertEqual(ko_check.room_of(f"x/{ROOM}-tiansuan.jsonl"), ROOM)
        with self.assertRaises(ko_check.Refused):
            ko_check.room_of("x/arena-run-1.json")


class ReplayTest(unittest.TestCase):
    """The arena bot plays the fixture with the honest search and writes its log; the replay follows the log and its
    search decides every searched decision as the bot did."""

    @classmethod
    def setUpClass(cls):
        import jax
        from duoforge_learn import bc_data, checkpoint, policy
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "bc.npz")
        model_config = policy.v2_config("S")
        params = policy.make(model_config).init(jax.random.PRNGKey(6))
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            mask = bc_data.bc_mask(ctx)
            config = {"model": model_config, "encoder": features.ENCODER, "ext_supported": mask,
                      "features": list(features.FEATURE_NAMES), "slot_features": list(features.SLOT_FEATURE_NAMES),
                      "data": {"kind": "pool", "fingerprint": ctx.fingerprint().hex()}, "teams": [], "update": 0,
                      "decisions": 0, "ids": checkpoint.ids_of(ctx)}
        checkpoint.save(cls.path, params, config)
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
        live.searcher = ko_check._Capture(live.searcher)
        return live, live_policy.load(self.path), data.for_checkpoint(self.path)

    def test_the_replay_decides_each_searched_decision_as_the_bot_did(self):
        logged = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        searched = [r for r in logged if r.get("search", {}).get("cause") == "searched"]
        self.assertTrue(searched, "the fixture has no searched decision")
        live, net, tables = self.load()
        replayed = list(ko_check.replay(self.log, tables, net, live, FIXTURE["team"], 0))
        self.assertEqual([r["decision"] for _, r, _ in replayed], [r["decision"] for r in searched])
        for game, record, search_record in replayed:
            texts = ko_check.pair_texts(game, net)
            self.assertEqual(texts[record["sent"]], search_record["choice"])  # the logged choice, reproduced

    def test_a_decision_row_probes_with_the_engine(self):
        live, net, tables = self.load()
        game, record, search_record = next(ko_check.replay(self.log, tables, net, live, FIXTURE["team"], 0))
        row = ko_check.decision_row(game, net, live, record, search_record, 2)
        self.assertEqual(json.loads(json.dumps(row)), row)  # a private row is plain JSON
        self.assertTrue(row["played_is_search"])
        self.assertGreaterEqual(row["probed"], row["k"])
        self.assertEqual(row["refused"], 0)
        self.assertGreater(row["leaves"], 0)
        for key in ("ko_played", "ko_best", "threat_raw", "threat_played"):
            self.assertTrue(0.0 <= row[key] <= 1.0, (key, row[key]))
        self.assertLessEqual(row["ko_played"], row["ko_best"])
        for threshold in ("0.5", "0.9"):
            self.assertEqual(set(row[threshold]), {"own", "foe"})

    def test_an_arm_counts_its_own_choice_as_played(self):
        live, net, tables = self.load()
        game, record, search_record = next(ko_check.replay(self.log, tables, net, live, FIXTURE["team"], 0))
        row = ko_check.decision_row(game, net, live, record, search_record, 1, played_from="search")
        self.assertEqual(row["played"], "search")
        with self.assertRaisesRegex(ValueError, "played_from"):
            ko_check.decision_row(game, net, live, record, search_record, 1, played_from="raw")

    def test_probe_answers_from_the_leaves_engine_state(self):
        # The probe of a pair against a column is the engine's: the same leaf expanded again gives the same KO facts.
        live, net, tables = self.load()
        game, record, search_record = next(ko_check.replay(self.log, tables, net, live, FIXTURE["team"], 0))
        search, p = live.searcher.searcher, int(search_record["seat"])
        own = search_record["own_pairs"][:2]
        first = ko_check.probe(search, p, search_record["key"], own, search_record["foe_pairs"], 1)
        again = ko_check.probe(search, p, search_record["key"], own, search_record["foe_pairs"], 1)
        np.testing.assert_array_equal(first["own_ko"], again["own_ko"])
        np.testing.assert_array_equal(first["foe_ko"], again["foe_ko"])
        np.testing.assert_allclose(first["q"].sum(axis=1), 1.0)
        for world, columns in enumerate(first["foe_sets"]):
            self.assertTrue(set(search_record["foe_pairs"][world]) <= set(columns) or columns == [lookahead.NO_FOE])

    def test_the_cli_counts_step_zeros_own_choice_with_played_search(self):
        # Step 2's KO comparison (HS, 2026-10-13): step 0 counted by its own choice, as the arms are, not by the logged
        # move. The default of step 0 stays the log.
        team = os.path.join(self.tmp.name, "team.txt")
        with open(team, "w", encoding="utf-8") as f:
            f.write(FIXTURE["team"])
        for played in ("search", None):
            with self.subTest(played=played), tempfile.TemporaryDirectory() as out, \
                    mock.patch.dict(os.environ, ENV), contextlib.redirect_stdout(io.StringIO()):
                extra = [] if played is None else ["--played", played]
                ko_check.main(["--logs", self.logs, "--team", team, "--checkpoint", self.path, "--step", "0",
                               "--samples-per-world", "1", "--out", os.path.join(out, "r"), *extra])
                with open(os.path.join(out, "r", "report.json"), encoding="utf-8") as f:
                    report = json.load(f)
                with open(os.path.join(out, "r", "decisions.jsonl"), encoding="utf-8") as f:
                    rows = [json.loads(line) for line in f]
                self.assertEqual(report["played"], played or "log")
                self.assertTrue(rows)
                self.assertEqual({r["played"] for r in rows}, {played or "log"})
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            ko_check.main(["--logs", self.logs, "--team", team, "--checkpoint", self.path, "--played", "raw",
                           "--out", os.path.join(self.tmp.name, "never")])

    def test_the_cli_refuses_an_output_inside_the_repository(self):
        from duoforge_live.data import ROOT
        with self.assertRaises(SystemExit):
            ko_check.main(["--logs", self.logs, "--team", "x", "--checkpoint", self.path,
                           "--out", str(Path(ROOT, "ko-out"))])
        self.assertFalse(Path(ROOT, "ko-out").exists())


if __name__ == "__main__":
    unittest.main()
