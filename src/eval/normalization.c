#include "eval/normalization.h"
#include <limits.h>
#include <stdbool.h>
#include <string.h>

typedef struct wide { uint64_t hi; uint64_t lo; } wide;
static int32_t compare(wide a, wide b)
{
    if (a.hi != b.hi) return a.hi < b.hi ? -1 : 1;
    return a.lo == b.lo ? 0 : a.lo < b.lo ? -1 : 1;
}
static wide subtract(wide a, wide b)
{
    wide r = {a.hi - b.hi - (a.lo < b.lo ? 1u : 0u), a.lo - b.lo}; return r;
}
static duoforge_status add(wide a, wide b, wide *out)
{
    uint64_t lo = a.lo + b.lo, carry = lo < a.lo ? 1u : 0u;
    if (a.hi > UINT64_MAX - b.hi || a.hi + b.hi > UINT64_MAX - carry)
        return DUOFORGE_E_EXHAUSTED;
    *out = (wide){a.hi + b.hi + carry, lo}; return DUOFORGE_OK;
}
static wide multiply(uint64_t a, uint64_t b)
{
    uint64_t al = (uint32_t)a, ah = a >> 32u, bl = (uint32_t)b, bh = b >> 32u;
    uint64_t low = al * bl, middle = ah * bl + (low >> 32u);
    uint64_t bottom = (middle & UINT32_MAX) + al * bh;
    return (wide){ah * bh + (middle >> 32u) + (bottom >> 32u),
                  (bottom << 32u) | (low & UINT32_MAX)};
}
static duoforge_status shift_left(wide a, uint32_t shift, wide *out)
{
    if (shift > 63u) return DUOFORGE_E_INVALID_ARGUMENT;
    if (!shift) { *out = a; return DUOFORGE_OK; }
    if (a.hi >> (64u - shift)) return DUOFORGE_E_EXHAUSTED;
    *out = (wide){(a.hi << shift) | (a.lo >> (64u - shift)), a.lo << shift};
    return DUOFORGE_OK;
}
/* Restoring division keeps remainder < divisor. The extra carry represents its
   possible 65th bit before subtraction; all wrap is defined modulo limb arithmetic. */
