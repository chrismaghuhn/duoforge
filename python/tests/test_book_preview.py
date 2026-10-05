"""Synthetic preview books and tiny native-engine runs; no private data."""
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock

import numpy as np

import duoforge
import duoforge_learn
from duoforge import _layout, data, features, teams
from duoforge_learn import book_preview, evaluate, ladder
from duoforge_replay import book
from duoforge_search import arena, book_ab
from python.tests.test_learn_v2_numpy import _StandIn


class PreviewModel(_StandIn):
    def __init__(self):
        super().__init__("attack")
        self.applies = 0
        self.feature_names = features.FEATURE_NAMES

    def value(self, params, obs):
        return np.zeros(len(obs), dtype=np.float32)

    def apply(self, params, obs, slots, mask):
        self.applies += 1
        n = len(obs)
        probs = np.full((n, 360), 1e-12)
        probs[:, 0], probs[:, 1] = .6, .4
        return np.zeros((n, 1024)), np.log(probs), np.zeros(n)


class BookPreviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="duoforge_synthetic_preview_")
        self.addCleanup(self.tmp.cleanup)
        self.ctx = duoforge.Context()
        self.addCleanup(self.ctx.close)
        self.pool = teams.TeamPool.from_setups(("PP_fixture", "LL_fixture"), duoforge.reference_setups([0])["sides"][0])
        self.sheets = book_preview.sheets(self.ctx, self.pool)
        self.rows = book_ab.paired_rows(2, 2, seed=5)
        self.rows[0] = (0, 1, 0, 0)
        self.rows[1] = (1, 0, 1, 0)
        self.model = PreviewModel()
        self.raw = evaluate.Player(self.model, None, features.ENCODER, "synthetic")

    def row(self, count=20, wins=16, picks=(2, 3, 4, 5), backs=True):
        own, foe = self.sheets
        return {"source": "champions", "format": "gen9championsvgc2026regmc",
                "team_species": [m["species"] for m in own], "team_items": [m["item"] for m in own],
                "opposing_team_species": [m["species"] for m in foe],
                "leads": [own[i]["species"] for i in picks[:2]],
                "backs": [own[i]["species"] for i in picks[2:]] if backs else None,
                "opposing_leads": [m["species"] for m in foe[:2]],
                "rating_band": 1500, "opposing_rating_band": 1400,
                "count": count, "decisive_count": count, "wins": wins, "win_rate": wins / count}

    def evidence(self, rows=None):
        self.path = Path(self.tmp.name, "openings.json")
        self.path.write_text(json.dumps({"schema_version": 2, "tables": {
            "leads_per_team": [self.row()] if rows is None else rows, "turn_1_actions": []}}), encoding="utf-8")
        return book.load(self.path)

    def batch(self):
        batch = duoforge.Batch(self.ctx, self.pool.setups(self.rows["side0"], self.rows["side1"]), 1, 5)
        self.addCleanup(batch.close)
        for e in range(2):
            batch.reset(e, 1)
        batch.query()
        batch.query_factored()
        return batch

    def choose(self, player, batch):
        choices = np.zeros((2, 2), dtype=_layout.FACTORED_CHOICE)
        out = player.indices(batch, choices, step=0, seats=[0, 1], last_step=False)
        return out, choices

    def test_override_uses_highest_win_rate_not_highest_frequency(self):
        evidence = self.evidence([self.row(100, 50, picks=(0, 1, 2, 3)), self.row(20, 18)])
        player = book_preview.BookPlayer(self.raw, evidence, self.sheets, self.rows)
        batch = self.batch()
        out, choices = self.choose(player, batch)
        self.assertEqual(choices["picks"][0, 0, :4].tolist(), [2, 3, 4, 5])
        self.assertEqual(choices["picks"][1, 1, :4].tolist(), [2, 3, 4, 5])
        self.assertEqual(int(out[0, 0]), int(duoforge.joint_indices(batch.domains[0, :1], choices[0, :1])[0]))
        self.assertEqual(player.summary(games=2)["applied_share"], 1)

    def test_small_noisy_raw_winner_loses_to_supported_wilson_estimate(self):
        evidence = self.evidence([self.row(20, 18), self.row(100, 80, picks=(0, 1, 2, 3))])
        self.assertGreater(18 / 20, 80 / 100)
        self.assertLess(book_preview.override_estimate(18, 20), book_preview.override_estimate(80, 100))
        player = book_preview.BookPlayer(self.raw, evidence, self.sheets, self.rows)
        _, choices = self.choose(player, self.batch())
        self.assertEqual(choices["picks"][0, 0, :4].tolist(), [0, 1, 2, 3])

    def test_sheets_decode_one_based_items_and_known_empty_items(self):
        sides = self.pool.sides.copy()
        item_id = data.find(self.ctx, data.TABLE_ITEM, "sitrusberry")
        sides["members"][0, 0]["item"] = item_id + 1
        sides["members"][1, 0]["item"] = 0
        decoded = book_preview.sheets(self.ctx, teams.TeamPool.from_setups(self.pool.ids, sides))
        self.assertEqual(decoded[0][0]["item"], "sitrusberry")
        self.assertEqual(decoded[1][0]["item"], "")

    def test_threshold_falls_back_byte_for_byte(self):
        batch = self.batch()
        before, choices_before = self.choose(self.raw, batch)
        player = book_preview.BookPlayer(self.raw, self.evidence([self.row(19, 10)]), self.sheets, self.rows)
        after, choices_after = self.choose(player, batch)
        self.assertEqual(before.tobytes(), after.tobytes())
        self.assertEqual(choices_before.tobytes(), choices_after.tobytes())
        self.assertEqual(player.summary()["fallbacks"], {"below_level_min_count": 2})

    def test_choice_counts_not_level_totals_gate_override(self):
        batch = self.batch()
        before, _ = self.choose(self.raw, batch)
        player = book_preview.BookPlayer(self.raw, self.evidence([self.row(10, 8), self.row(10, 5, picks=(0, 1, 4, 5))]),
                                        self.sheets, self.rows)
        after, _ = self.choose(player, batch)
        self.assertEqual(before.tobytes(), after.tobytes())
        summary = player.summary()
        self.assertEqual(summary["fallbacks"], {"below_choice_min_count": 2})
        self.assertEqual(summary["rejected_choices"], {"below_choice_min_count": 4})
        self.assertEqual(summary["answered_share"], 1)
        self.assertEqual(summary["applied_share"], 0)

    def test_missing_backs_are_never_completed(self):
        player = book_preview.BookPlayer(self.raw, self.evidence([self.row(backs=False)]), self.sheets, self.rows)
        batch = self.batch()
        before, _ = self.choose(self.raw, batch)
        after, _ = self.choose(player, batch)
        self.assertEqual(before.tobytes(), after.tobytes())
        self.assertEqual(player.summary()["fallbacks"], {"missing_backs": 2})

    def test_mapping_failures_are_explicit_and_do_not_guess(self):
        batch = self.batch()
        answer = self.evidence().leads(*self.sheets)
        malformed = copy.deepcopy(answer)
        malformed["suggestions"][0]["backs"] = ("absent", "other")
        probs, rank, causes = book_preview.mapped_distribution(malformed, self.sheets[0], batch.domains[0, 0], 20, "override")
        self.assertIsNone(probs)
        self.assertIsNone(rank)
        self.assertEqual(causes, {"species_not_in_roster": 1})
        malformed["suggestions"][0]["backs"] = malformed["suggestions"][0]["leads"]
        self.assertEqual(book_preview.mapped_distribution(malformed, self.sheets[0], batch.domains[0, 0], 20, "override")[2],
                         {"invalid_book_choice": 1})
        bad_domain = batch.domains[0, 0].copy()
        bad_domain["pick_count"] = 3
        self.assertEqual(book_preview.mapped_distribution(answer, self.sheets[0], bad_domain, 20, "override")[2],
                         {"unsupported_preview_domain": 1})

    def test_unknown_win_rate_is_not_an_override(self):
        row = self.row()
        row.update(decisive_count=0, wins=0, win_rate=None)
        player = book_preview.BookPlayer(self.raw, self.evidence([row]), self.sheets, self.rows)
        self.choose(player, self.batch())
        self.assertEqual(player.summary()["fallbacks"], {"no_decisive_games": 2})

    def test_prior_splits_mass_over_all_legal_orderings_and_mixes_net(self):
        evidence, batch = self.evidence(), self.batch()
        prior, _, causes = book_preview.mapped_distribution(evidence.leads(*self.sheets), self.sheets[0], batch.domains[0, 0], 20, "prior")
        self.assertEqual(causes, {})
        self.assertEqual(np.flatnonzero(prior).size, 4)
        np.testing.assert_array_equal(prior[prior > 0], [.25] * 4)
        player = book_preview.BookPlayer(self.raw, evidence, self.sheets, self.rows, mode="prior", weight=.8)
        out, _ = self.choose(player, batch)
        self.assertEqual(int(out[0, 0]), int(np.flatnonzero(prior)[0]))
        self.assertEqual(self.model.applies, 1)
        light = book_preview.BookPlayer(self.raw, evidence, self.sheets, self.rows, mode="prior", weight=.1)
        out, _ = self.choose(light, batch)
        self.assertEqual(int(out[0, 0]), 0)

    def test_prior_zero_weight_does_not_even_apply_network_again(self):
        batch = self.batch()
        before, choices_before = self.choose(self.raw, batch)
        player = book_preview.BookPlayer(self.raw, self.evidence(), self.sheets, self.rows, mode="prior", weight=0)
        after, choices_after = self.choose(player, batch)
        self.assertEqual(before.tobytes(), after.tobytes())
        self.assertEqual(choices_before.tobytes(), choices_after.tobytes())
        self.assertEqual(self.model.applies, 0)
        self.assertEqual(player.summary()["fallbacks"], {"zero_prior_weight": 2})

    def test_determinism_and_ties_do_not_depend_on_row_order(self):
        a, b = self.row(), self.row(picks=(0, 1, 4, 5))
        results = []
        for rows in ([a, b], [b, a]):
            player = book_preview.BookPlayer(self.raw, self.evidence(rows), self.sheets, self.rows)
            out, _ = self.choose(player, self.batch())
            results.append(out.tobytes())
        self.assertEqual(*results)

    def test_default_off_is_same_object_and_native_game_records_are_identical(self):
        args = SimpleNamespace(book=None, book_min_count=20, book_mode="override", book_weight=.5)
        evidence = book_preview.load_options(args)
        wrapped = book_preview.wrap(self.raw, evidence, None, self.rows, args)
        self.assertIs(wrapped, self.raw)
        before = evaluate.play_suite(self.ctx, self.pool, self.rows, self.raw, self.raw, 1, 5, max_steps=3)
        after = evaluate.play_suite(self.ctx, self.pool, self.rows, wrapped, self.raw, 1, 5, max_steps=3)
        self.assertEqual(before.tobytes(), after.tobytes())

    def test_battle_turns_do_not_consult_the_book_or_change_net_actions(self):
        batch = self.batch()
        player = book_preview.BookPlayer(self.raw, self.evidence(), self.sheets, self.rows)
        initial, _ = self.choose(player, batch)
        batch.step(initial)
        batch.query()
        batch.query_factored()
        before, choices_before = self.choose(self.raw, batch)
        after, choices_after = self.choose(player, batch)
        self.assertEqual(before.tobytes(), after.tobytes())
        self.assertEqual(choices_before.tobytes(), choices_after.tobytes())
        self.assertEqual(len(player.events), 2)

    def test_ladder_round_robin_accepts_book_players_on_both_seats(self):
        evidence = self.evidence()
        players = [book_preview.BookPlayer(self.raw, evidence, self.sheets, self.rows) for _ in range(2)]
        records = ladder.play_round_robin(self.ctx, self.pool, self.rows, players, 1, seed=5)
        self.assertEqual(records[(0, 1)].shape, (2,))
        self.assertEqual(players[0].summary()["applied"], 2)
        self.assertEqual(players[1].summary()["fallbacks"], {"below_level_min_count": 2})

    def test_options_and_private_book_refusal(self):
        for minimum, mode, weight in ((0, "override", .5), (20, "invalid", .5), (20, "prior", float("nan")), (20, "prior", 2)):
            with self.assertRaises(ValueError):
                book_preview.BookPlayer(self.raw, None, self.sheets, self.rows, minimum, mode, weight)
        root = Path(__file__).resolve().parents[2]
        args = SimpleNamespace(book=str(root / "private.json"), book_min_count=20, book_weight=.5, book_mode="override")
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            book_preview.load_options(args)
        evidence = self.evidence()
        args.book = str(self.path)
        original = book_preview.info(args)["sha256"]
        self.assertEqual(len(original), 64)
        self.path.write_text("replacement during evaluation", encoding="utf-8")
        self.assertEqual(book_preview.info(args, evidence)["sha256"], original)

    def test_real_engine_tiny_ab_smoke_writes_private_reports_and_is_deterministic(self):
        args = SimpleNamespace(out=str(Path(self.tmp.name, "ab")), workers=1, seed=5, max_steps=2,
                               resamples=20, book_min_count=20, book_mode="override", book_weight=.5)
        evidence = self.evidence()
        reports = book_ab.run(self.ctx, self.pool, self.rows, self.raw,
                              {name: self.raw for name in ("same_checkpoint", "BC", "3600", "11000")}, evidence, args)
        self.assertEqual(set(reports), {"same_checkpoint", "BC", "3600", "11000"})
        first = reports["same_checkpoint"]
        self.assertEqual(first["with_book"]["games"], 2)
        self.assertEqual(first["book"]["levels"], {"exact_team": 2})
        self.assertEqual(first["book"]["applied_share"], 1)
        self.assertTrue(Path(args.out, "same_checkpoint-preview.json").is_file())
        args.out = str(Path(self.tmp.name, "ab-repeat"))
        repeat = book_ab.run(self.ctx, self.pool, self.rows, self.raw, {"same_checkpoint": self.raw}, evidence, args)
        self.assertEqual(first, repeat["same_checkpoint"])
        self.assertEqual(Path(self.tmp.name, "ab", "same_checkpoint-with-book.csv").read_bytes(),
                         Path(args.out, "same_checkpoint-with-book.csv").read_bytes())
        with self.assertRaisesRegex(ValueError, "empty"):
            book_ab.run(self.ctx, self.pool, self.rows, self.raw, {}, evidence, args)

    def test_ab_refuses_repository_outputs_before_playing_any_arm(self):
        args = SimpleNamespace(out=str(Path(__file__).resolve().parents[2] / "private-ab"))
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            book_ab.run(self.ctx, self.pool, self.rows, self.raw, {}, self.evidence(), args)

    def write_checkpoints(self):
        from duoforge_learn import checkpoint

        # Real checkpoint I/O and native battles; only the optional JAX backend
        # is replaced at its boundary. No trained parameters or book data.
        config = {"model": {"version": 1, "hidden": 1, "option_hidden": 1}, "encoder": features.ENCODER,
                  "features": list(features.FEATURE_NAMES), "slot_features": list(features.SLOT_FEATURE_NAMES),
                  "data": {"kind": "closure"}, "teams": {"ids": ["A", "B"], "sha256": ["", ""], "weights": [1, 1]},
                  "update": 0, "decisions": 0, "ids": checkpoint.ids_of(self.ctx)}
        sizes = {"t1": (features.obs_size(features.ENCODER), 1), "t2": (1, 1), "option_torso": (1, 1),
                 "option_features": (len(features.SLOT_FEATURE_NAMES), 1), "option_out": (1, 2), "team": (1, 360), "value": (1, 1)}
        params = {key: {"w": np.zeros(shape, dtype=np.float32), "b": np.zeros(shape[1], dtype=np.float32)}
                  for key, shape in sizes.items()}
        for update in (0, 3600, 11000):
            checkpoint.save(Path(self.tmp.name, f"params-{update}.npz"), params, {**config, "update": update})

    def test_ab_cli_writes_summary_with_synthetic_checkpoint_and_numpy_backend(self):
        self.write_checkpoints()
        from duoforge_learn import checkpoint
        candidate_run = Path(self.tmp.name, "other-candidate-run")
        candidate_run.mkdir()
        params, config = checkpoint.load(Path(self.tmp.name, "params-0.npz"))
        checkpoint.save(candidate_run / "params-0.npz", params, {**config, "origin": "candidate"})
        for update in (3600, 11000):
            (candidate_run / f"params-{update}.npz").write_bytes(b"decoy: must never be selected as the panel")
        self.evidence()
        output = Path(self.tmp.name, "cli-ab")
        backend = SimpleNamespace(make=lambda config: PreviewModel())
        fake_jax = SimpleNamespace(default_backend=lambda: "cpu", __version__="synthetic", devices=lambda: [])
        with mock.patch.dict(sys.modules, {"duoforge_learn.policy": backend, "jax": fake_jax}), \
                mock.patch.object(duoforge_learn, "policy", backend, create=True), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(book_ab.main(["--run-dir", str(candidate_run), "--checkpoint", "params-0", "--book", str(self.path),
                                          "--panel-run-dir", self.tmp.name,
                                          "--out", str(output), "--games", "2", "--workers", "1", "--max-steps", "2",
                                          "--resamples", "10"]), 0)
        summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(set(summary["opponents"]), {"same_checkpoint", "BC", "3600", "11000"})
        self.assertEqual(summary["conditions"]["games_per_arm_per_opponent"], 2)
        self.assertEqual(summary["conditions"]["bootstrap_unit"], "paired seat orders")
        for label, update in (("BC", 0), ("3600", 3600), ("11000", 11000)):
            expected = Path(self.tmp.name, f"params-{update}.npz").resolve()
            recorded = summary["conditions"]["panel"][label]
            self.assertEqual(recorded["path"], str(expected))
            self.assertEqual(recorded["sha256"], arena._sha256(expected))
        self.assertNotEqual(summary["conditions"]["candidate"]["sha256"], summary["conditions"]["panel"]["BC"]["sha256"])

    def test_arena_preview_option_and_search_records_describe_the_played_choice(self):
        self.write_checkpoints()
        self.evidence()
        output = Path(self.tmp.name, "arena")
        backend = SimpleNamespace(make=lambda config: PreviewModel())
        fake_jax = SimpleNamespace(default_backend=lambda: "cpu", __version__="synthetic", devices=lambda: [])
        with mock.patch.dict(sys.modules, {"duoforge_learn.policy": backend, "jax": fake_jax}), \
                mock.patch.object(duoforge_learn, "policy", backend, create=True), redirect_stdout(io.StringIO()):
            self.assertEqual(arena.main(["--run-dir", self.tmp.name, "--checkpoint", "params-0",
                "--book", str(self.path), "--out", str(output), "--agents", "N", "--km", "1x1", "--s", "1",
                "--workers", "1", "--capacity", "1", "--max-steps", "1", "--resamples", "10"]), 0)
        summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        self.assertIn("book", summary["conditions"])
        self.assertGreater(summary["configs"]["R-vs-R"]["book"]["applied"], 0)
        decisions = [json.loads(line) for line in (output / "raw" / "N-k1m1s1-vs-R-decisions.jsonl").read_text().splitlines()]
        applied = [row for row in decisions if "book" in row]
        self.assertTrue(applied)
        self.assertTrue(all(row["choice"] != row["network_choice"] for row in applied))
        self.assertTrue(all(row["book"]["level"] == "exact_team" for row in applied))


