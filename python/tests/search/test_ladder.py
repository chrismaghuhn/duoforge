"""The search ladder's harness (issue #440, step 0): pure functions over NumPy arrays and the CLI's guards. No
network and no checkpoint: every guard runs before any network is loaded."""
import contextlib
import copy
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

from duoforge import teams
from duoforge_learn import suite
from duoforge_live.data import ROOT
from duoforge_live.search import HONEST_SETTINGS
from duoforge_search import arena, foe_arena, ladder

# The modules a verdict must never load: the verdict is a pure function of the JSON files it reads.
LIBRARIES = {name: None for name in ("duoforge", "duoforge_learn", "duoforge_live", "duoforge_replay", "jax", "jaxlib")}


def searched(k=2, m=3, s=4, refused=0, refused_pairs=None):
    record = {"kind": "searched", "k": k, "m": m, "s": s,
              "leaves": {"refused": refused, "terminal": 0, "cut_off": 0, "unresolved": 0}}
    if refused_pairs is not None:
        record["refused_pairs"] = refused_pairs
    return record


def decision(env, step, seat, kind="searched", choice=0):
    return {"env": env, "step": step, "seat": seat, "kind": kind, "choice": choice}


def write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f)


def arm(fallback=0, non_team=20):
    """A searching arm's summary as main writes it: the fields the gates and the pooled shares read."""
    return {"scores": [1.0, 0.0], "fallback_share": fallback / non_team, "fallback_decisions": fallback,
            "non_team_decisions": non_team}


def opponent(upper=0.6, same=True, step_fallback=0, previous_fallback=0, non_team=20):
    """One opponent's entry: the step against the previous step, its upper bound, and the reproduction check."""
    return {"arms": {"step": arm(step_fallback, non_team), "previous": arm(previous_fallback, non_team)},
            "paired": {"step_vs_previous": {"pairs": 4, "mean": 0.6, "95": [0.55, upper]}},
            "same_games_as_recorded": same}


def passing_report():
    """A finished ladder.json, as main writes it, that passes every gate. A test breaks one input at a time."""
    return {"conditions": {"commit": "c0ffee", "step": {"name": "1", "settings": {}},
                           "previous": {"name": "0", "settings": {}}},
            "h2h": {"pairs": 4, "score": 0.6, "95": [0.55, 0.65], "unfinished": 0, "unresolved": 0},
            "opponents": {"bot": opponent(), "bc6": opponent(), "ppo": opponent()},
            "p99_seconds": 0.12, "verdict": None}


def latency_run(p99=1.0, step="1", commit="c0ffee"):
    """An exclusive latency run's ladder.json: the fields the latency gate reads."""
    return {"conditions": {"commit": commit, "step": {"name": step, "settings": {}}}, "p99_seconds": p99}


class StepSettingsTest(unittest.TestCase):
    def test_step_zero_is_the_measured_baseline_and_2e_is_live(self):
        # Step 0 stays the baseline every recorded run measured: the approved spec's X (mix, lambda 0.5). The live
        # settings are step 2e since 2026-10-14 (owner), the best answer, and differ from step 0 by the rule only.
        settings = ladder.step_settings("0")
        self.assertEqual(settings, {"k": 8, "m": 8, "s": 16, "rule": "mix", "lam": 0.5, "species_prior": "count",
                                    "capacity": 1024})
        self.assertIsNot(settings, ladder.STEP0)
        self.assertEqual(ladder.step_settings("2e"), HONEST_SETTINGS)
        self.assertEqual({k for k in settings if settings[k] != HONEST_SETTINGS[k]}, {"rule"})

    def test_base_chain_applies_the_base_first(self):
        steps = {"0": {"base": None, "settings": {}}, "1": {"base": "0", "settings": {"k": 4}},
                 "2": {"base": "1", "settings": {"k": 2, "rule": "nash"}}}
        with mock.patch.dict(ladder.STEPS, steps):
            one, two = ladder.step_settings("1"), ladder.step_settings("2")
        self.assertEqual(one["k"], 4)
        self.assertEqual(one["rule"], ladder.STEP0["rule"])
        self.assertEqual(two["k"], 2)  # the child's delta over its base's delta over step 0's settings
        self.assertEqual(two["rule"], "nash")
        self.assertEqual(two["m"], ladder.STEP0["m"])

    def test_never_mutates_step_zero_or_the_live_settings(self):
        before, live = dict(ladder.STEP0), dict(HONEST_SETTINGS)
        for name in ("0", "2e"):
            settings = ladder.step_settings(name)
            settings["k"] = 99
        self.assertEqual((ladder.STEP0, HONEST_SETTINGS), (before, live))
        self.assertEqual(ladder.step_settings("0")["k"], ladder.STEP0["k"])

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


class DepthTwoStepsTest(unittest.TestCase):
    """D2's arms (README docs/benchmarks/2026-10-14-depth-d2, agreed with the AWS campaign #484): fixed names whose
    settings live here, so a campaign starts them by name alone."""

    def test_the_depth_two_arms_are_2e_with_the_tree(self):
        tree = {"depth": 2, "root_solver": "rm", "info_key": "digest", "capacity": 16384}
        for width in (2, 3, 4):
            for name, extra in ((f"d2-{width}{width}", {}), (f"d2-model-{width}{width}", {"foe_below": "model"})):
                with self.subTest(arm=name):
                    self.assertEqual(ladder.step_settings(name),
                                     {**ladder.step_settings("2e"), **tree, "k2": width, "m2": width, **extra})
                    self.assertIsNone(ladder.size_refusal(name))

    def test_the_equal_time_controls_are_one_turn_2e_on_the_rm_solver(self):
        controls = {"d2c-k12m12": {"k": 12, "m": 12, "capacity": 2304},
                    "d2c-k16m16": {"k": 16, "m": 16, "capacity": 4096}, "d2c-s32": {"s": 32, "capacity": 2048},
                    "d2c-s48": {"s": 48, "capacity": 3072}, "d2c-s64": {"s": 64, "capacity": 4096}}
        for name, delta in controls.items():
            with self.subTest(arm=name):
                settings = ladder.step_settings(name)
                self.assertEqual(settings, {**ladder.step_settings("2e"), "root_solver": "rm", **delta})
                self.assertEqual(settings["capacity"], settings["k"] * settings["m"] * settings["s"])
                self.assertIsNone(ladder.size_refusal(name))


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


