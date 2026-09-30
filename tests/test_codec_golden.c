/*
 * T11 duoforge.codec.golden (white-box parts marked): canonical encodings of
 * F1/F2/F3 equal the hand-assembled goldens (independent structural model),
 * digests equal the literal SHA-256 values, decode round-trips byte-exactly,
 * the RNG continues across encode/decode exactly as the pinned KAT, and the
 * canonical C1 context bytes hash to the C1 fingerprint.
 */
#include <stdio.h>
#include <string.h>

#include "core/sha256.h"
#include "rng/pcg32.h"
#include "state/battle_internal.h"
#include "state/context_internal.h"
#include "support/check.h"
#include "support/fixtures.h"

static void check_digest(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, const char *hex,
                         const uint8_t *golden, const char *what)
{
    uint8_t expected[DUOFORGE_DIGEST_SIZE];
    uint8_t digest[DUOFORGE_DIGEST_SIZE];
    uint8_t golden_sha[DUOFORGE_DIGEST_SIZE];
    DF_CHECK(t, df_hex_to_bytes(hex, expected, sizeof expected));
    DF_CHECK(t, duoforge_battle_digest(ctx, b, digest) == DUOFORGE_OK);
    DF_CHECK_BYTES(t, digest, expected, sizeof digest, what);
    /* The literal digest is also the SHA-256 of the golden bytes. */
    DF_CHECK(t, dfi_sha256(golden, DUOFORGE_STATE_V1_ENCODED_SIZE, golden_sha));
    DF_CHECK_BYTES(t, golden_sha, expected, sizeof golden_sha, what);
}

