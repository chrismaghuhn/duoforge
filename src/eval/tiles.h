#ifndef DFI_EVAL_TILES_H
#define DFI_EVAL_TILES_H
#include "eval/graph.h"
#include "batch/pool.h"

typedef struct dfi_eval_row_source {
    /* Fills every raw encoder-6 column, with no heap or retained row pointer.
     * leaf is logical, worker owns the supplied bounded scratch row. */
    duoforge_status (*read)(void *user, uint32_t leaf, uint32_t worker,
        uint32_t bits[DFI_EVAL_INPUT_WIDTH], duoforge_eval_error *error);
    /* Optional private parity hook, called synchronously on that row's worker. */
    duoforge_status (*trace)(void *user, uint32_t leaf, const char *stage,
        uint32_t index, uint32_t type, const void *values, uint32_t count);
    void *user;
} dfi_eval_row_source;

/* Caller exclusively owns the existing pool for the complete synchronous call.
 * Arrays/source state must be disjoint from workspace and one another. The
 * source/trace callbacks may run concurrently, for distinct logical leaves.
 * Global preflight refusal touches no output/scratch. All real rows run after
 * acquisition, even after another row refuses. A refused value is untouched.
 * The lowest failing leaf selects the returned status/diagnostic after joining.
 * This private primitive neither expands battles nor selects a public backend. */
DFI_PRIVATE duoforge_status dfi_eval_tiles(const duoforge_evaluator *model,
    duoforge_eval_workspace *workspace, dfi_pool *pool, const uint8_t context[32],
    uint32_t count, const dfi_eval_row_source *source, duoforge_status *statuses,
    int32_t *values, duoforge_eval_error *error);
#endif
