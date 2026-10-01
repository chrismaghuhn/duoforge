/*
 * T14 duoforge.api.atomicity: status names and pinned values; NULL sweep over
 * every public state function and pointer parameter; context-mismatch sweep
 * (every output unchanged); error precedence. Expectations: the public API
 * contract in include/duoforge/duoforge.h and docs/decisions/0002, 0005.
 * The M2 request/step functions have their own atomicity tests.
 */
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"

typedef struct probe {
    uint8_t buf[460];
    size_t written;
    size_t size;
    uint8_t digest[DUOFORGE_DIGEST_SIZE];
} probe;

static void probe_reset(probe *p)
{
    memset(p->buf, 0xA5, sizeof p->buf);
    p->written = 0xDEADBEEFu;
    p->size = 0xDEADBEEFu;
    memset(p->digest, 0xA5, sizeof p->digest);
}

static bool probe_untouched(const probe *p)
{
    for (size_t i = 0; i < sizeof p->buf; ++i) {
        if (p->buf[i] != 0xA5) {
            return false;
        }
    }
    for (size_t i = 0; i < sizeof p->digest; ++i) {
        if (p->digest[i] != 0xA5) {
            return false;
        }
    }
    return p->written == 0xDEADBEEFu && p->size == 0xDEADBEEFu;
}

