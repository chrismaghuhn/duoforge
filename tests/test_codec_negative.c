/*
 * T12 duoforge.codec.negative (white-box parts marked): strict decoding v3.
 * Every decode case runs through BOTH entry points (decode into dst: dst
 * unchanged; create_decoded: *out untouched, no leak) with exact-size heap
 * inputs, so a read past the size is an ASan heap-buffer-overflow in the
 * sanitizer job. Also: the M1 and M2 goldens as "rejected: old schema"
 * inputs, targeted invariant edits (ids from the independent model),
 * capacity semantics, corrupt-state encode/digest/check, and encoder
 * coverage on arbitrary state. Expectations: the layout and decode order in
 * docs/decisions/0002, 0005 and 0006.
 */
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "codec/state_codec.h"
#include "core/bytes.h"
#include "support/check.h"
#include "support/fixtures.h"

#define SZ DUOFORGE_STATE_V3_ENCODED_SIZE
#define BIG (SZ + 22u) /* a buffer longer than the encoding */

typedef struct env {
    df_test *t;
    const duoforge_context *c1;
    duoforge_battle *dst; /* bound to C1, holds F2 */
} env;

/* The kinds of this test are all schema 3 (no POOL tail): any such context encodes them. */
static const duoforge_context *enc_ctx;

static void raw(const duoforge_battle *b, uint8_t out[SZ])
{
    memset(out, 0, SZ);
    (void)dfi_encode_unchecked(enc_ctx, b, out);
}

/* Decodes bytes[0..size) through both entry points; size may exceed the
 * allocation only when alloc_size is given separately (oversized case). */
static void decode_both_sized(env *e, const uint8_t *bytes, size_t alloc_size, size_t size, duoforge_status expected,
                              const char *what)
{
    df_test *t = e->t;
    uint8_t before[SZ];
    uint8_t after[SZ];
    uint8_t *in = df_heap_copy(bytes, alloc_size);
    raw(e->dst, before);
    duoforge_status st = duoforge_battle_decode(e->c1, e->dst, in, size);
    if (!DF_CHECK(t, st == expected)) {
        fprintf(stderr, "  decode case %s: %s, expected %s\n", what, duoforge_status_name(st),
                duoforge_status_name(expected));
    }
    raw(e->dst, after);
    if (st != DUOFORGE_OK) {
        DF_CHECK_BYTES(t, after, before, sizeof after, what);
    }
    df_free(in);
    in = df_heap_copy(bytes, alloc_size);
    df_sentinel sentinel;
    duoforge_battle *const marker = (duoforge_battle *)(void *)&sentinel;
    duoforge_battle *out = marker;
    st = duoforge_battle_create_decoded(e->c1, in, size, &out);
    if (!DF_CHECK(t, st == expected)) {
        fprintf(stderr, "  create_decoded case %s: %s, expected %s\n", what, duoforge_status_name(st),
                duoforge_status_name(expected));
    }
    if (st == DUOFORGE_OK) {
        duoforge_battle_destroy(out);
    } else {
        DF_CHECK(t, out == marker);
    }
    df_free(in);
}

static void decode_both(env *e, const uint8_t *bytes, size_t size, duoforge_status expected, const char *what)
{
    decode_both_sized(e, bytes, size, size, expected, what);
}

