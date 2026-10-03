/*
 * duoforge.search.expand: duoforge_batch_expand (decision 0022).
 *
 * - Every leaf equals the single-battle sequence clone, reseed with
 *   duoforge_search_seeds, step and the encoder's row of the viewer, over
 *   random play of Teams A, B and C under POOL (records in the mask), with
 *   roots at TEAM_SELECTION, TURN and REPLACEMENT and TERMINAL leaves.
 * - 1, 2, 3, 4, 8 and 16 workers give the same bytes and digests.
 * - A leaf does not depend on its position, only on its root, choices and
 *   sample, so a sample's seeds are the same in every cell.
 * - A leaf environment's TERMINAL flag follows its battle.
 * - The roots are unchanged.
 * - The step's refusals and the encoder's are apart, and a refused leaf
 *   leaves the others alone (SYNTHETIC data refuses every combat step).
 * - The argument checks touch no leaf.
 */
#include <string.h>

#include <duoforge/duoforge_search.h>

#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"
#include "support/team_c.h"

#define ROOTS 8u
#define LEAVES 144u
#define PER_PLAYER 3u /* choices per requested player and root */
#define SAMPLES 2u
#define ROUNDS 48u
#define SEED 0x2026100300000221u
#define ARENA 0x2026100300000222u
#define V4 850u
#define VARIANTS 6u

static const uint32_t worker_counts[VARIANTS] = {1u, 2u, 3u, 4u, 8u, 16u};

/* The query of the roots. */
typedef struct root_query {
    duoforge_request requests[2u * ROOTS];
    duoforge_observation observations[2u * ROOTS];
    duoforge_factored_domain domains[2u * ROOTS];
} root_query;

/* The inputs of one call. */
typedef struct plan {
    uint32_t count;
    uint64_t keys[ROOTS];
    uint8_t viewers[ROOTS];
    uint32_t root_envs[LEAVES];
    uint32_t samples[LEAVES];
    duoforge_factored_choice choices[2u * LEAVES];
} plan;

/* The outputs of one call. */
typedef struct outputs {
    duoforge_status step_statuses[LEAVES];
    duoforge_status encode_statuses[LEAVES];
    duoforge_step_result results[LEAVES];
    uint32_t leaf_results[LEAVES];
    float obs[LEAVES * V4];
} outputs;

static root_query query;
static plan the_plan;
static outputs out[VARIANTS];
static float ref_obs[V4];
static float ref_slots[DUOFORGE_ENCODER_SLOT_VALUES];
static uint8_t ref_pairs[DUOFORGE_ENCODER_PAIR_VALUES];

static uint64_t next(uint64_t *s)
{
    uint64_t z = (*s += 0x9E3779B97F4A7C15u);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9u;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBu;
    return z ^ (z >> 31);
}

/* side 0 of reference setup p (Team A for 0, B for 1); Team C put explicitly. */
static void team(char letter, duoforge_side_setup *side)
{
    if (letter == 'C') {
        df_put_team_c(side);
        return;
    }
    duoforge_battle_setup s;
    (void)duoforge_reference_setup(letter == 'A' ? 0u : 1u, &s);
    *side = s.sides[0];
}

static duoforge_battle_setup setups[LEAVES];

static void make_setups(void)
{
    static const char pairs[ROOTS][2] = {{'A', 'B'}, {'B', 'C'}, {'C', 'A'}, {'C', 'C'},
                                         {'A', 'A'}, {'B', 'A'}, {'C', 'B'}, {'A', 'C'}};
    for (uint32_t e = 0u; e < LEAVES; ++e) {
        memset(&setups[e], 0, sizeof setups[e]);
        team(pairs[e % ROOTS][0], &setups[e].sides[0]);
        team(pairs[e % ROOTS][1], &setups[e].sides[1]);
    }
}

static duoforge_batch *make(df_test *t, const duoforge_context *ctx, const duoforge_battle_setup *s, uint32_t envs,
                            uint32_t workers)
{
    duoforge_batch_config c = {envs, workers, ARENA, s};
    duoforge_batch *b = NULL;
    DF_CHECK(t, duoforge_batch_create(ctx, &c, &b) == DUOFORGE_OK);
    return b;
}

