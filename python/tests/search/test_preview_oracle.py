"""The preview oracle (issue #458): its arms, the foe's preview draw, the preview wrappers, the statistics and the
summary, over NumPy arrays and fake searches. No network and no checkpoint: the CLI's guards run before any is loaded."""
import json
import os
import tempfile
import unittest

import numpy as np

from duoforge_learn.selfplay import TEAM_TABLE
from duoforge_live.data import ROOT
from duoforge_search import preview_oracle as oracle


class FakeTimed:
    """A Timed search that decides every root by a fixed record per env: (boundary, kind, choice)."""

    def __init__(self, plays):
        self.plays, self.cleared = plays, 0

    def clear(self):
        self.cleared += 1

    def decide(self, roots, envs, seats, keys, last_step):
        records = []
        for e, p in zip(envs, seats):
            boundary, kind, choice = self.plays[int(e)]
            records.append({"env": int(e), "seat": int(p), "boundary": boundary, "kind": kind, "choice": choice})
        return np.array([r["choice"] for r in records], np.int64), records


class FakeSearch:
    """The two pieces of a search that DrawnPreview reads: encoder and ext_supported for roots.query_encoded, and
    _policy, whose team head is heads[env] (log probabilities over TEAM_TABLE)."""
    encoder, ext_supported = 4, 0

    def __init__(self, heads):
        self.heads = heads

    def _policy(self, obs, slots, pairs):
        with np.errstate(divide="ignore"):  # a zero probability is log 0 = -inf, as a masked head's
            return None, np.log(self.heads[int(obs[0])])[None, :], None


class FakeRoots:
    """query_encoded's three arrays, indexed [env, seat]: obs carries the env, so FakeSearch finds its head."""

    def __init__(self, games):
        self.games = games

    def query_encoded(self, encoder, ext_supported):
        obs = np.repeat(np.arange(self.games)[:, None], 2, axis=1)
        return obs, np.zeros_like(obs), np.zeros_like(obs)


def uniform_head():
    return np.full(len(TEAM_TABLE), 1.0 / len(TEAM_TABLE))


class ArmsTest(unittest.TestCase):
    def test_ninety_combinations_each_one_team_row(self):
        names = oracle.combos()
        self.assertEqual(len(names), 90)
        self.assertEqual(len(set(names)), 90)
        rows = {oracle.team_index(name) for name in names}
        self.assertEqual(len(rows), 90)
        for name in names:
            self.assertEqual(oracle.arm_of(oracle.team_index(name)), name)

    def test_fifteen_bring_sets_of_six_lead_pairs(self):
        brought = {}
        for name in oracle.combos():
            leads, bench = oracle.parse_arm(name)
            brought.setdefault(tuple(sorted(leads + bench)), []).append(leads)
        self.assertEqual(len(brought), 15)
        self.assertTrue(all(len(v) == 6 for v in brought.values()))

    def test_a_team_row_is_leads_then_bench(self):
        self.assertEqual([int(x) for x in TEAM_TABLE[oracle.team_index("24|01")]], [2, 4, 0, 1])

    def test_arm_of_drops_side_and_bench_order(self):
        row = int(np.flatnonzero((TEAM_TABLE == np.array([4, 2, 1, 0], TEAM_TABLE.dtype)).all(axis=1))[0])
        self.assertEqual(oracle.arm_of(row), "24|01")

    def test_bad_arm_names_are_refused(self):
        for bad in ("today", "2401", "24|0", "42|01", "24|10", "24|24", "26|01", "2a|01", "24|01|"):
            with self.assertRaises(ValueError, msg=bad):
                oracle.parse_arm(bad)

    def test_all_is_today_and_the_combinations(self):
        arms = oracle.arms_of("all")
        self.assertEqual(arms[0], "today")
        self.assertEqual(arms[1:], oracle.combos())

    def test_a_comma_list_is_checked(self):
        self.assertEqual(oracle.arms_of("today, 24|01"), ["today", "24|01"])
        for bad in ("", "24|01,24|01", "today,42|01"):
            with self.assertRaises(ValueError, msg=bad):
                oracle.arms_of(bad)


