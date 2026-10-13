"""The network diagnosis (#451): the rankings, the statistics, the client-log replay's batching and the preview table,
as pure functions over NumPy arrays and records. No network, no checkpoint and no private data."""
import unittest

import numpy as np

from duoforge import _layout
from duoforge_live.data import ROOT
from duoforge_search import network_diagnosis as nd

C = _layout.CONSTANTS


def domain(kinds0, kinds1=(C["DUOFORGE_SLOT_NONE"],), team=False):
    d = np.zeros((), _layout.FACTORED_DOMAIN)
    if team:
        d["kind"] = C["DUOFORGE_CHOICE_TEAM_SELECTION"]
        return d
    d["kind"] = C["DUOFORGE_CHOICE_SLOTS"]
    for s, kinds in enumerate((kinds0, kinds1)):
        d["slot_count"][s] = len(kinds)
        for i, k in enumerate(kinds):
            d["slots"][s][i]["kind"] = k
    return d


class Ranks(unittest.TestCase):
    def test_rank_counts_allowed_entries_above_and_ties_below(self):
        logp = np.array([[0.0, 1.0, 1.0, 2.0, 5.0]])
        allowed = np.array([[True, True, True, True, False]])  # 4 is masked: never ahead of the target
        self.assertEqual(nd.ranks(logp, allowed, [3]).tolist(), [0])
        self.assertEqual(nd.ranks(logp, allowed, [1]).tolist(), [1])
        self.assertEqual(nd.ranks(logp, allowed, [2]).tolist(), [2])  # the tie goes to the lower index
        self.assertEqual(nd.ranks(logp, allowed, [0]).tolist(), [3])

    def test_rank_matches_the_live_policys_stable_order(self):
        rng = np.random.default_rng(1)
        logp = np.round(rng.normal(size=(20, 30)), 1)  # rounded: many ties
        allowed = rng.random((20, 30)) < 0.6
        allowed[:, 0] = True
        for b in range(20):
            index = np.flatnonzero(allowed[b])
            order = index[np.argsort(-logp[b][index], kind="stable")]
            for position, target in enumerate(order):
                self.assertEqual(int(nd.ranks(logp[b:b + 1], allowed[b:b + 1], [target])[0]), position)

    def test_a_label_set_counts_from_its_best_entry(self):
        logp = np.array([[3.0, 1.0, 2.0, 2.0]])
        label = np.array([[False, True, False, True]])
        best = nd.best_of_set(logp, label)
        self.assertEqual(best.tolist(), [3])
        self.assertEqual(nd.ranks(logp, np.ones_like(label), best).tolist(), [2])  # after 0 and the tie 2

    def test_team_bits_read_the_label_bytes_little_endian(self):
        label = np.zeros((1, 45), np.uint8)
        label[0, 0], label[0, 44] = 0b101, 0b10000000  # tuples 0, 2 and 359
        self.assertEqual(np.flatnonzero(nd.team_bits(label, 360)[0]).tolist(), [0, 2, 359])


class DecisionKind(unittest.TestCase):
    def test_kinds(self):
        move, switch, none = C["DUOFORGE_SLOT_MOVE"], C["DUOFORGE_SLOT_SWITCH"], C["DUOFORGE_SLOT_NONE"]
        self.assertEqual(nd.decision_kind(domain((), team=True)), "team")
        self.assertEqual(nd.decision_kind(domain((move, switch), (move,))), "turn")
        self.assertEqual(nd.decision_kind(domain((switch, switch), (none,))), "forced")
        self.assertEqual(nd.decision_kind(domain((none,), (switch, switch))), "forced")


