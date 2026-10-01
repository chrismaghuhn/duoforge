/*
 * duoforge.batch.step_indices: stepping a batch by candidate index
 * (duoforge_batch_step_indices) equals stepping it by bundles, a bad index
 * fails only its environment, TERMINAL environments are skipped, and
 * duoforge_batch_reset gives the battle of the seed derivation (decision 0013, M7 spec section 2).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge_batch.h>

#include "support/check.h"
#include "support/fixtures.h"

#define ENVS 37u
#define SEED 0x2026100200000013u

static duoforge_battle_setup setups[ENVS];
static duoforge_request req_a[ENVS * 2u];
static duoforge_request req_b[ENVS * 2u];
static duoforge_side_choice cand_a[ENVS * 2u * DUOFORGE_MAX_CANDIDATES];
static duoforge_side_choice cand_b[ENVS * 2u * DUOFORGE_MAX_CANDIDATES];
static uint32_t count_a[ENVS * 2u];
static uint32_t count_b[ENVS * 2u];
static uint16_t indices[ENVS * 2u];
static duoforge_decision_bundle bundles[ENVS];
static duoforge_status statuses[ENVS];
static duoforge_step_result results[ENVS];

static uint64_t next(uint64_t *s)
{
    *s += 0x9E3779B97F4A7C15u;
    uint64_t z = *s;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9u;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBu;
    return z ^ (z >> 31);
}

static duoforge_batch *make(df_test *t, const duoforge_context *ctx, uint32_t workers)
{
    duoforge_batch_config c = {ENVS, workers, SEED, setups};
    duoforge_batch *b = NULL;
    DF_CHECK(t, duoforge_batch_create(ctx, &c, &b) == DUOFORGE_OK && b != NULL);
    return b;
}

static void digest_of(const duoforge_context *ctx, const duoforge_batch *b, uint32_t e, uint8_t out[DUOFORGE_DIGEST_SIZE])
{
    memset(out, 0, DUOFORGE_DIGEST_SIZE);
    (void)duoforge_battle_digest(ctx, duoforge_batch_env(b, e), out);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.batch.step_indices");
    duoforge_context *ctx = df_make_context(&df_config_k1);
    for (uint32_t e = 0u; e < ENVS; ++e) {
        (void)duoforge_reference_setup(e % 4u, &setups[e]);
    }

    /* Index stepping equals bundle stepping, step by step to the end. */
    {
        duoforge_batch *a = make(&t, ctx, 4u);
        duoforge_batch *b = make(&t, ctx, 4u);
        uint64_t policy = 77u;
        unsigned steps = 0u;
        unsigned differ = 0u;
        bool live = a != NULL && b != NULL;
        while (live && steps < 2000u) {
            DF_CHECK(&t, duoforge_batch_query(a, req_a, NULL, cand_a, count_a) == DUOFORGE_OK);
            DF_CHECK(&t, duoforge_batch_query(b, req_b, NULL, cand_b, count_b) == DUOFORGE_OK);
            live = false;
            for (uint32_t e = 0u; e < ENVS; ++e) {
                memset(&bundles[e], 0, sizeof bundles[e]);
                bundles[e].epoch = req_a[e * 2u].epoch;
                for (uint32_t p = 0u; p < 2u; ++p) {
                    const uint32_t at = e * 2u + p;
                    indices[at] = DUOFORGE_BATCH_NO_CHOICE;
                    if (req_a[at].requested != 0u) {
                        indices[at] = (uint16_t)(next(&policy) % count_a[at]);
                        bundles[e].response_mask = (uint8_t)(bundles[e].response_mask | (1u << p));
                        bundles[e].responses[p] = cand_a[(size_t)at * DUOFORGE_MAX_CANDIDATES + indices[at]];
                        live = true;
                    }
                }
            }
            if (!live) {
                break;
            }
            DF_CHECK(&t, duoforge_batch_step(a, bundles, statuses, results) == DUOFORGE_OK);
            DF_CHECK(&t, duoforge_batch_step_indices(b, req_b, cand_b, count_b, indices, statuses, results) ==
                             DUOFORGE_OK);
            for (uint32_t e = 0u; e < ENVS; ++e) {
                uint8_t da[DUOFORGE_DIGEST_SIZE];
                uint8_t db[DUOFORGE_DIGEST_SIZE];
                digest_of(ctx, a, e, da);
                digest_of(ctx, b, e, db);
                differ += memcmp(da, db, sizeof da) != 0 ? 1u : 0u;
            }
            steps += 1u;
        }
        DF_CHECK(&t, !live && steps > 10u);
        DF_CHECK_EQ_U64(&t, differ, 0u);

        /* Every environment is TERMINAL now: a step skips them all, whatever
           the indices say. */
        if (b != NULL) {
            uint8_t before[DUOFORGE_DIGEST_SIZE];
            uint8_t after[DUOFORGE_DIGEST_SIZE];
            digest_of(ctx, b, 0u, before);
            for (uint32_t at = 0u; at < ENVS * 2u; ++at) {
                indices[at] = (uint16_t)(at % 3u == 0u ? 0xFFFEu : DUOFORGE_BATCH_NO_CHOICE);
            }
            memset(results, 0xA5, sizeof results);
            DF_CHECK(&t, duoforge_batch_step_indices(b, req_b, cand_b, count_b, indices, statuses, results) ==
                             DUOFORGE_OK);
            unsigned skipped = 0u;
            for (uint32_t e = 0u; e < ENVS; ++e) {
                skipped += statuses[e] == DUOFORGE_OK && results[e].boundary_kind == 0u ? 1u : 0u;
            }
            DF_CHECK_EQ_U64(&t, skipped, ENVS);
            digest_of(ctx, b, 0u, after);
            DF_CHECK(&t, memcmp(before, after, sizeof after) == 0);
        }
        duoforge_batch_destroy(a);
        duoforge_batch_destroy(b);
    }

    /* A bad index fails only its environment, which keeps its state. */
    {
        duoforge_batch *b = make(&t, ctx, 4u);
        if (b != NULL) {
            DF_CHECK(&t, duoforge_batch_query(b, req_b, NULL, cand_b, count_b) == DUOFORGE_OK);
            for (uint32_t at = 0u; at < ENVS * 2u; ++at) {
                indices[at] = req_b[at].requested != 0u ? 0u : DUOFORGE_BATCH_NO_CHOICE;
            }
            indices[3u * 2u] = (uint16_t)count_b[3u * 2u];    /* environment 3: one past the list */
            indices[8u * 2u] = DUOFORGE_BATCH_NO_CHOICE;      /* environment 8: a requested player without a choice */
            uint8_t before3[DUOFORGE_DIGEST_SIZE];
            uint8_t before8[DUOFORGE_DIGEST_SIZE];
            uint8_t after[DUOFORGE_DIGEST_SIZE];
            digest_of(ctx, b, 3u, before3);
            digest_of(ctx, b, 8u, before8);
            DF_CHECK(&t, duoforge_batch_step_indices(b, req_b, cand_b, count_b, indices, statuses, results) ==
                             DUOFORGE_E_INVALID_ARGUMENT);
            DF_CHECK(&t, statuses[3] == DUOFORGE_E_INVALID_ARGUMENT && statuses[8] == DUOFORGE_E_INVALID_ARGUMENT);
            digest_of(ctx, b, 3u, after);
            DF_CHECK(&t, memcmp(before3, after, sizeof after) == 0);
            digest_of(ctx, b, 8u, after);
            DF_CHECK(&t, memcmp(before8, after, sizeof after) == 0);
            unsigned stepped = 0u;
            for (uint32_t e = 0u; e < ENVS; ++e) {
                stepped += statuses[e] == DUOFORGE_OK ? 1u : 0u;
            }
            DF_CHECK_EQ_U64(&t, stepped, ENVS - 2u);

            /* Reset: the battle of the seed derivation; out of range fails. */
            DF_CHECK(&t, duoforge_batch_reset(b, 5u, 7u) == DUOFORGE_OK);
            DF_CHECK_EQ_U64(&t, duoforge_batch_env_episode(b, 5u), 7u);
            duoforge_battle_setup s = setups[5];
            duoforge_batch_seeds(SEED, 5u, 7u, &s.rng_initstate, &s.rng_initseq, NULL);
            duoforge_battle *fresh = df_make_battle(ctx, &s);
            uint8_t want[DUOFORGE_DIGEST_SIZE];
            DF_CHECK(&t, duoforge_battle_digest(ctx, fresh, want) == DUOFORGE_OK);
            digest_of(ctx, b, 5u, after);
            DF_CHECK(&t, memcmp(want, after, sizeof after) == 0);
            duoforge_battle_destroy(fresh);
            DF_CHECK(&t, duoforge_batch_reset(b, ENVS, 0u) == DUOFORGE_E_INVALID_ARGUMENT);
            DF_CHECK(&t, duoforge_batch_reset(NULL, 0u, 0u) == DUOFORGE_E_NULL_ARGUMENT);
            duoforge_batch_destroy(b);
        }
    }

    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