class DrawChoiceTest(unittest.TestCase):
    def test_the_draw_is_a_function_of_key_and_seed(self):
        probs = np.full(len(TEAM_TABLE), 1.0 / len(TEAM_TABLE))
        a = [oracle.draw_choice(probs, k, oracle.SEED) for k in range(50)]
        self.assertEqual(a, [oracle.draw_choice(probs, k, oracle.SEED) for k in range(50)])
        self.assertNotEqual(a, [oracle.draw_choice(probs, k, oracle.SEED + 1) for k in range(50)])

    def test_the_draw_follows_the_probabilities(self):
        probs = np.zeros(len(TEAM_TABLE))
        probs[[3, 7]] = [0.25, 0.75]
        drawn = np.array([oracle.draw_choice(probs, k, oracle.SEED) for k in range(4000)])
        self.assertTrue(set(drawn.tolist()) <= {3, 7})
        self.assertAlmostEqual(float((drawn == 7).mean()), 0.75, delta=0.03)


class ForcedPreviewTest(unittest.TestCase):
    def test_team_decisions_play_the_forced_row_and_others_stay(self):
        timed = FakeTimed({0: ("TEAM_SELECTION", "team", 11), 1: ("TURN", "searched", 5)})
        forced = oracle.ForcedPreview(timed, 42)
        actions, records = forced.decide(None, np.array([0, 1]), np.array([0, 1]), np.array([1, 2]), np.zeros(2, bool))
        self.assertEqual(actions.tolist(), [42, 5])
        self.assertEqual(records[0]["choice"], 42)
        self.assertEqual(records[0]["own_choice"], 11)
        self.assertNotIn("own_choice", records[1])
        forced.clear()
        self.assertEqual(timed.cleared, 1)

    def test_today_keeps_the_search_choice(self):
        timed = FakeTimed({0: ("TEAM_SELECTION", "team", 11)})
        actions, records = oracle.ForcedPreview(timed, None).decide(None, np.array([0]), np.array([0]), np.array([1]),
                                                                    np.zeros(1, bool))
        self.assertEqual(actions.tolist(), [11])
        self.assertEqual(records[0]["own_choice"], 11)

    def test_a_searched_preview_is_refused(self):
        timed = FakeTimed({0: ("TEAM_SELECTION", "unreconstructible", 11)})
        with self.assertRaisesRegex(RuntimeError, "unreconstructible"):
            oracle.ForcedPreview(timed, 42).decide(None, np.array([0]), np.array([0]), np.array([1]), np.zeros(1, bool))


