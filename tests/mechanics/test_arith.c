/*
 * T2 duoforge.unit.arith (white-box): checked integer helpers, narrowing,
 * rotation, popcount and byte order. Expectations are hand-derived or come
 * from independent bit-loop oracles. Extreme values (0xFF bytes, UINTn_MAX)
 * let GCC UBSan catch integer-promotion mistakes.
 */
#include <string.h>

#include "core/arith.h"
#include "core/bytes.h"
#include "support/check.h"

static uint32_t oracle_rotr32(uint32_t x, unsigned r)
{
    uint32_t v = x;
    for (unsigned i = 0; i < r; ++i) {
        v = (v >> 1) | ((v & 1u) << 31);
    }
    return v;
}

static uint32_t oracle_popcount(unsigned v)
{
    uint32_t c = 0;
    for (unsigned i = 0; i < 8; ++i) {
        if (v & (1u << i)) {
            ++c;
        }
    }
    return c;
}

static void test_checked(df_test *t)
{
    uint32_t o32 = 0xDEADBEEFu;
    uint64_t o64 = UINT64_C(0xDEADBEEFDEADBEEF);

    DF_CHECK(t, dfi_add_u32(UINT32_MAX, 0u, &o32) && o32 == UINT32_MAX);
    o32 = 0xDEADBEEFu;
    DF_CHECK(t, !dfi_add_u32(UINT32_MAX, 1u, &o32) && o32 == 0xDEADBEEFu);
    DF_CHECK(t, !dfi_add_u32(1u, UINT32_MAX, &o32) && o32 == 0xDEADBEEFu);
    DF_CHECK(t, !dfi_sub_u32(0u, 1u, &o32) && o32 == 0xDEADBEEFu);
    DF_CHECK(t, dfi_sub_u32(5u, 5u, &o32) && o32 == 0u);
    o32 = 0xDEADBEEFu;
    DF_CHECK(t, dfi_mul_u32(65535u, 65537u, &o32) && o32 == UINT32_MAX);
    o32 = 0xDEADBEEFu;
    DF_CHECK(t, !dfi_mul_u32(65536u, 65536u, &o32) && o32 == 0xDEADBEEFu);
    DF_CHECK(t, !dfi_mul_u32(UINT32_MAX, UINT32_MAX, &o32) && o32 == 0xDEADBEEFu);
    DF_CHECK(t, dfi_mul_u32(0u, UINT32_MAX, &o32) && o32 == 0u);

    DF_CHECK(t, dfi_add_u64(UINT64_MAX - 1u, 1u, &o64) && o64 == UINT64_MAX);
    o64 = UINT64_C(0xDEADBEEFDEADBEEF);
    DF_CHECK(t, !dfi_add_u64(UINT64_MAX - 1u, 2u, &o64) && o64 == UINT64_C(0xDEADBEEFDEADBEEF));
    DF_CHECK(t, !dfi_sub_u64(0u, 1u, &o64) && o64 == UINT64_C(0xDEADBEEFDEADBEEF));
    DF_CHECK(t, dfi_sub_u64(UINT64_MAX, UINT64_MAX, &o64) && o64 == 0u);
    o64 = UINT64_C(0xDEADBEEFDEADBEEF);
    DF_CHECK(t, dfi_mul_u64(UINT64_C(0xFFFFFFFF), UINT64_C(0x100000001), &o64) && o64 == UINT64_MAX);
    o64 = UINT64_C(0xDEADBEEFDEADBEEF);
    DF_CHECK(t, !dfi_mul_u64(UINT64_C(0x100000000), UINT64_C(0x100000000), &o64) &&
                    o64 == UINT64_C(0xDEADBEEFDEADBEEF));
    DF_CHECK(t, dfi_mul_u64(0u, UINT64_MAX, &o64) && o64 == 0u);
    o64 = UINT64_C(0xDEADBEEFDEADBEEF);
    DF_CHECK(t, !dfi_mul_u64(UINT64_MAX, 2u, &o64) && o64 == UINT64_C(0xDEADBEEFDEADBEEF));

    uint16_t o16 = 0xBEEFu;
    uint8_t o8 = 0xA5u;
    DF_CHECK(t, dfi_u32_to_u16(65535u, &o16) && o16 == 65535u);
    o16 = 0xBEEFu;
    DF_CHECK(t, !dfi_u32_to_u16(65536u, &o16) && o16 == 0xBEEFu);
    DF_CHECK(t, !dfi_u32_to_u16(UINT32_MAX, &o16) && o16 == 0xBEEFu);
    DF_CHECK(t, dfi_u32_to_u8(255u, &o8) && o8 == 255u);
    o8 = 0xA5u;
    DF_CHECK(t, !dfi_u32_to_u8(256u, &o8) && o8 == 0xA5u);
    DF_CHECK(t, !dfi_u32_to_u8(UINT32_MAX, &o8) && o8 == 0xA5u);
}

