"""The search ladder's harness (issue #440, step 0): pure functions over NumPy arrays and the CLI's guards. No
network and no checkpoint: every guard runs before any network is loaded."""
import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock

import numpy as np

from duoforge import teams
from duoforge_learn import suite
from duoforge_live.data import ROOT
from duoforge_live.search import HONEST_SETTINGS
from duoforge_search import foe_arena, ladder


def searched(k=2, m=3, s=4, refused=0):
    return {"kind": "searched", "k": k, "m": m, "s": s,
            "leaves": {"refused": refused, "terminal": 0, "cut_off": 0, "unresolved": 0}}


def decisions(raw=0, searched_count=20):
    """Searched decisions with raw ones among them: non-team decisions for fallback_share."""
    return [{"kind": "raw"} for _ in range(raw)] + [searched() for _ in range(searched_count - raw)]


class StepSettingsTest(unittest.TestCase):
    def test_step_zero_is_the_live_settings_unchanged(self):
        settings = ladder.step_settings("0")
        self.assertEqual(settings, HONEST_SETTINGS)
        self.assertIsNot(settings, HONEST_SETTINGS)

    def test_base_chain_applies_the_base_first(self):
        steps = {"0": {"base": None, "settings": {}}, "1": {"base": "0", "settings": {"k": 4}},
                 "2": {"base": "1", "settings": {"k": 2, "rule": "nash"}}}
        with mock.patch.dict(ladder.STEPS, steps):
            one, two = ladder.step_settings("1"), ladder.step_settings("2")
        self.assertEqual(one["k"], 4)
        self.assertEqual(one["rule"], HONEST_SETTINGS["rule"])
        self.assertEqual(two["k"], 2)  # the child's delta over its base's delta over the live settings
        self.assertEqual(two["rule"], "nash")
        self.assertEqual(two["m"], HONEST_SETTINGS["m"])

    def test_never_mutates_the_live_settings(self):
        before = dict(HONEST_SETTINGS)
        settings = ladder.step_settings("0")
        settings["k"] = 99
        self.assertEqual(HONEST_SETTINGS, before)
        self.assertEqual(ladder.step_settings("0")["k"], HONEST_SETTINGS["k"])

    def test_unknown_step_names_the_known_steps(self):
        with self.assertRaisesRegex(ValueError, "'0'"):
            ladder.step_settings("nope")

    def test_unknown_base_is_refused(self):
        with mock.patch.dict(ladder.STEPS, {"x": {"base": "missing", "settings": {}}}):
            with self.assertRaisesRegex(ValueError, "missing"):
                ladder.step_settings("x")

    def test_a_base_loop_is_refused(self):
        steps = {"a": {"base": "b", "settings": {}}, "b": {"base": "a", "settings": {}}}
        with mock.patch.dict(ladder.STEPS, steps):
            with self.assertRaisesRegex(ValueError, "loops"):
                ladder.step_settings("a")


class StepOneTest(unittest.TestCase):
    """Step 1 (issue #363 in the ladder, #440): team preview as a Nash matrix game, with its two controls."""

    def test_the_predeclared_entries(self):
        self.assertEqual(ladder.STEPS["0"], {"base": None, "settings": {}})
        preview = {"preview_mode": "value"}
        self.assertEqual(ladder.STEPS["1"], {"base": "0", "settings": {**preview, "preview_rule": "nash"}})
        self.assertEqual(ladder.STEPS["1e"], {"base": "0", "settings": {**preview, "preview_rule": "ev"}})
        self.assertEqual(ladder.STEPS["1x"], {"base": "0", "settings": {**preview, "preview_rule": "mix"}})

    def test_each_step_one_variant_is_step_zero_plus_exactly_its_delta(self):
        base = ladder.step_settings("0")
        for name, rule in (("1", "nash"), ("1e", "ev"), ("1x", "mix")):
            with self.subTest(step=name):
                self.assertEqual(ladder.step_settings(name), {**base, "preview_mode": "value", "preview_rule": rule})


