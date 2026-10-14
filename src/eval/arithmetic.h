#ifndef DFI_EVAL_ARITHMETIC_H
#define DFI_EVAL_ARITHMETIC_H
#include <duoforge/duoforge.h>
#include <stdint.h>
/* Private scalar oracle: multiplier > 0, shift <= 63. No negative signed shifts.
   Overflow is a refusal; only the declared int16 output conversion saturates. */
typedef struct dfi_eval_scale { uint32_t multiplier; uint32_t shift; } dfi_eval_scale;
uint64_t dfi_eval_magnitude(int64_t value);
duoforge_status dfi_eval_add(int64_t a, int64_t b, int64_t *out);
duoforge_status dfi_eval_mul(int64_t a, int64_t b, int64_t *out);
duoforge_status dfi_eval_round_div(int64_t value, uint64_t divisor, int64_t *out);
duoforge_status dfi_eval_requant(int64_t value, dfi_eval_scale scale, int64_t *out);
duoforge_status dfi_eval_requant16(int64_t value, dfi_eval_scale scale, int16_t *out);
/* Conservative absolute bounds. These cold proofs use actual max weight magnitude. */
duoforge_status dfi_eval_dot_bound(uint32_t count, uint32_t input_abs, uint32_t weight_abs,
                                  uint64_t bias_abs, dfi_eval_scale scale, uint64_t *out);
/* Convert finite IEEE binary32 bits with an integer-only exact rounding oracle. */
duoforge_status dfi_eval_binary32(uint32_t bits, dfi_eval_scale scale, int16_t *out);
duoforge_status dfi_eval_binary32_id(uint32_t bits, uint32_t factor, uint32_t capacity, uint32_t *out);
#endif