class DrawnPreviewTest(unittest.TestCase):
    def test_team_decisions_are_drawn_from_the_head_and_recorded(self):
        timed = FakeTimed({0: ("TEAM_SELECTION", "team", 11), 1: ("TEAM_SELECTION", "team", 12),
                           2: ("TURN", "searched", 5)})
        head = uniform_head()
        drawn = oracle.DrawnPreview(timed, FakeSearch({0: head, 1: head, 2: head}), oracle.SEED)
        keys = np.array([101, 102, 103], np.uint64)
        actions, records = drawn.decide(FakeRoots(3), np.array([0, 1, 2]), np.array([1, 1, 1]), keys,
                                        np.zeros(3, bool))
        expected = [oracle.draw_choice(head, int(k), oracle.SEED) for k in keys[:2]]
        self.assertEqual(actions.tolist(), expected + [5])
        self.assertEqual(drawn.drawn, {0: expected[0], 1: expected[1]})
        self.assertEqual([r["own_choice"] for r in records[:2]], [11, 12])
        self.assertNotIn("own_choice", records[2])
        drawn.clear()
        self.assertEqual(drawn.drawn, {})
        self.assertEqual(timed.cleared, 1)

    def test_the_keep_mask_restricts_the_draw(self):
        keep = oracle.lead_mask(FoeLeadTest.SPECIES, "Charizard,Venusaur")
        plays = {e: ("TEAM_SELECTION", "team", 0) for e in range(40)}
        head = uniform_head()
        drawn = oracle.DrawnPreview(FakeTimed(plays), FakeSearch({e: head for e in range(40)}), oracle.SEED, keep)
        keys = np.arange(40, dtype=np.uint64)
        actions, _ = drawn.decide(FakeRoots(40), np.arange(40), np.zeros(40, np.int64), keys, np.zeros(40, bool))
        self.assertTrue(all(keep[a] for a in actions))
        self.assertEqual(actions.tolist(), [oracle.draw_choice(head * keep, int(k), oracle.SEED) for k in keys])

    def test_a_head_that_differs_between_games_of_a_seat_is_refused(self):
        other = uniform_head()
        other[:2] = [2.0 / len(TEAM_TABLE), 0.0]
        timed = FakeTimed({0: ("TEAM_SELECTION", "team", 0), 1: ("TEAM_SELECTION", "team", 0)})
        drawn = oracle.DrawnPreview(timed, FakeSearch({0: uniform_head(), 1: other}), oracle.SEED)
        with self.assertRaisesRegex(RuntimeError, "differs between games of seat 0"):
            drawn.decide(FakeRoots(2), np.array([0, 1]), np.array([0, 0]), np.array([1, 2], np.uint64),
                         np.zeros(2, bool))

    def test_the_two_seats_keep_their_own_heads(self):
        other = uniform_head()
        other[:2] = [2.0 / len(TEAM_TABLE), 0.0]
        timed = FakeTimed({0: ("TEAM_SELECTION", "team", 0), 1: ("TEAM_SELECTION", "team", 0)})
        drawn = oracle.DrawnPreview(timed, FakeSearch({0: uniform_head(), 1: other}), oracle.SEED)
        drawn.decide(FakeRoots(2), np.array([0, 1]), np.array([0, 1]), np.array([1, 2], np.uint64), np.zeros(2, bool))
        self.assertEqual(sorted(drawn.heads), [0, 1])

    def test_a_searched_preview_is_refused(self):
        timed = FakeTimed({0: ("TEAM_SELECTION", "unreconstructible", 0)})
        drawn = oracle.DrawnPreview(timed, FakeSearch({0: uniform_head()}), oracle.SEED)
        with self.assertRaisesRegex(RuntimeError, "unreconstructible"):
            drawn.decide(FakeRoots(1), np.array([0]), np.array([0]), np.array([1], np.uint64), np.zeros(1, bool))


class FoeLeadTest(unittest.TestCase):
    SPECIES = ["Charizard", "Venusaur", "Garchomp", "Incineroar", "Sylveon", "Farigiraf"]

    def test_the_mask_keeps_the_rows_that_lead_with_the_pair(self):
        keep = oracle.lead_mask(self.SPECIES, "Venusaur, charizard")
        self.assertEqual(int(keep.sum()), 2 * 4 * 3)  # two lead orders, then 4 * 3 ordered benches
        self.assertTrue(all(sorted(TEAM_TABLE[i, :2].tolist()) == [0, 1] for i in np.flatnonzero(keep)))

    def test_bad_pairs_are_refused_by_name(self):
        with self.assertRaisesRegex(SystemExit, "no 'Pikachu'"):
            oracle.lead_mask(self.SPECIES, "Charizard,Pikachu")
        with self.assertRaisesRegex(SystemExit, "two species"):
            oracle.lead_mask(self.SPECIES, "Charizard")
        with self.assertRaisesRegex(SystemExit, "twice"):
            oracle.lead_mask(self.SPECIES, "Charizard,Charizard")

    def test_a_masked_draw_leads_with_the_pair(self):
        keep = oracle.lead_mask(self.SPECIES, "Charizard,Venusaur")
        probs = np.full(len(TEAM_TABLE), 1.0 / len(TEAM_TABLE)) * keep
        for k in range(200):
            self.assertEqual(sorted(TEAM_TABLE[oracle.draw_choice(probs, k, oracle.SEED), :2].tolist()), [0, 1])


class FallbackCausesTest(unittest.TestCase):
    def test_causes_reason_or_kind(self):
        decisions = [{"kind": "searched"}, {"kind": "team"},
                     {"kind": "unreconstructible", "causes": ["visible_sleep"], "reason": "x"},
                     {"kind": "unreconstructible", "reason": "missing team-preview record"},
                     {"kind": "raw"}, {"kind": "unreconstructible", "causes": ["visible_sleep", "substitute"]}]
        self.assertEqual(oracle.fallback_causes(decisions),
                         {"missing team-preview record": 1, "raw": 1, "substitute": 1, "visible_sleep": 2})


