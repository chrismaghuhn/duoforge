#include "support/check.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void df_test_begin(df_test *t, const char *name)
{
    t->name = name;
    t->checks = 0;
    t->failures = 0;
}

int df_test_end(df_test *t)
{
    printf("%s: %lu checks, %lu failures\n", t->name, t->checks, t->failures);
    return t->failures == 0 ? 0 : 1;
}

bool df_check_impl(df_test *t, bool ok, const char *expr, const char *file, int line)
{
    t->checks++;
    if (!ok) {
        t->failures++;
        fprintf(stderr, "%s:%d: CHECK FAILED: %s\n", file, line, expr);
    }
    return ok;
}

bool df_check_u64_impl(df_test *t, uint64_t actual, uint64_t expected, const char *expr,
                       const char *file, int line)
{
    t->checks++;
    if (actual != expected) {
        t->failures++;
        fprintf(stderr, "%s:%d: CHECK FAILED: %s (actual 0x%llx, expected 0x%llx)\n", file, line,
                expr, (unsigned long long)actual, (unsigned long long)expected);
        return false;
    }
    return true;
}

bool df_check_bytes_impl(df_test *t, const uint8_t *actual, const uint8_t *expected, size_t n,
                         const char *what, const char *file, int line)
{
    t->checks++;
    for (size_t i = 0; i < n; ++i) {
        if (actual[i] != expected[i]) {
            t->failures++;
            fprintf(stderr, "%s:%d: CHECK FAILED: %s differs at byte %zu (actual 0x%02x, expected 0x%02x)\n",
                    file, line, what, i, (unsigned)actual[i], (unsigned)expected[i]);
            return false;
        }
    }
    return true;
}

static int df_hex_digit(char c)
{
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    if (c >= 'a' && c <= 'f') {
        return c - 'a' + 10;
    }
    if (c >= 'A' && c <= 'F') {
        return c - 'A' + 10;
    }
    return -1;
}

bool df_hex_to_bytes(const char *hex, uint8_t *out, size_t n)
{
    if (strlen(hex) != 2 * n) {
        return false;
    }
    for (size_t i = 0; i < n; ++i) {
        const int hi = df_hex_digit(hex[2 * i]);
        const int lo = df_hex_digit(hex[2 * i + 1]);
        if (hi < 0 || lo < 0) {
            return false;
        }
        out[i] = (uint8_t)(hi * 16 + lo);
    }
    return true;
}

uint8_t *df_heap_copy(const uint8_t *bytes, size_t size)
{
    uint8_t *p = malloc(size == 0 ? 1 : size);
    if (p == NULL) {
        fprintf(stderr, "df_heap_copy: out of memory\n");
        exit(2);
    }
    if (size > 0) {
        memcpy(p, bytes, size);
    }
    return p;
}

void df_free(void *p)
{
    free(p);
}