/* A random choice in domain d: an allowed pair, or random distinct picks. */
static duoforge_factored_choice random_choice(const duoforge_factored_domain *d, uint64_t *s)
{
    duoforge_factored_choice c;
    memset(&c, 0, sizeof c);
    if (d->kind == DUOFORGE_CHOICE_TEAM_SELECTION) {
        uint8_t order[DUOFORGE_MAX_ROSTER];
        for (uint8_t k = 0u; k < d->member_count; ++k) {
            order[k] = k;
        }
        for (uint32_t k = d->member_count; k > 1u; --k) {
            const uint32_t j = (uint32_t)(next(s) % k);
            const uint8_t tmp = order[k - 1u];
            order[k - 1u] = order[j];
            order[j] = tmp;
        }
        memcpy(c.picks, order, d->pick_count);
    } else if (d->kind == DUOFORGE_CHOICE_SLOTS) {
        uint32_t allowed = 0u;
        for (uint32_t i = 0u; i < d->slot_count[0]; ++i) {
            for (uint32_t j = 0u; j < d->slot_count[1]; ++j) {
                allowed += (d->allowed[i] >> j) & 1u;
            }
        }
        uint32_t pick = allowed > 0u ? (uint32_t)(next(s) % allowed) : 0u;
        for (uint32_t i = 0u; i < d->slot_count[0]; ++i) {
            for (uint32_t j = 0u; j < d->slot_count[1]; ++j) {
                if (((d->allowed[i] >> j) & 1u) != 0u && pick-- == 0u) {
                    c.slot[0] = (uint8_t)i;
                    c.slot[1] = (uint8_t)j;
                }
            }
        }
    }
    return c;
}

/* The bundle built independently of the engine's builder. */
static bool build_bundle(const duoforge_request *rq, const duoforge_factored_domain *d,
                         const duoforge_factored_choice *c, duoforge_decision_bundle *b)
{
    memset(b, 0, sizeof *b);
    b->epoch = rq[0].epoch;
    for (uint32_t p = 0u; p < 2u; ++p) {
        if (rq[p].requested == 0u) {
            continue;
        }
        duoforge_side_choice *o = &b->responses[p];
        o->epoch = d[p].epoch;
        o->side = (uint8_t)p;
        o->kind = d[p].kind;
        if (d[p].kind == DUOFORGE_CHOICE_TEAM_SELECTION) {
            o->pick_count = d[p].pick_count;
            memcpy(o->picks, c[p].picks, sizeof o->picks);
        } else if (d[p].kind == DUOFORGE_CHOICE_SLOTS) {
            const uint32_t i = c[p].slot[0];
            const uint32_t j = c[p].slot[1];
            if (i >= d[p].slot_count[0] || j >= d[p].slot_count[1] || ((d[p].allowed[i] >> j) & 1u) == 0u) {
                return false;
            }
            o->slots[0] = d[p].slots[0][i];
            o->slots[1] = d[p].slots[1][j];
        } else {
            return false;
        }
        b->response_mask = (uint8_t)(b->response_mask | (1u << p));
    }
    return true;
}

static bool records_of(uint64_t mask)
{
    const uint64_t base = (UINT64_C(1) << DUOFORGE_VIEWEXT_FEATURE_WEATHER_SAND) |
                          (UINT64_C(1) << DUOFORGE_VIEWEXT_FEATURE_WEATHER_SNOW) |
                          (UINT64_C(1) << DUOFORGE_VIEWEXT_FEATURE_TERRAIN_ELECTRIC) |
                          (UINT64_C(1) << DUOFORGE_VIEWEXT_FEATURE_TERRAIN_MISTY) |
                          (UINT64_C(1) << DUOFORGE_VIEWEXT_FEATURE_AILMENT_TOX);
    return (mask & ~base) != 0u;
}

static bool row_is_zero(const float *row, uint32_t width)
{
    for (uint32_t k = 0u; k < width; ++k) {
        if (row[k] != 0.0f) {
            return false;
        }
    }
    return true;
}

static void digest_of(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, uint8_t *d)
{
    DF_CHECK(t, duoforge_battle_digest(ctx, b, d) == DUOFORGE_OK);
}

typedef struct tally {
    uint32_t leaves, terminal, refused, encoded;
    uint32_t root_kinds[DUOFORGE_BOUNDARY_COUNT + 1u];
} tally;

