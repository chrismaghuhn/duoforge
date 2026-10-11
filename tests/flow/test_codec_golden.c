/*
 * T11 duoforge.codec.golden (white-box parts marked): canonical v3 encodings
 * of F1/F2/F3/F5 equal the goldens of the independent structural model,
 * digests of G1/F1/F2/G3/F3/F5 equal the literal SHA-256 values, decode
 * round-trips byte-exactly, the RNG continues across encode/decode exactly as
 * the pinned KAT, and the canonical C1 context bytes hash to the C1
 * fingerprint.
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
    if (golden != NULL) {
        /* The literal digest is also the SHA-256 of the golden bytes. */
        DF_CHECK(t, dfi_sha256(golden, DUOFORGE_STATE_V3_ENCODED_SIZE, golden_sha));
        DF_CHECK_BYTES(t, golden_sha, expected, sizeof golden_sha, what);
    }
}

static void check_encode(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, const uint8_t *golden,
                         const char *what)
{
    uint8_t buf[DUOFORGE_STATE_V3_ENCODED_SIZE];
    size_t written = 0;
    memset(buf, 0xA5, sizeof buf);
    DF_CHECK(t, duoforge_battle_encode(ctx, b, buf, sizeof buf, &written) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, written, 1009u);
    DF_CHECK_BYTES(t, buf, golden, sizeof buf, what);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.codec.golden");

    duoforge_context *c1 = df_make_context(&df_config_c1);
    duoforge_context *c3 = df_make_context(&df_config_c3);
    duoforge_battle *g1 = df_make_g1(c1);
    duoforge_battle *f1 = df_make_f1(c1);
    duoforge_battle *f2 = df_make_f2(c1);
    duoforge_battle *g3 = df_make_g3(c3);
    duoforge_battle *f3 = df_make_f3(c3);
    duoforge_battle *f5 = df_make_f5(c1);

    size_t size = 0;
    DF_CHECK(&t, duoforge_battle_encoded_size(c1, f1, &size) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(&t, size, 1009u); /* literal from the layout table */

    check_encode(&t, c1, f1, df_golden_f1, "encode F1");
    check_encode(&t, c1, f2, df_golden_f2, "encode F2");
    check_encode(&t, c3, f3, df_golden_f3, "encode F3");
    check_encode(&t, c1, f5, df_golden_f5, "encode F5");
    check_digest(&t, c1, g1, DF_DIGEST_G1_HEX, NULL, "digest G1");
    check_digest(&t, c1, f1, DF_DIGEST_F1_HEX, df_golden_f1, "digest F1");
    check_digest(&t, c1, f2, DF_DIGEST_F2_HEX, df_golden_f2, "digest F2");
    check_digest(&t, c3, g3, DF_DIGEST_G3_HEX, NULL, "digest G3");
    check_digest(&t, c3, f3, DF_DIGEST_F3_HEX, df_golden_f3, "digest F3");
    check_digest(&t, c1, f5, DF_DIGEST_F5_HEX, df_golden_f5, "digest F5");
    /* The remaining white-box fixtures are pinned by their digests, so every
     * builder produces exactly the state of the structural model. */
    {
        duoforge_context *c4 = df_make_context(&df_config_c4);
        duoforge_battle *rest[10] = {df_make_f4(c1),  df_make_f6(c1),  df_make_g7(c4),  df_make_f8(c4),
                                     df_make_f9(c4),  df_make_f10(c4), df_make_f11(c4), df_make_f12(c4),
                                     df_make_f13(c4), NULL};
        static const char *const hex[9] = {DF_DIGEST_F4_HEX,  DF_DIGEST_F6_HEX,  DF_DIGEST_G7_HEX,
                                           DF_DIGEST_F8_HEX,  DF_DIGEST_F9_HEX,  DF_DIGEST_F10_HEX,
                                           DF_DIGEST_F11_HEX, DF_DIGEST_F12_HEX, DF_DIGEST_F13_HEX};
        for (unsigned i = 0; i < 9; ++i) {
            check_digest(&t, i < 2 ? c1 : c4, rest[i], hex[i], NULL, "digest of a white-box fixture");
            duoforge_battle_destroy(rest[i]);
        }
        duoforge_context_destroy(c4);
    }

    /* Layout spot checks on the F1 golden (decision 0005 section 9). */
    DF_CHECK_EQ_U64(&t, df_golden_f1[80], DUOFORGE_BOUNDARY_TURN); /* boundary_kind */
    DF_CHECK_EQ_U64(&t, df_golden_f1[81], 3u);                     /* request_mask */
    DF_CHECK_EQ_U64(&t, df_golden_f1[82], 2u);                     /* epoch low byte */
    DF_CHECK_EQ_U64(&t, df_golden_f1[86], 1u);                     /* turn low byte */
    DF_CHECK_EQ_U64(&t, df_golden_f1[94], 0u);                     /* queue_len */
    DF_CHECK_EQ_U64(&t, df_golden_f1[216], 0x0Fu);                 /* s0 brought */
    DF_CHECK_EQ_U64(&t, df_golden_f1[220], 0x0Au);                 /* s0 seen (s1 leads 1,3) */
    DF_CHECK_EQ_U64(&t, df_golden_f1[221], 2u);                    /* s0 order[0] */
    DF_CHECK_EQ_U64(&t, df_golden_f1[235], 6u);                    /* s0a first stage: neutral */
    DF_CHECK_EQ_U64(&t, df_golden_f1[289], 100u);                  /* s0 knows s1 member 1 at 100 percent */
    DF_CHECK_EQ_U64(&t, df_golden_f1[617], 0x05u);                 /* s1 seen (s0 leads 2,0) */
    /* And on the F5 golden, which uses every v3 group. */
    DF_CHECK_EQ_U64(&t, df_golden_f5[80], DUOFORGE_BOUNDARY_PIVOT);
    DF_CHECK_EQ_U64(&t, df_golden_f5[86], 7u);                     /* turn */
    DF_CHECK_EQ_U64(&t, df_golden_f5[89], 1u);                     /* weather: rain */
    DF_CHECK_EQ_U64(&t, df_golden_f5[94], 3u);                     /* queue_len */
    DF_CHECK_EQ_U64(&t, df_golden_f5[95], 5u);                     /* first record: a move */
    DF_CHECK_EQ_U64(&t, df_golden_f5[115], 6u);                    /* third record: the residual */
    DF_CHECK_EQ_U64(&t, df_golden_f5[227], 8u);                    /* s0 Reflect turns */
    DF_CHECK_EQ_U64(&t, df_golden_f5[237], 12u);                   /* s0a third stage: +6 */
    DF_CHECK_EQ_U64(&t, df_golden_f5[612 + 67 + 14], 100u);        /* s1 knows s0 member 2 */
    DF_CHECK_EQ_U64(&t, df_golden_f5[215 + 67 + 7], 50u);          /* s0 knows s1 member 1 at 50 percent */
    DF_CHECK_EQ_U64(&t, df_golden_f5[215 + 67 + 8], DUOFORGE_HP_FLAG_GREEN);
    DF_CHECK_EQ_U64(&t, df_golden_f5[215 + 15 + 20], 1u);          /* s0a switch flag: a self-switch move */

    /* Round trips: create_decoded of F1/F2, decode(dst) of F3. */
    {
        const struct {
            const duoforge_context *ctx;
            const uint8_t *golden;
            const duoforge_battle *built;
        } cases[] = {{c1, df_golden_f1, f1}, {c1, df_golden_f2, f2}};
        for (unsigned i = 0; i < 2; ++i) {
            uint8_t *in = df_heap_copy(cases[i].golden, DUOFORGE_STATE_V3_ENCODED_SIZE);
            duoforge_battle *d = NULL;
            DF_CHECK(&t, duoforge_battle_create_decoded(cases[i].ctx, in, DUOFORGE_STATE_V3_ENCODED_SIZE, &d) ==
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
        uint8_t *in = df_heap_copy(df_golden_f3, DUOFORGE_STATE_V3_ENCODED_SIZE);
        DF_CHECK(&t, duoforge_battle_decode(c3, dst, in, DUOFORGE_STATE_V3_ENCODED_SIZE) == DUOFORGE_OK);
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
        uint8_t enc[DUOFORGE_STATE_V3_ENCODED_SIZE];
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
        uint8_t table_sha[DUOFORGE_DIGEST_SIZE];
        dfi_context_canonical_bytes(c1, bytes);
        DF_CHECK_BYTES(&t, bytes, df_context_c1_bytes, sizeof bytes, "C1 canonical bytes");
        DF_CHECK(&t, dfi_sha256(bytes, sizeof bytes, sha));
        DF_CHECK(&t, duoforge_context_fingerprint(c1, fp) == DUOFORGE_OK);
        DF_CHECK(&t, df_hex_to_bytes(DF_FP_C1_HEX, expected, sizeof expected));
        DF_CHECK_BYTES(&t, sha, expected, sizeof sha, "sha(C1 bytes)");
        DF_CHECK_BYTES(&t, fp, expected, sizeof fp, "C1 fingerprint");
        /* Bytes 31..63 are the SHA-256 of the 36-byte table. */
        DF_CHECK(&t, dfi_sha256(df_table_t1, sizeof df_table_t1, table_sha));
        DF_CHECK_BYTES(&t, bytes + 31, table_sha, sizeof table_sha, "table hash in preimage");
    }

    duoforge_battle_destroy(g1);
    duoforge_battle_destroy(f1);
    duoforge_battle_destroy(f2);
    duoforge_battle_destroy(g3);
    duoforge_battle_destroy(f3);
    duoforge_battle_destroy(f5);
    duoforge_context_destroy(c1);
    duoforge_context_destroy(c3);
    return df_test_end(&t);
}
