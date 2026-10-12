"""duoforge.python.collect_expert: the stage 3 P1 teacher-data collector (Learner v2 plan
2026-10-08-stage3-p1-learner, task 8).

Lockstep self-play rounds of 512 games (the manifest pins them) with the deterministic NumPy network of
test_expert_teacher as collector, opponent and teacher network, the reference setups' spread table as the belief and
the P1 search sizes. The label cap and the cut-off are small so a round stays a few seconds; every output goes to a
temporary directory outside the repository. No trained weights, real data or run outputs.
"""
import dataclasses
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

import duoforge
from duoforge import _layout, features, teams
from duoforge_learn.selfplay import TEAM_ACTIONS

C = _layout.CONSTANTS
MAX_STEPS = 24  # most games of the near-uniform network end by then; the rest are cut and scored by tiebreak
LABELS = 12  # the test's label cap: round 0 exhausts it, so capped games and later raw rounds occur
SHARD_ROWS = 2500  # below a round's rows: trajectories span shards and a round writes several


def _pool():
    """Teams A and B (both spread sources of _table) and LL_B, a copy of B that is no spread source."""
    sides = duoforge.reference_setups([0])["sides"][0]
    return teams.TeamPool.from_setups(("A", "B", "LL_B"), np.stack([sides[0], sides[1], sides[1]]))


SOURCES = {"A": 0, "B": 1}  # _table's source index of each spread-source team (its position in the sides)


def _table():
    from duoforge_search import belief
    return belief.SpreadTable.from_sides(duoforge.reference_setups([0])["sides"].reshape(-1))


def _manifest(rounds=2):
    from duoforge_search import expert_data as ed
    from python.tests.test_expert_data import manifest
    return dataclasses.replace(manifest(ed), belief_hash=_table().sha256(), rounds=rounds, game_count=512 * rounds,
                               first_game_id=1000)


class StopInRound:
    """A stop flag that is raised once the collector has written a shard of the given round."""

    def __init__(self, shards, round_index):
        self.shards, self.round = Path(shards), round_index

    @property
    def requested(self):
        return any(self.shards.glob(f"round-{self.round:04d}-*.json"))


