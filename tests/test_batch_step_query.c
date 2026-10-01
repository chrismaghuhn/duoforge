/*
 * duoforge.batch.step_query: the fused RL step (duoforge_batch_step_query,
 * decision 0013) equals its parts. Without autoreset it equals
 * duoforge_batch_step_indices followed by duoforge_batch_query; with
 * DUOFORGE_BATCH_AUTORESET it equals step_indices, the ended episodes'
 * results, duoforge_batch_reset_terminal and duoforge_batch_query - every
 * output array, every digest and every episode number, step by step. A bad
 * index fails only its environment, whose outputs describe its unchanged
 * boundary.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge_batch.h>

#include "support/check.h"
#include "support/fixtures.h"

#define ENVS 37u
#define SEED 0x2026100200000019u
#define SLOTS (ENVS * 2u)

typedef struct side_arrays {
    duoforge_request requests[SLOTS];
    duoforge_observation observations[SLOTS];
    duoforge_side_choice candidates[SLOTS * DUOFORGE_MAX_CANDIDATES];
    uint32_t counts[SLOTS];
    uint32_t episode_results[ENVS];
    duoforge_status statuses[ENVS];
    duoforge_step_result results[ENVS];
} side_arrays;

static duoforge_battle_setup setups[ENVS];
static side_arrays a_side;
static side_arrays b_side;
static uint16_t indices[SLOTS];

static uint64_t next(uint64_t *s)
{
    *s += 0x9E3779B97F4A7C15u;
    uint64_t z = *s;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9u;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBu;
    return z ^ (z >> 31);
}

static duoforge_batch *make(df_test *t, const duoforge_context *ctx)
{
    duoforge_batch_config c = {ENVS, 4u, SEED, setups};
    duoforge_batch *b = NULL;
    DF_CHECK(t, duoforge_batch_create(ctx, &c, &b) == DUOFORGE_OK && b != NULL);
    return b;
}

/* Candidate indices for every requested player of the last query. */
static void choose(uint64_t *policy, const side_arrays *s)
{
    for (uint32_t at = 0u; at < SLOTS; ++at) {
        indices[at] = DUOFORGE_BATCH_NO_CHOICE;
        if (s->requests[at].requested != 0u) {
            indices[at] = (uint16_t)(next(policy) % s->counts[at]);
        }
    }
}

/* The query outputs, statuses, results, digests and episodes agree. */
static bool same(const duoforge_context *ctx, const duoforge_batch *a, const duoforge_batch *b)
{
    bool ok = memcmp(a_side.requests, b_side.requests, sizeof a_side.requests) == 0 &&
              memcmp(a_side.observations, b_side.observations, sizeof a_side.observations) == 0 &&
              memcmp(a_side.counts, b_side.counts, sizeof a_side.counts) == 0 &&
              memcmp(a_side.statuses, b_side.statuses, sizeof a_side.statuses) == 0 &&
              memcmp(a_side.results, b_side.results, sizeof a_side.results) == 0;
    for (uint32_t at = 0u; at < SLOTS && ok; ++at) {
        ok = memcmp(&a_side.candidates[(size_t)at * DUOFORGE_MAX_CANDIDATES],
                    &b_side.candidates[(size_t)at * DUOFORGE_MAX_CANDIDATES],
                    (size_t)a_side.counts[at] * sizeof a_side.candidates[0]) == 0;
    }
    for (uint32_t e = 0u; e < ENVS && ok; ++e) {
        uint8_t da[DUOFORGE_DIGEST_SIZE];
        uint8_t db[DUOFORGE_DIGEST_SIZE];
        ok = duoforge_battle_digest(ctx, duoforge_batch_env(a, e), da) == DUOFORGE_OK &&
             duoforge_battle_digest(ctx, duoforge_batch_env(b, e), db) == DUOFORGE_OK &&
             memcmp(da, db, sizeof da) == 0 && duoforge_batch_env_episode(a, e) == duoforge_batch_env_episode(b, e);
    }
    return ok;
}

/* The reference episode results: the result of every environment that is
   TERMINAL now (DUOFORGE_RESULT_* is 0 before TERMINAL). */