class StepOneBTest(unittest.TestCase):
    """Step 1b (#440): the turn-1 rollout's best answer (ev) and its nash control."""

    def test_the_predeclared_entries(self):
        self.assertEqual(ladder.STEPS["1b"], {"base": "0", "settings": {"preview_mode": "turn1", "preview_rule": "ev"}})
        self.assertEqual(ladder.STEPS["1bn"],
                         {"base": "0", "settings": {"preview_mode": "turn1", "preview_rule": "nash"}})

    def test_each_step_one_b_variant_is_step_zero_plus_exactly_its_delta(self):
        base = ladder.step_settings("0")
        for name, rule in (("1b", "ev"), ("1bn", "nash")):
            with self.subTest(step=name):
                self.assertEqual(ladder.step_settings(name), {**base, "preview_mode": "turn1", "preview_rule": rule})


class PairIntervalTest(unittest.TestCase):
    def test_opposite_results_within_a_pair_give_a_zero_width_interval(self):
        got = ladder.pair_interval([1, 0, 0, 1, 1, 0, 0, 1])
        self.assertEqual(got["pairs"], 4)
        self.assertEqual(got["score"], 0.5)
        self.assertEqual(got["95"], [0.5, 0.5])  # rows resampled alone would not give this: pairs are resampled

    def test_all_wins_is_one(self):
        self.assertEqual(ladder.pair_interval([1, 1, 1, 1]), {"pairs": 2, "score": 1.0, "95": [1.0, 1.0]})

    def test_two_pairs_one_win_and_one_loss(self):
        got = ladder.pair_interval([1, 1, 0, 0])
        self.assertEqual(got["score"], 0.5)
        self.assertEqual(got["95"], [0.0, 1.0])  # each of the four resamples of two pairs: 0, 0.5 or 1

    def test_odd_or_empty_rows_are_refused(self):
        with self.assertRaises(ValueError):
            ladder.pair_interval([1, 0, 1])
        with self.assertRaises(ValueError):
            ladder.pair_interval([])


class PairedHTest(unittest.TestCase):
    def test_identical_scores_are_exactly_half_with_zero_width(self):
        a = [1, 0, 0.5, 0.5, 1, 1, 0, 0]
        self.assertEqual(ladder.paired_h(a, a), {"pairs": 4, "mean": 0.5, "95": [0.5, 0.5]})

    def test_known_value(self):
        got = ladder.paired_h([1, 1, 1, 1], [0, 0, 0, 0])
        self.assertEqual(got, {"pairs": 2, "mean": 1.0, "95": [1.0, 1.0]})

    def test_matches_foe_arena_verdict_bootstrap(self):
        r = np.random.default_rng(3)
        a, b = r.choice([0.0, 0.5, 1.0], 8), r.choice([0.0, 0.5, 1.0], 8)
        got = ladder.paired_h(a, b, resamples=200, seed=7)
        expected = foe_arena.verdict(a, b, [], [], resamples=200, seed=7)["h"]
        self.assertAlmostEqual(got["mean"], expected["mean"], places=12)
        self.assertAlmostEqual(got["95"][0], expected["95"][0], places=12)
        self.assertAlmostEqual(got["95"][1], expected["95"][1], places=12)

    def test_shapes_and_counts_are_checked(self):
        with self.assertRaises(ValueError):
            ladder.paired_h([1, 0, 1], [1, 0, 1])  # odd
        with self.assertRaises(ValueError):
            ladder.paired_h([1, 0], [1, 0, 1, 0])  # different shapes


class RefusedLeavesTest(unittest.TestCase):
    def test_counts_over_searched_decisions_only(self):
        records = [searched(2, 3, 4, refused=6), searched(1, 1, 1, refused=0), {"kind": "forced"}, {"kind": "team"},
                   {"kind": "unreconstructible", "reason": "engine_refused_leaves"},
                   {"kind": "unreconstructible", "reason": "other"}]
        got = ladder.refused_leaves(records)
        self.assertEqual(got, {"leaves": 25, "refused": 6, "decisions_with_refused": 1, "refused_share": 6 / 25,
                               "unreconstructible_engine_refused": 1})

    def test_no_leaves_is_a_zero_share(self):
        self.assertEqual(ladder.refused_leaves([]), {"leaves": 0, "refused": 0, "decisions_with_refused": 0,
                                                     "refused_share": 0.0, "unreconstructible_engine_refused": 0})


