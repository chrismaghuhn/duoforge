"""duoforge.python.equivalence: the binding equals the native mode.

37 environments over the four reference pairings: the Python loop (query,
RandomPolicy, step) gives byte-identical episode records to the native
play_random, on the index form and on the factored form, for 1 and 4
workers. Also the factored helpers' bijection and the input checks of the
plan's Review Focus 2 and 3.
"""
import unittest

import numpy as np

import duoforge
from duoforge import _layout

SEED = 0x2026100200000012
ENVS = 37
EPISODES = 3
MAX_STEPS = 1000


def _setups():
    return duoforge.reference_setups([e % 4 for e in range(ENVS)])


def _native(ctx, workers):
    with duoforge.Batch(ctx, _setups(), workers, SEED) as batch:
        return batch.play_random(EPISODES, MAX_STEPS).copy()


def _python(ctx, workers, factored, on_domains=None, episodes=EPISODES):
    """The native mode's episodes, played from Python; on_domains(batch) is
    called after every factored query."""
    records = np.zeros((ENVS, episodes), dtype=_layout.EPISODE)
    policy = duoforge.RandomPolicy(SEED, ENVS)
    with duoforge.Batch(ctx, _setups(), workers, SEED) as batch:
        for k in range(1, episodes + 1):
            for e in range(ENVS):
                policy.start_episode(e, k)
                batch.reset(e, k)
            steps = np.zeros(ENVS, dtype=np.uint32)
            decisions = np.zeros(ENVS, dtype=np.uint32)
            for _ in range(MAX_STEPS + 1):
                if factored:
                    batch.query_factored()
                    if on_domains is not None:
                        on_domains(batch)
                else:
                    batch.query()
                requested = batch.requests["requested"] != 0
                live = requested.any(axis=1)
                if not live.any():
                    break
                if factored:
                    batch.step_factored(policy.choose_factored(batch))
                else:
                    batch.step(policy.choose(batch))
                steps += live
                decisions += requested.sum(axis=1, dtype=np.uint32)
            else:
                raise AssertionError("an episode passed MAX_STEPS")
            rec = records[:, k - 1]
            rec["env"] = np.arange(ENVS)
            rec["episode"] = k
            rec["steps"] = steps
            rec["decisions"] = decisions
            rec["turns"] = batch.observations[:, 0]["turn"]
            rec["result"] = [batch.result(e) for e in range(ENVS)]
            rec["digest"] = [np.frombuffer(batch.digest(e), dtype=np.uint8) for e in range(ENVS)]
    return records


class EquivalenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = duoforge.Context()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()

    def test_index_form_equals_native(self):
        for workers in (1, 4):
            with self.subTest(workers=workers):
                native = _native(self.ctx, workers)
                self.assertTrue((native["result"] != 0).all())
                self.assertEqual(_python(self.ctx, workers, False).tobytes(), native.tobytes())

    def test_factored_form_equals_native(self):
        for workers in (1, 4):
            with self.subTest(workers=workers):
                native = _native(self.ctx, workers)
                self.assertEqual(_python(self.ctx, workers, True).tobytes(), native.tobytes())

    def test_joint_index_inverts_factored_choice(self):
        checked = [0, 0]

        def every_rank(batch):
            for e, p in zip(*np.nonzero(batch.requests["requested"])):
                d = batch.domains[e, p]
                count = int(batch.requests[e, p]["candidate_count"])
                ks = np.arange(count)
                many = np.repeat(d.reshape(1), count)
                back = duoforge.joint_indices(many, duoforge.factored_choices(many, ks))
                self.assertTrue(np.array_equal(back, ks))
                self.assertEqual(duoforge.joint_index(d, duoforge.factored_choice(d, count - 1)), count - 1)
                checked[0] += 1
                checked[1] += count

        _python(self.ctx, 4, True, on_domains=every_rank, episodes=1)
        self.assertGreater(checked[0], 1000)

    def test_bad_index_arrays_raise_before_c(self):
        with duoforge.Batch(self.ctx, _setups(), 4, SEED) as batch:
            batch.query()
            idx = duoforge.RandomPolicy(SEED, ENVS).choose(batch)
            with self.assertRaises(TypeError):
                batch.step(np.zeros((ENVS, 2), dtype=np.int64))
            with self.assertRaises(ValueError):
                batch.step(np.asfortranarray(idx))
            with self.assertRaises(ValueError):
                batch.step(idx[:, ::-1])
            with self.assertRaises(ValueError):
                batch.step(idx[:-1])
            with self.assertRaises(TypeError):
                batch.step_factored(np.zeros((ENVS, 2), dtype=np.uint16))
            with self.assertRaises(ValueError):
                batch.reset(0, -1)
            with self.assertRaises(IndexError):
                batch.reset(ENVS, 0)
            batch.step(idx)  # the batch is unharmed

    def test_step_after_reset_terminal_needs_a_query(self):
        policy = duoforge.RandomPolicy(SEED, ENVS)
        with duoforge.Batch(self.ctx, _setups(), 4, SEED) as batch:
            for e in range(ENVS):
                policy.start_episode(e, 0)
            terminal = np.zeros(ENVS, dtype=bool)
            for _ in range(MAX_STEPS):
                batch.query()
                terminal = batch.requests["requested"].sum(axis=1) == 0
                if terminal.any():
                    break
                batch.step(policy.choose(batch))
            self.assertTrue(terminal.any() and not terminal.all())
            idx = policy.choose(batch)
            batch.reset_terminal()
            with self.assertRaises(duoforge.DuoforgeError) as caught:
                batch.step(idx)
            err = caught.exception
            self.assertEqual(err.status_name, "DUOFORGE_E_STALE_EPOCH")
            names = [duoforge.status_name(s) for s in err.statuses]
            self.assertEqual({n for n, t in zip(names, terminal) if t}, {"DUOFORGE_E_STALE_EPOCH"})
            self.assertEqual({n for n, t in zip(names, terminal) if not t}, {"DUOFORGE_OK"})

    def test_buffers_cannot_be_replaced(self):
        with duoforge.Batch(self.ctx, _setups(), 1, SEED) as batch:
            for name in ("requests", "observations", "candidates", "counts", "domains", "statuses", "results"):
                with self.assertRaises(AttributeError):
                    setattr(batch, name, np.zeros(1))
            with self.assertRaises(TypeError):
                batch.reset(0, 1.0)
            batch.query_factored()
            with self.assertRaises(TypeError):
                duoforge.factored_choices(batch.domains[0], [0.5, 0.5])

    def test_start_episodes_equals_seeds(self):
        policy = duoforge.RandomPolicy(SEED, 4096)
        rng = np.random.default_rng(7)
        envs = rng.permutation(4096)[:1000]
        episodes = rng.integers(0, 2**32, size=1000, dtype=np.uint64)
        policy.start_episodes(envs, episodes)
        for e, k in zip(envs[:200], episodes[:200]):
            self.assertEqual(int(policy.state[e]), duoforge.seeds(SEED, int(e), int(k))[2])
        with self.assertRaises(ValueError):
            policy.start_episodes([0], [2**32])

    def test_step_query_equals_its_parts(self):
        # step, the ended episodes' results, reset_terminal and query against
        # step_query with autoreset, until every environment ended 2 episodes.
        terminal = _layout.CONSTANTS["DUOFORGE_BOUNDARY_TERMINAL"]
        policy_a = duoforge.RandomPolicy(SEED, ENVS)
        policy_b = duoforge.RandomPolicy(SEED, ENVS)
        with duoforge.Batch(self.ctx, _setups(), 4, SEED) as a, duoforge.Batch(self.ctx, _setups(), 4, SEED) as b:
            for policy in (policy_a, policy_b):
                policy.start_episodes(np.arange(ENVS), np.zeros(ENVS, dtype=np.uint64))
            a.query()
            b.query()
            ended = 0
            while ended < 2 * ENVS:
                idx = policy_a.choose(a)
                self.assertTrue(np.array_equal(idx, policy_b.choose(b)))
                a.step(idx)
                done = np.flatnonzero(a.results["boundary_kind"] == terminal)
                results = np.zeros(ENVS, dtype=np.uint32)
                results[done] = [a.result(e) for e in done]
                a.reset_terminal()
                a.query()
                b.step_query(idx, autoreset=True)
                ended += done.size
                for buffer in ("requests", "observations", "counts", "statuses", "results"):
                    self.assertEqual(getattr(a, buffer).tobytes(), getattr(b, buffer).tobytes(), buffer)
                self.assertTrue(np.array_equal(results, b.episode_results))
                for e in done:
                    self.assertEqual(a.digest(e), b.digest(e))
                    self.assertEqual(a.episode(e), b.episode(e))
                episodes = np.array([a.episode(e) for e in done], dtype=np.uint64)
                policy_a.start_episodes(done, episodes)
                policy_b.start_episodes(done, episodes)

    def test_seeds(self):
        initstate, initseq, policy = duoforge.seeds(SEED, 5, 7)
        self.assertLess(initseq, 1 << 63)
        self.assertEqual(duoforge.seeds(SEED, 5, 7), (initstate, initseq, policy))
        self.assertNotEqual(duoforge.seeds(SEED, 5, 8)[2], policy)
        with self.assertRaises(ValueError):
            duoforge.seeds(-1, 0, 0)

    def test_closed_context_with_open_batch(self):
        ctx = duoforge.Context()
        batch = duoforge.Batch(ctx, _setups(), 1, SEED)
        with self.assertRaises(RuntimeError):
            ctx.close()
        batch.close()
        ctx.close()
        with self.assertRaises(ValueError):
            batch.query()


if __name__ == "__main__":
    unittest.main()
