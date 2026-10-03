/*
 * duoforge.encode: the C encoder's contract without the reference (decision
 * 0021; the byte equality with features.py is duoforge.python.encode_c).
 * The widths of the versions; NULL, version and mask refusals; a refused
 * row is all zero; duoforge_batch_query_encoded gives the same bytes for 1
 * and 4 workers and the same bytes as duoforge_encode row by row on what
 * duoforge_batch_query_factored returns. Teams A, B and C under TEAM_C, so
 * the sanitizer jobs run the encoder over real battles.
 */
#include <string.h>

#include <duoforge/duoforge_encode.h>

#include "support/check.h"
#include "support/fixtures.h"
#include "support/team_c.h"

#define ENVS 8u
#define ROWS (ENVS * 2u)
#define SEED 0x2026100300000500u
#define V4 850u

static const duoforge_context_config team_c_config = {DUOFORGE_DATA_KIND_TEAM_C, 6u, 4u, 0u, 0u, NULL};

typedef struct encoded {
    duoforge_request requests[ROWS];
    duoforge_observation observations[ROWS];
    duoforge_factored_domain domains[ROWS];
    float obs[ROWS * V4];
    float slots[ROWS * DUOFORGE_ENCODER_SLOT_VALUES];
    uint8_t pairs[ROWS * DUOFORGE_ENCODER_PAIR_VALUES];
    duoforge_status statuses[ENVS];
} encoded;

static encoded one;
static encoded four;
static float row_obs[V4];
static float row_slots[DUOFORGE_ENCODER_SLOT_VALUES];
static uint8_t row_pairs[DUOFORGE_ENCODER_PAIR_VALUES];

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

static duoforge_batch *make(df_test *t, const duoforge_context *ctx, const duoforge_battle_setup *setups,
                            uint32_t workers)
{
    duoforge_batch_config c = {ENVS, workers, SEED, setups};
    duoforge_batch *b = NULL;
    DF_CHECK(t, duoforge_batch_create(ctx, &c, &b) == DUOFORGE_OK);
    return b;
}

static bool encode_all(duoforge_batch *b, encoded *e, uint64_t mask)
{
    return duoforge_batch_query_encoded(b, 4u, mask, e->requests, e->observations, e->domains, e->obs, e->slots,
                                        e->pairs, e->statuses) == DUOFORGE_OK;
}

