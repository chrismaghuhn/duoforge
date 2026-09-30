#ifndef DUOFORGE_CORE_ARITH_H
#define DUOFORGE_CORE_ARITH_H
/*
 * Checked integer helpers (internal). Fallible helpers return true on
 * success; on failure *out is left untouched. No compiler builtins.
 * Helpers with Pokemon semantics (rounding modes, 4096-based modifiers)
 * arrive with their first consumer in M3 (docs/decisions/0002).
 */
#include <stdbool.h>
#include <stdint.h>

#include "core/platform.h"

static inline bool dfi_add_u32(uint32_t a, uint32_t b, uint32_t *out)
{
    if (a > UINT32_MAX - b) {
        return false;
    }
    *out = a + b;
    return true;
}

static inline bool dfi_sub_u32(uint32_t a, uint32_t b, uint32_t *out)
{
    if (b > a) {
        return false;
    }
    *out = a - b;
    return true;
}

static inline bool dfi_mul_u32(uint32_t a, uint32_t b, uint32_t *out)
{
    const uint64_t product = (uint64_t)a * b;
    if (product > UINT32_MAX) {
        return false;
    }
    *out = (uint32_t)product;
    return true;
}

static inline bool dfi_add_u64(uint64_t a, uint64_t b, uint64_t *out)
{
    if (a > UINT64_MAX - b) {
        return false;
    }
    *out = a + b;
    return true;
}

static inline bool dfi_sub_u64(uint64_t a, uint64_t b, uint64_t *out)
{
    if (b > a) {
        return false;
    }
    *out = a - b;
    return true;
}

static inline bool dfi_mul_u64(uint64_t a, uint64_t b, uint64_t *out)
{
    if (a != 0u && b > UINT64_MAX / a) {
        return false;
    }
    *out = a * b;
    return true;
}

static inline bool dfi_u32_to_u16(uint32_t v, uint16_t *out)
{
    if (v > UINT16_MAX) {
        return false;
    }
    *out = (uint16_t)v;
    return true;
}

static inline bool dfi_u32_to_u8(uint32_t v, uint8_t *out)
{
    if (v > UINT8_MAX) {
        return false;
    }
    *out = (uint8_t)v;
    return true;
}

/* Rotate right; the count is reduced modulo 32, so every count is defined. */
static inline uint32_t dfi_rotr32(uint32_t x, uint32_t r)
{
    const uint32_t k = r & 31u;
    return (x >> k) | (x << ((32u - k) & 31u));
}

static inline uint32_t dfi_popcount8(uint8_t v)
{
    const uint32_t w = v;
    uint32_t count = 0u;
    for (uint32_t i = 0u; i < 8u; ++i) {
        count += (w >> i) & 1u;
    }
    return count;
}

#endif
