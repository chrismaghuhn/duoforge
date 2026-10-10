"""Visible search: raw equivalence, information safety, worlds and Arena CLI."""
import os
os.environ["JAX_PLATFORMS"] = "cpu"

import json
import hashlib
import ctypes
import tempfile
import unittest
from unittest import mock

import numpy as np

import duoforge
from duoforge import _layout, privileged, view
from duoforge_search import arena, belief, honest
from python.tests.test_search import _v2s
from python.tests import test_search as search_tests

C = _layout.CONSTANTS


class CanonicalReduction(unittest.TestCase):
    def test_roundoff_at_vertex_is_certified_before_recording(self):
        a = np.array([[0.0, 0.0], [1.0, 1.0]])
        solution = honest.matrix.Solution(np.array([1e-16, 1 - 1e-16]), np.array([1.0, 0.0]), 1.0, False)
        honest.matrix.certify(a, solution.x, solution.y)
        with mock.patch.object(honest.matrix, "solve", return_value=solution):
            _, record = honest.reduce(a[None], [1], [[1, 0]], [0, 1], 0.5, 0.5, oracle=True)
        self.assertEqual(record["x"], [0.0, 1.0])
        honest.matrix.bayes_certify(a[None], [1], np.array(record["x"]), [np.array(record["ys"][0])])
        _, mixed = honest.reduce(np.array([[[1., -1.], [-1., 1.]]]), [1], [[0.5, 0.5]], [0, 1], 0.5, 0.5)
        np.testing.assert_array_equal(mixed["x"], [0.5, 0.5])

    def test_small_real_probability_survives_failed_vertex_certificate(self):
        a = np.array([[0., 1e16], [1., -1.]])
        solution = honest.matrix.Solution(np.array([2e-16, 1 - 2e-16]), np.array([1 - 1e-16, 1e-16]), 1., True)
        honest.matrix.certify(a, solution.x, solution.y)
        with mock.patch.object(honest.matrix, "solve", return_value=solution):
            _, record = honest.reduce(a[None], [1], [[1, 0]], [0, 1], 0.5, 0.5, oracle=True)
        np.testing.assert_array_equal(record["x"], solution.x)
        np.testing.assert_array_equal(record["ys"][0], solution.y)


class PublicCauses(unittest.TestCase):
    def test_every_public_cause_bit_has_a_name(self):
        # visible_causes names the library's refusal causes; a DUOFORGE_PUBLIC_CAUSE_* bit without a name would vanish
        # into the unnamed "public_record_unsupported" (Substitute, decision 0032 step G60, among them)
        bits = {v for k, v in C.items() if k.startswith("DUOFORGE_PUBLIC_CAUSE_")}
        self.assertEqual({bit for bit, _ in honest._CAUSES}, bits)
        self.assertIn((C["DUOFORGE_PUBLIC_CAUSE_SUBSTITUTE"], "substitute"), honest._CAUSES)
        self.assertIn((C["DUOFORGE_PUBLIC_CAUSE_TEMP_FORME"], "temp_forme"), honest._CAUSES)
        self.assertIn((C["DUOFORGE_PUBLIC_CAUSE_RAISED_THIS_TURN"], "raised_this_turn"), honest._CAUSES)
        self.assertIn((C["DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY"], "turn_history"), honest._CAUSES)


class HonestSearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, cls.params = _v2s()

    def make(self, ctx, k=2, rule="mix", table=None, excluded=None, lam=0.5):
        table = table or belief.SpreadTable.from_sides(duoforge.reference_setups([0])["sides"].reshape(-1))
        with duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
            mask = int(b.observe_ext()[0, 0]["supported"])
        return honest.Honest(ctx, self.model, self.params, 4, mask, k=k, m=2, s=2, rule=rule,
                             capacity=16, workers=2, table=table, exclude_teams=excluded, lam=lam)

    def preview(self, search, roots, seat=0):
        return search.decide(roots, list(range(roots.envs)), [seat] * roots.envs,
                             [123] * roots.envs, [False] * roots.envs)

    def start_turn(self, roots):
        roots.query_factored()
        choices = np.zeros((roots.envs, 2), _layout.FACTORED_CHOICE)
        choices["picks"][:, :, :4] = np.arange(4, dtype=np.uint8)
        roots.step_factored(choices)
        roots.query_factored()

    def test_hidden_roots_give_exactly_same_decision(self):
        # Visible counters are refused, so this searched-world test varies spreads, bench order and RNG instead.
        for seat in (0, 1):
            with self.subTest(seat=seat), duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                    duoforge.Batch(ctx, np.repeat(duoforge.reference_setups([0]), 2), 2, 42) as b, \
                    self.make(ctx) as search:
                self.preview(search, b, seat)
                self.start_turn(b)
                v, st = b.public(np.full(2, seat, np.uint32))
                self.assertFalse(st.any())
                h = view.hypotheses(2)
                h[0] = privileged.hypothesis(b, 0, seat)
                h[1] = h[0]
                h[1]["stat_points"] = 0
                h[1]["pick_order"][2:4] = h[0]["pick_order"][2:4][::-1]
                self.assertFalse(b.from_view(np.repeat(v[:1], 2), h).any())
                reseed = b._lib.duoforge_battle_reseed
                reseed.restype = ctypes.c_uint32
                reseed.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64)
                for e in range(2):
                    self.assertEqual(reseed(ctx.handle, b._battle(e), 100 + e, 10 + e), 0)
                v, st = b.public(np.full(2, seat, np.uint32))
                self.assertEqual(v[0].tobytes(), v[1].tobytes())
                with mock.patch.object(privileged, "hypothesis", side_effect=AssertionError("privileged")), \
                        mock.patch.object(b._lib, "duoforge_battle_hypothesis", side_effect=AssertionError("direct privileged ABI")), \
                        mock.patch.object(b, "encode", side_effect=AssertionError("true root bytes")):
                    actions, records = search.decide(b, [0, 1], [seat, seat], [456, 456], [False, False])
                self.assertEqual(actions[0], actions[1])
                self.assertEqual([r["kind"] for r in records], ["searched", "searched"])
                for name in ("own_pairs", "foe_pairs", "tables", "x", "ys", "pi_X", "outcomes"):
                    self.assertEqual(records[0][name], records[1][name], name)
                np.testing.assert_array_equal(search.last[0]["samples"], np.tile(np.arange(2), 4))

    def test_k_one_is_raw_for_all_rules(self):
        for rule in honest.RULES:
            with self.subTest(rule=rule), duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                    duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, self.make(ctx, 1, rule) as search:
                self.preview(search, b)
                self.start_turn(b)
                obs, slots, masks = b.query_encoded(4, search.ext_supported)
                logp = np.asarray(self.model.apply(self.params, obs[:, 0], slots[:, 0], masks[:, 0])[0])
                expected = int(np.argmax(logp[0]))
                with mock.patch.object(search, "_hypotheses", side_effect=AssertionError("no worlds for K=1")):
                    actions, records = search.decide(b, [0], [0], [456], [False])
                self.assertEqual(int(actions[0]), expected)
                self.assertEqual(records[0]["kind"], "raw")

    def test_sources_and_exclusion(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            table, ids, info = honest.spread_table(ctx)
            self.assertEqual(info["sha256"], table.sha256())
            self.assertGreater(info["sets"], 18)
            self.assertTrue({"A", "B", "C"} <= set(ids))
            self.assertTrue(all(t in ("A", "B", "C") or t.startswith("PP_") for t in ids))
            sampled = belief.Belief(table).sample([(int(table.species[0]), int(table.nature[0]), int(table.item[0]))],
                                                    16, 42, 1, ids["A"])
            _, rows = table.candidates(int(table.species[0]), int(table.nature[0]), int(table.item[0]), ids["A"])
            self.assertFalse((table.team[rows] == ids["A"]).any())
            self.assertEqual(sampled["stat_points"].shape, (16, 6, 6))

    def test_missing_history_is_counted_and_errors_stop(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, self.make(ctx) as search:
            self.start_turn(b)
            _, records = search.decide(b, [0], [0], [456], [False])
            self.assertEqual(records[0]["kind"], "unreconstructible")
            self.assertIn("missing team-preview", records[0]["reason"])
            self.assertEqual(arena.diagnostics(records, 1)["decisions"]["unreconstructible"], 1)
            with self.assertRaisesRegex(ValueError, "unique valid"):
                search.decide(b, [0, 0], [0, 0], [1, 1], [False, False])

    def test_pivot_records_and_queue_sampling(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, np.resize(duoforge.reference_setups([0, 1, 2, 3]), 8), 3, 42) as b, \
                self.make(ctx, 1) as search:
            policy = duoforge.RandomPolicy(71, 8)
            counted = searched = 0
            for _ in range(160):
                b.query_factored()
                for p in (0, 1):
                    envs = np.flatnonzero(b.requests["requested"][:, p])
                    if not envs.size:
                        continue
                    pivot = b.requests["boundary_kind"][envs, p] == C["DUOFORGE_BOUNDARY_PIVOT"]
                    search.k = 2 if pivot.any() else 1
                    _, records = search.decide(b, envs, [p] * len(envs), np.arange(len(envs), dtype=np.uint64),
                                               np.zeros(len(envs), bool))
                    for r in records:
                        if r["boundary"] == "PIVOT":
                            counted += 1
                            self.assertIn(r["kind"], ("forced", "searched", "unreconstructible"))
                            if r["kind"] == "searched":
                                searched += 1
                                self.assertEqual(r["foe_pairs"], [[-1], [-1]])
                                players = np.full(b.envs, p, np.uint32)
                                public, st = b.public(players)
                                self.assertEqual(int(st[r["env"]]), 0)
                                current = public[r["env"]:r["env"] + 1].reshape(())
                                mask = duoforge.queue_mask(ctx, search.history[b][(r["env"], p)]["turn_start"], current)
                                self.assertEqual(len(r["queue_pairs"]), 2)
                                self.assertTrue(all(mask.reshape(-1)[x] for x in r["queue_pairs"]))
                                history = search.history[b][(r["env"], p)]
                                saved_start = history["turn_start"].copy()
                                history["turn_start"]["turn"] -= 1
                                with mock.patch.object(duoforge, "queue_mask", side_effect=AssertionError("stale C query")):
                                    _, fallback = search.decide(b, [r["env"]], [p], [r["key"]], [False])
                                self.assertEqual(fallback[0]["kind"], "unreconstructible")
                                self.assertIn("turn-start", fallback[0]["reason"])
                                history["turn_start"] = saved_start
                b.step_factored(policy.choose_factored(b))
                b.reset_terminal()
                if counted >= 4 and searched:
                    break
            self.assertGreaterEqual(counted, 4)
            self.assertGreater(searched, 0)

    def test_pinned_abc_decisions(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            pool = duoforge.teams.load(ctx, ["A", "B", "C"])
            table = belief.SpreadTable.from_sides(pool.sides)
            with duoforge.Batch(ctx, pool.setups(np.array([0, 1, 2]), np.array([1, 2, 0])), 2, 42) as roots, \
                    self.make(ctx, table=table, excluded=[1, 2, 0]) as search:
                self.preview(search, roots)
                self.start_turn(roots)
                actions, records = search.decide(roots, [0, 1, 2], [0, 0, 0], [456, 457, 458], [False] * 3)
                self.assertEqual(actions.tolist(), [103, 289, 352])
                for i, r in enumerate(records):
                    self.assertEqual(r["own_pairs"], PINNED_OWN[i])
                    self.assertEqual(r["foe_pairs"], [PINNED_FOE[i]] * 2)
                    last = search.last[i]
                    raw = last["hypotheses"].tobytes() + last["choices"].tobytes() + last["samples"].astype("<u8").tobytes()
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), PINNED_WORDS[i])
                    np.testing.assert_allclose(r["tables"], PINNED_TABLES[i], rtol=0, atol=1e-6)
                    self.assertEqual(r["exclude_team"], [1, 2, 0][i])

    def test_engine_and_solver_failures_keep_public_reproduction(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, self.make(ctx) as search:
            self.preview(search, b)
            self.start_turn(b)
            from duoforge_search.errors import SearchError
            with mock.patch.object(search.worlds, "from_view", return_value=np.full(2, 8, np.uint32)):  # C ABI E_INVARIANT
                with self.assertRaises(SearchError) as caught:
                    search.decide(b, [0], [0], [456], [False])
                self.assertIn("E_INVARIANT", str(caught.exception))
                self.assertIn("public_view", caught.exception.reproduction)
                self.assertNotIn("root", caught.exception.reproduction)
                for name in ("search_seed", "exclude_team", "preview", "turn_start"):
                    self.assertIn(name, caught.exception.reproduction)
                self.assertIsNotNone(caught.exception.reproduction["preview"])
            with mock.patch.object(honest.matrix, "solve_bayes", side_effect=SearchError("certificate failed")):
                with self.assertRaises(SearchError) as caught:
                    search.decide(b, [0], [0], [456], [False])
                self.assertIn("tables", caught.exception.reproduction)

    def test_nex_share_worlds_and_cutoff_uses_engine_results(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, self.make(ctx) as search:
            self.preview(search, b)
            self.start_turn(b)
            first = None
            for rule in honest.RULES:
                search.rule = rule
                actions, records = search.decide(b, [0], [0], [456], [False])
                r = records[0]
                self.assertEqual(int(actions[0]), r["own_pairs"][r["outcomes"][rule]])
                if first is None:
                    first = r["tables"]
                self.assertEqual(r["tables"], first)
                expected_mix = 0.5 * np.array(r["x"])
                expected_mix[r["outcomes"]["ev"]] += 0.5
                np.testing.assert_array_equal(r["pi_X"], expected_mix)
            _, records = search.decide(b, [0], [0], [456], [True])
            self.assertGreater(records[0]["leaves"]["cut_off"], 0)
            self.assertTrue(np.isin(np.array(records[0]["tables"]), [-1, 0, 1]).all())

    def test_respreads_keep_world_words_and_other_worlds(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, self.make(ctx) as search:
            self.preview(search, b)
            self.start_turn(b)
            build = search._build
            calls = []

            def refused_once(record, hypotheses):
                calls.append(hypotheses.copy())
                statuses = build(record, hypotheses)
                if len(calls) == 2:  # first current-root world 0 contradicts its HP display
                    statuses[0] = C["DUOFORGE_E_INVALID_ARGUMENT"]
                return statuses

            with mock.patch.object(search, "_build", side_effect=refused_once), \
                    mock.patch.object(search.belief, "sample", wraps=search.belief.sample) as sample:
                _, records = search.decide(b, [0], [0], [456], [False])
                self.assertEqual(records[0]["respreads"], 1)
                self.assertEqual(sample.call_count, 2)
                np.testing.assert_array_equal(sample.call_args.args[-1], [[1] * 6, [0] * 6])
            for name in ("hp", "sleep", "confusion", "charge_target"):
                np.testing.assert_array_equal(calls[0][name], calls[2][name])
            np.testing.assert_array_equal(calls[0]["stat_points"][1], calls[2]["stat_points"][1])

    def test_visible_counter_fallbacks_are_public_and_counted_per_cause(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, np.repeat(duoforge.reference_setups([0]), 2), 2, 42) as b, self.make(ctx) as search:
            self.preview(search, b)
            self.start_turn(b)
            decode = b._lib.duoforge_battle_decode
            decode.restype = ctypes.c_uint32
            decode.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t)
            original = b.encode(0)
            for cause in ("visible_sleep", "visible_confusion"):
                for e in range(2):
                    # Privileged codec fixtures only: schema-3 offsets, no live rule implementation.
                    raw = np.frombuffer(original, np.uint8).copy()
                    if cause == "visible_sleep":
                        raw[215 + 109 + 27] = C["DUOFORGE_AILMENT_SLEEP"]
                        raw[215 + 109 + 28] = 1 + e
                    else:
                        raw[215 + 15 + 15] = 1 + e
                    self.assertEqual(decode(ctx.handle, b._battle(e), raw.ctypes.data, raw.size), 0)
                with mock.patch.object(b._lib, "duoforge_battle_hypothesis", side_effect=AssertionError("privileged ABI")):
                    actions, records = search.decide(b, [0, 1], [0, 0], [456, 456], [False, False])
                self.assertEqual(actions[0], actions[1])
                self.assertTrue(all(r["kind"] == "unreconstructible" and r["causes"] == [cause] for r in records))
                stats = arena.diagnostics(records, 2)
                self.assertEqual(stats["unreconstructible_by_cause"][cause], {"decisions": 2, "share_of_decisions": 1.0})

    def test_stale_turn_start_counts_as_unreconstructible(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, self.make(ctx) as search:
            self.preview(search, b)
            self.start_turn(b)
            v, _ = b.public(np.zeros(1, np.uint32))
            record = v[:1].reshape(()).copy()
            history = search.history[b][(0, 0)]
            history["turn_start"] = record.copy()
            record["turn"] += 1
            record["boundary"] = C["DUOFORGE_BOUNDARY_PIVOT"]
            costs = {k: 0. for k in ("public_records", "world_builds", "team_head", "network")}
            with mock.patch.object(duoforge, "queue_mask", side_effect=AssertionError("stale record must not reach C")):
                with self.assertRaisesRegex(honest.Unreconstructible, "stale"):
                    search._hypotheses(record, b.observations[0, 0], history, 1, None, costs)

    def test_redraw_bound_stops_with_complete_reproduction(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, self.make(ctx) as search:
            self.preview(search, b)
            self.start_turn(b)
            build = search._build
            calls = 0
            def reject_root(record, h):
                nonlocal calls
                if int(record["boundary"]) == C["DUOFORGE_BOUNDARY_TEAM_SELECTION"]:
                    return build(record, h)
                calls += 1
                return np.full(2, C["DUOFORGE_E_INVALID_ARGUMENT"], np.uint32)
            with mock.patch.object(search, "_build", side_effect=reject_root):
                with self.assertRaisesRegex(honest.SearchError, "256") as stopped:
                    search.decide(b, [0], [0], [456], [False])
            self.assertEqual(calls, 256)
            for name in ("public_view", "preview", "turn_start", "exclude_team", "search_seed"):
                self.assertIn(name, stopped.exception.reproduction)


class HonestArena(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        search_tests.ArenaCli.setUpClass()

    @classmethod
    def tearDownClass(cls):
        search_tests.ArenaCli.tearDownClass()

    def test_cli_honest_and_oracle_mix(self):
        run = search_tests.ArenaCli.run_dir
        with tempfile.TemporaryDirectory() as tmp:
            for mode in ("honest", "oracle"):
                out = os.path.join(tmp, mode)
                self.assertEqual(arena.main(["--run-dir", run, "--out", out, "--checkpoint", "params-400",
                                             "--search", mode, "--agents", "X", "--lam", "0.25", "--km", "2x2",
                                             "--s", "2", "--capacity", "16", "--workers", "2", "--max-steps", "3",
                                             "--resamples", "10"]), 0)
                with open(os.path.join(out, "summary.json"), encoding="utf-8") as f:
                    summary = json.load(f)
                self.assertEqual(summary["conditions"]["search"], mode)
                self.assertEqual(summary["conditions"]["lam"], 0.25)
                self.assertIn("X-k2m2s2-vs-R", summary["configs"])
                if mode == "honest":
                    self.assertNotIn("oracle", summary["conditions"])
                    self.assertEqual(len(summary["conditions"]["belief"]["sha256"]), 64)
                    self.assertIn("cost_ms", summary["configs"]["X-k2m2s2-vs-R"]["timing"])
                    with open(os.path.join(out, "raw", "X-k2m2s2-vs-R-decisions.jsonl"), encoding="utf-8") as f:
                        searched = [r for line in f if (r := json.loads(line))["kind"] == "searched"]
                    self.assertTrue(searched)
                    self.assertTrue(all(r["exclude_team"] in (0, 1, 2) for r in searched))
                    self.assertTrue(all(r["lam"] == 0.25 for r in searched))
                    for r in searched:
                        target = 0.25 * np.array(r["x"])
                        target[r["outcomes"]["ev"]] += 0.75
                        np.testing.assert_array_equal(r["pi_X"], target)


PINNED_OWN = [[103, 97], [289, 295], [358, 352]]
PINNED_FOE = [[261, 293], [165, 162], [171, 165]]
PINNED_WORDS = ["c69873953e3ce225253ca6a7f968c4093c82d78a8a9114cb00ce2f4a58b0d922",
                "da37e4bece3570a2b0e0276c93bdfddbff693f4bb13bae0df718304152f6f20f",
                "9574ab04ae002e53f008d798e64bc268174003f492f75daadfe5a0e7c54e37c1"]
PINNED_TABLES = [
    [[[-0.0007553966715931892, -0.0004699230194091797], [-0.005582381505519152, -0.004870862700045109]],
     [[0.0002768551930785179, -0.0007560942322015762], [-0.004128935746848583, -0.005577234551310539]]],
    [[[0.0013917628675699234, 0.001984288915991783], [0.0006093308329582214, 0.0013067219406366348]],
     [[0.0020258380100131035, 0.0020160749554634094], [0.0013299547135829926, 0.0013069864362478256]]],
    [[[0.0012448998168110847, 0.0012224335223436356], [0.003726405091583729, 0.0037659434601664543]],
     [[0.0012306282296776772, 0.0012039029970765114], [0.0037127695977687836, 0.0029854867607355118]]],
]


if __name__ == "__main__":
    unittest.main()
