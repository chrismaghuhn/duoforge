"""duoforge.python.repo_hygiene: trained weights and run outputs never enter the repository.

AGENTS.md: weights, checkpoints, league snapshots and run directories are private. This test fails if any tracked
file looks like one, and if a workflow uploads CI artifacts (adding an upload needs the owner's decision).
"""
import subprocess
import unittest
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[3]
WEIGHT_SUFFIXES = {".npz", ".npy", ".pkl", ".pickle", ".pt", ".pth", ".ckpt", ".safetensors", ".msgpack", ".h5",
                   ".onnx"}
RUN_DIRECTORIES = {"runs", "checkpoints", "league"}
RUN_STEMS = {"best", "latest"}


def run_definition(p):
    """runs/<kind>/<id>/campaign*.conf and its team texts (*.txt), and runs/README.md: the definitions of named runs
    that the top-level runs/ holds (restructure step 8, HauptSession 2026-10-16). Their outputs never: a run's results,
    a deeper directory or any other file under runs/ stays forbidden."""
    if p.parts == ("runs", "README.md"):
        return True
    return (len(p.parts) == 4 and p.parts[0] == "runs"
            and (p.name.startswith("campaign") and p.suffix == ".conf" or p.suffix == ".txt"))


def forbidden(path):
    """Whether a repository path (POSIX form) looks like trained weights or a run output."""
    p = PurePosixPath(path)
    if p.suffix.lower() in WEIGHT_SUFFIXES or p.name.split(".")[0] in RUN_STEMS:
        return True
    return any(part in RUN_DIRECTORIES for part in p.parts[:-1]) and not run_definition(p)


class RepoHygieneTest(unittest.TestCase):
    def test_the_matcher(self):
        for path in ("runs/night/params-12.npz", "bc.npz", "x/league/snap", "checkpoints/a.json", "best.npz",
                     "latest.json", "model.safetensors", "w.pt"):
            self.assertTrue(forbidden(path), path)
        for path in ("python/duoforge_learn/checkpoint.py", "docs/learning/RUNBOOK.md", "tests/test_pool_g41.c",
                     "python/tests/support/data/live_stream_ab.json", "src/batch/batch.c"):
            self.assertFalse(forbidden(path), path)

    def test_runs_holds_definitions_only(self):
        # restructure step 8: runs/<kind>/<id>/ holds a named run's definition (campaign.conf and its team texts)
        for path in ("runs/fuzz/g10-moves/campaign.conf", "runs/fuzz/registry-mix/campaign-3.conf",
                     "runs/fuzz/weather-sand-snow/sand.txt", "runs/README.md"):
            self.assertFalse(forbidden(path), path)
        # and never a result: an output file, a run directory below a definition, a file in the wrong place, weights
        for path in ("runs/fuzz/g10-moves/summary.json", "runs/fuzz/g10-moves/manifest.json",
                     "runs/fuzz/g10-moves/out/campaign.conf", "runs/fuzz/g10-moves/2026-10-16/D.txt",
                     "runs/fuzz/campaign.conf", "runs/campaign.conf", "runs/fuzz/g10-moves/cases.tgz",
                     "runs/fuzz/g10-moves/params.npz", "runs/fuzz/g10-moves/best.txt", "runs/eval/x/games.jsonl",
                     "x/runs/fuzz/a/campaign.conf", "python/runs/fuzz/a/D.txt"):
            self.assertTrue(forbidden(path), path)

    def test_no_tracked_weights_or_run_outputs(self):
        tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
        bad = [p for p in tracked.decode("utf-8").split("\0") if p and forbidden(p)]
        self.assertEqual(bad, [], "trained weights or run outputs are tracked (AGENTS.md: they stay private)")

    def test_no_workflow_uploads_artifacts(self):
        uploads = [str(f.relative_to(ROOT)) for f in sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))
                   if "upload-artifact" in f.read_text(encoding="utf-8")]
        self.assertEqual(uploads, [], "a workflow uploads CI artifacts; that needs the owner's decision (AGENTS.md)")


if __name__ == "__main__":
    unittest.main()