class BookABStatisticsTest(unittest.TestCase):
    def test_book_ladder_requires_separate_output_before_loading_inputs(self):
        with tempfile.TemporaryDirectory(prefix="duoforge_ladder_guard_") as temp:
            root = Path(temp)
            saved = root / "ladder.json"
            saved.write_text('{"original": true}', encoding="utf-8")
            for extra in ([], ["--out", str(root)]):
                error = io.StringIO()
                with redirect_stderr(error), self.assertRaises(SystemExit) as caught:
                    ladder.main([str(root), "--book", "missing.json", *extra])
                self.assertEqual(caught.exception.code, 2)
                self.assertIn("--out", error.getvalue())
                self.assertEqual(saved.read_text(encoding="utf-8"), '{"original": true}')

    def test_best_checkpoint_refuses_book_key_and_preserves_ordinary_selection(self):
        with tempfile.TemporaryDirectory(prefix="duoforge_ladder_select_") as temp:
            root = Path(temp)
            for update in (0, 7):
                (root / f"params-{update}.npz").touch()
            payload = {"players": [{"player": f"{root.name} update 0", "elo": 0},
                                   {"player": f"{root.name} update 7", "elo": 10}]}
            path = root / "ladder.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(arena.best_checkpoint(str(root)), str(root / "params-7.npz"))
            for value in ({}, None):
                path.write_text(json.dumps({**payload, "book": value}), encoding="utf-8")
                with self.assertRaisesRegex(SystemExit, "book-influenced"):
                    arena.best_checkpoint(str(root))

    def test_panel_never_defaults_to_candidate_run_and_absolute_paths_are_explicit(self):
        with tempfile.TemporaryDirectory(prefix="duoforge_panel_guard_") as temp:
            root = Path(temp)
            for name in book_ab.PANEL:
                (root / f"{name}.npz").touch()
            with self.assertRaisesRegex(ValueError, "--panel-run-dir"):
                book_ab.panel_paths(book_ab.PANEL)
            expected = [str(root / f"{name}.npz") for name in book_ab.PANEL]
            self.assertEqual(book_ab.panel_paths(book_ab.PANEL, root), expected)
            self.assertEqual(book_ab.panel_paths(expected), expected)

    def test_all_preview_clis_report_invalid_options_as_argparse_errors(self):
        cases = ((arena.main, ["--run-dir", "unused", "--out", "unused"]),
                 (ladder.main, ["unused", "--out", "unused"]),
                 (book_ab.main, ["--run-dir", "unused", "--checkpoint", "unused", "--out", "unused"]))
        for main, argv in cases:
            for flag, value in (("--book-min-count", "0"), ("--book-weight", "nan"), ("--book-weight", "1.1")):
                error = io.StringIO()
                with redirect_stderr(error), self.assertRaises(SystemExit) as caught:
                    main([*argv, flag, value])
                self.assertEqual(caught.exception.code, 2)
                self.assertIn(flag, error.getvalue())
                self.assertNotIn("Traceback", error.getvalue())

    def test_gpu_requires_the_same_deterministic_setting_as_arena(self):
        gpu = SimpleNamespace(default_backend=lambda: "gpu")
        with mock.patch.dict(os.environ, {"XLA_FLAGS": ""}), self.assertRaises(SystemExit):
            arena.require_deterministic_gpu(gpu)
        with mock.patch.dict(os.environ, {"XLA_FLAGS": "--xla_gpu_deterministic_ops=true"}):
            self.assertIsNone(arena.require_deterministic_gpu(gpu))
    def test_exact_budget_same_matchups_and_both_seat_orders(self):
        for n in (1, 2, 8, 9, 20):
            rows = book_ab.paired_rows(n, 2000, 7)
            self.assertEqual(len(rows), 2000)
            np.testing.assert_array_equal(rows["side0"][::2], rows["side1"][1::2])
            np.testing.assert_array_equal(rows["side1"][::2], rows["side0"][1::2])
            np.testing.assert_array_equal(rows["learner_seat"], [0, 1] * 1000)
            self.assertEqual(rows.tobytes(), book_ab.paired_rows(n, 2000, 7).tobytes())
        for n, games in ((0, 2), (1, 1), (1, 3)):
            with self.assertRaises(ValueError):
                book_ab.paired_rows(n, games)

    def test_panel_defaults_and_pool_groups(self):
        self.assertEqual(book_ab.PANEL, ("params-0", "params-3600", "params-11000"))
        self.assertEqual([book_ab.pool_group(x) for x in ("PP_a", "A", "B", "C", "LL_a", "other")],
                         ["PP_/A/B/C"] * 4 + ["LL_", "other"])

    def test_comparison_has_paired_cis_groups_and_missing_preview_denominator(self):
        rows = np.array([(0, 1, 0, 0), (1, 0, 1, 0), (1, 0, 0, 1), (0, 1, 1, 1)], dtype=book_ab.suite.SUITE)
        raw, changed = np.zeros(4, dtype=evaluate.RECORD), np.zeros(4, dtype=evaluate.RECORD)
        for field in ("side0", "side1", "learner_seat"):
            raw[field], changed[field] = rows[field], rows[field]
        changed["result"] = [1, 1, -1, -1]
        player = book_preview.BookPlayer(SimpleNamespace(name="test"), None, None, rows)
        player.events = [{"env": 0, "answered": True, "applied": True, "level": "exact_team",
                          "fallback": {}, "rejected_choices": {}}]
        result = book_ab.comparison(raw, changed, rows, ("A", "LL_x"), player, resamples=30)
        self.assertEqual(result["paired_difference"]["score"], 0)
        self.assertEqual(result["by_pool_group"]["PP_/A/B/C"]["with_book"]["score"], 1)
        self.assertEqual(result["by_pool_group"]["LL_"]["with_book"]["score"], 0)
        self.assertEqual(result["book"]["answered_share"], .25)
        self.assertEqual(result["book"]["level_shares"], {"exact_team": .25})
        self.assertEqual(result["book"]["fallbacks"], {"preview_not_requested": 3})
        with self.assertRaises(ValueError):
            book_ab.comparison(raw[:2], changed, rows, ("A", "LL_x"), player)
        changed["side0"][0] = 1
        with self.assertRaisesRegex(ValueError, "pairing records"):
            book_ab.comparison(raw, changed, rows, ("A", "LL_x"), player)


if __name__ == "__main__":
    unittest.main()
