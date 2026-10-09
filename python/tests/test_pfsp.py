"""duoforge.python.pfsp: prioritized fictitious self-play for the league's
refills (league.Refill, train.py --league-pfsp-share and friends).

The weights (win rate with its prior, f, the minimum weight), the mixture of
uniform, PFSP and anchor refills over many keyed draws, determinism, the
persisted statistics across a resume, and the default: without the new
options the draws, the log's league loads, the run state and the snapshot
configs are those of the code before PFSP. The training runs need JAX, so
this module is in the learn list.
"""
import json
import math
import os
import shutil
import tempfile
import unittest

import numpy as np

from duoforge_learn import league, pairing

SEED = 0x2026100200000021  # train.py's default --seed

# The scheme before PFSP (train.py _Pool.draw until this change), kept verbatim as the reference of the default.
def _old_draw(seed, update, updates):
    u = pairing.draw(seed, pairing.LEAGUE_SNAPSHOT, np.array([update]), np.array([0]))
    return updates[int(pairing.pick(u, np.ones(len(updates)))[0])]


# A tolerance declared before the draws: 5 binomial standard deviations (two-sided, p < 1e-6 per check).
def _within(test, count, n, share, label):
    sigma = math.sqrt(n * share * (1 - share))
    test.assertLessEqual(abs(count - n * share), 5 * sigma + 1e-9,
                         f"{label}: {count} of {n}, expected share {share}")