class VerdictTest(unittest.TestCase):
    def passing(self, **changes):
        inputs = {"h2h": {"pairs": 4, "score": 0.6, "95": [0.55, 0.65]},
                  "paired": {name: {"pairs": 4, "mean": 0.6, "95": [0.55, 0.65]} for name in ("bot", "bc6", "ppo")},
                  "records_new": decisions(), "records_prev": decisions(), "p99_seconds": 1.0}
        inputs.update(changes)
        return ladder.verdict(**inputs)

    def test_every_gate_passing_adopts(self):
        got = self.passing()
        self.assertEqual(got["gates"], {"strength": True, "no_harm": True, "fallback": True, "latency": True})
        self.assertTrue(got["adopt"])

    def test_strength_needs_the_lower_bound_above_one_half(self):
        self.assertFalse(self.passing(h2h={"pairs": 4, "score": 0.5, "95": [0.5, 0.7]})["gates"]["strength"])
        got = self.passing(h2h={"pairs": 4, "score": 0.6, "95": [0.5000001, 0.7]})
        self.assertTrue(got["gates"]["strength"])

    def test_no_harm_needs_each_gated_upper_bound_at_least_one_half(self):
        paired = {"bot": {"pairs": 4, "mean": 0.4, "95": [0.3, 0.49]}, "bc6": {"pairs": 4, "95": [0.4, 0.9]}}
        got = self.passing(paired=paired)
        self.assertFalse(got["gates"]["no_harm"])
        self.assertFalse(got["adopt"])
        paired["bot"]["95"] = [0.3, 0.5]  # an upper bound of exactly one half passes
        self.assertTrue(self.passing(paired=paired)["gates"]["no_harm"])

    def test_ppo_is_reported_but_not_gated(self):
        paired = {"bot": {"pairs": 4, "95": [0.5, 0.6]}, "bc6": {"pairs": 4, "95": [0.5, 0.6]},
                  "ppo": {"pairs": 4, "95": [0.0, 0.1]}}
        self.assertTrue(self.passing(paired=paired)["gates"]["no_harm"])

    def test_a_gated_opponent_without_a_measurement_fails_the_gate(self):
        # No measurement against a gated opponent is no evidence of no harm (as a missing p99 fails the latency).
        self.assertFalse(self.passing(paired={})["gates"]["no_harm"])
        only_bot = {"bot": {"pairs": 4, "95": [0.5, 0.6]}, "ppo": {"pairs": 4, "95": [0.5, 0.6]}}
        self.assertFalse(self.passing(paired=only_bot)["gates"]["no_harm"])

    def test_fallback_at_most_five_percent_passes(self):
        got = self.passing(records_new=decisions(raw=1), records_prev=decisions())  # 1 of 20 = 0.05
        self.assertTrue(got["gates"]["fallback"])
        self.assertFalse(self.passing(records_new=decisions(raw=2), records_prev=decisions())["gates"]["fallback"])

    def test_fallback_over_five_percent_may_follow_the_previous_share_plus_a_point(self):
        prev = decisions(raw=2)  # 0.10: the allowance is 0.11
        self.assertTrue(self.passing(records_new=decisions(raw=2), records_prev=prev)["gates"]["fallback"])
        self.assertFalse(self.passing(records_new=decisions(raw=3), records_prev=prev)["gates"]["fallback"])

    def test_previous_share_at_or_below_five_percent_leaves_the_plain_gate(self):
        prev = decisions(raw=1)  # 0.05 is not above five percent: the plain 0.05 gate stands
        self.assertFalse(self.passing(records_new=decisions(raw=3), records_prev=prev)["gates"]["fallback"])
        self.assertTrue(self.passing(records_new=decisions(raw=1), records_prev=prev)["gates"]["fallback"])

    def test_latency_needs_a_p99_at_most_two_seconds(self):
        self.assertFalse(self.passing(p99_seconds=None)["gates"]["latency"])
        self.assertTrue(self.passing(p99_seconds=2.0)["gates"]["latency"])
        self.assertFalse(self.passing(p99_seconds=2.01)["gates"]["latency"])

    def test_shares_are_exact_ratios(self):
        got = self.passing(records_new=decisions(raw=1, searched_count=3), records_prev=decisions())
        self.assertEqual(got["fallback_share_new"], 1 / 3)
        self.assertEqual(got["fallback_share_previous"], 0.0)

    def test_reports_the_inputs(self):
        got = self.passing()
        for key in ("h2h", "paired", "fallback_share_new", "fallback_share_previous", "fallback_allowed", "p99_seconds",
                    "gates", "adopt"):
            self.assertIn(key, got)


