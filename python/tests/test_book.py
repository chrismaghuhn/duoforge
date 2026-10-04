"""Hand-written schema-2 fixtures only; all JSON files live in temporary dirs."""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

from duoforge_replay import book, openings
from duoforge_replay.dataset import refuse_repository

OWN = ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta")
FOE = ("Rho", "Sigma", "Tau", "Upsilon", "Phi", "Chi")
ITEMS = ("Berry", "Scarf", "", "", "", "")
OWN_ITEMS = [{"species": s, "item": i} for s, i in zip(OWN, ITEMS)]


def lead(count=20, wins=12, **extra):
    return {"source": "champions", "format": "gen9championsvgc2026regmc", "team_species": list(OWN),
            "team_items": list(ITEMS), "opposing_team_species": list(FOE), "leads": ["Alpha", "Beta"],
            "opposing_leads": ["Rho", "Sigma"], "backs": ["Gamma", "Delta"],
            "rating": 1500, "opposing_rating": 1400, "count": count, "decisive_count": count, "wins": wins,
            "win_rate": wins / count if count else None, **extra}


def action(count=20, wins=10, **extra):
    return {"source": "champions", "format": "gen9championsvgc2026regmc", "leads": ["Alpha", "Beta"],
            "opposing_leads": ["Rho", "Sigma"], "action_kind": "move", "slot": "a", "actor": "Alpha",
            "action": "Example move", "target": "p2a: Rho", "switch_context": "", "side": 0,
            "rating": 1500, "opposing_rating": 1400, "count": count, "decisive_count": count, "wins": wins,
            "win_rate": wins / count, **extra}


class BookTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="duoforge_synthetic_book_")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "openings.json"

    def payload(self, leads=(), actions=(), **extra):
        return {"schema_version": 2, "tables": {"leads_per_team": list(leads), "turn_1_actions": list(actions)}, **extra}

    def load(self, leads=(), actions=(), **extra):
        self.path.write_text(json.dumps(self.payload(leads, actions, **extra)), encoding="utf-8")
        return book.load(self.path)

    def test_exact_items_and_matchup_returns_observed_back_distribution(self):
        model = self.load([lead(30, 15), lead(10, 8, backs=None),
                           lead(100, 90, opposing_team_species=[*FOE[:5], "Other"])])
        result = model.leads(OWN_ITEMS, FOE)
        self.assertEqual((result["level"], result["count"], result["confidence"]), ("exact_team", 40, "high"))
        first, second = result["suggestions"]
        self.assertEqual(first["backs"], ("delta", "gamma"))
        self.assertEqual((first["count"], first["win_rate"], first["probability"]), (30, .5, .75))
        self.assertIsNone(second["backs"])
        self.assertEqual(second["probability"], .25)
        self.assertEqual(model.leads(list(reversed(OWN_ITEMS)), list(reversed(FOE))), result)

    def test_ignoring_items_handles_unknown_and_different_items(self):
        model = self.load([lead(10, 5), lead(10, 7, team_items=["Other", *ITEMS[1:]])])
        for own in (OWN, [{"species": s, "item": "Unknown"} for s in OWN]):
            result = model.leads(own, FOE)
            self.assertEqual((result["level"], result["count"]), ("team_ignoring_items", 20))
            self.assertEqual(result["suggestions"][0]["win_rate"], .6)
        self.assertEqual(model.leads(OWN, FOE)["skipped"][0]["reason"], "own_items_unknown")

    def test_pair_matchup_backs_off_both_teams_and_filters_observed_foe_pairs(self):
        other = ["Other", *OWN[1:]]
        rows = [lead(20, 12, team_species=[*OWN[:5], "Other"], backs=["Gamma", "Other"],
                     opposing_team_species=[*FOE[:5], "Different"]),
                lead(50, 10, team_species=other, leads=["Other", "Beta"]),
                lead(100, 10, opposing_team_species=["Else", *FOE[1:]], opposing_leads=["Else", "Sigma"])]
        model = self.load(rows)
        result = model.leads(OWN_ITEMS, FOE)
        self.assertEqual((result["level"], result["count"]), (book.LEAD_LEVELS[2], 20))
        self.assertIsNone(result["suggestions"][0]["backs"])
        self.assertTrue(result["opposing_leads_marginalized"])
        self.assertFalse(model.leads(OWN_ITEMS, FOE, opposing_leads=FOE[:2])["opposing_leads_marginalized"])

    def test_single_species_weights_are_marginals_and_counts_remain_observations(self):
        rows = [lead(10, 5, opposing_leads=None, leads=["Alpha", "Beta"]),
                lead(10, 8, opposing_leads=None, leads=["Alpha", "Gamma"], backs=None),
                lead(30, 10, team_species=[*OWN[:5], "Other"], leads=["Beta", "Other"],
                     opposing_leads=None, backs=None)]
        result = self.load(rows).leads(OWN_ITEMS, ["Else", *FOE[1:]], min_count=10)
        self.assertEqual((result["level"], result["count"]), ("single_species", 20))
        self.assertEqual(result["species_counts"], {"alpha": 20, "beta": 40, "gamma": 10})
        first, second, third = result["suggestions"]
        self.assertEqual((first["leads"], first["count"], first["win_rate"]), (("alpha", "beta"), 10, .5))
        self.assertAlmostEqual(first["probability"], 4 / 7)
        self.assertAlmostEqual(second["probability"], 2 / 7)
        self.assertAlmostEqual(third["probability"], 1 / 7)
        self.assertEqual(second["count"], 0)
        self.assertIsNone(second["win_rate"])
        self.assertTrue(all(s["backs"] is None and s["confidence"] == "low" for s in result["suggestions"]))

    def test_species_backoff_can_suggest_unseen_pairs_without_inventing_games(self):
        rows = [lead(20, 10, team_species=[*OWN[:5], "Other"], leads=["Alpha", "Other"], backs=None),
                lead(20, 10, team_species=[*OWN[:5], "Other"], leads=["Beta", "Other"], backs=None)]
        result = self.load(rows).leads(OWN_ITEMS, FOE)
        self.assertEqual((result["level"], result["count"], result["support_count"]), ("single_species", 0, 20))
        suggestion = result["suggestions"][0]
        self.assertEqual((suggestion["leads"], suggestion["count"], suggestion["probability"]),
                         (("alpha", "beta"), 0, 1.0))
        self.assertIsNone(suggestion["win_rate"])

    def test_minimum_skips_sparse_exact_and_sums_matching_rows_before_threshold(self):
        model = self.load([lead(19, 10), lead(1, 1, team_items=["Other", *ITEMS[1:]])])
        result = model.leads(OWN_ITEMS, FOE)
        self.assertEqual(result["level"], "team_ignoring_items")
        self.assertEqual(result["skipped"], [{"level": "exact_team", "count": 19, "reason": "below_min_count"}])
        self.assertEqual(model.leads(OWN_ITEMS, FOE, min_count=19)["level"], "exact_team")
        unavailable = model.leads(OWN_ITEMS, FOE, min_count=21)
        self.assertEqual((unavailable["level"], unavailable["suggestions"]), ("unavailable", []))
        self.assertEqual(len(unavailable["skipped"]), 4)

    def test_champions_default_and_explicit_sv_filter_apply_to_leads_and_actions(self):
        model = self.load([lead(), lead(100, 90, source="sv_vgc")],
                          [action(), action(100, 90, source="sv_vgc", action="SV move")])
        self.assertEqual(model.leads(OWN_ITEMS, FOE)["count"], 20)
        self.assertEqual(model.leads(OWN_ITEMS, FOE, sources=("sv_vgc",))["count"], 100)
        self.assertEqual(model.leads(OWN_ITEMS, FOE, sources=book.SOURCES)["count"], 120)
        self.assertEqual(model.turn_1(OWN[:2], FOE[:2])["a"]["count"], 20)
        self.assertEqual(model.turn_1(OWN[:2], FOE[:2], sources=("sv_vgc",))["a"]["suggestions"][0]["action"], "SV move")
        sparse = self.load([lead(19, 10), lead(100, 90, source="sv_vgc")],
                           [action(19, 10), action(100, 90, source="sv_vgc")])
        self.assertEqual(sparse.leads(OWN_ITEMS, FOE)["level"], "unavailable")
        self.assertEqual(sparse.turn_1(OWN[:2], FOE[:2])["a"]["level"], "unavailable")

    def test_rating_bounds_exclude_unknown_and_preserve_weighted_win_rates(self):
        rows = [lead(20, 10, rating=1400), lead(20, 16, rating=1600), lead(20, 0, rating=-1)]
        model = self.load(rows, [action(rating=1600), action(rating=-1)])
        self.assertEqual(model.leads(OWN_ITEMS, FOE, min_rating=1500)["suggestions"][0]["win_rate"], .8)
        self.assertEqual(model.leads(OWN_ITEMS, FOE, max_rating=1400)["count"], 20)
        self.assertEqual(model.turn_1(OWN[:2], FOE[:2], min_rating=1500)["a"]["count"], 20)
        model = self.load([lead(rating=-1)], [action(rating=-1)])
        with self.assertRaisesRegex(ValueError, "no ratings"):
            model.leads(OWN_ITEMS, FOE, min_rating=1500)
        with self.assertRaisesRegex(ValueError, "no ratings"):
            model.turn_1(OWN[:2], FOE[:2], max_rating=1600)

    def test_turn_one_per_actor_backoff_and_only_choice_switches(self):
        rows = [action(19, 10), action(1, 1, leads=["Alpha", "Gamma"], action="Other move", slot="b"),
                action(actor="Beta", slot="b", action_kind="switch", action="Delta", target=None, switch_context="choice"),
                *[action(100, 90, action_kind="switch", action="Gamma", switch_context=c)
                  for c in ("pivot", "replacement", "drag")], action(100, 90, action_kind="mega"),
                action(100, 90, leads=["Gamma", "Delta"])]
        result = self.load(actions=rows).turn_1(OWN[:2], FOE[:2])
        self.assertEqual((result["a"]["level"], result["a"]["count"]), ("single_species", 20))
        self.assertEqual(result["b"]["level"], "exact_pairs")
        self.assertEqual(result["b"]["suggestions"][0]["switch_context"], "choice")
        self.assertIsNone(result["b"]["suggestions"][0]["target"])
        self.assertEqual(result["a"]["suggestions"][1]["observed_slots"], {"b": 1})
        reversed_slots = self.load(actions=rows).turn_1(OWN[1::-1], FOE[:2])
        self.assertEqual(reversed_slots["a"]["actor"], "beta")

    def test_identical_actions_from_different_slots_merge_with_slot_evidence(self):
        result = self.load(actions=[action(10, 5), action(10, 5, slot="b")]).turn_1(OWN[:2], FOE[:2])
        self.assertEqual(len(result["a"]["suggestions"]), 1)
        suggestion = result["a"]["suggestions"][0]
        self.assertEqual((suggestion["count"], suggestion["probability"]), (20, 1.0))
        self.assertEqual(suggestion["observed_slots"], {"a": 10, "b": 10})

    def test_targets_normalize_player_perspective_without_inventing_a_target(self):
        rows = [action(10, 5), action(10, 5, side=1, target="p1a: Rho"),
                action(20, 10, target="p1b: Beta", action="Ally move"),
                action(20, 10, target=None, action="Unknown target"),
                action(20, 10, target="opaque", action="Opaque target")]
        suggestions = self.load(actions=rows).turn_1(OWN[:2], FOE[:2])["a"]["suggestions"]
        by_action = {s["action"]: s for s in suggestions}
        self.assertEqual(by_action["Example move"]["target"], "foe:a: Rho")
        self.assertEqual(by_action["Example move"]["count"], 20)
        self.assertEqual(by_action["Ally move"]["target"], "own:b: Beta")
        self.assertIsNone(by_action["Unknown target"]["target"])
        self.assertEqual(by_action["Opaque target"]["target"], "opaque")
        self.assertEqual(self.load().turn_1(OWN[:2], FOE[:2])["a"]["level"], "unavailable")

    def test_ties_and_row_order_are_deterministic_and_ties_use_fixed_key(self):
        leads = [lead(leads=["Alpha", "Gamma"], backs=None), lead(leads=["Alpha", "Beta"], backs=None)]
        actions = [action(action="Z move"), action(action="A move")]
        model = self.load(leads, actions)
        result = model.leads(OWN_ITEMS, FOE)
        turns = model.turn_1(OWN[:2], FOE[:2])
        self.assertEqual(result["suggestions"][0]["leads"], ("alpha", "beta"))
        self.assertEqual(turns["a"]["suggestions"][0]["action"], "A move")
        reversed_model = self.load(leads[::-1], actions[::-1])
        self.assertEqual(result, reversed_model.leads(OWN_ITEMS, FOE))
        self.assertEqual(turns, reversed_model.turn_1(OWN[:2], FOE[:2]))

    def test_ties_or_unknown_winners_do_not_count_as_losses(self):
        result = self.load([lead(wins=0, decisive_count=0)]).leads(OWN_ITEMS, FOE)
        self.assertIsNone(result["suggestions"][0]["win_rate"])
        self.assertEqual(result["suggestions"][0]["count"], 20)

    def test_schema_one_unknown_and_incomplete_schemas_fail_explicitly(self):
        for version in (1, 3, "2", True, None):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "schema_version 2"):
                self.load(schema_version=version)
        self.path.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "schema_version 2"):
            book.load(self.path)
        self.path.write_text('{"schema_version":2}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "tables"):
            book.load(self.path)
        row = lead()
        del row["backs"]
        with self.assertRaisesRegex(ValueError, "schema-2"):
            self.load([row])

    def test_malformed_rows_and_invalid_options_fail(self):
        bad_rows = [lead(source="other"), lead(format=""), lead(count=True), lead(wins=21), lead(count=0),
                    lead(team_items=[]), lead(team_items=[1, *ITEMS[1:]]), lead(leads=["", "Beta"]),
                    lead(leads=["Alpha", "Alpha"]), lead(leads=["Alpha", "Outside"]),
                    lead(backs=["Alpha", "Gamma"]), lead(opposing_leads=["Outside", "Sigma"]),
                    lead(rating=-2)]
        for row in bad_rows:
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.load([row])
        for row in (action(action_kind="other"), action(opposing_leads=None), action(slot="c"),
                    action(side=True), action(target=3), action(actor=""), action(switch_context=None),
                    action(action_kind="switch", switch_context="")):
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.load(actions=[row])
        model = self.load([lead()])
        for options in ({"min_count": 0}, {"min_count": True}, {"min_rating": -1}, {"max_rating": "1500"},
                        {"min_rating": 1500, "max_rating": 1400}, {"sources": ()}, {"sources": "champions"},
                        {"sources": ("other",)}, {"opposing_leads": ("Outside", "Sigma")}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                model.leads(OWN_ITEMS, FOE, **options)
        for own in ([], [None] * 6, [{"species": s, "item": 3} for s in OWN]):
            with self.assertRaises(ValueError):
                model.leads(own, FOE)
        self.assertEqual(model.leads(OWN_ITEMS, FOE, min_rating=2000)["level"], "unavailable")

    def test_load_refuses_main_and_other_worktrees_before_reading(self):
        root = Path(book.__file__).resolve().parents[2]
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            book.load(root / "nonexistent-private-book.json")
        listing = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=root,
                                 capture_output=True, text=True, check=True).stdout
        for line in listing.splitlines():
            if line.startswith("worktree "):
                with self.assertRaisesRegex(ValueError, "inside the repository"):
                    refuse_repository(Path(line[9:]) / "private" / "book.json")

    def test_cli_pastes_and_explicit_pairs_print_both_queries(self):
        self.load([lead(), lead(team_species=list(FOE), team_items=[""] * 6,
                                opposing_team_species=list(OWN), leads=list(FOE[:2]),
                                opposing_leads=list(OWN[:2]), backs=list(FOE[2:4]))], [action()])
        paste = "\n\n".join(f"Nickname ({s}) (M)" + (f" @ {i}" if i else "") +
                              "\nAbility: Ignored\n- Ignored move" for s, i in zip(OWN, ITEMS))
        paste_path = Path(self.temp.name) / "own.txt"
        paste_path.write_text(paste, encoding="utf-8")
        output = io.StringIO()
        args = ["--book", str(self.path), "--own", "@" + str(paste_path), "--foe", ",".join(FOE)]
        with redirect_stdout(output):
            self.assertEqual(book.main(args), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["leads"]["level"], "exact_team")
        self.assertTrue(result["turn_1"][0]["hypothetical"])
        output = io.StringIO()
        with redirect_stdout(output):
            book.main([*args, "--own-leads", "Alpha,Beta", "--foe-leads", "Rho,Sigma"])
        self.assertFalse(json.loads(output.getvalue())["turn_1"][0]["hypothetical"])
        self.assertEqual(book.parse_team(paste.replace("\n", "\r\n")), book.parse_team(paste))
        self.assertEqual(len(book.parse_team("\n\n".join(OWN))), 6)

    def test_cli_errors_and_module_entrypoint(self):
        self.load([lead()])
        args = ["--book", str(self.path), "--own", ",".join(OWN), "--foe", ",".join(FOE)]
        for extra in (["--own-leads", "Alpha,Beta"], ["--own-leads", "Alpha,Outside", "--foe-leads", "Rho,Sigma"],
                      ["--min-count", "0"], ["--own", "@missing-paste-file"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                book.main([*args, *extra])
            self.assertEqual(error.exception.code, 2)
        proc = subprocess.run([sys.executable, "-m", "duoforge_replay.book", *args],
                              capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(proc.stdout)["turn_1"], [])

    def test_schema_two_exporter_output_is_consumed_without_adaptation(self):
        from python.tests.test_openings import FakeData, LOG

        game = openings.extract_game("synthetic", "gen9championsvgc2026regmc", LOG, FakeData())
        payload = {"schema_version": 2, **openings.aggregate([game] * 20)}
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        model = book.load(self.path)
        own = [{"species": m.species, "item": m.item} for m in game.sides[0].team]
        foe = [m.species for m in game.sides[1].team]
        self.assertEqual(model.leads(own, foe)["level"], "exact_team")
        result = model.turn_1(game.sides[0].leads, game.sides[1].leads)
        self.assertEqual(result["a"]["count"], 20)
        self.assertEqual(result["a"]["suggestions"][0]["action"], "U-turn")


if __name__ == "__main__":
    unittest.main()
