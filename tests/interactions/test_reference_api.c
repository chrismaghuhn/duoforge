/*
 * duoforge.api.reference: the reference setups of decision 0004 in the
 * library (duoforge_reference_setup) and the battle result query
 * (duoforge_battle_result), decision 0013 / M7 spec section 2.
 */
#include <stdio.h>
#include <string.h>

#include "support/check.h"
#include "support/fixtures.h"

/* FNV-1a 64 of the pairing-0 setup bytes, taken from the test-support
 * fixture before the team data moved into the library. */
#define SETUP_A_B_HASH 0xEBCDEBFB7CEE0557u

static duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];
static duoforge_event events[2][DUOFORGE_MAX_EVENTS];

static uint64_t fnv(const void *p, size_t n)
{
    const uint8_t *b = p;
    uint64_t h = 0xCBF29CE484222325u;
    for (size_t i = 0u; i < n; ++i) {
        h ^= b[i];
        h *= 0x100000001B3u;
    }
    return h;
}

static uint64_t next(uint64_t *s)
{
    *s += 0x9E3779B97F4A7C15u;
    uint64_t z = *s;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9u;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBu;
    return z ^ (z >> 31);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.api.reference");

    /* Reference setups: the four pairings. */
    duoforge_battle_setup s[4];
    for (uint32_t p = 0u; p < 4u; ++p) {
        DF_CHECK(&t, duoforge_reference_setup(p, &s[p]) == DUOFORGE_OK);
    }
    DF_CHECK_EQ_U64(&t, fnv(&s[0], sizeof s[0]), SETUP_A_B_HASH);
    DF_CHECK(&t, memcmp(&s[1].sides[0], &s[0].sides[1], sizeof s[0].sides[0]) == 0); /* B-A */
    DF_CHECK(&t, memcmp(&s[1].sides[1], &s[0].sides[0], sizeof s[0].sides[0]) == 0);
    DF_CHECK(&t, memcmp(&s[2].sides[0], &s[0].sides[0], sizeof s[0].sides[0]) == 0); /* A-A */
    DF_CHECK(&t, memcmp(&s[2].sides[1], &s[0].sides[0], sizeof s[0].sides[0]) == 0);
    DF_CHECK(&t, memcmp(&s[3].sides[0], &s[0].sides[1], sizeof s[0].sides[0]) == 0); /* B-B */
    DF_CHECK(&t, memcmp(&s[3].sides[1], &s[0].sides[1], sizeof s[0].sides[0]) == 0);
    duoforge_battle_setup fixture;
    df_setup_teams(&fixture);
    DF_CHECK(&t, memcmp(&fixture, &s[0], sizeof fixture) == 0);
    duoforge_battle_setup marker;
    memset(&marker, 0xA5, sizeof marker);
    duoforge_battle_setup out = marker;
    DF_CHECK(&t, duoforge_reference_setup(4u, &out) == DUOFORGE_E_INVALID_ARGUMENT &&
                     memcmp(&out, &marker, sizeof out) == 0);
    DF_CHECK(&t, duoforge_reference_setup(0u, NULL) == DUOFORGE_E_NULL_ARGUMENT);

    /* Battle result: 0 until TERMINAL, then the RESULT event's value. */
    duoforge_context *ctx = df_make_context(&df_config_k1);
    duoforge_context *other = df_make_context(&df_config_c1);
    unsigned battles = 0u;
    for (uint64_t seed = 1u; seed <= 8u; ++seed) {
        duoforge_battle_setup setup = s[seed % 4u];
        setup.rng_initstate = seed;
        duoforge_battle *b = df_make_battle(ctx, &setup);
        uint64_t policy = seed * 7919u;
        uint32_t seen = 0u;
        uint32_t result = 0xFFu;
        DF_CHECK(&t, duoforge_battle_result(ctx, b, &result) == DUOFORGE_OK && result == 0u);
        for (uint32_t step = 0u; step < 1000u; ++step) {
            duoforge_decision_bundle bd;
            memset(&bd, 0, sizeof bd);
            for (uint32_t p = 0u; p < 2u; ++p) {
                duoforge_request rq;
                uint32_t n = 0u;
                DF_CHECK(&t, duoforge_battle_request(ctx, b, p, &rq) == DUOFORGE_OK);
                bd.epoch = rq.epoch;
                if (rq.requested != 0u &&
                    DF_CHECK(&t, duoforge_battle_candidates(ctx, b, p, cands, DUOFORGE_MAX_CANDIDATES, &n) ==
                                     DUOFORGE_OK)) {
                    bd.response_mask = (uint8_t)(bd.response_mask | (1u << p));
                    bd.responses[p] = cands[next(&policy) % n];
                }
            }
            if (bd.response_mask == 0u) {
                break;
            }
            DF_CHECK(&t, duoforge_battle_result(ctx, b, &result) == DUOFORGE_OK && result == 0u);
            duoforge_step_result res;
            duoforge_event_buffer buffers[2] = {{events[0], DUOFORGE_MAX_EVENTS, 0u}, {events[1], DUOFORGE_MAX_EVENTS, 0u}};
            DF_CHECK(&t, duoforge_battle_step_events(ctx, b, &bd, &res, buffers) == DUOFORGE_OK);
            for (uint32_t i = 0u; i < buffers[0].count; ++i) {
                if (events[0][i].kind == DUOFORGE_EVENT_RESULT) {
                    seen = events[0][i].detail;
                }
            }
        }
        DF_CHECK(&t, seen != 0u && duoforge_battle_result(ctx, b, &result) == DUOFORGE_OK && result == seen);
        battles += seen != 0u ? 1u : 0u;
        uint32_t untouched = 0xA5A5A5A5u;
        DF_CHECK(&t, duoforge_battle_result(NULL, b, &untouched) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_result(ctx, b, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_result(other, b, &untouched) == DUOFORGE_E_CONTEXT_MISMATCH &&
                         untouched == 0xA5A5A5A5u);
        duoforge_battle_destroy(b);
    }
    DF_CHECK_EQ_U64(&t, battles, 8u);
    duoforge_context_destroy(other);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