class StatisticsTest(unittest.TestCase):
    def test_paired_difference_in_points(self):
        a = np.array([1, 1, 1, 0, 1, 1, 0, 0], np.float64)
        b = np.array([0, 1, 1, 0, 0, 1, 0, 0], np.float64)
        out = oracle.paired_difference(a, b)
        self.assertEqual(out["pairs"], 4)
        self.assertAlmostEqual(out["points"], 25.0)
        self.assertLessEqual(out["95"][0], 25.0)
        self.assertGreaterEqual(out["95"][1], 25.0)

    def test_paired_difference_needs_the_same_pairs(self):
        with self.assertRaises(ValueError):
            oracle.paired_difference(np.ones(4), np.ones(6))
        with self.assertRaises(ValueError):
            oracle.paired_difference(np.ones(3), np.ones(3))

    def test_identical_combinations_have_no_spread(self):
        s = np.array([1, 0, 1, 1, 0, 0, 1, 0], np.float64)
        out = oracle.spread({"a": s, "b": s.copy(), "c": s.copy()})
        self.assertEqual(out["range_points"], 0.0)
        self.assertEqual(out["true_sd_points"], 0.0)
        self.assertGreater(out["noise_points"], 0.0)

    def test_noise_free_combinations_keep_their_spread(self):
        out = oracle.spread({"a": np.ones(8), "b": np.zeros(8), "c": np.full(8, 0.5)})
        self.assertAlmostEqual(out["range_points"], 100.0)
        self.assertAlmostEqual(out["noise_points"], 0.0)
        self.assertAlmostEqual(out["true_sd_points"], out["sd_points"])
        self.assertAlmostEqual(out["sd_points"], 50.0)


    def test_common_noise_is_not_subtracted_by_the_paired_estimate(self):
        rng = np.random.default_rng(458)
        common = rng.random(400)  # the same games in every arm: only the offsets differ
        offsets = {"a": 0.0, "b": 0.1, "c": 0.2}
        out = oracle.spread({name: common + off for name, off in offsets.items()})
        self.assertAlmostEqual(out["paired_noise_points"], 0.0, places=9)
        self.assertAlmostEqual(out["true_sd_paired_points"], out["sd_points"], places=9)
        self.assertAlmostEqual(out["sd_points"], 10.0, places=9)
        self.assertLess(out["true_sd_points"], out["true_sd_paired_points"])  # the predeclared one is a lower bound

    def test_independent_noise_is_estimated_alike_by_both(self):
        rng = np.random.default_rng(459)
        out = oracle.spread({name: rng.random(20000) for name in "abcdefgh"})
        self.assertAlmostEqual(out["paired_noise_points"], out["noise_points"], delta=0.1)


class GuardTest(unittest.TestCase):
    def test_resume_ignores_commit_dirty_cpu_and_workers_only(self):
        conditions = {"seed": "0x1", "pairs": 32, "commit": "b", "dirty": True, "cpu": "y", "workers": 4}
        old = {"seed": "0x1", "pairs": 32, "commit": "a", "dirty": False, "cpu": "x", "workers": 8}
        self.assertEqual(oracle.resume_changes(old, conditions), [])
        self.assertEqual(oracle.resume_changes(dict(old, pairs=256, seed="0x2"), conditions), ["seed", "pairs"])

    def test_every_game_needs_a_foe_draw(self):
        oracle.check_drawn("24|01", {0: 1, 1: 2}, 2)
        with self.assertRaisesRegex(SystemExit, r"arm 24\|01: the foe drew no preview in 1 game"):
            oracle.check_drawn("24|01", {0: 1}, 2)

    def test_our_preview_must_play_the_arm(self):
        row = oracle.team_index("24|01")
        swapped = int(np.flatnonzero((TEAM_TABLE == np.array([4, 2, 1, 0], TEAM_TABLE.dtype)).all(axis=1))[0])
        turn = {"boundary": "TURN", "choice": 3}
        oracle.check_played("24|01", [{"boundary": "TEAM_SELECTION", "choice": row},
                                      {"boundary": "TEAM_SELECTION", "choice": swapped}, turn])
        oracle.check_played("today", [{"boundary": "TEAM_SELECTION", "choice": 0}])
        with self.assertRaisesRegex(SystemExit, r"played \['01\|23'\]"):
            oracle.check_played("24|01", [{"boundary": "TEAM_SELECTION", "choice": oracle.team_index("01|23")}])


