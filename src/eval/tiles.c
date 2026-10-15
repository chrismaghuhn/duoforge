#include "eval/tiles.h"
#include <string.h>

/* Each worker stores one bounded diagnostic in its own unused tail. Copies
 * avoid imposing typed alignment on this byte region. No count-sized storage. */
#define DFI_EVAL_DIAGNOSTIC_BYTES 256u
typedef struct worker_result {
    duoforge_status status;
    duoforge_eval_error error;
} worker_result;
_Static_assert(sizeof(worker_result) <= DFI_EVAL_DIAGNOSTIC_BYTES, "worker diagnostic capacity");
typedef struct tile_job {
    const duoforge_evaluator *model;
    duoforge_eval_workspace *workspace;
    const dfi_eval_row_source *source;
    duoforge_status *statuses;
    int32_t *values;
    uint32_t count;
} tile_job;
typedef struct row_trace { const dfi_eval_row_source *source; uint32_t leaf; } row_trace;
static duoforge_status trace_row(void *user, const char *stage, uint32_t index,
    uint32_t type, const void *values, uint32_t count)
{
    const row_trace *row = user;
    return row->source->trace(row->source->user, row->leaf, stage, index, type, values, count);
}
static void tile_slice(void *user, uint32_t worker, uint32_t begin, uint32_t end)
{
    const tile_job *job = user;
    const size_t stride = job->model->graph->scratch_per_worker;
    uint8_t *region = job->workspace->scratch + (size_t)worker * stride;
    const uintptr_t address = (uintptr_t)region;
    const size_t low = (size_t)address & 127u;
    const size_t padding = (128u - low) & 127u;
    /* E3g reserves this aligned raw-row slot, separate from all activations. */
    uint32_t *bits = (uint32_t *)(void *)(region + padding);
    worker_result own;
    own.status = dfi_eval_error(&own.error, DUOFORGE_OK, "", "");
    for (uint32_t tile = begin; tile < end; ++tile) {
        /* Preflight limits count to 65,536: these offsets cannot wrap. */
        const uint32_t first = tile * 16u;
        const uint32_t rows = job->count - first < 16u ? job->count - first : 16u;
        for (uint32_t row = 0u; row < rows; ++row) {
            const uint32_t leaf = first + row;
            duoforge_eval_error detail;
            (void)dfi_eval_error(&detail, DUOFORGE_OK, "", "");
            duoforge_status status = job->source->read(job->source->user, leaf, worker, bits, &detail);
            if (status == DUOFORGE_OK) {
                row_trace state = {job->source, leaf};
                const dfi_eval_trace trace = {trace_row, &state};
                status = dfi_eval_graph_row(job->model, region, stride - DFI_EVAL_DIAGNOSTIC_BYTES,
                    row, bits, job->source->trace == NULL ? NULL : &trace, &job->values[leaf], &detail);
            } else if (detail.reason[0] == '\0') {
                (void)dfi_eval_error(&detail, status, "input", "eval_row_source_refused");
            }
            job->statuses[leaf] = status;
            if (own.status == DUOFORGE_OK && status != DUOFORGE_OK) {
                own.status = status;
                own.error = detail;
                own.error.leaf = leaf;
            }
        }
    }
    memcpy(region + stride - DFI_EVAL_DIAGNOSTIC_BYTES, &own, sizeof own);
}
duoforge_status dfi_eval_tiles(const duoforge_evaluator *model,
    duoforge_eval_workspace *workspace, dfi_pool *pool, const uint8_t context[32],
    uint32_t count, const dfi_eval_row_source *source, duoforge_status *statuses,
    int32_t *values, duoforge_eval_error *error)
{
    if (model == NULL || workspace == NULL || pool == NULL || context == NULL ||
        (count != 0u && (source == NULL || source->read == NULL || statuses == NULL || values == NULL)))
        return dfi_eval_error(error, DUOFORGE_E_NULL_ARGUMENT, "tiles", "eval_tiles_argument");
    const dfi_eval_shape *shape = dfi_eval_shape_lookup(model->graph->id);
    if (shape == NULL || shape->graph != model->graph || model->parameters == NULL)
        return dfi_eval_error(error, DUOFORGE_E_UNSUPPORTED, "tiles", "eval_graph_unregistered");
    const uint32_t workers = dfi_pool_workers(pool);
    const size_t stride = model->graph->scratch_per_worker;
    const size_t required = dfi_eval_graph_scratch(shape);
    duoforge_status status = dfi_eval_workspace_acquire(workspace, model, context, count, workers, error);
    if (status != DUOFORGE_OK) return status;
    if (workers > model->graph->max_workers || stride > SIZE_MAX / workers ||
        required > stride || stride - required < DFI_EVAL_DIAGNOSTIC_BYTES ||
        workspace->scratch_bytes < stride * workers ||
        (uint64_t)count * sizeof(*values) > SIZE_MAX || (uint64_t)count * sizeof(*statuses) > SIZE_MAX)
    {
        dfi_eval_workspace_release(workspace);
        return dfi_eval_error(error, DUOFORGE_E_CAPACITY, "tiles", "eval_tiles_capacity");
    }
    worker_result selected;
    selected.status = dfi_eval_error(&selected.error, DUOFORGE_OK, "", "");
    if (count != 0u) {
        const uint32_t tiles = count / 16u + (count % 16u != 0u ? 1u : 0u);
        tile_job job = {model, workspace, source, statuses, values, count};
        dfi_pool_run(pool, tile_slice, &job, tiles);
        for (uint32_t worker = 0u; worker < workers; ++worker) {
            /* Empty slices are never called and their old tail must not be read. */
            const uint32_t begin = (uint32_t)(((uint64_t)tiles * worker) / workers); /* wide-operands-reviewed */
            const uint32_t end = (uint32_t)(((uint64_t)tiles * (worker + 1u)) / workers); /* wide-operands-reviewed */
            if (begin == end) continue;
            worker_result own;
            const size_t boundary = (size_t)worker + 1u;
            memcpy(&own, workspace->scratch + boundary * stride - DFI_EVAL_DIAGNOSTIC_BYTES, sizeof own);
            if (own.status != DUOFORGE_OK && own.error.leaf < selected.error.leaf) selected = own;
        }
    }
    dfi_eval_workspace_release(workspace);
    if (error != NULL) *error = selected.error;
    return selected.status;
}
