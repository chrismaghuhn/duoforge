"""The preview oracle (issue #458): its arms, the foe's preview draw, the preview wrappers, the statistics and the
summary, over NumPy arrays and fake searches. No network and no checkpoint: the CLI's guards run before any is loaded."""
import json
import os
import tempfile
import unittest
from unittest import mock

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
        for bad in ("", "24|01,24|01", "today,42|01", "drawn"):
            with self.assertRaises(ValueError, msg=bad):
                oracle.arms_of(bad)

    def test_the_foe_side_has_drawn_for_today(self):
        self.assertEqual(oracle.arms_of("all", "foe"), ["drawn"] + oracle.combos())
        self.assertEqual(oracle.arms_of("drawn,24|01", "foe"), ["drawn", "24|01"])
        with self.assertRaisesRegex(ValueError, "foe side"):
            oracle.arms_of("today,24|01", "foe")
        with self.assertRaises(ValueError):
            oracle.arms_of("all", "both")


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

    def test_a_run_from_before_the_foe_side_resumes_as_the_ours_side(self):
        old = {"seed": "0x1", "pairs": 32}
        self.assertEqual(oracle.resume_changes(old, {"seed": "0x1", "pairs": 32, "side": "ours"}), [])
        self.assertEqual(oracle.resume_changes(old, {"seed": "0x1", "pairs": 32, "side": "foe"}), ["side"])

    def test_a_mix_added_dropped_or_changed_is_another_measurement(self):
        old = {"seed": "0x1", "side": "foe", "our_arm": None, "our_mix": "23|04:1/2,today:1/2", "foe_mix": None}
        same = dict(old)
        self.assertEqual(oracle.resume_changes(old, same), [])
        self.assertEqual(oracle.resume_changes(old, dict(old, our_mix=None)), ["our_mix"])
        self.assertEqual(oracle.resume_changes(old, dict(old, our_mix="23|04:1/3,today:2/3")), ["our_mix"])
        before = {"seed": "0x1", "side": "foe", "our_arm": None}  # a run from before the mixes resumes without one
        self.assertEqual(oracle.resume_changes(before, dict(before, our_mix=None, foe_mix=None)), [])
        self.assertEqual(oracle.resume_changes(before, dict(before, our_mix="23|04:1", foe_mix=None)), ["our_mix"])

    def test_a_run_from_before_our_arm_resumes_without_it(self):
        old = {"seed": "0x1", "pairs": 32, "side": "foe"}
        self.assertEqual(oracle.resume_changes(old, {"seed": "0x1", "pairs": 32, "side": "foe", "our_arm": None}), [])
        self.assertEqual(oracle.resume_changes(old, {"seed": "0x1", "pairs": 32, "side": "foe", "our_arm": "23|04"}),
                         ["our_arm"])

    def test_our_own_preview_must_be_one_per_seat(self):
        a, b = oracle.team_index("24|01"), oracle.team_index("01|23")
        swapped = int(np.flatnonzero((TEAM_TABLE == np.array([4, 2, 1, 0], TEAM_TABLE.dtype)).all(axis=1))[0])
        team = lambda seat, own: {"boundary": "TEAM_SELECTION", "seat": seat, "own_choice": own}
        oracle.check_constant_own("45|23", [team(0, a), team(0, swapped), team(1, b), {"boundary": "TURN"}])
        with self.assertRaisesRegex(SystemExit, r"arm 45\|23: our own preview differs between games \(\{0: "):
            oracle.check_constant_own("45|23", [team(0, a), team(0, b), team(1, b)])

    def test_the_foe_previews_come_from_the_draw_or_the_team_records(self):
        drawn = oracle.DrawnPreview(None, None, oracle.SEED)
        drawn.drawn = {0: 5, 1: 6}
        self.assertEqual(oracle.foe_previews(drawn, []), {0: 5, 1: 6})
        forced = oracle.ForcedPreview(None, 7)
        decisions = [{"boundary": "TEAM_SELECTION", "env": 1, "choice": 7}, {"boundary": "TURN", "env": 0, "choice": 2},
                     {"boundary": "TEAM_SELECTION", "env": 0, "choice": 7}]
        self.assertEqual(oracle.foe_previews(forced, decisions), {0: 7, 1: 7})

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
        oracle.check_played("drawn", [{"boundary": "TEAM_SELECTION", "choice": 0}])
        with self.assertRaisesRegex(SystemExit, r"played \['01\|23'\]"):
            oracle.check_played("24|01", [{"boundary": "TEAM_SELECTION", "choice": oracle.team_index("01|23")}])

    def test_our_fixed_preview_must_play_in_every_arm(self):
        row = oracle.team_index("23|04")
        team = [{"boundary": "TEAM_SELECTION", "choice": row}, {"boundary": "TURN", "choice": 3}]
        oracle.check_played("drawn", team, combination="23|04")
        oracle.check_played("45|13", team, combination="23|04")
        with self.assertRaisesRegex(SystemExit, r"arm drawn: our preview played \['01\|23'\], not 23\|04"):
            oracle.check_played("drawn", [{"boundary": "TEAM_SELECTION", "choice": oracle.team_index("01|23")}],
                                combination="23|04")

    def test_an_arm_file_records_our_played_preview(self):
        forced, own = oracle.team_index("23|04"), oracle.team_index("24|03")
        records = {"unfinished": np.zeros(1, int), "unresolved": np.zeros(1, int)}
        decisions = [{"boundary": "TEAM_SELECTION", "kind": "team", "seat": 0, "choice": forced, "own_choice": own}]
        with mock.patch("duoforge_search.arena.scores", return_value=np.array([1.0])), \
                mock.patch.object(oracle.foe_arena, "fallback_share", return_value=0.0), \
                mock.patch.object(oracle.ladder, "decisions_digest", return_value="d"), \
                mock.patch.object(oracle.ladder, "wall_seconds", return_value=0.0):
            entry = oracle._arm_entry("drawn", records, decisions, [], [0], 1.0)
        self.assertEqual(entry["own_choice"], {"0": "24|03"})
        self.assertEqual(entry["our_played"], {"0": "23|04"})