class Statistics(unittest.TestCase):
    def test_auc_against_counting_pairs(self):
        rng = np.random.default_rng(2)
        score = np.round(rng.normal(size=200), 1)
        positive = rng.random(200) < 0.4
        weight = rng.integers(0, 3, 200).astype(float)
        want = num = 0.0
        for i in np.flatnonzero(positive):
            for j in np.flatnonzero(~positive):
                w = weight[i] * weight[j]
                want += w * (1.0 if score[i] > score[j] else 0.5 if score[i] == score[j] else 0.0)
                num += w
        self.assertAlmostEqual(nd.auc(score, positive, weight), want / num, places=12)
        self.assertEqual(nd.auc([0.1, 0.9], [False, True]), 1.0)
        self.assertEqual(nd.auc([0.5, 0.5], [False, True]), 0.5)

    def test_ratio_interval_is_seeded_and_holds_the_point(self):
        rng = np.random.default_rng(3)
        group = np.repeat(np.arange(40), 5)
        hits = (rng.random(200) < 0.3).astype(float)
        a = nd.ratio(hits, np.ones(200), group, 40, b=200)
        b = nd.ratio(hits, np.ones(200), group, 40, b=200)
        self.assertEqual(a, b)
        self.assertAlmostEqual(a["value"], hits.mean())
        self.assertLessEqual(a["ci"][0], a["value"])
        self.assertGreaterEqual(a["ci"][1], a["value"])
        self.assertEqual(a["n"], 200)

    def test_a_constant_group_effect_widens_the_interval(self):
        # the same hit rate, once independent rows and once whole games alike: the games' interval is wider
        group = np.repeat(np.arange(20), 10)
        alike = np.repeat(np.arange(20) % 2, 10).astype(float)
        mixed = np.tile(np.arange(10) % 2, 20).astype(float)
        wide = nd.ratio(alike, np.ones(200), group, 20, b=300)["ci"]
        narrow = nd.ratio(mixed, np.ones(200), group, 20, b=300)["ci"]
        self.assertGreater(wide[1] - wide[0], narrow[1] - narrow[0])

    def test_value_metrics_of_a_perfect_and_a_blind_value(self):
        z = np.array([1, -1] * 50)
        group = np.arange(100)
        perfect = nd.value_metrics(z.astype(float), z, group, 100, b=50)
        self.assertEqual(perfect["auc"]["value"], 1.0)
        self.assertEqual(perfect["brier"]["value"], 0.0)
        self.assertAlmostEqual(perfect["log_loss"]["value"], -np.log(1 - nd.P_CLIP))
        blind = nd.value_metrics(np.zeros(100), z, group, 100, b=50)
        self.assertEqual(blind["auc"]["value"], 0.5)
        self.assertAlmostEqual(blind["brier"]["value"], 0.25)
        self.assertAlmostEqual(blind["ece"], 0.0)

    def test_rating_buckets(self):
        k = np.searchsorted(nd.RATINGS, [0, 1, 1199, 1200, 1599, 1600, 2100], side="right")
        self.assertEqual([nd.rating_name(int(x)) for x in k],
                         ["unrated", "<1200", "<1200", "1200-1399", "1400-1599", ">=1600", ">=1600"])

    def test_probability_clips_the_value(self):
        self.assertEqual(nd.probability([-3.0, -1.0, 0.0, 0.5, 2.0]).tolist(), [0.0, 0.0, 0.5, 0.75, 1.0])


class PreviewTable(unittest.TestCase):
    def test_spread_over_distinct_candidates_and_worlds(self):
        # 2 worlds, 3 own candidates (the last two alike), 2 foe teams
        cell = np.array([[0.2, 0.0], [0.6, 0.4], [0.6, 0.4]])
        record = {"tables": [cell, cell], "weights": [0.5, 0.5], "foe_probs": [[0.3, 0.1], [0.3, 0.1]],
                  "changed": True}
        t = nd.preview_table(record)
        self.assertAlmostEqual(t["spread"], (0.75 * 0.6 + 0.25 * 0.4) - (0.75 * 0.2))
        self.assertEqual(t["distinct"], 2)
        self.assertEqual(t["candidates"], 3)
        self.assertEqual(t["world_sd"], 0.0)
        record["tables"] = [cell, cell + 0.2]
        self.assertAlmostEqual(nd.preview_table(record)["world_sd"], 0.1)


