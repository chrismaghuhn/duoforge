"""duoforge.python.eval_forwarders: the old names of the moved evaluation entry points keep working (restructure step 8).

Imported, an old module is the new module itself (attributes and mock.patch reach the same object); run as
python -m OLD, it names the new module on stderr and runs it with the same arguments. The other tests still import
the old names (test_search, test_book_preview, test_p1_eval, ...), so their real runs go through the forwarders too.
"""
import importlib
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
MOVED = {
    "duoforge_learn.bc_eval": "duoforge_eval.bc_eval",
    "duoforge_learn.p1_eval": "duoforge_eval.p1_eval",
    "duoforge_learn.ladder": "duoforge_eval.ladder",
    "duoforge_search.arena": "duoforge_eval.arena",
    "duoforge_search.book_ab": "duoforge_eval.book_ab",
    "duoforge_search.preview_ab": "duoforge_eval.preview_ab",
    "duoforge_search.expert_eval": "duoforge_eval.expert_eval",
    "duoforge_search.eval_manifest": "duoforge_eval.eval_manifest",
}
COMMANDS = {**MOVED, "duoforge_live.arena": "duoforge_eval.live_arena"}


class ForwarderTest(unittest.TestCase):
    def test_an_old_module_is_the_new_module(self):
        for old, new in MOVED.items():
            with self.subTest(old=old):
                module = importlib.import_module(old)
                self.assertIs(module, importlib.import_module(new))
                self.assertIs(sys.modules[old], module)
                package, name = old.rsplit(".", 1)
                self.assertIs(getattr(importlib.import_module(package), name), module)

    def test_a_patch_through_the_old_name_reaches_the_new_module(self):
        from duoforge_eval import arena
        with mock.patch("duoforge_search.arena.RESAMPLES", -1):
            self.assertEqual(arena.RESAMPLES, -1)
        self.assertNotEqual(arena.RESAMPLES, -1)

    def test_the_live_arena_keeps_its_client_and_forwards_its_main(self):
        from duoforge_eval import live_arena
        from duoforge_live import arena
        self.assertIsNot(arena, live_arena)  # the client code stays in duoforge_live (the live bot imports it)
        for name in ("provenance", "ENGINE_REFUSES", "run_lane", "evaluate", "GATES", "CTS_GATES"):
            self.assertTrue(hasattr(arena, name), name)
        with mock.patch.object(live_arena, "main", return_value="report") as main:
            self.assertEqual(arena.main(["--games", "2"]), "report")
        main.assert_called_once_with(["--games", "2"])

    def test_every_old_command_runs_the_new_one(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "python"), "PYTHONDONTWRITEBYTECODE": "1"}
        for old, new in COMMANDS.items():
            with self.subTest(old=old):
                run = subprocess.run([sys.executable, "-m", old, "--help"], cwd=ROOT, env=env, capture_output=True,
                                     text=True, timeout=300)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertIn(f"{old} moved to {new}: run python -m {new}", run.stderr)
                self.assertIn("usage:", run.stdout)
                self.assertNotIn(f"python -m {old}", run.stdout)  # the help names the new command, if it names one


if __name__ == "__main__":
    unittest.main()