class PreviewWidthStepTest(unittest.TestCase):
    """The preview width (owner, 2026-10-13): step 1b with one candidate per bring-and-lead combination."""

    def test_the_predeclared_entry_is_step_zero_plus_exactly_its_delta(self):
        delta = {"preview_mode": "turn1", "preview_rule": "ev", "preview_width": "distinct"}
        self.assertEqual(ladder.STEPS["1bw"], {"base": "0", "settings": delta})
        self.assertEqual(ladder.step_settings("1bw"), {**ladder.step_settings("0"), **delta})
        self.assertEqual(ladder.step_settings("1bw"), {**ladder.step_settings("1b"), "preview_width": "distinct"})

    def test_the_corrected_width_is_1bw_with_the_lead_seats_kept(self):
        self.assertEqual(ladder.STEPS["1bws"], {"base": "0", "settings": {**ladder.STEPS["1bw"]["settings"],
                                                                          "preview_width": "seats"}})
        self.assertEqual(ladder.step_settings("1bws"), {**ladder.step_settings("1bw"), "preview_width": "seats"})


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


class PairedEntryTest(unittest.TestCase):
    def test_step_against_previous_is_the_paired_h_of_the_two_arms(self):
        scores = {"step": [1, 1, 0.5, 1], "previous": [0, 0.5, 0, 0]}
        got = ladder.paired_entry(scores)
        self.assertEqual(got["step_vs_previous"], ladder.paired_h(scores["step"], scores["previous"]))

    def test_a_better_step_is_above_one_half_and_swapped_arms_are_below(self):
        scores = {"step": [1, 1, 0.5, 1], "previous": [0, 0.5, 0, 0]}
        self.assertGreater(ladder.paired_entry(scores)["step_vs_previous"]["mean"], 0.5)
        swapped = {"step": scores["previous"], "previous": scores["step"]}
        self.assertLess(ladder.paired_entry(swapped)["step_vs_previous"]["mean"], 0.5)

    def test_r_is_compared_when_it_was_played(self):
        got = ladder.paired_entry({"step": [1, 1], "previous": [0, 0], "R": [0.5, 0.5]})
        self.assertEqual(set(got), {"step_vs_previous", "step_vs_R"})
        self.assertEqual(got["step_vs_R"]["mean"], 0.75)

    def test_without_a_previous_or_r_nothing_is_compared(self):
        self.assertEqual(ladder.paired_entry({"step": [1, 0]}), {})


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

    def test_dropped_refused_pairs_still_count_as_leaves(self):
        # #443 drops the refused rows: k = 7 kept, one pair dropped, so the record had (7 + 1) * 8 * 16 leaves
        got = ladder.refused_leaves([searched(7, 8, 16, refused_pairs=[[0, 1]])])
        self.assertEqual(got["leaves"], 1024)
        self.assertEqual(got["refused_share"], 0.0)


class TreeLimitTest(unittest.TestCase):
    # The HauptSession (D2, 2026-10-15): the depth-2 decisions at the iteration bound are counted per arm, with the
    # position that reached it, so that a new one is told apart from the known calibration decision.
    @staticmethod
    def tree(env, key, step, iterations, bound=490):
        return {"kind": "searched", "env": env, "key": key, "step": step, "depth": {"max_iterations": bound},
                "tree": {"iterations": iterations}}

    def test_decisions_at_the_bound_and_unconverged_are_counted_with_their_position(self):
        records = [self.tree(1, 11, 3, 120), self.tree(56, 179, 9, 490), self.tree(2, 22, 4, 489),
                   {"kind": "unreconstructible", "reason": "solver_unconverged", "env": 7, "key": 77, "step": 5,
                    "depth": {"max_iterations": 490}},
                   {"kind": "unreconstructible", "reason": "solver_unconverged", "env": 8, "key": 88, "step": 6},
                   {"kind": "team"}]
        self.assertEqual(ladder.tree_limit(records), {
            "bound": 490, "tree_decisions": 4, "at_bound": 1, "unconverged": 1,
            "positions": [{"env": 56, "key": 179, "step": 9, "iterations": 490},
                          {"env": 7, "key": 77, "step": 5, "iterations": None}]})

    def test_no_depth_two_decision_is_none(self):
        self.assertIsNone(ladder.tree_limit([{"kind": "searched", "env": 1, "key": 1, "step": 1}, {"kind": "team"}]))


class DecisionsDigestTest(unittest.TestCase):
    def records(self):
        return [decision(1, 0, 1, choice=3), decision(0, 2, 0, kind="raw", choice=1),
                decision(0, 0, 1, kind="team", choice=2)]

    def test_the_input_order_does_not_change_it(self):
        records = self.records()
        self.assertEqual(ladder.decisions_digest(records), ladder.decisions_digest(list(reversed(records))))

    def test_one_choice_changes_it(self):
        records = self.records()
        changed = copy.deepcopy(records)
        changed[0]["choice"] = 4
        self.assertNotEqual(ladder.decisions_digest(records), ladder.decisions_digest(changed))

    def test_it_is_a_sha256_hex_digest(self):
        digest = ladder.decisions_digest(self.records())
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in digest))


