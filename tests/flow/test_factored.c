/*
 * duoforge.request.factored: the factored domain (M7 spec section 2) is the
 * joint candidate list in another form. Over the 64 battles of
 * duoforge.request.candidates_digest, every factored domain expands (the
 * allowed pairs in row-major order; team tuples by lexicographic unranking)
 * to the candidate list byte for byte, in its order, and its unused entries
 * are zero.
 */
#include <stdio.h>
#include <string.h>

#include "support/check.h"
#include "support/factored.h"
#include "support/fixtures.h"

static duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];
static duoforge_side_choice expanded[DUOFORGE_MAX_CANDIDATES];

static uint64_t next(uint64_t *s)
{
    *s += 0x9E3779B97F4A7C15u;
    uint64_t z = *s;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9u;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBu;
    return z ^ (z >> 31);
}

/* Unused list entries, unused bits and reserved bytes are zero. */
static bool unused_zero(const duoforge_factored_domain *d)
{
    duoforge_slot_command zero_cmd;
    memset(&zero_cmd, 0, sizeof zero_cmd);
    bool ok = d->reserved[0] == 0u && d->reserved[1] == 0u && d->reserved[2] == 0u;
    for (uint32_t s = 0u; s < 2u; ++s) {
        for (uint32_t i = d->slot_count[s]; i < DUOFORGE_MAX_SLOT_OPTIONS; ++i) {
            ok = ok && memcmp(&d->slots[s][i], &zero_cmd, sizeof zero_cmd) == 0;
        }
    }
    const uint32_t cols = d->slot_count[1] >= 32u ? 0xFFFFFFFFu : (1u << d->slot_count[1]) - 1u;
    for (uint32_t i = 0u; i < DUOFORGE_MAX_SLOT_OPTIONS; ++i) {
        ok = ok && (d->allowed[i] & ~(i < d->slot_count[0] ? cols : 0u)) == 0u;
    }
    return ok;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.request.factored");
    DF_CHECK_EQ_U64(&t, sizeof(duoforge_factored_domain), 652u);
    DF_CHECK_EQ_U64(&t, sizeof(duoforge_factored_choice), 8u);
    duoforge_context *ctx = df_make_context(&df_config_k1);
    duoforge_context *other = df_make_context(&df_config_c1);
    uint64_t rng = 2026100102u;
    unsigned lists = 0u;
    unsigned teams = 0u;
    unsigned mismatched = 0u;
    for (uint64_t seed = 1u; seed <= 64u; ++seed) {
        duoforge_battle_setup s;
        df_setup_teams(&s);
        s.rng_initstate = seed;
        duoforge_battle *b = df_make_battle(ctx, &s);
        for (uint32_t step = 0u; step < 400u && b != NULL; ++step) {
            duoforge_decision_bundle bd;
            memset(&bd, 0, sizeof bd);
            for (uint32_t p = 0u; p < 2u; ++p) {
                duoforge_request rq;
                duoforge_factored_domain d;
                memset(&d, 0xA5, sizeof d);
                DF_CHECK(&t, duoforge_battle_request(ctx, b, p, &rq) == DUOFORGE_OK);
                DF_CHECK(&t, duoforge_battle_factored(ctx, b, p, &d) == DUOFORGE_OK);
                bd.epoch = rq.epoch;
                if (rq.requested == 0u) {
                    duoforge_factored_domain z;
                    memset(&z, 0, sizeof z);
                    z.epoch = rq.epoch;
                    DF_CHECK(&t, memcmp(&d, &z, sizeof d) == 0);
                    continue;
                }
                uint32_t n = 0u;
                if (!DF_CHECK(&t, duoforge_battle_candidates(ctx, b, p, cands, DUOFORGE_MAX_CANDIDATES, &n) ==
                                          DUOFORGE_OK &&
                                      n > 0u)) {
                    break;
                }
                const uint32_t m = df_factored_expand(&d, p, expanded);
                mismatched += m == n && memcmp(expanded, cands, (size_t)n * sizeof cands[0]) == 0 ? 0u : 1u;
                DF_CHECK(&t, d.epoch == rq.epoch && unused_zero(&d));
                lists += 1u;
                teams += d.kind == DUOFORGE_CHOICE_TEAM_SELECTION ? 1u : 0u;
                bd.response_mask = (uint8_t)(bd.response_mask | (1u << p));
                bd.responses[p] = cands[(size_t)(next(&rng) % n)];
            }
            if (bd.response_mask == 0u) {
                break; /* TERMINAL */
            }
            duoforge_step_result res;
            if (!DF_CHECK(&t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK)) {
                break;
            }
        }
        if (seed == 1u) {
            duoforge_factored_domain marker;
            memset(&marker, 0xA5, sizeof marker);
            duoforge_factored_domain d = marker;
            DF_CHECK(&t, duoforge_battle_factored(NULL, b, 0u, &d) == DUOFORGE_E_NULL_ARGUMENT);
            DF_CHECK(&t, duoforge_battle_factored(ctx, NULL, 0u, &d) == DUOFORGE_E_NULL_ARGUMENT);
            DF_CHECK(&t, duoforge_battle_factored(ctx, b, 0u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
            DF_CHECK(&t, duoforge_battle_factored(ctx, b, 2u, &d) == DUOFORGE_E_INVALID_ARGUMENT);
            DF_CHECK(&t, duoforge_battle_factored(other, b, 0u, &d) == DUOFORGE_E_CONTEXT_MISMATCH);
            DF_CHECK(&t, memcmp(&d, &marker, sizeof d) == 0);
        }
        duoforge_battle_destroy(b);
    }
    fprintf(stderr, "  factored: %u domains (%u team selection), %u mismatched\n", lists, teams, mismatched);
    DF_CHECK(&t, lists > 1000u && teams == 128u);
    DF_CHECK_EQ_U64(&t, mismatched, 0u);
    duoforge_context_destroy(other);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
