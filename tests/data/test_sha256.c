/*
 * T3 duoforge.unit.sha256 (white-box). Expectations: NIST FIPS 180-2
 * examples and coreutils sha256sum 9.4 (recorded in docs/decisions/0002).
 */
#include <stdlib.h>
#include <string.h>

#include "core/sha256.h"
#include "support/check.h"

static void check_digest(df_test *t, const uint8_t *data, size_t size, const char *hex,
                         const char *label)
{
    uint8_t expected[32];
    uint8_t out[32];
    memset(out, 0xA5, sizeof out);
    if (!DF_CHECK(t, df_hex_to_bytes(hex, expected, sizeof expected))) {
        return;
    }
    DF_CHECK(t, dfi_sha256(data, size, out));
    DF_CHECK_BYTES(t, out, expected, sizeof out, label);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.unit.sha256");

    static const uint8_t one[1] = {0};
    check_digest(&t, one, 0, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "empty");
    check_digest(&t, (const uint8_t *)"abc", 3,
                 "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", "abc");

    /* 448-bit message: "abcdbcde...nopq" (letters i..i+3 for i = a..n). */
    uint8_t m448[56];
    for (int i = 0; i < 14; ++i) {
        for (int j = 0; j < 4; ++j) {
            m448[4 * i + j] = (uint8_t)('a' + i + j);
        }
    }
    check_digest(&t, m448, sizeof m448,
                 "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1", "448-bit");

    /* 896-bit message: "abcdefgh bcdefghi ... nopqrstu" (8 letters from i = a..n). */
    uint8_t m896[112];
    for (int i = 0; i < 14; ++i) {
        for (int j = 0; j < 8; ++j) {
            m896[8 * i + j] = (uint8_t)('a' + i + j);
        }
    }
    check_digest(&t, m896, sizeof m896,
                 "cf5b16a778af8380036ce59e7b0492370b249b11e8f07a51afac45037afee9d1", "896-bit");

    uint8_t *million = malloc(1000000);
    if (DF_CHECK(&t, million != NULL)) {
        memset(million, 'a', 1000000);
        check_digest(&t, million, 1000000,
                     "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0", "1e6 x a");
        free(million);
    }

    /* Padding boundaries around 55/56 and 64-byte blocks. */
    static const struct {
        size_t n;
        const char *hex;
    } lengths[] = {
        {1, "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb"},
        {55, "9f4390f8d30c2dd92ec9f095b65e2b9ae9b0a925a5258e241c9f1e910f734318"},
        {56, "b35439a4ac6f0948b6d6f9e3c6af0f5f590ce20f1bde7090ef7970686ec6738a"},
        {57, "f13b2d724659eb3bf47f2dd6af1accc87b81f09f59f2b75e5c0bed6589dfe8c6"},
        {63, "7d3e74a05d7db15bce4ad9ec0658ea98e3f06eeecf16b4c6fff2da457ddc2f34"},
        {64, "ffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb"},
        {65, "635361c48bb9eab14198e76ea8ab7f1a41685d6ad62aa9146d301d4f17eb0ae0"},
        {119, "31eba51c313a5c08226adf18d4a359cfdfd8d2e816b13f4af952f7ea6584dcfb"},
        {120, "2f3d335432c70b580af0e8e1b3674a7c020d683aa5f73aaaedfdc55af904c21c"},
        {127, "c57e9278af78fa3cab38667bef4ce29d783787a2f731d4e12200270f0c32320a"},
        {128, "6836cf13bac400e9105071cd6af47084dfacad4e5e302c94bfed24e013afb73e"},
    };
    uint8_t as[128];
    memset(as, 'a', sizeof as);
    for (size_t i = 0; i < sizeof lengths / sizeof lengths[0]; ++i) {
        /* Exact-size heap copy so over-reads are caught by ASan. */
        uint8_t *copy = df_heap_copy(as, lengths[i].n);
        check_digest(&t, copy, lengths[i].n, lengths[i].hex, "a x n");
        df_free(copy);
    }

#if SIZE_MAX > UINT32_MAX
    /* An unrepresentable length is rejected without reading the data. */
    {
        uint8_t out[32];
        uint8_t before[32];
        memset(out, 0xA5, sizeof out);
        memcpy(before, out, sizeof out);
        DF_CHECK(&t, !dfi_sha256(one, (size_t)UINT64_C(0x2000000000000000), out));
        DF_CHECK_BYTES(&t, out, before, sizeof out, "untouched on reject");
    }
#endif

    return df_test_end(&t);
}
