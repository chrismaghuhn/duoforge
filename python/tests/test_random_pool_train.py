"""duoforge.python.random_pool_train: train with a random-team corpus in its pool (infrastructure; a run of one update,
a smoke, no training).

--random-teams-root and --random-team-share go together; the run's pool is the registry's teams and the corpus's
(teams.combine), its config records the corpus's provenance, its log names it, a resume keeps it and refuses another
corpus, and a run without them saves the options it saved before.
"""
import json
import os
import tempfile
import unittest

from python.tests.test_ledger import _SMALL, _train
from python.tests.test_random_pool import _registry_ids, make_corpus

REGISTRY = os.path.join(os.path.dirname(__file__), "..", "..", "data", "teams")


class RandomPoolTrainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "rt")
        self.rt = make_corpus(self.root)
        self.out = os.path.join(self.tmp.name, "run")
        self.base = ["--data-kind", "pool", "--teams", ",".join(_registry_ids(2)), "--teams-root", REGISTRY,
                     "--minutes", "0"] + _SMALL

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_run_plays_and_records_the_corpus(self):
        from duoforge import teams
        from duoforge_learn import runstate
        argv = ["--out", self.out, "--updates", "1", "--random-teams-root", self.root, "--random-team-share", "0.5"]
        self.assertEqual(_train(argv + self.base), 0)
        state = runstate.load_state(self.out)
        self.assertEqual(state["teams"]["ids"], _registry_ids(2) + self.rt)
        self.assertEqual(state["train"]["random_teams"], teams.corpus_provenance(self.root))
        self.assertEqual(state["train"]["random_team_share"], 0.5)
        with open(os.path.join(self.out, "log.jsonl"), encoding="utf-8") as f:
            lines = [json.loads(line) for line in f]
        named = [r for r in lines if "random_teams" in r]
        self.assertEqual(named[0]["random_teams"]["count"], 3)
        self.assertEqual(named[0]["teams"], 5)
        # A resume keeps the corpus; another corpus (a changed index) is refused.
        self.assertEqual(_train(["--resume", self.out, "--updates", "2"]), 0)
        with open(os.path.join(self.root, "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        manifest["seed"] = "0x0"
        with open(os.path.join(self.root, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        with self.assertRaisesRegex(SystemExit, "not the run's corpus"):
            _train(["--resume", self.out, "--updates", "3"])

    def test_a_resume_may_change_the_share_and_the_log_records_it(self):
        from duoforge_learn import runstate
        argv = ["--out", self.out, "--updates", "1", "--random-teams-root", self.root, "--random-team-share", "0.5"]
        self.assertEqual(_train(argv + self.base), 0)
        self.assertEqual(_train(["--resume", self.out, "--updates", "2", "--random-team-share", "0.25"]), 0)
        state = runstate.load_state(self.out)
        self.assertEqual(state["train"]["random_team_share"], 0.25)
        weights = state["teams"]["weights"]
        self.assertAlmostEqual(sum(weights[2:]) / sum(weights), 0.25)  # the corpus's share of each side's draw
        with open(os.path.join(self.out, "log.jsonl"), encoding="utf-8") as f:
            resumes = [r for r in (json.loads(line) for line in f) if "resume" in r]
        self.assertEqual(resumes[-1]["resume"]["random_team_share"], [0.5, 0.25])
        self.assertIn("teams", resumes[-1]["resume"])  # the pool's weights changed with it
        self.assertEqual(resumes[-1]["random_teams"]["count"], 3)

    def test_the_options_go_together_and_a_bad_corpus_stops(self):
        with self.assertRaisesRegex(SystemExit, "go together"):
            _train(["--out", self.out, "--updates", "1", "--random-teams-root", self.root] + self.base)
        with self.assertRaisesRegex(SystemExit, "share"):
            _train(["--out", self.out, "--updates", "1", "--random-teams-root", self.root, "--random-team-share",
                    "1.5"] + self.base)
        os.remove(os.path.join(self.root, "manifest.json"))
        with self.assertRaises(SystemExit):
            _train(["--out", self.out, "--updates", "1", "--random-teams-root", self.root, "--random-team-share",
                    "0.5"] + self.base)

    def test_a_run_without_a_corpus_saves_no_such_option(self):
        from duoforge_learn import runstate
        self.assertEqual(_train(["--out", self.out, "--updates", "1"] + self.base), 0)
        train = runstate.load_state(self.out)["train"]
        self.assertFalse({"random_teams", "random_teams_root", "random_team_share"} & set(train))


if __name__ == "__main__":
    unittest.main()