class Collector(unittest.TestCase):
    """One uninterrupted baseline collection of two rounds, compared with a second collection, an interrupted and
    resumed one, and read back row by row."""

    @classmethod
    def setUpClass(cls):
        from python.tests.test_expert_teacher import FoeSensitiveNet

        class RowLocalNet(FoeSensitiveNet):
            """test_expert_teacher's network with each row's slot term its own (np.resize there spreads one row's
            slot terms over the next rows of a batch), so a row's outputs do not depend on its batch."""

            def apply(self, params, obs, slots, mask):
                obs = np.asarray(obs, np.float32)
                b = obs.shape[0]
                legal = np.asarray(mask, bool).reshape(b, -1)
                slot_term = np.asarray(slots, np.float32).reshape(b, -1, features.SLOT_FEATURES) @ params["slot"]
                pair = obs @ params["pair"] + np.tile(slot_term, (1, 1024 // slot_term.shape[1]))
                pair = self._log_softmax(pair, legal | ~legal.any(axis=1, keepdims=True))
                team = self._log_softmax(obs @ params["team"], np.ones((b, TEAM_ACTIONS), bool))
                return pair, team, np.tanh(obs @ params["value"])

        cls.net = RowLocalNet()
        cls.ctx = duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"])
        cls.manifest = _manifest()
        cls.tmp = tempfile.TemporaryDirectory(prefix="duoforge-collect-")
        cls.root = Path(cls.tmp.name)
        cls.base = cls.root / "base"
        cls.base_result = cls.collect(cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()
        cls.tmp.cleanup()

    @classmethod
    def search(cls):
        from duoforge_search import honest, lookahead
        with duoforge.Batch(cls.ctx, duoforge.reference_setups([0]), 1, 42) as b:
            mask = int(b.observe_ext()[0, 0]["supported"]) & features.version_features(4)  # encoder 4 (0050)
        return honest.Honest(cls.ctx, cls.net, cls.net.params, 4, mask, k=8, m=8, s=16, rule="mix", capacity=1024,
                             workers=2, table=_table(), seed=lookahead.SEARCH_SEED)

    @classmethod
    def collect(cls, out, **kw):
        from duoforge_learn import collect_expert as ce
        options = {"max_steps": MAX_STEPS, "label_limit": LABELS, "source_ids": SOURCES}
        options.update(kw)
        with mock.patch.object(ce, "SHARD_ROWS", SHARD_ROWS), cls.search() as search:
            return ce.collect(cls.manifest, cls.net, cls.net.params, _pool(), search, out, **options)

    @staticmethod
    def files(out):
        return {p.name: p.read_bytes() for p in sorted((Path(out) / "shards").glob("*.json"))}

    def rows(self, out):
        from duoforge_search import expert_data as ed
        rows = []
        for path in sorted((Path(out) / "shards").glob("*.json")):
            rows.extend(ed.read_shard(path, self.manifest))
        return rows

    def test_collect_is_deterministic_and_round_trips(self):
        from duoforge_learn import collect_expert as ce, distill_data
        from duoforge_search import expert as ex, expert_data as ed
        base = self.files(self.base)
        self.assertTrue(self.base_result.complete)
        self.assertGreater(len(base), 2)
        self.assertEqual(sorted(base), sorted(base, key=lambda n: (int(n[6:10]), int(n[17:21]))))  # write order
        self.assertTrue(all(n.startswith(("round-0000-", "round-0001-")) for n in base))
        # Another collection with the same inputs, on another number of native workers: the same bytes.
        from duoforge_learn import ledger
        again = self.root / "again"
        book = ledger.Ledger(self.root / "ledger.json")
        result = self.collect(again, workers=1, ledger=book)
        self.assertEqual(self.files(again), base)
        # The generation phase is charged. On CPU JAX the network pass is CPU work: its time is in the CPU
        # core-seconds (getrusage), never in GPU-seconds.
        saved = __import__("json").loads((self.root / "ledger.json").read_text())
        self.assertGreater(saved["phases"]["generate"]["cpu_core_seconds"], 0)
        self.assertEqual(saved["phases"]["generate"]["gpu_seconds"], 0.0)
        self.assertEqual(saved["gpu_seconds"], 0.0)
        self.assertEqual(ce.device_platform(self.net.params), "cpu")
        self.assertEqual(result.counters, self.base_result.counters)
        self.assertEqual(ed.read_manifest(again / "manifest.json"), self.manifest)
        # Learner v2's loader reads them: complete trajectories, one learner seat per game, done on the last row.
        data = distill_data.load(self.base / "shards", self.manifest)
        rows = self.rows(self.base)
        self.assertEqual(len(rows), self.base_result.rows)
        self.assertEqual(data.obs.shape[0], len(rows))
        games = {}
        for row in rows:
            games.setdefault(row.key.game_id, []).append(row)
        self.assertEqual(sorted(games), list(range(1000, 1000 + 1024)))
        self.assertEqual(self.base_result.games, 1024)
        cut = 0
        for game, trajectory in games.items():
            trajectory.sort(key=lambda r: r.logical_tick)
            self.assertEqual({r.key.seat for r in trajectory}, {ex.learner_seat(game)})
            self.assertEqual([r.logical_tick for r in trajectory], list(range(len(trajectory))))
            self.assertEqual(trajectory[0].boundary, "TEAM_SELECTION")
            self.assertEqual([r.done for r in trajectory], [False] * (len(trajectory) - 1) + [True])
            self.assertLessEqual(len(trajectory), MAX_STEPS)
            self.assertTrue(all(r.bootstrap == 0.0 for r in trajectory))  # no truncated trajectory: done ends each
            self.assertIn(trajectory[-1].reward, (-1.0, 0.0, 1.0))
            self.assertTrue(all(r.reward == 0.0 for r in trajectory[:-1]))
            cut += len(trajectory) == MAX_STEPS
        self.assertGreater(self.base_result.counters["cuts"], 0)  # a game at MAX_STEPS rows may also have ended
        self.assertLessEqual(self.base_result.counters["cuts"], cut)
        self.assertLess(cut, 1024)
        self.assertEqual(self.base_result.counters["rows"], len(rows))
        self.assertEqual(self.base_result.counters["games"], 1024)
        # The collector value is the network's value of the learner row.
        values = self.net.value(self.net.params, np.stack([r.obs for r in rows]))
        np.testing.assert_allclose(np.array([r.collector_value for r in rows]), values, rtol=1e-6, atol=1e-6)
        # Pairings by game id: the pool's teams, independent of environment order.
        pairs = ce.pairing_of(self.manifest, _pool(), np.arange(1000, 2024))
        self.assertEqual(pairs.shape, (1024, 2))
        self.assertEqual(ce.pairing_of(self.manifest, _pool(), [1001, 1000]).tolist(), pairs[1::-1].tolist())

    def test_refusals_and_a_failed_setup_leave_no_collection(self):
        from duoforge_learn import collect_expert as ce
        out = self.root / "refused"
        # The network must run on the manifest's device (P1: cpu); another platform is refused before any write.
        with mock.patch.object(ce, "device_platform", return_value="gpu"), \
                self.assertRaisesRegex(ce.Refusal, "device"):
            self.collect(out)
        self.assertFalse(out.exists())
        # A setup that fails before the first state save leaves no manifest or state: a fresh start is accepted
        # (it fails again here for the same injected cause, never as "a collection exists").
        for _ in range(2):
            with mock.patch.object(ce._Collection, "roots", side_effect=RuntimeError("injected setup failure")), \
                    self.assertRaisesRegex(RuntimeError, "injected"):
                self.collect(out)
            self.assertFalse((out / "manifest.json").exists())
            self.assertFalse((out / ce.STATE).exists())
            self.assertEqual(list((out / "shards").iterdir()), [])
        # Refusals are ValueErrors of their own type: an existing collection, a resume without state.
        with self.assertRaisesRegex(ce.Refusal, "exists"):
            self.collect(self.base)
        with self.assertRaisesRegex(ce.Refusal, "no collection state"):
            self.collect(self.root / "nothing", resume=True)
        self.assertTrue(issubclass(ce.Refusal, ValueError))

    def test_the_foe_source_is_left_out(self):
        """D0023's leave-foe-source-out (as arena.py): the teacher's belief of a game excludes its foe team's spread
        source, and nothing when the foe team is no source (an LL_ team)."""
        from duoforge_learn import collect_expert as ce
        from duoforge_search import expert as ex
        pool = _pool()
        for r in (0, 1):
            games = 1000 + 512 * r + np.arange(512)
            pairs = ce.pairing_of(self.manifest, pool, games)
            excluded = ce.exclusions(self.manifest, pool, SOURCES, r)
            self.assertEqual(len(excluded), 512)
            for e, game in enumerate(games):
                foe = pool.ids[int(pairs[e, 1 - ex.learner_seat(int(game))])]
                self.assertEqual(excluded[e], SOURCES.get(foe), (r, e, foe))
            self.assertEqual({type(x) for x in excluded}, {int, type(None)})  # sources and a non-source occur
            self.assertEqual(set(excluded) - {None}, {0, 1})
        self.assertNotEqual(ce.exclusions(self.manifest, pool, SOURCES, 0), ce.exclusions(self.manifest, pool,
                                                                                            SOURCES, 1))
        with self.assertRaisesRegex(ValueError, "source"):
            ce.exclusions(self.manifest, pool, {"A": "0"}, 0)

    def test_raw_draw_is_keyed_and_follows_the_full_policy(self):
        from duoforge_learn import collect_expert as ce
        from duoforge_search.expert_data import DecisionKey
        logp = np.full(1024, -np.inf, np.float32)
        ids, probs = np.array([5, 40, 700]), np.array([0.2, 0.5, 0.3])
        logp[ids] = np.log(probs).astype(np.float32)
        legal = np.isfinite(logp)
        n = 20000
        keys = [DecisionKey(g, g % 2, 3 + g % 5) for g in range(n)]
        rows = np.broadcast_to(logp, (n, 1024))
        actions, logps = ce.raw_draws(rows, np.broadcast_to(legal, (n, 1024)), keys, seed=7)
        self.assertEqual(set(actions.tolist()) - set(ids.tolist()), set())
        for a, p in zip(ids, np.exp(logp[ids].astype(np.float64))):
            count = int((actions == a).sum())
            self.assertLessEqual(abs(count - n * p), 4 * math.sqrt(n * p * (1 - p)), (a, count))
        np.testing.assert_array_equal(logps, logp[actions].astype(np.float64))
        # Keyed: the draw of a key depends neither on the other rows of its batch nor on their order.
        order = np.random.default_rng(3).permutation(n)[:997]
        for chunk in np.array_split(order, 7):
            got, got_logp = ce.raw_draws(rows[chunk], np.broadcast_to(legal, (chunk.size, 1024)),
                                         [keys[i] for i in chunk], seed=7)
            np.testing.assert_array_equal(got, actions[chunk])
            np.testing.assert_array_equal(got_logp, logps[chunk])
        # The inverse CDF over ascending ids of the raw word's u = word / 2**64; another seed draws otherwise.
        from duoforge_search.expert_data import selection_word
        for key, action in zip(keys[:50], actions[:50]):
            u = selection_word(key, 7, domain="raw") / 2 ** 64
            cdf = np.cumsum(np.exp(logp[ids].astype(np.float64)))
            self.assertEqual(int(action), int(ids[np.searchsorted(cdf, u * cdf[-1], side="right")]))
        other, _ = ce.raw_draws(rows[:200], np.broadcast_to(legal, (200, 1024)), keys[:200], seed=8)
        self.assertFalse(np.array_equal(other, actions[:200]))
        # One legal action: FORCED with logp exactly 0; an empty or nonfinite legal row raises.
        one = np.full(1024, -np.inf, np.float32)
        one[9] = 0.0
        a, lp = ce.raw_draws(one[None], np.isfinite(one)[None], keys[:1], seed=7)
        self.assertEqual((int(a[0]), float(lp[0])), (9, 0.0))
        with self.assertRaisesRegex(ValueError, "no legal"):
            ce.raw_draws(one[None], np.zeros((1, 1024), bool), keys[:1], seed=7)
        bad = logp.copy()
        bad[40] = np.nan
        with self.assertRaisesRegex(ValueError, "finite"):
            ce.raw_draws(bad[None], legal[None], keys[:1], seed=7)
        # u = word / 2**64 rounds to 1.0 for the top words: the inverse CDF's limit, the last id with positive mass
        # (a legal id whose mass underflows to 0 after it is never drawn).
        from duoforge_search import expert_data as ed
        tail = logp.copy()
        tail[900] = -1000.0  # legal, exp() == 0 in float64
        with mock.patch.object(ed, "selection_word", return_value=2 ** 64 - 1):
            a, lp = ce.raw_draws(tail[None], np.isfinite(tail)[None], keys[:1], seed=7)
        self.assertEqual((int(a[0]), float(lp[0])), (700, float(logp[700])))
        # The full legal distribution of a pair row is Model.full_joint_log_probs; a preview row is the team head.
        import jax
        from duoforge_learn import policy
        from python.tests.test_learn_v2 import _scenes
        model = policy.make(policy.v2_config("S"))
        params = model.init(jax.random.PRNGKey(7))
        _, turn = _scenes()
        obs, slots, mask = (x[:6] for x in turn)
        is_team = np.zeros(6, bool)
        is_team[2] = True
        pairs, team, value = ce.distributions(model, params, obs, slots, mask)
        full = np.asarray(model.full_joint_log_probs(params, obs[~is_team], slots[~is_team], mask[~is_team]))
        legal_rows = mask[~is_team].reshape(5, -1)
        self.assertTrue(np.all(pairs[~is_team][~legal_rows] == -np.inf))
        np.testing.assert_allclose(pairs[~is_team][legal_rows], full[legal_rows], rtol=1e-6, atol=1e-6)
        logp_pairs, logp_team, v = (np.asarray(x) for x in model.apply(params, obs, slots, mask))
        np.testing.assert_array_equal(team[2], logp_team[2])
        np.testing.assert_array_equal(value, v)

    def test_resume_at_a_round_boundary_equals_uninterrupted(self):
        from duoforge_learn import collect_expert as ce
        out = self.root / "resumed"
        stopped = self.collect(out, stop=StopInRound(out / "shards", 1))
        self.assertFalse(stopped.complete)
        partial = self.files(out)
        self.assertTrue(any(n.startswith("round-0001-") for n in partial))  # the interrupted round's shard
        state = ce.read_state(out)
        self.assertEqual(state["next_round"], 1)
        # The teacher checkpoint of the boundary binds round 1's own exclusions (its pairings differ from round 0's).
        teacher = __import__("json").loads(state["teacher"])
        self.assertEqual(teacher["search"]["exclude_teams"], ce.exclusions(self.manifest, _pool(), SOURCES, 1))
        self.assertNotEqual(teacher["search"]["exclude_teams"], ce.exclusions(self.manifest, _pool(), SOURCES, 0))
        with self.assertRaisesRegex(ValueError, "resume"):
            self.collect(out, resume=True, source_ids={"A": 0})
        # Anything other than the run's own manifest and configuration is refused.
        with self.assertRaisesRegex(ValueError, "resume"):
            self.collect(out, resume=True, max_steps=MAX_STEPS + 1)
        with self.assertRaisesRegex(ValueError, "resume"):
            self.collect(out, resume=True, label_limit=LABELS + 1)
        with self.assertRaisesRegex(ValueError, "exists"):
            self.collect(out)  # a fresh start never writes over a collection
        resumed = self.collect(out, resume=True)
        self.assertTrue(resumed.complete)
        self.assertEqual(self.files(out), self.files(self.base))
        self.assertEqual(resumed.counters, self.base_result.counters)
        self.assertEqual(ce.read_state(out)["cursor"], ce.read_state(self.base)["cursor"])
        # The interrupted round's shards were set aside, not read as data.
        self.assertTrue(any((out / "discarded").rglob("round-0001-*.json")))
        # A finished collection resumes to nothing new.
        again = self.collect(out, resume=True)
        self.assertEqual((again.complete, again.counters), (True, self.base_result.counters))
        self.assertEqual(self.files(out), self.files(self.base))

    def test_admission_and_statuses(self):
        from duoforge_search import expert as ex, expert_data as ed
        rows = self.rows(self.base)
        status = ed.RowStatus
        seen = {s: 0 for s in status}
        games = {}
        for row in rows:
            seen[row.status] += 1
            games.setdefault(row.key.game_id, []).append(row)
            self.assertEqual(row.key.seat, ex.learner_seat(row.key.game_id))  # opponent rows are never stored
            legal = int(np.count_nonzero(row.legal_mask))
            if not row.requested:
                self.assertIs(row.status, status.UNREQUESTED)
                continue
            self.assertEqual(row.status is status.FORCED, legal == 1)
            eligible = row.boundary in ed.DECISION_BOUNDARIES and legal >= 2
            if row.boundary == "TEAM_SELECTION":
                self.assertIs(row.status, status.UNSELECTED)
                self.assertEqual(legal, 360)
            elif eligible and ed.is_selected(row.key, self.manifest.seed):
                self.assertIn(row.status, (status.TARGET, status.PUBLIC_REFUSAL, status.WORK_EXHAUSTED,
                                           status.CAP_RAW))
            elif eligible:
                self.assertIs(row.status, status.UNSELECTED)
            if row.status is status.TARGET:
                self.assertIsNotNone(row.sparse_policy)
                self.assertIn(row.raw_action, row.sparse_policy.ids.tolist())
            else:
                self.assertIsNone(row.sparse_policy)
        # Every status the test must see occurs, and the cap holds.
        for s in (status.TARGET, status.UNSELECTED, status.CAP_RAW, status.FORCED, status.UNREQUESTED):
            self.assertGreater(seen[s], 0, s)
        admitted = seen[status.TARGET] + seen[status.PUBLIC_REFUSAL] + seen[status.WORK_EXHAUSTED]
        self.assertLessEqual(seen[status.TARGET], LABELS)
        counters = self.base_result.counters
        self.assertEqual((counters["targets"], counters["capped"], counters["forced"], counters["admitted"],
                          counters["public_refusals"], counters["work_exhausted"]),
                         (seen[status.TARGET], seen[status.CAP_RAW], seen[status.FORCED], admitted,
                          seen[status.PUBLIC_REFUSAL], seen[status.WORK_EXHAUSTED]))
        self.assertEqual(counters["selected"], admitted + seen[status.CAP_RAW])
        self.assertEqual(counters["eligible"], sum(
            r.requested and r.boundary in ed.DECISION_BOUNDARIES and np.count_nonzero(r.legal_mask) >= 2
            for r in rows))
        # A capped game stays raw for the rest of the collection: no admitted row after its first CAP_RAW.
        capped_games = 0
        for game, trajectory in games.items():
            trajectory.sort(key=lambda r: r.logical_tick)
            first = next((i for i, r in enumerate(trajectory) if r.status is status.CAP_RAW), None)
            if first is None:
                continue
            capped_games += 1
            self.assertFalse([r for r in trajectory[first:] if r.admitted], game)
        self.assertGreater(capped_games, 0)
        # The behaviour likelihood of a raw row is the network's full-legal log-probability of its action.
        raw = next(r for r in rows if r.status is status.UNSELECTED and r.boundary == "TURN")
        pair = self.net.apply(self.net.params, raw.obs[None], raw.slots[None], raw.legal_mask[None])[0][0]
        self.assertAlmostEqual(raw.behavior_logp, float(pair[raw.action]), delta=1e-5)


class Cli(unittest.TestCase):
    """The CLI with a real (untrained) checkpoint standing in for params-49333 and a manifest carrying exactly the
    hashes the CLI computes: the init file, the canonical model configuration, the context's ids, the pool (M12's
    expert_eval.pool_sha256 of the default Teams A and B) and the pinned spread table."""

    def setUp(self):
        import hashlib
        import json
        import jax
        from duoforge_learn import checkpoint, policy
        from duoforge_search import expert_eval, honest
        self.tmp = tempfile.TemporaryDirectory(prefix="duoforge-collect-cli-")
        self.dir = Path(self.tmp.name)
        cfg = policy.v2_config("S")
        names = list(features.feature_names(4))  # P1 pins encoder 4 (params-49333's layout)
        params = policy.make(cfg, names).init(jax.random.PRNGKey(5))
        self.init = self.dir / "params-other.npz"
        checkpoint.save(self.init, params, {"model": cfg, "encoder": 4, "features": names,
                                            "slot_features": list(features.SLOT_FEATURE_NAMES),
                                            "data": {"kind": "pool"}, "teams": {}, "update": 0, "decisions": 0,
                                            "ids": {}})

        def canonical(value):
            return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            ids, belief = canonical(checkpoint.ids_of(ctx)), honest.spread_table(ctx)[2]["sha256"]
        self.right = dataclasses.replace(
            _manifest(), checkpoint_hash=hashlib.sha256(self.init.read_bytes()).hexdigest(), model_hash=canonical(cfg),
            ids_hash=ids, belief_hash=belief, pool_hash=expert_eval.pool_sha256(teams.TeamPool.from_setups(
                ("A", "B"), duoforge.reference_setups([0])["sides"][0])))

    def tearDown(self):
        self.tmp.cleanup()

    def main(self, manifest, *extra):
        import contextlib
        import io
        from duoforge_learn import collect_expert as ce
        from duoforge_search import expert_data as ed
        path = self.dir / f"manifest-{len(list(self.dir.glob('manifest-*')))}.json"
        ed.write_manifest(path, manifest)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = ce.main(["--init", str(self.init), "--manifest", str(path), *extra])
        return code, err.getvalue()

    def test_cli_refusals_exit_2(self):
        repo = Path(__file__).resolve().parents[2]
        other = ["--allow-other-init", "--out", str(self.dir / "out")]
        r = self.right
        cases = {"inside the repository": (r, ["--out", str(repo / "collect-out")]),
                 "params-49333": (r, ["--out", str(self.dir / "out")]),
                 "the manifest pins checkpoint": (dataclasses.replace(r, checkpoint_hash="b" * 64), other),
                 "workers": (r, other + ["--workers", "8"]),
                 "the manifest pins model": (dataclasses.replace(r, model_hash="c" * 64), other),
                 "the manifest pins ids": (dataclasses.replace(r, ids_hash="d" * 64), other),
                 "the manifest pins pool": (dataclasses.replace(r, pool_hash="e" * 64), other),
                 "the manifest pins belief": (dataclasses.replace(r, belief_hash="f" * 64), other)}
        for cause, (manifest, extra) in cases.items():
            with self.subTest(cause):
                code, err = self.main(manifest, *extra)
                self.assertEqual(code, 2)
                self.assertIn(cause, err)
        self.assertFalse((self.dir / "out").exists())
        self.assertFalse((repo / "collect-out").exists())

    def test_cli_refusal_versus_crash_during_the_collection(self):
        """A refusal of collect's own pre-run checks exits 2; any other error inside the collection is a crash and
        propagates (exit 1), never a refusal."""
        from duoforge_learn import collect_expert as ce
        other = ["--allow-other-init", "--out", str(self.dir / "out")]
        with mock.patch.object(ce, "collect", side_effect=ce.Refusal("resume refused: injected")):
            code, err = self.main(self.right, *other)
        self.assertEqual(code, 2)
        self.assertIn("resume refused: injected", err)
        with mock.patch.object(ce, "collect", side_effect=ValueError("injected crash")), \
                self.assertRaisesRegex(ValueError, "injected crash"):
            self.main(self.right, *other)


if __name__ == "__main__":
    unittest.main()
