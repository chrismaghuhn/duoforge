/*
 * T6 duoforge.state.context (black-box): context validation, fingerprints and
 * failure atomicity. Fingerprints: SHA-256 of the hand-assembled canonical
 * context bytes (tools/state_model; coreutils sha256sum). Fault values of the
 * form 2^w + valid detect a narrow-before-validate implementation.
 */
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "support/check.h"
#include "support/fixtures.h"

static void check_fp(df_test *t, const duoforge_context *ctx, const char *hex)
{
    uint8_t expected[DUOFORGE_DIGEST_SIZE];
    uint8_t fp[DUOFORGE_DIGEST_SIZE];
    memset(fp, 0xA5, sizeof fp);
    DF_CHECK(t, df_hex_to_bytes(hex, expected, sizeof expected));
    DF_CHECK(t, duoforge_context_fingerprint(ctx, fp) == DUOFORGE_OK);
    DF_CHECK_BYTES(t, fp, expected, sizeof fp, hex);
}

static void check_create_fails(df_test *t, duoforge_context_config c, const char *what)
{
    df_sentinel sentinel;
    duoforge_context *const marker = (duoforge_context *)(void *)&sentinel;
    duoforge_context *out = marker;
    const duoforge_status st = duoforge_context_create(&c, &out);
    const bool ok = DF_CHECK(t, st == DUOFORGE_E_INVALID_ARGUMENT) && DF_CHECK(t, out == marker);
    if (!ok) {
        fprintf(stderr, "  case: %s (status %s)\n", what, duoforge_status_name(st));
    }
}

static void check_create_ok(df_test *t, duoforge_context_config c, const char *what)
{
    duoforge_context *out = NULL;
    const duoforge_status st = duoforge_context_create(&c, &out);
    if (!DF_CHECK(t, st == DUOFORGE_OK && out != NULL)) {
        fprintf(stderr, "  case: %s (status %s)\n", what, duoforge_status_name(st));
    }
    duoforge_context_destroy(out);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.context");

    duoforge_context *c1 = df_make_context(&df_config_c1);
    duoforge_context *c1b = df_make_context(&df_config_c1);
    duoforge_context *c2 = df_make_context(&df_config_c2);
    duoforge_context *c3 = df_make_context(&df_config_c3);
    check_fp(&t, c1, DF_FP_C1_HEX);
    check_fp(&t, c1b, DF_FP_C1_HEX); /* an independent C1 has the same fingerprint */
    check_fp(&t, c2, DF_FP_C2_HEX);
    check_fp(&t, c3, DF_FP_C3_HEX);

    /* Variants are pairwise distinct from each other and from C1..C3. */
    {
        duoforge_context_config v[3] = {df_config_c1, df_config_c1, df_config_c1};
        v[0].max_roster = 5u;
        v[1].brought_count = 3u;
        v[2].species_count = 17u;
        uint8_t fps[6][DUOFORGE_DIGEST_SIZE];
        const duoforge_context *known[3] = {c1, c2, c3};
        for (unsigned i = 0; i < 3; ++i) {
            DF_CHECK(&t, duoforge_context_fingerprint(known[i], fps[i]) == DUOFORGE_OK);
            duoforge_context *vc = df_make_context(&v[i]);
            DF_CHECK(&t, duoforge_context_fingerprint(vc, fps[3 + i]) == DUOFORGE_OK);
            duoforge_context_destroy(vc);
        }
        unsigned equal_pairs = 0;
        for (unsigned i = 0; i < 6; ++i) {
            for (unsigned j = i + 1; j < 6; ++j) {
                equal_pairs += memcmp(fps[i], fps[j], DUOFORGE_DIGEST_SIZE) == 0 ? 1u : 0u;
            }
        }
        DF_CHECK_EQ_U64(&t, equal_pairs, 0u);
    }

    /* Single faults: INVALID_ARGUMENT and *out untouched. */
    {
        static const uint32_t data_kinds[] = {0u, 2u, UINT32_MAX, 257u};
        for (unsigned i = 0; i < 4; ++i) {
            duoforge_context_config c = df_config_c1;
            c.data_kind = data_kinds[i];
            check_create_fails(&t, c, "data_kind");
        }
        static const uint32_t rosters[] = {0u, 7u, 262u};
        for (unsigned i = 0; i < 3; ++i) {
            duoforge_context_config c = df_config_c1;
            c.max_roster = rosters[i];
            check_create_fails(&t, c, "max_roster");
        }
        static const uint32_t brought[] = {0u, 7u, 260u};
        for (unsigned i = 0; i < 3; ++i) {
            duoforge_context_config c = df_config_c1;
            c.brought_count = brought[i];
            check_create_fails(&t, c, "brought_count");
        }
        static const uint32_t species[] = {0u, 65536u, UINT32_MAX, 65552u};
        for (unsigned i = 0; i < 4; ++i) {
            duoforge_context_config c = df_config_c1;
            c.species_count = species[i];
            check_create_fails(&t, c, "species_count");
        }
        static const uint32_t moves[] = {0u, 65536u, 65568u};
        for (unsigned i = 0; i < 3; ++i) {
            duoforge_context_config c = df_config_c1;
            c.move_count = moves[i];
            check_create_fails(&t, c, "move_count");
        }
    }

    /* Boundaries accepted. */
    {
        duoforge_context_config c = df_config_c1;
        c.max_roster = 1u;
        c.brought_count = 1u;
        check_create_ok(&t, c, "max_roster 1 brought 1");
        c = df_config_c1;
        c.species_count = 65535u;
        check_create_ok(&t, c, "species 65535");
        c = df_config_c1;
        c.move_count = 65535u;
        check_create_ok(&t, c, "moves 65535");
        c = df_config_c1;
        c.brought_count = 6u;
        check_create_ok(&t, c, "brought = max_roster");
    }

    /* NULL handling. */
    {
        df_sentinel sentinel;
        duoforge_context *const marker = (duoforge_context *)(void *)&sentinel;
        duoforge_context *out = marker;
        DF_CHECK(&t, duoforge_context_create(NULL, &out) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, out == marker);
        DF_CHECK(&t, duoforge_context_create(&df_config_c1, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        uint8_t buf[DUOFORGE_DIGEST_SIZE];
        uint8_t before[DUOFORGE_DIGEST_SIZE];
        memset(buf, 0xA5, sizeof buf);
        memcpy(before, buf, sizeof buf);
        DF_CHECK(&t, duoforge_context_fingerprint(NULL, buf) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK_BYTES(&t, buf, before, sizeof buf, "fingerprint buffer untouched");
        DF_CHECK(&t, duoforge_context_fingerprint(c1, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        duoforge_context_destroy(NULL);
    }

    duoforge_context_destroy(c1);
    duoforge_context_destroy(c1b);
    duoforge_context_destroy(c2);
    duoforge_context_destroy(c3);
    return df_test_end(&t);
}
