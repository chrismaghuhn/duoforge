#ifndef DFI_EVAL_MODEL_H
#define DFI_EVAL_MODEL_H
#include <duoforge/duoforge_eval.h>
#include "core/private.h"
#include "search/error_lock.h"
#include <stdbool.h>
#include <stddef.h>
/* Numeric tags below are private wire tags, not gameplay identifiers. */
#define DFI_EVAL_HEADER_BYTES 256u
#define DFI_EVAL_TENSOR_BYTES 128u
#define DFI_EVAL_MAX_TENSORS 128u
#define DFI_EVAL_METADATA_MAX 65536u
#define DFI_EVAL_FILE_MAX (UINT64_C(1) << 30)

typedef struct dfi_eval_tensor_spec {
    const char *name;
    uint32_t dtype, rank, dims[4], scale_count;
    uint32_t input_bound, fan_in;
    uint64_t bias_bound;
} dfi_eval_tensor_spec;
/* E3g registers reviewed full/small/medium graphs. No graph instructions are
 * read from a file. Bound arithmetic and scratch formulas belong here. */
typedef struct dfi_eval_graph {
    uint32_t id, arithmetic, encoder, width;
    uint64_t mask, file_max;
    uint8_t features[32], layout[32];
    uint32_t tensor_count, max_leaves, max_workers;
    size_t scratch_per_worker, scratch_per_leaf, scratch_max;
    const dfi_eval_tensor_spec *tensors;
} dfi_eval_graph;

typedef struct dfi_eval_allocator {
    void *(*allocate)(size_t bytes, void *user);
    void (*release)(void *memory, void *user);
    void *user;
} dfi_eval_allocator;

typedef struct dfi_eval_lifetime {
    dfi_error_lock lock;
    size_t references;
    void *owner;
} dfi_eval_lifetime;
struct duoforge_evaluator {
    const dfi_eval_graph *graph; /* compiled static lifetime */
    uint8_t sha256[32], context[32];
    uint8_t *file;
    size_t file_bytes;
    dfi_eval_allocator allocator;
    dfi_eval_lifetime *lifetime;
    void *parameters; /* immutable cold-decoded compiled graph bindings */
    size_t parameter_bytes;
};
struct duoforge_eval_workspace {
    const duoforge_evaluator *model;
    uint32_t capacity, workers;
    size_t scratch_bytes;
    uint8_t *scratch;
    dfi_error_lock lock;
    bool busy;
};
DFI_PRIVATE duoforge_status dfi_eval_error(duoforge_eval_error *error, duoforge_status status,
                                          const char *phase, const char *reason);
DFI_PRIVATE duoforge_status dfi_eval_load(const char *path, const uint8_t expected[32],
    const duoforge_context *context, uint32_t version, uint64_t mask,
    duoforge_evaluator **out, duoforge_eval_error *error);
/* Private whitebox seam; never used by public load, only immutable compiled
 * descriptors are acceptable. Fault injection concerns cold allocation only. */
DFI_PRIVATE duoforge_status dfi_eval_load_descriptor(const char *path, const uint8_t expected[32],
    const duoforge_context *context, uint32_t version, uint64_t mask,
    const dfi_eval_graph *graph, const dfi_eval_allocator *allocator,
    duoforge_evaluator **out, duoforge_eval_error *error);
DFI_PRIVATE void dfi_eval_model_release(const duoforge_evaluator *model);
DFI_PRIVATE duoforge_status dfi_eval_workspace_create(const duoforge_evaluator *model,
    uint32_t capacity, uint32_t workers, duoforge_eval_workspace **out, duoforge_eval_error *error);
DFI_PRIVATE duoforge_status dfi_eval_workspace_destroy(duoforge_eval_workspace *workspace,
    duoforge_eval_error *error);
/* Preflight-only, no heap/file access. On success workspace remains owned until
 * release. Bound checks and busy checks never mutate another owner's scratch. */
DFI_PRIVATE duoforge_status dfi_eval_workspace_acquire(duoforge_eval_workspace *workspace,
    const duoforge_evaluator *model, const uint8_t context[32], uint32_t count,
    uint32_t workers, duoforge_eval_error *error);
DFI_PRIVATE void dfi_eval_workspace_release(duoforge_eval_workspace *workspace);
#endif
