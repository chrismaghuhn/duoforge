/*
 * duoforge.request.candidates_digest: the candidate lists of random
 * real-team battles, byte for byte. Every requested player's list at every
 * boundary of 64 seeded battles (uniform random policy) is hashed (FNV-1a,
 * 64 bit, over the count and the candidates in order). The golden value was
 * taken from the enumeration before its speedup (decision 0008 section 7):
 * an optimization of the enumeration must keep the lists, their order and
 * every byte, including reserved ones.
 */
#include <stdio.h>
#include <string.h>

#include "support/check.h"
#include "support/fixtures.h"

#define GOLDEN_HASH 0xD4AF6C709C2756A9u
#define GOLDEN_LISTS 1993u
#define GOLDEN_TOTAL 180562u

static duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];
static duoforge_side_choice exact[DUOFORGE_MAX_CANDIDATES];

static uint64_t next(uint64_t *s)
{
    *s += 0x9E3779B97F4A7C15u;
    uint64_t z = *s;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9u;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBu;
    return z ^ (z >> 31);
}

static uint64_t fnv(uint64_t h, const uint8_t *p, size_t n)
{
    for (size_t i = 0u; i < n; ++i) {
        h ^= p[i];
        h *= 0x100000001B3u;
    }
    return h;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.request.candidates_digest");
    duoforge_context *ctx = df_make_context(&df_config_k1);
    uint64_t h = 0xCBF29CE484222325u;
    uint64_t rng = 2026100102u;
    unsigned lists = 0u;
    unsigned total = 0u;
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
                DF_CHECK(&t, duoforge_battle_request(ctx, b, p, &rq) == DUOFORGE_OK);
                bd.epoch = rq.epoch;
                if (rq.requested == 0u) {
                    continue;
                }
                uint32_t n = 0u;
                if (!DF_CHECK(&t, duoforge_battle_candidates(ctx, b, p, cands, DUOFORGE_MAX_CANDIDATES, &n) ==
                                          DUOFORGE_OK &&
                                      n > 0u)) {
                    break;
                }
                /* The request's count, an exactly sized buffer (two passes when
                 * the domain's bound exceeds it) and one too small (E_CAPACITY,
                 * required size, buffer untouched) agree with the list. */
                DF_CHECK_EQ_U64(&t, rq.candidate_count, n);
                uint32_t n2 = 0u;
                DF_CHECK(&t, duoforge_battle_candidates(ctx, b, p, exact, n, &n2) == DUOFORGE_OK && n2 == n &&
                                 memcmp(exact, cands, (size_t)n * sizeof cands[0]) == 0);
                memset(exact, 0xA5, sizeof exact[0]);
                uint32_t n3 = 0u;
                DF_CHECK(&t, duoforge_battle_candidates(ctx, b, p, exact, n - 1u, &n3) == DUOFORGE_E_CAPACITY &&
                                 n3 == n && exact[0].epoch == 0xA5A5A5A5u);
                const uint8_t count[4] = {(uint8_t)n, (uint8_t)(n >> 8), (uint8_t)(n >> 16), (uint8_t)(n >> 24)};
                h = fnv(h, count, sizeof count);
                h = fnv(h, (const uint8_t *)cands, (size_t)n * sizeof cands[0]);
                lists += 1u;
                total += n;
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
        duoforge_battle_destroy(b);
    }
    fprintf(stderr, "  candidates: %u lists, %u candidates, hash 0x%016llX\n", lists, total, (unsigned long long)h);
    DF_CHECK_EQ_U64(&t, lists, GOLDEN_LISTS);
    DF_CHECK_EQ_U64(&t, total, GOLDEN_TOTAL);
    DF_CHECK_EQ_U64(&t, h, GOLDEN_HASH);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
