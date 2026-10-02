/*
 * duoforge.batch.reset_setups: an environment reset with a new setup
 * (duoforge_batch_reset_setups, Learner v2) plays exactly what a fresh batch
 * created with that setup plays at that episode; a refused entry keeps its
 * environment while the others go through; a duplicate or out-of-range
 * environment changes nothing; the worker count changes nothing. Teams A, B
 * (duoforge_reference_setup) and C (df_put_team_c) under TEAM_C.
 */
#include <string.h>

#include <duoforge/duoforge_batch.h>

#include "support/check.h"
#include "support/fixtures.h"
#include "support/team_c.h"

#define ENVS 8u
#define SEED 0x2026100200000171u
#define SLOTS (ENVS * 2u)

static const duoforge_context_config team_c_config = {DUOFORGE_DATA_KIND_TEAM_C, 6u, 4u, 0u, 0u, NULL};

typedef struct arrays {
    duoforge_request requests[SLOTS];
    duoforge_side_choice candidates[SLOTS * DUOFORGE_MAX_CANDIDATES];
    uint32_t counts[SLOTS];
    duoforge_status statuses[ENVS];
    duoforge_step_result results[ENVS];
} arrays;

static arrays a_arr;
static arrays b_arr;
static uint16_t indices[SLOTS];

static uint64_t next(uint64_t *s)
{
    *s += 0x9E3779B97F4A7C15u;
    uint64_t z = *s;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9u;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBu;
    return z ^ (z >> 31);
}

/* side 0 of pairing p: 0 A, 1 B; Team C is put explicitly. */
static void team_a(duoforge_side_setup *side)
{
    duoforge_battle_setup s;
    (void)duoforge_reference_setup(0u, &s);
    *side = s.sides[0];
}

static void team_b(duoforge_side_setup *side)
{
    duoforge_battle_setup s;
    (void)duoforge_reference_setup(1u, &s);
    *side = s.sides[0];
}

/* A setup of two sides given by letters 'A', 'B', 'C'. */
static void pair(char x, char y, duoforge_battle_setup *out)
{
    memset(out, 0, sizeof *out);
    char letters[2] = {x, y};
    for (int s = 0; s < 2; ++s) {
        if (letters[s] == 'A') {
            team_a(&out->sides[s]);
        } else if (letters[s] == 'B') {
            team_b(&out->sides[s]);
        } else {
            df_put_team_c(&out->sides[s]);
        }
    }
}

static duoforge_batch *make(df_test *t, const duoforge_context *ctx, const duoforge_battle_setup *setups,
                            uint32_t workers)
{
    duoforge_batch_config c = {ENVS, workers, SEED, setups};
    duoforge_batch *b = NULL;
    DF_CHECK(t, duoforge_batch_create(ctx, &c, &b) == DUOFORGE_OK);
    return b;
}

static void digest(const duoforge_context *ctx, const duoforge_batch *b, uint32_t e, uint8_t out[32])
{
    (void)duoforge_battle_digest(ctx, duoforge_batch_env(b, e), out);
}

/* True iff every environment's digest is equal in a and b. */
static bool same(const duoforge_context *ctx, const duoforge_batch *a, const duoforge_batch *b)
{
    for (uint32_t e = 0u; e < ENVS; ++e) {
        uint8_t x[32];
        uint8_t y[32];
        digest(ctx, a, e, x);
        digest(ctx, b, e, y);
        if (memcmp(x, y, 32) != 0) {
            return false;
        }
    }
    return true;
}

static bool query(duoforge_batch *b, arrays *r)
{
    return duoforge_batch_query(b, r->requests, NULL, r->candidates, r->counts) == DUOFORGE_OK;
}

/* Steps both batches `steps` times with the same indices; false at the
   first unequal digest. */
