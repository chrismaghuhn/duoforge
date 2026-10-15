#ifndef DFI_EVAL_GRAPH_H
#define DFI_EVAL_GRAPH_H
#include "eval/model.h"
#include "eval/inputs.h"
typedef struct dfi_eval_shape {
    const dfi_eval_graph *graph;
    const char *name;
    uint32_t embed, member, position, hidden, layers, parameters;
} dfi_eval_shape;
/* Compiled positive registry, never an executable graph supplied by a file. */
DFI_PRIVATE const dfi_eval_shape *dfi_eval_shape_lookup(uint32_t id);
DFI_PRIVATE duoforge_status dfi_eval_graph_bind(duoforge_evaluator *model, duoforge_eval_error *error);
typedef struct dfi_eval_trace {
    /* Private synthetic-oracle hook. Types: 1=int16, 2=int32, 3=uint32, 4=uint8. */
    duoforge_status (*emit)(void *user, const char *stage, uint32_t index,
        uint32_t type, const void *values, uint32_t count);
    void *user;
} dfi_eval_trace;
/* Scratch is a complete worker region; row selects one of its 16 slots.
 * Output and input must be disjoint from writable activation/canonical buffers.
 * Input may use a reserved encoder/raw-row slot. Output publishes on success.
 * A caller must hold the E2 workspace ownership across all worker calls. */
DFI_PRIVATE duoforge_status dfi_eval_graph_row(const duoforge_evaluator *model,
    void *scratch, size_t bytes, uint32_t row, const uint32_t bits[1094],
    const dfi_eval_trace *trace, int32_t *value, duoforge_eval_error *error);
DFI_PRIVATE size_t dfi_eval_graph_scratch(const dfi_eval_shape *shape);
#endif
