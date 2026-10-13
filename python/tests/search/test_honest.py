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
from duoforge import _layout, features, privileged, state_layout, view

from python.tests.support._pivot_fixture import SETUP, play_to_pivot
from duoforge_search import arena, belief, honest, lookahead, matrix
from python.tests.search.test_search import _v2s
from python.tests.search import test_search as search_tests

C = _layout.CONSTANTS
PIVOT_STEPS = 160  # lockstep steps of the PIVOT record test
WORLDS = 64  # worlds per search in the visible-sleep case (the S = 2 split needs many)


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

    def make(self, ctx, k=2, rule="mix", table=None, excluded=None, lam=0.5, species_prior=False, model=None,
             foe_net=None, s=2, **extra):
        table = table or belief.SpreadTable.from_sides(duoforge.reference_setups([0])["sides"].reshape(-1))
        with duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
            mask = int(b.observe_ext()[0, 0]["supported"]) & features.version_features(4)  # encoder 4 (0050)
        options = dict(extra)
        if foe_net is not None:
            options["foe_net"] = foe_net
        return honest.Honest(ctx, model or self.model, self.params, 4, mask, k=k, m=2, s=s, rule=rule,
                             capacity=16, workers=2, table=table, exclude_teams=excluded, lam=lam,
                             species_prior=species_prior, **options)

    def encoder3_net(self, ctx, key=11):
        """(model, params, encoder, ext_supported) of an encoder-3 network with other weights (M11's BC priors are
        encoder 3)."""
        import jax
        from duoforge_learn import policy
        model = policy.make(policy.v2_config("S"), features.feature_names(3))
        with duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
            mask = int(b.observe_ext()[0, 0]["supported"]) & features.version_features(3)
        return model, model.init(jax.random.PRNGKey(key)), 3, mask

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
                        mock.patch.object(privileged, "step_events", side_effect=AssertionError("privileged")), \
                        mock.patch.object(b._lib, "duoforge_battle_hypothesis", side_effect=AssertionError("direct privileged ABI")), \
                        mock.patch.object(b._lib, "duoforge_battle_step_events", side_effect=AssertionError("direct privileged ABI")), \
                        mock.patch.object(b._lib, "duoforge_battle_clone", side_effect=AssertionError("direct privileged ABI")), \
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

    def test_live_spread_table_is_pinned(self):
        # Live play's belief (owner 2026-10-12): the spreads derived from Smogon's usage stats of Reg M-C (the committed
        # data/belief table, smogon_spreads: the highest rating cutoff with enough weight per species), the registry's
        # stated A/B/C and PP_ spreads for a species Smogon lacks; pinned by the table's hash. P1's and the evaluation's 79 SPREAD_SOURCES stay as they are.
        from pathlib import Path
        from duoforge import data as ddata
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            table, ids, info = honest.live_spread_table(ctx)
            self.assertEqual(info["sha256"], honest.LIVE_SPREAD_SHA256)
            registry = json.loads((Path(honest.__file__).resolve().parents[2] / "data/teams/index.json")
                                  .read_text(encoding="utf-8"))["teams"]
            self.assertEqual(set(ids), {r["id"] for r in registry if r["id"] in ("A", "B", "C") or r["id"].startswith("PP_")})
            self.assertTrue(set(honest.SPREAD_SOURCES) < set(ids))  # the registry's teams fill and leave themselves out
            toxapex = ddata.find(ctx, ddata.TABLE_SPECIES, "toxapex")
            level, rows = table.candidates(toxapex, 0, 0)
            self.assertLessEqual(level, 3)  # the species has a prior (MoccaOTS's Toxapex refused every decision)
            self.assertTrue((table.team[rows] == -1).all())  # from Smogon, not the registry
            self.assertGreater(info["smogon"]["species"], 200)
            with mock.patch.object(honest, "LIVE_SPREAD_SHA256", "0" * 64), \
                    self.assertRaisesRegex(honest.SearchError, "pinned"):
                honest.live_spread_table(ctx)

    def test_a_species_without_prior_draws_the_counted_fallback(self):
        # Owner 2026-10-12: with species_prior "count" a foe species without spreads in the table is drawn from the
        # belief's general levels (its nature over every species, else every spread) instead of refusing the decision;
        # every such species is named in the record, never silently.
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            other = belief.SpreadTable.from_sides(duoforge.reference_setups([2])["sides"].reshape(-1))  # no Politoed team
            own = belief.SpreadTable.from_sides(duoforge.reference_setups([0])["sides"].reshape(-1))
            for table, fallback in ((other, True), (own, False)):
                with self.subTest(fallback=fallback), \
                        duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, \
                        self.make(ctx, table=table, species_prior="count") as search:
                    self.preview(search, b)
                    self.start_turn(b)
                    _, records = search.decide(b, [0], [0], [456], [False])
                    self.assertEqual(records[0]["kind"], "searched")
                    foe = [int(m["species_id"]) for m in b.observations[0, 0]["sides"][1]["members"][:6]]
                    named = records[0]["spread_fallback"]
                    self.assertEqual(bool(named), fallback)
                    self.assertTrue(set(named) <= set(foe))
                    if fallback:
                        self.assertTrue(all(int(sp) not in set(table.species.tolist()) for sp in named))
            for bad in ("sometimes", np.bool_(True), 1, 1.0, None):
                with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "species_prior"):
                    self.make(ctx, species_prior=bad)

    def test_species_without_prior_is_refused_when_required(self):
        # Live play (owner, 2026-10-10): a foe species without a stated spread in the table is not drawn from the
        # belief's nature-only or table-wide fallback; the decision is refused with its cause and played raw (counted).
        # Off (P1, the arena), the fallback levels stay as they are.
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            other = belief.SpreadTable.from_sides(duoforge.reference_setups([2])["sides"].reshape(-1))  # no Politoed team
            for required, kind in ((True, "unreconstructible"), (False, "searched")):
                with self.subTest(required=required), \
                        duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, \
                        self.make(ctx, table=other, species_prior=required) as search:
                    self.preview(search, b)
                    self.start_turn(b)
                    _, records = search.decide(b, [0], [0], [456], [False])
                    self.assertEqual(records[0]["kind"], kind)
                    if required:
                        self.assertIn("no spread prior", records[0]["reason"])

    def test_a_redraw_past_the_species_prior_is_named_apart_from_no_prior(self):
        # Review of #339: a redraw raises the table level (draw: min_level = initial + redraw), so "no spread prior" is
        # decided from the first draw's level only. A species with only species-level spreads (level 3) is searched; a
        # world the public view refuses redraws it past level 3, which is its own named refusal, never "no spread prior".
        sides = duoforge.reference_setups([0])["sides"].reshape(-1)
        table = belief.SpreadTable.from_sides(sides)
        table.nature[:] = (table.nature + 1) % 25  # no stated nature matches: every foe member draws at level 3
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            for forced in (False, True):
                with self.subTest(forced=forced), \
                        duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, \
                        self.make(ctx, table=table, species_prior=True) as search:
                    self.preview(search, b)
                    self.start_turn(b)
                    real, refused = search._build, []

                    def build(record, h):
                        statuses = real(record, h)
                        if forced and int(record["boundary"]) == C["DUOFORGE_BOUNDARY_TURN"] and not refused:
                            refused.append(True)  # the turn record refuses world 0 once: its spreads are redrawn
                            statuses = statuses.copy()
                            statuses[0] = C["DUOFORGE_E_INVALID_ARGUMENT"]
                        return statuses

                    with mock.patch.object(search, "_build", side_effect=build):
                        _, records = search.decide(b, [0], [0], [456], [False])
                    if forced:
                        self.assertEqual(records[0]["kind"], "unreconstructible")
                        self.assertIn("redraw past the species prior", records[0]["reason"])
                        self.assertNotIn("no spread prior", records[0]["reason"])
                    else:
                        self.assertEqual(records[0]["kind"], "searched")

    def test_count_names_a_redraw_past_the_prior_apart_from_no_prior(self):
        # As True keeps the two refusals apart (#339), "count" names a species whose spreads a redraw exhausted
        # (spread_redrawn) apart from one without any spread (spread_fallback).
        sides = duoforge.reference_setups([0])["sides"].reshape(-1)
        table = belief.SpreadTable.from_sides(sides)
        table.nature[:] = (table.nature + 1) % 25  # no stated nature matches: every foe member draws at level 3
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, \
                self.make(ctx, table=table, species_prior="count") as search:
            self.preview(search, b)
            self.start_turn(b)
            real, refused = search._build, []

            def build(record, h):
                statuses = real(record, h)
                if int(record["boundary"]) == C["DUOFORGE_BOUNDARY_TURN"] and not refused:
                    refused.append(True)  # the turn record refuses world 0 once: its spreads are redrawn
                    statuses = statuses.copy()
                    statuses[0] = C["DUOFORGE_E_INVALID_ARGUMENT"]
                return statuses

            with mock.patch.object(search, "_build", side_effect=build):
                _, records = search.decide(b, [0], [0], [456], [False])
        self.assertEqual(records[0]["kind"], "searched")
        self.assertEqual(records[0]["spread_fallback"], [])
        self.assertTrue(records[0]["spread_redrawn"])

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
        def check_searched(b, search, r, p):
            # Since the view audit of 2026-10-10 a public PIVOT record has no move left to run (one with a move left is
            # refused: a silent flinch may be outstanding), so no foe command is sampled and neither the queue mask nor
            # the turn-start record is needed: a stale one and a queue mask that must not be queried leave it searched.
            self.assertEqual(r["foe_pairs"], [[-1], [-1]])
            public, st = b.public(np.full(b.envs, p, np.uint32))
            self.assertEqual(int(st[r["env"]]), 0)
            self.assertEqual(int(public[r["env"]]["foe_pending_mask"]), 0)
            self.assertEqual(r["queue_pairs"], [])
            history = search.history[b][(r["env"], p)]
            saved_start = history["turn_start"].copy()
            history["turn_start"]["turn"] -= 1
            with mock.patch.object(duoforge, "queue_mask", side_effect=AssertionError("no queue mask")):
                _, again = search.decide(b, [r["env"]], [p], [r["key"]], [False])
            self.assertEqual(again[0]["kind"], "searched")
            history["turn_start"] = saved_start

        counted = searched = refused = 0
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, np.resize(duoforge.reference_setups([0, 1, 2, 3]), 8), 3, 42) as b, \
                self.make(ctx, 1) as search:
            policy = duoforge.RandomPolicy(71, 8)
            for _ in range(PIVOT_STEPS):
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
                                check_searched(b, search, r, p)
                            elif r["kind"] == "unreconstructible":
                                refused += 1
                b.step_factored(policy.choose_factored(b))
                b.reset_terminal()
                if counted >= 4 and refused:
                    break
        self.assertGreaterEqual(counted, 4)
        self.assertGreater(refused, 0)  # PIVOTs with a move left are refused, not searched
        # Random play almost never reaches a public PIVOT (a Protect up and no move left): the scripted one.
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([SETUP]), 1, 43) as b, \
                self.make(ctx, 1) as search:
            keys = iter(range(100, 200))

            def observe(batch):  # the searcher's history: the team preview and the turn-start records
                for p in (0, 1):
                    if batch.requests["requested"][0, p]:
                        search.decide(batch, [0], [p], [next(keys)], [False])

            play_to_pivot(b, before_step=observe)
            search.k = 2
            _, records = search.decide(b, [0], [0], [7], [False])
            self.assertEqual(records[0]["boundary"], "PIVOT")
            self.assertEqual(records[0]["kind"], "searched")
            check_searched(b, search, records[0], 0)
            searched += 1
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
                    # G90 (hypothesis revision 3) changed two things in a hypothesis record and nothing else: its revision word (2 -> 3)
                    # and reserved2 -> trap_pick (4 zero bytes, filled only where a record shows a hidden partial trap: none in
                    # A/B/C at the turn start). trap_pick reads words 33..36 of the counter-based world words (belief.world_words:
                    # splitmix64 of seed, key, world and k, no stream), so no other draw moved. The pinned words, choices and
                    # samples stay as pinned: the revision is checked here and written back as 2 for the hash.
                    hypotheses = last["hypotheses"].copy()
                    self.assertTrue((hypotheses["revision"] == C["DUOFORGE_HYPOTHESIS_REVISION"]).all())
                    self.assertFalse(hypotheses["trap_pick"].any())
                    hypotheses["revision"] = 2  # DUOFORGE_HYPOTHESIS_REVISION_NO_TRAP, the revision of the pin
                    raw = hypotheses.tobytes() + last["choices"].tobytes() + last["samples"].astype("<u8").tobytes()
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

    def refuse_pairs(self, search, refuse, seat=0):
        """(patch, refused): while patch is active, a leaf whose seat's pair satisfies refuse(pair) returns the
        engine's E_UNSUPPORTED step status, as C reports a refused step; refused lists the forced count per chunk."""
        real, refused = search.leaves.expand, []

        def expand(*args):
            row, st, enc, other, res = real(*args)
            choices = args[-1]
            pairs = choices["slot"][:, seat, 0].astype(np.int64) * honest.lookahead.OPTIONS + choices["slot"][:, seat, 1]
            hit = np.array([refuse(int(x)) for x in pairs], bool)
            st = np.array(st, copy=True)
            st[hit] = C["DUOFORGE_E_UNSUPPORTED"]
            refused.append(int(hit.sum()))
            return row, st, enc, other, res

        return mock.patch.object(search.leaves, "expand", side_effect=expand), refused

    def test_refused_leaves_drop_their_own_candidate(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, self.make(ctx) as search:
            self.preview(search, b)
            self.start_turn(b)
            _, records = search.decide(b, [0], [0], [456], [False])
            base = records[0]
            self.assertEqual(base["kind"], "searched")
            self.assertEqual(base["leaves"]["refused"], 0)
            self.assertEqual(len(base["own_pairs"]), 2)
            dropped, kept = base["own_pairs"]
            patch, refused = self.refuse_pairs(search, lambda pair: pair == dropped)
            with patch:
                actions, records = search.decide(b, [0], [0], [456], [False])
            r = records[0]
            self.assertEqual(r["kind"], "searched")
            self.assertEqual(r["refused_pairs"], [dropped])
            self.assertEqual(r["own_pairs"], [kept])
            self.assertEqual(r["k"], 1)
            self.assertEqual(int(actions[0]), kept)
            self.assertEqual(r["choice"], kept)
            self.assertNotEqual(r["choice"], dropped)
            self.assertEqual(r["raw"], dropped)  # raw stays the network's first candidate
            self.assertTrue(r["changed"])
            self.assertGreater(sum(refused), 0)
            self.assertEqual(r["leaves"]["refused"], sum(refused))
            # Row 1's leaves are untouched by the forced refusals: its table is the baseline's row 1 exactly.
            np.testing.assert_array_equal(np.array(r["tables"]), np.array(base["tables"])[:, 1:, :])
            self.assertEqual(search.last[0]["tables"].shape, (search.s, 1, r["m"]))

    def test_every_leaf_refused_is_unreconstructible(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, self.make(ctx) as search:
            self.preview(search, b)
            self.start_turn(b)
            _, records = search.decide(b, [0], [0], [456], [False])
            raw = records[0]["raw"]
            patch, refused = self.refuse_pairs(search, lambda pair: True)
            with patch:
                actions, records = search.decide(b, [0], [0], [456], [False])
            r = records[0]
            self.assertEqual(r["kind"], "unreconstructible")
            self.assertEqual(r["reason"], "engine_refused_leaves")
            self.assertEqual(r["causes"], ["engine_refused_leaves"])
            self.assertEqual(int(actions[0]), raw)  # played raw and counted
            self.assertGreater(sum(refused), 0)

    def test_refused_drop_without_refusals_is_score(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, self.make(ctx) as search:
            self.preview(search, b)
            self.start_turn(b)
            drop_actions, drop = search.decide(b, [0], [0], [456], [False])
            drop_tables = search.last[0]["tables"].copy()
            real = search._decision
            with mock.patch.object(search, "_decision", side_effect=lambda *a, **kw: real(*a, **{**kw, "refused": "score"})):
                score_actions, score = search.decide(b, [0], [0], [456], [False])
            score_tables = search.last[0]["tables"].copy()
            self.assertEqual(drop[0]["kind"], "searched")
            np.testing.assert_array_equal(drop_actions, score_actions)
            self.assertEqual(drop[0]["refused_pairs"], [])
            self.assertNotIn("refused_pairs", score[0])
            np.testing.assert_array_equal(drop_tables, score_tables)
            # cost and time are wall-clock measurements; every other field of the record must match exactly.
            self.assertEqual({k: v for k, v in drop[0].items() if k not in ("refused_pairs", "cost", "time")},
                             {k: v for k, v in score[0].items() if k not in ("cost", "time")})

    def test_width_and_prune_must_be_named_settings(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            for bad in ({"width": "pairs"}, {"prune": True}, {"prune": "weak"}):
                with self.subTest(**bad), self.assertRaises(ValueError):
                    self.make(ctx, **bad)

    def test_slot_width_keeps_the_raw_pair_first_and_adds_each_slot_option(self):
        # #433, step 2w: the joint top k and every slot option's best pair; the first pair (raw) is the joint one's.
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, self.make(ctx) as joint, \
                self.make(ctx, width="slots") as slots:
            self.preview(joint, b)
            self.preview(slots, b)
            self.start_turn(b)
            _, (narrow,) = joint.decide(b, [0], [0], [456], [False])
            _, (wide,) = slots.decide(b, [0], [0], [456], [False])
            self.assertEqual((narrow["kind"], wide["kind"]), ("searched", "searched"))
            self.assertEqual(wide["raw"], narrow["raw"])
            self.assertEqual(wide["own_pairs"][0], narrow["own_pairs"][0])
            self.assertTrue(set(narrow["own_pairs"]) < set(wide["own_pairs"]))  # 2 joint pairs, then the slots' options
            self.assertEqual(wide["k"], len(wide["own_pairs"]))
            self.assertEqual(np.asarray(wide["table"]).shape[0], wide["k"])
            options = {pair // lookahead.OPTIONS for pair in wide["own_pairs"]}
            self.assertGreater(len(options), len({pair // lookahead.OPTIONS for pair in narrow["own_pairs"]}))
            self.assertNotIn("dominated_pairs", wide)

    def test_a_wide_table_above_the_lp_size_limit_stops_by_name(self):
        # width "slots" knows its own pairs only at the decision: a table above the limit is a named stop, never solved
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, self.make(ctx, width="slots") as wide:
            self.preview(wide, b)
            self.start_turn(b)
            with mock.patch.object(honest.matrix, "MAX_BAYES_CELLS", 100):  # built at 50 cells; its table has more
                with self.assertRaisesRegex(honest.SearchError, "this decision's table.*above the limit"):
                    wide.decide(b, [0], [0], [456], [False])

    def test_dominated_rows_leave_the_solve_and_are_named(self):
        # #433, step 2d: the own rows weakly dominated in every world leave the solve; the choice is a kept row.
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, \
                self.make(ctx, width="slots") as plain, self.make(ctx, width="slots", prune="dominated") as pruned:
            self.preview(plain, b)
            self.preview(pruned, b)
            self.start_turn(b)
            _, (full,) = plain.decide(b, [0], [0], [456], [False])
            _, (kept,) = pruned.decide(b, [0], [0], [456], [False])
            tables = np.asarray(full["tables"])
            dominated = matrix.weakly_dominated(tables)
            self.assertTrue(dominated.any())  # the fixture's root has dominated rows: the test is not vacuous
            self.assertEqual(kept["dominated_pairs"], [p for p, d in zip(full["own_pairs"], dominated) if d])
            self.assertEqual(kept["own_pairs"], [p for p, d in zip(full["own_pairs"], dominated) if not d])
            self.assertNotIn(kept["choice"], kept["dominated_pairs"])
            self.assertEqual(kept["raw"], full["raw"])
            np.testing.assert_array_equal(np.asarray(kept["tables"]), tables[:, ~dominated, :])
            self.assertAlmostEqual(kept["value"], full["value"], delta=1e-9 * (1 + np.ptp(tables)))

    def test_a_search_above_the_lp_size_limit_is_refused_when_built(self):
        # #440: the exact rescue is known to finish up to 129 rows and 32 variables; one candidate solves nothing
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            for k, m, s in ((16, 16, 16), (8, 8, 32), (17, 8, 16)):
                with self.subTest(k=k, m=m, s=s), self.assertRaisesRegex(ValueError, "above the limit"):
                    honest.Honest(ctx, self.model, self.params, 4, 0, k=k, m=m, s=s)
            with honest.Honest(ctx, self.model, self.params, 4, 0, k=1, m=64, s=4, capacity=16, workers=1):
                pass

    def test_refused_mode_must_be_score_or_drop(self):
        costs = {k: 0.0 for k in ("public_records", "world_builds", "team_head", "leaves", "network", "solve")}
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, self.make(ctx) as search:
            with self.assertRaises(ValueError):
                search._decision(0, 456, np.zeros(1, np.int64), np.ones(1), np.ones(2) / 2, False, costs, refused="other")
            with self.assertRaises(ValueError):
                search._finish(None, np.zeros(1, np.float32), np.ones(1), costs, refused="other")

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
            for cause in ("visible_confusion",):
                for e in range(2):
                    # Privileged codec fixtures only: schema-3 offsets, no live rule implementation.
                    raw = np.frombuffer(original, np.uint8).copy()
                    raw[215 + 15 + 15] = 1 + e
                    self.assertEqual(decode(ctx.handle, b._battle(e), raw.ctypes.data, raw.size), 0)
                with mock.patch.object(b._lib, "duoforge_battle_hypothesis",
                                       side_effect=AssertionError("privileged ABI")), \
                        mock.patch.object(b._lib, "duoforge_battle_step_events",
                                          side_effect=AssertionError("privileged ABI")), \
                        mock.patch.object(b._lib, "duoforge_battle_clone",
                                          side_effect=AssertionError("privileged ABI")):
                    actions, records = search.decide(b, [0, 1], [0, 0], [456, 456], [False, False])
                self.assertEqual(actions[0], actions[1])
                self.assertTrue(all(r["kind"] == "unreconstructible" and r["causes"] == [cause] for r in records))
                stats = arena.diagnostics(records, 2)
                self.assertEqual(stats["unreconstructible_by_cause"][cause], {"decisions": 2, "share_of_decisions": 1.0})

    def test_visible_sleep_under_pool_is_searched_and_follows_the_start_law(self):
        # Decision 0066: a visible sleep under POOL is no fallback. Env e has the sleeper (side 0, member 0) with count
        # c = e (tail byte) and counter 3 - e (the true start 3 less the count). Each world that the search rebuilds
        # from the root's sample carries the exact law: S = 2 when the sleep word is in bucket 0 of 3 (for c in {0, 1}),
        # else 3; for c = 2, S = 3. The counter read from the world's encoding is S - c.
        # The S = 2 split needs WORLDS worlds. Their 2 x 2 tables have a tableau of 25,284 cells, above the size limit of
        # #440 (b-k16's 20,898). The limit is not under test here, so it is raised to this search's size.
        offs = {name: start for name, start, _ in state_layout.fields()}
        _, _, cells = honest.matrix.bayes_size(2, 2, WORLDS)
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, np.repeat(duoforge.reference_setups([0]), 3), 3, 42) as b, \
                mock.patch.object(honest.matrix, "MAX_BAYES_CELLS", cells), \
                self.make(ctx, s=WORLDS) as search:
            self.preview(search, b)
            self.start_turn(b)
            decode = b._lib.duoforge_battle_decode
            decode.restype = ctypes.c_uint32
            decode.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t)
            original = b.encode(0)
            for e in range(3):
                # Privileged codec fixtures only: the layout's offsets, no live rule implementation.
                raw = np.frombuffer(original, np.uint8).copy()
                raw[offs["side0.member0.status"]] = C["DUOFORGE_AILMENT_SLEEP"]
                raw[offs["side0.member0.status_counter"]] = 3 - e
                raw[offs["tail.side0.member0.sleep_cant"]] = e
                self.assertEqual(decode(ctx.handle, b._battle(e), raw.ctypes.data, raw.size), 0)
            with mock.patch.object(b._lib, "duoforge_battle_hypothesis",
                                   side_effect=AssertionError("privileged ABI")), \
                    mock.patch.object(b._lib, "duoforge_battle_step_events",
                                      side_effect=AssertionError("privileged ABI")), \
                    mock.patch.object(b._lib, "duoforge_battle_clone",
                                      side_effect=AssertionError("privileged ABI")):
                actions, records = search.decide(b, [0, 1, 2], [0, 0, 0], [456, 456, 456], [False, False, False])
            self.assertEqual([r["kind"] for r in records], ["searched"] * 3)
            publics, statuses = b.public(np.zeros(3, np.uint32))
            self.assertTrue((statuses == 0).all())
            publics = publics.copy()
            for e in range(3):
                # the worlds of root e, rebuilt from the sample that decide used for it (its last hypotheses)
                hypotheses = search.last[e]["hypotheses"]
                built = search._build(publics[e:e + 1].reshape(()).copy(), hypotheses)
                self.assertTrue((built == 0).all())
                words = [int(x) for x in hypotheses["sleep"][:, 0, 0]]
                starts, counters = [], []
                for w in range(WORLDS):
                    enc = np.frombuffer(search.worlds.encode(w), np.uint8)
                    self.assertEqual(int(enc[offs["side0.member0.status"]]), C["DUOFORGE_AILMENT_SLEEP"])
                    self.assertEqual(int(enc[offs["tail.side0.member0.sleep_cant"]]), e)
                    start = 3 if e == 2 else (2 if words[w] * 3 < 2 ** 64 else 3)  # the exact law, from the word
                    counter = int(enc[offs["side0.member0.status_counter"]])
                    self.assertEqual(counter, start - e)  # (a) the counter from_view built is S - c, S in {2, 3}
                    starts.append(start)
                    counters.append(counter)
                if e == 2:
                    self.assertEqual(set(counters), {1})  # (b) c = 2: every world starts at 3 and its counter is 1
                if e == 0:
                    # (c) the S = 2 / S = 3 split of the fixed key is about 1 : 2 (a loose bound for 64 worlds)
                    share = sum(1 for start in starts if start == 2) / WORLDS
                    self.assertLess(abs(share - 1 / 3), 0.2, share)

    def test_record_roots_reproduce_batch_decisions(self):
        # The live path (plan 2026-10-10-live-honest-search, Task 2): decide() over RecordRoots filled with a batch's
        # own parts (request, observation, encoded features, public record, episode) gives the batch's decisions.
        from duoforge_search.record_roots import RecordRoots
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, np.resize(duoforge.reference_setups([0, 1, 2, 3]), 4), 2, 42) as b, \
                self.make(ctx) as search, self.make(ctx) as twin:
            roots = RecordRoots(b.envs)
            policy = duoforge.RandomPolicy(73, b.envs)
            compared = 0
            for step in range(24):
                b.query_factored()
                obs, slots, pairs = b.query_encoded(search.encoder, search.ext_supported)
                for p in (0, 1):
                    envs = np.flatnonzero(b.requests["requested"][:, p])
                    if not envs.size:
                        continue
                    records, statuses = b.public(np.full(b.envs, p, np.uint32))
                    records, statuses = records.copy(), statuses.copy()
                    causes, _ = b.public_causes(np.full(b.envs, p, np.uint32))
                    for e in envs:
                        roots.set(e, p, request=b.requests[e, p], observation=b.observations[e, p], obs=obs[e, p],
                                  slots=slots[e, p], pairs=pairs[e, p], record=records[e], status=statuses[e],
                                  episode=b.episode(int(e)), causes=causes[e])
                    roots.requests[:, 1 - p]["requested"] = b.requests[:, 1 - p]["requested"]
                    keys = np.arange(len(envs), dtype=np.uint64) + 1000 * step
                    want, want_records = search.decide(b, envs, [p] * len(envs), keys, np.zeros(len(envs), bool))
                    got, got_records = twin.decide(roots, envs, [p] * len(envs), keys, np.zeros(len(envs), bool))
                    np.testing.assert_array_equal(got, want)
                    for w, g in zip(want_records, got_records):
                        self.assertEqual((g["kind"], g["boundary"], g.get("reason")), (w["kind"], w["boundary"], w.get("reason")))
                    compared += len(envs)
                b.step_factored(policy.choose_factored(b))
                b.reset_terminal()
            self.assertGreater(compared, 20)

    def test_live_search_on_live_features_gives_the_batch_decision(self):
        # The live path (plan 2026-10-10-live-honest-search, Task 5) encodes its own features (features.encode of the
        # tracker's observation and domain; zero slots and pairs at team preview) and LiveSearch converts them to the
        # network's encoder: over a batch's parts it decides as decide() on the batch.
        from duoforge_live import search as live_search
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, \
                self.make(ctx) as search, self.make(ctx) as twin:
            live = live_search.LiveSearch(twin)
            try:
                for turn in (False, True):
                    if turn:
                        self.start_turn(b)
                    else:
                        b.query_factored()
                    records, statuses = b.public(np.zeros(1, np.uint32))
                    causes, _ = b.public_causes(np.zeros(1, np.uint32))
                    parts = {"request": b.requests[0, 0], "observation": b.observations[0, 0],
                             "record": records[0].copy(), "status": int(statuses[0]), "causes": int(causes[0])}
                    obs_part, slot_part, pair_mask = features.encode(b.observations[0, 0], b.domains[0, 0],
                                                                     b.observe_ext()[0, 0], twin.ext_supported)
                    want, _ = search.decide(b, [0], [0], [456], [False])
                    got = live.decide(parts, obs_part, slot_part, pair_mask if turn else None, key=456,
                                      episode=b.episode(0), budget=600.0)
                    if turn:
                        self.assertEqual((got.cause, got.fallback, got.action), ("searched", None, int(want[0])))
                    else:
                        self.assertEqual((got.cause, got.fallback), ("team", None))
            finally:
                live.close()

    def test_a_provisional_pair_mask_is_cut_to_the_engines_domain(self):
        # The live tracker's pair mask is provisional (Showdown judges a pair; the arena of #362 met "switch 3, switch 3"):
        # the search's own candidates come from the engine's own domain of the worlds, never from a pair the engine
        # refuses. The root policy here puts a pair outside the engine's domain first.
        from duoforge_search.record_roots import RecordRoots
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, self.make(ctx) as search:
            self.preview(search, b)
            self.start_turn(b)
            obs, slots, pairs = b.query_encoded(search.encoder, search.ext_supported)
            records, statuses = b.public(np.zeros(1, np.uint32))
            d = b.domains[0, 0]
            widened = np.zeros_like(pairs[0, 0])
            widened[:int(d["slot_count"][0]), :int(d["slot_count"][1])] = True  # every slot pair, the illegal ones too
            illegal = np.argwhere(widened & ~pairs[0, 0].astype(bool))
            self.assertTrue(illegal.size, "no pair outside the engine's domain at this root")
            roots = RecordRoots(1)
            roots.set(0, 0, request=b.requests[0, 0], observation=b.observations[0, 0], obs=obs[0, 0],
                      slots=slots[0, 0], pairs=widened, record=records[0], status=int(statuses[0]),
                      episode=b.episode(0))
            search.history[roots] = {(0, 0): dict(search.history[b][(0, 0)])}  # the team preview the batch recorded
            bad = int(illegal[0][0]) * 32 + int(illegal[0][1])
            real = search._policy

            def policy(*inputs):
                pair, team, seconds = real(*inputs)
                pair = pair.copy()
                pair[0, bad] = 0.0  # the highest log-probability: the root's first candidate
                return pair, team, seconds

            with mock.patch.object(search, "_policy", side_effect=policy):
                actions, records_ = search.decide(roots, [0], [0], [456], [False])
            self.assertEqual(records_[0]["kind"], "searched")
            i, k = divmod(int(actions[0]), 32)
            self.assertTrue(pairs[0, 0][i, k], "the search played a pair the engine refuses")
            self.assertEqual(records_[0]["cut_pairs"], int((widened & ~pairs[0, 0].astype(bool)).sum()))  # shown
            _, engine_records = search.decide(b, [0], [0], [457], [False])
            self.assertEqual(engine_records[0]["cut_pairs"], 0)  # an engine root's mask is the engine's domain

    def test_a_foe_net_plays_the_worlds_and_the_main_net_the_root_and_the_leaves(self):
        # M7 (owner 2026-10-11): a second network models the foe. Every policy call on the worlds (the foe's team draw,
        # its queued pair and its menu) goes to it, encoded with its own encoder; the own candidates (the root's
        # policy) and the leaf values stay with the main network.
        class Spy:
            def __init__(self, inner):
                self.inner, self.rows = inner, []

            def __getattr__(self, name):
                return getattr(self.inner, name)

            def apply(self, params, obs, *rest):
                self.rows.append(np.asarray(obs).shape[0])
                return self.inner.apply(params, obs, *rest)

        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
            foe = self.encoder3_net(ctx)
            spy = Spy(self.model)
            with self.make(ctx) as plain, self.make(ctx, model=spy, foe_net=foe) as split:
                for search in (plain, split):
                    self.preview(search, b)
                self.start_turn(b)
                spy.rows.clear()
                _, (a,) = plain.decide(b, [0], [0], [456], [False])
                _, (r,) = split.decide(b, [0], [0], [456], [False])
                self.assertEqual((a["kind"], r["kind"]), ("searched", "searched"))
                self.assertEqual(r["own_pairs"], a["own_pairs"])  # the root's policy: the main network
                self.assertEqual(r["own_probs"], a["own_probs"])
                self.assertNotIn(2 * split.s, spy.rows)  # the main network saw no world row
                # The foe's menu is the foe network's ranking on the built worlds (encoder 3), not the main network's.
                menus = []
                for net, params, encoder, mask in (foe, (self.model, self.params, 4, split.ext_supported)):
                    o, sl, pm = split.worlds.query_encoded(encoder, mask)
                    n = 2 * split.s
                    pp = np.asarray(net.apply(params, o.reshape(n, -1), sl.reshape((n,) + sl.shape[2:]),
                                              pm.reshape((n,) + pm.shape[2:]))[0]).reshape(split.s, 2, -1)
                    probabilities = np.exp(pp[:, 1].astype(np.float64))
                    mean = np.sum(np.asarray(r["weights"])[:, None] * probabilities, axis=0)
                    order = np.lexsort((np.arange(mean.size), -mean))
                    menu = [order[pm[w, 1].reshape(-1)[order] != 0][:split.m].tolist() for w in range(split.s)]
                    menus.append((menu, probabilities))
                (foe_menu, foe_probs), (main_menu, _) = menus
                self.assertNotEqual(foe_menu, main_menu, "the two networks rank the foe alike: no evidence here")
                self.assertEqual(r["foe_pairs"], foe_menu)
                np.testing.assert_array_equal(r["foe_probs"], np.take_along_axis(foe_probs, np.array(foe_menu), axis=1))

    def test_the_main_net_as_foe_net_decides_bit_for_bit_as_without(self):
        # The second network's path changes the source of the worlds' policy only: given the main network itself, every
        # record field and leaf is the default's.
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
            with self.make(ctx) as probe:
                same = (self.model, self.params, 4, probe.ext_supported)
            with self.make(ctx) as plain, self.make(ctx, foe_net=same) as split:
                for search in (plain, split):
                    self.preview(search, b)
                self.start_turn(b)
                for key in (456, 457):
                    _, (a,) = plain.decide(b, [0], [0], [key], [False])
                    _, (r,) = split.decide(b, [0], [0], [key], [False])
                    self.assertEqual(a["kind"], "searched")
                    drop = ("cost", "time", "foe_net")  # wall times; the foe network's name, checked here
                    self.assertEqual(r["foe_net"], {"encoder": 4, "ext_supported": probe.ext_supported})
                    self.assertEqual({k: v for k, v in r.items() if k not in drop},
                                     {k: v for k, v in a.items() if k not in drop})
                    for name in ("hypotheses", "choices", "values"):
                        np.testing.assert_array_equal(split.last[-1][name], plain.last[-1][name])

    def test_the_main_net_as_foe_net_previews_bit_for_bit_as_without(self):
        # Step 1 (#440): the value preview's foe candidates come from the foe network; given the main network itself,
        # every field of the team-preview record is the default's, the wall times and the foe network's name aside.
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
            with self.make(ctx) as probe:
                same = (self.model, self.params, 4, probe.ext_supported)
            with self.make(ctx, preview_mode="value") as plain, \
                    self.make(ctx, preview_mode="value", foe_net=same) as split:
                for seat in (0, 1):
                    for key in (456, 457):
                        _, (a,) = plain.decide(b, [0], [seat], [key], [False])
                        _, (r,) = split.decide(b, [0], [seat], [key], [False])
                        self.assertEqual(a["kind"], "searched")
                        drop = ("cost", "time", "foe_net")
                        self.assertEqual(r["foe_net"], {"encoder": 4, "ext_supported": probe.ext_supported})
                        self.assertEqual({k: v for k, v in r.items() if k not in drop},
                                         {k: v for k, v in a.items() if k not in drop})
                        for name in ("hypotheses", "choices", "tables"):
                            np.testing.assert_array_equal(split.last[-1][name], plain.last[-1][name])

    def test_a_foe_nets_team_head_picks_the_preview_foe_candidates(self):
        # Step 1 (#440): the foe candidates are the foe network's ranking of the worlds' team draws, weighted by the
        # sampled worlds; the own candidates and the leaf values stay with the main network.
        class Spy:
            def __init__(self, inner):
                self.inner, self.apply_rows, self.values = inner, [], 0

            def __getattr__(self, name):
                return getattr(self.inner, name)

            def apply(self, params, obs, *rest):
                self.apply_rows.append(np.asarray(obs).shape[0])
                return self.inner.apply(params, obs, *rest)

            def value(self, params, rows):
                self.values += 1
                return self.inner.value(params, rows)

        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
            foe_model, foe_params, foe_encoder, foe_ext = self.encoder3_net(ctx)
            main, foe = Spy(self.model), Spy(foe_model)
            with self.make(ctx, preview_mode="value") as plain, \
                    self.make(ctx, model=main, preview_mode="value",
                              foe_net=(foe, foe_params, foe_encoder, foe_ext)) as split:
                _, (a,) = plain.decide(b, [0], [0], [456], [False])
                main.apply_rows.clear()
                foe.apply_rows.clear()
                _, (r,) = split.decide(b, [0], [0], [456], [False])
                self.assertEqual((a["kind"], r["kind"]), ("searched", "searched"))
                self.assertEqual(r["own_teams"], a["own_teams"])  # the root's team head: the main network
                self.assertEqual(r["own_probs"], a["own_probs"])
                self.assertNotIn(2 * split.s, main.apply_rows)  # the main network saw no world row
                self.assertIn(2 * split.s, foe.apply_rows)  # the foe network ranked the worlds
                self.assertGreater(main.values, 0)  # the leaves are valued by the main network
                self.assertEqual(foe.values, 0)
                # The foe's candidates: the foe network's team ranking of the built worlds, under the sampled weights.
                o, sl, pm = split.worlds.query_encoded(foe_encoder, foe_ext)
                n = 2 * split.s
                _, team, _ = foe.apply(foe_params, o.reshape(n, -1), sl.reshape((n,) + sl.shape[2:]),
                                       pm.reshape((n,) + pm.shape[2:]))
                probabilities = np.exp(np.asarray(team).reshape(split.s, 2, -1)[:, 1].astype(np.float64))
                mean = np.sum(np.asarray(r["weights"])[:, None] * probabilities, axis=0)
                other = np.argsort(-mean, kind="stable")[:split.m]
                self.assertEqual(r["foe_teams"], other.tolist())
                np.testing.assert_array_equal(r["foe_probs"], probabilities[:, other])
                self.assertNotEqual(r["foe_teams"], a["foe_teams"], "the two networks rank the foe alike: no evidence")

    def test_preview_rule(self):
        # Step 1 (#440): the preview plays outcomes[preview_rule] and names it; None keeps the search's own rule.
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
            with self.make(ctx, rule="ev", preview_mode="value") as default, \
                    self.make(ctx, rule="mix", preview_mode="value", preview_rule="nash") as named, \
                    self.make(ctx, rule="nash", preview_mode="value") as nash:
                _, (d,) = default.decide(b, [0], [0], [456], [False])
                _, (x,) = named.decide(b, [0], [0], [456], [False])
                _, (n,) = nash.decide(b, [0], [0], [456], [False])
                self.assertEqual((d["kind"], x["kind"]), ("searched", "searched"))
                self.assertEqual(d["rule"], "ev")
                self.assertEqual(d["choice"], d["own_teams"][d["outcomes"]["ev"]])
                self.assertEqual(x["rule"], "nash")
                self.assertEqual(x["choice"], x["own_teams"][x["outcomes"]["nash"]])
                drop = ("cost", "time", "rule")  # the named preview is the nash rule's, whatever the search's rule
                self.assertEqual({k: v for k, v in x.items() if k not in drop},
                                 {k: v for k, v in n.items() if k not in drop})
            with self.assertRaisesRegex(ValueError, "preview_rule"):
                self.make(ctx, preview_mode="value", preview_rule="other")
            with self.assertRaisesRegex(ValueError, "preview_rule"):
                self.make(ctx, preview_rule="nash")  # a raw search has no preview to rule

    def test_a_foe_net_must_read_its_encoders_rows(self):
        # A foe network trained on another encoder is refused when the search is built, not at its first decision.
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            model, params, _, mask = self.encoder3_net(ctx)
            with self.assertRaisesRegex(ValueError, "foe network"):
                self.make(ctx, foe_net=(model, params, 4, mask))
            with self.assertRaisesRegex(ValueError, "foe network"):
                self.make(ctx, foe_net=(model, params))
            with self.assertRaisesRegex(ValueError, "foe network's extension mask"):
                self.make(ctx, foe_net=(model, params, 3, features.version_features(4)))

    def test_a_foe_net_is_accepted_with_a_turn1_preview_search(self):
        # Step 1b (#440): the turn-1 rollout plays the foe seat with the foe network, so the combination is accepted.
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            foe = self.encoder3_net(ctx)
            with self.make(ctx, foe_net=foe, preview_mode="turn1") as search:
                self.assertEqual(search.foe_net[2:], (3, foe[3]))

    def test_the_main_net_as_foe_net_rolls_out_bit_for_bit_as_without(self):
        # Step 1b (#440): the rollout's foe seat takes the foe network's rows and policy; given the main network itself,
        # every field of the turn-1 preview record is the default's, the wall times and the foe network's name aside.
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
            with self.make(ctx) as probe:
                same = (self.model, self.params, 4, probe.ext_supported)
            with self.make(ctx, preview_mode="turn1") as plain, \
                    self.make(ctx, preview_mode="turn1", foe_net=same) as split:
                for seat in (0, 1):
                    for key in (456, 457):
                        _, (a,) = plain.decide(b, [0], [seat], [key], [False])
                        _, (r,) = split.decide(b, [0], [seat], [key], [False])
                        self.assertEqual((a["kind"], a["preview_eval"]), ("searched", "turn1"))
                        drop = ("cost", "time", "foe_net")
                        self.assertEqual(r["foe_net"], {"encoder": 4, "ext_supported": probe.ext_supported})
                        self.assertEqual({k: v for k, v in r.items() if k not in drop},
                                         {k: v for k, v in a.items() if k not in drop})
                        for name in ("hypotheses", "choices", "tables"):
                            np.testing.assert_array_equal(split.last[-1][name], plain.last[-1][name])

    def test_the_turn1_rollout_plays_the_foe_seat_with_the_foe_net(self):
        # Step 1b (#440): each rollout step asks the foe network for the foe seat's rows only, and the main network for
        # the player seat's rows only; both see the rollout batch's rows (one per environment), not the worlds' rows.
        class Spy:
            def __init__(self, inner):
                self.inner, self.rows = inner, []

            def __getattr__(self, name):
                return getattr(self.inner, name)

            def apply(self, params, obs, *rest):
                self.rows.append(np.asarray(obs).shape[0])
                return self.inner.apply(params, obs, *rest)

        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
            model, params, encoder, mask = self.encoder3_net(ctx)
            main, foe = Spy(self.model), Spy(model)
            with self.make(ctx, model=main, foe_net=(foe, params, encoder, mask), preview_mode="turn1") as search:
                envs = search.leaves.envs
                self.assertNotEqual(envs, 2 * search.s)  # the worlds' policy calls have 2 * s rows: told apart
                main.rows.clear()
                foe.rows.clear()
                self.preview(search, b)
        rollout_foe = [r for r in foe.rows if r == envs]
        rollout_main = [r for r in main.rows if r == envs]
        self.assertTrue(rollout_foe, "the foe network was not called on the rollout's foe seat")
        self.assertTrue(rollout_main, "the main network was not called on the rollout's player seat")
        self.assertEqual(len(rollout_foe), len(rollout_main))  # one foe-seat call for each player-seat call

    def test_rollout_masks_must_agree(self):
        # Step 1b (#440): the foe seat's pair is chosen from the foe encoding's legal mask; a mask the main encoding
        # gives the same asked foe seat differently stops the decision, as _prepare does, and nothing is picked from either.
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
            with self.make(ctx, foe_net=self.encoder3_net(ctx), preview_mode="turn1") as search:
                real = search.leaves.query_encoded

                def query(version, ext=0):
                    obs, slots, pairs = real(version, ext)
                    if version == 4:  # the main encoding: the foe seat (seat 1) has no legal pair at all
                        pairs = pairs.copy()
                        pairs[:, 1] = False
                    return obs, slots, pairs

                with mock.patch.object(search.leaves, "query_encoded", side_effect=query):
                    with self.assertRaisesRegex(honest.SearchError, "another pair mask"):
                        search.decide(b, [0], [0], [456], [False])

    def test_a_foe_net_is_accepted_with_a_value_preview_search(self):
        # The value preview's rollout is none: the foe's team candidates come from the foe network, the own candidates
        # and the leaf values from the main one (step 1 of the search ladder, #440).
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            foe = self.encoder3_net(ctx)
            with self.make(ctx, foe_net=foe, preview_mode="value") as search:
                self.assertEqual(search.foe_net[2:], (3, foe[3]))

    def test_the_foe_and_main_encodings_must_give_the_worlds_one_pair_mask(self):
        # _prepare ranks the foe's menu on the foe encoding's mask and checks the viewer on the main encoding's rows: a
        # mask the two encodings disagree on stops the decision explicitly.
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
            with self.make(ctx, foe_net=self.encoder3_net(ctx)) as split:
                self.preview(split, b)
                self.start_turn(b)
                real = split.worlds.query_encoded

                def query(version, ext=0):
                    obs, slots, pairs = real(version, ext)
                    if version == 4:  # the main encoding: one pair more than the foe encoding allows
                        pairs = pairs.copy()
                        pairs[0, 1].flat[np.flatnonzero(~pairs[0, 1])[0]] = True
                    return obs, slots, pairs

                with mock.patch.object(split.worlds, "query_encoded", side_effect=query):
                    with self.assertRaisesRegex(honest.SearchError, "another pair mask"):
                        split.decide(b, [0], [0], [456], [False])

    def test_a_foe_nets_record_names_its_encoder(self):
        # A stopped decision under a foe network is reproducible from its record only if the record says which encoder
        # and mask modelled the foe; the default's records stay as they were.
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
            foe = self.encoder3_net(ctx)
            with self.make(ctx) as plain, self.make(ctx, foe_net=foe) as split:
                for search in (plain, split):
                    self.preview(search, b)
                self.start_turn(b)
                _, (a,) = plain.decide(b, [0], [0], [456], [False])
                _, (r,) = split.decide(b, [0], [0], [456], [False])
            self.assertNotIn("foe_net", a)
            self.assertEqual(r["foe_net"], {"encoder": 3, "ext_supported": foe[3]})

    def test_assembled_record_is_checked_and_named(self):
        # A record assembled outside the engine (the live tracker's) is not searched unless the engine accepts it and
        # every world built from it gives it back. A filled masked field (here the foe's exact HP) is refused by the
        # engine itself; a world that gives another record back is named by field.
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, self.make(ctx) as search:
            self.preview(search, b)
            self.start_turn(b)
            v, st = b.public(np.zeros(1, np.uint32))
            self.assertEqual(int(st[0]), 0)
            record = v[:1].reshape(()).copy()
            history = search.history[b][(0, 0)]
            costs = {k: 0. for k in ("public_records", "world_builds", "team_head", "network")}
            search._hypotheses(record, b.observations[0, 0], history, 1, None, costs)  # the engine's record passes
            from duoforge import state_layout
            starts = dict((n, s) for n, s, _ in state_layout.fields())
            masked = record.copy()
            masked["state"][starts["side1.member0.hp"]] = 7
            with self.assertRaisesRegex(honest.SearchError, "MALFORMED"):
                search._hypotheses(masked, b.observations[0, 0], history, 2, None, costs)
            public = search.worlds.public

            def other_turn(players):  # worlds that give a record with another weather byte back
                again, statuses = public(players)
                again = again.copy()
                again["state"][:, starts["weather_turns"]] ^= 1
                return again, statuses

            with mock.patch.object(search.worlds, "public", side_effect=other_turn), \
                    self.assertRaisesRegex(honest.SearchError, r"state fields \['weather_turns'\]"):
                search._hypotheses(record, b.observations[0, 0], history, 3, None, costs)

            def other_preview(players):  # only the team preview's worlds give another record back (review of #339)
                again, statuses = public(players)
                if int(again[0]["boundary"]) == C["DUOFORGE_BOUNDARY_TEAM_SELECTION"]:
                    again = again.copy()
                    again["state"][:, starts["weather_turns"]] ^= 1
                return again, statuses

            with mock.patch.object(search.worlds, "public", side_effect=other_preview), \
                    self.assertRaisesRegex(honest.SearchError, r"state fields \['weather_turns'\]"):
                search._hypotheses(record, b.observations[0, 0], history, 4, None, costs)

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
            # Only a PIVOT record with a pending foe command needs its turn-start record (the queue mask). Since the
            # view audit of 2026-10-10 the engine's public records never carry one, so this hand-made record sets it;
            # a public PIVOT without one is searched from its own record (test_pivot_records_and_queue_sampling).
            record["foe_pending_mask"] = 1
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


class LiveModelPolicy(unittest.TestCase):
    def test_a_v2_checkpoint_plays_through_its_own_network(self):
        # The live bot's raw ranking (its play without the search, and the search's fallback) of a model-v2 checkpoint
        # such as params-49333 (plan 2026-10-10-live-honest-search, Task 4): the checkpoint's own network in its trained
        # layout, never the v1-only NumPy forward. Over the live features its best team and pair are the network's
        # argmax over the batch's own rows.
        from duoforge_learn import checkpoint, policy as learn_policy
        from duoforge_live import policy as live_policy
        model_config = learn_policy.v2_config("S")
        model = learn_policy.make(model_config, features.feature_names(4))
        params = model.init(__import__("jax").random.PRNGKey(11))
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b, \
                tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "v2.npz")
            checkpoint.save(path, params, {"model": model_config, "encoder": 4,
                                           "features": list(features.feature_names(4)),
                                           "slot_features": list(features.SLOT_FEATURE_NAMES),
                                           "data": {"kind": "pool", "fingerprint": "00"}, "teams": {}, "update": 0,
                                           "decisions": 0, "ids": checkpoint.ids_of(ctx)})
            live = live_policy.load(path)
            self.assertEqual(live.encoder, 4)
            for turn in (False, True):
                if turn:
                    choices = np.zeros((1, 2), _layout.FACTORED_CHOICE)
                    choices["picks"][:, :, :4] = np.arange(4, dtype=np.uint8)
                    b.step_factored(choices)
                b.query_factored()
                obs, slots, pairs = b.query_encoded(4, live.ext_supported)
                logp_pairs, logp_team, _ = (np.asarray(x) for x in model.apply(params, obs[:, 0], slots[:, 0], pairs[:, 0]))
                obs_part, slot_part, pair_mask = features.encode(b.observations[0, 0], b.domains[0, 0], None,
                                                                 live.ext_supported)
                if turn:
                    i, j, _ = live.rank_pairs(b.observations[0, 0], obs_part, slot_part, pair_mask)[0]
                    self.assertEqual(i * pair_mask.shape[1] + j, int(np.argmax(logp_pairs[0])))
                else:
                    self.assertEqual(live.rank_teams(b.observations[0, 0], obs_part)[0][0], int(np.argmax(logp_team[0])))


class LiveLatency(unittest.TestCase):
    def test_a_short_measurement_reports_every_boundary_kind_it_met(self):
        # Task 4 of plan 2026-10-10-live-honest-search: the live search's own latency per boundary kind (no deadline),
        # its warm-up and its outcome causes; private output outside the repository only.
        from duoforge_learn import checkpoint, policy as learn_policy
        from duoforge_search import live_latency
        model_config = learn_policy.v2_config("S")
        model = learn_policy.make(model_config, features.feature_names(4))
        params = model.init(__import__("jax").random.PRNGKey(11))
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "v2.npz")
            checkpoint.save(path, params, {"model": model_config, "encoder": 4,
                                           "features": list(features.feature_names(4)),
                                           "slot_features": list(features.SLOT_FEATURE_NAMES),
                                           "data": {"kind": "pool", "fingerprint": "00"}, "teams": {}, "update": 0,
                                           "decisions": 0, "ids": checkpoint.ids_of(ctx)})
            out = os.path.join(tmp, "out")
            with self.assertRaisesRegex(ValueError, "repository"):
                live_latency.main(["--checkpoint", path, "--out", "python/tests/latency-out", "--games", "1"])
            live_latency.main(["--checkpoint", path, "--out", out, "--games", "1", "--max-steps", "6",
                               "--k", "2", "--m", "2", "--worlds", "2", "--no-foe-net"])
            with open(os.path.join(out, "latency.json"), encoding="utf-8") as f:
                report = json.load(f)
        self.assertEqual(report["games"], 1)
        self.assertEqual(report["runtime"], "jax-cpu")
        self.assertGreater(report["warmup"]["load_seconds"], 0.0)
        self.assertIn("team_selection", report["boundaries"])
        self.assertIn("turn", report["boundaries"])
        for kind, row in report["boundaries"].items():
            self.assertEqual(set(row), {"n", "p50", "p95", "p99", "max", "causes", "reasons"}, kind)
            self.assertTrue(row["p50"] <= row["p95"] <= row["p99"] <= row["max"], kind)
            self.assertEqual(sum(row["causes"].values()), row["n"], kind)
            self.assertEqual(set(row["reasons"]) == set(), all(c in ("searched", "forced", "raw", "team")
                                                                for c in row["causes"]), kind)
        self.assertEqual(report["settings"]["k"], 2)
        self.assertIsNone(report["foe_net"])  # the report names its arm: here --no-foe-net

    def test_the_live_search_loads_its_pinned_foe_network(self):
        # Owner 2026-10-12: the live search's worlds are modelled by the pinned foe network (BC6 in play; here an
        # encoder-3 stand-in pinned by its own hash); it must read the library's tables as the network does
        # (checkpoint.check_data), and the main network keeps its own candidates and the values.
        import hashlib
        import jax
        from duoforge_learn import checkpoint, policy as learn_policy
        from duoforge_live import search as live_search

        def save(path, encoder, key):
            config = learn_policy.v2_config("S")
            model = learn_policy.make(config, features.feature_names(encoder))
            checkpoint.save(path, model.init(jax.random.PRNGKey(key)),
                            {"model": config, "encoder": encoder, "features": list(features.feature_names(encoder)),
                             "slot_features": list(features.SLOT_FEATURE_NAMES),
                             "data": {"kind": "pool", "fingerprint": "00"}, "teams": {}, "update": 0, "decisions": 0,
                             "ids": checkpoint.ids_of(ctx)})

        settings = dict(live_search.HONEST_SETTINGS, k=2, m=2, s=2, capacity=8)
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, tempfile.TemporaryDirectory() as tmp:
            main, foe = os.path.join(tmp, "main.npz"), os.path.join(tmp, "foe.npz")
            save(main, 4, 11)
            save(foe, 3, 12)
            with open(foe, "rb") as f:
                pin = hashlib.sha256(f.read()).hexdigest()
            live = live_search.load(main, settings=settings, foe_net=foe, foe_net_sha256=pin)
            try:
                model, _, encoder, _ = live.searcher.foe_net
                self.assertEqual(encoder, 3)
                self.assertEqual(len(model.feature_names), features.obs_size(3))
                self.assertEqual(live.searcher.encoder, 4)
                self.assertEqual(live.foe_check["ids"], "carried over")  # another fingerprint, its ids carry over
                self.assertEqual(live.foe_check["sha256"], pin)  # the arm a log or a report names
            finally:
                live.close()
            bare = live_search.load(main, settings=settings, foe_net=None)
            try:
                self.assertIsNone(bare.searcher.foe_net)
                self.assertIsNone(bare.foe_check)
            finally:
                bare.close()


class PositionsTool(unittest.TestCase):
    def test_the_tool_plays_every_position_raw_honest_and_by_oracle(self):
        # M12 bundle 7: the test positions per checkpoint, a diagnosis written outside the repository only.
        from duoforge_learn import checkpoint, policy as learn_policy
        from duoforge_search import positions
        model_config = learn_policy.v2_config("S")
        model = learn_policy.make(model_config, features.feature_names(4))
        params = model.init(__import__("jax").random.PRNGKey(11))
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "v2.npz")
            checkpoint.save(path, params, {"model": model_config, "encoder": 4,
                                           "features": list(features.feature_names(4)),
                                           "slot_features": list(features.SLOT_FEATURE_NAMES),
                                           "data": {"kind": "pool", "fingerprint": "00"}, "teams": {}, "update": 0,
                                           "decisions": 0, "ids": checkpoint.ids_of(ctx)})
            inside = os.path.join(os.path.dirname(os.path.abspath(__file__)), "positions-out")  # in the repository
            with self.assertRaisesRegex(ValueError, "repository"):
                positions.main(["--checkpoint", path, "--out", inside])
            report = positions.main(["--checkpoint", path, "--out", os.path.join(tmp, "out"), "--k", "2", "--m", "2",
                                     "--worlds", "2"])
        all_positions = positions.load_all()
        self.assertEqual([r["name"] for r in report["positions"]], [p.name for p in all_positions])
        for row, position in zip(report["positions"], all_positions):
            self.assertEqual("oracle" in row, row["kind"] in positions.ORACLE_KINDS)
            for name in ("raw", "honest") + (("oracle",) if "oracle" in row else ()):
                # a hit is exactly an expected answer's labels; the honest row names its search's kind
                self.assertEqual(row[name]["hit"], positions.accepted(position.expected, row[name]["labels"]))
            self.assertIn(row["honest"]["kind"], ("searched", "unreconstructible", "forced", "raw"))
        rates = report["hit_rates"]
        self.assertEqual(rates["raw"]["counted"], len(all_positions))
        # only searched decisions are the search's answers
        self.assertEqual(rates["honest"]["counted"],
                         sum(r["honest"]["kind"] == "searched" for r in report["positions"]))
        self.assertEqual(rates["honest"]["hits"],
                         sum(r["honest"]["hit"] for r in report["positions"] if r["honest"]["kind"] == "searched"))


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



class FoeArena(unittest.TestCase):
    """M7's paired measurement (duoforge_search.foe_arena): its schedule, its predeclared gates and its guards."""

    def test_each_team_pair_is_played_twice_with_the_teams_and_seats_swapped(self):
        from duoforge_search import foe_arena
        rows = foe_arena.games(5, 40, seed=3)
        self.assertEqual(rows.shape, (80,))
        np.testing.assert_array_equal(rows["side0"][0::2], rows["side0"][1::2])
        np.testing.assert_array_equal(rows["side1"][0::2], rows["side1"][1::2])
        np.testing.assert_array_equal(rows["learner_seat"], np.tile([0, 1], 40))
        np.testing.assert_array_equal(rows["game"], np.repeat(np.arange(40), 2))
        self.assertTrue((rows["side0"] != rows["side1"]).all())
        self.assertTrue((rows["side0"] < 5).all() and (rows["side1"] < 5).all())
        np.testing.assert_array_equal(rows, foe_arena.games(5, 40, seed=3))  # a pure function of its arguments
        self.assertFalse(np.array_equal(rows, foe_arena.games(5, 40, seed=4)))
        with self.assertRaises(ValueError):
            foe_arena.games(1, 4)

    def test_the_verdict_adopts_only_when_every_gate_holds(self):
        from duoforge_search import foe_arena
        searched = [{"kind": "searched", "wall": 0.1}] * 99 + [{"kind": "team"}]
        better, worse = np.tile([1.0, 0.5], 50), np.tile([0.5, 0.0], 50)
        v = foe_arena.verdict(better, worse, searched, searched, resamples=200)
        self.assertEqual(v["pairs"], 50)
        self.assertEqual(v["h"]["mean"], 0.75)
        self.assertTrue(v["adopt"], v)
        even = foe_arena.verdict(worse, worse, searched, searched, resamples=200)
        self.assertEqual(even["h"]["95"], [0.5, 0.5])
        self.assertFalse(even["gates"]["lower_bound"])  # the lower bound must be above 0.50, not at it
        self.assertFalse(even["adopt"])
        slow = [{"kind": "searched", "wall": 2.5}] * 99
        self.assertFalse(foe_arena.verdict(better, worse, slow, searched, resamples=200)["gates"]["p99_seconds"])
        nothing = foe_arena.verdict(better, worse, [{"kind": "team"}], searched, resamples=200)
        self.assertIsNone(nothing["p99_seconds_f"])
        self.assertFalse(nothing["adopt"])  # no searched decision, no latency evidence

    def test_the_verdicts_interval_resamples_team_pairs_not_games(self):
        # Within every pair F wins one game and loses the other against M: each pair's mean difference is 0, so a
        # bootstrap over pairs has no spread at all, while one over single games would be wide.
        from duoforge_search import foe_arena
        searched = [{"kind": "searched", "wall": 0.1}] * 10
        f, m = np.tile([1.0, 0.0], 100), np.tile([0.0, 1.0], 100)
        v = foe_arena.verdict(f, m, searched, searched, resamples=500)
        self.assertEqual(v["pairs"], 100)
        self.assertEqual(v["h"], {"mean": 0.5, "95": [0.5, 0.5]})
        with self.assertRaises(ValueError):
            foe_arena.verdict(f[:-1], m[:-1], searched, searched)  # an odd row count is no set of pairs

    def test_the_tool_refuses_an_output_inside_the_repository(self):
        from duoforge_search import foe_arena
        with tempfile.TemporaryDirectory() as tmp:
            nets = [os.path.join(tmp, name) for name in ("a.npz", "b.npz", "c.npz")]
            for path, data in zip(nets, (b"main", b"foe", b"bot")):
                with open(path, "wb") as f:
                    f.write(data)
            inside = os.path.join(os.path.dirname(os.path.abspath(foe_arena.__file__)), "foe-arena-out")
            with self.assertRaisesRegex(SystemExit, "inside the repository"):
                foe_arena.main(["--checkpoint", nets[0], "--foe-net", nets[1], "--bot", nets[2], "--out", inside])
            self.assertFalse(os.path.exists(inside))

    def test_the_fallback_gate_is_the_arenas_or_the_status_quos_own_share(self):
        from duoforge_search import foe_arena

        def records(raw):  # 100 non-team decisions, raw of them unreconstructible
            return [{"kind": "unreconstructible"}] * raw + [{"kind": "searched", "wall": 0.1}] * (100 - raw) + \
                [{"kind": "team"}] * 7

        score = np.tile([1.0, 0.0], 10)
        self.assertEqual(foe_arena.fallback_share(records(5)), 0.05)
        self.assertTrue(foe_arena.verdict(score, score, records(5), records(0))["gates"]["fallback_share"])
        self.assertFalse(foe_arena.verdict(score, score, records(6), records(0))["gates"]["fallback_share"])
        # Where the status quo M itself falls back more often, F may not add more than one point to it.
        self.assertTrue(foe_arena.verdict(score, score, records(9), records(8))["gates"]["fallback_share"])
        self.assertFalse(foe_arena.verdict(score, score, records(10), records(8))["gates"]["fallback_share"])

    def test_the_bot_and_the_foe_model_must_be_two_networks(self):
        from duoforge_search import foe_arena
        with tempfile.TemporaryDirectory() as tmp:
            paths = [os.path.join(tmp, name) for name in ("a.npz", "b.npz", "c.npz")]
            for path, data in zip(paths, (b"one", b"one", b"two")):
                with open(path, "wb") as f:
                    f.write(data)
            with self.assertRaisesRegex(SystemExit, "one network"):
                foe_arena.check_nets(paths[0], paths[1])
            self.assertEqual(len(foe_arena.check_nets(paths[0], paths[2])), 2)

    def test_the_timed_search_decides_one_root_per_call(self):
        from duoforge_search import foe_arena

        class Search:
            calls = []

            def decide(self, roots, envs, seats, keys, last_step):
                self.calls.append((list(envs), list(seats), list(keys), list(last_step)))
                return np.array([10 * int(envs[0]) + int(seats[0])]), [{"kind": "searched", "env": int(envs[0])}]

        timed = foe_arena.Timed(Search())
        actions, records = timed.decide(None, np.array([3, 5]), np.array([1, 0]), np.array([7, 8], np.uint64),
                                        np.array([False, True]))
        self.assertEqual(actions.tolist(), [31, 50])
        self.assertEqual(Search.calls, [([3], [1], [7], [False]), ([5], [0], [8], [True])])
        self.assertEqual([r["env"] for r in records], [3, 5])
        self.assertTrue(all(r["wall"] >= 0 for r in records))


class SmogonSpreads(unittest.TestCase):
    """The live belief's Smogon source (duoforge_search.smogon_spreads; owner 2026-10-12): spreads checked and
    counted, the highest rating cutoff with enough weight per species, weights as whole draws, pinned files."""

    @staticmethod
    def stats(spreads, battles=1000):
        return {"info": {"number of battles": battles}, "data": {name: {"Spreads": sp} for name, sp in spreads.items()}}

    def test_candidates_are_computed_once_per_key(self):
        # The live table holds about 270,000 rows: SpreadTable.candidates keeps each key's answer (the table is read
        # only once drawn from), so a decision's draws do not rescan it; the rows and levels are the same.
        sides = duoforge.reference_setups([0, 1, 2, 3])["sides"].reshape(-1)
        table = belief.SpreadTable.from_sides(sides)
        fresh = belief.SpreadTable.from_sides(sides)
        keys = [(int(sp), int(n), int(i), t, lvl) for sp, n, i in zip(table.species[:5], table.nature[:5], table.item[:5])
                for t in (None, 0, 1) for lvl in (1, 3)]
        for key in keys:
            level, rows = table.candidates(*key)
            again_level, again = table.candidates(*key)
            self.assertIs(again, rows)  # the kept answer
            ref_level, ref = fresh._scan(*key)
            self.assertEqual((level, rows.tolist()), (ref_level, ref.tolist()))

    def test_a_spread_is_parsed_and_its_stat_points_checked(self):
        from duoforge_search import smogon_spreads as ss
        self.assertEqual(ss.parse_spread("Bold:32/0/18/0/16/0"), ("Bold", (32, 0, 18, 0, 16, 0)))
        self.assertIsNone(ss.parse_spread("Bold:33/0/0/0/0/0"))  # past 32 in one stat
        self.assertIsNone(ss.parse_spread("Bold:32/32/2/1/0/0"))  # past 66 in all
        for bad in ("Bold", "Bold:32/0/18/0/16", "Bold:a/0/0/0/0/0"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ss.parse_spread(bad)

    def test_each_species_takes_the_highest_cutoff_with_enough_weight(self):
        from duoforge_search import smogon_spreads as ss
        heavy, light = ss.MIN_WEIGHT, ss.MIN_WEIGHT / 4
        sources = {
            ("gen9championsvgc2026regmc", 1760): self.stats({"Toxapex": {"Bold:32/0/18/0/16/0": light}}),
            ("gen9championsvgc2026regmcbo3", 1760): self.stats({"Toxapex": {"Relaxed:32/0/18/0/16/0": light},
                                                                "Amoonguss": {"Calm:32/0/16/0/18/0": heavy},
                                                                "Garchomp-Mega-Z": {"Jolly:2/32/0/0/0/32": heavy}}),
            ("gen9championsvgc2026regmc", 1630): self.stats({"Toxapex": {"Bold:32/0/18/0/16/0": heavy / 2}}),
            ("gen9championsvgc2026regmcbo3", 1630): self.stats({"Toxapex": {"Relaxed:32/0/18/0/16/0": heavy / 2}}),
            ("gen9championsvgc2026regmc", 0): self.stats({"Toxapex": {"Bold:32/0/32/2/0/0": 9 * heavy},
                                                          "Pikachu": {"Timid:0/0/0/32/2/32": 1.0}}),
        }
        bases = {"Garchomp-Mega-Z": ("Garchomp", True), "Notamon": None}
        chosen, counts = ss.species_spreads(sources, lambda name: bases.get(name, (name, False)))
        # 1760 has Toxapex with too little weight (both formats summed), 1630 enough: its two formats' spreads
        self.assertEqual(chosen["Toxapex"][0], 1630)
        self.assertEqual(chosen["Toxapex"][1], {("Bold", (32, 0, 18, 0, 16, 0)): heavy / 2,
                                                ("Relaxed", (32, 0, 18, 0, 16, 0)): heavy / 2})
        self.assertEqual(chosen["Amoonguss"][0], 1760)
        self.assertEqual(chosen["Pikachu"][0], 0)  # too light everywhere: the lowest cutoff's, as the fill
        # a Mega forme's users bring the base species with its stone (an open sheet names the base): merged into it
        self.assertEqual(chosen["Garchomp"], (1760, {("Jolly", (2, 32, 0, 0, 0, 32)): heavy}))
        self.assertNotIn("Garchomp-Mega-Z", chosen)
        self.assertEqual(counts["mega_merged"], 1)
        self.assertEqual(counts["origin"], {"1760": 2, "1630": 1, "0": 1})
        sources[("gen9championsvgc2026regmc", 0)]["data"]["Notamon"] = {"Spreads": {"Bold:0/0/0/0/0/0": 1.0}}
        _, counts = ss.species_spreads(sources, lambda name: bases.get(name, (name, False)))
        self.assertEqual(counts["outside_context"], 1)  # a name the engine does not know: counted, not drawn
        for weightless in ({"Bold:0/0/0/0/0/0": 0.0}, {"Bold:33/0/0/0/0/0": 5.0}):
            sources[("gen9championsvgc2026regmc", 0)]["data"]["Pikachu"] = {"Spreads": weightless}
            with self.subTest(weightless=weightless), self.assertRaisesRegex(ValueError, "no valid weight"):
                ss.species_spreads({k: v for k, v in sources.items() if k[1] == 0}, lambda name: (name, False))

    def test_a_mega_formes_base_species_is_the_engines(self):
        # The engine's own forme data (duoforge_data_forme_info's base_species), never a name rule: Floette-Mega's
        # users bring Floette-Eternal, Meowstic-M-Mega's Meowstic.
        from duoforge import data as ddata
        from duoforge_search import smogon_spreads as ss
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            base = ss.engine_base(ctx)
            self.assertEqual(base("Floette-Mega"), ("floetteeternal", True))
            meowstic = ddata.name(ctx, ddata.TABLE_SPECIES,
                                  ddata.forme_info(ctx, ddata.find(ctx, ddata.TABLE_SPECIES, "meowsticmmega"))["base_species"])
            self.assertEqual(base("Meowstic-M-Mega"), (meowstic, True))
            self.assertEqual(base("Garchomp-Mega-Z"), ("garchomp", True))
            self.assertEqual(base("Toxapex"), ("toxapex", False))
            self.assertIsNone(base("Notamon"))

    def test_the_raw_stats_never_lie_in_the_repository(self):
        from duoforge_search import smogon_spreads as ss
        inside = os.path.join(os.path.dirname(os.path.abspath(ss.__file__)), "smogon-raw")
        with self.assertRaisesRegex(SystemExit, "inside the repository"):
            ss.main(["--stats", inside])
        self.assertFalse(os.path.exists(inside))

    def test_weights_become_whole_draws_and_the_light_ones_are_counted(self):
        from duoforge_search import smogon_spreads as ss
        chosen = {"Toxapex": (1760, {("Bold", (32, 0, 18, 0, 16, 0)): 3.0, ("Calm", (32, 0, 16, 0, 18, 0)): 1.0,
                                     ("Bold", (0, 0, 0, 0, 0, 1)): 1e-6})}
        derived, dropped = ss.quantize(chosen)
        self.assertEqual(derived, {"Toxapex": {"cutoff": 1760, "spreads": [["Bold", "32/0/18/0/16/0", 750],
                                                                           ["Calm", "32/0/16/0/18/0", 250]]}})
        self.assertEqual(dropped, {"below_resolution": 1, "beyond_max_spreads": 0})  # too light for one draw
        many = {"Toxapex": (0, {("Bold", (i % 33, 0, 0, 0, 0, i // 33)): 1.0 + i for i in range(ss.MAX_SPREADS + 5)})}
        kept, dropped = ss.quantize(many)
        self.assertEqual(len(kept["Toxapex"]["spreads"]), ss.MAX_SPREADS)  # the heaviest MAX_SPREADS, renormalised
        self.assertEqual(sum(n for _, _, n in kept["Toxapex"]["spreads"]), ss.RESOLUTION)
        self.assertEqual(dropped["beyond_max_spreads"], 5)

    def test_rows_repeat_each_spread_by_its_draws_and_count_unknown_species(self):
        from duoforge import data as ddata
        from duoforge_search import smogon_spreads as ss
        derived = {"Toxapex": {"cutoff": 1760, "spreads": [["Bold", "32/0/18/0/16/0", 3], ["Calm", "32/0/16/0/18/0", 1]]},
                   "Notamon": {"cutoff": 1760, "spreads": [["Bold", "32/0/18/0/16/0", 5]]}}
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            (team, species, nature, item, spreads), counts = ss.rows(ctx, derived)
            toxapex = ddata.find(ctx, ddata.TABLE_SPECIES, "toxapex")
            bold = ddata.find(ctx, ddata.TABLE_NATURE, "bold")
        self.assertEqual(species, [toxapex] * 4)
        self.assertEqual((set(team), set(item)), ({-1}, {-1}))  # no team to leave out; no item stated with a spread
        self.assertEqual([n == bold for n in nature], [True, True, True, False])
        self.assertEqual([list(x) for x in spreads[:1]], [[32, 0, 18, 0, 16, 0]])
        self.assertEqual(counts, {"species": 1, "outside_context": 1})

    def test_the_committed_table_credits_its_source_and_renders_as_committed(self):
        # Owner 2026-10-12: a derived table may be committed with credits; the raw stats stay outside the repository.
        from duoforge_search import smogon_spreads as ss
        table = ss.load_table()
        header = table["source"]
        self.assertIn("smogon.com/stats", header["credit"])
        self.assertEqual(header["month"], ss.MONTH)
        self.assertEqual(header["cutoffs"], list(ss.CUTOFFS))
        self.assertEqual(header["files"], ss.SOURCES)
        self.assertIn("toxapex", table["species"])
        self.assertIn("floetteeternal", table["species"])  # Floette-Mega's spreads, under the engine's base species
        tox = table["species"]["toxapex"]["spreads"]
        self.assertEqual(sum(n for _, _, n in tox), ss.RESOLUTION)
        with open(ss.TABLE_PATH, "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), ss.TABLE_SHA256)  # the pin of the committed file
        self.assertEqual(ss.render(table), open(ss.TABLE_PATH, encoding="utf-8").read())  # one rendering: --check

    def test_the_cached_files_must_be_the_pinned_ones(self):
        from duoforge_search import smogon_spreads as ss
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(honest.SearchError, "missing"):
                ss.load(tmp)
            for name in ss.SOURCES:
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
                    json.dump(self.stats({}), f)
            with self.assertRaisesRegex(honest.SearchError, "pinned"):
                ss.load(tmp)


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
