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

/* A random step that leaves TERMINAL environments as they are. */
static void random_step_keep(df_test *t, duoforge_batch *roots, const root_query *q, uint64_t *s)
{
    static duoforge_factored_choice choices[2u * ROOTS];
    static duoforge_status statuses[ROOTS];
    static duoforge_step_result results[ROOTS];
    for (uint32_t k = 0u; k < 2u * ROOTS; ++k) {
        choices[k] = random_choice(&q->domains[k], s);
    }
    DF_CHECK(t, duoforge_batch_step_factored(roots, q->requests, q->domains, choices, statuses, results) ==
                    DUOFORGE_OK);
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
    /* The library's mask within encoder 4's features (bits 0 to 41): the library also reports the reserve families of
       encoder 6 (bits 59 to 63, decision 0050), which encoder 4 has no columns for (features.version_features(4) in the
       Python tests). */
    const uint64_t supported = root_ext[0].supported & ((UINT64_C(1) << DUOFORGE_VIEWEXT_FEATURE_TRANSFORM) - 1u);
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
        static outputs sentinel;
        memset(&sentinel, 0xA5, sizeof sentinel);
        memset(o, 0xA5, sizeof *o); /* no refused call may write an output */
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
        /* another context; the order of the checks: NULL, then the contexts, then the rest */
        duoforge_context *tc = df_make_context(&df_config_team_c);
        duoforge_batch *other = make(&t, tc, setups, ROOTS, 1u);
        DF_CHECK_EQ_U64(&t, expand(lv, other, 4u, m, &query, pl, 1u, o), DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK_EQ_U64(&t, expand(lv, other, 5u, m, &query, pl, 1u, o), DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK_EQ_U64(&t, expand(lv, other, 4u, m, &query, pl, LEAVES + 1u, o), DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK_EQ_U64(&t, duoforge_batch_expand(lv, other, 5u, m, SEED, rq, dm, NULL, pl->viewers, 1u, pl->root_envs,
                                                  pl->samples, pl->choices, o->step_statuses, o->encode_statuses,
                                                  o->results, o->leaf_results, o->obs),
                        DUOFORGE_E_NULL_ARGUMENT);
        duoforge_batch_destroy(other);
        duoforge_context_destroy(tc);
        /* version and mask, as duoforge_batch_query_encoded checks them */
        const uint64_t roost = UINT64_C(1) << DUOFORGE_VIEWEXT_FEATURE_ROOST;
        DF_CHECK_EQ_U64(&t, expand(lv, roots, 0u, 0u, &query, pl, 1u, o), DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK_EQ_U64(&t, expand(lv, roots, 7u, 0u, &query, pl, 1u, o), DUOFORGE_E_INVALID_ARGUMENT); /* 6: encoder 6 (0050) */
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
        DF_CHECK(&t, memcmp(o, &sentinel, sizeof sentinel) == 0);
    }

    /* test_partial_count: count below the leaf batch's size (the last chunk of a round). The first count
       leaves equal those of a full call; the environments and the outputs from count on are not touched. */
    {
        DF_CHECK(&t, duoforge_batch_query_factored(roots, query.requests, query.observations, query.domains) ==
                         DUOFORGE_OK);
        uint64_t stream = 0x2026100300000405u;
        tally ty;
        memset(&ty, 0, sizeof ty);
        make_plan(&query, &stream, 0u, &the_plan, &ty);
        DF_CHECK_EQ_U64(&t, the_plan.count, LEAVES);
        const uint32_t part = 37u;
        const duoforge_status full = expand(leaves[0], roots, 4u, supported, &query, &the_plan, LEAVES, &out[0]);
        DF_CHECK_EQ_U64(&t, full, first_failure(&out[0], LEAVES));
        static uint8_t untouched[LEAVES][DUOFORGE_DIGEST_SIZE];
        digests(&t, pool, leaves[1], LEAVES, untouched);
        static outputs sentinel;
        memset(&sentinel, 0xA5, sizeof sentinel);
        memset(&out[1], 0xA5, sizeof out[1]);
        const duoforge_status st = expand(leaves[1], roots, 4u, supported, &query, &the_plan, part, &out[1]);
        DF_CHECK_EQ_U64(&t, st, first_failure(&out[1], part));
        DF_CHECK(&t, memcmp(out[1].step_statuses, out[0].step_statuses, part * sizeof out[0].step_statuses[0]) == 0);
        DF_CHECK(&t, memcmp(out[1].encode_statuses, out[0].encode_statuses, part * sizeof out[0].encode_statuses[0]) ==
                         0);
        DF_CHECK(&t, memcmp(out[1].results, out[0].results, part * sizeof out[0].results[0]) == 0);
        DF_CHECK(&t, memcmp(out[1].leaf_results, out[0].leaf_results, part * sizeof out[0].leaf_results[0]) == 0);
        DF_CHECK(&t, memcmp(out[1].obs, out[0].obs, (size_t)part * V4 * sizeof out[0].obs[0]) == 0);
        DF_CHECK(&t, memcmp(&out[1].step_statuses[part], &sentinel.step_statuses[part],
                            (LEAVES - part) * sizeof sentinel.step_statuses[0]) == 0);
        DF_CHECK(&t, memcmp(&out[1].encode_statuses[part], &sentinel.encode_statuses[part],
                            (LEAVES - part) * sizeof sentinel.encode_statuses[0]) == 0);
        DF_CHECK(&t, memcmp(&out[1].results[part], &sentinel.results[part],
                            (LEAVES - part) * sizeof sentinel.results[0]) == 0);
        DF_CHECK(&t, memcmp(&out[1].leaf_results[part], &sentinel.leaf_results[part],
                            (LEAVES - part) * sizeof sentinel.leaf_results[0]) == 0);
        DF_CHECK(&t, memcmp(&out[1].obs[(size_t)part * V4], &sentinel.obs[(size_t)part * V4],
                            (size_t)(LEAVES - part) * V4 * sizeof sentinel.obs[0]) == 0);
        digests(&t, pool, leaves[0], part, before);
        digests(&t, pool, leaves[1], LEAVES, after);
        DF_CHECK(&t, memcmp(before, after, part * sizeof before[0]) == 0);
        DF_CHECK(&t, memcmp(&untouched[part], &after[part], (LEAVES - part) * sizeof after[0]) == 0);
    }

    /* test_terminal_flag_both_ways and test_terminal_root. A TERMINAL root is not skipped: its leaves report the
       step's E_INVALID_ARGUMENT and keep the root's copy with the TERMINAL flag set. A later leaf in the same
       environment clears the flag, whether its step succeeds or fails on a running root. The flag is read through
       duoforge_batch_reset_terminal, which starts the next episode exactly in the TERMINAL environments. */
    {
        duoforge_batch *troots = make(&t, pool, setups, ROOTS, 1u);
        static root_query tq;
        uint64_t stream = 0x2026100300000406u;
        uint32_t ended = ROOTS;
        uint32_t running = ROOTS;
        for (uint32_t step = 0u; step < 600u; ++step) {
            DF_CHECK(&t, duoforge_batch_query_factored(troots, tq.requests, tq.observations, tq.domains) ==
                             DUOFORGE_OK);
            ended = ROOTS;
            running = ROOTS;
            for (uint32_t r = 0u; r < ROOTS; ++r) {
                const duoforge_request *rq = &tq.requests[2u * r];
                if (rq[0].boundary_kind == DUOFORGE_BOUNDARY_TERMINAL && ended == ROOTS) {
                    ended = r;
                }
                for (uint32_t p = 0u; p < 2u; ++p) {
                    if (rq[p].requested != 0u && tq.domains[2u * r + p].kind == DUOFORGE_CHOICE_SLOTS &&
                        running == ROOTS) {
                        running = r;
                    }
                }
            }
            if (ended < ROOTS && running < ROOTS) {
                break;
            }
            random_step_keep(&t, troots, &tq, &stream);
        }
        if (DF_CHECK(&t, ended < ROOTS && running < ROOTS)) {
            duoforge_batch *lt = make(&t, pool, setups, 4u, 2u);
            static plan tp;
            static outputs to;
            memset(&tp, 0, sizeof tp);
            for (uint32_t r = 0u; r < ROOTS; ++r) {
                tp.keys[r] = next(&stream);
                tp.viewers[r] = (uint8_t)(r % 2u);
            }
            /* leaf 0 from the TERMINAL root; leaves 1 and 3 from the running root; leaf 2 there with a pair
               outside the domain */
            static const uint32_t from[4] = {0u, 1u, 1u, 1u};
            for (uint32_t i = 0u; i < 4u; ++i) {
                tp.root_envs[i] = from[i] == 0u ? ended : running;
                tp.samples[i] = i;
                tp.choices[2u * i] = random_choice(&tq.domains[2u * tp.root_envs[i]], &stream);
                tp.choices[2u * i + 1u] = random_choice(&tq.domains[2u * tp.root_envs[i] + 1u], &stream);
            }
            for (uint32_t p = 0u; p < 2u; ++p) {
                tp.choices[2u * 2u + p].slot[0] = DUOFORGE_MAX_SLOT_OPTIONS - 1u;
                tp.choices[2u * 2u + p].slot[1] = DUOFORGE_MAX_SLOT_OPTIONS - 1u;
            }
            tally ty;
            memset(&ty, 0, sizeof ty);
            const duoforge_status st = expand(lt, troots, 4u, supported, &tq, &tp, 4u, &to);
            DF_CHECK_EQ_U64(&t, st, DUOFORGE_E_INVALID_ARGUMENT);
            for (uint32_t i = 0u; i < 4u; ++i) {
                check_leaf(&t, pool, troots, lt, &tq, &tp, &to, i, 4u, supported, V4, &ty);
            }
            DF_CHECK_EQ_U64(&t, to.step_statuses[0], DUOFORGE_E_INVALID_ARGUMENT);
            DF_CHECK_EQ_U64(&t, to.step_statuses[2], DUOFORGE_E_INVALID_ARGUMENT);
            uint32_t episodes[4];
            for (uint32_t i = 0u; i < 4u; ++i) {
                episodes[i] = duoforge_batch_env_episode(lt, i);
            }
            DF_CHECK(&t, duoforge_batch_reset_terminal(lt) == DUOFORGE_OK);
            DF_CHECK(&t, duoforge_batch_env_episode(lt, 0u) != episodes[0]); /* the TERMINAL root's copy */
            DF_CHECK(&t, duoforge_batch_env_episode(lt, 2u) == episodes[2]); /* a failed step on a running root */
            for (uint32_t i = 1u; i < 4u; i += 2u) {
                DF_CHECK(&t, (duoforge_batch_env_episode(lt, i) != episodes[i]) == (to.leaf_results[i] != 0u));
            }
            /* the flag cleared by a later leaf: a TERMINAL root's copy, then a running root's leaf in the same
               environment, (a) a step that succeeds and does not end, (b) a step that fails */
            static plan one;
            for (uint32_t c = 0u; c < 2u; ++c) {
                one = tp;
                one.root_envs[0] = ended;
                (void)expand(lt, troots, 4u, supported, &tq, &one, 1u, &to);
                one.root_envs[0] = running;
                one.choices[0] = c == 0u ? tp.choices[2] : tp.choices[4];
                one.choices[1] = c == 0u ? tp.choices[3] : tp.choices[5];
                bool fits = false;
                for (uint32_t sample = 0u; sample < 64u && !fits; ++sample) {
                    one.samples[0] = sample;
                    (void)expand(lt, troots, 4u, supported, &tq, &one, 1u, &to);
                    fits = c == 0u ? to.step_statuses[0] == DUOFORGE_OK && to.leaf_results[0] == 0u
                                   : to.step_statuses[0] == DUOFORGE_E_INVALID_ARGUMENT;
                    if (!fits) { /* a sample whose step ended the battle: put the TERMINAL root's copy back */
                        one.root_envs[0] = ended;
                        (void)expand(lt, troots, 4u, supported, &tq, &one, 1u, &to);
                        one.root_envs[0] = running;
                    }
                }
                if (DF_CHECK(&t, fits)) {
                    const uint32_t before_reset = duoforge_batch_env_episode(lt, 0u);
                    DF_CHECK(&t, duoforge_batch_reset_terminal(lt) == DUOFORGE_OK);
                    DF_CHECK_EQ_U64(&t, duoforge_batch_env_episode(lt, 0u), before_reset);
                }
            }
            duoforge_batch_destroy(lt);
        }
        duoforge_batch_destroy(troots);
    }

    /* test_equal_fingerprints: leaves on another context object with the same fingerprint expand alike */
    {
        DF_CHECK(&t, duoforge_batch_query_factored(roots, query.requests, query.observations, query.domains) ==
                         DUOFORGE_OK);
        uint64_t stream = 0x2026100300000407u;
        tally ty;
        memset(&ty, 0, sizeof ty);
        make_plan(&query, &stream, 1u, &the_plan, &ty);
        duoforge_context *pool2 = df_make_context(&df_config_pool);
        duoforge_batch *l2 = make(&t, pool2, setups, LEAVES, 2u);
        const duoforge_status a = expand(leaves[0], roots, 4u, supported, &query, &the_plan, LEAVES, &out[0]);
        const duoforge_status b = expand(l2, roots, 4u, supported, &query, &the_plan, LEAVES, &out[1]);
        DF_CHECK_EQ_U64(&t, a, b);
        DF_CHECK(&t, memcmp(&out[0], &out[1], sizeof out[0]) == 0);
        digests(&t, pool, leaves[0], LEAVES, before);
        digests(&t, pool2, l2, LEAVES, after);
        DF_CHECK(&t, memcmp(before, after, sizeof before) == 0);
        duoforge_batch_destroy(l2);
        duoforge_context_destroy(pool2);
    }

    /* test_query_encoded_zeroes_rows_after_a_failed_player: the encoder's batch path, which the leaves share
       (decision 0022). A records bit the POOL library does not support refuses player 0's row; player 1's rows
       are then not refreshed and are all zero. */
    {
        uint32_t missing = DUOFORGE_VIEWEXT_FEATURE_COUNT;
        for (uint32_t k = 0u; k < DUOFORGE_VIEWEXT_FEATURE_COUNT && missing == DUOFORGE_VIEWEXT_FEATURE_COUNT; ++k) {
            if (((supported >> k) & 1u) == 0u) {
                missing = k;
            }
        }
        if (DF_CHECK(&t, missing < DUOFORGE_VIEWEXT_FEATURE_COUNT)) {
            static float qobs[2u * ROOTS * V4];
            static float qslots[2u * ROOTS * DUOFORGE_ENCODER_SLOT_VALUES];
            static uint8_t qpairs[2u * ROOTS * DUOFORGE_ENCODER_PAIR_VALUES];
            static duoforge_status qstatuses[ROOTS];
            memset(qobs, 0xA5, sizeof qobs);
            memset(qslots, 0xA5, sizeof qslots);
            memset(qpairs, 0xA5, sizeof qpairs);
            const duoforge_status st = duoforge_batch_query_encoded(
                roots, 4u, supported | (UINT64_C(1) << missing), NULL, NULL, NULL, qobs, qslots, qpairs, qstatuses);
            DF_CHECK_EQ_U64(&t, st, DUOFORGE_E_UNSUPPORTED);
            bool zero = true;
            for (uint32_t e = 0u; e < ROOTS; ++e) {
                DF_CHECK_EQ_U64(&t, qstatuses[e], DUOFORGE_E_UNSUPPORTED);
                zero = zero && row_is_zero(&qobs[(size_t)(2u * e + 1u) * V4], V4) &&
                       row_is_zero(&qslots[(size_t)(2u * e + 1u) * DUOFORGE_ENCODER_SLOT_VALUES],
                                   DUOFORGE_ENCODER_SLOT_VALUES);
                for (uint32_t k = 0u; k < DUOFORGE_ENCODER_PAIR_VALUES; ++k) {
                    zero = zero && qpairs[(size_t)(2u * e + 1u) * DUOFORGE_ENCODER_PAIR_VALUES + k] == 0u;
                }
            }
            DF_CHECK(&t, zero);
        }
    }

    for (uint32_t v = 0u; v < VARIANTS; ++v) {
        duoforge_batch_destroy(leaves[v]);
    }
    duoforge_batch_destroy(roots);
    duoforge_context_destroy(pool);
    return df_test_end(&t);
}
