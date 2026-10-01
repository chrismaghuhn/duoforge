"""duoforge.python.recipes: write, load and replay trajectory recipes.

16 episodes (8 environments, 2 rounds) with RandomPolicy are recorded,
written and loaded, then replayed: on_decision sees every decision once.
A changed choice raises ReplayMismatch; a recipe of another library version
raises RecipeVersionError before anything replays (Review Focus 4).
"""
import json
import os
import shutil
import tempfile
import unittest

import numpy as np

import duoforge
from duoforge import recipes

SEED = 0x2026100200000015
ENVS = 8
SPEC = {  # spec section 6: name -> dtype
    "env": np.uint32, "episode": np.uint32, "setup": np.uint8, "policy": np.uint16, "steps": np.uint32,
    "result": np.uint8, "truncated": np.bool_, "digest": np.uint8, "choice_offset": np.uint64, "choice": np.uint16,
}


class RecipeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="duoforge-recipes-")
        cls.path = os.path.join(cls.dir, "random16")
        with duoforge.Context() as ctx:
            setups = duoforge.reference_setups([e % 4 for e in range(ENVS)])
            with duoforge.Batch(ctx, setups, 4, SEED) as batch:
                writer = recipes.RecipeWriter(cls.path, seed=SEED, max_steps=1000,
                                              setups=["A-B", "B-A", "A-A", "B-B"],
                                              policies=[{"name": "random", "seed": SEED}], command="test_recipes")
                with writer:
                    recipes.record(batch, duoforge.RandomPolicy(SEED, ENVS), writer, episodes=2,
                                   setup=np.arange(ENVS) % 4, policy=(0, 0))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def _copy(self, name, change_arrays=None, change_manifest=None):
        path = os.path.join(self.dir, name)
        with np.load(self.path + ".npz") as npz:
            arrays = {k: npz[k].copy() for k in npz.files}
        if change_arrays:
            change_arrays(arrays)
        np.savez(path + ".npz", **arrays)
        with open(self.path + ".json", encoding="utf-8") as f:
            manifest = json.load(f)
        if change_manifest:
            change_manifest(manifest)
        with open(path + ".json", "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        return path

    def test_arrays_have_the_spec_names_and_types(self):
        with np.load(self.path + ".npz") as npz:
            self.assertEqual(sorted(npz.files), sorted(SPEC))
            for name, dtype in SPEC.items():
                self.assertEqual(npz[name].dtype, dtype, name)
            self.assertEqual(npz["env"].shape, (16,))
            self.assertEqual(int(npz["choice_offset"][-1]), npz["choice"].shape[0])
        with open(self.path + ".json", encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["format"], "duoforge-recipe-1")
        self.assertEqual(manifest["library_version"], duoforge.version())

    def test_replay_sees_every_decision(self):
        recipe = recipes.load(self.path)
        calls = []
        recipes.replay(recipe, workers=4, on_decision=lambda *args: calls.append(args[:3] + args[5:]))
        self.assertEqual(len(calls), recipe.arrays["choice"].shape[0])
        self.assertTrue((recipe.arrays["result"] != 0).all())

    def test_changed_choice_raises(self):
        recipe = recipes.load(self.path)
        counts = []
        recipes.replay(recipe, on_decision=lambda e, k, p, ob, cands, count, choice:
                       counts.append(count) if (e, k) == (0, 1) else None)
        first = int(np.flatnonzero((recipe.arrays["env"] == 0) & (recipe.arrays["episode"] == 1))[0])
        self.assertEqual(int(recipe.arrays["choice_offset"][first]), 0)
        self.assertGreater(counts[5], 1)

        def change(arrays):
            arrays["choice"][5] = (int(arrays["choice"][5]) + 1) % counts[5]

        with self.assertRaises(recipes.ReplayMismatch):
            recipes.replay(recipes.load(self._copy("changed", change_arrays=change)))

    def test_other_library_version_raises_before_replay(self):
        def change(manifest):
            manifest["library_version"] = "0.0.0"

        calls = []
        recipe = recipes.load(self._copy("old", change_manifest=change))
        with self.assertRaises(recipes.RecipeVersionError):
            recipes.replay(recipe, on_decision=lambda *args: calls.append(args))
        self.assertEqual(calls, [])

    def test_other_fingerprint_raises(self):
        def change(manifest):
            manifest["context_fingerprint"] = "00" * 32

        with self.assertRaises(recipes.RecipeVersionError):
            recipes.replay(recipes.load(self._copy("fingerprint", change_manifest=change)))

    def test_truncated_episodes_replay(self):
        path = os.path.join(self.dir, "truncated")
        with duoforge.Context() as ctx:
            setups = duoforge.reference_setups([e % 4 for e in range(ENVS)])
            with duoforge.Batch(ctx, setups, 2, SEED) as batch:
                with recipes.RecipeWriter(path, seed=SEED, max_steps=4, setups=["A-B", "B-A", "A-A", "B-B"],
                                          policies=[{"name": "random"}], command="test") as writer:
                    recipes.record(batch, duoforge.RandomPolicy(SEED, ENVS), writer, episodes=1,
                                   setup=np.arange(ENVS) % 4, policy=(0, 0))
        recipe = recipes.load(path)
        self.assertTrue(recipe.arrays["truncated"].all())
        self.assertTrue((recipe.arrays["steps"] == 4).all())
        recipes.replay(recipe)


if __name__ == "__main__":
    unittest.main()