static void with_byte(env *e, size_t off, uint8_t value, duoforge_status expected, const char *what)
{
    uint8_t b[SZ];
    memcpy(b, df_golden_f1, sizeof b);
    b[off] = value;
    decode_both(e, b, sizeof b, expected, what);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.codec.negative");

    duoforge_context *c1 = df_make_context(&df_config_c1);
    enc_ctx = c1;
    duoforge_context *c1b = df_make_context(&df_config_c1);
    duoforge_context *c2 = df_make_context(&df_config_c2);
    duoforge_context *c4 = df_make_context(&df_config_c4);
    duoforge_battle *f2 = df_make_f2(c1);
    env e = {&t, c1, f2};
    const uint8_t *g = df_golden_f1;

    /* Sizes below the envelope. */
    decode_both(&e, g, 0, DUOFORGE_E_MALFORMED, "size 0");
    decode_both(&e, g, 7, DUOFORGE_E_MALFORMED, "size 7");
    decode_both(&e, g, 19, DUOFORGE_E_MALFORMED, "size 19");
    /* Each magic byte flipped; CRLF-translated magic (byte 4 removed). */
    for (size_t i = 0; i < 8; ++i) {
        with_byte(&e, i, (uint8_t)(g[i] ^ 0x01u), DUOFORGE_E_MALFORMED, "magic byte");
    }
    {
        uint8_t b[SZ - 1];
        memcpy(b, g, 4);
        memcpy(b + 4, g + 5, sizeof b - 4);
        decode_both(&e, b, sizeof b, DUOFORGE_E_MALFORMED, "CRLF-translated magic");
    }
    /* Kind, schema, semantics. */
    with_byte(&e, 8, 1, DUOFORGE_E_SCHEMA_MISMATCH, "kind 1");
    with_byte(&e, 8, 3, DUOFORGE_E_SCHEMA_MISMATCH, "kind 3");
    with_byte(&e, 10, 0, DUOFORGE_E_SCHEMA_MISMATCH, "schema 0");
    with_byte(&e, 10, 1, DUOFORGE_E_SCHEMA_MISMATCH, "schema 1");
    with_byte(&e, 10, 2, DUOFORGE_E_SCHEMA_MISMATCH, "schema 2");
    with_byte(&e, 10, 4, DUOFORGE_E_SCHEMA_MISMATCH, "schema 4");
    with_byte(&e, 12, 0, DUOFORGE_E_SEMANTICS_MISMATCH, "semantics 0");
    with_byte(&e, 12, 1, DUOFORGE_E_SEMANTICS_MISMATCH, "semantics 1");
    with_byte(&e, 12, 2, DUOFORGE_E_SEMANTICS_MISMATCH, "semantics 2");
    with_byte(&e, 12, 4, DUOFORGE_E_SEMANTICS_MISMATCH, "semantics 4");
    {
        /* A longer future schema reports SCHEMA_MISMATCH (checked before length). */
        uint8_t b[BIG];
        memset(b, 0, sizeof b);
        memcpy(b, g, SZ);
        dfi_store_u16le(b + 10, 4u);
        dfi_store_u32le(b + 16, BIG);
        decode_both(&e, b, sizeof b, DUOFORGE_E_SCHEMA_MISMATCH, "schema 4 at a longer size");
    }
    /* "Rejected: schema 1": the M1 golden (380 bytes) through the v3 decoder.
     * Schema first; with the schema patched the semantics id (1) rejects;
     * with both patched the size (380 != 1009) rejects. */
    {
        uint8_t b[380];
        memcpy(b, df_golden_v1_f1, sizeof b);
        decode_both(&e, b, sizeof b, DUOFORGE_E_SCHEMA_MISMATCH, "M1 golden: schema 1");
        dfi_store_u16le(b + 10, 3u);
        decode_both(&e, b, sizeof b, DUOFORGE_E_SEMANTICS_MISMATCH, "M1 golden: semantics 1");
        dfi_store_u32le(b + 12, 3u);
        decode_both(&e, b, sizeof b, DUOFORGE_E_MALFORMED, "M1 golden: 380 bytes");
    }
    /* "Rejected: schema 2": the M2 golden (438 bytes), the same three steps. */
    {
        uint8_t b[438];
        memcpy(b, df_golden_v2_f1, sizeof b);
        decode_both(&e, b, sizeof b, DUOFORGE_E_SCHEMA_MISMATCH, "M2 golden: schema 2");
        dfi_store_u16le(b + 10, 3u);
        decode_both(&e, b, sizeof b, DUOFORGE_E_SEMANTICS_MISMATCH, "M2 golden: semantics 2");
        dfi_store_u32le(b + 12, 3u);
        decode_both(&e, b, sizeof b, DUOFORGE_E_MALFORMED, "M2 golden: 438 bytes");
    }
    /* Decode order, pinned pairwise: each input carries two faults and the
     * earlier check in the documented order must win. */
    {
        uint8_t b[BIG];
        memcpy(b, g, SZ);
        b[0] ^= 1u;
        b[8] = 3;
        decode_both(&e, b, SZ, DUOFORGE_E_MALFORMED, "magic before kind");
        memcpy(b, g, SZ);
        b[8] = 3;
        b[12] = 4;
        decode_both(&e, b, SZ, DUOFORGE_E_SCHEMA_MISMATCH, "kind before semantics");
        memcpy(b, g, SZ);
        b[10] = 4;
        b[12] = 4;
        decode_both(&e, b, SZ, DUOFORGE_E_SCHEMA_MISMATCH, "schema before semantics");
        memcpy(b, g, SZ);
        b[12] = 4;
        dfi_store_u32le(b + 16, SZ - 1u);
        decode_both(&e, b, SZ, DUOFORGE_E_SEMANTICS_MISMATCH, "semantics before length");
        memcpy(b, g, SZ);
        dfi_store_u32le(b + 16, SZ - 1u);
        b[20] ^= 1u;
        decode_both(&e, b, SZ, DUOFORGE_E_MALFORMED, "length before context");
        memset(b, 0, sizeof b);
        memcpy(b, g, SZ);
        dfi_store_u32le(b + 16, BIG);
        b[20] ^= 1u;
        decode_both(&e, b, BIG, DUOFORGE_E_MALFORMED, "size before context");
        memcpy(b, g, SZ);
        b[20] ^= 1u;
        b[60] = 0x6C;
        decode_both(&e, b, SZ, DUOFORGE_E_CONTEXT_MISMATCH, "context before invariants");
    }
    /* total_length vs size. */
    {
        uint8_t b[SZ];
        memcpy(b, g, sizeof b);
        dfi_store_u32le(b + 16, SZ - 1u);
        decode_both(&e, b, sizeof b, DUOFORGE_E_MALFORMED, "total_length one less");
        dfi_store_u32le(b + 16, SZ + 1u);
        decode_both(&e, b, sizeof b, DUOFORGE_E_MALFORMED, "total_length one more");
        uint8_t c[BIG];
        memset(c, 0, sizeof c);
        memcpy(c, g, SZ);
        dfi_store_u32le(c + 16, BIG);
        decode_both(&e, c, sizeof c, DUOFORGE_E_MALFORMED, "consistent longer input");
    }
    /* Consistent short inputs (total_length patched to the size): the
     * two-sided size check must reject them without over-reading. */
    {
        static const size_t sizes[] = {20, 21, 51, 52, 85, 86, 94, 95, 214, 215, 611, 612, 1008};
        for (size_t i = 0; i < sizeof sizes / sizeof sizes[0]; ++i) {
            uint8_t b[SZ];
            memcpy(b, g, sizeof b);
            dfi_store_u32le(b + 16, (uint32_t)sizes[i]);
            decode_both(&e, b, sizes[i], DUOFORGE_E_MALFORMED, "consistent short input");
        }
    }
#if SIZE_MAX > UINT32_MAX
    /* Oversized size: only the first 20 bytes may be read, and size must not
     * be narrowed (1009 + 2^32 narrowed to 32 bits would equal 1009). */
    decode_both_sized(&e, g, SZ, (size_t)SZ + (size_t)UINT64_C(0x100000000), DUOFORGE_E_MALFORMED,
                      "size 1009 + 2^32");
#endif
    /* Context mismatch: a C2 encoding under C1; a dst bound to C2. */
    {
        duoforge_battle_setup setup;
        df_setup_g1(&setup);
        duoforge_battle *b2 = df_make_battle(c2, &setup);
        uint8_t enc[SZ];
        df_encode(c2, b2, enc);
        decode_both(&e, enc, sizeof enc, DUOFORGE_E_CONTEXT_MISMATCH, "C2 encoding under C1");
        uint8_t before[SZ];
        uint8_t after[SZ];
        uint8_t garbage[3] = {1, 2, 3};
        uint8_t *in = df_heap_copy(garbage, sizeof garbage);
        raw(b2, before);
        DF_CHECK(&t, duoforge_battle_decode(c1, b2, in, sizeof garbage) == DUOFORGE_E_CONTEXT_MISMATCH);
        raw(b2, after);
        DF_CHECK_BYTES(&t, after, before, sizeof after, "dst bound to C2 unchanged");
        df_free(in);
        duoforge_battle_destroy(b2);
    }
    /* Every truncation of F1 (total_length intact), and one extra byte. */
    for (size_t n = 0; n < SZ; ++n) {
        decode_both(&e, g, n, DUOFORGE_E_MALFORMED, "truncation");
    }
    {
        uint8_t b[SZ + 1];
        memcpy(b, g, SZ);
        b[SZ] = 0;
        decode_both(&e, b, sizeof b, DUOFORGE_E_MALFORMED, "one extra byte");
    }
    /* 139 targeted invariant edits over seven fixtures: MALFORMED publicly, the
     * exact id white-box. Rows are the TARGETED list of
     * tools/state_model/state_v3_model.py, in its order. */
    {
        enum { FX_G1, FX_F1, FX_F2, FX_F4, FX_F5, FX_F6, FX_F13, FX_COUNT };
        duoforge_battle *fx[FX_COUNT] = {df_make_g1(c1), df_make_f1(c1), df_make_f2(c1), df_make_f4(c1),
                                         df_make_f5(c1), df_make_f6(c1), df_make_f13(c4)};
        const duoforge_context *fx_ctx[FX_COUNT] = {c1, c1, c1, c1, c1, c1, c4};
        uint8_t enc[FX_COUNT][SZ];
        for (unsigned i = 0; i < FX_COUNT; ++i) {
            df_encode(fx_ctx[i], fx[i], enc[i]);
        }
        static const struct {
            uint8_t fixture;
            uint16_t off;
            uint8_t value;
            dfi_invariant inv;
        } edits[] = {
            {FX_F1, 60, 0x6C, DFI_INV_RNG_INC_EVEN},
            {FX_F1, 76, 0x00, DFI_INV_NEXT_ACTIVATION_ZERO},
            {FX_F1, 80, 0x00, DFI_INV_BOUNDARY_KIND},
            {FX_F1, 80, 0x06, DFI_INV_BOUNDARY_KIND},
            {FX_F1, 82, 0x00, DFI_INV_EPOCH_ZERO},
            {FX_F1, 81, 0x00, DFI_INV_REQUEST_MASK},
            {FX_F1, 81, 0x04, DFI_INV_REQUEST_MASK},
            {FX_F1, 80, 0x05, DFI_INV_REQUEST_MASK},
            {FX_F13, 81, 0x01, DFI_INV_REQUEST_MASK},
            {FX_F1, 86, 0x00, DFI_INV_TURN_COUNTER},
            {FX_G1, 86, 0x01, DFI_INV_TURN_COUNTER},
            {FX_F1, 88, 0x01, DFI_INV_RESULT},
            {FX_F1, 88, 0x04, DFI_INV_RESULT},
            {FX_F13, 88, 0x00, DFI_INV_RESULT},
            {FX_F13, 88, 0x04, DFI_INV_RESULT},
            {FX_F1, 89, 0x01, DFI_INV_FIELD},
            {FX_F1, 89, 0x03, DFI_INV_FIELD},
            {FX_F1, 90, 0x01, DFI_INV_FIELD},
            {FX_F5, 90, 0x06, DFI_INV_FIELD},
            {FX_F1, 91, 0x01, DFI_INV_FIELD},
            {FX_F1, 92, 0x01, DFI_INV_FIELD},
            {FX_F5, 91, 0x02, DFI_INV_FIELD},
            {FX_F5, 92, 0x00, DFI_INV_FIELD},
            {FX_F1, 93, 0x06, DFI_INV_FIELD},
            {FX_F1, 215, 0x03, DFI_INV_MEMBER_COUNT},
            {FX_F1, 215, 0x07, DFI_INV_MEMBER_COUNT},
            {FX_F1, 324, 0x10, DFI_INV_SPECIES_RANGE},
            {FX_F1, 328, 0x00, DFI_INV_HP_MAX_ZERO},
            {FX_F1, 326, 0x65, DFI_INV_HP_ABOVE_MAX},
            {FX_F1, 340, 0x00, DFI_INV_MOVE_COUNT},
            {FX_F1, 340, 0x05, DFI_INV_MOVE_COUNT},
            {FX_F1, 356, 0x24, DFI_INV_MOVE_ID_RANGE},
            {FX_F1, 359, 0x00, DFI_INV_PP_MAX_ZERO},
            {FX_F1, 358, 0x06, DFI_INV_PP_ABOVE_MAX},
            {FX_F1, 360, 0x01, DFI_INV_UNUSED_MOVE_NONZERO},
            {FX_F1, 341, 0x02, DFI_INV_MEGA_CAPABLE_RANGE},
            {FX_F1, 330, 0x01, DFI_INV_MEMBER_EXTRA},
            {FX_F1, 339, 0x01, DFI_INV_MEMBER_EXTRA},
            {FX_F1, 342, 0x01, DFI_INV_MEMBER_EXTRA},
            {FX_F1, 343, 0x01, DFI_INV_MEMBER_EXTRA},
            {FX_F1, 344, 0x01, DFI_INV_MEMBER_EXTRA},
            {FX_F1, 345, 0x01, DFI_INV_MEMBER_EXTRA},
            {FX_F1, 350, 0x01, DFI_INV_MEMBER_EXTRA},
            {FX_F1, 351, 0x01, DFI_INV_MEMBER_EXTRA},
            {FX_F1, 352, 0x01, DFI_INV_MEMBER_EXTRA},
            {FX_F1, 353, 0x01, DFI_INV_MEMBER_EXTRA},
            {FX_F1, 354, 0x01, DFI_INV_MEMBER_EXTRA},
            {FX_F1, 355, 0x01, DFI_INV_MEMBER_EXTRA},
            {FX_F1, 913, 0x01, DFI_INV_UNUSED_MEMBER_NONZERO},
            {FX_F1, 990, 0x01, DFI_INV_UNUSED_MEMBER_NONZERO},
            {FX_F1, 613, 0x17, DFI_INV_BROUGHT_OUT_OF_RANGE},
            {FX_F1, 216, 0x07, DFI_INV_BROUGHT_COUNT},
            {FX_F1, 221, 0x05, DFI_INV_BROUGHT_ORDER},
            {FX_F1, 224, 0xFF, DFI_INV_BROUGHT_ORDER},
            {FX_F1, 225, 0x00, DFI_INV_BROUGHT_ORDER},
            {FX_F1, 218, 0x02, DFI_INV_MEGA_USED_RANGE},
            {FX_F1, 227, 0x09, DFI_INV_SIDE_CONDITION},
            {FX_F1, 228, 0x09, DFI_INV_SIDE_CONDITION},
            {FX_F1, 229, 0x05, DFI_INV_SIDE_CONDITION},
            {FX_F1, 230, 0xFF, DFI_INV_EMPTY_WITH_ACTIVATION},
            {FX_F1, 649, 0x00, DFI_INV_OCCUPIED_WITHOUT_ACTIVATION},
            {FX_F1, 627, 0x04, DFI_INV_OCCUPANT_RANGE},
            {FX_F1, 230, 0x04, DFI_INV_OCCUPANT_NOT_BROUGHT},
            {FX_F1, 231, 0x05, DFI_INV_ACTIVATION_NOT_ISSUED},
            {FX_F1, 251, 0x02, DFI_INV_OCCUPANT_DUPLICATE},
            {FX_F1, 235, 0x0D, DFI_INV_VOLATILE},
            {FX_F1, 242, 0x08, DFI_INV_VOLATILE},
            {FX_F1, 243, 0x01, DFI_INV_VOLATILE},
            {FX_F1, 243, 0x07, DFI_INV_VOLATILE},
            {FX_F1, 244, 0x01, DFI_INV_VOLATILE},
            {FX_F5, 265, 0x03, DFI_INV_VOLATILE},
            {FX_F1, 245, 0x06, DFI_INV_VOLATILE},
            {FX_F1, 246, 0x01, DFI_INV_VOLATILE},
            {FX_F5, 643, 0x03, DFI_INV_VOLATILE},
            {FX_F1, 247, 0x01, DFI_INV_VOLATILE},
            {FX_F5, 644, 0x05, DFI_INV_VOLATILE},
            {FX_F1, 248, 0x01, DFI_INV_VOLATILE},
            {FX_F5, 645, 0x04, DFI_INV_VOLATILE},
            {FX_F5, 268, 0x02, DFI_INV_VOLATILE},
            {FX_F1, 250, 0x04, DFI_INV_VOLATILE},
            {FX_F2, 653, 0x05, DFI_INV_VOLATILE},
            {FX_F2, 660, 0x01, DFI_INV_VOLATILE},
            {FX_F2, 667, 0x01, DFI_INV_VOLATILE},
            {FX_F2, 668, 0x01, DFI_INV_VOLATILE},
            {FX_F1, 217, 0x01, DFI_INV_REQUESTED_SLOTS},
            {FX_F1, 217, 0x04, DFI_INV_REQUESTED_SLOTS},
            {FX_F13, 217, 0x01, DFI_INV_REQUESTED_SLOTS},
            {FX_F1, 250, 0x01, DFI_INV_SWITCH_FLAG},
            {FX_F5, 250, 0x00, DFI_INV_SWITCH_FLAG},
            {FX_F5, 271, 0x01, DFI_INV_SWITCH_FLAG},
            {FX_F5, 647, 0x02, DFI_INV_SWITCH_FLAG},
            {FX_F6, 668, 0x00, DFI_INV_SWITCH_FLAG},
            {FX_F4, 250, 0x01, DFI_INV_SWITCH_FLAG},
            {FX_F1, 219, 0x02, DFI_INV_SEALED_RANGE},
            {FX_F1, 219, 0x01, DFI_INV_SEALED_RULE},
            {FX_F5, 616, 0x01, DFI_INV_SEALED_RULE},
            {FX_F1, 272, 0x01, DFI_INV_SEALED_COMMAND},
            {FX_F1, 628, 0x01, DFI_INV_ACTIVATION_DUPLICATE},
            {FX_F1, 220, 0x1A, DFI_INV_SEEN_MASK},
            {FX_F1, 220, 0x08, DFI_INV_SEEN_MASK},
            {FX_F1, 617, 0x10, DFI_INV_SEEN_MASK},
            {FX_F1, 282, 0x01, DFI_INV_KNOWLEDGE},
            {FX_F1, 285, 0x01, DFI_INV_KNOWLEDGE},
            {FX_F1, 289, 0x63, DFI_INV_KNOWLEDGE},
            {FX_F1, 290, 0x01, DFI_INV_KNOWLEDGE},
            {FX_F1, 683, 0x01, DFI_INV_KNOWLEDGE},
            {FX_F2, 693, 0x65, DFI_INV_KNOWLEDGE},
            {FX_F2, 694, 0x03, DFI_INV_KNOWLEDGE},
            {FX_F2, 694, 0x00, DFI_INV_KNOWLEDGE},
            {FX_F1, 291, 0x01, DFI_INV_KNOWLEDGE},
            {FX_F1, 291, 0x02, DFI_INV_KNOWLEDGE},
            {FX_F1, 291, 0x04, DFI_INV_KNOWLEDGE},
            {FX_F1, 284, 0x01, DFI_INV_KNOWLEDGE},
            {FX_F1, 94, 0x01, DFI_INV_QUEUE},
            {FX_F1, 95, 0x01, DFI_INV_QUEUE},
            {FX_F1, 104, 0x01, DFI_INV_QUEUE},
            {FX_F5, 94, 0x00, DFI_INV_QUEUE},
            {FX_F5, 94, 0x0D, DFI_INV_QUEUE},
            {FX_F5, 94, 0x02, DFI_INV_QUEUE},
            {FX_F5, 94, 0x04, DFI_INV_QUEUE},
            {FX_F5, 95, 0x00, DFI_INV_QUEUE},
            {FX_F5, 95, 0x07, DFI_INV_QUEUE},
            {FX_F5, 96, 0x02, DFI_INV_QUEUE},
            {FX_F5, 97, 0x02, DFI_INV_QUEUE},
            {FX_F5, 98, 0x06, DFI_INV_QUEUE}, /* 5 is the recharge turn since step G17 */
            {FX_F5, 99, 0x04, DFI_INV_QUEUE},
            {FX_F5, 100, 0x01, DFI_INV_QUEUE},
            {FX_F5, 101, 0x05, DFI_INV_QUEUE},
            {FX_F5, 101, 0x00, DFI_INV_QUEUE},
            {FX_F5, 116, 0x01, DFI_INV_QUEUE},
            {FX_F5, 121, 0x01, DFI_INV_QUEUE},
            {FX_F6, 100, 0x06, DFI_INV_QUEUE},
            {FX_F6, 101, 0x01, DFI_INV_QUEUE},
            {FX_F6, 98, 0x01, DFI_INV_QUEUE},
            {FX_F6, 110, 0x01, DFI_INV_QUEUE},
            {FX_F6, 111, 0x00, DFI_INV_QUEUE},
            {FX_F6, 120, 0x04, DFI_INV_QUEUE},
            {FX_F6, 121, 0x00, DFI_INV_QUEUE},
            {FX_F6, 130, 0x01, DFI_INV_QUEUE},
        };
        DF_CHECK_EQ_U64(&t, sizeof edits / sizeof edits[0], 139u);
        unsigned ids_seen[DFI_INV_COUNT] = {0};
        for (size_t i = 0; i < sizeof edits / sizeof edits[0]; ++i) {
            const duoforge_context *ctx = fx_ctx[edits[i].fixture];
            uint8_t b[SZ];
            memcpy(b, enc[edits[i].fixture], sizeof b);
            DF_CHECK(&t, b[edits[i].off] != edits[i].value); /* the edit changes the byte */
            b[edits[i].off] = edits[i].value;
            if (ctx == c1) {
                decode_both(&e, b, sizeof b, DUOFORGE_E_MALFORMED, dfi_invariant_name(edits[i].inv));
            }
            uint8_t *in = df_heap_copy(b, sizeof b);
            df_sentinel sentinel;
            duoforge_battle *const marker = (duoforge_battle *)(void *)&sentinel;
            duoforge_battle *out = marker;
            DF_CHECK(&t, duoforge_battle_create_decoded(ctx, in, sizeof b, &out) == DUOFORGE_E_MALFORMED);
            DF_CHECK(&t, out == marker);
            duoforge_battle tmp;
            memset(&tmp, 0, sizeof tmp);
            dfi_invariant got = DFI_INV_NONE;
            DF_CHECK(&t, dfi_decode_state(ctx, in, sizeof b, &tmp, &got) == DUOFORGE_E_MALFORMED);
            if (!DF_CHECK(&t, got == edits[i].inv)) {
                fprintf(stderr, "  edit %u=0x%02x: got %s, expected %s\n", (unsigned)edits[i].off,
                        (unsigned)edits[i].value, dfi_invariant_name(got), dfi_invariant_name(edits[i].inv));
            }
            ids_seen[edits[i].inv] += 1u;
            df_free(in);
        }
        /* Every id a single byte can trigger is covered (the fingerprint is
         * CONTEXT_MISMATCH and has its own cases above). The TAIL ids of the POOL state tail cannot be reached by
         * a byte of a schema 3 fixture; duoforge.state.pool_tail covers them. */
        for (unsigned id = DFI_INV_RNG_INC_EVEN; id <= DFI_INV_QUEUE; ++id) {
            if (!DF_CHECK(&t, ids_seen[id] > 0u)) {
                fprintf(stderr, "  no targeted edit for %s\n", dfi_invariant_name((dfi_invariant)id));
            }
        }
        /* Single-byte edits that stay valid: the checker is structural. */
        static const struct {
            uint8_t fixture;
            uint16_t off;
            uint8_t value;
        } accepted[] = {
            {FX_F1, 249, 0xC8},
            {FX_F1, 235, 0x00},
            {FX_F1, 235, 0x0C},
            {FX_F1, 227, 0x08},
            {FX_F1, 229, 0x04},
            {FX_F1, 93, 0x05},
            {FX_F5, 99, 0xFF},
            {FX_F5, 250, 0x02},
        };
        for (size_t i = 0; i < sizeof accepted / sizeof accepted[0]; ++i) {
            uint8_t b[SZ];
            memcpy(b, enc[accepted[i].fixture], sizeof b);
            DF_CHECK(&t, b[accepted[i].off] != accepted[i].value);
            b[accepted[i].off] = accepted[i].value;
            uint8_t *in = df_heap_copy(b, sizeof b);
            duoforge_battle *out = NULL;
            DF_CHECK(&t, duoforge_battle_create_decoded(fx_ctx[accepted[i].fixture], in, sizeof b, &out) == DUOFORGE_OK);
            duoforge_battle_destroy(out);
            df_free(in);
        }
        for (unsigned i = 0; i < FX_COUNT; ++i) {
            duoforge_battle_destroy(fx[i]);
        }
    }
    /* F1 decodes under an independently created second C1. */
    {
        duoforge_battle *d = NULL;
        uint8_t *in = df_heap_copy(g, SZ);
        DF_CHECK(&t, duoforge_battle_create_decoded(c1b, in, SZ, &d) == DUOFORGE_OK);
        duoforge_battle_destroy(d);
        df_free(in);
    }
    /* Capacity: E_CAPACITY writes nothing; OK writes exactly 1009 bytes. */
    {
        uint8_t buf[BIG];
        uint8_t pattern[BIG];
        memset(pattern, 0xA5, sizeof pattern);
        const size_t caps[] = {0, 1008};
        for (unsigned i = 0; i < 2; ++i) {
            memset(buf, 0xA5, sizeof buf);
            size_t written = 0xDEADBEEFu;
            DF_CHECK(&t, duoforge_battle_encode(c1, f2, buf, caps[i], &written) == DUOFORGE_E_CAPACITY);
            DF_CHECK(&t, written == 0xDEADBEEFu);
            DF_CHECK_BYTES(&t, buf, pattern, sizeof buf, "capacity failure writes nothing");
        }
        const size_t okcaps[] = {1009, BIG};
        for (unsigned i = 0; i < 2; ++i) {
            memset(buf, 0xA5, sizeof buf);
            size_t written = 0;
            DF_CHECK(&t, duoforge_battle_encode(c1, f2, buf, okcaps[i], &written) == DUOFORGE_OK);
            DF_CHECK_EQ_U64(&t, written, 1009u);
            DF_CHECK_BYTES(&t, buf, df_golden_f2, SZ, "encoded F2");
            DF_CHECK_BYTES(&t, buf + SZ, pattern + SZ, 22, "bytes after the encoding untouched");
        }
    }
    /* Corrupt state (white-box): encode/digest/check report INVARIANT with
     * outputs untouched; encoded_size is still 1009 (documented). */
    {
        duoforge_battle *x = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, f2, &x) == DUOFORGE_OK);
        x->sides[1].members[0].move_count = 0u;
        uint8_t buf[BIG];
        uint8_t pattern[BIG];
        memset(buf, 0xA5, sizeof buf);
        memset(pattern, 0xA5, sizeof pattern);
        size_t written = 0xDEADBEEFu;
        DF_CHECK(&t, duoforge_battle_encode(c1, x, buf, sizeof buf, &written) == DUOFORGE_E_INVARIANT);
        DF_CHECK(&t, written == 0xDEADBEEFu);
        DF_CHECK_BYTES(&t, buf, pattern, sizeof buf, "encode of corrupt writes nothing");
        DF_CHECK(&t, duoforge_battle_digest(c1, x, buf) == DUOFORGE_E_INVARIANT);
        DF_CHECK_BYTES(&t, buf, pattern, sizeof buf, "digest of corrupt writes nothing");
        DF_CHECK(&t, duoforge_battle_check(c1, x) == DUOFORGE_E_INVARIANT);
        size_t size = 0;
        DF_CHECK(&t, duoforge_battle_encoded_size(c1, x, &size) == DUOFORGE_OK && size == 1009u);
        duoforge_battle_destroy(x);
    }
    /* Encoder coverage (white-box): on valid and arbitrary states, encoding
     * into buffers pre-filled with 0x00 and 0xFF gives identical bytes, which
     * proves all 1009 bytes are written unconditionally. */
    {
        duoforge_battle *f1 = df_make_f1(c1);
        duoforge_battle *states[7];
        for (unsigned i = 0; i < 7; ++i) {
            states[i] = NULL;
            DF_CHECK(&t, duoforge_battle_clone(c1, i == 1 ? f2 : f1, &states[i]) == DUOFORGE_OK);
        }
        states[2]->sides[0].member_count = 0xFFu;
        states[3]->sides[1].members[2].move_count = 0xFFu;
        states[4]->sides[0].positions[1].occupant = 0xFEu;
        memset(states[5], 0xFF, sizeof *states[5]);
        memset(states[6], 0xA5, sizeof *states[6]);
        unsigned differing = 0;
        for (unsigned i = 0; i < 7; ++i) {
            uint8_t a[SZ];
            uint8_t b[SZ];
            memset(a, 0x00, sizeof a);
            memset(b, 0xFF, sizeof b);
            (void)dfi_encode_unchecked(enc_ctx, states[i], a);
            (void)dfi_encode_unchecked(enc_ctx, states[i], b);
            differing += memcmp(a, b, sizeof a) != 0 ? 1u : 0u;
            duoforge_battle_destroy(states[i]);
        }
        DF_CHECK_EQ_U64(&t, differing, 0u);
        duoforge_battle_destroy(f1);
    }

    duoforge_battle_destroy(f2);
    duoforge_context_destroy(c1);
    duoforge_context_destroy(c1b);
    duoforge_context_destroy(c2);
    duoforge_context_destroy(c4);
    return df_test_end(&t);
}
