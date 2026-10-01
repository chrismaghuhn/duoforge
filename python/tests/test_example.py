"""duoforge.python.example: the generation example writes and replays.

Runs python -m duoforge.examples.generate with 8 environments, 2 episodes
and the scripted policy: exit status 0, both recipe files, and the line
"replay: 16 episodes, 0 mismatches".
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


class ExampleTest(unittest.TestCase):
    def test_generate_writes_and_replays(self):
        folder = tempfile.mkdtemp(prefix="duoforge-example-")
        try:
            out = os.path.join(folder, "scripted16")
            run = subprocess.run(
                [sys.executable, "-m", "duoforge.examples.generate", "--envs", "8", "--episodes", "2",
                 "--policy", "scripted", "--workers", "2", "--out", out],
                capture_output=True, text=True, timeout=300)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertTrue(os.path.isfile(out + ".npz"))
            self.assertTrue(os.path.isfile(out + ".json"))
            self.assertIn("replay: 16 episodes, 0 mismatches", run.stdout)
            self.assertIn("battles: 16", run.stdout)
        finally:
            shutil.rmtree(folder)

    def test_bad_arguments_fail(self):
        run = subprocess.run([sys.executable, "-m", "duoforge.examples.generate", "--envs", "0", "--out", "x"],
                             capture_output=True, text=True, timeout=60)
        self.assertNotEqual(run.returncode, 0)


if __name__ == "__main__":
    unittest.main()