static bool play_alike(df_test *t, const duoforge_context *ctx, duoforge_batch *a, duoforge_batch *b,
                       unsigned steps)
{
    uint64_t policy = 11u;
    for (unsigned k = 0u; k < steps; ++k) {
        if (!DF_CHECK(t, query(a, &a_arr) && query(b, &b_arr))) {
            return false;
        }
        for (uint32_t at = 0u; at < SLOTS; ++at) {
            const uint64_t r = next(&policy);
            indices[at] = a_arr.requests[at].requested != 0u && a_arr.counts[at] > 0u
                              ? (uint16_t)(r % a_arr.counts[at])
                              : DUOFORGE_BATCH_NO_CHOICE;
        }
        (void)duoforge_batch_step_indices(a, a_arr.requests, a_arr.candidates, a_arr.counts, indices, a_arr.statuses,
                                          a_arr.results);
        (void)duoforge_batch_step_indices(b, b_arr.requests, b_arr.candidates, b_arr.counts, indices, b_arr.statuses,
                                          b_arr.results);
        if (!same(ctx, a, b)) {
            return false;
        }
    }
    return true;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.batch.reset_setups");
    duoforge_context *ctx = df_make_context(&team_c_config);
    static duoforge_battle_setup base[ENVS];
    for (uint32_t e = 0u; e < ENVS; ++e) {
        pair('A', 'B', &base[e]);
    }
    static const uint32_t envs[3] = {1u, 4u, 6u};
    static const uint32_t episodes[3] = {3u, 9u, 2u};
    static duoforge_battle_setup fresh[3];
    pair('C', 'A', &fresh[0]);
    pair('B', 'C', &fresh[1]);
    pair('C', 'C', &fresh[2]);

    /* test_reset_matches_a_fresh_batch */
    {
        duoforge_batch *a = make(&t, ctx, base, 2u);
        static duoforge_battle_setup with[ENVS];
        memcpy(with, base, sizeof with);
        for (uint32_t i = 0u; i < 3u; ++i) {
            with[envs[i]] = fresh[i];
        }
        duoforge_batch *b = make(&t, ctx, with, 2u);
        duoforge_status st[3] = {99u, 99u, 99u};
        DF_CHECK(&t, duoforge_batch_reset_setups(a, 3u, envs, episodes, fresh, st) == DUOFORGE_OK);
        DF_CHECK(&t, st[0] == DUOFORGE_OK && st[1] == DUOFORGE_OK && st[2] == DUOFORGE_OK);
        for (uint32_t i = 0u; i < 3u; ++i) {
            DF_CHECK(&t, duoforge_batch_reset(b, envs[i], episodes[i]) == DUOFORGE_OK);
            DF_CHECK(&t, duoforge_batch_env_episode(a, envs[i]) == episodes[i]);
        }
        DF_CHECK(&t, same(ctx, a, b));
        DF_CHECK(&t, play_alike(&t, ctx, a, b, 60u));
        /* the stored setup stays: a plain reset replays the new teams */
        DF_CHECK(&t, duoforge_batch_reset(a, 4u, 20u) == DUOFORGE_OK && duoforge_batch_reset(b, 4u, 20u) == DUOFORGE_OK);
        DF_CHECK(&t, same(ctx, a, b));
        duoforge_batch_destroy(a);
        duoforge_batch_destroy(b);
    }

    /* test_refused_entry_keeps_its_environment */
    {
        duoforge_batch *a = make(&t, ctx, base, 2u);
        static duoforge_battle_setup three[3];
        three[0] = fresh[0];
        memset(&three[1], 0, sizeof three[1]);
        three[2] = fresh[2];
        uint8_t before[32];
        digest(ctx, a, 4u, before);
        duoforge_status st[3] = {99u, 99u, 99u};
        const duoforge_status r = duoforge_batch_reset_setups(a, 3u, envs, episodes, three, st);
        DF_CHECK(&t, r == DUOFORGE_E_INVALID_ARGUMENT && st[1] == DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(&t, st[0] == DUOFORGE_OK && st[2] == DUOFORGE_OK);
        uint8_t after[32];
        digest(ctx, a, 4u, after);
        DF_CHECK(&t, memcmp(before, after, 32) == 0 && duoforge_batch_env_episode(a, 4u) == 0u);
        DF_CHECK(&t, duoforge_batch_env_episode(a, 1u) == 3u && duoforge_batch_env_episode(a, 6u) == 2u);
        /* env 4 keeps its old setup too: a plain reset is still A-B */
        duoforge_batch *b = make(&t, ctx, base, 2u);
        DF_CHECK(&t, duoforge_batch_reset(a, 4u, 5u) == DUOFORGE_OK && duoforge_batch_reset(b, 4u, 5u) == DUOFORGE_OK);
        uint8_t x[32];
        uint8_t y[32];
        digest(ctx, a, 4u, x);
        digest(ctx, b, 4u, y);
        DF_CHECK(&t, memcmp(x, y, 32) == 0);
        duoforge_batch_destroy(a);
        duoforge_batch_destroy(b);
    }

    /* test_duplicate_or_out_of_range_changes_nothing */
    {
        duoforge_batch *a = make(&t, ctx, base, 2u);
        duoforge_batch *b = make(&t, ctx, base, 2u);
        static const uint32_t twice[2] = {2u, 2u};
        static const uint32_t outside[1] = {ENVS};
        DF_CHECK(&t, duoforge_batch_reset_setups(a, 2u, twice, episodes, fresh, NULL) == DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(&t, duoforge_batch_reset_setups(a, 1u, outside, episodes, fresh, NULL) == DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(&t, same(ctx, a, b) && duoforge_batch_env_episode(a, 2u) == 0u);
        duoforge_batch_destroy(a);
        duoforge_batch_destroy(b);
    }

    /* test_null_checks */
    {
        duoforge_batch *a = make(&t, ctx, base, 1u);
        DF_CHECK(&t, duoforge_batch_reset_setups(NULL, 1u, envs, episodes, fresh, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_batch_reset_setups(a, 1u, NULL, episodes, fresh, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_batch_reset_setups(a, 1u, envs, NULL, fresh, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_batch_reset_setups(a, 1u, envs, episodes, NULL, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_batch_reset_setups(a, 0u, NULL, NULL, NULL, NULL) == DUOFORGE_OK);
        duoforge_batch_destroy(a);
    }

    /* test_worker_counts_agree */
    {
        duoforge_batch *a = make(&t, ctx, base, 1u);
        duoforge_batch *b = make(&t, ctx, base, 4u);
        DF_CHECK(&t, duoforge_batch_reset_setups(a, 3u, envs, episodes, fresh, NULL) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_batch_reset_setups(b, 3u, envs, episodes, fresh, NULL) == DUOFORGE_OK);
        DF_CHECK(&t, same(ctx, a, b));
        DF_CHECK(&t, play_alike(&t, ctx, a, b, 60u));
        duoforge_batch_destroy(a);
        duoforge_batch_destroy(b);
    }

    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