class WslPathTest(unittest.TestCase):
    """A worktree's .git pointer names a Windows gitdir; WSL's git needs its /mnt spelling."""

    def test_a_windows_drive_path_gets_its_wsl_spelling(self):
        self.assertEqual(ladder.wsl_path("C:/Dev/src/duoforge/.git/worktrees/x"),
                         "/mnt/c/Dev/src/duoforge/.git/worktrees/x")
        self.assertEqual(ladder.wsl_path("D:\\data\\run"), "/mnt/d/data/run")

    def test_other_paths_are_unchanged(self):
        self.assertEqual(ladder.wsl_path("/home/chris/df-runs"), "/home/chris/df-runs")
        self.assertEqual(ladder.wsl_path("relative/dir"), "relative/dir")


class SameGamesTest(unittest.TestCase):
    def test_identical_games_match(self):
        self.assertTrue(ladder.same_games([1.0, 0.5, 0.0], np.array([1.0, 0.5, 0.0])))

    def test_one_different_game_or_length_differs(self):
        self.assertFalse(ladder.same_games([1.0, 0.5], [1.0, 0.0]))
        self.assertFalse(ladder.same_games([1.0], [1.0, 1.0]))


class CliGuardTest(unittest.TestCase):
    """Each refusal raises SystemExit before any network is loaded and before the output directory exists."""

    def argv(self, out, opponents=("bot=missing/bot.npz",), step="0", extra=()):
        args = ["--checkpoint", "missing/main.npz", "--foe-net", "missing/foe.npz", "--teams-from", "missing/pool.npz",
                "--step", step, "--out", out]
        for opponent in opponents:
            args += ["--opponent", opponent]
        return args + list(extra)

    def assertRefused(self, pattern, argv, out):
        with self.assertRaisesRegex(SystemExit, pattern):
            ladder.main(argv)
        self.assertFalse(os.path.exists(out))

    def test_out_inside_the_repository_is_refused(self):
        out = os.path.join(str(ROOT), "ladder-guard-test-out")
        self.assertRefused("inside the repository", self.argv(out), out)

    def test_unknown_opponent_name_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            self.assertRefused("foo", self.argv(out, opponents=("foo=missing/x.npz",)), out)

    def test_an_opponent_at_most_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            self.assertRefused("twice", self.argv(out, opponents=("bot=missing/a.npz", "bot=missing/b.npz")), out)

    def test_an_opponent_needs_name_and_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            self.assertRefused("NAME=PATH", self.argv(out, opponents=("bot",)), out)

    def test_h2h_needs_a_previous_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            self.assertRefused("--previous", self.argv(out, extra=("--h2h",)), out)

    def test_previous_run_needs_a_previous_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            self.assertRefused("--previous", self.argv(out, extra=("--previous-run", "missing/ladder.json")), out)

    def test_unknown_step_is_refused_before_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            self.assertRefused("known steps", self.argv(out, step="nope"), out)

    def test_previous_run_must_have_measured_the_previous_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            recorded = os.path.join(tmp, "ladder.json")
            with open(recorded, "w", encoding="utf-8") as f:
                json.dump({"conditions": {"step": {"name": "7", "settings": {}}}}, f)
            self.assertRefused("measured step", self.argv(out, extra=("--previous", "0", "--previous-run", recorded)),
                               out)


def packed_set(name, species="", item="", ability="", moves=(), nature="", evs="", gender="", level="50"):
    """One set of a Showdown packed team: its 12 fields, the IVs, shininess and happiness left empty."""
    return "|".join([name, species, item, ability, ",".join(moves), nature, evs, gender, "", "", level, ""])


PACKED = "]".join([
    packed_set("Rillaboom", item="MiracleSeed", ability="GrassySurge", moves=("WoodHammer", "GrassyGlide"),
               nature="Adamant", evs="18,32,2,,,8"),
    packed_set("Staraptor", item="Staraptite", ability="Intimidate", moves=("BraveBird",), nature="Jolly",
               gender="F")])  # no EVs: all zero