class RefillWeightsTest(unittest.TestCase):
    def test_win_rate_counts_draws_as_half_and_adds_the_prior(self):
        refill = league.Refill(pfsp_share=1.0, prior=0.5, prior_games=4.0)
        stats = {"0": [10, 7, 2], "3": [2, 0, 0]}
        p = refill.win_rates([0, 3, 7], stats)
        np.testing.assert_allclose(p, [(7 + 1 + 2) / 14, (0 + 2) / 6, 0.5])

    def test_f_values_and_minimum_weight(self):
        p = np.array([0.0, 0.25, 0.5, 0.9, 1.0])
        hard = league.Refill(pfsp_share=1.0, weighting="hard", min_weight=0.05).weights_of(p)
        np.testing.assert_allclose(hard, [1.0, 0.5625, 0.25, 0.05, 0.05])
        linear = league.Refill(pfsp_share=1.0, weighting="linear", min_weight=0.05).weights_of(p)
        np.testing.assert_allclose(linear, [1.0, 0.75, 0.5, 0.1, 0.05])
        variance = league.Refill(pfsp_share=1.0, weighting="variance", min_weight=0.01).weights_of(p)
        np.testing.assert_allclose(variance, [0.01, 0.1875, 0.25, 0.09, 0.01])

    def test_defaults_are_documented_values(self):
        r = league.Refill()
        self.assertEqual((r.pfsp_share, r.anchor_share, r.anchors, r.weighting, r.min_weight, r.prior,
                          r.prior_games), (0.0, 0.0, 1, "hard", 0.05, 0.5, 4.0))
        self.assertFalse(r.enabled)
        self.assertTrue(league.Refill(pfsp_share=0.5).enabled)
        self.assertTrue(league.Refill(anchor_share=0.1).enabled)

    def test_invalid_settings_are_refused(self):
        for kw, word in (({"pfsp_share": 0.8, "anchor_share": 0.4}, "share"), ({"pfsp_share": -0.1}, "share"),
                         ({"anchor_share": 1.5}, "share"), ({"min_weight": 0.0}, "min_weight"),
                         ({"min_weight": 1.5}, "min_weight"), ({"prior": 1.2}, "prior"),
                         ({"prior_games": 0.0}, "prior_games"), ({"anchors": 0}, "anchors"),
                         ({"weighting": "easy"}, "weighting")):
            with self.subTest(kw=kw), self.assertRaisesRegex(ValueError, word):
                league.Refill(**kw)

    def test_default_draws_are_the_old_uniform_draws(self):
        refill = league.Refill()
        for seed in (SEED, 0, 12345):
            for n in (1, 2, 5, 17):
                updates = list(range(0, 50 * n, 50))
                for update in range(1, 400, 7):
                    chosen, source = refill.draw(seed, update, updates, {"0": [5, 5, 0]})
                    self.assertEqual(chosen, _old_draw(seed, update, updates))
                    self.assertEqual(source, "uniform")

    def test_mixture_proportions_over_keyed_draws(self):
        refill = league.Refill(pfsp_share=0.5, anchor_share=0.15)
        updates = list(range(0, 1000, 100))
        n = 20000
        sources = [refill.draw(SEED, u, updates, {})[1] for u in range(1, n + 1)]
        for name, share in (("uniform", 0.35), ("pfsp", 0.5), ("anchor", 0.15)):
            _within(self, sources.count(name), n, share, name)

    def test_uniform_refills_of_a_mixture_keep_the_old_pick(self):
        refill = league.Refill(pfsp_share=0.5, anchor_share=0.15)
        updates = list(range(0, 1000, 100))
        for u in range(1, 2000):
            chosen, source = refill.draw(SEED, u, updates, {})
            if source == "uniform":
                self.assertEqual(chosen, _old_draw(SEED, u, updates))

    def test_pfsp_draws_follow_the_weights(self):
        refill = league.Refill(pfsp_share=1.0)
        updates = [0, 10, 20, 30, 40]
        # p = 0.09, 0.5 (unseen: the prior), 0.7, 0.95, 0.28 with the prior of 4 games at 0.5.
        stats = {"0": [96, 7, 0], "20": [96, 68, 0], "30": [996, 948, 0], "40": [96, 26, 0]}
        p = refill.win_rates(updates, stats)
        np.testing.assert_allclose(p, [0.09, 0.5, 0.7, 0.95, 0.28], atol=1e-12)
        w = refill.weights_of(p)
        expected = w / w.sum()
        n = 20000
        drawn = [refill.draw(SEED, u, updates, stats) for u in range(1, n + 1)]
        self.assertEqual({s for _, s in drawn}, {"pfsp"})
        chosen = [c for c, _ in drawn]
        for update, share in zip(updates, expected):
            _within(self, chosen.count(update), n, share, f"snapshot {update}")
        # The beaten snapshot 30 (p = 0.95) is kept alive by the minimum weight, never starved.
        self.assertGreater(chosen.count(30), 0)

    def test_anchors_are_the_earliest_snapshots(self):
        refill = league.Refill(anchor_share=1.0, anchors=2)
        updates = [0, 200, 400, 600, 800]
        n = 4000
        chosen = [refill.draw(SEED, u, updates, {})[0] for u in range(1, n + 1)]
        self.assertEqual(set(chosen), {0, 200})
        _within(self, chosen.count(0), n, 0.5, "anchor 0")
        # Fewer snapshots than anchors: all of them are anchors.
        self.assertEqual(refill.draw(SEED, 5, [0], {})[0], 0)

    def test_draws_are_a_pure_function_of_seed_update_pool_and_stats(self):
        refill = league.Refill(pfsp_share=0.5, anchor_share=0.15)
        updates = list(range(0, 1000, 100))
        stats = {"0": [40, 30, 2], "500": [40, 5, 1]}
        first = [refill.draw(SEED, u, updates, stats) for u in range(1, 300)]
        again = [refill.draw(SEED, u, list(updates), json.loads(json.dumps(stats))) for u in range(1, 300)]
        self.assertEqual(first, again)
        other = [refill.draw(SEED + 1, u, updates, stats) for u in range(1, 300)]
        self.assertNotEqual(first, other)

    def test_stats_persist_through_the_league_state(self):
        st = league.LeagueState(8, 0.5, 2, 1, SEED)
        st.load(0, "0")
        st.load(1, "0")
        st.start(np.arange(8), np.zeros(8))
        st.end(np.arange(4, 8), np.array([1, -1, 0, 1]))
        back = league.LeagueState.from_dict(json.loads(json.dumps(st.to_dict())))
        self.assertEqual(back.stats, st.stats)
        refill = league.Refill(pfsp_share=1.0)
        updates = [0, 1, 2]
        self.assertEqual([refill.draw(SEED, u, updates, st.stats) for u in range(1, 50)],
                         [refill.draw(SEED, u, updates, back.stats) for u in range(1, 50)])


_SMALL = ["--envs", "8", "--workers", "2", "--rollout", "8", "--minutes", "0", "--eval-every", "100",
          "--minibatch", "256", "--snapshot-every", "1", "--slot-refresh", "1", "--league-slots", "2"]
_PFSP = ["--league-pfsp-share", "0.5", "--league-anchor-share", "0.2", "--pfsp-min-weight", "0.1"]
# The run configuration's keys before PFSP: a run without the new options saves exactly these.
_OLD_TRAIN_KEYS = {"envs", "workers", "rollout", "minutes", "updates", "epochs", "minibatch", "learning_rate",
                   "learning_rate_schedule", "kl_ref", "kl_refresh", "kl_coef", "entropy", "eval_every",
                   "eval_games", "eval_budget", "seed", "max_steps", "out", "model", "preset", "embed", "member",
                   "position", "hidden", "layers", "option", "self_play_share", "opponent_precision",
                   "league_slots", "snapshot_every", "slot_refresh", "save_minutes", "teams", "team_weights",
                   "teams_root", "data_kind", "init", "ext_supported"}