class SummaryTest(unittest.TestCase):
    SPECIES = {"ours": ["O0", "O1", "O2", "O3", "O4", "O5"], "foe": ["F0", "F1", "F2", "F3", "F4", "F5"]}

    def write(self, out, arms, foe_drawn=None, side=None, own=None, played=None):
        os.makedirs(os.path.join(out, "arms"), exist_ok=True)
        with open(os.path.join(out, "conditions.json"), "w", encoding="utf-8") as f:
            json.dump({"species": self.SPECIES, **({"side": side} if side else {})}, f)
        lead01 = oracle.team_index("01|23")
        for name, scores in arms.items():
            entry = {"arm": name, "scores": scores, "unfinished": 0, "unresolved": 0,
                     "foe_drawn": foe_drawn.get(name, [lead01] * len(scores)) if foe_drawn else [lead01] * len(scores),
                     "own_choice": (own or {}).get(name, {"0": "24|01", "1": "24|01"}),
                     "fallback_share": {"ours": 0.0, "foe": 0.0}}
            if played and name in played:
                entry["our_played"] = played[name]
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


    def test_the_foe_side_ranks_the_foes_best_answers_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = {"drawn": oracle.team_index("01|23"), "45|23": oracle.team_index("45|23"),
                    "02|13": oracle.team_index("02|13")}
            self.write(tmp, {"drawn": [1, 1, 1, 0], "45|23": [0, 0, 1, 0], "02|13": [1, 1, 1, 1]}, side="foe",
                       foe_drawn={name: [row] * 4 for name, row in rows.items()})
            out = oracle.summarize(tmp)
            self.assertEqual(out["ranking"], ["45|23", "02|13"])
            self.assertEqual(out["exploitability"]["best_answer"], "45|23")
            self.assertAlmostEqual(out["exploitability"]["points"]["points"], 50.0)  # drawn 0.75 against 0.25
            self.assertEqual(out["exploitability"]["our_preview"], {"0": "24|01", "1": "24|01"})
            self.assertAlmostEqual(out["arms"]["45|23"]["vs_drawn"]["points"], -50.0)
            self.assertEqual(out["arms"]["45|23"]["members"], {"leads": ["F4", "F5"], "bench": ["F2", "F3"]})
            self.assertEqual(out["marginals"]["leads"]["45"]["members"], ["F4", "F5"])
            self.assertEqual(out["foe_preview"]["leads"], {"F0 + F1": 4})  # the drawn arm's previews
            self.assertNotIn("loss", out)
            self.assertNotIn("by_foe_lead", out)

    def test_the_foe_side_pairs_and_reports_our_played_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, {"drawn": [1, 1], "45|23": [0, 1]}, side="foe",
                       own={"drawn": {"0": "24|01", "1": "24|01"}, "45|23": {"0": "24|01", "1": "02|34"}},
                       played={name: {"0": "23|04", "1": "23|04"} for name in ("drawn", "45|23")})
            with open(os.path.join(tmp, "conditions.json"), encoding="utf-8") as f:
                conditions = json.load(f)
            with open(os.path.join(tmp, "conditions.json"), "w", encoding="utf-8") as f:
                json.dump(dict(conditions, our_arm="23|04"), f)
            out = oracle.summarize(tmp)  # our own choices differ, the played preview is one: paired
            self.assertEqual(out["exploitability"]["our_preview"], {"0": "23|04", "1": "23|04"})
            self.assertEqual(out["exploitability"]["our_arm"], "23|04")
            self.assertEqual(out["arms"]["drawn"]["our_played"], {"0": "23|04", "1": "23|04"})

    def test_the_foe_side_refuses_arms_that_did_not_play_our_arm(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, {"drawn": [1, 1], "45|23": [0, 1]}, side="foe",
                       played={name: {"0": "24|01", "1": "24|01"} for name in ("drawn", "45|23")})
            with open(os.path.join(tmp, "conditions.json"), encoding="utf-8") as f:
                conditions = json.load(f)
            with open(os.path.join(tmp, "conditions.json"), "w", encoding="utf-8") as f:
                json.dump(dict(conditions, our_arm="23|04"), f)
            with self.assertRaisesRegex(SystemExit, r"arms \['45\|23', 'drawn'\]: our preview did not play --our-arm"):
                oracle.summarize(tmp)

    def test_the_foe_side_refuses_arms_where_our_played_preview_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, {"drawn": [1, 1], "45|23": [0, 1]}, side="foe",
                       played={"drawn": {"0": "23|04", "1": "23|04"}, "45|23": {"0": "24|01", "1": "24|01"}})
            with self.assertRaisesRegex(SystemExit, "our previews differ: the arms are not paired"):
                oracle.summarize(tmp)

    def test_the_foe_side_refuses_arms_where_our_preview_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, {"drawn": [1, 1], "45|23": [0, 1]}, side="foe",
                       own={"45|23": {"0": "24|01", "1": "02|34"}})
            with self.assertRaisesRegex(SystemExit, "our previews differ: the arms are not paired"):
                oracle.summarize(tmp)


