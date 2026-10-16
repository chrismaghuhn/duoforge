"""duoforge.python.runs: the run helper (duoforge.runs, restructure step 8): output directories, the code, the manifest.

Run outputs never land in a work tree of this repository (AGENTS.md); the default directory needs DUOFORGE_RUNS (no
silent fallback); the manifest names the commit, also for a worktree whose gitdir does not resolve (#411).
"""
import datetime
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from duoforge import runs

ROOT = Path(__file__).resolve().parents[3]
DAY = datetime.date(2026, 10, 16)


def git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True,
                          env=env).stdout.strip()


class RepoFixture(unittest.TestCase):
    """A throwaway repository with one commit and a worktree inside it (as .claude/worktrees/<name> here)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.main = Path(self.tmp.name, "main")
        self.main.mkdir()
        git(self.main, "init", "-q")
        (self.main / "a.txt").write_text("a\n", encoding="utf-8")
        git(self.main, "add", "a.txt")
        git(self.main, "commit", "-q", "-m", "a")
        self.head = git(self.main, "rev-parse", "HEAD")
        self.worktree = self.main / "wt" / "lane"
        git(self.main, "worktree", "add", "-q", "--detach", str(self.worktree))

    def tearDown(self):
        self.tmp.cleanup()


class OutputTest(RepoFixture):
    def test_the_default_is_under_duoforge_runs(self):
        out = runs.default_out("eval", "arena", environ={runs.RUNS_ENV: "/private/runs"}, today=DAY)
        self.assertEqual(out, Path("/private/runs") / "eval" / "2026-10-16-arena")

    def test_a_second_run_of_the_day_never_reuses_the_default(self):
        base = Path(self.tmp.name, "private-runs")
        environ = {runs.RUNS_ENV: str(base)}
        first = runs.default_out("eval", "arena", environ=environ, today=DAY)
        first.mkdir(parents=True)
        self.assertEqual(runs.default_out("eval", "arena", environ=environ, today=DAY), first)  # created, still empty
        (first / "summary.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "already holds a run"):
            runs.out_dir(None, "eval", "arena", environ=environ, today=DAY, root=self.main)
        self.assertEqual(runs.out_dir(str(first), "eval", "arena", root=self.main), first)  # an explicit --out decides

    def test_no_default_without_duoforge_runs(self):
        with self.assertRaisesRegex(SystemExit, "DUOFORGE_RUNS"):
            runs.default_out("eval", "arena", environ={}, today=DAY)
        with self.assertRaisesRegex(SystemExit, "DUOFORGE_RUNS"):
            runs.out_dir(None, "eval", "arena", environ={runs.RUNS_ENV: ""}, today=DAY)

    def test_unknown_kinds_and_names_are_refused(self):
        with self.assertRaises(ValueError):
            runs.default_out("night", "arena", environ={runs.RUNS_ENV: "/r"})
        for name in ("", "a/b", f"a{os.sep}b"):
            with self.assertRaises(ValueError):
                runs.default_out("eval", name, environ={runs.RUNS_ENV: "/r"})

    def test_an_output_outside_the_repository_is_taken(self):
        out = Path(self.tmp.name, "outside", "run")
        self.assertEqual(runs.out_dir(str(out), "eval", "arena", root=self.main), out)
        self.assertFalse(runs.inside_repository(out, root=self.main))

    def test_an_output_in_any_work_tree_of_the_repository_is_refused(self):
        for out in (self.main, self.main / "results", self.worktree / "deep" / "run"):
            with self.subTest(out=out), self.assertRaisesRegex(SystemExit, "inside the repository"):
                runs.out_dir(str(out), "eval", "arena", root=self.main)
        # the worktree's own root: the main checkout is the same repository
        with self.assertRaisesRegex(SystemExit, "inside the repository"):
            runs.refuse_repository(self.main / "x", root=self.worktree)
        # a default under DUOFORGE_RUNS inside the repository is refused too
        with self.assertRaisesRegex(SystemExit, "inside the repository"):
            runs.out_dir(None, "eval", "arena", environ={runs.RUNS_ENV: str(self.main / "runs")}, today=DAY,
                         root=self.main)

    def test_this_repository_refuses_its_own_tree(self):
        with self.assertRaisesRegex(SystemExit, "inside the repository"):
            runs.out_dir(str(ROOT / "python" / "out"), "eval", "arena")


class CodeTest(RepoFixture):
    def test_the_commit_and_dirty_flag_of_a_checkout(self):
        self.assertEqual(runs.code(self.main, environ={}), {"commit": self.head, "dirty": False})
        (self.main / "a.txt").write_text("b\n", encoding="utf-8")
        self.assertEqual(runs.code(self.main, environ={}), {"commit": self.head, "dirty": True})
        (self.main / "untracked.txt").write_text("u\n", encoding="utf-8")  # untracked files do not count
        (self.main / "a.txt").write_text("a\n", encoding="utf-8")
        self.assertEqual(runs.code(self.main, environ={})["dirty"], False)

    def test_a_worktree_whose_gitdir_does_not_resolve(self):
        # #411: a worktree made under another path (a Windows path seen from WSL) names a gitdir git cannot open
        # Rewritten in place ('r+'): Git for Windows hides the .git file, and Windows refuses to create a hidden file anew
        with open(self.worktree / ".git", "r+", encoding="utf-8", newline="\n") as dot_git:
            dot_git.truncate(0)
            dot_git.write("gitdir: C:/Dev/src/duoforge/.git/worktrees/lane\n")
        self.assertIsNone(runs._git(["rev-parse", "HEAD"], cwd=self.worktree))
        self.assertEqual(runs.code(self.worktree, environ={}), {"commit": self.head, "dirty": False})

    def test_a_copy_without_git_names_its_code_in_the_environment(self):
        plain = Path(self.tmp.name, "copy")
        plain.mkdir()
        self.assertEqual(runs.code(plain, environ={"DUOFORGE_COMMIT": "abc", "DUOFORGE_DIRTY": "1"}),
                         {"commit": "abc", "dirty": True})
        for environ in ({}, {"DUOFORGE_COMMIT": "abc"}, {"DUOFORGE_COMMIT": "abc", "DUOFORGE_DIRTY": "yes"}):
            with self.subTest(environ=environ), self.assertRaisesRegex(SystemExit, "no commit to name"):
                runs.code(plain, environ=environ)


class ManifestTest(RepoFixture):
    def test_the_manifest_of_a_run(self):
        out = Path(self.tmp.name, "out", "run")
        manifest = runs.Manifest("eval", "duoforge_eval.arena", ["--games", 4], seeds={"arena": 7}, root=self.main,
                                 environ={})
        path = manifest.write(out, games=4)
        self.assertEqual(path, out / "manifest.json")
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["manifest.json"])  # no temporary file is left
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["manifest"], runs.MANIFEST_VERSION)
        self.assertEqual((record["kind"], record["tool"], record["argv"], record["seeds"], record["games"]),
                         ("eval", "duoforge_eval.arena", ["--games", "4"], {"arena": 7}, 4))
        self.assertEqual(record["code"], {"commit": self.head, "dirty": False})
        self.assertLessEqual(record["start"], record["end"])
        self.assertEqual(set(record["machine"]), {"host", "system", "release", "machine", "processors", "python"})

    def test_the_manifest_names_this_repositorys_commit(self):
        record = runs.Manifest("eval", "t", []).record
        self.assertEqual(record["code"]["commit"], git(ROOT, "rev-parse", "HEAD"))

    def test_an_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError):
            runs.Manifest("night", "t", [], root=self.main, environ={})


if __name__ == "__main__":
    unittest.main()