/* Leaf i of output o against the single-battle sequence. */
static void check_leaf(df_test *t, const duoforge_context *ctx, const duoforge_batch *roots,
                       const duoforge_batch *leaves, const root_query *q, const plan *pl, const outputs *o,
                       uint32_t i, uint32_t version, uint64_t mask, uint32_t width, tally *ty)
{
    const uint32_t r = pl->root_envs[i];
    duoforge_battle *ref = NULL;
    if (!DF_CHECK(t, duoforge_battle_clone(ctx, duoforge_batch_env(roots, r), &ref) == DUOFORGE_OK)) {
        return;
    }
    uint64_t initstate = 0u;
    uint64_t initseq = 0u;
    duoforge_search_seeds(SEED, pl->keys[r], pl->samples[i], &initstate, &initseq);
    DF_CHECK(t, duoforge_battle_reseed(ctx, ref, initstate, initseq) == DUOFORGE_OK);
    duoforge_decision_bundle bundle;
    duoforge_step_result rr;
    memset(&rr, 0, sizeof rr);
    duoforge_status st = DUOFORGE_E_INVALID_ARGUMENT;
    if (build_bundle(&q->requests[2u * r], &q->domains[2u * r], &pl->choices[2u * i], &bundle)) {
        st = duoforge_battle_step(ctx, ref, &bundle, &rr);
    }
    ++ty->leaves;
    DF_CHECK_EQ_U64(t, o->step_statuses[i], st);
    DF_CHECK(t, memcmp(&o->results[i], &rr, sizeof rr) == 0);
    uint8_t want[DUOFORGE_DIGEST_SIZE];
    uint8_t got[DUOFORGE_DIGEST_SIZE];
    digest_of(t, ctx, ref, want);
    digest_of(t, ctx, duoforge_batch_env(leaves, i), got);
    DF_CHECK(t, memcmp(want, got, sizeof want) == 0);
    const float *row = &o->obs[(size_t)i * width];
    if (st != DUOFORGE_OK) {
        ++ty->refused;
        DF_CHECK(t, o->encode_statuses[i] == DUOFORGE_OK && o->leaf_results[i] == 0u && row_is_zero(row, width));
    } else if (rr.boundary_kind == DUOFORGE_BOUNDARY_TERMINAL) {
        ++ty->terminal;
        uint32_t result = 0u;
        DF_CHECK(t, duoforge_battle_result(ctx, ref, &result) == DUOFORGE_OK && result != 0u);
        DF_CHECK_EQ_U64(t, o->leaf_results[i], result);
        DF_CHECK(t, o->encode_statuses[i] == DUOFORGE_OK && row_is_zero(row, width));
    } else {
        const uint32_t viewer = pl->viewers[r];
        duoforge_observation ob;
        duoforge_factored_domain dom;
        static duoforge_observation_ext ext;
        DF_CHECK(t, duoforge_battle_observe(ctx, ref, viewer, &ob) == DUOFORGE_OK);
        DF_CHECK(t, duoforge_battle_factored(ctx, ref, viewer, &dom) == DUOFORGE_OK);
        const bool records = records_of(mask);
        if (records) {
            DF_CHECK(t, duoforge_battle_observe_ext(ctx, ref, viewer, &ext) == DUOFORGE_OK);
        }
        const duoforge_status enc =
            duoforge_encode(version, mask, &ob, &dom, records ? &ext : NULL, ref_obs, ref_slots, ref_pairs);
        DF_CHECK_EQ_U64(t, o->encode_statuses[i], enc);
        DF_CHECK(t, memcmp(ref_obs, row, (size_t)width * sizeof *row) == 0);
        DF_CHECK_EQ_U64(t, o->leaf_results[i], 0u);
        ty->encoded += enc == DUOFORGE_OK;
    }
    duoforge_battle_destroy(ref);
}

/* Up to PER_PLAYER choices per requested player of every root that is not
   TERMINAL, crossed, SAMPLES samples each; the plan repeats cyclically until
   it fills every leaf environment, so each environment is overwritten. */
