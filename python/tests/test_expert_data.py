"""Synthetic P1 data only; private shards are written to temporary directories."""
import dataclasses
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from duoforge import features


def manifest(ed):
    return ed.DataManifest(source_commit="a" * 40, checkpoint_hash="b" * 64,
        model_hash="c" * 64, encoder=4, ids_hash="d" * 64, pool_hash="e" * 64,
        belief_hash="f" * 64, seed=7, split_seed=9, key_version=1,
        device="cpu", runtime="synthetic", compiler="synthetic", capacity=1024,
        workers=4, parallel_games=512, game_count=1024, rounds=2,
        obs_width=features.obs_size(4), slot_width=features.SLOT_FEATURES,
        teacher_config={"k": 8, "m": 8, "worlds": 16, "lam": .5},
        budget={"labels": 16384}, evaluation={"synthetic": True})


def target_row(ed, m):
    mask = np.zeros((32, 32), bool)
    mask.flat[[0, 1]] = True
    obs = np.zeros(m.obs_width, np.float32)
    obs[0] = np.float32(-0.0)
    return ed.ExpertRow(key=ed.DecisionKey(0, 0, 1), obs=obs,
        slots=np.zeros((2, 32, m.slot_width), np.float32), legal_mask=mask,
        sparse_policy=ed.SparsePolicy(np.array([0, 1], np.int64), np.array([.25, .75], np.float64)),
        status=ed.RowStatus.TARGET, raw_action=1, action=0, behavior_logp=float(np.log(.25)),
        requested=True, acting=True, learner=True, value_mask=True, admitted=True,
        reward=0., done=False, collector_value=.5, bootstrap=.3, cause=None, work={}, audit={})


class ExpertDataTest(unittest.TestCase):
    def test_schema_refusal_and_private_roundtrip(self):
        from duoforge_search import expert_data as ed
        m = manifest(ed)
        row = target_row(ed, m)
        ed.validate_manifest(m)
        ed.validate_row(row, m)
        with tempfile.TemporaryDirectory(prefix="duoforge_synthetic_expert_") as temp:
            a, b = Path(temp)/"a.json", Path(temp)/"b.json"
            sha = ed.write_shard(a, [row], m)
            self.assertEqual(sha, hashlib.sha256(a.read_bytes()).hexdigest())
            self.assertEqual(sha, ed.write_shard(b, [row], m))
            restored, = ed.read_shard(a, m)
            for field in ("obs", "slots", "legal_mask"):
                self.assertEqual(getattr(row, field).tobytes(), getattr(restored, field).tobytes())
            self.assertEqual(restored.behavior_logp, row.behavior_logp)
            self.assertEqual(restored.key, row.key)
            self.assertEqual(restored.sparse_policy.probs.tobytes(), row.sparse_policy.probs.tobytes())
            with self.assertRaises(FileExistsError):
                ed.write_shard(a, [row], m)
            with self.assertRaisesRegex(ValueError, "manifest"):
                ed.read_shard(a, dataclasses.replace(m, seed=8))
            data = json.loads(a.read_text(encoding="utf-8"))
            data["schema_version"] = 2
            b.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema"):
                ed.read_shard(b, m)
            data = json.loads(a.read_text(encoding="utf-8"))
            data["rows"][0]["action"] = 1
            b.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "integrity"):
                ed.read_shard(b, m)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                ed.write_shard(Path(temp)/"dupes.json", [row, row], m)
        with self.assertRaisesRegex(ValueError, "repository"):
            ed.write_shard(Path(__file__).parent/"private-expert.json", [row], m)
        for bad in (dataclasses.replace(m, schema_version=2), dataclasses.replace(m, key_version=2),
                    dataclasses.replace(m, rounds=3), dataclasses.replace(m, checkpoint_hash="invalid")):
            with self.subTest(manifest=bad), self.assertRaises(ValueError):
                ed.validate_manifest(bad)
        for bad in (dataclasses.replace(row, obs=row.obs.astype(np.float64)),
                    dataclasses.replace(row, slots=np.zeros((2, 31, m.slot_width), np.float32)),
                    dataclasses.replace(row, action=2), dataclasses.replace(row, raw_action=1024),
                    dataclasses.replace(row, behavior_logp=0.), dataclasses.replace(row, admitted=False),
                    dataclasses.replace(row, learner=False), dataclasses.replace(row, reward=float("nan")),
                    dataclasses.replace(row, sparse_policy=ed.SparsePolicy(np.array([0,0],np.int64),np.array([.5,.5]))),
                    dataclasses.replace(row, sparse_policy=ed.SparsePolicy(np.array([0,1],np.int64),np.array([.5,.500002])))):
            with self.subTest(row=bad), self.assertRaises(ValueError):
                ed.validate_row(bad, m)
        waiting = dataclasses.replace(row, status=ed.RowStatus.UNREQUESTED, requested=False,
            acting=False, admitted=False, action=None, raw_action=None, behavior_logp=None, sparse_policy=None)
        ed.validate_row(waiting, m)
        fallback = dataclasses.replace(row, status=ed.RowStatus.PUBLIC_REFUSAL, sparse_policy=None,
            action=1, behavior_logp=float(np.log(.8)), cause="synthetic_public_refusal")
        ed.validate_row(fallback, m)
        # Frozen data objects must detach from caller-owned mutable arrays/configs.
        with self.assertRaises(ValueError):
            row.obs[0] = 1.
        with self.assertRaises(TypeError):
            m.teacher_config["k"] = 9
        caller = row.obs.copy()
        detached = dataclasses.replace(row, obs=caller)
        caller[0] = 42.
        self.assertEqual(detached.obs[0].tobytes(), row.obs[0].tobytes())


    def test_selection_word_domains_and_frequency(self):
        from duoforge_search import expert_data as ed
        key = ed.DecisionKey(42, 1, 9)
        self.assertEqual(ed.selection_word(key, 7, domain="SELECT"), 7771256613835731320)
        domains = ("raw", "SELECT", "world", "X", "audit", "split")
        words = [ed.selection_word(key, 7, domain=d) for d in domains]
        self.assertEqual(len(set(words)), len(domains))
        self.assertTrue(all(0 <= x < 2**64 for x in words))
        keys = [ed.DecisionKey(i, i % 2, 3) for i in range(65536)]
        count = sum(ed.selection_word(k, 7, domain="SELECT") < 2**61 for k in keys)
        self.assertLessEqual(abs(count - 8192), 384)
        sample = keys[:100]
        expected = {k: ed.selection_word(k, 7, domain="SELECT") for k in sample}
        self.assertEqual(expected, {k: ed.selection_word(k, 7, domain="SELECT") for k in reversed(sample)})
        with self.assertRaisesRegex(ValueError, "version"):
            ed.selection_word(key, 7, domain="SELECT", version=2)
        for bad_key, seed, domain in ((ed.DecisionKey(-1,0,0),7,"SELECT"),
                                     (ed.DecisionKey(0,2,0),7,"SELECT"),
                                     (ed.DecisionKey(0,0,2**64),7,"SELECT"),
                                     (key,True,"SELECT"), (key,2**64,"SELECT"), (key,7,""),
                                     (key,7,"select")):
            with self.subTest(key=bad_key, seed=seed, domain=domain), self.assertRaises(ValueError):
                ed.selection_word(bad_key, seed, domain=domain)

if __name__ == "__main__":
    unittest.main()