def write_bytes(directory, name, raw):
    path = os.path.join(directory, name)
    with open(path, "wb") as f:
        f.write(raw)
    return path


class MatchupRowsTest(unittest.TestCase):
    def test_the_learner_plays_team_zero_on_both_seats(self):
        rows = ladder.matchup_rows(3)
        self.assertEqual(rows.dtype, suite.SUITE)
        self.assertEqual(rows.shape, (6,))
        learner = np.where(rows["learner_seat"] == 0, rows["side0"], rows["side1"])
        foe = np.where(rows["learner_seat"] == 0, rows["side1"], rows["side0"])
        self.assertTrue((learner == 0).all())
        self.assertTrue((foe == 1).all())

    def test_the_seats_alternate_and_each_pair_is_one_game_index(self):
        rows = ladder.matchup_rows(2)
        self.assertEqual(rows["learner_seat"].tolist(), [0, 1, 0, 1])
        self.assertEqual(rows["side0"].tolist(), [0, 1, 0, 1])
        self.assertEqual(rows["side1"].tolist(), [1, 0, 1, 0])
        self.assertEqual(rows["game"].tolist(), [0, 0, 1, 1])

    def test_at_least_one_pair_is_needed(self):
        with self.assertRaises(ValueError):
            ladder.matchup_rows(0)


class ReadTeamTest(unittest.TestCase):
    def test_a_packed_team_is_unpacked_into_members(self):
        raw = (PACKED + "\n").encode("ascii")
        with tempfile.TemporaryDirectory() as tmp:
            members, packed, digest = ladder.read_team(write_bytes(tmp, "foe.packed", raw))
        self.assertTrue(packed)
        self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
        self.assertEqual(members, [
            {"species": "Rillaboom", "gender": None, "item": "MiracleSeed", "ability": "GrassySurge",
             "nature": "Adamant", "moves": ["WoodHammer", "GrassyGlide"], "stat_points": [18, 32, 2, 0, 0, 8]},
            {"species": "Staraptor", "gender": "F", "item": "Staraptite", "ability": "Intimidate",
             "nature": "Jolly", "moves": ["BraveBird"], "stat_points": [0] * 6}])

    def test_a_packed_level_other_than_fifty_is_refused(self):
        raw = packed_set("Rillaboom", ability="GrassySurge", moves=("WoodHammer",), nature="Adamant",
                         level="100").encode("ascii")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "level 50"):
                ladder.read_team(write_bytes(tmp, "foe.packed", raw))

    def test_a_registry_paste_is_parsed_as_before(self):
        path = os.path.join(str(ROOT), "data", "teams", "A.txt")
        with open(path, "rb") as f:
            raw = f.read()
        members, packed, digest = ladder.read_team(path)
        self.assertFalse(packed)
        self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
        self.assertEqual(members, teams.parse(raw.decode("utf-8"), path))
        self.assertEqual(len(members), 6)


def spread_table(*spreads, species="charizard"):
    """A hand-made table of the Smogon table's shape: the spreads (nature, "a/b/c/d/e/f", weight) of one species."""
    return {"species": {species: {"cutoff": 0, "spreads": [list(s) for s in spreads]}}}


def member(species, nature, stat_points=(0,) * 6):
    return {"species": species, "gender": None, "item": None, "ability": "Blaze", "nature": nature,
            "moves": ["Flare Blitz"], "stat_points": list(stat_points)}