static void make_plan(const root_query *q, uint64_t *s, uint32_t round, plan *pl, tally *ty)
{
    static duoforge_factored_choice mine[PER_PLAYER];
    static duoforge_factored_choice theirs[PER_PLAYER];
    uint32_t n = 0u;
    for (uint32_t r = 0u; r < ROOTS; ++r) {
        const duoforge_request *rq = &q->requests[2u * r];
        pl->viewers[r] = (uint8_t)((r + round) % 2u);
        pl->keys[r] = next(s);
        if (rq[0].requested == 0u && rq[1].requested == 0u) {
            continue; /* TERMINAL */
        }
        ++ty->root_kinds[rq[0].boundary_kind <= DUOFORGE_BOUNDARY_COUNT ? rq[0].boundary_kind : 0u];
        const uint32_t a = rq[0].requested != 0u ? PER_PLAYER : 1u;
        const uint32_t b = rq[1].requested != 0u ? PER_PLAYER : 1u;
        for (uint32_t k = 0u; k < PER_PLAYER; ++k) {
            mine[k] = random_choice(&q->domains[2u * r], s);
            theirs[k] = random_choice(&q->domains[2u * r + 1u], s);
        }
        for (uint32_t x = 0u; x < a; ++x) {
            for (uint32_t y = 0u; y < b; ++y) {
                for (uint32_t z = 0u; z < SAMPLES && n < LEAVES; ++z) {
                    pl->root_envs[n] = r;
                    pl->samples[n] = z + round % 3u;
                    pl->choices[2u * n] = mine[x];
                    pl->choices[2u * n + 1u] = theirs[y];
                    ++n;
                }
            }
        }
    }
    for (uint32_t k = n; k < LEAVES && n > 0u; ++k) {
        const uint32_t from = k % n;
        pl->root_envs[k] = pl->root_envs[from];
        pl->samples[k] = pl->samples[from];
        pl->choices[2u * k] = pl->choices[2u * from];
        pl->choices[2u * k + 1u] = pl->choices[2u * from + 1u];
    }
    pl->count = n > 0u ? LEAVES : 0u;
}

static duoforge_status expand(duoforge_batch *leaves, const duoforge_batch *roots, uint32_t version, uint64_t mask,
                              const root_query *q, const plan *pl, uint32_t count, outputs *o)
{
    return duoforge_batch_expand(leaves, roots, version, mask, SEED, q->requests, q->domains, pl->keys, pl->viewers,
                                 count, pl->root_envs, pl->samples, pl->choices, o->step_statuses,
                                 o->encode_statuses, o->results, o->leaf_results, o->obs);
}

/* The lowest failing step status, else the lowest failing encode status. */
static duoforge_status first_failure(const outputs *o, uint32_t count)
{
    for (uint32_t i = 0u; i < count; ++i) {
        if (o->step_statuses[i] != DUOFORGE_OK) {
            return o->step_statuses[i];
        }
    }
    for (uint32_t i = 0u; i < count; ++i) {
        if (o->encode_statuses[i] != DUOFORGE_OK) {
            return o->encode_statuses[i];
        }
    }
    return DUOFORGE_OK;
}

static void random_step(df_test *t, duoforge_batch *roots, const root_query *q, uint64_t *s)
{
    static duoforge_factored_choice choices[2u * ROOTS];
    static duoforge_status statuses[ROOTS];
    static duoforge_step_result results[ROOTS];
    for (uint32_t k = 0u; k < 2u * ROOTS; ++k) {
        choices[k] = random_choice(&q->domains[k], s);
    }
    DF_CHECK(t, duoforge_batch_step_factored(roots, q->requests, q->domains, choices, statuses, results) ==
                    DUOFORGE_OK);
    DF_CHECK(t, duoforge_batch_reset_terminal(roots) == DUOFORGE_OK);
}