static void check_encode(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, const uint8_t *golden,
                         const char *what)
{
    uint8_t buf[DUOFORGE_STATE_V1_ENCODED_SIZE];
    size_t written = 0;
    memset(buf, 0xA5, sizeof buf);
    DF_CHECK(t, duoforge_battle_encode(ctx, b, buf, sizeof buf, &written) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, written, 380u);
    DF_CHECK_BYTES(t, buf, golden, sizeof buf, what);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.codec.golden");

    duoforge_context *c1 = df_make_context(&df_config_c1);
    duoforge_context *c3 = df_make_context(&df_config_c3);
    duoforge_battle_setup setup;

    df_setup_f1(&setup);
    duoforge_battle *f1 = df_make_battle(c1, &setup);
    duoforge_battle *f2 = df_make_f2(c1);
    df_setup_f3(&setup);
    duoforge_battle *f3 = df_make_battle(c3, &setup);

    size_t size = 0;
    DF_CHECK(&t, duoforge_battle_encoded_size(c1, f1, &size) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(&t, size, 380u); /* literal from the layout table */

    check_encode(&t, c1, f1, df_golden_f1, "encode F1");
    check_encode(&t, c1, f2, df_golden_f2, "encode F2");
    check_encode(&t, c3, f3, df_golden_f3, "encode F3");
    check_digest(&t, c1, f1, DF_DIGEST_F1_HEX, df_golden_f1, "digest F1");
    check_digest(&t, c1, f2, DF_DIGEST_F2_HEX, df_golden_f2, "digest F2");
    check_digest(&t, c3, f3, DF_DIGEST_F3_HEX, df_golden_f3, "digest F3");

    /* Round trips: create_decoded of F1/F2, decode(dst) of F3. */
    {
        const struct {
            const duoforge_context *ctx;
            const uint8_t *golden;
            const duoforge_battle *built;
        } cases[] = {{c1, df_golden_f1, f1}, {c1, df_golden_f2, f2}};
        for (unsigned i = 0; i < 2; ++i) {
            uint8_t *in = df_heap_copy(cases[i].golden, DUOFORGE_STATE_V1_ENCODED_SIZE);
            duoforge_battle *d = NULL;
            DF_CHECK(&t, duoforge_battle_create_decoded(cases[i].ctx, in, DUOFORGE_STATE_V1_ENCODED_SIZE, &d) ==
                             DUOFORGE_OK);
            check_encode(&t, cases[i].ctx, d, cases[i].golden, "re-encode decoded");
            bool eq = false;
            DF_CHECK(&t, duoforge_battle_equal(cases[i].ctx, d, cases[i].built, &eq) == DUOFORGE_OK && eq);
            duoforge_battle_destroy(d);
            df_free(in);
        }
        duoforge_battle *dst = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c3, f3, &dst) == DUOFORGE_OK);
        dst->sides[0].members[0].hp = 7u; /* make dst differ before decode */
        uint8_t *in = df_heap_copy(df_golden_f3, DUOFORGE_STATE_V1_ENCODED_SIZE);
        DF_CHECK(&t, duoforge_battle_decode(c3, dst, in, DUOFORGE_STATE_V1_ENCODED_SIZE) == DUOFORGE_OK);
        check_encode(&t, c3, dst, df_golden_f3, "decode into dst");
        df_free(in);
        duoforge_battle_destroy(dst);
    }

    /* RNG continuation across encode/decode (white-box): F1, 5 draws, encode,
     * decode, 11 more draws equal KAT raw[5..15]; state after 16 draws. */
    {
        static const uint32_t raw16[16] = {
            0xa15c02b7u, 0x7b47f409u, 0xba1d3330u, 0x83d2f293u, 0xbfa4784bu, 0xcbed606eu, 0xbfc6a3adu, 0x812fff6du,
            0xe61f305au, 0xf9384b90u, 0x32db86feu, 0x1dc035f9u, 0xed786826u, 0x3822441du, 0x2ba113d7u, 0x1c5b818bu,
        };
        duoforge_battle *a = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, f1, &a) == DUOFORGE_OK);
        for (unsigned i = 0; i < 5; ++i) {
            uint32_t v = 0;
            DF_CHECK(&t, dfi_rng_next_u32(&a->rng, &v) == DUOFORGE_OK);
            DF_CHECK_EQ_U64(&t, v, raw16[i]);
        }
        uint8_t enc[DUOFORGE_STATE_V1_ENCODED_SIZE];
        df_encode(c1, a, enc);
        uint8_t *in = df_heap_copy(enc, sizeof enc);
        duoforge_battle *d = NULL;
        DF_CHECK(&t, duoforge_battle_create_decoded(c1, in, sizeof enc, &d) == DUOFORGE_OK);
        for (unsigned i = 5; i < 16; ++i) {
            uint32_t v = 0;
            DF_CHECK(&t, dfi_rng_next_u32(&d->rng, &v) == DUOFORGE_OK);
            DF_CHECK_EQ_U64(&t, v, raw16[i]);
        }
        DF_CHECK_EQ_U64(&t, d->rng.draws, 16u);
        DF_CHECK_EQ_U64(&t, d->rng.state, UINT64_C(0xbdaaa7a4f94ba8e8));
        duoforge_battle_destroy(d);
        duoforge_battle_destroy(a);
        df_free(in);
    }

    /* Canonical C1 context bytes and their SHA-256 (white-box). */
    {
        uint8_t bytes[DFI_CONTEXT_BYTES_SIZE];
        uint8_t sha[DUOFORGE_DIGEST_SIZE];
        uint8_t fp[DUOFORGE_DIGEST_SIZE];
        uint8_t expected[DUOFORGE_DIGEST_SIZE];
        dfi_context_canonical_bytes(c1, bytes);
        DF_CHECK_BYTES(&t, bytes, df_context_c1_bytes, sizeof bytes, "C1 canonical bytes");
        DF_CHECK(&t, dfi_sha256(bytes, sizeof bytes, sha));
        DF_CHECK(&t, duoforge_context_fingerprint(c1, fp) == DUOFORGE_OK);
        DF_CHECK(&t, df_hex_to_bytes(DF_FP_C1_HEX, expected, sizeof expected));
        DF_CHECK_BYTES(&t, sha, expected, sizeof sha, "sha(C1 bytes)");
        DF_CHECK_BYTES(&t, fp, expected, sizeof fp, "C1 fingerprint");
    }

    duoforge_battle_destroy(f1);
    duoforge_battle_destroy(f2);
    duoforge_battle_destroy(f3);
    duoforge_context_destroy(c1);
    duoforge_context_destroy(c3);
    return df_test_end(&t);
}
