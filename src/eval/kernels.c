#include "eval/kernels.h"
#include <limits.h>
#include <stddef.h>
#include <string.h>
static bool shape(uint32_t rows, uint32_t width, size_t size)
{ return !rows || (width <= SIZE_MAX / rows && (size_t)width * rows <= SIZE_MAX / size); }
static bool scale_ok(dfi_eval_scale s) { return s.multiplier && s.shift <= 63u; }
static duoforge_status dense_core(const int16_t *in, uint32_t ni, const int8_t *weights,
                              const int64_t *bias, const dfi_eval_scale *scales,
                              uint32_t no, bool relu, int16_t *out16, int32_t *out32)
{
    if (!in || !weights || !bias || !scales || (!out16 && !out32)) return DUOFORGE_E_NULL_ARGUMENT;
    if (!ni || !no || !shape(no, ni, sizeof(*weights))) return DUOFORGE_E_INVALID_ARGUMENT;
    uint32_t input_abs = 0u;
    for (uint32_t i = 0; i < ni; ++i) {
        uint32_t mag = (uint32_t)dfi_eval_magnitude(in[i]);
        if (mag > input_abs) input_abs = mag;
    }
    for (uint32_t o = 0; o < no; ++o) {
        uint32_t wa = 0u;
        for (uint32_t i = 0; i < ni; ++i) {
            uint32_t mag = (uint32_t)dfi_eval_magnitude(weights[(size_t)o * ni + i]);
            if (mag > wa) wa = mag;
        }
        uint64_t bound;
        duoforge_status st = dfi_eval_dot_bound(ni, input_abs, wa, dfi_eval_magnitude(bias[o]), scales[o], &bound);
        if (st != DUOFORGE_OK) return st;
    }
    for (uint32_t o = 0; o < no; ++o) {
        int64_t sum = bias[o];
        for (uint32_t i = 0; i < ni; ++i) sum += (int64_t)in[i] * weights[(size_t)o * ni + i];
        if (relu && sum < 0) sum = 0;
        duoforge_status st = out32 ? dfi_eval_requant32(sum, scales[o], &out32[o])
                                 : dfi_eval_requant16(sum, scales[o], &out16[o]);
        if (st != DUOFORGE_OK) return st;
    }
    return DUOFORGE_OK;
}
duoforge_status dfi_eval_dense(const int16_t *in, uint32_t ni, const int8_t *weights,
                              const int64_t *bias, const dfi_eval_scale *scales,
                              uint32_t no, bool relu, int16_t *out)
{
    return dense_core(in, ni, weights, bias, scales, no, relu, out, NULL);
}
duoforge_status dfi_eval_dense32(const int16_t *in, uint32_t ni, const int8_t *weights,
                                const int64_t *bias, const dfi_eval_scale *scales,
                                uint32_t no, bool relu, int32_t *out)
{
    return dense_core(in, ni, weights, bias, scales, no, relu, NULL, out);
}
duoforge_status dfi_eval_embedding(const int8_t *table, uint32_t rows, uint32_t width,
                                  uint32_t id, dfi_eval_scale scale, int16_t *out)
{
    if (!table || !out) return DUOFORGE_E_NULL_ARGUMENT;
    if (!rows || !width || !shape(rows, width, sizeof(*table)) || !scale_ok(scale)) return DUOFORGE_E_INVALID_ARGUMENT;
    if (id >= rows) return DUOFORGE_E_UNSUPPORTED;
    for (uint32_t j = 0; j < width; ++j) {
        duoforge_status st = dfi_eval_requant16(table[(size_t)id * width + j], scale, &out[j]);
        if (st != DUOFORGE_OK) return st;
    }
    return DUOFORGE_OK;
}
duoforge_status dfi_eval_pool(const int16_t *in, const uint8_t *mask, uint32_t rows,
                             uint32_t width, bool maximum, dfi_eval_scale scale, int16_t *out)
{
    if (!out || (rows && (!in || !mask))) return DUOFORGE_E_NULL_ARGUMENT;
    if (!width || !shape(rows, width, sizeof(*in)) || !scale_ok(scale)) return DUOFORGE_E_INVALID_ARGUMENT;
    for (uint32_t r = 0; r < rows; ++r) if (mask[r] > 1u) return DUOFORGE_E_INVALID_ARGUMENT;
    for (uint32_t j = 0; j < width; ++j) {
        int64_t sum = 0; bool found = false;
        for (uint32_t r = 0; r < rows; ++r) if (mask[r]) {
            int64_t v = in[(size_t)r * width + j];
            if (maximum) { if (!found || v > sum) sum = v; }
            else sum += v; /* uint32 rows * int16 magnitude fits int64. */
            found = true;
        }
        duoforge_status st = dfi_eval_requant16(sum, scale, &out[j]);
        if (st != DUOFORGE_OK) return st;
    }
    return DUOFORGE_OK;
}
duoforge_status dfi_eval_gather(const int16_t *in, uint32_t rows, uint32_t width,
                               uint32_t index, bool present, int16_t *out)
{
    if (!in || !out) return DUOFORGE_E_NULL_ARGUMENT;
    if (!width || !shape(rows, width, sizeof(*in))) return DUOFORGE_E_INVALID_ARGUMENT;
    if (present && index >= rows) return DUOFORGE_E_UNSUPPORTED;
    if (present) memcpy(out, in + (size_t)index * width, (size_t)width * sizeof(*out));
    else memset(out, 0, (size_t)width * sizeof(*out));
    return DUOFORGE_OK;
}
duoforge_status dfi_eval_concat(const int16_t *a, uint32_t na, dfi_eval_scale sa,
                               const int16_t *b, uint32_t nb, dfi_eval_scale sb,
                               uint32_t capacity, int16_t *out)
{
    if (!out || (na && !a) || (nb && !b)) return DUOFORGE_E_NULL_ARGUMENT;
    if (na > capacity || nb > capacity - na) return DUOFORGE_E_CAPACITY;
    if (!scale_ok(sa) || !scale_ok(sb)) return DUOFORGE_E_INVALID_ARGUMENT;
    for (uint32_t j = 0; j < na; ++j) {
        duoforge_status st = dfi_eval_requant16(a[j], sa, &out[j]); if (st != DUOFORGE_OK) return st;
    }
    for (uint32_t j = 0; j < nb; ++j) {
        duoforge_status st = dfi_eval_requant16(b[j], sb, &out[na + j]); if (st != DUOFORGE_OK) return st;
    }
    return DUOFORGE_OK;
}
