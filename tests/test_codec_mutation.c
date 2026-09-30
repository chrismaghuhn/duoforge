/*
 * T13 duoforge.codec.mutation: exhaustive single-byte substitution over the
 * golden F1 and F2 encodings (380 x 255 = 96,900 inputs each) via decode into
 * dst, and over F1 again via create_decoded. Every outcome is atomic (dst
 * unchanged / *out untouched, no leak); every accepted input re-encodes to
 * itself and passes check; the exact per-region outcome counts equal the
 * independent structural model (tools/state_model/state_v1_model.py).
 * Plus 10,000 seeded 2..4-byte mutations (property only). Inputs are
 * exact-size heap buffers so over-reads fail under ASan.
 */
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "codec/state_codec.h"
#include "rng/pcg32.h"
#include "support/check.h"
#include "support/fixtures.h"

enum { REGION_COUNT = 14, STATUS_COUNT = 5 };
static const struct {
    size_t lo;
    size_t hi;
    const char *name;
} regions[REGION_COUNT] = {
    {0, 8, "magic"},          {8, 10, "kind"},           {10, 12, "schema"},          {12, 16, "semantics"},
    {16, 20, "total_length"}, {20, 52, "fingerprint"},   {52, 60, "rng.state"},       {60, 68, "rng.inc"},
    {68, 76, "rng.draws"},    {76, 80, "next_activation"}, {80, 92, "side0.header"},   {92, 230, "side0.members"},
    {230, 242, "side1.header"}, {242, 380, "side1.members"},
};

/* Status column order: OK, MALFORMED, CONTEXT_MISMATCH, SCHEMA_MISMATCH, SEMANTICS_MISMATCH. */
static const unsigned expected_f1[REGION_COUNT][STATUS_COUNT] = {
    {0, 2040, 0, 0, 0}, /* magic */
    {0, 0, 0, 510, 0}, /* kind */
    {0, 0, 0, 510, 0}, /* schema */
    {0, 0, 0, 0, 1020}, /* semantics */
    {0, 1020, 0, 0, 0}, /* total_length */
    {0, 0, 8160, 0, 0}, /* fingerprint */
    {2040, 0, 0, 0, 0}, /* rng.state */
    {1912, 128, 0, 0, 0}, /* rng.inc */
    {2040, 0, 0, 0, 0}, /* rng.draws */
    {1015, 5, 0, 0, 0}, /* next_activation */
    {9, 3051, 0, 0, 0}, /* side0.header */
    {6868, 28322, 0, 0, 0}, /* side0.members */
    {4, 3056, 0, 0, 0}, /* side1.header */
    {6676, 28514, 0, 0, 0}, /* side1.members */
};
static const unsigned expected_f2[REGION_COUNT][STATUS_COUNT] = {
    {0, 2040, 0, 0, 0}, /* magic */
    {0, 0, 0, 510, 0}, /* kind */
    {0, 0, 0, 510, 0}, /* schema */
    {0, 0, 0, 0, 1020}, /* semantics */
    {0, 1020, 0, 0, 0}, /* total_length */
    {0, 0, 8160, 0, 0}, /* fingerprint */
    {2040, 0, 0, 0, 0}, /* rng.state */
    {1912, 128, 0, 0, 0}, /* rng.inc */
    {2040, 0, 0, 0, 0}, /* rng.draws */
    {1014, 6, 0, 0, 0}, /* next_activation */
    {13, 3047, 0, 0, 0}, /* side0.header */
    {7024, 28166, 0, 0, 0}, /* side0.members */
    {5, 3055, 0, 0, 0}, /* side1.header */
    {6902, 28288, 0, 0, 0}, /* side1.members */
};

static int status_column(duoforge_status st)
{
    switch (st) {
    case DUOFORGE_OK:
        return 0;
    case DUOFORGE_E_MALFORMED:
        return 1;
    case DUOFORGE_E_CONTEXT_MISMATCH:
        return 2;
    case DUOFORGE_E_SCHEMA_MISMATCH:
        return 3;
    case DUOFORGE_E_SEMANTICS_MISMATCH:
        return 4;
    default:
        return -1;
    }
}

static void raw(const duoforge_battle *b, uint8_t out[DUOFORGE_STATE_V1_ENCODED_SIZE])
{
    memset(out, 0, DUOFORGE_STATE_V1_ENCODED_SIZE);
    dfi_encode_unchecked(b, out);
}