static void enc(const duoforge_context *ctx, const duoforge_battle *b, uint8_t out[DUOFORGE_STATE_V3_ENCODED_SIZE])
{
    df_encode(ctx, b, out);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.api.atomicity");

    /* Status names and pinned values (0..10 stable since M1; 11, 12 added in M2). */
    {
        static const struct {
            duoforge_status code;
            uint32_t value;
            const char *name;
        } names[] = {
            {DUOFORGE_OK, 0u, "DUOFORGE_OK"},
            {DUOFORGE_E_NULL_ARGUMENT, 1u, "DUOFORGE_E_NULL_ARGUMENT"},
            {DUOFORGE_E_INVALID_ARGUMENT, 2u, "DUOFORGE_E_INVALID_ARGUMENT"},
            {DUOFORGE_E_CONTEXT_MISMATCH, 3u, "DUOFORGE_E_CONTEXT_MISMATCH"},
            {DUOFORGE_E_CAPACITY, 4u, "DUOFORGE_E_CAPACITY"},
            {DUOFORGE_E_MALFORMED, 5u, "DUOFORGE_E_MALFORMED"},
            {DUOFORGE_E_SCHEMA_MISMATCH, 6u, "DUOFORGE_E_SCHEMA_MISMATCH"},
            {DUOFORGE_E_SEMANTICS_MISMATCH, 7u, "DUOFORGE_E_SEMANTICS_MISMATCH"},
            {DUOFORGE_E_INVARIANT, 8u, "DUOFORGE_E_INVARIANT"},
            {DUOFORGE_E_EXHAUSTED, 9u, "DUOFORGE_E_EXHAUSTED"},
            {DUOFORGE_E_OUT_OF_MEMORY, 10u, "DUOFORGE_E_OUT_OF_MEMORY"},
            {DUOFORGE_E_UNSUPPORTED, 11u, "DUOFORGE_E_UNSUPPORTED"},
            {DUOFORGE_E_STALE_EPOCH, 12u, "DUOFORGE_E_STALE_EPOCH"},
        };
        for (size_t i = 0; i < sizeof names / sizeof names[0]; ++i) {
            DF_CHECK_EQ_U64(&t, names[i].code, names[i].value);
            DF_CHECK(&t, strcmp(duoforge_status_name(names[i].code), names[i].name) == 0);
        }
        DF_CHECK(&t, strcmp(duoforge_status_name(13u), "DUOFORGE_STATUS_UNKNOWN") == 0);
        DF_CHECK(&t, strcmp(duoforge_status_name(0xFFFFFFFFu), "DUOFORGE_STATUS_UNKNOWN") == 0);
        DF_CHECK_EQ_U64(&t, DUOFORGE_SEMANTICS_ID, 3u);
        DF_CHECK_EQ_U64(&t, DUOFORGE_CONTEXT_SCHEMA_VERSION, 3u);
        DF_CHECK_EQ_U64(&t, DUOFORGE_STATE_SCHEMA_VERSION, 3u);
        DF_CHECK(&t, strcmp(duoforge_version_string(), "0.11.0") == 0);
    }

    duoforge_context *c1 = df_make_context(&df_config_c1);
    duoforge_context *c2 = df_make_context(&df_config_c2);
    duoforge_battle_setup setup;
    df_setup_g1(&setup);
    duoforge_battle *b1 = df_make_f1(c1);             /* bound to C1 */
    duoforge_battle *b2 = df_make_battle(c2, &setup); /* bound to C2 */
    uint8_t e1[DUOFORGE_STATE_V3_ENCODED_SIZE];
    uint8_t e2[DUOFORGE_STATE_V3_ENCODED_SIZE];
    uint8_t golden_before[DUOFORGE_STATE_V3_ENCODED_SIZE];
    enc(c1, b1, golden_before);
    probe p;
    df_sentinel sentinel;
    duoforge_battle *const marker = (duoforge_battle *)(void *)&sentinel;
    duoforge_battle *outb = marker;
    const uint8_t *g = df_golden_f1;

    /* NULL sweep: every public function x each pointer parameter. */
    {
        probe_reset(&p);
        DF_CHECK(&t, duoforge_battle_create(NULL, &setup, &outb) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_create(c1, NULL, &outb) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_create(c1, &setup, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_create_decoded(NULL, g, 1009, &outb) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_create_decoded(c1, NULL, 1009, &outb) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_create_decoded(c1, NULL, 0, &outb) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_create_decoded(c1, g, 1009, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_clone(NULL, b1, &outb) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_clone(c1, NULL, &outb) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_clone(c1, b1, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, outb == marker);
        DF_CHECK(&t, duoforge_battle_copy(NULL, b1, b1) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_copy(c1, NULL, b1) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_copy(c1, b1, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_decode(NULL, b1, g, 1009) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_decode(c1, NULL, g, 1009) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_decode(c1, b1, NULL, 1009) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_decode(c1, b1, NULL, 0) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_check(NULL, b1) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_check(c1, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        for (unsigned preset = 0; preset < 2; ++preset) {
            bool eq = preset == 1;
            DF_CHECK(&t, duoforge_battle_equal(NULL, b1, b1, &eq) == DUOFORGE_E_NULL_ARGUMENT);
            DF_CHECK(&t, duoforge_battle_equal(c1, NULL, b1, &eq) == DUOFORGE_E_NULL_ARGUMENT);
            DF_CHECK(&t, duoforge_battle_equal(c1, b1, NULL, &eq) == DUOFORGE_E_NULL_ARGUMENT);
            DF_CHECK(&t, eq == (preset == 1));
        }
        DF_CHECK(&t, duoforge_battle_equal(c1, b1, b1, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_encoded_size(NULL, b1, &p.size) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_encoded_size(c1, NULL, &p.size) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_encoded_size(c1, b1, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_encode(NULL, b1, p.buf, 460, &p.written) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_encode(c1, NULL, p.buf, 460, &p.written) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_encode(c1, b1, NULL, 460, &p.written) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_encode(c1, b1, NULL, 0, &p.written) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_encode(c1, b1, p.buf, 460, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_digest(NULL, b1, p.digest) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_digest(c1, NULL, p.digest) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_digest(c1, b1, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_reseed(NULL, b1, 1u, 2u) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_reseed(c1, NULL, 1u, 2u) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, probe_untouched(&p));
        enc(c1, b1, e1);
        DF_CHECK_BYTES(&t, e1, golden_before, sizeof e1, "battle unchanged by NULL sweep");
        duoforge_battle_destroy(NULL);
        duoforge_context_destroy(NULL);
    }

    /* Context-mismatch sweep: C1 on a battle bound to C2; every output unchanged. */
    {
        probe_reset(&p);
        enc(c2, b2, e2);
        outb = marker;
        DF_CHECK(&t, duoforge_battle_clone(c1, b2, &outb) == DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK(&t, outb == marker);
        DF_CHECK(&t, duoforge_battle_copy(c1, b2, b1) == DUOFORGE_E_CONTEXT_MISMATCH); /* dst */
        DF_CHECK(&t, duoforge_battle_copy(c1, b1, b2) == DUOFORGE_E_CONTEXT_MISMATCH); /* src */
        DF_CHECK(&t, duoforge_battle_decode(c1, b2, g, 1009) == DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK(&t, duoforge_battle_check(c1, b2) == DUOFORGE_E_CONTEXT_MISMATCH);
        for (unsigned preset = 0; preset < 2; ++preset) {
            bool eq = preset == 1;
            DF_CHECK(&t, duoforge_battle_equal(c1, b2, b1, &eq) == DUOFORGE_E_CONTEXT_MISMATCH);
            DF_CHECK(&t, duoforge_battle_equal(c1, b1, b2, &eq) == DUOFORGE_E_CONTEXT_MISMATCH);
            DF_CHECK(&t, eq == (preset == 1));
        }
        DF_CHECK(&t, duoforge_battle_encoded_size(c1, b2, &p.size) == DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK(&t, duoforge_battle_encode(c1, b2, p.buf, 460, &p.written) == DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK(&t, duoforge_battle_digest(c1, b2, p.digest) == DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK(&t, duoforge_battle_reseed(c1, b2, 1u, 2u) == DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK(&t, probe_untouched(&p));
        uint8_t now[DUOFORGE_STATE_V3_ENCODED_SIZE];
        enc(c2, b2, now);
        DF_CHECK_BYTES(&t, now, e2, sizeof now, "C2 battle unchanged");
        enc(c1, b1, now);
        DF_CHECK_BYTES(&t, now, golden_before, sizeof now, "C1 battle unchanged");
    }

    /* Precedence. */
    {
        probe_reset(&p);
        DF_CHECK(&t, duoforge_battle_encode(c1, b2, NULL, 460, &p.written) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_encode(c1, b2, p.buf, 0, &p.written) == DUOFORGE_E_CONTEXT_MISMATCH);
        /* Corrupt state (white-box): INVARIANT is reported before CAPACITY
         * (acceptable only because encode is privileged). */
        duoforge_battle *x = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, b1, &x) == DUOFORGE_OK);
        x->sides[0].member_count = 0xFFu;
        DF_CHECK(&t, duoforge_battle_encode(c1, x, p.buf, 0, &p.written) == DUOFORGE_E_INVARIANT);
        duoforge_battle_destroy(x);
        uint8_t garbage[4] = {0, 0, 0, 0};
        DF_CHECK(&t, duoforge_battle_decode(c1, b2, garbage, sizeof garbage) == DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK(&t, probe_untouched(&p));
    }

    duoforge_battle_destroy(b1);
    duoforge_battle_destroy(b2);
    duoforge_context_destroy(c1);
    duoforge_context_destroy(c2);
    return df_test_end(&t);
}
