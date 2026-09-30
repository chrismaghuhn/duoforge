#ifndef DUOFORGE_TESTS_SUPPORT_CHECK_H
#define DUOFORGE_TESTS_SUPPORT_CHECK_H
/*
 * Minimal test support: an explicit test context (no globals), expression
 * check macros that work in Release (no assert/NDEBUG), and helpers.
 *
 * Rules for DuoForge tests:
 *  S1. Sentinels: byte buffers start at 0xA5, integer outputs at a distinct
 *      pattern, pointer outputs at the address of a local max_align_t object
 *      (never dereferenced).
 *  S2. Battles are compared only through encodings or duoforge_battle_equal.
 *  S3. bool outputs never hold byte-pattern sentinels (loading a non-0/1
 *      byte as bool is UB). Every error case with a bool out-parameter runs
 *      twice, preset to false and to true, and must leave it unchanged.
 *  S4. Decode inputs are exact-size heap copies (df_heap_copy), so a read
 *      past the size is an ASan heap-buffer-overflow in the sanitizer job.
 *  Expectations are never "ran the implementation once".
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct df_test {
    const char *name;
    unsigned long checks;
    unsigned long failures;
} df_test;

void df_test_begin(df_test *t, const char *name);
/* Prints "<name>: <checks> checks, <failures> failures" and returns the exit code. */
int df_test_end(df_test *t);

bool df_check_impl(df_test *t, bool ok, const char *expr, const char *file, int line);
bool df_check_u64_impl(df_test *t, uint64_t actual, uint64_t expected, const char *expr,
                       const char *file, int line);
bool df_check_bytes_impl(df_test *t, const uint8_t *actual, const uint8_t *expected, size_t n,
                         const char *what, const char *file, int line);

#define DF_CHECK(t, cond) df_check_impl((t), (cond) ? true : false, #cond, __FILE__, __LINE__)
#define DF_CHECK_EQ_U64(t, actual, expected)                                                     \
    df_check_u64_impl((t), (uint64_t)(actual), (uint64_t)(expected), #actual " == " #expected, \
                      __FILE__, __LINE__)
#define DF_CHECK_BYTES(t, actual, expected, n, what) \
    df_check_bytes_impl((t), (actual), (expected), (n), (what), __FILE__, __LINE__)

/* Parses 2*n lowercase/uppercase hex digits into out; returns false on bad input. */
bool df_hex_to_bytes(const char *hex, uint8_t *out, size_t n);

/* Exact-size heap copy (rule S4). Allocates 1 byte for size 0. Free with df_free. */
uint8_t *df_heap_copy(const uint8_t *bytes, size_t size);
void df_free(void *p);

#endif
