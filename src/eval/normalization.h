#ifndef DFI_EVAL_NORMALIZATION_H
#define DFI_EVAL_NORMALIZATION_H
#include "eval/arithmetic.h"
#include "core/private.h"
/* normalization-v1: epsilon is positive in squared input-integer units.
   sqrt_shift declares fractional bits of sqrt(variance + epsilon).
   numerator_shift declares numerator bits; their difference fixes normalized units.
   Gamma product is requantized to beta units; output_scale defines output units.
   All shifts/scales are graph data, never selected from the current input. */
typedef struct dfi_eval_normalization {
    uint64_t epsilon;
    uint32_t sqrt_shift;
    uint32_t numerator_shift;
    dfi_eval_scale gamma_scale;
    dfi_eval_scale output_scale;
} dfi_eval_normalization;
/* Exact portable two-word radicand, correctly rounded adjacent-square result.
   UINT128_MAX may round to 2^64, which explicitly refuses instead of wrapping. */
DFI_PRIVATE duoforge_status dfi_eval_sqrt128(uint64_t hi, uint64_t lo, uint64_t *out);
typedef struct dfi_eval_normalization_stats {
    int64_t mean;
    uint64_t variance_hi;
    uint64_t variance_lo;
    uint64_t denominator;
} dfi_eval_normalization_stats;
/* Intermediate scalar oracle, also used by layernorm32. Stats publish last. */
DFI_PRIVATE duoforge_status dfi_eval_layernorm_moments(const int32_t *input,
    uint32_t count, dfi_eval_normalization parameters, dfi_eval_normalization_stats *out);
/* Caller supplies count int32 scratch cells. Outputs publish only on full success.
   count > 0, sqrt_shift <= 31, numerator_shift <= 63; arbitrary int32 inputs,
   gamma and beta. Gamma/beta must use the declared graph scales. No allocation. */
DFI_PRIVATE duoforge_status dfi_eval_layernorm32(const int32_t *input,
    const int32_t *gamma, const int32_t *beta, uint32_t count,
    dfi_eval_normalization parameters, int32_t *scratch, uint32_t capacity, int32_t *out);
/* Each branch is explicitly rescaled before the residual addition. Output32
   never saturates; residual16 alone declares final int16 saturation. */
DFI_PRIVATE duoforge_status dfi_eval_residual32(const int32_t *left, const int32_t *right,
    uint32_t count, dfi_eval_scale left_scale, dfi_eval_scale right_scale,
    dfi_eval_scale output_scale, int32_t *scratch, uint32_t capacity, int32_t *out);
DFI_PRIVATE duoforge_status dfi_eval_residual16(const int32_t *left, const int32_t *right,
    uint32_t count, dfi_eval_scale left_scale, dfi_eval_scale right_scale,
    dfi_eval_scale output_scale, int32_t *scratch, uint32_t capacity, int16_t *out);
#endif