class ReproductionTest(unittest.TestCase):
    def test_the_scores_and_the_decision_digest_must_both_match(self):
        old = {"scores": [1.0, 0.5], "decisions_sha256": "abc"}
        self.assertTrue(ladder.recorded_reproduction([1.0, 0.5], "abc", old, "unused", "bot"))
        self.assertFalse(ladder.recorded_reproduction([1.0, 0.5], "xyz", old, "unused", "bot"))
        self.assertFalse(ladder.recorded_reproduction([1.0, 0.0], "abc", old, "unused", "bot"))

    def test_an_opponent_missing_from_the_recorded_run_is_none(self):
        self.assertIsNone(ladder.recorded_reproduction([1.0], "abc", None, "unused", "bot"))

    def test_no_digest_and_no_decision_file_is_none_never_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = {"scores": [1.0, 0.5]}
            self.assertIsNone(ladder.recorded_reproduction([1.0, 0.5], "abc", old, tmp, "bot"))

    def test_the_recorded_decision_file_gives_the_digest_when_the_summary_has_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = [decision(0, 0, 0, choice=2), decision(1, 0, 1, kind="raw", choice=0)]
            with open(os.path.join(tmp, "step-bot-decisions.jsonl"), "w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r) + "\n")
            old = {"scores": [1.0, 0.5]}
            digest = ladder.decisions_digest(records)
            self.assertTrue(ladder.recorded_reproduction([1.0, 0.5], digest, old, tmp, "bot"))
            self.assertFalse(ladder.recorded_reproduction([1.0, 0.5], "0" * 64, old, tmp, "bot"))


class VerdictTest(unittest.TestCase):
    def test_every_gate_passing_adopts(self):
        got = ladder.verdict(passing_report(), latency_run())
        self.assertEqual(got["gates"], {"strength": True, "no_harm": True, "reproduced": True, "fallback": True,
                                        "latency": True})
        self.assertTrue(got["adopt"])
        self.assertEqual(got["notes"], [])

    def test_each_gate_flips_alone(self):
        breakers = {
            "strength": lambda r: r["h2h"].update({"95": [0.5, 0.65]}),
            "no_harm": lambda r: r["opponents"]["bot"]["paired"]["step_vs_previous"].update({"95": [0.4, 0.49]}),
            "reproduced": lambda r: r["opponents"]["bc6"].update({"same_games_as_recorded": False}),
            "fallback": lambda r: r["opponents"]["bot"]["arms"]["step"].update(fallback_share=0.2,
                                                                                fallback_decisions=4),
        }
        for gate, breaker in breakers.items():
            with self.subTest(gate=gate):
                report = passing_report()
                breaker(report)
                gates = ladder.verdict(report, latency_run())["gates"]
                self.assertFalse(gates[gate])
                self.assertEqual({name for name, passed in gates.items() if not passed}, {gate})
        with self.subTest(gate="latency"):
            gates = ladder.verdict(passing_report(), latency_run(p99=2.01))["gates"]
            self.assertEqual({name for name, passed in gates.items() if not passed}, {"latency"})

    def test_latency_pending_without_a_latency_run(self):
        got = ladder.verdict(passing_report())
        self.assertIsNone(got["gates"]["latency"])
        self.assertIsNone(got["adopt"])
        self.assertIsNone(got["p99_seconds"])
        self.assertTrue(all(v for name, v in got["gates"].items() if name != "latency"))
        self.assertTrue(any("latency pending" in note for note in got["notes"]))

    def test_latency_needs_a_p99_at_most_two_seconds(self):
        self.assertTrue(ladder.verdict(passing_report(), latency_run(p99=2.0))["gates"]["latency"])
        self.assertFalse(ladder.verdict(passing_report(), latency_run(p99=None))["gates"]["latency"])
        self.assertFalse(ladder.verdict(passing_report(), latency_run(p99=None))["adopt"])

    def test_the_latency_run_must_measure_this_step(self):
        with self.assertRaisesRegex(ValueError, "step"):
            ladder.verdict(passing_report(), latency_run(step="2"))

    def test_the_latency_run_must_be_on_this_commit(self):
        with self.assertRaisesRegex(ValueError, "commit"):
            ladder.verdict(passing_report(), latency_run(commit="other"))

    def test_a_report_without_a_commit_cannot_be_matched_to_a_latency_run(self):
        report = passing_report()
        report["conditions"]["commit"] = None
        with self.assertRaisesRegex(ValueError, "commit"):
            ladder.verdict(report, latency_run(commit=None))

    def test_strength_needs_the_lower_bound_above_one_half(self):
        report = passing_report()
        report["h2h"]["95"] = [0.5, 0.7]
        self.assertFalse(ladder.verdict(report, latency_run())["gates"]["strength"])
        report["h2h"]["95"] = [0.5000001, 0.7]
        self.assertTrue(ladder.verdict(report, latency_run())["gates"]["strength"])

    def test_unresolved_games_fail_strength_although_the_interval_passes(self):
        report = passing_report()
        report["h2h"]["unresolved"] = 1
        got = ladder.verdict(report, latency_run())
        self.assertGreater(got["h2h"]["95"][0], 0.5)
        self.assertFalse(got["gates"]["strength"])
        self.assertFalse(got["adopt"])
        self.assertTrue(any("unresolved" in note for note in got["notes"]))

    def test_strength_without_a_head_to_head_is_refused(self):
        report = passing_report()
        report["h2h"] = None
        with self.assertRaisesRegex(ValueError, "--h2h"):
            ladder.verdict(report, latency_run())

    def test_no_harm_needs_each_gated_upper_bound_at_least_one_half(self):
        report = passing_report()
        report["opponents"]["bot"] = opponent(upper=0.49)
        self.assertFalse(ladder.verdict(report, latency_run())["gates"]["no_harm"])
        report["opponents"]["bot"] = opponent(upper=0.5)  # an upper bound of exactly one half passes
        self.assertTrue(ladder.verdict(report, latency_run())["gates"]["no_harm"])

    def test_ppo_is_reported_but_not_gated(self):
        report = passing_report()
        report["opponents"]["ppo"] = opponent(upper=0.1)
        got = ladder.verdict(report, latency_run())
        self.assertTrue(got["gates"]["no_harm"])
        self.assertIn("ppo", got["paired"])

    def test_a_gated_opponent_without_a_measurement_fails_the_gates_that_need_it(self):
        report = passing_report()
        del report["opponents"]["bc6"]
        gates = ladder.verdict(report, latency_run())["gates"]
        self.assertFalse(gates["no_harm"])
        self.assertFalse(gates["reproduced"])
        self.assertFalse(gates["fallback"])

    def test_no_harm_needs_the_paired_entry(self):
        report = passing_report()
        del report["opponents"]["bot"]["paired"]["step_vs_previous"]
        self.assertFalse(ladder.verdict(report, latency_run())["gates"]["no_harm"])

    def test_reproduced_needs_true_for_each_gated_opponent(self):
        for value in (None, False):
            with self.subTest(value=value):
                report = passing_report()
                report["opponents"]["bot"]["same_games_as_recorded"] = value
                self.assertFalse(ladder.verdict(report, latency_run())["gates"]["reproduced"])
        report = passing_report()
        del report["opponents"]["bot"]["same_games_as_recorded"]
        self.assertFalse(ladder.verdict(report, latency_run())["gates"]["reproduced"])
        self.assertTrue(ladder.verdict(passing_report(), latency_run())["gates"]["reproduced"])

    def test_fallback_at_most_five_percent_passes(self):
        report = passing_report()
        report["opponents"]["bot"] = opponent(step_fallback=1)  # 1 of 20 = 0.05
        self.assertTrue(ladder.verdict(report, latency_run())["gates"]["fallback"])
        report["opponents"]["bot"] = opponent(step_fallback=2)
        self.assertFalse(ladder.verdict(report, latency_run())["gates"]["fallback"])

    def test_fallback_over_five_percent_may_follow_the_previous_share_plus_a_point(self):
        report = passing_report()  # previous 2 of 20 = 0.10: the allowance is 0.11
        report["opponents"]["bot"] = opponent(step_fallback=2, previous_fallback=2)
        self.assertTrue(ladder.verdict(report, latency_run())["gates"]["fallback"])
        report["opponents"]["bot"] = opponent(step_fallback=3, previous_fallback=2)
        got = ladder.verdict(report, latency_run())
        self.assertFalse(got["gates"]["fallback"])
        self.assertAlmostEqual(got["fallback"]["per_opponent"]["bot"]["allowed"], 0.11)

    def test_previous_share_at_or_below_five_percent_leaves_the_plain_gate(self):
        report = passing_report()  # previous 1 of 20 = 0.05 is not above five percent: 0.05 stands
        report["opponents"]["bot"] = opponent(step_fallback=3, previous_fallback=1)
        self.assertFalse(ladder.verdict(report, latency_run())["gates"]["fallback"])
        report["opponents"]["bot"] = opponent(step_fallback=1, previous_fallback=1)
        self.assertTrue(ladder.verdict(report, latency_run())["gates"]["fallback"])

    def test_a_bot_only_fallback_regression_fails_although_pooling_hides_it(self):
        report = passing_report()
        report["opponents"]["bot"] = opponent(step_fallback=5)  # 5 of 20 against 0 of 20
        report["opponents"]["ppo"] = opponent(non_team=400)  # the pooled share is dominated by 400 clean ppo decisions
        got = ladder.verdict(report, latency_run())
        self.assertFalse(got["gates"]["fallback"])
        self.assertLessEqual(got["fallback"]["pooled"]["step"], 0.05)

    def test_an_old_report_without_the_counts_gets_gates_and_no_pooled_share(self):
        report = passing_report()
        for entry in report["opponents"].values():  # step 1's report: per-opponent shares only
            for summary in entry["arms"].values():
                del summary["fallback_decisions"], summary["non_team_decisions"]
        got = ladder.verdict(report, latency_run())
        self.assertTrue(got["adopt"])
        self.assertEqual(got["fallback"]["pooled"], {"step": None, "previous": None})
        self.assertEqual(len(got["notes"]), 1)
        self.assertIn("old-format report", got["notes"][0])

    def test_an_old_report_still_fails_the_per_opponent_fallback_gate(self):
        report = passing_report()
        report["opponents"]["bot"]["arms"]["step"]["fallback_share"] = 0.2
        for entry in report["opponents"].values():
            for summary in entry["arms"].values():
                del summary["fallback_decisions"], summary["non_team_decisions"]
        self.assertFalse(ladder.verdict(report, latency_run())["gates"]["fallback"])

    def test_reports_the_inputs_and_the_notes(self):
        got = ladder.verdict(passing_report(), latency_run())
        for key in ("h2h", "paired", "fallback", "p99_seconds", "p99_source", "gates", "adopt", "notes"):
            self.assertIn(key, got)
        self.assertEqual(set(got["paired"]), {"bot", "bc6", "ppo"})
        self.assertEqual(set(got["fallback"]["per_opponent"]), {"bot", "bc6", "ppo"})
        self.assertEqual(set(got["fallback"]["pooled"]), {"step", "previous"})
        self.assertEqual(got["p99_seconds"], 1.0)


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
        for opponent_item in opponents:
            args += ["--opponent", opponent_item]
        return args + list(extra)

    def assertRefused(self, pattern, argv, out):
        with self.assertRaisesRegex(SystemExit, pattern):
            ladder.main(argv)
        self.assertFalse(os.path.exists(out))

    def recorded(self, directory, **conditions):
        """A recorded ladder.json of step 0 with conditions that match this test's defaults, unless overridden."""
        base = {"seed": hex(ladder.SEED), "pairs": 1024, "max_steps": 1000, "games": 2048, "step": {"name": "0"},
                "table_sha256": "t", "sha256_prefix": {}}
        base.update(conditions)
        path = os.path.join(directory, "ladder.json")
        write_json(path, {"conditions": base})
        return path

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

    def test_latency_run_needs_h2h(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            self.assertRefused("--h2h", self.argv(out, extra=("--latency-run", "missing/ladder.json")), out)

    def test_previous_run_needs_a_previous_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            self.assertRefused("--previous", self.argv(out, extra=("--previous-run", "missing/ladder.json")), out)

    def test_unknown_step_is_refused_before_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            self.assertRefused("known steps", self.argv(out, step="nope"), out)

    def test_steps_above_the_lp_size_limit_are_refused_by_name_before_loading(self):
        # owner on #440: b-s64 and b-km16 stopped in the exact rescue; the limit is b-k16's tableau
        above = {"b-s32", "b-s64", "b-s128", "b-s256", "b-m16", "b-km16", "b-km16-s64"}
        for name in ladder.STEPS:
            with self.subTest(step=name):
                self.assertEqual(ladder.size_refusal(name) is not None, name in above)
        self.assertIn("above the limit of 20898 cells", ladder.size_refusal("b-km16"))
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            for name in ("b-km16", "b-s64"):
                with self.subTest(step=name):
                    self.assertRefused(f"step '{name}'.*above the limit", self.argv(out, step=name), out)
                    self.assertRefused(f"step '{name}'.*above the limit", self.argv(out, extra=("--previous", name)),
                                       out)

    def test_a_distinct_preview_step_is_sized_with_its_cover(self):
        # 1bw's preview brings up to k + preview.COVER_MAX own candidates (20,124 cells at k = 8): under the limit, and
        # refused by a limit between step 0's k and k + 2, where step 1b's top preview still passes.
        from duoforge_search import matrix, preview
        self.assertIsNone(ladder.size_refusal("1bw"))
        self.assertIsNone(ladder.size_refusal("1bws"))
        _, _, at_k = matrix.bayes_size(8, 8, 16)
        with mock.patch.object(matrix, "MAX_BAYES_CELLS", at_k):
            self.assertIsNone(ladder.size_refusal("1b"))
            for name in ("1bw", "1bws"):
                self.assertIn(f"k={8 + preview.COVER_MAX}", ladder.size_refusal(name))

    def test_an_rm_step_is_not_held_to_the_lp_limit(self):
        # D1 (#481): CFR+ at the turns has no tableau, so b-km16's size passes with root_solver "rm"; a preview still
        # solves an LP and keeps the limit.
        steps = {**ladder.STEPS, "rm-km16": {"base": "b-km16", "settings": {"root_solver": "rm"}},
                 "rm-km16-1b": {"base": "rm-km16", "settings": {"preview_mode": "turn1", "preview_rule": "ev"}}}
        with mock.patch.object(ladder, "STEPS", steps):
            self.assertIsNotNone(ladder.size_refusal("b-km16"))
            self.assertIsNone(ladder.size_refusal("rm-km16"))
            self.assertIn("above the limit", ladder.size_refusal("rm-km16-1b"))

    def test_previous_run_must_have_measured_the_previous_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            recorded = os.path.join(tmp, "ladder.json")
            with open(recorded, "w", encoding="utf-8") as f:
                json.dump({"conditions": {"step": {"name": "7", "settings": {}}}}, f)
            self.assertRefused("measured step", self.argv(out, extra=("--previous", "0", "--previous-run", recorded)),
                               out)

    def test_previous_run_must_match_seed_pairs_max_steps_and_games(self):
        cases = {"seed": {"seed": hex(ladder.SEED + 1)}, "pairs": {"pairs": 512, "games": 1024},
                 "max_steps": {"max_steps": 999}, "games": {"games": 4096}}
        for field, changed in cases.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                out = os.path.join(tmp, "out")
                recorded = self.recorded(tmp, **changed)
                self.assertRefused(field, self.argv(out, extra=("--previous", "0", "--previous-run", recorded)), out)

    def test_previous_run_must_match_the_main_sha_prefix_before_any_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            files = {}
            for role in ("main", "foe", "bot", "teams"):  # real files, not networks: they are hashed, never loaded
                files[role] = os.path.join(tmp, f"{role}.npz")
                with open(files[role], "wb") as f:
                    f.write(f"not a network: {role}".encode("ascii"))
            digests = {}
            for role, path in files.items():
                with open(path, "rb") as f:
                    digests[role] = hashlib.sha256(f.read()).hexdigest()[:12]
            recorded = self.recorded(tmp, sha256_prefix={"main": "0" * 12, "foe": digests["foe"],
                                                         "opponent bot": digests["bot"]})
            argv = ["--checkpoint", files["main"], "--foe-net", files["foe"], "--teams-from", files["teams"],
                    "--step", "0", "--previous", "0", "--previous-run", recorded, "--opponent", f"bot={files['bot']}",
                    "--out", out]
            self.assertRefused("sha256_prefix of main", argv, out)
            # The pool's teams are compared as well: another pool is refused before any game, not found afterwards.
            recorded = self.recorded(tmp, sha256_prefix={"main": digests["main"], "foe": digests["foe"],
                                                         "teams": "0" * 12, "opponent bot": digests["bot"]})
            argv[argv.index("--previous-run") + 1] = recorded
            self.assertRefused("sha256_prefix of teams", argv, out)


class VerdictCliTest(unittest.TestCase):
    """`verdict RUN/ladder.json [--latency-run L/ladder.json]`: reads two JSON files, writes verdict.json, loads no
    network and no library."""

    def run_files(self, tmp, report, latency=None):
        run = os.path.join(tmp, "run", "ladder.json")
        write_json(run, report)
        lat = None
        if latency is not None:
            lat = os.path.join(tmp, "latency", "ladder.json")
            write_json(lat, latency)
        return run, lat

    def test_main_verdict_writes_verdict_json_next_to_the_run_without_loading_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, lat = self.run_files(tmp, passing_report(), latency_run())
            with mock.patch.dict(sys.modules, LIBRARIES), contextlib.redirect_stdout(io.StringIO()) as printed:
                code = ladder.main(["verdict", run, "--latency-run", lat])
            self.assertEqual(code, 0)
            with open(os.path.join(tmp, "run", "verdict.json"), encoding="utf-8") as f:
                written = json.load(f)
            self.assertTrue(written["adopt"])
            self.assertEqual(json.loads(printed.getvalue())["adopt"], True)

    def test_without_a_latency_run_the_verdict_is_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, _ = self.run_files(tmp, passing_report())
            with mock.patch.dict(sys.modules, LIBRARIES), contextlib.redirect_stdout(io.StringIO()):
                ladder.main(["verdict", run])  # dispatched by main's first argument
            with open(os.path.join(tmp, "run", "verdict.json"), encoding="utf-8") as f:
                written = json.load(f)
            self.assertIsNone(written["adopt"])
            self.assertIsNone(written["gates"]["latency"])

    def test_a_mismatched_latency_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, lat = self.run_files(tmp, passing_report(), latency_run(commit="other"))
            with mock.patch.dict(sys.modules, LIBRARIES), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(SystemExit, "commit"):
                    ladder.main(["verdict", run, "--latency-run", lat])
            self.assertFalse(os.path.exists(os.path.join(tmp, "run", "verdict.json")))


class MainVerdictCliTest(unittest.TestCase):
    def test_verdict_of_a_run_without_a_head_to_head_is_refused(self):
        report = passing_report()
        report["h2h"] = None
        with tempfile.TemporaryDirectory() as tmp:
            run = os.path.join(tmp, "ladder.json")
            write_json(run, report)
            with mock.patch.dict(sys.modules, LIBRARIES), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(SystemExit, "--h2h"):
                    ladder.main(["verdict", run])


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


# --- budget scaling, --paired-with and the duplicate-row share (owner, 2026-10-12) ---

# The budget-scaling arms, written out again: each is step 0's settings plus exactly this delta.
BUDGET = {"b-s32": {"s": 32, "capacity": 2048}, "b-s64": {"s": 64, "capacity": 4096},
          "b-s128": {"s": 128, "capacity": 8192}, "b-s256": {"s": 256, "capacity": 16384},
          "b-k16": {"k": 16, "capacity": 2048}, "b-m16": {"m": 16, "capacity": 2048},
          "b-km16": {"k": 16, "m": 16, "capacity": 4096}, "b-km16-s64": {"k": 16, "m": 16, "s": 64, "capacity": 16384}}
# The budget of each arm relative to step 0's 8 * 8 * 16 leaves.
FACTORS = {"b-s32": 2, "b-s64": 4, "b-s128": 8, "b-s256": 16, "b-k16": 2, "b-m16": 2, "b-km16": 4, "b-km16-s64": 16}
DIGESTS = {"main": "a" * 64, "foe": "b" * 64, "teams": "c" * 64, "opponent bot": "d" * 64}


def prefixes(changed=None):
    """The sha256_prefix of DIGESTS (12 characters each), with the roles in changed replaced."""
    out = {role: digest[:12] for role, digest in DIGESTS.items()}
    out.update(changed or {})
    return out


def paired_recorded(pairs=4, seed=ladder.SEED, max_steps=1000, sha=None, names=("bot",)):
    """A recorded step-0 ladder.json as main writes it, for --paired-with: the conditions the guard reads, and each
    named opponent's step arm with 2 * pairs games."""
    conditions = {"seed": hex(seed), "pairs": pairs, "max_steps": max_steps, "commit": "c0ffee",
                  "step": {"name": "0", "settings": {}}, "sha256_prefix": prefixes() if sha is None else sha}
    return {"conditions": conditions,
            "opponents": {name: {"arms": {"step": {"scores": [1.0, 0.0] * pairs}}} for name in names}}


def table_record(table, env=0, **extra):
    """A searched decision with its k x m table, as honest writes it: the fields duplicate_rows and _summary read."""
    record = {**decision(env, 0, 0), **searched(len(table), len(table[0]), 1), "table": table, "wall": 0.01}
    record.update(extra)
    return record


def stand_in_files(directory):
    """Real files for the CLI's hashes (they are hashed, never loaded as networks): role -> (path, sha256 hex)."""
    files = {}
    for role in ("main", "foe", "bot", "teams"):
        data = f"not a network: {role}".encode("ascii")
        path = os.path.join(directory, f"{role}.npz")
        with open(path, "wb") as f:
            f.write(data)
        files[role] = (path, hashlib.sha256(data).hexdigest())
    return files


class BudgetStepsTest(unittest.TestCase):
    def test_step_zero_is_unchanged_and_each_budget_arm_is_declared_on_base_zero(self):
        self.assertEqual(ladder.STEPS["0"], {"base": None, "settings": {}})
        for name, delta in BUDGET.items():
            with self.subTest(step=name):
                self.assertEqual(ladder.STEPS[name], {"base": "0", "settings": delta})

    def test_each_budget_step_is_step_zero_plus_exactly_its_delta(self):
        base = ladder.step_settings("0")
        for name, delta in BUDGET.items():
            with self.subTest(step=name):
                got = ladder.step_settings(name)
                self.assertEqual(got, {**base, **delta})
                self.assertEqual({key for key in got if got[key] != base[key]}, set(delta))

    def test_capacity_is_k_times_m_times_s(self):
        for name in BUDGET:
            with self.subTest(step=name):
                got = ladder.step_settings(name)
                self.assertEqual(got["capacity"], got["k"] * got["m"] * got["s"])

    def test_the_budget_factor_of_each_arm_is_its_declared_multiple_of_step_zero(self):
        base = ladder.step_settings("0")
        base_budget = base["k"] * base["m"] * base["s"]
        self.assertEqual(base_budget, 1024)
        for name, factor in FACTORS.items():
            with self.subTest(step=name):
                got = ladder.step_settings(name)
                self.assertEqual(got["k"] * got["m"] * got["s"], factor * base_budget)


class PairedAgainstRecordedTest(unittest.TestCase):
    def test_the_recorded_steps_first_2_pairs_games_are_the_comparison_and_the_rest_is_ignored(self):
        recorded = paired_recorded(pairs=4)
        recorded["opponents"]["bot"]["arms"]["step"]["scores"] = [1.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0]
        scores = [1.0, 1.0, 0.0, 0.0]
        got = ladder.paired_against_recorded(scores, recorded, "bot", 2)  # the tail would raise a shape error
        self.assertEqual(got, ladder.paired_h(scores, [1.0, 1.0, 0.0, 0.0]))
        self.assertEqual(got["mean"], 0.5)

    def test_the_comparison_is_the_paired_h_of_this_step_against_the_recorded_step(self):
        recorded = paired_recorded(pairs=2)  # [1, 0, 1, 0]
        got = ladder.paired_against_recorded([0.0, 0.0, 0.0, 0.0], recorded, "bot", 2)
        self.assertAlmostEqual(got["mean"], ladder.paired_h([0.0] * 4, [1.0, 0.0, 1.0, 0.0])["mean"])
        self.assertAlmostEqual(got["mean"], 0.25)


class PairedWithConditionTest(unittest.TestCase):
    def test_the_conditions_record_the_step_commit_and_the_basename_only(self):
        got = ladder.paired_with_condition(paired_recorded(), os.path.join("runs", "step0", "ladder.json"))
        self.assertEqual(got, {"step": "0", "commit": "c0ffee", "file": "ladder.json"})


class PairedGuardTest(unittest.TestCase):
    def guard(self, recorded=None, seed=ladder.SEED, pairs=4, max_steps=1000, digests=DIGESTS):
        ladder.paired_guard(paired_recorded() if recorded is None else recorded, seed, pairs, max_steps, digests)

    def test_a_matching_run_passes_and_a_larger_recorded_run_passes(self):
        self.guard()
        self.guard(paired_recorded(pairs=8), pairs=4)  # the first games of the larger run are these games

    def test_the_seed_and_max_steps_must_be_equal(self):
        with self.assertRaisesRegex(SystemExit, "--paired-with's seed"):
            self.guard(paired_recorded(seed=ladder.SEED + 1))
        with self.assertRaisesRegex(SystemExit, "--paired-with's max_steps"):
            self.guard(max_steps=999)

    def test_the_recorded_run_needs_at_least_as_many_pairs(self):
        with self.assertRaisesRegex(SystemExit, "--paired-with's pairs"):
            self.guard(paired_recorded(pairs=2), pairs=4)

    def test_main_foe_teams_and_each_opponent_must_match_by_prefix(self):
        for role in ("main", "foe", "teams", "opponent bot"):
            with self.subTest(role=role), self.assertRaisesRegex(SystemExit, f"sha256_prefix of {role}"):
                self.guard(paired_recorded(sha=prefixes({role: "0" * 12})))

    def test_a_missing_sha256_prefix_is_a_mismatch(self):
        sha = prefixes()
        del sha["opponent bot"]
        with self.assertRaisesRegex(SystemExit, "sha256_prefix of opponent bot"):
            self.guard(paired_recorded(sha=sha))

    def test_an_opponent_missing_from_the_recorded_run_is_refused(self):
        with self.assertRaisesRegex(SystemExit, "no step arm for opponent 'bot'"):
            self.guard(paired_recorded(names=()))

    def test_the_recorded_step_arm_needs_two_games_per_pair_of_this_run(self):
        recorded = paired_recorded(pairs=4)
        recorded["opponents"]["bot"]["arms"]["step"]["scores"] = [1.0, 0.0] * 3  # 6 games; 4 pairs need 8
        with self.assertRaisesRegex(SystemExit, "this run needs 8"):
            self.guard(recorded)


class PairedWithCliTest(unittest.TestCase):
    """--paired-with excludes --previous, --h2h and --previous-run; its guard refuses before any network is loaded."""

    def argv(self, out, extra=()):
        return ["--checkpoint", "missing/main.npz", "--foe-net", "missing/foe.npz", "--teams-from", "missing/pool.npz",
                "--step", "b-k16", "--opponent", "bot=missing/bot.npz", "--out", out, *extra]  # under the LP limit

    def test_it_excludes_previous_h2h_and_previous_run(self):
        cases = {"--previous": ("--previous", "0"), "--h2h": ("--h2h",),
                 "--previous-run": ("--previous-run", "missing/ladder.json")}
        for flag, extra in cases.items():
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as tmp:
                out = os.path.join(tmp, "out")
                with self.assertRaisesRegex(SystemExit, f"excludes {flag}"):
                    ladder.main(self.argv(out, ("--paired-with", "missing/ladder.json", *extra)))
                self.assertFalse(os.path.exists(out))

    def test_a_different_main_network_is_refused_before_any_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            files = stand_in_files(tmp)
            digest = {role: sha for role, (_, sha) in files.items()}
            sha = {"main": "0" * 12, "foe": digest["foe"][:12], "teams": digest["teams"][:12],
                   "opponent bot": digest["bot"][:12]}
            recorded = os.path.join(tmp, "recorded", "ladder.json")
            write_json(recorded, paired_recorded(pairs=4, sha=sha))
            argv = ["--checkpoint", files["main"][0], "--foe-net", files["foe"][0], "--teams-from", files["teams"][0],
                    "--step", "b-k16", "--paired-with", recorded, "--opponent", f"bot={files['bot'][0]}",
                    "--pairs", "4", "--out", out]
            with self.assertRaisesRegex(SystemExit, "sha256_prefix of main"):
                ladder.main(argv)
            self.assertFalse(os.path.exists(out))


class DuplicateRowsTest(unittest.TestCase):
    def test_a_row_equal_to_an_earlier_row_of_its_table_is_counted_once(self):
        four = table_record([[1.0, 2.0], [1.0, 2.0 + 5e-7], [3.0, 4.0], [3.0, 4.0]])  # rows 1 and 3 repeat
        two = table_record([[0.0, 0.0, 0.0], [0.0, 0.0, 0.5]])
        got = ladder.duplicate_rows([four, two])
        self.assertEqual(got, {"decisions": 2, "decisions_with_duplicates": 1, "rows": 6, "duplicate_rows": 2,
                               "share": 2 / 6})

    def test_the_tolerance_is_one_millionth_of_the_largest_absolute_difference(self):
        self.assertEqual(ladder.duplicate_rows([table_record([[1.0], [1.0 + 5e-7]])])["duplicate_rows"], 1)
        self.assertEqual(ladder.duplicate_rows([table_record([[1.0], [1.0 + 2e-6]])])["duplicate_rows"], 0)

    def test_rows_are_compared_within_their_own_table_only(self):
        same = [[1.0, 2.0], [3.0, 4.0]]
        got = ladder.duplicate_rows([table_record(same), table_record(same)])
        self.assertEqual(got, {"decisions": 2, "decisions_with_duplicates": 0, "rows": 4, "duplicate_rows": 0,
                               "share": 0.0})

    def test_preview_records_and_other_kinds_are_ignored(self):
        dup = [[1.0], [1.0]]
        records = [table_record(dup, preview_eval="full"), {"kind": "raw"}, {"kind": "team"}, table_record([[1.0]])]
        self.assertEqual(ladder.duplicate_rows(records), {"decisions": 1, "decisions_with_duplicates": 0, "rows": 1,
                                                          "duplicate_rows": 0, "share": 0.0})

    def test_no_records_is_a_zero_share(self):
        self.assertEqual(ladder.duplicate_rows([]), {"decisions": 0, "decisions_with_duplicates": 0, "rows": 0,
                                                     "duplicate_rows": 0, "share": 0.0})

    def test_a_table_that_is_not_k_by_m_is_refused(self):
        bad = table_record([[1.0, 2.0], [3.0, 4.0]])
        bad["k"] = 3
        with self.assertRaises(ValueError):
            ladder.duplicate_rows([bad])


class SummaryDuplicateRowsTest(unittest.TestCase):
    def test_a_searching_arm_stores_its_duplicate_rows_and_a_raw_arm_does_not(self):
        records = {"result": np.array([1, -1]), "unfinished": np.zeros(2, int), "unresolved": np.zeros(2, int)}
        decisions = [table_record([[1.0, 2.0], [1.0, 2.0]]), decision(0, 0, 1, kind="team")]
        with mock.patch.object(arena, "diagnostics", return_value={}):
            searching = ladder._summary(records, 2, decisions, 1.5)
            raw = ladder._summary(records, 2)
        self.assertEqual(searching["duplicate_rows"], ladder.duplicate_rows(decisions))
        self.assertEqual(searching["duplicate_rows"]["duplicate_rows"], 1)
        self.assertNotIn("duplicate_rows", raw)


class StepsLeftTest(unittest.TestCase):
    """D2's steps_left through the harness (plan docs/superpowers/plans/2026-10-14-depth-search-d2.md step 6): a
    SearchPlayer that knows play_suite's max_steps passes each decision's steps left; one that does not calls decide
    as before."""

    class Recorder:
        def __init__(self):
            self.calls = []

        def decide(self, roots, envs, seats, keys, last_step, **extra):
            self.calls.append((np.asarray(last_step).tolist(), extra))
            return np.zeros(len(envs), np.int64), [{"env": int(e)} for e in envs]

    def indices(self, player, step, last_step):
        import duoforge
        from duoforge import _layout
        with duoforge.Context(_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as batch:
            batch.query_factored()
            choices = np.zeros((1, 2), _layout.FACTORED_CHOICE)
            player.indices(batch, choices, step=step, seats=np.array([0]), last_step=last_step)

    def test_max_steps_gives_each_decision_its_steps_left(self):
        recorder = self.Recorder()
        player = arena.SearchPlayer(recorder, "d2", 1, max_steps=10)
        self.indices(player, 3, False)
        self.indices(player, 9, True)
        self.assertEqual([extra["steps_left"].tolist() for _, extra in recorder.calls], [[7], [1]])

    def test_without_max_steps_decide_is_called_as_before(self):
        recorder = self.Recorder()
        self.indices(arena.SearchPlayer(recorder, "d1", 1), 3, False)
        self.assertEqual(recorder.calls, [([False], {})])

    def test_steps_left_must_agree_with_the_last_step_flag(self):
        player = arena.SearchPlayer(self.Recorder(), "d2", 1, max_steps=10)
        for step, last_step in ((9, False), (3, True)):
            with self.subTest(step=step), self.assertRaisesRegex(ValueError, "max_steps"):
                self.indices(player, step, last_step)
        with self.assertRaisesRegex(ValueError, "max_steps"):
            arena.SearchPlayer(self.Recorder(), "d2", 1, max_steps=0)

    def test_the_timed_wrapper_passes_steps_left_through(self):
        recorder = self.Recorder()
        timed = foe_arena.Timed(recorder)
        timed.decide(None, np.array([0, 1]), np.array([0, 0]), np.array([5, 6], np.uint64), np.array([False, False]),
                     steps_left=np.array([4, 3]))
        timed.decide(None, np.array([0]), np.array([0]), np.array([5], np.uint64), np.array([False]))
        self.assertEqual([extra["steps_left"].tolist() if "steps_left" in extra else None
                          for _, extra in recorder.calls], [[4], [3], None])


if __name__ == "__main__":
    unittest.main()