static void reference_results(const duoforge_context *ctx, const duoforge_batch *a)
{
    for (uint32_t e = 0u; e < ENVS; ++e) {
        a_side.episode_results[e] = 0u;
        (void)duoforge_battle_result(ctx, duoforge_batch_env(a, e), &a_side.episode_results[e]);
    }
}

static bool query(duoforge_batch *batch, side_arrays *s)
{
    return duoforge_batch_query(batch, s->requests, s->observations, s->candidates, s->counts) == DUOFORGE_OK;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.batch.step_query");
    duoforge_context *ctx = df_make_context(&df_config_k1);
    for (uint32_t e = 0u; e < ENVS; ++e) {
        (void)duoforge_reference_setup(e % 4u, &setups[e]);
    }

    /* Without autoreset: step_indices, then query, to the end. */
    {
        duoforge_batch *a = make(&t, ctx);
        duoforge_batch *b = make(&t, ctx);
        uint64_t policy = 5u;
        unsigned steps = 0u;
        unsigned differ = 0u;
        bool live = a != NULL && b != NULL && DF_CHECK(&t, query(a, &a_side) && query(b, &b_side));
        while (live && steps < 2000u) {
            live = false;
            for (uint32_t at = 0u; at < SLOTS; ++at) {
                live = live || a_side.requests[at].requested != 0u;
            }
            if (!live) {
                break;
            }
            choose(&policy, &a_side);
            DF_CHECK(&t, duoforge_batch_step_indices(a, a_side.requests, a_side.candidates, a_side.counts, indices,
                                                     a_side.statuses, a_side.results) == DUOFORGE_OK &&
                             query(a, &a_side));
            reference_results(ctx, a);
            DF_CHECK(&t, duoforge_batch_step_query(b, 0u, indices, b_side.requests, b_side.observations,
                                                   b_side.candidates, b_side.counts, b_side.episode_results,
                                                   b_side.statuses, b_side.results) == DUOFORGE_OK);
            differ += same(ctx, a, b) &&
                              memcmp(a_side.episode_results, b_side.episode_results, sizeof a_side.episode_results) == 0
                          ? 0u
                          : 1u;
            steps += 1u;
        }
        DF_CHECK(&t, steps > 10u);
        DF_CHECK_EQ_U64(&t, differ, 0u);

        /* Every environment is TERMINAL on entry now: with the flag, one call
           reports every result and resets every environment, as
           step_indices, the results, reset_terminal and query do. */
        choose(&policy, &a_side);
        DF_CHECK(&t, duoforge_batch_step_indices(a, a_side.requests, a_side.candidates, a_side.counts, indices,
                                                 a_side.statuses, a_side.results) == DUOFORGE_OK);
        reference_results(ctx, a);
        unsigned reported = 0u;
        for (uint32_t e = 0u; e < ENVS; ++e) {
            reported += a_side.episode_results[e] != 0u ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, reported, ENVS);
        DF_CHECK(&t, duoforge_batch_reset_terminal(a) == DUOFORGE_OK && query(a, &a_side));
        DF_CHECK(&t, duoforge_batch_step_query(b, DUOFORGE_BATCH_AUTORESET, indices, b_side.requests,
                                               b_side.observations, b_side.candidates, b_side.counts,
                                               b_side.episode_results, b_side.statuses,
                                               b_side.results) == DUOFORGE_OK);
        DF_CHECK(&t, same(ctx, a, b) &&
                         memcmp(a_side.episode_results, b_side.episode_results, sizeof a_side.episode_results) == 0);
        DF_CHECK_EQ_U64(&t, duoforge_batch_env_episode(b, 0u), 1u);
        duoforge_batch_destroy(a);
        duoforge_batch_destroy(b);
    }

    /* With autoreset: step_indices, the ended episodes' results,
       reset_terminal, query - until every environment ended 3 episodes. */
    {
        duoforge_batch *a = make(&t, ctx);
        duoforge_batch *b = make(&t, ctx);
        uint64_t policy = 6u;
        unsigned steps = 0u;
        unsigned differ = 0u;
        unsigned ended = 0u;
        bool live = a != NULL && b != NULL && DF_CHECK(&t, query(a, &a_side) && query(b, &b_side));
        while (live && steps < 5000u) {
            choose(&policy, &a_side);
            DF_CHECK(&t, duoforge_batch_step_indices(a, a_side.requests, a_side.candidates, a_side.counts, indices,
                                                     a_side.statuses, a_side.results) == DUOFORGE_OK);
            for (uint32_t e = 0u; e < ENVS; ++e) {
                a_side.episode_results[e] = 0u;
                if (a_side.results[e].boundary_kind == DUOFORGE_BOUNDARY_TERMINAL) {
                    (void)duoforge_battle_result(ctx, duoforge_batch_env(a, e), &a_side.episode_results[e]);
                    ended += 1u;
                }
            }
            DF_CHECK(&t, duoforge_batch_reset_terminal(a) == DUOFORGE_OK && query(a, &a_side));
            memset(b_side.episode_results, 0xA5, sizeof b_side.episode_results);
            DF_CHECK(&t, duoforge_batch_step_query(b, DUOFORGE_BATCH_AUTORESET, indices, b_side.requests,
                                                   b_side.observations, b_side.candidates, b_side.counts,
                                                   b_side.episode_results, b_side.statuses,
                                                   b_side.results) == DUOFORGE_OK);
            differ += same(ctx, a, b) &&
                              memcmp(a_side.episode_results, b_side.episode_results, sizeof a_side.episode_results) == 0
                          ? 0u
                          : 1u;
            steps += 1u;
            live = ended < 3u * ENVS;
        }
        DF_CHECK(&t, ended >= 3u * ENVS);
        DF_CHECK_EQ_U64(&t, differ, 0u);

        /* A bad index fails only its environment, which keeps its state and
           reports its unchanged boundary. */
        duoforge_request before[2];
        memcpy(before, &b_side.requests[3u * 2u], sizeof before);
        uint8_t digest_before[DUOFORGE_DIGEST_SIZE];
        uint8_t digest_after[DUOFORGE_DIGEST_SIZE];
        (void)duoforge_battle_digest(ctx, duoforge_batch_env(b, 3u), digest_before);
        choose(&policy, &b_side);
        for (uint32_t p = 0u; p < 2u; ++p) {
            if (b_side.requests[3u * 2u + p].requested != 0u) {
                indices[3u * 2u + p] = (uint16_t)b_side.counts[3u * 2u + p];
            }
        }
        DF_CHECK(&t, duoforge_batch_step_query(b, DUOFORGE_BATCH_AUTORESET, indices, b_side.requests,
                                               b_side.observations, b_side.candidates, b_side.counts,
                                               b_side.episode_results, b_side.statuses,
                                               b_side.results) == DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(&t, b_side.statuses[3] == DUOFORGE_E_INVALID_ARGUMENT && b_side.episode_results[3] == 0u);
        (void)duoforge_battle_digest(ctx, duoforge_batch_env(b, 3u), digest_after);
        DF_CHECK(&t, memcmp(digest_before, digest_after, sizeof digest_after) == 0);
        DF_CHECK(&t, memcmp(before, &b_side.requests[3u * 2u], sizeof before) == 0);
        unsigned others = 0u;
        for (uint32_t e = 0u; e < ENVS; ++e) {
            others += e != 3u && b_side.statuses[e] == DUOFORGE_OK ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, others, ENVS - 1u);

        /* Arguments. */
        DF_CHECK(&t, duoforge_batch_step_query(b, 2u, indices, b_side.requests, NULL, b_side.candidates,
                                               b_side.counts, NULL, b_side.statuses,
                                               b_side.results) == DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(&t, duoforge_batch_step_query(b, 0u, NULL, b_side.requests, NULL, b_side.candidates,
                                               b_side.counts, NULL, b_side.statuses,
                                               b_side.results) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_batch_step_query(NULL, 0u, indices, b_side.requests, NULL, b_side.candidates,
                                               b_side.counts, NULL, b_side.statuses,
                                               b_side.results) == DUOFORGE_E_NULL_ARGUMENT);
        duoforge_batch_destroy(a);
        duoforge_batch_destroy(b);
    }

    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
