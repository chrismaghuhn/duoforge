/*
 * duoforge.request.accepts: at the boundaries of random real-team battles a
 * step accepts exactly the enumerated domain (decision 0005 section 3):
 * every candidate of a requested side is accepted, and a candidate with
 * one byte changed (epoch bytes left alone) is accepted iff it equals some
 * candidate byte for byte, otherwise rejected with E_INVALID_ARGUMENT. The
 * step's membership test does not list the domain (decision 0008), so this
 * compares the two at many states, through the public API on copies.
 */
#include <stdio.h>
#include <string.h>

#include "support/check.h"
#include "support/fixtures.h"

static duoforge_side_choice cands[2][DUOFORGE_MAX_CANDIDATES];

static uint64_t next(uint64_t *s)
{
    *s += 0x9E3779B97F4A7C15u;
    uint64_t z = *s;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9u;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBu;
    return z ^ (z >> 31);
}

static bool in_domain(const duoforge_side_choice *c, const duoforge_side_choice *list, uint32_t n)
{
    for (uint32_t i = 0u; i < n; ++i) {
        if (memcmp(c, &list[i], sizeof *c) == 0) {
            return true;
        }
    }
    return false;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.request.accepts");
    duoforge_context *ctx = df_make_context(&df_config_k1);
    uint64_t rng = 2026u;
    unsigned accepted = 0;
    unsigned rejected = 0;
    unsigned mismatches = 0;
    for (uint64_t seed = 1u; seed <= 12u; ++seed) {
        duoforge_battle_setup s;
        df_setup_teams(&s);
        s.rng_initstate = seed;
        duoforge_battle *b = df_make_battle(ctx, &s);
        duoforge_battle *scratch = NULL;
        DF_CHECK(&t, duoforge_battle_clone(ctx, b, &scratch) == DUOFORGE_OK);
        for (uint32_t step = 0u; step < 300u && scratch != NULL; ++step) {
            duoforge_decision_bundle bd;
            memset(&bd, 0, sizeof bd);
            uint32_t n[2] = {0u, 0u};
            for (uint32_t p = 0u; p < 2u; ++p) {
                duoforge_request rq;
                DF_CHECK(&t, duoforge_battle_request(ctx, b, p, &rq) == DUOFORGE_OK);
                bd.epoch = rq.epoch;
                if (rq.requested != 0u) {
                    DF_CHECK(&t, duoforge_battle_candidates(ctx, b, p, cands[p], DUOFORGE_MAX_CANDIDATES, &n[p]) ==
                                     DUOFORGE_OK && n[p] > 0u);
                    bd.response_mask = (uint8_t)(bd.response_mask | (1u << p));
                    bd.responses[p] = cands[p][(size_t)(next(&rng) % n[p])];
                }
            }
            if (bd.response_mask == 0u) {
                break; /* TERMINAL */
            }
            for (uint32_t p = 0u; p < 2u; ++p) {
                if (n[p] == 0u) {
                    continue;
                }
                /* Up to 16 candidates and 24 one-byte mutations per side. */
                for (uint32_t k = 0u; k < 40u; ++k) {
                    duoforge_decision_bundle probe = bd;
                    bool expect = true;
                    if (k < 16u) {
                        if (k >= n[p]) {
                            continue;
                        }
                        probe.responses[p] = cands[p][k];
                    } else {
                        duoforge_side_choice m = cands[p][(size_t)(next(&rng) % n[p])];
                        uint8_t *bytes = (uint8_t *)&m;
                        const size_t at = 4u + (size_t)(next(&rng) % (sizeof m - 4u)); /* not the epoch */
                        bytes[at] = (uint8_t)next(&rng);
                        probe.responses[p] = m;
                        expect = in_domain(&m, cands[p], n[p]);
                    }
                    DF_CHECK(&t, duoforge_battle_copy(ctx, scratch, b) == DUOFORGE_OK);
                    duoforge_step_result res;
                    const duoforge_status st = duoforge_battle_step(ctx, scratch, &probe, &res);
                    const bool ok = st == DUOFORGE_OK;
                    if (ok != expect || (!ok && st != DUOFORGE_E_INVALID_ARGUMENT)) {
                        mismatches += 1u;
                        if (mismatches <= 5u) {
                            fprintf(stderr, "  seed %u step %u side %u probe %u: %s, expected %s\n", (unsigned)seed,
                                    step, p, k, duoforge_status_name(st), expect ? "OK" : "INVALID_ARGUMENT");
                        }
                    }
                    accepted += ok ? 1u : 0u;
                    rejected += ok ? 0u : 1u;
                }
            }
            duoforge_step_result res;
            if (!DF_CHECK(&t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK)) {
                break;
            }
        }
        duoforge_battle_destroy(scratch);
        duoforge_battle_destroy(b);
    }
    DF_CHECK_EQ_U64(&t, mismatches, 0u);
    DF_CHECK(&t, accepted > 1000u && rejected > 1000u);
    fprintf(stderr, "  accepts: %u accepted, %u rejected probes, %u mismatches\n", accepted, rejected, mismatches);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