class BattleSteps(unittest.TestCase):
    def test_lines_since_a_decision_are_one_batch_and_the_choice_is_accepted_before_the_next_battle_line(self):
        records = [{"in": "|init|battle"}, {"in": "|request|{}"}, {"decision": 1, "top": [], "sent": "team 1234"},
                   {"in": "|j|☆someone"}, {"in": "|start"}, {"in": "|switch|p1a: X|X|100/100"},
                   {"in": "|error|[Unavailable choice] x"}, {"unavailable": "move 1", "error": "x"},
                   {"in": "|request|{}"}, {"decision": 2, "top": [], "sent": "move 1"},
                   {"in": "|win|someone"}, {"end": "|win|someone"}]
        steps = list(nd.battle_steps(records))
        self.assertEqual([s for s, _ in steps], ["feed", "decision", "feed", "accept", "feed", "decision", "end"])
        self.assertEqual(steps[2][1], ["|j|☆someone"])  # a room line does not accept the choice
        self.assertEqual(steps[3][1], "team 1234")
        self.assertEqual(steps[4][1], ["|start", "|switch|p1a: X|X|100/100", "|request|{}"])  # no error line
        self.assertEqual(steps[6][1], "|win|someone")

    def test_the_result_line_ends_the_battle_unfed_as_in_the_live_client(self):
        for end in ("|win|Some-One", "|tie", "|tie|"):
            records = [{"in": "|request|{}"}, {"decision": 1, "top": [], "sent": "move 1"},
                       {"in": "|move|p1a: X|Tackle|p2a: Y"}, {"in": end}, {"in": "|deinit"}, {"end": end}]
            steps = list(nd.battle_steps(records))
            # the |move| line accepts the choice (as when it comes in a message of its own), but is not fed
            self.assertEqual(steps, [("feed", ["|request|{}"]), ("decision", records[1]), ("accept", "move 1"),
                                     ("end", end)])
        self.assertFalse(nd.battle_end("|winner|x"))
        self.assertFalse(nd.battle_end("|tier|x"))

    def test_an_unavailable_choice_is_not_accepted(self):
        records = [{"in": "|request|{}"}, {"decision": 1, "top": [], "sent": "move 1"},
                   {"in": "|error|[Unavailable choice] x"}, {"unavailable": "move 1", "error": "x"},
                   {"in": "|request|{}"}, {"decision": 1, "top": [], "sent": "move 2"}]
        steps = list(nd.battle_steps(records))
        self.assertEqual([s for s, _ in steps], ["feed", "decision", "feed", "decision"])

    def test_a_rejected_choice_and_a_second_start_stop_the_replay(self):
        rejected = [{"decision": 1, "top": [], "sent": "move 1"}, {"rejected": "move 1", "error": "x"}]
        self.assertEqual(list(nd.battle_steps(rejected))[-1], ("stop", "rejected_choice"))
        twice = [{"in": "|start"}, {"in": "|turn|1"}, {"in": "|start"}]
        self.assertEqual(list(nd.battle_steps(twice))[-1], ("stop", "second_start"))


class Arguments(unittest.TestCase):
    def test_nets_are_named_once(self):
        self.assertEqual(nd.parse_nets(["bc6=a.npz", "p49333=b.npz"]), [("bc6", "a.npz"), ("p49333", "b.npz")])
        for bad in (["a.npz"], ["bc6=a", "bc6=b"], ["6x=a"]):
            with self.assertRaises(ValueError):
                nd.parse_nets(bad)

    def test_an_output_inside_the_repository_is_refused(self):
        for argv in (["outcomes", "--source", "x.jsonl", "--player", "p", "--out", str(ROOT / "diag")],
                     ["report", "--out", str(ROOT / "diag" / "report.json")]):
            with self.assertRaises(SystemExit):
                nd.main(argv)

    def test_fidelity_reads_a_searched_decision_after_its_choice(self):
        row = {"cause": "searched", "logged_top": [["b", 0.1], ["a", 0.5], ["c", 0.2]],
               "top3_n": [("a", 0.5), ("b", 0.1 + 1e-7), ("c", 0.2)]}
        self.assertTrue(nd.fidelity(row, "n"))
        row["cause"] = "team"
        self.assertFalse(nd.fidelity(row, "n"))
        row["logged_top"] = [["a", 0.5], ["b", 0.1], ["c", 0.2]]
        self.assertTrue(nd.fidelity(row, "n"))


if __name__ == "__main__":
    unittest.main()