/* Decodes one input; checks atomicity and, on OK, re-encode identity. */
static duoforge_status decode_one(df_test *t, const duoforge_context *c1, duoforge_battle *dst,
                                  const uint8_t *in, bool via_create, unsigned *violations)
{
    uint8_t before[DUOFORGE_STATE_V1_ENCODED_SIZE];
    uint8_t after[DUOFORGE_STATE_V1_ENCODED_SIZE];
    duoforge_status st;
    if (via_create) {
        max_align_t sentinel;
        duoforge_battle *const marker = (duoforge_battle *)(void *)&sentinel;
        duoforge_battle *out = marker;
        st = duoforge_battle_create_decoded(c1, in, DUOFORGE_STATE_V1_ENCODED_SIZE, &out);
        if (st == DUOFORGE_OK) {
            raw(out, after);
            *violations += memcmp(after, in, sizeof after) != 0 ? 1u : 0u;
            *violations += duoforge_battle_check(c1, out) != DUOFORGE_OK ? 1u : 0u;
            duoforge_battle_destroy(out);
        } else {
            *violations += out != marker ? 1u : 0u;
        }
    } else {
        raw(dst, before);
        st = duoforge_battle_decode(c1, dst, in, DUOFORGE_STATE_V1_ENCODED_SIZE);
        raw(dst, after);
        if (st == DUOFORGE_OK) {
            *violations += memcmp(after, in, sizeof after) != 0 ? 1u : 0u;
            *violations += duoforge_battle_check(c1, dst) != DUOFORGE_OK ? 1u : 0u;
        } else {
            *violations += memcmp(after, before, sizeof after) != 0 ? 1u : 0u;
        }
    }
    (void)t;
    return st;
}

static void sweep(df_test *t, const duoforge_context *c1, duoforge_battle *dst, const uint8_t *golden,
                  const unsigned expected[REGION_COUNT][STATUS_COUNT], bool via_create, const char *label)
{
    unsigned counts[REGION_COUNT][STATUS_COUNT];
    memset(counts, 0, sizeof counts);
    unsigned violations = 0;
    unsigned unknown = 0;
    uint8_t *in = df_heap_copy(golden, DUOFORGE_STATE_V1_ENCODED_SIZE);
    for (unsigned r = 0; r < REGION_COUNT; ++r) {
        for (size_t off = regions[r].lo; off < regions[r].hi; ++off) {
            for (unsigned v = 0; v < 256; ++v) {
                if (v == golden[off]) {
                    continue;
                }
                in[off] = (uint8_t)v;
                const int col = status_column(decode_one(t, c1, dst, in, via_create, &violations));
                if (col < 0) {
                    ++unknown;
                } else {
                    counts[r][col]++;
                }
                in[off] = golden[off];
            }
        }
    }
    df_free(in);
    DF_CHECK_EQ_U64(t, violations, 0u);
    DF_CHECK_EQ_U64(t, unknown, 0u);
    for (unsigned r = 0; r < REGION_COUNT; ++r) {
        for (unsigned c = 0; c < STATUS_COUNT; ++c) {
            if (!DF_CHECK(t, counts[r][c] == expected[r][c])) {
                fprintf(stderr, "  %s region %s status column %u: %u, expected %u\n", label, regions[r].name, c,
                        counts[r][c], expected[r][c]);
            }
        }
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.codec.mutation");

    duoforge_context *c1 = df_make_context(&df_config_c1);
    duoforge_battle *dst = df_make_f2(c1);

    sweep(&t, c1, dst, df_golden_f1, expected_f1, false, "F1 decode");
    sweep(&t, c1, dst, df_golden_f2, expected_f2, false, "F2 decode");
    sweep(&t, c1, dst, df_golden_f1, expected_f1, true, "F1 create_decoded");

    /* 10,000 seeded multi-byte mutations: property checks only. */
    {
        dfi_rng rng;
        dfi_rng_seed(&rng, 20260930u, 1u);
        unsigned violations = 0;
        unsigned unknown = 0;
        uint8_t *in = df_heap_copy(df_golden_f1, DUOFORGE_STATE_V1_ENCODED_SIZE);
        for (unsigned i = 0; i < 10000; ++i) {
            memcpy(in, df_golden_f1, DUOFORGE_STATE_V1_ENCODED_SIZE);
            uint32_t n = 0;
            (void)dfi_rng_bounded_u32(&rng, 3u, &n);
            for (uint32_t j = 0; j < n + 2u; ++j) {
                uint32_t off = 0;
                uint32_t val = 0;
                (void)dfi_rng_bounded_u32(&rng, DUOFORGE_STATE_V1_ENCODED_SIZE, &off);
                (void)dfi_rng_bounded_u32(&rng, 256u, &val);
                in[off] = (uint8_t)val;
            }
            if (status_column(decode_one(&t, c1, dst, in, (i & 1u) != 0u, &violations)) < 0) {
                ++unknown;
            }
        }
        df_free(in);
        DF_CHECK_EQ_U64(&t, violations, 0u);
        DF_CHECK_EQ_U64(&t, unknown, 0u);
    }

    duoforge_battle_destroy(dst);
    duoforge_context_destroy(c1);
    return df_test_end(&t);
}
