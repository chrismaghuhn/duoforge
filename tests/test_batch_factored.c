/*
 * duoforge.batch.step_factored: stepping a batch by factored choices
 * (duoforge_batch_query_factored, duoforge_batch_step_factored) equals
 * stepping it by candidate index, and a forbidden pair or an index past a
 * slot list fails only its environment (M7 spec section 2).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge_batch.h>

#include "support/check.h"
#include "support/factored.h"
#include "support/fixtures.h"

#define ENVS 37u
#define SEED 0x2026100200000014u

static duoforge_battle_setup setups[ENVS];
static duoforge_request req_a[ENVS * 2u];
static duoforge_request req_b[ENVS * 2u];
static duoforge_side_choice cand_a[ENVS * 2u * DUOFORGE_MAX_CANDIDATES];
static uint32_t count_a[ENVS * 2u];
static duoforge_factored_domain dom_b[ENVS * 2u];
static uint16_t indices[ENVS * 2u];
static duoforge_factored_choice choices[ENVS * 2u];
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

/* Every requested player takes the choice of joint rank 0. */
static void first_choices(void)
{
    for (uint32_t at = 0u; at < ENVS * 2u; ++at) {
        memset(&choices[at], 0, sizeof choices[at]);
        if (req_b[at].requested != 0u) {
            choices[at] = df_factored_choice(&dom_b[at], 0u);
        }
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.batch.step_factored");
    duoforge_context *ctx = df_make_context(&df_config_k1);
    for (uint32_t e = 0u; e < ENVS; ++e) {
        (void)duoforge_reference_setup(e % 4u, &setups[e]);
    }

    /* Factored stepping equals index stepping, step by step to the end. */
    {
        duoforge_batch *a = make(&t, ctx, 4u);
        duoforge_batch *b = make(&t, ctx, 4u);
        uint64_t policy = 91u;
        unsigned steps = 0u;
        unsigned differ = 0u;
        unsigned counts_differ = 0u;
        bool live = a != NULL && b != NULL;
        while (live && steps < 2000u) {
            DF_CHECK(&t, duoforge_batch_query(a, req_a, NULL, cand_a, count_a) == DUOFORGE_OK);
            DF_CHECK(&t, duoforge_batch_query_factored(b, req_b, NULL, dom_b) == DUOFORGE_OK);
            live = false;
            for (uint32_t at = 0u; at < ENVS * 2u; ++at) {
                indices[at] = DUOFORGE_BATCH_NO_CHOICE;
                memset(&choices[at], 0, sizeof choices[at]);
                if (req_a[at].requested != 0u) {
                    const uint32_t k = (uint32_t)(next(&policy) % count_a[at]);
                    indices[at] = (uint16_t)k;
                    choices[at] = df_factored_choice(&dom_b[at], k);
                    counts_differ += req_b[at].candidate_count == count_a[at] ? 0u : 1u;
                    live = true;
                }
            }
            if (!live) {
                break;
            }
            DF_CHECK(&t, duoforge_batch_step_indices(a, req_a, cand_a, count_a, indices, statuses, results) ==
                             DUOFORGE_OK);
            DF_CHECK(&t, duoforge_batch_step_factored(b, req_b, dom_b, choices, statuses, results) == DUOFORGE_OK);
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
        DF_CHECK_EQ_U64(&t, counts_differ, 0u);
        duoforge_batch_destroy(a);
        duoforge_batch_destroy(b);
    }

    /* A forbidden pair or an index past a slot list fails only its
       environment, which keeps its state. */
    {
        duoforge_batch *b = make(&t, ctx, 4u);
        if (b != NULL) {
            DF_CHECK(&t, duoforge_batch_query_factored(b, req_b, NULL, dom_b) == DUOFORGE_OK);
            first_choices(); /* past team selection */
            DF_CHECK(&t, duoforge_batch_step_factored(b, req_b, dom_b, choices, statuses, results) == DUOFORGE_OK);
            DF_CHECK(&t, duoforge_batch_query_factored(b, req_b, NULL, dom_b) == DUOFORGE_OK);
            first_choices();
            uint32_t bad = ENVS;
            for (uint32_t e = 0u; e < ENVS && bad == ENVS; ++e) {
                const duoforge_factored_domain *d = &dom_b[e * 2u];
                for (uint32_t i = 0u; d->kind == DUOFORGE_CHOICE_SLOTS && i < d->slot_count[0] && bad == ENVS; ++i) {
                    for (uint32_t j = 0u; j < d->slot_count[1] && bad == ENVS; ++j) {
                        if (((d->allowed[i] >> j) & 1u) == 0u) {
                            bad = e;
                            choices[e * 2u].slot[0] = (uint8_t)i;
                            choices[e * 2u].slot[1] = (uint8_t)j;
                        }
                    }
                }
            }
            const uint32_t past = bad == 0u ? 1u : 0u;
            if (DF_CHECK(&t, bad < ENVS && dom_b[past * 2u].kind == DUOFORGE_CHOICE_SLOTS)) {
                choices[past * 2u].slot[1] = dom_b[past * 2u].slot_count[1];
                uint8_t before_bad[DUOFORGE_DIGEST_SIZE];
                uint8_t before_past[DUOFORGE_DIGEST_SIZE];
                uint8_t after[DUOFORGE_DIGEST_SIZE];
                digest_of(ctx, b, bad, before_bad);
                digest_of(ctx, b, past, before_past);
                DF_CHECK(&t, duoforge_batch_step_factored(b, req_b, dom_b, choices, statuses, results) ==
                                 DUOFORGE_E_INVALID_ARGUMENT);
                DF_CHECK(&t, statuses[bad] == DUOFORGE_E_INVALID_ARGUMENT &&
                                 statuses[past] == DUOFORGE_E_INVALID_ARGUMENT);
                digest_of(ctx, b, bad, after);
                DF_CHECK(&t, memcmp(before_bad, after, sizeof after) == 0);
                digest_of(ctx, b, past, after);
                DF_CHECK(&t, memcmp(before_past, after, sizeof after) == 0);
                unsigned stepped = 0u;
                for (uint32_t e = 0u; e < ENVS; ++e) {
                    stepped += statuses[e] == DUOFORGE_OK ? 1u : 0u;
                }
                DF_CHECK_EQ_U64(&t, stepped, ENVS - 2u);
            }
            DF_CHECK(&t, duoforge_batch_step_factored(b, req_b, NULL, choices, statuses, results) ==
                             DUOFORGE_E_NULL_ARGUMENT);
            duoforge_batch_destroy(b);
        }
    }

    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