class MixTest(unittest.TestCase):
    def test_a_mix_parses_exactly_and_sorted(self):
        from fractions import Fraction as F
        mix = oracle.parse_mix(" today:0.5, 23|04:1/4,12|35:1/4 ", "ours")
        self.assertEqual(mix, [("12|35", F(1, 4)), ("23|04", F(1, 4)), ("today", F(1, 2))])
        self.assertEqual(oracle.mix_text(mix), "12|35:1/4,23|04:1/4,today:1/2")
        self.assertEqual(oracle.parse_mix(oracle.mix_text(mix), "ours"), mix)
        self.assertEqual(oracle.parse_mix("drawn:2/3,15|23:1/3", "foe"), [("15|23", F(1, 3)), ("drawn", F(2, 3))])

    def test_bad_mixes_are_refused(self):
        bad = {"23|04:1/2,today:1/3": "sum to 5/6", "23|04:1,today:0": "not positive", "23|04:2,today:-1": "positive",
               "23|04:1/2,23|04:1/2": "twice", "drawn:1": "no arm of the ours side", "32|04:1": "ascending",
               "23|04": "ARM:P", ":1": "ARM:P", "23|04:x": "no number", "23|04:1/0": "no number", "": "no arm"}
        for text, pattern in bad.items():
            with self.assertRaisesRegex(ValueError, pattern, msg=text):
                oracle.parse_mix(text, "ours")
        with self.assertRaisesRegex(ValueError, "no arm of the foe side"):
            oracle.parse_mix("today:1", "foe")

    def test_the_pick_is_a_function_of_key_seed_and_tag(self):
        mix = oracle.parse_mix("23|04:1/2,today:1/2", "ours")
        picks = [oracle.mix_pick(mix, k, oracle.SEED, oracle.OUR_MIX_TAG) for k in range(200)]
        self.assertEqual(picks, [oracle.mix_pick(mix, k, oracle.SEED, oracle.OUR_MIX_TAG) for k in range(200)])
        self.assertNotEqual(picks, [oracle.mix_pick(mix, k, oracle.SEED, oracle.FOE_MIX_TAG) for k in range(200)])
        self.assertNotEqual(picks, [oracle.mix_pick(mix, k, oracle.SEED + 1, oracle.OUR_MIX_TAG) for k in range(200)])
        self.assertEqual({oracle.mix_pick([("23|04", 1)], k, oracle.SEED, oracle.OUR_MIX_TAG) for k in range(50)},
                         {"23|04"})

    def test_the_pick_follows_the_probabilities(self):
        mix = oracle.parse_mix("23|04:1/4,today:3/4", "ours")
        picks = [oracle.mix_pick(mix, k, oracle.SEED, oracle.OUR_MIX_TAG) for k in range(4000)]
        self.assertAlmostEqual(picks.count("today") / 4000, 0.75, delta=0.03)

    def test_the_pick_is_apart_from_the_foes_draw(self):
        mix = oracle.parse_mix("01|23:1/2,45|23:1/2", "foe")
        head = uniform_head()
        draws = np.array([oracle.draw_choice(head, k, oracle.SEED) < len(TEAM_TABLE) // 2 for k in range(4000)])
        for tag in (oracle.FOE_MIX_TAG, oracle.OUR_MIX_TAG):  # the foe's mix shares the foe's keys with its draw
            picks = np.array([oracle.mix_pick(mix, k, oracle.SEED, tag) == "01|23" for k in range(4000)])
            self.assertLess(abs(float(np.corrcoef(picks, draws)[0, 1])), 0.06)


class MixedPreviewTest(unittest.TestCase):
    def play(self, mix_text, games=60, side="ours"):
        tag = oracle.OUR_MIX_TAG if side == "ours" else oracle.FOE_MIX_TAG
        plays = {e: ("TEAM_SELECTION", "team", 11) for e in range(games)}
        plays[games] = ("TURN", "searched", 5)
        head = uniform_head()
        timed = FakeTimed(plays)
        mixed = oracle.MixedPreview(timed, FakeSearch({e: head for e in range(games + 1)}), oracle.SEED,
                                    oracle.parse_mix(mix_text, side), tag)
        keys = np.arange(100, 101 + games, dtype=np.uint64)
        actions, records = mixed.decide(FakeRoots(games + 1), np.arange(games + 1), np.zeros(games + 1, np.int64), keys,
                                        np.zeros(games + 1, bool))
        return mixed, timed, keys, actions, records, head

    def test_each_game_plays_its_pick(self):
        mixed, timed, keys, actions, records, _ = self.play("23|04:1/2,today:1/2")
        for e in range(60):
            name = oracle.mix_pick(mixed.mix, int(keys[e]), oracle.SEED, mixed.tag)
            self.assertEqual(mixed.picked[e], name)
            self.assertEqual(int(actions[e]), 11 if name == "today" else oracle.team_index("23|04"))
            self.assertEqual(records[e]["own_choice"], 11)
            self.assertEqual(mixed.played[e], int(actions[e]))
        self.assertEqual(set(mixed.picked.values()), {"23|04", "today"})
        self.assertEqual(int(actions[60]), 5)
        self.assertNotIn("own_choice", records[60])
        self.assertNotIn(60, mixed.picked)
        mixed.clear()
        self.assertEqual((mixed.picked, mixed.played, timed.cleared), ({}, {}, 1))

    def test_drawn_draws_from_the_head_as_the_drawn_arm(self):
        mixed, _, keys, actions, _, head = self.play("drawn:1/2,45|23:1/2", side="foe")
        for e in range(60):
            if mixed.picked[e] == "drawn":
                self.assertEqual(int(actions[e]), oracle.draw_choice(head, int(keys[e]), oracle.SEED))
            else:
                self.assertEqual(int(actions[e]), oracle.team_index("45|23"))

    def test_a_searched_preview_is_refused(self):
        timed = FakeTimed({0: ("TEAM_SELECTION", "unreconstructible", 0)})
        mixed = oracle.MixedPreview(timed, None, oracle.SEED, [("23|04", 1)], oracle.OUR_MIX_TAG)
        with self.assertRaisesRegex(RuntimeError, "unreconstructible"):
            mixed.decide(None, np.array([0]), np.array([0]), np.array([1], np.uint64), np.zeros(1, bool))

    def test_the_check_passes_a_played_mix_and_counts_it(self):
        mixed, _, _, _, records, _ = self.play("23|04:1/2,today:1/2")
        counts = oracle.check_mix("drawn", mixed, records, 60)
        self.assertEqual(sum(counts.values()), 60)
        self.assertEqual(counts, {name: list(mixed.picked.values()).count(name) for name in ("23|04", "today")})

    def test_the_check_refuses_a_missing_pick_a_wrong_play_and_skewed_shares(self):
        mixed, _, _, _, records, _ = self.play("23|04:1/2,today:1/2")
        with self.assertRaisesRegex(SystemExit, r"arm drawn: our mix picked no preview in 1 game"):
            oracle.check_mix("drawn", mixed, records, 61)
        wrong = [dict(r) for r in records]
        e = next(e for e in range(60) if mixed.picked[e] == "23|04")
        wrong[e]["choice"] = oracle.team_index("01|23")
        with self.assertRaisesRegex(SystemExit, rf"picked 23\|04 in game {e}, but it played 01\|23"):
            oracle.check_mix("drawn", mixed, wrong, 60)
        skewed = oracle.MixedPreview(None, None, oracle.SEED, oracle.parse_mix("23|04:1/2,today:1/2", "ours"), 0)
        skewed.picked = {e: "23|04" for e in range(100)}
        with self.assertRaisesRegex(SystemExit, r"picked 23\|04 in 100 of 100 games, expected 50.0"):
            oracle.check_mix("45|23", skewed, [], 100)
        skewed.picked = {e: "01|23" for e in range(4)}
        with self.assertRaisesRegex(SystemExit, r"picked \['01\|23'\], which it does not hold"):
            oracle.check_mix("45|23", skewed, [], 4)

    def test_the_foe_previews_of_a_mix_are_its_played_rows(self):
        mixed = oracle.MixedPreview(None, None, oracle.SEED, [("drawn", 1)], oracle.FOE_MIX_TAG)
        mixed.played = {0: 4, 1: 9}
        self.assertEqual(oracle.foe_previews(mixed, []), {0: 4, 1: 9})

    def test_an_arm_file_records_a_varied_preview_and_the_picks(self):
        rows = [oracle.team_index("23|04"), oracle.team_index("12|35"), oracle.team_index("23|04")]
        decisions = [{"boundary": "TEAM_SELECTION", "kind": "team", "seat": 0, "choice": c,
                      "own_choice": oracle.team_index("24|03")} for c in rows]
        records = {"unfinished": np.zeros(3, int), "unresolved": np.zeros(3, int)}
        with mock.patch("duoforge_search.arena.scores", return_value=np.ones(3)), \
                mock.patch.object(oracle.foe_arena, "fallback_share", return_value=0.0), \
                mock.patch.object(oracle.ladder, "decisions_digest", return_value="d"), \
                mock.patch.object(oracle.ladder, "wall_seconds", return_value=0.0):
            entry = oracle._arm_entry("drawn", records, decisions, [], [0, 0, 0], 1.0,
                                      our_picked=["23|04", "12|35", "23|04"])
        self.assertEqual(entry["our_played"], {"0": ["12|35", "23|04"]})
        self.assertEqual(entry["our_picked"], ["23|04", "12|35", "23|04"])
        self.assertIsNone(entry["foe_picked"])


class MixSummaryTest(unittest.TestCase):
    SPECIES = SummaryTest.SPECIES
    write = SummaryTest.write

    def conditions(self, tmp, **extra):
        with open(os.path.join(tmp, "conditions.json"), encoding="utf-8") as f:
            conditions = json.load(f)
        with open(os.path.join(tmp, "conditions.json"), "w", encoding="utf-8") as f:
            json.dump(dict(conditions, **extra), f)

    def picks(self, tmp, key, picks):
        for name, value in picks.items():
            path = os.path.join(tmp, "arms", name.replace("|", "-") + ".json")
            with open(path, encoding="utf-8") as f:
                entry = json.load(f)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(dict(entry, **{key: value}), f)

    def test_the_foe_side_pairs_our_mix_by_its_picks(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, {"drawn": [1, 1], "45|23": [0, 1]}, side="foe")
            self.conditions(tmp, our_mix="23|04:1/2,today:1/2")
            self.picks(tmp, "our_picked", {"drawn": ["23|04", "today"], "45|23": ["23|04", "today"]})
            out = oracle.summarize(tmp)
            self.assertEqual(out["exploitability"]["our_mix"], "23|04:1/2,today:1/2")
            self.picks(tmp, "our_picked", {"45|23": ["today", "today"]})
            with self.assertRaisesRegex(SystemExit, "our picked previews of --our-mix differ: the arms are not paired"):
                oracle.summarize(tmp)

    def test_a_mixed_arm_files_lists_of_our_played_previews_summarize(self):
        with tempfile.TemporaryDirectory() as tmp:
            varied = {"0": ["23|04", "today"], "1": "23|04"}
            self.write(tmp, {"drawn": [1, 1], "45|23": [0, 1]}, side="foe",
                       played={name: varied for name in ("drawn", "45|23")})
            self.conditions(tmp, our_mix="23|04:1/2,today:1/2")
            self.picks(tmp, "our_picked", {"drawn": ["23|04", "today"], "45|23": ["23|04", "today"]})
            out = oracle.summarize(tmp)
            self.assertEqual(out["exploitability"]["our_preview"], varied)
            self.assertEqual(oracle.played_set({"our_played": varied, "own_choice": {}}), {"23|04", "today"})

    def test_the_ours_side_pairs_the_foe_mix_by_its_picks(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, {"today": [1, 1], "01|23": [0, 1]})
            self.conditions(tmp, foe_mix="drawn:1/2,45|23:1/2")
            self.picks(tmp, "foe_picked", {"today": ["drawn", "45|23"], "01|23": ["drawn", "drawn"]})
            with self.assertRaisesRegex(SystemExit, "foe picked previews of --foe-mix differ"):
                oracle.summarize(tmp)


class MatrixTest(unittest.TestCase):
    BASE = {"tool": "preview_oracle", "seed": "0x464", "pairs": 2, "games": 4, "max_steps": 1000, "step": {"name": "0"},
            "side": "foe", "foe_preview": "fixed", "ours_sha256_prefix": "a", "foe_sha256_prefix": "b",
            "registry": {}, "left_out": {}, "species": SummaryTest.SPECIES, "commit": "c0ffee", "dirty": False,
            "library": "0.45.0", "encoders": {}, "sha256_prefix": {}, "table_sha256": "t", "workers": 8}

    def run_dir(self, root, name, scores, our_arm=None, foe_drawn=None, commit="c0ffee", dirty=False, arm_dirty=None,
                played=None, **extra):
        d = os.path.join(root, name)
        os.makedirs(os.path.join(d, "arms"))
        games = len(next(iter(scores.values())))
        with open(os.path.join(d, "conditions.json"), "w", encoding="utf-8") as f:
            json.dump(dict(self.BASE, games=games, our_arm=our_arm, dirty=dirty, **extra), f)
        for arm, s in scores.items():
            row = oracle.team_index("01|23") if arm == "drawn" else oracle.team_index(arm)
            ours = (played or {}).get(arm, our_arm or "24|01")
            entry = {"arm": arm, "scores": s, "foe_drawn": (foe_drawn or {}).get(arm, [row] * len(s)), "commit": commit,
                     "dirty": dirty if arm_dirty is None else arm_dirty, "own_choice": {"0": "24|01", "1": "24|01"}, "our_played": {"0": ours, "1": ours}}
            with open(os.path.join(d, "arms", arm.replace("|", "-") + ".json"), "w", encoding="utf-8") as f:
                json.dump(entry, f)
        return d

    def test_the_matrix_of_mean_scores_and_its_equilibrium(self):
        from fractions import Fraction as F
        with tempfile.TemporaryDirectory() as tmp:
            a = self.run_dir(tmp, "today", {"drawn": [1, 1, 1, 0], "15|23": [0, 0, 1, 0]})
            b = self.run_dir(tmp, "c", {"drawn": [1, 0, 1, 0], "15|23": [1, 1, 0.5, 0.5]}, our_arm="23|04")
            rows, columns, scores, conditions = oracle.build_matrix([a, b])
            self.assertEqual((rows, columns), (["today", "23|04"], ["drawn", "15|23"]))
            self.assertEqual(scores, [[F(3, 4), F(1, 4)], [F(1, 2), F(3, 4)]])
            self.assertEqual(conditions["commit"], "c0ffee")
            out_file = os.path.join(tmp, "m1.json")
            with mock.patch("sys.stdout"):
                oracle.main(["matrix", a, b, "--out", out_file])
            with open(out_file, encoding="utf-8") as f:
                out = json.load(f)
            # 3/4 p + 1/2 (1 - p) = 1/4 p + 3/4 (1 - p): p = 1/3, value 7/12
            self.assertEqual(out["our_mix"], {"today": "1/3", "23|04": "2/3"})
            self.assertEqual(out["our_mix_text"], "23|04:2/3,today:1/3")
            self.assertEqual(out["foe_mix"], {"drawn": "2/3", "15|23": "1/3"})
            self.assertEqual(out["value_exact"], "7/12")
            self.assertAlmostEqual(out["value_points"], 700 / 12)
            # the gap of m1's mixes on the same matrix is zero
            with mock.patch("sys.stdout"):
                oracle.main(["matrix", a, b, "--out", os.path.join(tmp, "m2.json"), "--previous", out_file])
            with open(os.path.join(tmp, "m2.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["previous"]["gap_exact"], "0")

    def test_the_gap_on_a_wider_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self.run_dir(tmp, "today", {"drawn": [1, 1, 1, 0], "15|23": [0, 0, 1, 0]})
            b = self.run_dir(tmp, "c", {"drawn": [1, 0, 1, 0], "15|23": [1, 1, 0.5, 0.5]}, our_arm="23|04")
            first = os.path.join(tmp, "m1.json")
            with mock.patch("sys.stdout"):
                oracle.main(["matrix", a, b, "--out", first])
            for d, ours in ((a, "24|01"), (b, "23|04")):  # a new foe answer that beats both
                with open(os.path.join(d, "arms", "12-35.json"), "w", encoding="utf-8") as f:
                    json.dump({"arm": "12|35", "scores": [0, 0, 0, 0], "foe_drawn": [oracle.team_index("12|35")] * 4,
                               "commit": "c0ffee", "dirty": False, "our_played": {"0": ours, "1": ours},
                               "own_choice": {"0": "24|01", "1": "24|01"}}, f)
            with mock.patch("sys.stdout"):
                oracle.main(["matrix", a, b, "--out", os.path.join(tmp, "m2.json"), "--previous", first])
            with open(os.path.join(tmp, "m2.json"), encoding="utf-8") as f:
                prev = json.load(f)["previous"]
            self.assertEqual(prev["worst_column_exact"], "0")
            self.assertEqual(prev["best_row_exact"], "7/12")
            self.assertEqual(prev["gap_exact"], "7/12")

    def test_the_order_of_the_runs_does_not_matter(self):
        with tempfile.TemporaryDirectory() as tmp:  # a game whose equilibrium is not unique
            a = self.run_dir(tmp, "a", {"drawn": [1, 1], "15|23": [0, 0]}, our_arm="01|23")
            b = self.run_dir(tmp, "b", {"drawn": [0, 0], "15|23": [1, 1]}, our_arm="02|13")
            c = self.run_dir(tmp, "c", {"drawn": [0.5, 0.5], "15|23": [0.5, 0.5]})
            outs = []
            for i, dirs in enumerate(([a, b, c], [c, b, a], [b, a, c])):
                path = os.path.join(tmp, f"m{i}.json")
                with mock.patch("sys.stdout"):
                    oracle.main(["matrix", *dirs, "--out", path])
                with open(path, encoding="utf-8") as f:
                    outs.append(json.load(f))
            self.assertEqual(outs[0]["rows"], ["today", "01|23", "02|13"])
            self.assertTrue(all(o == outs[0] for o in outs))

    def test_a_dirty_short_or_unplayed_arm_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self.run_dir(tmp, "a", {"drawn": [1, 1]})
            dirty = self.run_dir(tmp, "b", {"drawn": [1, 1]}, our_arm="23|04", arm_dirty=True)
            with self.assertRaisesRegex(SystemExit, "arm drawn names dirty True, not False"):
                oracle.build_matrix([a, dirty])
            short = self.run_dir(tmp, "c", {"drawn": [1, 1]}, our_arm="23|04")
            with open(os.path.join(short, "arms", "drawn.json"), encoding="utf-8") as f:
                entry = json.load(f)
            with open(os.path.join(short, "arms", "drawn.json"), "w", encoding="utf-8") as f:
                json.dump(dict(entry, scores=[1]), f)
            with self.assertRaisesRegex(SystemExit, "arm drawn holds 1 scores, not 2"):
                oracle.build_matrix([a, short])
            other = self.run_dir(tmp, "d", {"drawn": [1, 1]}, our_arm="23|04", played={"drawn": "12|35"})
            with self.assertRaisesRegex(SystemExit, r"arms \['drawn'\]: our preview did not play --our-arm 23\|04"):
                oracle.build_matrix([a, other])
            varied = self.run_dir(tmp, "e", {"drawn": [1, 1], "15|23": [0, 0]}, our_arm="23|04",
                                  played={"15|23": "12|35"})
            with self.assertRaisesRegex(SystemExit, "our previews differ: the arms are not paired"):
                oracle.build_matrix([varied])

    def test_a_previous_matrix_of_another_measurement_or_other_cells_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self.run_dir(tmp, "a", {"drawn": [1, 1], "15|23": [0, 0]})
            first = os.path.join(tmp, "m1.json")
            with mock.patch("sys.stdout"):
                oracle.main(["matrix", a, "--out", first])
            other = self.run_dir(tmp, "b", {"drawn": [1, 1], "15|23": [0, 0]}, seed="0x465")
            with self.assertRaisesRegex(SystemExit, r"--previous is of another measurement \(it differs in \['seed'\]"), \
                    mock.patch("sys.stdout"):
                oracle.main(["matrix", other, "--out", os.path.join(tmp, "m2.json"), "--previous", first])
            with open(os.path.join(a, "arms", "15-23.json"), encoding="utf-8") as f:
                entry = json.load(f)
            with open(os.path.join(a, "arms", "15-23.json"), "w", encoding="utf-8") as f:
                json.dump(dict(entry, scores=[1, 0]), f)
            with self.assertRaisesRegex(SystemExit, r"cell \(today, 15\|23\) is 0 there, 1/2 here"), \
                    mock.patch("sys.stdout"):
                oracle.main(["matrix", a, "--out", os.path.join(tmp, "m3.json"), "--previous", first])

    def test_runs_of_other_measurements_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self.run_dir(tmp, "a", {"drawn": [1, 1]})
            cases = {"seed": dict(seed="0x465"), "library": dict(library="0.46.0"), "dirty": dict(dirty=True)}
            for i, (key, extra) in enumerate(cases.items()):
                b = self.run_dir(tmp, f"b{i}", {"drawn": [1, 1]}, our_arm="23|04", **extra)
                with self.assertRaisesRegex(SystemExit, rf"not one measurement \(they differ in \['{key}'\]\)"):
                    oracle.build_matrix([a, b])

    def test_unpaired_or_mismatched_rows_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self.run_dir(tmp, "a", {"drawn": [1, 1], "15|23": [0, 0]})
            other = self.run_dir(tmp, "b", {"drawn": [1, 1]}, our_arm="23|04")
            with self.assertRaisesRegex(SystemExit, "played other foe arms"):
                oracle.build_matrix([a, other])
            drawn = self.run_dir(tmp, "c", {"drawn": [1, 1], "15|23": [0, 0]}, our_arm="23|04",
                                 foe_drawn={"drawn": [5, 6]})
            with self.assertRaisesRegex(SystemExit, "arm drawn's foe previews differ: not paired"):
                oracle.build_matrix([a, drawn])
            commit = self.run_dir(tmp, "d", {"drawn": [1, 1], "15|23": [0, 0]}, our_arm="23|04", commit="beef")
            with self.assertRaisesRegex(SystemExit, "names commit beef"):
                oracle.build_matrix([a, commit])
            with self.assertRaisesRegex(SystemExit, "rows repeat"):
                oracle.build_matrix([a, a])

    def test_ours_side_and_mixed_runs_are_no_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            ours = self.run_dir(tmp, "a", {"drawn": [1, 1]}, side="ours")
            with self.assertRaisesRegex(SystemExit, "a matrix row is a foe-side run"):
                oracle.build_matrix([ours])
            mixed = self.run_dir(tmp, "b", {"drawn": [1, 1]}, our_mix="23|04:1/2,today:1/2")
            with self.assertRaisesRegex(SystemExit, "not the mix"):
                oracle.build_matrix([mixed])

    def test_a_previous_mix_must_fit_the_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self.run_dir(tmp, "a", {"drawn": [1, 1]})
            prev = os.path.join(tmp, "prev.json")
            first = os.path.join(tmp, "m1.json")
            with mock.patch("sys.stdout"):
                oracle.main(["matrix", a, "--out", first])
            with open(first, encoding="utf-8") as f:
                old = json.load(f)
            with open(prev, "w", encoding="utf-8") as f:
                json.dump(dict(old, our_mix={"23|04": "1"}, foe_mix={"drawn": "1"}), f)
            with self.assertRaisesRegex(SystemExit, r"our mix holds \['23\|04'\], which this matrix lacks"), \
                    mock.patch("sys.stdout"):
                oracle.main(["matrix", a, "--out", os.path.join(tmp, "m.json"), "--previous", prev])

    def test_the_matrix_file_stays_outside_the_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self.run_dir(tmp, "a", {"drawn": [1, 1]})
            out = os.path.join(str(ROOT), "preview-oracle-matrix-guard-test.json")
            with self.assertRaisesRegex(SystemExit, "inside the repository"):
                oracle.main(["matrix", a, "--out", out])
            self.assertFalse(os.path.exists(out))


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

    def test_the_foe_side_takes_no_foe_lead_and_no_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            self.assertRefused("--foe-lead", self.argv(out, ("--side", "foe", "--foe-lead", "A,B")), out)
            self.assertRefused("foe side", self.argv(out, ("--side", "foe", "--arms", "today")), out)

    def test_our_arm_is_the_foe_sides_and_a_combination(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            self.assertRefused("--our-arm fixes our preview on the foe side", self.argv(out, ("--our-arm", "23|04")),
                               out)
            self.assertRefused("--our-arm: .*ascending", self.argv(out, ("--side", "foe", "--our-arm", "32|04")), out)
            for name in ("today", "drawn"):
                self.assertRefused(rf"--our-arm takes a combination LEADS\|BENCH like '23\|04', not '{name}'",
                                   self.argv(out, ("--side", "foe", "--our-arm", name)), out)

    def test_our_mix_is_the_foe_sides_and_a_valid_mix(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            self.assertRefused("--our-mix mixes our preview on the foe side",
                               self.argv(out, ("--our-mix", "23|04:1")), out)
            self.assertRefused("--our-mix and --our-arm both",
                               self.argv(out, ("--side", "foe", "--our-mix", "23|04:1", "--our-arm", "23|04")), out)
            self.assertRefused("--our-mix: .*sum to 1/2",
                               self.argv(out, ("--side", "foe", "--our-mix", "23|04:1/2")), out)
            self.assertRefused("--our-mix: 'drawn' is no arm",
                               self.argv(out, ("--side", "foe", "--our-mix", "drawn:1")), out)

    def test_foe_mix_is_the_ours_sides_and_a_valid_mix(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            self.assertRefused("--foe-mix mixes the foe's preview on the ours side",
                               self.argv(out, ("--side", "foe", "--foe-mix", "drawn:1")), out)
            self.assertRefused("--foe-mix and --foe-lead both",
                               self.argv(out, ("--foe-mix", "drawn:1", "--foe-lead", "A,B")), out)
            self.assertRefused("--foe-mix: 'today' is no arm", self.argv(out, ("--foe-mix", "today:1")), out)

    def test_pairs_must_be_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            self.assertRefused("positive", self.argv(out, ("--pairs", "0")), out)


if __name__ == "__main__":
    unittest.main()
