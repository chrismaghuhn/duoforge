"""duoforge.tools.coverage: the replay coverage tools (tools/coverage, restructure step 8), offline and without data.

The measurement itself needs the library and private replays (docs/research/expansion/champions-100.md, sections 1 and
10); these tests cover what runs without them: the greedy order, the packed-sheet reader, the batch view, where a run
may write, and the forwarders at the tools' old paths (tools/research/).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent
ROOT = TOOL.parent.parent
sys.path.insert(0, str(TOOL))

import champions_coverage  # noqa: E402


def run(script, *args, env=None):
    environ = {k: v for k, v in os.environ.items() if k != "DUOFORGE_RUNS"}
    environ.update(env or {})
    return subprocess.run([sys.executable, str(script), *args], cwd=ROOT, env=environ, capture_output=True, text=True,
                          timeout=300)


class GreedyTest(unittest.TestCase):
    def test_the_token_that_frees_the_most_games_first_ties_by_game_order(self):
        games = [set(), {"move:a"}, {"move:a", "item:b"}, {"item:b"}, {"item:b"}]
        order = champions_coverage.greedy(games, 10)
        self.assertEqual([(o["token"], o["gain"], o["playable"], o["in_games"]) for o in order],
                         [("item:b", 2, 3, 3), ("move:a", 2, 5, 2)])
        self.assertEqual(order[-1]["share"], 1.0)
        tie = champions_coverage.greedy([{"move:a"}, {"item:b"}], 10)
        self.assertEqual([o["token"] for o in tie], ["move:a", "item:b"])  # the token first met in game order
        self.assertEqual(len(champions_coverage.greedy(games, 1)), 1)


class PackedTest(unittest.TestCase):
    def test_a_packed_member(self):
        [member] = champions_coverage.parse_packed("Charizard||charizarditex|blaze|flamethrower,roost|Timid||M|||50|]")
        self.assertEqual(member, {"species": "Charizard", "item": "charizarditex", "ability": "blaze",
                                  "moves": ["flamethrower", "roost"], "nature": "Timid", "gender": "M"})


class BatchesTest(unittest.TestCase):
    def test_alone_and_cumulative(self):
        with tempfile.TemporaryDirectory() as tmp:
            games = Path(tmp, "games.jsonl")
            rows = [{"id": 1, "b": [[], []], "t": 10}, {"id": 2, "b": [["move:a"], []], "t": 20},
                    {"id": 3, "b": [["move:a"], ["mega:Gyarados@Gyaradosite"]], "t": 30}]
            games.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            batches = Path(tmp, "batches.json")
            batches.write_text(json.dumps([{"name": "one", "tokens": ["move:a"]},
                                           {"name": "two", "tokens": ["mega:gyarados@gyaradosite"]}]), encoding="utf-8")
            out = Path(tmp, "out.json")
            r = run(TOOL / "champions_batches.py", "--games", str(games), "--batches", str(batches), "--out", str(out))
            self.assertEqual(r.returncode, 0, r.stderr)
            report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual((report["games"], report["base_games"], report["base_sides"], report["turns"]), (3, 1, 3, 60))
        one, two = report["batches"]
        self.assertEqual((one["alone_games"], one["alone_sides"], one["cum_games"], one["cum_turns"]), (1, 2, 2, 30))
        self.assertEqual((two["alone_games"], two["cum_games"], two["cum_sides"], two["cum_turns"]), (0, 3, 6, 60))


class OutputTest(unittest.TestCase):
    def test_the_output_never_lies_in_the_repository(self):
        r = run(TOOL / "champions_coverage.py", "--sheets", "none.jsonl", "--out", str(ROOT / "coverage-out"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("must be outside the repository", r.stderr)
        self.assertFalse((ROOT / "coverage-out").exists())

    def test_the_default_output_needs_duoforge_runs(self):
        r = run(TOOL / "champions_coverage.py", "--sheets", "none.jsonl")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("DUOFORGE_RUNS", r.stderr)
        r = run(TOOL / "champions_coverage.py", "--sheets", "none.jsonl", env={"DUOFORGE_RUNS": str(ROOT / "runs-x")})
        self.assertNotEqual(r.returncode, 0)  # a default inside the repository is refused like an explicit --out
        self.assertIn("must be outside the repository", r.stderr)
        self.assertFalse((ROOT / "runs-x").exists())
        with tempfile.TemporaryDirectory() as tmp:  # a default that already holds a run is not reused
            import datetime
            taken = Path(tmp, "coverage", f"{datetime.date.today().isoformat()}-champions_coverage")
            taken.mkdir(parents=True)
            (taken / "aggregate.json").write_text("{}", encoding="utf-8")
            r = run(TOOL / "champions_coverage.py", "--sheets", "none.jsonl", env={"DUOFORGE_RUNS": tmp})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already holds a run", r.stderr)


class ForwarderTest(unittest.TestCase):
    def test_the_old_paths_run_the_moved_tools(self):
        for name in ("champions_coverage", "champions_batches"):
            with self.subTest(tool=name):
                r = run(ROOT / "tools" / "research" / f"{name}.py", "--help")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(f"tools/research/{name}.py moved to tools/coverage/{name}.py", r.stderr)
                self.assertIn("usage:", r.stdout)


if __name__ == "__main__":
    unittest.main()