_OLD_LEAGUE_KEYS = {"self_play", "learner_seat", "slot_of", "slots", "refresh", "seed", "snapshots", "draining",
                    "next_drain", "active", "stats"}


def _run(argv):
    from duoforge_learn import train
    return train.run(train.parse(argv))


def _records(out):
    with open(os.path.join(out, "log.jsonl"), encoding="utf-8") as f:
        return [json.loads(line) for line in f]


class TrainPfspTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="duoforge-pfsp-")
        self.out = os.path.join(self.root, "run")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_default_run_is_unchanged(self):
        from duoforge_learn import checkpoint, runstate
        self.assertEqual(_run(_SMALL + ["--updates", "8", "--out", self.out]), 0)
        loads = [(r["update"], r["league_load"]) for r in _records(self.out) if "league_load" in r]
        self.assertGreater(len(loads), 0)
        for update, load in loads:
            # --snapshot-every 1: the pool at update u holds params-0 .. params-u.
            self.assertEqual(load, {"slot": load["slot"], "snapshot": _old_draw(SEED, update, list(range(update + 1)))})
        saved = runstate.load_state(self.out)
        self.assertEqual(set(saved["train"]), _OLD_TRAIN_KEYS)
        self.assertEqual(set(saved["league"]), _OLD_LEAGUE_KEYS)
        config = checkpoint.load(os.path.join(self.out, "params-8.npz"))[1]
        self.assertEqual(set(config["train"]), _OLD_TRAIN_KEYS)

    def test_pfsp_run_resumes_identically_and_keeps_its_stats(self):
        from duoforge_learn import runstate
        self.assertEqual(_run(_SMALL + _PFSP + ["--updates", "4", "--out", self.out]), 0)
        saved = runstate.load_state(self.out)
        self.assertEqual((saved["train"]["league_pfsp_share"], saved["train"]["league_anchor_share"],
                          saved["train"]["pfsp_min_weight"]), (0.5, 0.2, 0.1))
        self.assertNotIn("pfsp_prior", saved["train"])  # a new option at its default is not saved
        before = saved["league"]["stats"]
        copies = [os.path.join(self.root, name) for name in ("a", "b")]
        for c in copies:
            shutil.copytree(self.out, c)
            self.assertEqual(_run(["--resume", c, "--updates", "10"]), 0)
        tails = []
        for c in copies:
            records = _records(c)
            at = next(i for i, r in enumerate(records) if "resume" in r)
            # Only --updates changes: the PFSP options come back from the run state.
            self.assertEqual(records[at]["resume"], {"updates": [4, 10]})
            tails.append([(r["update"], r["league_load"]) for r in records[at + 1:] if "league_load" in r])
        self.assertGreater(len(tails[0]), 0)
        self.assertEqual(tails[0], tails[1])
        for _, load in tails[0]:
            self.assertIn(load["source"], ("uniform", "pfsp", "anchor"))
            self.assertTrue(0.0 <= load["win_rate"] <= 1.0)
        after = [runstate.load_state(c)["league"]["stats"] for c in copies]
        self.assertEqual(after[0], after[1])
        for label, (games, wins, draws) in before.items():  # the resumed run counts on from the saved stats
            self.assertGreaterEqual(after[0][label][0], games)
            self.assertGreaterEqual(after[0][label][1], wins)
            self.assertGreaterEqual(after[0][label][2], draws)

    def test_resume_may_change_the_mixture_and_logs_it(self):
        self.assertEqual(_run(_SMALL + ["--updates", "1", "--out", self.out]), 0)
        self.assertEqual(_run(["--resume", self.out, "--updates", "2", "--league-pfsp-share", "0.5"]), 0)
        resume = [r for r in _records(self.out) if "resume" in r][-1]["resume"]
        self.assertEqual(resume["league_pfsp_share"], [None, 0.5])

    def test_invalid_mixture_is_refused(self):
        with self.assertRaisesRegex(SystemExit, "share"):
            _run(_SMALL + ["--updates", "1", "--league-pfsp-share", "0.8", "--league-anchor-share", "0.4",
                           "--out", self.out])
        self.assertFalse(os.path.exists(self.out))


if __name__ == "__main__":
    unittest.main()
