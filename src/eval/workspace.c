#include "eval/model.h"
#include <string.h>

static bool dfi_eval_context_equal(const uint8_t a[32], const uint8_t b[32])
{
    for (size_t i = 0; i < 32u; ++i) { if (a[i] != b[i]) { return false; } }
    return true;
}
static duoforge_status dfi_workspace_error(duoforge_eval_error *error, duoforge_status status, const char *reason)
{
    return dfi_eval_error(error, status, "workspace", reason);
}
duoforge_status dfi_eval_workspace_create(const duoforge_evaluator *immutable,
    uint32_t capacity, uint32_t workers, duoforge_eval_workspace **out, duoforge_eval_error *error)
{
    if (immutable == NULL || out == NULL) {
        return dfi_workspace_error(error, DUOFORGE_E_NULL_ARGUMENT, "eval_workspace_argument");
    }
    const dfi_eval_graph *graph = immutable->graph;
    if (capacity == 0u || workers == 0u) {
        return dfi_workspace_error(error, DUOFORGE_E_INVALID_ARGUMENT, "eval_workspace_configuration");
    }
    if (capacity > graph->max_leaves || workers > graph->max_workers ||
        graph->scratch_per_worker > SIZE_MAX / workers || graph->scratch_per_leaf > SIZE_MAX / capacity) {
        return dfi_workspace_error(error, DUOFORGE_E_CAPACITY, "eval_workspace_capacity");
    }
    const size_t worker_bytes = graph->scratch_per_worker * workers;
    const size_t leaf_bytes = graph->scratch_per_leaf * capacity;
    if (leaf_bytes > SIZE_MAX - worker_bytes || worker_bytes + leaf_bytes == 0u ||
        worker_bytes + leaf_bytes > graph->scratch_max) {
        return dfi_workspace_error(error, DUOFORGE_E_CAPACITY, "eval_workspace_capacity");
    }
    const dfi_eval_allocator allocator = immutable->allocator;
    duoforge_eval_workspace *workspace = allocator.allocate(sizeof *workspace, allocator.user);
    if (workspace == NULL) { return dfi_workspace_error(error, DUOFORGE_E_OUT_OF_MEMORY, "eval_workspace_allocation"); }
    memset(workspace, 0, sizeof *workspace);
    workspace->scratch_bytes = worker_bytes + leaf_bytes;
    workspace->scratch = allocator.allocate(workspace->scratch_bytes, allocator.user);
    if (workspace->scratch == NULL) {
        allocator.release(workspace, allocator.user);
        return dfi_workspace_error(error, DUOFORGE_E_OUT_OF_MEMORY, "eval_scratch_allocation");
    }
#if defined(_WIN32)
    InitializeSRWLock(&workspace->lock);
#else
    if (pthread_mutex_init(&workspace->lock, NULL) != 0) {
        allocator.release(workspace->scratch, allocator.user);
        allocator.release(workspace, allocator.user);
        return dfi_workspace_error(error, DUOFORGE_E_OUT_OF_MEMORY, "eval_workspace_lock");
    }
#endif
    const duoforge_evaluator *model = immutable;
    dfi_error_lock_enter(&model->lifetime->lock);
    if (model->lifetime->references == SIZE_MAX) {
        dfi_error_lock_leave(&model->lifetime->lock);
        dfi_error_lock_destroy(&workspace->lock);
        allocator.release(workspace->scratch, allocator.user);
        allocator.release(workspace, allocator.user);
        return dfi_workspace_error(error, DUOFORGE_E_EXHAUSTED, "eval_model_references");
    }
    ++model->lifetime->references;
    dfi_error_lock_leave(&model->lifetime->lock);
    workspace->model = model;
    workspace->capacity = capacity;
    workspace->workers = workers;
    *out = workspace;
    return dfi_workspace_error(error, DUOFORGE_OK, "");
}
duoforge_status dfi_eval_workspace_acquire(duoforge_eval_workspace *workspace,
    const duoforge_evaluator *model, const uint8_t context[32], uint32_t count,
    uint32_t workers, duoforge_eval_error *error)
{
    if (workspace == NULL || model == NULL || context == NULL) {
        return dfi_workspace_error(error, DUOFORGE_E_NULL_ARGUMENT, "eval_workspace_argument");
    }
    if (workspace->model != model || !dfi_eval_context_equal(model->context, context)) {
        return dfi_workspace_error(error, DUOFORGE_E_CONTEXT_MISMATCH, "eval_workspace_model_context");
    }
    if (workers != workspace->workers) {
        return dfi_workspace_error(error, DUOFORGE_E_INVALID_ARGUMENT, "eval_workspace_workers");
    }
    if (count > workspace->capacity) {
        return dfi_workspace_error(error, DUOFORGE_E_CAPACITY, "eval_workspace_capacity");
    }
    dfi_error_lock_enter(&workspace->lock);
    const bool busy = workspace->busy;
    if (!busy) { workspace->busy = true; }
    dfi_error_lock_leave(&workspace->lock);
    return dfi_workspace_error(error, busy ? DUOFORGE_E_UNSUPPORTED : DUOFORGE_OK,
                               busy ? "eval_workspace_busy" : "");
}
void dfi_eval_workspace_release(duoforge_eval_workspace *workspace)
{
    dfi_error_lock_enter(&workspace->lock);
    workspace->busy = false;
    dfi_error_lock_leave(&workspace->lock);
}
duoforge_status dfi_eval_workspace_destroy(duoforge_eval_workspace *workspace, duoforge_eval_error *error)
{
    if (workspace == NULL) { return dfi_workspace_error(error, DUOFORGE_OK, ""); }
    dfi_error_lock_enter(&workspace->lock);
    if (workspace->busy) {
        dfi_error_lock_leave(&workspace->lock);
        return dfi_workspace_error(error, DUOFORGE_E_UNSUPPORTED, "eval_workspace_busy");
    }
    workspace->busy = true;
    dfi_error_lock_leave(&workspace->lock);
    const duoforge_evaluator *model = workspace->model;
    const dfi_eval_allocator allocator = model->allocator;
    allocator.release(workspace->scratch, allocator.user);
    dfi_error_lock_destroy(&workspace->lock);
    allocator.release(workspace, allocator.user);
    dfi_eval_model_release(model);
    return dfi_workspace_error(error, DUOFORGE_OK, "");
}