static wide divide(wide value, uint64_t divisor, uint64_t *remainder)
{
    wide q = {0, 0}; uint64_t rem = 0;
    for (uint32_t k = 128u; k > 0u; --k) {
        uint32_t bit = k - 1u;
        uint64_t incoming = bit >= 64u ? (value.hi >> (bit - 64u)) & 1u : (value.lo >> bit) & 1u;
        bool carry = (rem >> 63u) != 0;
        rem = (rem << 1u) | incoming;
        if (carry || rem >= divisor) {
            rem -= divisor;
            if (bit >= 64u) q.hi |= UINT64_C(1) << (bit - 64u);
            else q.lo |= UINT64_C(1) << bit;
        }
    }
    *remainder = rem; return q;
}
static duoforge_status rounded_divide(wide value, uint64_t divisor, wide *out)
{
    if (!divisor) return DUOFORGE_E_INVALID_ARGUMENT;
    uint64_t rem; wide q = divide(value, divisor, &rem);
    if (rem > divisor - rem || (rem == divisor - rem && (q.lo & 1u)))
        return add(q, (wide){0, 1}, out);
    *out = q; return DUOFORGE_OK;
}
static duoforge_status signed_value(wide magnitude, bool negative, int64_t *out)
{
    uint64_t limit = (uint64_t)INT64_MAX + (negative ? 1u : 0u);
    if (magnitude.hi || magnitude.lo > limit) return DUOFORGE_E_EXHAUSTED;
    *out = negative ? magnitude.lo == (UINT64_C(1) << 63u) ? INT64_MIN : -(int64_t)magnitude.lo
                    : (int64_t)magnitude.lo;
    return DUOFORGE_OK;
}
static bool valid_scale(dfi_eval_scale scale)
{
    return scale.multiplier && scale.shift <= 63u;
}
static duoforge_status scaled_product(int64_t a, int64_t b, dfi_eval_scale scale, int64_t *out)
{
    wide product = multiply(dfi_eval_magnitude(a), dfi_eval_magnitude(b));
    /* Call sites multiply at most int64 by int32; scaling adds at most 32 bits.
       Use checked limb multiplication rather than relying on those bounds. */
    wide low = multiply(product.lo, scale.multiplier), high = multiply(product.hi, scale.multiplier);
    if (high.hi || low.hi > UINT64_MAX - high.lo) return DUOFORGE_E_EXHAUSTED;
    product = (wide){low.hi + high.lo, low.lo};
    wide q; duoforge_status st = rounded_divide(product, UINT64_C(1) << scale.shift, &q);
    return st == DUOFORGE_OK ? signed_value(q, (a < 0) != (b < 0), out) : st;
}
duoforge_status dfi_eval_sqrt128(uint64_t hi, uint64_t lo, uint64_t *out)
{
    if (!out) return DUOFORGE_E_NULL_ARGUMENT;
    wide value = {hi, lo}; uint64_t root = 0;
    for (uint32_t k = 64u; k > 0u; --k) {
        uint64_t candidate = root | (UINT64_C(1) << (k - 1u));
        if (compare(multiply(candidate, candidate), value) <= 0) root = candidate;
    }
    wide distance = subtract(value, multiply(root, root));
    wide gap = {root >> 63u, (root << 1u) | 1u}; /* (root + 1)^2 - root^2 */
    int32_t cmp = compare(distance, subtract(gap, distance));
    if (cmp > 0 || (cmp == 0 && (root & 1u))) {
        if (root == UINT64_MAX) return DUOFORGE_E_EXHAUSTED;
        ++root;
    }
    *out = root; return DUOFORGE_OK;
}
static duoforge_status normalize_parameters(dfi_eval_normalization p)
{
    return !p.epsilon || p.sqrt_shift > 31u || p.numerator_shift > 63u ||
           !valid_scale(p.gamma_scale) || !valid_scale(p.output_scale)
        ? DUOFORGE_E_INVALID_ARGUMENT : DUOFORGE_OK;
}
static duoforge_status vector_arguments(const int32_t *a, const int32_t *b,
    uint32_t count, int32_t *scratch, uint32_t capacity, const void *out)
{
    if (!a || !b || !scratch || !out) return DUOFORGE_E_NULL_ARGUMENT;
    if (!count) return DUOFORGE_E_INVALID_ARGUMENT;
    if (count > capacity || (uint64_t)count * sizeof(int32_t) > SIZE_MAX)
        return DUOFORGE_E_CAPACITY;
    /* Scratch is disjoint from inputs/outputs. Output32 may overlap int32
       inputs because publication is last; output16 is disjoint from int32
       input objects. Caller proves buffer extents; no address-range inference. */
    if ((const void *)scratch == (const void *)a || (const void *)scratch == (const void *)b ||
        (const void *)scratch == out) return DUOFORGE_E_INVALID_ARGUMENT;
    return DUOFORGE_OK;
}
duoforge_status dfi_eval_layernorm_moments(const int32_t *input, uint32_t count,
    dfi_eval_normalization p, dfi_eval_normalization_stats *out)
{
    if (!input || !out) return DUOFORGE_E_NULL_ARGUMENT;
    if (!count) return DUOFORGE_E_INVALID_ARGUMENT;
    if ((uint64_t)count * sizeof(int32_t) > SIZE_MAX) return DUOFORGE_E_CAPACITY;
    duoforge_status st = normalize_parameters(p); if (st != DUOFORGE_OK) return st;
    int64_t sum = 0, mean;
    for (uint32_t i = 0; i < count; ++i) {
        st = dfi_eval_add(sum, input[i], &sum); if (st != DUOFORGE_OK) return st;
    }
    st = dfi_eval_round_div(sum, count, &mean); if (st != DUOFORGE_OK) return st;
    wide squares = {0, 0};
    for (uint32_t i = 0; i < count; ++i) {
        uint64_t d = dfi_eval_magnitude((int64_t)input[i] - mean);
        st = add(squares, multiply(d, d), &squares); if (st != DUOFORGE_OK) return st;
    }
    wide variance, radicand;
    st = rounded_divide(squares, count, &variance); if (st != DUOFORGE_OK) return st;
    st = add(variance, (wide){0, p.epsilon}, &radicand); if (st != DUOFORGE_OK) return st;
    st = shift_left(radicand, p.sqrt_shift * 2u, &radicand); if (st != DUOFORGE_OK) return st;
    uint64_t denominator;
    st = dfi_eval_sqrt128(radicand.hi, radicand.lo, &denominator); if (st != DUOFORGE_OK) return st;
    if (!denominator) return DUOFORGE_E_INVARIANT;
    *out = (dfi_eval_normalization_stats){mean, variance.hi, variance.lo, denominator};
    return DUOFORGE_OK;
}
duoforge_status dfi_eval_layernorm32(const int32_t *input, const int32_t *gamma,
    const int32_t *beta, uint32_t count, dfi_eval_normalization p,
    int32_t *scratch, uint32_t capacity, int32_t *out)
{
    duoforge_status st = vector_arguments(input, gamma, count, scratch, capacity, out);
    if (st != DUOFORGE_OK) return st;
    if (!beta) return DUOFORGE_E_NULL_ARGUMENT;
    if ((const void *)scratch == (const void *)beta) return DUOFORGE_E_INVALID_ARGUMENT;
    st = normalize_parameters(p); if (st != DUOFORGE_OK) return st;
    dfi_eval_normalization_stats stats;
    st = dfi_eval_layernorm_moments(input, count, p, &stats); if (st != DUOFORGE_OK) return st;
    int64_t mean = stats.mean; uint64_t denominator = stats.denominator;
    for (uint32_t i = 0; i < count; ++i) {
        int64_t delta = (int64_t)input[i] - mean, normalized, affine, value;
        wide numerator = {0, dfi_eval_magnitude(delta)}, quotient;
        st = shift_left(numerator, p.numerator_shift, &numerator); if (st != DUOFORGE_OK) return st;
        st = rounded_divide(numerator, denominator, &quotient); if (st != DUOFORGE_OK) return st;
        st = signed_value(quotient, delta < 0, &normalized); if (st != DUOFORGE_OK) return st;
        st = scaled_product(normalized, gamma[i], p.gamma_scale, &affine); if (st != DUOFORGE_OK) return st;
        st = dfi_eval_add(affine, beta[i], &value); if (st != DUOFORGE_OK) return st;
        st = scaled_product(value, 1, p.output_scale, &value); if (st != DUOFORGE_OK) return st;
        if (value < INT32_MIN || value > INT32_MAX) return DUOFORGE_E_EXHAUSTED;
        scratch[i] = (int32_t)value;
    }
    memcpy(out, scratch, (size_t)count * sizeof(int32_t)); return DUOFORGE_OK;
}
static duoforge_status residual(const int32_t *left, const int32_t *right,
    uint32_t count, dfi_eval_scale ls, dfi_eval_scale rs, dfi_eval_scale os,
    int32_t *scratch, uint32_t capacity, void *out, bool saturated)
{
    duoforge_status st = vector_arguments(left, right, count, scratch, capacity, out);
    if (st != DUOFORGE_OK) return st;
    if (!valid_scale(ls) || !valid_scale(rs) || !valid_scale(os)) return DUOFORGE_E_INVALID_ARGUMENT;
    for (uint32_t i = 0; i < count; ++i) {
        int64_t a, b, value;
        st = scaled_product(left[i], 1, ls, &a); if (st != DUOFORGE_OK) return st;
        st = scaled_product(right[i], 1, rs, &b); if (st != DUOFORGE_OK) return st;
        st = dfi_eval_add(a, b, &value); if (st != DUOFORGE_OK) return st;
        st = scaled_product(value, 1, os, &value); if (st != DUOFORGE_OK) return st;
        if (saturated) scratch[i] = value > INT16_MAX ? INT16_MAX : value < INT16_MIN ? INT16_MIN : (int32_t)value;
        else {
            if (value < INT32_MIN || value > INT32_MAX) return DUOFORGE_E_EXHAUSTED;
            scratch[i] = (int32_t)value;
        }
    }
    if (saturated) for (uint32_t i = 0; i < count; ++i) ((int16_t *)out)[i] = (int16_t)scratch[i];
    else memcpy(out, scratch, (size_t)count * sizeof(int32_t));
    return DUOFORGE_OK;
}
duoforge_status dfi_eval_residual32(const int32_t *left, const int32_t *right,
    uint32_t count, dfi_eval_scale ls, dfi_eval_scale rs, dfi_eval_scale os,
    int32_t *scratch, uint32_t capacity, int32_t *out)
{
    return residual(left, right, count, ls, rs, os, scratch, capacity, out, false);
}
duoforge_status dfi_eval_residual16(const int32_t *left, const int32_t *right,
    uint32_t count, dfi_eval_scale ls, dfi_eval_scale rs, dfi_eval_scale os,
    int32_t *scratch, uint32_t capacity, int16_t *out)
{
    return residual(left, right, count, ls, rs, os, scratch, capacity, out, true);
}