/* The digests of every environment of b. */
static void digests(df_test *t, const duoforge_context *ctx, const duoforge_batch *b, uint32_t envs,
                    uint8_t (*d)[DUOFORGE_DIGEST_SIZE])
{
    for (uint32_t e = 0u; e < envs; ++e) {
        digest_of(t, ctx, duoforge_batch_env(b, e), d[e]);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.search.expand");
    make_setups();
    static uint8_t before[LEAVES][DUOFORGE_DIGEST_SIZE];
    static uint8_t after[LEAVES][DUOFORGE_DIGEST_SIZE];

    duoforge_context *pool = df_make_context(&df_config_pool);
    duoforge_batch *roots = make(&t, pool, setups, ROOTS, 4u);
    duoforge_batch *leaves[VARIANTS];
    for (uint32_t v = 0u; v < VARIANTS; ++v) {
        leaves[v] = make(&t, pool, setups, LEAVES, worker_counts[v]);
    }
    /* The mask: every feature the POOL records support (records in every row). */
    DF_CHECK(&t, duoforge_batch_query_factored(roots, query.requests, query.observations, query.domains) ==
                     DUOFORGE_OK);
    static duoforge_observation_ext root_ext[2u * ROOTS];
    DF_CHECK(&t, duoforge_batch_observe_ext(roots, root_ext) == DUOFORGE_OK);
    const uint64_t supported = root_ext[0].supported;
    DF_CHECK(&t, root_ext[0].revision != 0u && supported != 0u);

    /* test_leaves_equal_the_single_battle_sequence, test_worker_counts_agree,
       test_terminal_flag_follows_the_battle, test_roots_are_unchanged */
    {
        uint64_t stream = 0x2026100300000400u;
        tally ty;
        memset(&ty, 0, sizeof ty);
        for (uint32_t round = 0u; round < ROUNDS; ++round) {
            DF_CHECK(&t, duoforge_batch_query_factored(roots, query.requests, query.observations, query.domains) ==
                             DUOFORGE_OK);
            make_plan(&query, &stream, round, &the_plan, &ty);
            digests(&t, pool, roots, ROOTS, before);
            for (uint32_t v = 0u; v < VARIANTS; ++v) {
                const duoforge_status st = expand(leaves[v], roots, 4u, supported, &query, &the_plan,
                                                  the_plan.count, &out[v]);
                DF_CHECK_EQ_U64(&t, st, first_failure(&out[v], the_plan.count));
            }
            digests(&t, pool, roots, ROOTS, after);
            DF_CHECK(&t, memcmp(before, after, ROOTS * sizeof before[0]) == 0);
            for (uint32_t i = 0u; i < the_plan.count; ++i) {
                check_leaf(&t, pool, roots, leaves[0], &query, &the_plan, &out[0], i, 4u, supported, V4, &ty);
            }
            for (uint32_t v = 1u; v < VARIANTS; ++v) {
                DF_CHECK(&t, memcmp(&out[0], &out[v], sizeof out[0]) == 0);
                digests(&t, pool, leaves[0], the_plan.count, before);
                digests(&t, pool, leaves[v], the_plan.count, after);
                DF_CHECK(&t, memcmp(before, after, the_plan.count * sizeof before[0]) == 0);
            }
            /* the TERMINAL flag: reset_terminal starts the next episode exactly in the TERMINAL leaves */
            uint32_t episodes[LEAVES];
            for (uint32_t i = 0u; i < LEAVES; ++i) {
                episodes[i] = duoforge_batch_env_episode(leaves[0], i);
            }
            DF_CHECK(&t, duoforge_batch_reset_terminal(leaves[0]) == DUOFORGE_OK);
            for (uint32_t i = 0u; i < the_plan.count; ++i) {
                const bool reset = duoforge_batch_env_episode(leaves[0], i) != episodes[i];
                DF_CHECK(&t, reset == (out[0].leaf_results[i] != 0u));
            }
            random_step(&t, roots, &query, &stream);
        }
        DF_CHECK(&t, ty.leaves >= ROUNDS * ROOTS); /* every round expanded */
        DF_CHECK(&t, ty.terminal > 0u);           /* TERMINAL leaves were met */
        DF_CHECK(&t, ty.encoded > 0u);
        DF_CHECK(&t, ty.root_kinds[DUOFORGE_BOUNDARY_TEAM_SELECTION] > 0u && ty.root_kinds[DUOFORGE_BOUNDARY_TURN] > 0u &&
                         ty.root_kinds[DUOFORGE_BOUNDARY_REPLACEMENT] > 0u);
    }

    /* test_samples_share_seeds_across_cells: a leaf depends on its root, choices and sample only, not on its
       position (or so on its cell), so one leaf moved to another position gives the same battle and row */
    {
        DF_CHECK(&t, duoforge_batch_query_factored(roots, query.requests, query.observations, query.domains) ==
                         DUOFORGE_OK);
        uint64_t stream = 0x2026100300000401u;
        tally ty;
        memset(&ty, 0, sizeof ty);
        make_plan(&query, &stream, 0u, &the_plan, &ty);
        DF_CHECK(&t, expand(leaves[0], roots, 4u, supported, &query, &the_plan, the_plan.count, &out[0]) ==
                         first_failure(&out[0], the_plan.count));
        static plan moved;
        moved = the_plan;
        moved.root_envs[LEAVES - 1u] = the_plan.root_envs[0];
        moved.samples[LEAVES - 1u] = the_plan.samples[0];
        moved.choices[2u * (LEAVES - 1u)] = the_plan.choices[0];
        moved.choices[2u * (LEAVES - 1u) + 1u] = the_plan.choices[1];
        DF_CHECK(&t, expand(leaves[1], roots, 4u, supported, &query, &moved, moved.count, &out[1]) ==
                         first_failure(&out[1], moved.count));
        DF_CHECK_EQ_U64(&t, out[1].step_statuses[LEAVES - 1u], out[0].step_statuses[0]);
        DF_CHECK(&t, memcmp(&out[1].obs[(size_t)(LEAVES - 1u) * V4], &out[0].obs[0], V4 * sizeof out[0].obs[0]) == 0);
        uint8_t a[DUOFORGE_DIGEST_SIZE];
        uint8_t b[DUOFORGE_DIGEST_SIZE];
        digest_of(&t, pool, duoforge_batch_env(leaves[0], 0u), a);
        digest_of(&t, pool, duoforge_batch_env(leaves[1], LEAVES - 1u), b);
        DF_CHECK(&t, memcmp(a, b, sizeof a) == 0);
    }

    /* test_step_and_encode_statuses_are_apart: (a) a pair outside the domain is the step's refusal; (b) a mask
       bit the records do not support is the encoder's refusal, after a step that succeeded */
    {
        DF_CHECK(&t, duoforge_batch_query_factored(roots, query.requests, query.observations, query.domains) ==
                         DUOFORGE_OK);
        uint64_t stream = 0x2026100300000402u;
        tally ty;
        memset(&ty, 0, sizeof ty);
        make_plan(&query, &stream, 1u, &the_plan, &ty);
        /* (a) */
        static plan bad;
        bad = the_plan;
        uint32_t target = LEAVES;
        for (uint32_t i = 0u; i < bad.count && target == LEAVES; ++i) {
            const uint32_t r = bad.root_envs[i];
            if (query.requests[2u * r].requested != 0u && query.domains[2u * r].kind == DUOFORGE_CHOICE_SLOTS) {
                target = i;
            }
        }
        if (DF_CHECK(&t, target < LEAVES)) {
            bad.choices[2u * target].slot[0] = DUOFORGE_MAX_SLOT_OPTIONS - 1u; /* past every slot list */
            bad.choices[2u * target].slot[1] = DUOFORGE_MAX_SLOT_OPTIONS - 1u;
            const duoforge_status st = expand(leaves[0], roots, 4u, supported, &query, &bad, bad.count, &out[0]);
            DF_CHECK_EQ_U64(&t, out[0].step_statuses[target], DUOFORGE_E_INVALID_ARGUMENT);
            DF_CHECK(&t, out[0].encode_statuses[target] == DUOFORGE_OK &&
                             row_is_zero(&out[0].obs[(size_t)target * V4], V4));
            DF_CHECK_EQ_U64(&t, st, first_failure(&out[0], bad.count));
            DF_CHECK_EQ_U64(&t, st, DUOFORGE_E_INVALID_ARGUMENT);
            for (uint32_t i = 0u; i < bad.count; ++i) {
                check_leaf(&t, pool, roots, leaves[0], &query, &bad, &out[0], i, 4u, supported, V4, &ty);
            }
        }
        /* (b): the lowest version-4 feature the records do not support */
        uint32_t missing = DUOFORGE_VIEWEXT_FEATURE_COUNT;
        for (uint32_t k = 0u; k < DUOFORGE_VIEWEXT_FEATURE_COUNT && missing == DUOFORGE_VIEWEXT_FEATURE_COUNT; ++k) {
            if (((supported >> k) & 1u) == 0u) {
                missing = k;
            }
        }
        /* When the POOL records support every feature, this case needs another source of an encoder refusal. */
        if (DF_CHECK(&t, missing < DUOFORGE_VIEWEXT_FEATURE_COUNT)) {
            const uint64_t mask = supported | (UINT64_C(1) << missing);
            const duoforge_status st = expand(leaves[0], roots, 4u, mask, &query, &the_plan, the_plan.count, &out[0]);
            uint32_t refused_rows = 0u;
            for (uint32_t i = 0u; i < the_plan.count; ++i) {
                check_leaf(&t, pool, roots, leaves[0], &query, &the_plan, &out[0], i, 4u, mask, V4, &ty);
                if (out[0].step_statuses[i] == DUOFORGE_OK && out[0].leaf_results[i] == 0u) {
                    DF_CHECK_EQ_U64(&t, out[0].encode_statuses[i], DUOFORGE_E_UNSUPPORTED);
                    DF_CHECK(&t, row_is_zero(&out[0].obs[(size_t)i * V4], V4));
                    ++refused_rows;
                }
            }
            DF_CHECK(&t, refused_rows > 0u);
            DF_CHECK_EQ_U64(&t, st, first_failure(&out[0], the_plan.count));
            DF_CHECK_EQ_U64(&t, st, DUOFORGE_E_UNSUPPORTED);
        }
    }

    /* test_refused_step_is_isolated: SYNTHETIC data refuses every combat step (E_UNSUPPORTED); a root still
       at TEAM_SELECTION steps in the same call */
    {
        duoforge_context *c1 = df_make_context(&df_config_c1);
        static duoforge_battle_setup g1[4];
        df_setup_g1(&g1[0]);
        for (uint32_t k = 1u; k < 4u; ++k) {
            g1[k] = g1[0];
        }
        duoforge_batch *sroots = make(&t, c1, g1, 2u, 1u);
        duoforge_batch *sleaves = make(&t, c1, g1, 4u, 2u);
        static root_query sq;
        static plan sp;
        DF_CHECK(&t, duoforge_batch_query_factored(sroots, sq.requests, sq.observations, sq.domains) == DUOFORGE_OK);
        /* root 1 to TURN; root 0 stays at TEAM_SELECTION (its picks repeat a member: refused) */
        static duoforge_factored_choice picks[4];
        static duoforge_status statuses[2];
        static duoforge_step_result results[2];
        memset(picks, 0, sizeof picks);
        for (uint32_t p = 2u; p < 4u; ++p) {
            for (uint8_t k = 0u; k < 4u; ++k) {
                picks[p].picks[k] = k;
            }
        }
        (void)duoforge_batch_step_factored(sroots, sq.requests, sq.domains, picks, statuses, results);
        DF_CHECK(&t, statuses[0] == DUOFORGE_E_INVALID_ARGUMENT && statuses[1] == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_batch_query_factored(sroots, sq.requests, sq.observations, sq.domains) == DUOFORGE_OK);
        DF_CHECK(&t, sq.requests[0].boundary_kind == DUOFORGE_BOUNDARY_TEAM_SELECTION &&
                         sq.requests[2].boundary_kind == DUOFORGE_BOUNDARY_TURN);
        memset(&sp, 0, sizeof sp);
        uint64_t stream = 0x2026100300000403u;
        sp.keys[0] = next(&stream);
        sp.keys[1] = next(&stream);
        for (uint32_t i = 0u; i < 4u; ++i) {
            sp.root_envs[i] = i % 2u; /* leaves 0 and 2 at TEAM_SELECTION, 1 and 3 at TURN */
            sp.samples[i] = i / 2u;
            sp.choices[2u * i] = random_choice(&sq.domains[2u * sp.root_envs[i]], &stream);
            sp.choices[2u * i + 1u] = random_choice(&sq.domains[2u * sp.root_envs[i] + 1u], &stream);
        }
        const duoforge_status st = expand(sleaves, sroots, 4u, 0u, &sq, &sp, 4u, &out[0]);
        tally ty;
        memset(&ty, 0, sizeof ty);
        for (uint32_t i = 0u; i < 4u; ++i) {
            check_leaf(&t, c1, sroots, sleaves, &sq, &sp, &out[0], i, 4u, 0u, V4, &ty);
        }
        DF_CHECK(&t, out[0].step_statuses[0] == DUOFORGE_OK && out[0].step_statuses[2] == DUOFORGE_OK);
        DF_CHECK(&t, out[0].step_statuses[1] == DUOFORGE_E_UNSUPPORTED &&
                         out[0].step_statuses[3] == DUOFORGE_E_UNSUPPORTED);
        DF_CHECK_EQ_U64(&t, st, DUOFORGE_E_UNSUPPORTED);
        duoforge_batch_destroy(sleaves);
        duoforge_batch_destroy(sroots);
        duoforge_context_destroy(c1);
    }

    /* test_checks_touch_no_leaf */
    {
        DF_CHECK(&t, duoforge_batch_query_factored(roots, query.requests, query.observations, query.domains) ==
                         DUOFORGE_OK);
        uint64_t stream = 0x2026100300000404u;
        tally ty;
        memset(&ty, 0, sizeof ty);
        make_plan(&query, &stream, 2u, &the_plan, &ty);
        duoforge_batch *lv = leaves[2];
        outputs *o = &out[2];
        plan *pl = &the_plan;
        digests(&t, pool, lv, LEAVES, before);
        const uint64_t m = supported;
        const duoforge_request *rq = query.requests;
        const duoforge_factored_domain *dm = query.domains;
        DF_CHECK(&t, duoforge_batch_expand(NULL, roots, 4u, m, SEED, rq, dm, pl->keys, pl->viewers, 1u, pl->root_envs,
                                           pl->samples, pl->choices, o->step_statuses, o->encode_statuses, o->results,
                                           o->leaf_results, o->obs) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_batch_expand(lv, NULL, 4u, m, SEED, rq, dm, pl->keys, pl->viewers, 1u, pl->root_envs,
                                           pl->samples, pl->choices, o->step_statuses, o->encode_statuses, o->results,
                                           o->leaf_results, o->obs) == DUOFORGE_E_NULL_ARGUMENT);
        for (uint32_t k = 0u; k < 12u; ++k) {
            const duoforge_status st = duoforge_batch_expand(
                lv, roots, 4u, m, SEED, k == 0u ? NULL : rq, k == 1u ? NULL : dm, k == 2u ? NULL : pl->keys,
                k == 3u ? NULL : pl->viewers, 1u, k == 4u ? NULL : pl->root_envs, k == 5u ? NULL : pl->samples,
                k == 6u ? NULL : pl->choices, k == 7u ? NULL : o->step_statuses, k == 8u ? NULL : o->encode_statuses,
                k == 9u ? NULL : o->results, k == 10u ? NULL : o->leaf_results, k == 11u ? NULL : o->obs);
            DF_CHECK_EQ_U64(&t, st, DUOFORGE_E_NULL_ARGUMENT);
        }
        DF_CHECK(&t, duoforge_batch_expand(lv, roots, 4u, m, SEED, NULL, NULL, NULL, NULL, 0u, NULL, NULL, NULL, NULL,
                                           NULL, NULL, NULL, NULL) == DUOFORGE_OK);
        /* another context */
        duoforge_context *tc = df_make_context(&df_config_team_c);
        duoforge_batch *other = make(&t, tc, setups, ROOTS, 1u);
        DF_CHECK_EQ_U64(&t, expand(lv, other, 4u, m, &query, pl, 1u, o), DUOFORGE_E_CONTEXT_MISMATCH);
        duoforge_batch_destroy(other);
        duoforge_context_destroy(tc);
        /* version and mask, as duoforge_batch_query_encoded checks them */
        const uint64_t roost = UINT64_C(1) << DUOFORGE_VIEWEXT_FEATURE_ROOST;
        DF_CHECK_EQ_U64(&t, expand(lv, roots, 0u, 0u, &query, pl, 1u, o), DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK_EQ_U64(&t, expand(lv, roots, 5u, 0u, &query, pl, 1u, o), DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK_EQ_U64(&t, expand(lv, roots, 3u, roost, &query, pl, 1u, o), DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK_EQ_U64(&t, expand(lv, roots, 4u, UINT64_C(1) << 42, &query, pl, 1u, o), DUOFORGE_E_INVALID_ARGUMENT);
        /* the same batch, the count, a root environment, a viewer */
        DF_CHECK_EQ_U64(&t, expand(roots, roots, 4u, m, &query, pl, 1u, o), DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK_EQ_U64(&t, expand(lv, roots, 4u, m, &query, pl, LEAVES + 1u, o), DUOFORGE_E_INVALID_ARGUMENT);
        static plan off;
        off = the_plan;
        off.root_envs[3] = ROOTS;
        DF_CHECK_EQ_U64(&t, expand(lv, roots, 4u, m, &query, &off, 4u, o), DUOFORGE_E_INVALID_ARGUMENT);
        off = the_plan;
        off.viewers[off.root_envs[2]] = 2u;
        DF_CHECK_EQ_U64(&t, expand(lv, roots, 4u, m, &query, &off, 4u, o), DUOFORGE_E_INVALID_ARGUMENT);
        digests(&t, pool, lv, LEAVES, after);
        DF_CHECK(&t, memcmp(before, after, sizeof before) == 0);
    }

    for (uint32_t v = 0u; v < VARIANTS; ++v) {
        duoforge_batch_destroy(leaves[v]);
    }
    duoforge_batch_destroy(roots);
    duoforge_context_destroy(pool);
    return df_test_end(&t);
}