/* The first allowed pair (or the first four picks) of every requested player. */
static void first_choices(const encoded *e, duoforge_factored_choice *choices)
{
    memset(choices, 0, ROWS * sizeof *choices);
    for (uint32_t r = 0u; r < ROWS; ++r) {
        const duoforge_factored_domain *d = &e->domains[r];
        if (d->kind == DUOFORGE_CHOICE_TEAM_SELECTION) {
            for (uint8_t k = 0u; k < 4u; ++k) {
                choices[r].picks[k] = k;
            }
        } else if (d->kind == DUOFORGE_CHOICE_SLOTS) {
            for (uint8_t i = 0u; i < DUOFORGE_MAX_SLOT_OPTIONS; ++i) {
                if (d->allowed[i] != 0u) {
                    uint8_t j = 0u;
                    while (((d->allowed[i] >> j) & 1u) == 0u) {
                        ++j;
                    }
                    choices[r].slot[0] = i;
                    choices[r].slot[1] = j;
                    break;
                }
            }
        }
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.encode");

    /* test_widths */
    {
        static const uint32_t want[6] = {0u, 607u, 607u, 842u, 850u, 0u};
        for (uint32_t v = 0u; v < 6u; ++v) {
            uint32_t size = 7u;
            const duoforge_status st = duoforge_encoder_size(v, &size);
            DF_CHECK(&t, want[v] == 0u ? st == DUOFORGE_E_INVALID_ARGUMENT && size == 7u
                                       : st == DUOFORGE_OK && size == want[v]);
        }
        DF_CHECK(&t, duoforge_encoder_size(3u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    }

    duoforge_context *ctx = df_make_context(&team_c_config);
    static duoforge_battle_setup setups[ENVS];
    static const char pairs[ENVS][2] = {{'A', 'B'}, {'B', 'C'}, {'C', 'A'}, {'C', 'C'},
                                        {'A', 'A'}, {'B', 'A'}, {'C', 'B'}, {'A', 'C'}};
    for (uint32_t e = 0u; e < ENVS; ++e) {
        memset(&setups[e], 0, sizeof setups[e]);
        team(pairs[e][0], &setups[e].sides[0]);
        team(pairs[e][1], &setups[e].sides[1]);
    }

    /* test_refusals: NULL, version, mask; a refused row is all zero */
    {
        duoforge_batch *b = make(&t, ctx, setups, 1u);
        DF_CHECK(&t, duoforge_batch_query_factored(b, one.requests, one.observations, one.domains) == DUOFORGE_OK);
        const duoforge_observation *ob = &one.observations[0];
        const duoforge_factored_domain *d = &one.domains[0];
        const uint64_t record_bit = UINT64_C(1) << DUOFORGE_VIEWEXT_FEATURE_STEALTH_ROCK;
        const uint64_t roost = UINT64_C(1) << DUOFORGE_VIEWEXT_FEATURE_ROOST;
        DF_CHECK(&t, duoforge_encode(4u, 0u, NULL, d, NULL, row_obs, row_slots, row_pairs) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_encode(5u, 0u, ob, d, NULL, row_obs, row_slots, row_pairs) ==
                         DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(&t, duoforge_encode(2u, record_bit, ob, d, NULL, row_obs, row_slots, row_pairs) ==
                         DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(&t, duoforge_encode(3u, roost, ob, d, NULL, row_obs, row_slots, row_pairs) ==
                         DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(&t, duoforge_encode(4u, UINT64_C(1) << 42, ob, d, NULL, row_obs, row_slots, row_pairs) ==
                         DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(&t, duoforge_encode(4u, record_bit, ob, d, NULL, row_obs, row_slots, row_pairs) ==
                         DUOFORGE_E_NULL_ARGUMENT);
        /* a malformed row: refused, and all zero */
        static duoforge_observation bad;
        bad = *ob;
        bad.weather = 9u;
        memset(row_obs, 0xFF, sizeof row_obs);
        DF_CHECK(&t, duoforge_encode(4u, 0u, &bad, d, NULL, row_obs, row_slots, row_pairs) ==
                         DUOFORGE_E_INVALID_ARGUMENT);
        bool zero = true;
        for (uint32_t k = 0u; k < V4; ++k) {
            zero = zero && row_obs[k] == 0.0f;
        }
        DF_CHECK(&t, zero);
        /* Sand without its bit: unsupported; with it: encoded */
        bad = *ob;
        bad.weather = DUOFORGE_WEATHER_SAND;
        DF_CHECK(&t, duoforge_encode(4u, 0u, &bad, d, NULL, row_obs, row_slots, row_pairs) == DUOFORGE_E_UNSUPPORTED);
        DF_CHECK(&t, duoforge_encode(2u, 0u, &bad, d, NULL, row_obs, row_slots, row_pairs) == DUOFORGE_E_UNSUPPORTED);
        DF_CHECK(&t, duoforge_encode(4u, UINT64_C(1) << DUOFORGE_VIEWEXT_FEATURE_WEATHER_SAND, &bad, d, NULL, row_obs,
                                     row_slots, row_pairs) == DUOFORGE_OK);
        /* two faults: the reference's check order decides the class (records before the global one-hots,
           the global one-hots before the sides, locations before statuses) */
        static duoforge_observation_ext x;
        memset(&x, 0, sizeof x);
        x.revision = DUOFORGE_OBSERVATION_EXT_REVISION;
        x.player = ob->player;
        x.epoch = ob->epoch;
        x.supported = 0u; /* lacks the mask's bit: unsupported */
        bad = *ob;
        bad.weather = 9u; /* malformed, but checked after the records */
        DF_CHECK(&t, duoforge_encode(4u, record_bit, &bad, d, &x, row_obs, row_slots, row_pairs) ==
                         DUOFORGE_E_UNSUPPORTED);
        x.supported = record_bit;
        x.field.gravity_turns = 6u; /* out of range: malformed, before the weather's unsupported Sand */
        bad.weather = DUOFORGE_WEATHER_SAND;
        DF_CHECK(&t, duoforge_encode(4u, record_bit, &bad, d, &x, row_obs, row_slots, row_pairs) ==
                         DUOFORGE_E_INVALID_ARGUMENT);
        bad = *ob;
        bad.weather = DUOFORGE_WEATHER_SAND;       /* unsupported, in the global part */
        bad.sides[0].members[0].location = 9u;     /* malformed, in a side: later */
        DF_CHECK(&t, duoforge_encode(4u, 0u, &bad, d, NULL, row_obs, row_slots, row_pairs) == DUOFORGE_E_UNSUPPORTED);
        bad = *ob;
        bad.sides[bad.player].members[1].status = DUOFORGE_AILMENT_TOX; /* unsupported, statuses after locations */
        bad.sides[bad.player].members[5].location = 9u;                 /* malformed */
        DF_CHECK(&t, duoforge_encode(4u, 0u, &bad, d, NULL, row_obs, row_slots, row_pairs) ==
                         DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(&t, duoforge_batch_query_encoded(b, 0u, 0u, NULL, NULL, NULL, one.obs, one.slots, one.pairs,
                                                  one.statuses) == DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(&t, duoforge_batch_query_encoded(b, 4u, 0u, NULL, NULL, NULL, NULL, one.slots, one.pairs,
                                                  one.statuses) == DUOFORGE_E_NULL_ARGUMENT);
        duoforge_batch_destroy(b);
    }

    /* test_workers_and_rows_agree: over real play, every step */
    {
        duoforge_batch *a = make(&t, ctx, setups, 1u);
        duoforge_batch *b = make(&t, ctx, setups, 4u);
        const uint64_t mask = UINT64_C(1) << DUOFORGE_VIEWEXT_FEATURE_ENCORE; /* revision-0 records: empty */
        static duoforge_factored_choice choices[ROWS];
        static duoforge_status step_statuses[ENVS];
        static duoforge_step_result results[ENVS];
        static duoforge_observation_ext ext[ROWS];
        for (uint32_t step = 0u; step < 40u; ++step) {
            if (!DF_CHECK(&t, encode_all(a, &one, mask) && encode_all(b, &four, mask))) {
                break;
            }
            DF_CHECK(&t, memcmp(one.obs, four.obs, sizeof one.obs) == 0);
            DF_CHECK(&t, memcmp(one.slots, four.slots, sizeof one.slots) == 0);
            DF_CHECK(&t, memcmp(one.pairs, four.pairs, sizeof one.pairs) == 0);
            DF_CHECK(&t, duoforge_batch_observe_ext(a, ext) == DUOFORGE_OK);
            for (uint32_t r = 0u; r < ROWS; ++r) {
                DF_CHECK(&t, duoforge_encode(4u, mask, &one.observations[r], &one.domains[r], &ext[r], row_obs,
                                             row_slots, row_pairs) == DUOFORGE_OK);
                DF_CHECK(&t, memcmp(row_obs, &one.obs[r * V4], sizeof row_obs) == 0);
                DF_CHECK(&t, memcmp(row_slots, &one.slots[r * DUOFORGE_ENCODER_SLOT_VALUES], sizeof row_slots) == 0);
                DF_CHECK(&t, memcmp(row_pairs, &one.pairs[r * DUOFORGE_ENCODER_PAIR_VALUES], sizeof row_pairs) == 0);
            }
            first_choices(&one, choices);
            (void)duoforge_batch_step_factored(a, one.requests, one.domains, choices, step_statuses, results);
            (void)duoforge_batch_step_factored(b, four.requests, four.domains, choices, step_statuses, results);
            DF_CHECK(&t, duoforge_batch_reset_terminal(a) == DUOFORGE_OK && duoforge_batch_reset_terminal(b) == DUOFORGE_OK);
        }
        duoforge_batch_destroy(a);
        duoforge_batch_destroy(b);
    }

    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