class FillStatPointsTest(unittest.TestCase):
    TABLE = spread_table(("Jolly", "0/252/0/0/4/252", 900), ("Adamant", "4/252/0/0/0/252", 400),
                         ("Adamant", "0/252/0/0/4/252", 600))

    def test_the_heaviest_spread_of_the_members_nature_is_taken(self):
        out, filled = ladder.fill_stat_points([member("Charizard", "Adamant")], self.TABLE)
        self.assertEqual(out[0]["stat_points"], [0, 252, 0, 0, 4, 252])  # not the table's heaviest (Jolly, 900)
        self.assertEqual(filled, [{"species": "Charizard", "nature": "Adamant", "spread": "0/252/0/0/4/252"}])

    def test_a_tie_keeps_the_first_spread_of_the_table(self):
        table = spread_table(("Adamant", "4/252/0/0/0/252", 500), ("Adamant", "0/252/0/0/4/252", 500))
        out, _ = ladder.fill_stat_points([member("Charizard", "Adamant")], table)
        self.assertEqual(out[0]["stat_points"], [4, 252, 0, 0, 0, 252])

    def test_a_member_with_stat_points_is_untouched(self):
        out, filled = ladder.fill_stat_points([member("Charizard", "Adamant", (1, 2, 3, 4, 5, 6))], self.TABLE)
        self.assertEqual(out[0]["stat_points"], [1, 2, 3, 4, 5, 6])
        self.assertEqual(filled, [])

    def test_the_species_is_keyed_by_its_showdown_id(self):
        table = spread_table(("Timid", "0/0/0/252/4/252", 10), species="mrmime")
        out, filled = ladder.fill_stat_points([member("Mr. Mime", "Timid")], table)
        self.assertEqual(out[0]["stat_points"], [0, 0, 0, 252, 4, 252])
        self.assertEqual(filled[0]["species"], "Mr. Mime")

    def test_a_missing_species_is_refused_naming_it(self):
        with self.assertRaisesRegex(SystemExit, "Pikachu"):
            ladder.fill_stat_points([member("Pikachu", "Jolly")], self.TABLE)

    def test_a_missing_nature_is_refused_never_guessed(self):
        with self.assertRaisesRegex(SystemExit, "Modest"):
            ladder.fill_stat_points([member("Charizard", "Modest")], self.TABLE)

    def test_the_input_members_are_not_changed(self):
        members = [member("Charizard", "Adamant")]
        ladder.fill_stat_points(members, self.TABLE)
        self.assertEqual(members[0]["stat_points"], [0] * 6)

    def test_each_filled_member_is_named_in_the_list(self):
        table = spread_table(("Adamant", "0/252/0/0/4/252", 600))
        table["species"]["mrmime"] = {"cutoff": 0, "spreads": [["Timid", "0/0/0/252/4/252", 10]]}
        members = [member("Charizard", "Adamant"), member("Mr. Mime", "Timid"),
                   member("Charizard", "Adamant", (1, 0, 0, 0, 0, 0))]
        out, filled = ladder.fill_stat_points(members, table)
        self.assertEqual([f["species"] for f in filled], ["Charizard", "Mr. Mime"])
        self.assertEqual(out[2]["stat_points"], [1, 0, 0, 0, 0, 0])


class MatchupGuardTest(unittest.TestCase):
    """The --matchup guards raise SystemExit before any network or checkpoint is loaded."""

    def argv(self, out, *extra):
        return ["--checkpoint", "missing/main.npz", "--foe-net", "missing/foe.npz", "--step", "0", "--out", out,
                "--opponent", "bot=missing/bot.npz", *extra]

    def test_teams_from_and_matchup_are_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            ours = os.path.join(str(ROOT), "data", "teams", "A.txt")
            with self.assertRaisesRegex(SystemExit, "exactly one"):
                ladder.main(self.argv(out, "--teams-from", "missing/pool.npz", "--matchup", ours, ours))
            self.assertFalse(os.path.exists(out))

    def test_one_of_teams_from_and_matchup_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            with self.assertRaisesRegex(SystemExit, "exactly one"):
                ladder.main(self.argv(out))
            self.assertFalse(os.path.exists(out))

    def test_a_foe_without_stat_points_needs_the_fill(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            foe = write_bytes(tmp, "foe.packed", PACKED.encode("ascii"))
            ours = os.path.join(str(ROOT), "data", "teams", "A.txt")
            with self.assertRaisesRegex(SystemExit, "foe.*Staraptor.*--fill-stat-points"):
                ladder.main(self.argv(out, "--matchup", ours, foe))
            self.assertFalse(os.path.exists(out))

    def test_a_matchup_has_no_head_to_head(self):
        # In a head-to-head the previous step searches as the foe team, and its belief about our team would draw on
        # our registry team's own stated spreads (no matchup team has a registry id to leave out): refused.
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            ours = os.path.join(str(ROOT), "data", "teams", "A.txt")
            with self.assertRaisesRegex(SystemExit, "--h2h.*--matchup"):
                ladder.main(self.argv(out, "--matchup", ours, ours, "--previous", "0", "--h2h"))
            self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
