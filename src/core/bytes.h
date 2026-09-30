#ifndef DUOFORGE_CORE_BYTES_H
#define DUOFORGE_CORE_BYTES_H
/*
 * Explicit little- and big-endian byte access (internal). Values are widened
 * before shifting; no type punning and no dependence on host byte order.
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "core/platform.h"

static inline uint16_t dfi_load_u16le(const uint8_t *p)
{
    const uint32_t v = (uint32_t)p[0] | ((uint32_t)p[1] << 8u);
    return (uint16_t)v;
}

static inline uint32_t dfi_load_u32le(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8u) | ((uint32_t)p[2] << 16u) |
           ((uint32_t)p[3] << 24u);
}

static inline uint64_t dfi_load_u64le(const uint8_t *p)
{
    uint64_t v = 0u;
    for (uint32_t i = 0u; i < 8u; ++i) {
        v |= (uint64_t)p[i] << (8u * i);
    }
    return v;
}

static inline uint32_t dfi_load_u32be(const uint8_t *p)
{
    return ((uint32_t)p[0] << 24u) | ((uint32_t)p[1] << 16u) | ((uint32_t)p[2] << 8u) |
           (uint32_t)p[3];
}

static inline uint64_t dfi_load_u64be(const uint8_t *p)
{
    uint64_t v = 0u;
    for (uint32_t i = 0u; i < 8u; ++i) {
        v = (v << 8u) | (uint64_t)p[i];
    }
    return v;
}

static inline void dfi_store_u16le(uint8_t *p, uint16_t value)
{
    const uint32_t w = value;
    p[0] = (uint8_t)(w & 0xFFu);        /* wide-operands-reviewed */
    p[1] = (uint8_t)((w >> 8u) & 0xFFu); /* wide-operands-reviewed */
}

static inline void dfi_store_u32le(uint8_t *p, uint32_t value)
{
    for (uint32_t i = 0u; i < 4u; ++i) {
        p[i] = (uint8_t)((value >> (8u * i)) & 0xFFu); /* wide-operands-reviewed */
    }
}

static inline void dfi_store_u64le(uint8_t *p, uint64_t value)
{
    for (uint32_t i = 0u; i < 8u; ++i) {
        p[i] = (uint8_t)((value >> (8u * i)) & 0xFFu); /* wide-operands-reviewed */
    }
}

static inline void dfi_store_u32be(uint8_t *p, uint32_t value)
{
    for (uint32_t i = 0u; i < 4u; ++i) {
        p[i] = (uint8_t)((value >> (24u - 8u * i)) & 0xFFu); /* wide-operands-reviewed */
    }
}

static inline void dfi_store_u64be(uint8_t *p, uint64_t value)
{
    for (uint32_t i = 0u; i < 8u; ++i) {
        p[i] = (uint8_t)((value >> (56u - 8u * i)) & 0xFFu); /* wide-operands-reviewed */
    }
}

/* Byte-wise equality. src/ does not use memcmp; the lint enforces this. */
static inline bool dfi_bytes_equal(const uint8_t *a, const uint8_t *b, size_t n)
{
    for (size_t i = 0u; i < n; ++i) {
        if (a[i] != b[i]) {
            return false;
        }
    }
    return true;
}

#endif