class SummaryTest(unittest.TestCase):
    SPECIES = {"ours": ["O0", "O1", "O2", "O3", "O4", "O5"], "foe": ["F0", "F1", "F2", "F3", "F4", "F5"]}

    def write(self, out, arms, foe_drawn=None):
        os.makedirs(os.path.join(out, "arms"), exist_ok=True)
        with open(os.path.join(out, "conditions.json"), "w", encoding="utf-8") as f:
            json.dump({"species": self.SPECIES}, f)
        lead01 = oracle.team_index("01|23")
        for name, scores in arms.items():
            entry = {"arm": name, "scores": scores, "unfinished": 0, "unresolved": 0,
                     "foe_drawn": foe_drawn.get(name, [lead01] * len(scores)) if foe_drawn else [lead01] * len(scores),
                     "own_choice": {"0": "24|01", "1": "24|01"}, "fallback_share": {"ours": 0.0, "foe": 0.0}}
            with open(os.path.join(out, "arms", name.replace("|", "-") + ".json"), "w", encoding="utf-8") as f:
                json.dump(entry, f)

    def test_the_loss_is_the_best_combination_against_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, {"today": [0, 0, 1, 0], "24|01": [0, 0, 1, 0], "01|23": [1, 1, 1, 0],
                             "35|01": [0, 0, 0, 0]})
            out = oracle.summarize(tmp)
            self.assertEqual(out["ranking"], ["01|23", "24|01", "35|01"])
            self.assertEqual(out["loss"]["best"], "01|23")
            self.assertEqual(out["loss"]["today_combination"], ["24|01"])
            self.assertAlmostEqual(out["loss"]["points"]["points"], 50.0)
            self.assertAlmostEqual(out["spread"]["range_points"], 75.0)
            self.assertEqual(out["foe_preview"], {"games": 4, "leads": {"F0 + F1": 4}, "brought": {"F0 + F1 + F2 + F3": 4}})
            self.assertEqual(out["arms"]["01|23"]["members"], {"leads": ["O0", "O1"], "bench": ["O2", "O3"]})
            self.assertEqual(out["marginals"]["bring"]["0123"]["members"], ["O0", "O1", "O2", "O3"])
            self.assertTrue(os.path.exists(os.path.join(tmp, "oracle.json")))

    def test_arms_with_different_foe_previews_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = oracle.team_index("45|01")
            self.write(tmp, {"today": [0, 1], "01|23": [1, 1]}, foe_drawn={"01|23": [other, other]})
            with self.assertRaisesRegex(SystemExit, "not paired"):
                oracle.summarize(tmp)


class CliGuardTest(unittest.TestCase):
    """Each refusal raises SystemExit before any network is loaded and before the output directory exists."""

    def argv(self, out, extra=()):
        return ["--checkpoint", "missing/main.npz", "--foe-net", "missing/foe.npz", "--ours", "missing/a.txt",
                "--foe", "missing/b.txt", "--out", out] + list(extra)

    def assertRefused(self, pattern, argv, out):
        with self.assertRaisesRegex(SystemExit, pattern):
            oracle.main(argv)
        self.assertFalse(os.path.exists(out))

    def test_out_inside_the_repository_is_refused(self):
        out = os.path.join(str(ROOT), "preview-oracle-guard-test-out")
        self.assertRefused("inside the repository", self.argv(out), out)

    def test_bad_arms_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            self.assertRefused("ascending", self.argv(out, ("--arms", "42|01")), out)

    def test_pairs_must_be_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            self.assertRefused("positive", self.argv(out, ("--pairs", "0")), out)


if __name__ == "__main__":
    unittest.main()
