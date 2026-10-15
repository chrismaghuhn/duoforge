#include "eval/arithmetic.h"
#include <limits.h>
#include <stdbool.h>

/* wide-operands-reviewed: v+1 and its negation are representable before conversion. */
uint64_t dfi_eval_magnitude(int64_t v) { return v < 0 ? (uint64_t)(-(v + 1)) + 1u : (uint64_t)v; /* wide-operands-reviewed */ }
static duoforge_status signed_value(uint64_t mag, bool negative, int64_t *out)
{
    const uint64_t lim = (uint64_t)INT64_MAX + (negative ? 1u : 0u);
    if (mag > lim) return DUOFORGE_E_EXHAUSTED;
    *out = negative ? (mag == (UINT64_C(1) << 63u) ? INT64_MIN : -(int64_t)mag) : (int64_t)mag;
    return DUOFORGE_OK;
}
duoforge_status dfi_eval_add(int64_t a, int64_t b, int64_t *out)
{
    if (!out) return DUOFORGE_E_NULL_ARGUMENT;
    if ((b > 0 && a > INT64_MAX - b) || (b < 0 && a < INT64_MIN - b)) return DUOFORGE_E_EXHAUSTED;
    *out = a + b; return DUOFORGE_OK;
}
duoforge_status dfi_eval_mul(int64_t a, int64_t b, int64_t *out)
{
    if (!out) return DUOFORGE_E_NULL_ARGUMENT;
    uint64_t aa = dfi_eval_magnitude(a), bb = dfi_eval_magnitude(b);
    if (bb && aa > UINT64_MAX / bb) return DUOFORGE_E_EXHAUSTED;
    return signed_value(aa * bb, (a < 0) != (b < 0), out);
}
static uint64_t rounded(uint64_t mag, uint64_t div)
{
    uint64_t q = mag / div, rem = mag % div;
    if (rem > div - rem || (rem == div - rem && (q & 1u))) ++q;
    return q;
}
duoforge_status dfi_eval_round_div(int64_t v, uint64_t div, int64_t *out)
{
    if (!out) return DUOFORGE_E_NULL_ARGUMENT;
    if (!div) return DUOFORGE_E_INVALID_ARGUMENT;
    return signed_value(rounded(dfi_eval_magnitude(v), div), v < 0, out);
}
duoforge_status dfi_eval_requant(int64_t v, dfi_eval_scale scale, int64_t *out)
{
    if (!out) return DUOFORGE_E_NULL_ARGUMENT;
    if (!scale.multiplier || scale.shift > 63u) return DUOFORGE_E_INVALID_ARGUMENT;
    uint64_t mag = dfi_eval_magnitude(v);
    if (mag > UINT64_MAX / scale.multiplier) return DUOFORGE_E_EXHAUSTED;
    return signed_value(rounded(mag * scale.multiplier, UINT64_C(1) << scale.shift), v < 0, out);
}
duoforge_status dfi_eval_requant16(int64_t v, dfi_eval_scale scale, int16_t *out)
{
    if (!out) return DUOFORGE_E_NULL_ARGUMENT;
    int64_t q; duoforge_status st = dfi_eval_requant(v, scale, &q);
    if (st != DUOFORGE_OK) return st;
    *out = q > INT16_MAX ? INT16_MAX : q < INT16_MIN ? INT16_MIN : (int16_t)q;
    return DUOFORGE_OK;
}
duoforge_status dfi_eval_requant32(int64_t v, dfi_eval_scale scale, int32_t *out)
{
    if (!out) return DUOFORGE_E_NULL_ARGUMENT;
    int64_t q; duoforge_status st = dfi_eval_requant(v, scale, &q);
    if (st != DUOFORGE_OK) return st;
    if (q > INT32_MAX || q < INT32_MIN) return DUOFORGE_E_EXHAUSTED;
    *out = (int32_t)q; return DUOFORGE_OK;
}
duoforge_status dfi_eval_dot_bound(uint32_t count, uint32_t input_abs, uint32_t weight_abs,
                                  uint64_t bias_abs, dfi_eval_scale scale, uint64_t *out)
{
    if (!out) return DUOFORGE_E_NULL_ARGUMENT;
    if (!scale.multiplier || scale.shift > 63u || input_abs > 32768u || weight_abs > 128u)
        return DUOFORGE_E_INVALID_ARGUMENT;
    uint64_t one = (uint64_t)input_abs * weight_abs;
    /* Validated factors give one <= 2^22 and count < 2^32, so the
       product fits in 54 bits, even for a zero factor. */
    const uint64_t terms = count * one;
    if (bias_abs > (uint64_t)INT64_MAX || terms > (uint64_t)INT64_MAX - bias_abs)
        return DUOFORGE_E_EXHAUSTED;
    uint64_t bound = bias_abs + terms;
    /* Exact upper word of bound * multiplier. bound <= INT64_MAX and a
       uint32 multiplier keep both intermediates within uint64. This tests
       the same limit without a division MSVC IPO may diagnose on dead paths. */
    const uint64_t scaled_low = (bound & UINT64_C(0xffffffff)) * scale.multiplier;
    const uint64_t scaled_high = (bound >> 32u) * scale.multiplier + (scaled_low >> 32u);
    if (scaled_high > UINT64_C(0x7fffffff)) return DUOFORGE_E_EXHAUSTED;
    *out = bound; return DUOFORGE_OK;
}
/* Binary32 significand has at most 24 bits; a uint32 factor gives <= 56 bits.
   Nonfinite values always refuse, including masked/padded input cells. */