static void test_bits(df_test *t)
{
    static const uint32_t samples[] = {0x80000001u, 0x12345678u, 0xFFFFFFFFu, 0u};
    for (size_t s = 0; s < sizeof samples / sizeof samples[0]; ++s) {
        for (unsigned r = 0; r < 32; ++r) {
            DF_CHECK_EQ_U64(t, dfi_rotr32(samples[s], r), oracle_rotr32(samples[s], r));
        }
        /* The count is reduced modulo 32. */
        DF_CHECK_EQ_U64(t, dfi_rotr32(samples[s], 32u), samples[s]);
        DF_CHECK_EQ_U64(t, dfi_rotr32(samples[s], 33u), oracle_rotr32(samples[s], 1));
        DF_CHECK_EQ_U64(t, dfi_rotr32(samples[s], UINT32_MAX), oracle_rotr32(samples[s], 31));
    }
    for (unsigned v = 0; v < 256; ++v) {
        DF_CHECK_EQ_U64(t, dfi_popcount8((uint8_t)v), oracle_popcount(v));
    }
}

static void test_bytes(df_test *t)
{
    uint8_t buf[8];
    static const uint8_t le16[2] = {0x02, 0x01};
    static const uint8_t le32[4] = {0x04, 0x03, 0x02, 0x01};
    static const uint8_t le64[8] = {0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01};
    static const uint8_t be32[4] = {0x01, 0x02, 0x03, 0x04};
    static const uint8_t be64[8] = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
    static const uint8_t ff[8] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

    memset(buf, 0xA5, sizeof buf);
    dfi_store_u16le(buf, 0x0102u);
    DF_CHECK_BYTES(t, buf, le16, 2, "store_u16le");
    DF_CHECK(t, buf[2] == 0xA5);
    dfi_store_u32le(buf, 0x01020304u);
    DF_CHECK_BYTES(t, buf, le32, 4, "store_u32le");
    dfi_store_u64le(buf, UINT64_C(0x0102030405060708));
    DF_CHECK_BYTES(t, buf, le64, 8, "store_u64le");
    dfi_store_u32be(buf, 0x01020304u);
    DF_CHECK_BYTES(t, buf, be32, 4, "store_u32be");
    dfi_store_u64be(buf, UINT64_C(0x0102030405060708));
    DF_CHECK_BYTES(t, buf, be64, 8, "store_u64be");

    DF_CHECK_EQ_U64(t, dfi_load_u16le(le16), 0x0102u);
    DF_CHECK_EQ_U64(t, dfi_load_u32le(le32), 0x01020304u);
    DF_CHECK_EQ_U64(t, dfi_load_u64le(le64), UINT64_C(0x0102030405060708));
    DF_CHECK_EQ_U64(t, dfi_load_u32be(be32), 0x01020304u);
    DF_CHECK_EQ_U64(t, dfi_load_u64be(be64), UINT64_C(0x0102030405060708));

    /* All-0xFF loads: the high byte would overflow a promoted int. */
    DF_CHECK_EQ_U64(t, dfi_load_u16le(ff), 0xFFFFu);
    DF_CHECK_EQ_U64(t, dfi_load_u32le(ff), 0xFFFFFFFFu);
    DF_CHECK_EQ_U64(t, dfi_load_u64le(ff), UINT64_MAX);
    DF_CHECK_EQ_U64(t, dfi_load_u32be(ff), 0xFFFFFFFFu);
    DF_CHECK_EQ_U64(t, dfi_load_u64be(ff), UINT64_MAX);
    /* 0x80 in the top byte is the smallest value that overflows int. */
    static const uint8_t top80[8] = {0, 0, 0, 0x80, 0, 0, 0, 0x80};
    DF_CHECK_EQ_U64(t, dfi_load_u32le(top80), 0x80000000u);
    DF_CHECK_EQ_U64(t, dfi_load_u64le(top80), UINT64_C(0x8000000080000000));

    static const uint64_t rt[] = {UINT64_C(0xFFFEFDFC80818283), 0u, UINT64_MAX};
    for (size_t i = 0; i < sizeof rt / sizeof rt[0]; ++i) {
        dfi_store_u64le(buf, rt[i]);
        DF_CHECK_EQ_U64(t, dfi_load_u64le(buf), rt[i]);
        dfi_store_u64be(buf, rt[i]);
        DF_CHECK_EQ_U64(t, dfi_load_u64be(buf), rt[i]);
        const uint32_t v32 = (uint32_t)(rt[i] >> 16);
        dfi_store_u32le(buf, v32);
        DF_CHECK_EQ_U64(t, dfi_load_u32le(buf), v32);
        dfi_store_u32be(buf, v32);
        DF_CHECK_EQ_U64(t, dfi_load_u32be(buf), v32);
        const uint16_t v16 = (uint16_t)(rt[i] >> 40);
        dfi_store_u16le(buf, v16);
        DF_CHECK_EQ_U64(t, dfi_load_u16le(buf), v16);
    }

    static const uint8_t x[4] = {1, 2, 3, 4};
    static const uint8_t y[4] = {1, 2, 3, 5};
    DF_CHECK(t, dfi_bytes_equal(x, x, 4));
    DF_CHECK(t, !dfi_bytes_equal(x, y, 4));
    DF_CHECK(t, dfi_bytes_equal(x, y, 3));
    DF_CHECK(t, dfi_bytes_equal(x, y, 0));
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.unit.arith");
    test_checked(&t);
    test_bits(&t);
    test_bytes(&t);
    return df_test_end(&t);
}
