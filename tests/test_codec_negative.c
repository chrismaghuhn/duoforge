/*
 * T12 duoforge.codec.negative (white-box parts marked): strict decoding v2.
 * Every decode case runs through BOTH entry points (decode into dst: dst
 * unchanged; create_decoded: *out untouched, no leak) with exact-size heap
 * inputs, so a read past the size is an ASan heap-buffer-overflow in the
 * sanitizer job. Also: the M1 golden as a "rejected: schema 1" input,
 * targeted invariant edits (ids from the independent model), capacity
 * semantics, corrupt-state encode/digest/check, and encoder coverage on
 * arbitrary state. Expectations: the layout and decode order in
 * docs/decisions/0002 and 0005.
 */
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "codec/state_codec.h"
#include "core/bytes.h"
#include "support/check.h"
#include "support/fixtures.h"

#define SZ DUOFORGE_STATE_V2_ENCODED_SIZE

typedef struct env {
    df_test *t;
    const duoforge_context *c1;
    duoforge_battle *dst; /* bound to C1, holds F2 */
} env;

static void raw(const duoforge_battle *b, uint8_t out[SZ])
{
    memset(out, 0, SZ);
    dfi_encode_unchecked(b, out);
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
    duoforge_context *c1b = df_make_context(&df_config_c1);
    duoforge_context *c2 = df_make_context(&df_config_c2);
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
    with_byte(&e, 10, 3, DUOFORGE_E_SCHEMA_MISMATCH, "schema 3");
    with_byte(&e, 12, 0, DUOFORGE_E_SEMANTICS_MISMATCH, "semantics 0");
    with_byte(&e, 12, 1, DUOFORGE_E_SEMANTICS_MISMATCH, "semantics 1");
    with_byte(&e, 12, 3, DUOFORGE_E_SEMANTICS_MISMATCH, "semantics 3");
    {
        /* A longer future schema reports SCHEMA_MISMATCH (checked before length). */
        uint8_t b[460];
        memset(b, 0, sizeof b);
        memcpy(b, g, SZ);
        dfi_store_u16le(b + 10, 3u);
        dfi_store_u32le(b + 16, 460u);
        decode_both(&e, b, sizeof b, DUOFORGE_E_SCHEMA_MISMATCH, "schema 3 at 460 bytes");
    }
    /* "Rejected: schema 1": the M1 golden (380 bytes) through the v2 decoder.
     * Schema first; with the schema patched the semantics id (1) rejects;
     * with both patched the size (380 != 438) rejects. */
    {
        uint8_t b[380];
        memcpy(b, df_golden_v1_f1, sizeof b);
        decode_both(&e, b, sizeof b, DUOFORGE_E_SCHEMA_MISMATCH, "M1 golden: schema 1");
        dfi_store_u16le(b + 10, 2u);
        decode_both(&e, b, sizeof b, DUOFORGE_E_SEMANTICS_MISMATCH, "M1 golden: semantics 1");
        dfi_store_u32le(b + 12, 2u);
        decode_both(&e, b, sizeof b, DUOFORGE_E_MALFORMED, "M1 golden: 380 bytes");
    }
    /* Decode order, pinned pairwise: each input carries two faults and the
     * earlier check in the documented order must win. */
    {
        uint8_t b[460];
        memcpy(b, g, SZ);
        b[0] ^= 1u;
        b[8] = 3;
        decode_both(&e, b, SZ, DUOFORGE_E_MALFORMED, "magic before kind");
        memcpy(b, g, SZ);
        b[8] = 3;
        b[12] = 3;
        decode_both(&e, b, SZ, DUOFORGE_E_SCHEMA_MISMATCH, "kind before semantics");
        memcpy(b, g, SZ);
        b[10] = 3;
        b[12] = 3;
        decode_both(&e, b, SZ, DUOFORGE_E_SCHEMA_MISMATCH, "schema before semantics");
        memcpy(b, g, SZ);
        b[12] = 3;
        dfi_store_u32le(b + 16, 437u);
        decode_both(&e, b, SZ, DUOFORGE_E_SEMANTICS_MISMATCH, "semantics before length");
        memcpy(b, g, SZ);
        dfi_store_u32le(b + 16, 437u);
        b[20] ^= 1u;
        decode_both(&e, b, SZ, DUOFORGE_E_MALFORMED, "length before context");
        memset(b, 0, sizeof b);
        memcpy(b, g, SZ);
        dfi_store_u32le(b + 16, 460u);
        b[20] ^= 1u;
        decode_both(&e, b, 460, DUOFORGE_E_MALFORMED, "size before context");
        memcpy(b, g, SZ);
        b[20] ^= 1u;
        b[60] = 0x6C;
        decode_both(&e, b, SZ, DUOFORGE_E_CONTEXT_MISMATCH, "context before invariants");
    }
    /* total_length vs size. */
    {
        uint8_t b[SZ];
        memcpy(b, g, sizeof b);
        dfi_store_u32le(b + 16, 437u);
        decode_both(&e, b, sizeof b, DUOFORGE_E_MALFORMED, "total_length 437");
        dfi_store_u32le(b + 16, 439u);
        decode_both(&e, b, sizeof b, DUOFORGE_E_MALFORMED, "total_length 439");
        uint8_t c[460];
        memset(c, 0, sizeof c);
        memcpy(c, g, SZ);
        dfi_store_u32le(c + 16, 460u);
        decode_both(&e, c, sizeof c, DUOFORGE_E_MALFORMED, "total_length 460 at 460 bytes");
    }
    /* Consistent short inputs (total_length patched to the size): the
     * two-sided size check must reject them without over-reading. */
    {
        static const size_t sizes[] = {20, 21, 51, 52, 85, 86, 261, 262, 437};
        for (size_t i = 0; i < sizeof sizes / sizeof sizes[0]; ++i) {
            uint8_t b[SZ];
            memcpy(b, g, sizeof b);
            dfi_store_u32le(b + 16, (uint32_t)sizes[i]);
            decode_both(&e, b, sizes[i], DUOFORGE_E_MALFORMED, "consistent short input");
        }
    }
#if SIZE_MAX > UINT32_MAX
    /* Oversized size: only the first 20 bytes may be read, and size must not
     * be narrowed (438 + 2^32 narrowed to 32 bits would equal 438). */
    decode_both_sized(&e, g, SZ, (size_t)SZ + (size_t)UINT64_C(0x100000000), DUOFORGE_E_MALFORMED,
                      "size 438 + 2^32");
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
        decode_both(&e, b, sizeof b, DUOFORGE_E_MALFORMED, "439 bytes");
    }
    /* 41 targeted invariant edits: MALFORMED publicly, exact id white-box
     * (offsets and ids from tools/state_model/state_v2_model.py TARGETED). */
    {
        static const struct {
            size_t off;
            uint8_t value;
            dfi_invariant inv;
        } edits[] = {
            {60, 0x6C, DFI_INV_RNG_INC_EVEN},
            {76, 0, DFI_INV_NEXT_ACTIVATION_ZERO},
            {80, 0, DFI_INV_BOUNDARY_KIND},
            {80, 5, DFI_INV_BOUNDARY_KIND},
            {82, 0, DFI_INV_EPOCH_ZERO},
            {81, 0, DFI_INV_REQUEST_MASK},
            {81, 4, DFI_INV_REQUEST_MASK},
            {86, 3, DFI_INV_MEMBER_COUNT},
            {86, 7, DFI_INV_MEMBER_COUNT},
            {118, 16, DFI_INV_SPECIES_RANGE},
            {122, 0, DFI_INV_HP_MAX_ZERO},
            {120, 101, DFI_INV_HP_ABOVE_MAX},
            {124, 0, DFI_INV_MOVE_COUNT},
            {124, 5, DFI_INV_MOVE_COUNT},
            {126, 36, DFI_INV_MOVE_ID_RANGE},
            {129, 0, DFI_INV_PP_MAX_ZERO},
            {128, 6, DFI_INV_PP_ABOVE_MAX},
            {130, 1, DFI_INV_UNUSED_MOVE_NONZERO},
            {125, 2, DFI_INV_MEGA_CAPABLE_RANGE},
            {390, 1, DFI_INV_UNUSED_MEMBER_NONZERO},
            {263, 0x17, DFI_INV_BROUGHT_OUT_OF_RANGE},
            {87, 0x07, DFI_INV_BROUGHT_COUNT},
            {92, 5, DFI_INV_BROUGHT_ORDER},
            {95, 0xFF, DFI_INV_BROUGHT_ORDER},
            {96, 0, DFI_INV_BROUGHT_ORDER},
            {89, 2, DFI_INV_MEGA_USED_RANGE},
            {98, 0xFF, DFI_INV_EMPTY_WITH_ACTIVATION},
            {280, 0, DFI_INV_OCCUPIED_WITHOUT_ACTIVATION},
            {274, 4, DFI_INV_OCCUPANT_RANGE},
            {98, 4, DFI_INV_OCCUPANT_NOT_BROUGHT},
            {99, 5, DFI_INV_ACTIVATION_NOT_ISSUED},
            {103, 2, DFI_INV_OCCUPANT_DUPLICATE},
            {88, 1, DFI_INV_REQUESTED_SLOTS},
            {88, 4, DFI_INV_REQUESTED_SLOTS},
            {90, 2, DFI_INV_SEALED_RANGE},
            {90, 1, DFI_INV_SEALED_RULE},
            {108, 1, DFI_INV_SEALED_COMMAND},
            {275, 1, DFI_INV_ACTIVATION_DUPLICATE},
            {91, 0x1A, DFI_INV_SEEN_MASK},
            {91, 0x08, DFI_INV_SEEN_MASK},
            {267, 0x10, DFI_INV_SEEN_MASK},
        };
        DF_CHECK_EQ_U64(&t, sizeof edits / sizeof edits[0], 41u);
        for (size_t i = 0; i < sizeof edits / sizeof edits[0]; ++i) {
            uint8_t b[SZ];
            memcpy(b, g, sizeof b);
            b[edits[i].off] = edits[i].value;
            decode_both(&e, b, sizeof b, DUOFORGE_E_MALFORMED, dfi_invariant_name(edits[i].inv));
            duoforge_battle tmp;
            memset(&tmp, 0, sizeof tmp);
            dfi_invariant got = DFI_INV_NONE;
            uint8_t *in = df_heap_copy(b, sizeof b);
            DF_CHECK(&t, dfi_decode_state(c1, in, sizeof b, &tmp, &got) == DUOFORGE_E_MALFORMED);
            if (!DF_CHECK(&t, got == edits[i].inv)) {
                fprintf(stderr, "  edit %zu=0x%02x: got %s, expected %s\n", edits[i].off, (unsigned)edits[i].value,
                        dfi_invariant_name(got), dfi_invariant_name(edits[i].inv));
            }
            df_free(in);
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
    /* Capacity: E_CAPACITY writes nothing; OK writes exactly 438 bytes. */
    {
        uint8_t buf[460];
        uint8_t pattern[460];
        memset(pattern, 0xA5, sizeof pattern);
        const size_t caps[] = {0, 437};
        for (unsigned i = 0; i < 2; ++i) {
            memset(buf, 0xA5, sizeof buf);
            size_t written = 0xDEADBEEFu;
            DF_CHECK(&t, duoforge_battle_encode(c1, f2, buf, caps[i], &written) == DUOFORGE_E_CAPACITY);
            DF_CHECK(&t, written == 0xDEADBEEFu);
            DF_CHECK_BYTES(&t, buf, pattern, sizeof buf, "capacity failure writes nothing");
        }
        const size_t okcaps[] = {438, 460};
        for (unsigned i = 0; i < 2; ++i) {
            memset(buf, 0xA5, sizeof buf);
            size_t written = 0;
            DF_CHECK(&t, duoforge_battle_encode(c1, f2, buf, okcaps[i], &written) == DUOFORGE_OK);
            DF_CHECK_EQ_U64(&t, written, 438u);
            DF_CHECK_BYTES(&t, buf, df_golden_f2, SZ, "encoded F2");
            DF_CHECK_BYTES(&t, buf + SZ, pattern + SZ, 22, "bytes after 438 untouched");
        }
    }
    /* Corrupt state (white-box): encode/digest/check report INVARIANT with
     * outputs untouched; encoded_size is still 438 (documented). */
    {
        duoforge_battle *x = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, f2, &x) == DUOFORGE_OK);
        x->sides[1].members[0].move_count = 0u;
        uint8_t buf[460];
        uint8_t pattern[460];
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
        DF_CHECK(&t, duoforge_battle_encoded_size(c1, x, &size) == DUOFORGE_OK && size == 438u);
        duoforge_battle_destroy(x);
    }
    /* Encoder coverage (white-box): on valid and arbitrary states, encoding
     * into buffers pre-filled with 0x00 and 0xFF gives identical bytes, which
     * proves all 438 bytes are written unconditionally. */
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
            dfi_encode_unchecked(states[i], a);
            dfi_encode_unchecked(states[i], b);
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
    return df_test_end(&t);
}