static duoforge_status bits_magnitude(uint32_t bits, uint32_t factor, uint32_t shift, uint64_t *out)
{
    uint32_t exponent = (bits >> 23u) & 255u;
    if (exponent == 255u || !factor || shift > 63u) return DUOFORGE_E_INVALID_ARGUMENT;
    uint64_t sig = bits & UINT32_C(0x7fffff);
    int32_t power = exponent ? (int32_t)exponent - 150 : -149;
    if (exponent) sig |= UINT64_C(1) << 23u;
    uint64_t mag = sig * factor;
    power -= (int32_t)shift;
    if (power >= 0) {
        if (power >= 64 || mag > (UINT64_MAX >> (uint32_t)power)) {
            if (!mag) { *out = 0; return DUOFORGE_OK; }
            return DUOFORGE_E_EXHAUSTED;
        }
        *out = mag << (uint32_t)power;
    } else {
        uint32_t right = (uint32_t)(-power); /* wide-operands-reviewed: power is -212..-1. */
        *out = right >= 64u ? 0u : rounded(mag, UINT64_C(1) << right);
    }
    return DUOFORGE_OK;
}
duoforge_status dfi_eval_binary32(uint32_t bits, dfi_eval_scale scale, int16_t *out)
{
    if (!out) return DUOFORGE_E_NULL_ARGUMENT;
    uint64_t mag; duoforge_status st = bits_magnitude(bits, scale.multiplier, scale.shift, &mag);
    if (st == DUOFORGE_E_EXHAUSTED) {
        *out = bits >> 31u ? INT16_MIN : INT16_MAX; return DUOFORGE_OK;
    }
    if (st != DUOFORGE_OK) return st;
    if (bits >> 31u) *out = mag >= 32768u ? INT16_MIN : (int16_t)(-(int32_t)mag);
    else *out = mag >= 32767u ? INT16_MAX : (int16_t)mag;
    return DUOFORGE_OK;
}
duoforge_status dfi_eval_binary32_id(uint32_t bits, uint32_t factor, uint32_t capacity, uint32_t *out)
{
    if (!out) return DUOFORGE_E_NULL_ARGUMENT;
    if (!capacity || ((bits >> 31u) && (bits & UINT32_C(0x7fffffff)))) return DUOFORGE_E_INVALID_ARGUMENT;
    uint64_t mag; duoforge_status st = bits_magnitude(bits, factor, 0u, &mag);
    if (st != DUOFORGE_OK) return st;
    if (mag >= capacity) return DUOFORGE_E_UNSUPPORTED;
    *out = (uint32_t)mag; return DUOFORGE_OK;
}
