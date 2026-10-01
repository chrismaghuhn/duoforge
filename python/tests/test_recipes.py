"""duoforge.python.recipes: write, load and replay trajectory recipes.

16 episodes (8 environments, 2 rounds) with RandomPolicy are recorded,
written and loaded, then replayed: on_decision sees every decision once, in
the recipe's order. A changed choice, digest, step count or result raises
ReplayMismatch; a recipe of another library version or fingerprint raises
RecipeVersionError before anything replays (Review Focus 4). Sparse and
uneven recipes replay through Batch.step's active mask; a failed recording
writes nothing; record() refuses a writer that describes another run; load()
refuses malformed contents.
"""
import json
import os
import shutil
import tempfile
import unittest

import numpy as np

import duoforge
from duoforge import features, recipes

SEED = 0x2026100200000015
ENVS = 8
PAIRINGS = ["A-B", "B-A", "A-A", "B-B"]
SPEC = {  # spec section 6: name -> dtype
    "env": np.uint32, "episode": np.uint32, "setup": np.uint8, "policy": np.uint16, "steps": np.uint32,
    "result": np.uint8, "truncated": np.bool_, "digest": np.uint8, "choice_offset": np.uint64, "choice": np.uint16,
}


def _setups():
    return duoforge.reference_setups([e % 4 for e in range(ENVS)])


def _writer(path, ctx, **change):
    args = dict(context=ctx, seed=SEED, max_steps=1000, setups=PAIRINGS,
                policies=[{"name": "random", "seed": SEED}], command="test_recipes")
    args.update(change)
    return recipes.RecipeWriter(path, **args)


class _BadAfter:
    """RandomPolicy that answers one index past the list from round 2 on."""

    def __init__(self):
        self.inner = duoforge.RandomPolicy(SEED, ENVS)
        self.round = 0

    def start_episode(self, env, episode):
        self.round = episode
        self.inner.start_episode(env, episode)

    def choose(self, batch):
        idx = self.inner.choose(batch)
        if self.round >= 2:
            requested = batch.requests["requested"] != 0
            idx[requested] = batch.counts[requested].astype(np.uint16)
        return idx


class RecipeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="duoforge-recipes-")
        cls.path = os.path.join(cls.dir, "random16")
        cls.ctx = duoforge.Context()
        with duoforge.Batch(cls.ctx, _setups(), 4, SEED) as batch:
            with _writer(cls.path, cls.ctx) as writer:
                recipes.record(batch, duoforge.RandomPolicy(SEED, ENVS), writer, episodes=2,
                               setup=np.arange(ENVS) % 4, policy=(0, 0))

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()
        shutil.rmtree(cls.dir)

    def _copy(self, name, change_arrays=None, change_manifest=None):
        path = os.path.join(self.dir, name)
        with np.load(self.path + ".npz") as npz:
            arrays = {k: npz[k].copy() for k in npz.files}
        if change_arrays:
            arrays = change_arrays(arrays) or arrays
        np.savez(path + ".npz", **arrays)
        with open(self.path + ".json", encoding="utf-8") as f:
            manifest = json.load(f)
        manifest["episodes"] = int(arrays["env"].shape[0])
        manifest["decisions"] = int(arrays["choice"].shape[0])
        if change_manifest:
            change_manifest(manifest)
        with open(path + ".json", "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        return path

    def _mismatch(self, name, change_arrays):
        with self.assertRaises(recipes.ReplayMismatch):
            recipes.replay(recipes.load(self._copy(name, change_arrays=change_arrays)))

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
        self.assertEqual(manifest["context_fingerprint"], self.ctx.fingerprint().hex())

    def test_replay_sees_every_decision_in_order(self):
        recipe = recipes.load(self.path)
        seen = {}
        recipes.replay(recipe, workers=4,
                       on_decision=lambda e, k, p, ob, cands, count, choice, domain:
                       seen.setdefault((e, k), []).append(choice))
        self.assertEqual(sum(len(v) for v in seen.values()), recipe.arrays["choice"].shape[0])
        for i in range(len(recipe)):
            key = (int(recipe.arrays["env"][i]), int(recipe.arrays["episode"][i]))
            self.assertEqual(seen[key], [int(c) for c in recipe.choices(i)])
        self.assertTrue((recipe.arrays["result"] != 0).all())

    def test_replay_feeds_the_encoder(self):
        # on_decision receives the encoder's inputs: the observation and the
        # factored domain of the same boundary, which holds the choice.
        slots = duoforge._layout.CONSTANTS["DUOFORGE_CHOICE_SLOTS"]
        seen = [0, 0]

        def check(e, k, p, ob, cands, count, choice, domain):
            obs_part, slot_part, pair_mask = features.encode(ob, domain)
            self.assertEqual(int(duoforge.joint_counts(domain)[0]), count)
            self.assertEqual(duoforge.joint_index(domain, duoforge.factored_choice(domain, choice)), choice)
            if int(domain["kind"]) == slots:
                self.assertEqual(int(pair_mask.sum()), count)
                seen[1] += 1
            seen[0] += 1

        recipe = recipes.load(self.path)
        recipes.replay(recipe, on_decision=check)
        self.assertEqual(seen[0], recipe.arrays["choice"].shape[0])
        self.assertGreater(seen[1], 0)

    def test_changed_choice_raises(self):
        recipe = recipes.load(self.path)
        counts = []
        recipes.replay(recipe, on_decision=lambda e, k, p, ob, cands, count, choice, domain:
                       counts.append(count) if (e, k) == (0, 1) else None)
        first = int(np.flatnonzero((recipe.arrays["env"] == 0) & (recipe.arrays["episode"] == 1))[0])
        self.assertEqual(int(recipe.arrays["choice_offset"][first]), 0)
        self.assertGreater(counts[5], 1)

        def change(arrays):
            arrays["choice"][5] = (int(arrays["choice"][5]) + 1) % counts[5]

        self._mismatch("changed", change)

    def test_changed_digest_steps_or_result_raise(self):
        def digest(arrays):
            arrays["digest"][3, 7] ^= 1

        def steps(arrays):
            arrays["steps"][3] -= 1

        def result(arrays):
            arrays["result"][3] = 3 - int(arrays["result"][3]) if arrays["result"][3] != 3 else 1

        self._mismatch("digest", digest)
        self._mismatch("steps", steps)
        self._mismatch("result", result)

    def test_sparse_and_uneven_recipes_replay(self):
        # Drop environment 3 entirely and environment 1's second episode:
        # environments 1 and 3 are then skipped through the active mask.
        def subset(arrays):
            keep = ~((arrays["env"] == 3) | ((arrays["env"] == 1) & (arrays["episode"] == 2)))
            offsets = arrays["choice_offset"]
            pieces = [arrays["choice"][int(offsets[i]):int(offsets[i + 1])] for i in np.flatnonzero(keep)]
            out = {name: arrays[name][keep] for name in SPEC if name not in ("choice_offset", "choice")}
            out["choice"] = np.concatenate(pieces).astype(np.uint16)
            out["choice_offset"] = np.concatenate([[0], np.cumsum([len(p) for p in pieces])]).astype(np.uint64)
            return out

        recipe = recipes.load(self._copy("sparse", change_arrays=subset))
        self.assertEqual(len(recipe), 13)
        calls = []
        recipes.replay(recipe, workers=2, on_decision=lambda *args: calls.append(args[0]))
        self.assertEqual(len(calls), recipe.arrays["choice"].shape[0])
        self.assertNotIn(3, calls)

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
        with duoforge.Batch(self.ctx, _setups(), 2, SEED) as batch:
            with _writer(path, self.ctx, max_steps=4) as writer:
                recipes.record(batch, duoforge.RandomPolicy(SEED, ENVS), writer, episodes=1,
                               setup=np.arange(ENVS) % 4, policy=(0, 0))
        recipe = recipes.load(path)
        self.assertTrue(recipe.arrays["truncated"].all())
        self.assertTrue((recipe.arrays["steps"] == 4).all())
        recipes.replay(recipe)

    def test_failed_recording_writes_nothing(self):
        path = os.path.join(self.dir, "failed")
        with duoforge.Batch(self.ctx, _setups(), 2, SEED) as batch:
            with self.assertRaises(duoforge.DuoforgeError):
                with _writer(path, self.ctx) as writer:
                    recipes.record(batch, _BadAfter(), writer, episodes=3, setup=np.arange(ENVS) % 4)
        self.assertFalse(os.path.exists(path + ".npz") or os.path.exists(path + ".json"))
        with self.assertRaises(TypeError):
            _writer(os.path.join(self.dir, "unserializable"), self.ctx, policies=[{"name": "x", "n": np.uint64(1)}])

    def test_record_refuses_a_writer_of_another_run(self):
        path = os.path.join(self.dir, "refused")
        with duoforge.Batch(self.ctx, _setups(), 2, SEED) as batch:
            for writer in (_writer(path, self.ctx, seed=SEED + 1),
                           _writer(path, self.ctx, setups=["B-A", "A-B", "A-A", "B-B"])):
                with self.assertRaises(ValueError):
                    recipes.record(batch, duoforge.RandomPolicy(SEED, ENVS), writer, episodes=1,
                                   setup=np.arange(ENVS) % 4)
            with duoforge.Context(data_kind=4) as other:
                with self.assertRaises(ValueError):
                    recipes.record(batch, duoforge.RandomPolicy(SEED, ENVS), _writer(path, other), episodes=1,
                                   setup=np.arange(ENVS) % 4)
        self.assertFalse(os.path.exists(path + ".npz"))

    def test_load_refuses_malformed_recipes(self):
        def offsets(arrays):
            arrays["choice_offset"][-1] -= 3

        def policy(arrays):
            arrays["policy"][0, 1] = 1

        def counts(manifest):
            manifest["decisions"] += 1

        for name, arrays, manifest in (("offsets", offsets, None), ("policy", policy, None), ("counts", None, counts)):
            with self.subTest(name), self.assertRaises(ValueError):
                recipes.load(self._copy(name, change_arrays=arrays, change_manifest=manifest))

    def test_masked_step_reports_the_active_failure(self):
        with duoforge.Batch(self.ctx, _setups(), 2, SEED) as batch:
            policy = duoforge.RandomPolicy(SEED, ENVS)
            for e in range(ENVS):
                policy.start_episode(e, 0)
            batch.query()
            idx = policy.choose(batch)
            active = np.arange(ENVS) % 2 == 0
            masked = idx.copy()
            masked[~active] = duoforge._layout.NO_CHOICE
            with self.assertRaises(ValueError):
                batch.step(idx, active=active)  # choices outside the mask
            batch.step(masked, active=active)
            self.assertTrue((batch.statuses == 0).all())
            with self.assertRaises(duoforge.DuoforgeError) as caught:
                batch.step(masked, active=active)  # no query: the active environments are stale
            self.assertEqual(caught.exception.status_name, "DUOFORGE_E_STALE_EPOCH")
            self.assertTrue((caught.exception.statuses[~active] == 0).all())


if __name__ == "__main__":
    unittest.main()
