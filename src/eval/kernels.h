#ifndef DFI_EVAL_KERNELS_H
#define DFI_EVAL_KERNELS_H
#include "eval/arithmetic.h"
#include <stddef.h>
/* Pure byte-extent predicate. The explicit limit permits platform-independent
   tests of narrower address spaces without a runtime override. No multiplication
   occurs until divisibility bounds prove the byte extent representable. */
static inline bool dfi_eval_extent(uint32_t rows, uint32_t width, size_t element_size, size_t byte_limit)
{
    return element_size != 0u && (rows == 0u || (size_t)width <= byte_limit / element_size / rows);
}
/* Row-major weights [output][input], ascending reductions; caller-owned buffers
   must be disjoint. Registered masks are bytes exactly 0 or 1. Empty pools zero.
   Failure invalidates output (no partial output may be consumed). */
DFI_PRIVATE duoforge_status dfi_eval_dense(const int16_t *input, uint32_t ni, const int8_t *weights,
                              const int64_t *bias, const dfi_eval_scale *scales,
                              uint32_t no, bool relu, int16_t *output);
/* BC6 pre-normalization storage and unclamped Q12.20 value head. The int32
   conversion refuses out-of-range results; it never applies int16 saturation. */
DFI_PRIVATE duoforge_status dfi_eval_dense32(const int16_t *input, uint32_t ni, const int8_t *weights,
                                const int64_t *bias, const dfi_eval_scale *scales,
                                uint32_t no, bool relu, int32_t *output);
DFI_PRIVATE duoforge_status dfi_eval_embedding(const int8_t *table, uint32_t rows, uint32_t width,
                                  uint32_t id, dfi_eval_scale scale, int16_t *output);
DFI_PRIVATE duoforge_status dfi_eval_pool(const int16_t *input, const uint8_t *mask, uint32_t rows,
                             uint32_t width, bool maximum, dfi_eval_scale scale, int16_t *output);
DFI_PRIVATE duoforge_status dfi_eval_gather(const int16_t *input, uint32_t rows, uint32_t width,
                               uint32_t index, bool present, int16_t *output);
/* Each branch explicitly rescales into the destination common tensor scale. */
DFI_PRIVATE duoforge_status dfi_eval_concat(const int16_t *a, uint32_t na, dfi_eval_scale sa,
                               const int16_t *b, uint32_t nb, dfi_eval_scale sb,
                               uint32_t capacity, int16_t *output);
#endif
