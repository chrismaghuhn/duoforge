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
    return ed.ExpertRow(key=ed.DecisionKey(0, 0, 1), logical_tick=0, boundary="TURN", obs=obs,
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


    def test_schema_refusal_and_private_roundtrip_boundaries_and_masks(self):
        from duoforge_search import expert_data as ed
        m = manifest(ed)
        row = target_row(ed,m)
        # Explicit boundary prevents preview or forced rows becoming turn labels.
        with self.assertRaises(ValueError):
            ed.validate_row(dataclasses.replace(row,boundary="TEAM_SELECTION"),m)
        with self.assertRaises(ValueError):
            ed.validate_row(dataclasses.replace(row,boundary="UNKNOWN"),m)
        team_mask = np.zeros(360,bool)
        team_mask[0] = team_mask[1] = True
        preview = dataclasses.replace(row, boundary="TEAM_SELECTION", status=ed.RowStatus.UNSELECTED,
            sparse_policy=None, admitted=False, legal_mask=team_mask, action=1, behavior_logp=float(np.log(.8)))
        ed.validate_row(preview,m)
        with self.assertRaises(ValueError):
            ed.validate_row(dataclasses.replace(preview,learner=False,value_mask=False),m)
        with self.assertRaises(ValueError):
            ed.validate_row(dataclasses.replace(preview,action=360),m)
        missing_raw = dataclasses.replace(row, sparse_policy=ed.SparsePolicy(np.array([0],np.int64),np.array([1.])),behavior_logp=0.)
        with self.assertRaises(ValueError):
            ed.validate_row(missing_raw,m)
        with self.assertRaises(ValueError):
            ed.validate_row(dataclasses.replace(row,work={"exact_ops":-1}),m)
        for bad in (dataclasses.replace(m, budget={"labels":16384.}),
                    dataclasses.replace(m,teacher_config={"k":8.,"m":8,"worlds":16,"lam":.5})):
            with self.assertRaises(ValueError):
                ed.validate_manifest(bad)

    def test_schema_refusal_and_private_roundtrip_waiting_ticks_and_workers(self):
        from duoforge_search import expert_data as ed
        m = dataclasses.replace(manifest(ed),workers=14)
        ed.validate_manifest(m)
        row = target_row(ed,m)
        self.assertEqual(row.logical_tick,0)
        waiting = dataclasses.replace(row,status=ed.RowStatus.UNREQUESTED,requested=False,
            acting=False,admitted=False,action=None,raw_action=None,behavior_logp=None,sparse_policy=None)
        later = dataclasses.replace(waiting,logical_tick=1)
        with tempfile.TemporaryDirectory(prefix="duoforge_synthetic_ticks_") as temp:
            path=Path(temp)/"ticks.json"
            ed.write_shard(path,[waiting,later],m)
            restored=ed.read_shard(path,m)
            self.assertEqual([r.logical_tick for r in restored],[0,1])
            self.assertEqual(restored[0].key,restored[1].key)
            with self.assertRaisesRegex(ValueError,"duplicate"):
                ed.write_shard(Path(temp)/"same_tick.json",[waiting,dataclasses.replace(waiting,key=ed.DecisionKey(0,0,2))],m)
            with self.assertRaisesRegex(ValueError,"regress"):
                ed.write_shard(Path(temp)/"regress.json",[later,waiting],m)
        for tick in (-1,True,2**64):
            with self.assertRaises(ValueError):
                ed.validate_row(dataclasses.replace(row,logical_tick=tick),m)
        for workers in (4,8,14):
            ed.validate_manifest(dataclasses.replace(m,workers=workers))
        for workers in (0,7,14.):
            with self.assertRaises(ValueError):
                ed.validate_manifest(dataclasses.replace(m,workers=workers))

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

    def test_selection_word_domains_and_frequency_select_rule_in_code(self):
        from duoforge_search import expert_data as ed
        self.assertEqual(ed.SELECT_THRESHOLD, 2**61)  # random 1/8, not every eighth arrival
        key = ed.DecisionKey(42, 1, 9)
        self.assertFalse(ed.is_selected(key, 7))  # pinned word 7771256613835731320 >= 2**61
        keys = [ed.DecisionKey(i, i % 2, 3) for i in range(65536)]
        chosen = [k for k in keys if ed.is_selected(k, 7)]
        self.assertEqual(chosen, [k for k in keys if ed.selection_word(k, 7, domain="SELECT") < 2**61])
        self.assertLessEqual(abs(len(chosen) - 8192), 384)
        for bad_key, seed in ((ed.DecisionKey(0, 2, 0), 7), (key, True), (key, 2**64)):
            with self.subTest(key=bad_key, seed=seed), self.assertRaises(ValueError):
                ed.is_selected(bad_key, seed)

    def test_selection_word_domains_and_frequency_held_out_split(self):
        from duoforge_search import expert_data as ed
        # Whole-game keyed split, fixed before collection: only game id and split seed enter.
        self.assertEqual(ed.HELD_OUT_THRESHOLD, 2**64 // 5)
        games = range(65536)
        held = [g for g in games if ed.is_held_out(g, 9)]
        self.assertEqual(held, [g for g in games if ed.selection_word(
            ed.DecisionKey(g, 0, 0), 9, domain="split") < 2**64 // 5])
        # Predeclared: 13107.2 expected, ~4.5 binomial standard deviations (102.4); no tuning.
        self.assertLessEqual(abs(len(held) - 13107), 460)
        self.assertEqual(held[:4], [17, 23, 32, 33])
        self.assertNotEqual(held, [g for g in games if ed.is_held_out(g, 7)])
        # The split never follows the SELECT gate; both are drawn from separate domains.
        self.assertNotEqual(set(held), {g for g in games if ed.is_selected(ed.DecisionKey(g, 0, 0), 9)})
        for game, seed in ((-1, 9), (True, 9), (2**64, 9), (0, -1), (0, 2**64)):
            with self.subTest(game=game, seed=seed), self.assertRaises(ValueError):
                ed.is_held_out(game, seed)

    def test_admission_precedes_tau_and_drops_games_in_order_never_tau_for_discarded_label(self):
        from duoforge_search import expert_data as ed
        m = manifest(ed)
        a, b, c = ed.DecisionKey(0, 0, 1), ed.DecisionKey(1, 1, 1), ed.DecisionKey(2, 0, 1)
        cursor = ed.LabelCursor(remaining=1)
        batch = ed.admit_tick(cursor, [a, b])
        self.assertEqual((batch.admitted_keys, batch.cap_raw_keys), ((a,), (b,)))
        pending = ed.cursor_bytes(cursor, m)
        # A cap-raw (discarded-label) root may only execute its pre-drawn raw action.
        for status in (ed.RowStatus.TARGET, ed.RowStatus.PUBLIC_REFUSAL, ed.RowStatus.WORK_EXHAUSTED,
                       ed.RowStatus.UNSELECTED, ed.RowStatus.FORCED):
            with self.subTest(cap_raw=status), self.assertRaisesRegex(ValueError, "cap-raw"):
                ed.commit_tick(cursor, [ed.AdmissionOutcome(a, ed.RowStatus.TARGET),
                                        ed.AdmissionOutcome(b, status)])
        # An admitted root cannot silently become cap-raw/unselected after the teacher ran.
        for status in (ed.RowStatus.CAP_RAW, ed.RowStatus.UNSELECTED, ed.RowStatus.FORCED):
            with self.subTest(admitted=status), self.assertRaisesRegex(ValueError, "admitted"):
                ed.commit_tick(cursor, [ed.AdmissionOutcome(a, status),
                                        ed.AdmissionOutcome(b, ed.RowStatus.CAP_RAW)])
        for outcomes in ([ed.AdmissionOutcome(a, ed.RowStatus.TARGET)],
                         [ed.AdmissionOutcome(a, ed.RowStatus.TARGET), ed.AdmissionOutcome(b, ed.RowStatus.CAP_RAW),
                          ed.AdmissionOutcome(c, ed.RowStatus.CAP_RAW)],
                         [ed.AdmissionOutcome(a, ed.RowStatus.TARGET), ed.AdmissionOutcome(a, ed.RowStatus.TARGET),
                          ed.AdmissionOutcome(b, ed.RowStatus.CAP_RAW)]):
            with self.subTest(outcomes=outcomes), self.assertRaises(ValueError):
                ed.commit_tick(cursor, outcomes)
        self.assertEqual(ed.cursor_bytes(cursor, m), pending)  # refused commits change nothing
        # Released refusal tickets never revive a dropped game: it stays cap-raw.
        after = ed.commit_tick(cursor, [ed.AdmissionOutcome(a, ed.RowStatus.PUBLIC_REFUSAL),
                                        ed.AdmissionOutcome(b, ed.RowStatus.CAP_RAW)])
        self.assertEqual(after.remaining, 1)
        again = ed.admit_tick(after, [ed.DecisionKey(1, 1, 2)])
        self.assertEqual((again.admitted_keys, again.cap_raw_keys), ((), (ed.DecisionKey(1, 1, 2),)))
        self.assertEqual(after.remaining, 1)
        # Row level: no stored tau, no fallback cause and no admission on a discarded label.
        row = target_row(ed, m)
        raw = dataclasses.replace(row, status=ed.RowStatus.CAP_RAW, sparse_policy=None, admitted=False,
                                  action=1, behavior_logp=float(np.log(.8)))
        ed.validate_row(raw, m)
        for bad in (dataclasses.replace(raw, action=0), dataclasses.replace(raw, sparse_policy=row.sparse_policy),
                    dataclasses.replace(raw, admitted=True), dataclasses.replace(raw, cause="cap"),
                    dataclasses.replace(raw, status=ed.RowStatus.UNSELECTED, action=0),
                    dataclasses.replace(raw, status=ed.RowStatus.PUBLIC_REFUSAL, admitted=True, cause="x", action=0),
                    dataclasses.replace(raw, status=ed.RowStatus.WORK_EXHAUSTED, admitted=True, cause="x", action=0),
                    dataclasses.replace(row, sparse_policy=None)):
            with self.subTest(row=bad.status), self.assertRaises(ValueError):
                ed.validate_row(bad, m)

    def test_admission_precedes_tau_and_drops_games_in_order(self):
        from duoforge_search import expert_data as ed
        m = manifest(ed)
        a, b = ed.DecisionKey(0, 0, 1), ed.DecisionKey(1, 1, 1)
        cursor = ed.LabelCursor(remaining=1)
        batch = ed.admit_tick(cursor, [b, a])
        self.assertEqual(batch.admitted_keys, (a,))
        self.assertEqual(batch.cap_raw_keys, (b,))
        self.assertEqual(batch.reserved_count, 1)
        self.assertEqual(cursor.remaining, 0)  # reservation precedes teacher/tau
        checkpoint = ed.cursor_bytes(cursor, m)
        resumed = ed.restore_cursor(checkpoint, m)
        self.assertEqual(ed.cursor_bytes(resumed, m), checkpoint)
        with self.assertRaisesRegex(ValueError, "manifest"):
            ed.restore_cursor(checkpoint, dataclasses.replace(m, seed=8))
        with self.assertRaises(ValueError):
            ed.admit_tick(cursor, [])
        with self.assertRaises(ValueError):
            ed.commit_tick(cursor, [ed.AdmissionOutcome(a, ed.RowStatus.TARGET)])
        with self.assertRaises(ValueError):
            ed.commit_tick(cursor, [ed.AdmissionOutcome(a, ed.RowStatus.UNSELECTED),
                                    ed.AdmissionOutcome(b, ed.RowStatus.CAP_RAW)])
        self.assertEqual(ed.cursor_bytes(cursor, m), checkpoint)
        outcomes = [ed.AdmissionOutcome(b, ed.RowStatus.CAP_RAW),
                    ed.AdmissionOutcome(a, ed.RowStatus.PUBLIC_REFUSAL)]
        committed = ed.commit_tick(cursor, outcomes)
        restored = ed.commit_tick(resumed, outcomes[::-1])
        self.assertEqual(ed.cursor_bytes(committed, m), ed.cursor_bytes(restored, m))
        self.assertEqual(committed.remaining, 1)  # refusal releases only at commit
        self.assertEqual(committed.logical_tick, 1)
        self.assertEqual(committed.dropped_games, frozenset({1}))
        c, again_b = ed.DecisionKey(2, 0, 1), ed.DecisionKey(1, 1, 2)
        next_batch = ed.admit_tick(committed, [again_b, c])
        self.assertEqual(next_batch.admitted_keys, (c,))
        self.assertEqual(next_batch.cap_raw_keys, (again_b,))
        final = ed.commit_tick(committed, [ed.AdmissionOutcome(c, ed.RowStatus.TARGET),
                                          ed.AdmissionOutcome(again_b, ed.RowStatus.CAP_RAW)])
        self.assertEqual(final.remaining, 0)
        self.assertIsNone(final.pending_reservations)
        with self.assertRaises(ValueError):
            ed.commit_tick(final, [])
        with self.assertRaises(ValueError):
            ed.admit_tick(final, [c])  # no repeated epoch
        for ordering in ([a,b], [b,a], sum([[b],[a]], [])):
            fresh = ed.LabelCursor(remaining=1)
            self.assertEqual(ed.admit_tick(fresh, ordering), batch)
            self.assertEqual(ed.cursor_bytes(fresh, m), checkpoint)
        empty = ed.LabelCursor(remaining=0)
        rejected = ed.admit_tick(empty, [a,b])
        self.assertEqual(rejected.admitted_keys, ())
        self.assertEqual(rejected.cap_raw_keys, (a,b))
        done = ed.commit_tick(empty, [ed.AdmissionOutcome(k,ed.RowStatus.CAP_RAW) for k in (a,b)])
        self.assertEqual(done.remaining, 0)
        blank = ed.LabelCursor()
        ed.admit_tick(blank, [])
        self.assertEqual(ed.commit_tick(blank, []).logical_tick, 1)
        for requests in ([a,a], [a,ed.DecisionKey(0,1,1)]):
            fresh = ed.LabelCursor()
            before = ed.cursor_bytes(fresh,m)
            with self.assertRaises(ValueError):
                ed.admit_tick(fresh, requests)
            self.assertEqual(ed.cursor_bytes(fresh,m),before)

if __name__ == "__main__":
    unittest.main()
