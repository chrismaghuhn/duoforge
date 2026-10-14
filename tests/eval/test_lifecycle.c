#include <duoforge/duoforge_eval.h>
#include "eval/model.h"
#include "state/context_internal.h"
#include "support/check.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(DF_EVAL_ALLOC_WRAP)
/* Linker hooks cover every repository C allocation/free during warmed ownership
 * operations, not only the injected model allocator. Test counters are local
 * to this executable, never library state. */
static bool allocation_armed;
static size_t warmed_allocations, warmed_frees;
void *__wrap_malloc(size_t bytes);
void *__wrap_calloc(size_t count, size_t bytes);
void *__wrap_realloc(void *p, size_t bytes);
void __wrap_free(void *p);
void *__real_malloc(size_t bytes);
void *__real_calloc(size_t count, size_t bytes);
void *__real_realloc(void *p, size_t bytes);
void __real_free(void *p);
void *__wrap_malloc(size_t bytes)
{
    if (allocation_armed) { ++warmed_allocations; }
    return __real_malloc(bytes);
}
void *__wrap_calloc(size_t count, size_t bytes)
{
    if (allocation_armed) { ++warmed_allocations; }
    return __real_calloc(count, bytes);
}
void *__wrap_realloc(void *p, size_t bytes)
{
    if (allocation_armed) { ++warmed_allocations; }
    return __real_realloc(p, bytes);
}
void __wrap_free(void *p)
{
    if (allocation_armed) { ++warmed_frees; }
    __real_free(p);
}
#endif
/* Public tests never register this graph. Only the private whitebox seam sees
 * these deterministic toy tensors generated in temporary storage. */
static const dfi_eval_tensor_spec tensors[] = {
    {"dense.weight", 1u, 2u, {2u, 3u, 0u, 0u}, 2u, 32768u, 3u, 17u},
    {"dense.bias", 4u, 1u, {2u, 0u, 0u, 0u}, 0u, 0u, 0u, 17u}
};
static const dfi_eval_graph graph = {
    1u, 1u, 6u, 1094u, 0u, 4096u,
    {1u}, {2u}, 2u, 32u, 8u, 64u, 8u, 768u, tensors
};
typedef struct allocations { size_t count, frees, fail; const char *mutate; } allocations;
static void *allocate(size_t bytes, void *user)
{
    allocations *a = user;
    if (a->mutate != NULL) {
        FILE *file = fopen(a->mutate, "r+b");
        if (file != NULL) { (void)fputc(0, file); (void)fclose(file); }
        a->mutate = NULL;
    }
    if (a->count++ == a->fail) { return NULL; }
    return calloc(1u, bytes);
}
static void release(void *p, void *user)
{
    allocations *a = user;
    if (p != NULL) { ++a->frees; }
    free(p);
}
#if defined(_WIN32)
static DWORD WINAPI other_caller(void *p)
#else
static void *other_caller(void *p)
#endif
{
    duoforge_eval_workspace *w = p;
    const duoforge_status status = dfi_eval_workspace_acquire(w, w->model, w->model->context, 1u, 8u, NULL);
#if defined(_WIN32)
    return (DWORD)status;
#else
    return (void *)(uintptr_t)status;
#endif
}
static void workspace_checks(df_test *t, duoforge_evaluator *model, const duoforge_evaluator *other, allocations *a)
{
    df_sentinel sentinel;
    duoforge_eval_workspace *w = (duoforge_eval_workspace *)&sentinel;
    duoforge_eval_error error;
    DF_CHECK_EQ_U64(t, duoforge_eval_workspace_create(model, 33u, 8u, &w, &error), DUOFORGE_E_CAPACITY);
    DF_CHECK(t, w == (duoforge_eval_workspace *)&sentinel);
    DF_CHECK_EQ_U64(t, duoforge_eval_workspace_create(model, 32u, 9u, &w, &error), DUOFORGE_E_CAPACITY);
    DF_CHECK_EQ_U64(t, duoforge_eval_workspace_create(model, 0u, 8u, &w, &error), DUOFORGE_E_INVALID_ARGUMENT);
    for (size_t fail = 0u; fail < 2u; ++fail) {
        a->fail = a->count + fail;
        const size_t frees = a->frees;
        DF_CHECK_EQ_U64(t, duoforge_eval_workspace_create(model, 32u, 8u, &w, &error), DUOFORGE_E_OUT_OF_MEMORY);
        DF_CHECK_EQ_U64(t, a->frees - frees, fail);
        DF_CHECK(t, w == (duoforge_eval_workspace *)&sentinel);
    }
    a->fail = SIZE_MAX;
    if (!DF_CHECK_EQ_U64(t, duoforge_eval_workspace_create(model, 32u, 8u, &w, &error), DUOFORGE_OK)) { return; }
    DF_CHECK_EQ_U64(t, w->scratch_bytes, 768u);
    DF_CHECK_EQ_U64(t, dfi_eval_workspace_acquire(w, other, other->context, 32u, 8u, &error), DUOFORGE_E_CONTEXT_MISMATCH);
    DF_CHECK_BYTES(t, other->sha256, model->sha256, 32u, "even same-hash different handles refuse");
    const size_t count = a->count, frees = a->frees;
    memset(w->scratch, 0xA5, w->scratch_bytes);
    uint8_t wrong[32]; memcpy(wrong, model->context, sizeof wrong); wrong[0] ^= 1u;
    DF_CHECK_EQ_U64(t, dfi_eval_workspace_acquire(w, model, wrong, 32u, 8u, &error), DUOFORGE_E_CONTEXT_MISMATCH);
    DF_CHECK_EQ_U64(t, dfi_eval_workspace_acquire(w, model, model->context, 33u, 8u, &error), DUOFORGE_E_CAPACITY);
    DF_CHECK_EQ_U64(t, dfi_eval_workspace_acquire(w, model, model->context, 32u, 7u, &error), DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK_EQ_U64(t, dfi_eval_workspace_acquire(w, model, model->context, 32u, 8u, &error), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, duoforge_eval_workspace_destroy(w, &error), DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, strcmp(error.reason, "eval_workspace_busy") == 0);
#if defined(_WIN32)
    HANDLE thread = CreateThread(NULL, 0, other_caller, w, 0, NULL);
    if (DF_CHECK(t, thread != NULL)) {
        DWORD result = 0;
        DF_CHECK_EQ_U64(t, WaitForSingleObject(thread, INFINITE), WAIT_OBJECT_0);
        DF_CHECK(t, GetExitCodeThread(thread, &result) != 0);
        DF_CHECK_EQ_U64(t, result, DUOFORGE_E_UNSUPPORTED);
        (void)CloseHandle(thread);
    }
#else
    pthread_t thread;
    if (DF_CHECK_EQ_U64(t, pthread_create(&thread, NULL, other_caller, w), 0u)) {
        void *result = NULL;
        DF_CHECK_EQ_U64(t, pthread_join(thread, &result), 0u);
        DF_CHECK_EQ_U64(t, (uintptr_t)result, DUOFORGE_E_UNSUPPORTED);
    }
#endif
    dfi_eval_workspace_release(w);
#if defined(DF_EVAL_ALLOC_WRAP)
    allocation_armed = true;
#endif
    for (size_t i = 0; i < 1000u; ++i) {
        DF_CHECK_EQ_U64(t, dfi_eval_workspace_acquire(w, model, model->context, 32u, 8u, NULL), DUOFORGE_OK);
        dfi_eval_workspace_release(w);
    }
#if defined(DF_EVAL_ALLOC_WRAP)
    allocation_armed = false;
    DF_CHECK_EQ_U64(t, warmed_allocations, 0u);
    DF_CHECK_EQ_U64(t, warmed_frees, 0u);
#endif
    for (size_t i = 0; i < w->scratch_bytes; ++i) { DF_CHECK_EQ_U64(t, w->scratch[i], 0xA5u); }
    DF_CHECK_EQ_U64(t, a->count, count);
    DF_CHECK_EQ_U64(t, a->frees, frees);
    /* Workspace retains model after the caller releases its model handle. */
    duoforge_evaluator_destroy(model);
    DF_CHECK_EQ_U64(t, dfi_eval_workspace_acquire(w, w->model, w->model->context, 0u, 8u, NULL), DUOFORGE_OK);
    dfi_eval_workspace_release(w);
    DF_CHECK_EQ_U64(t, duoforge_eval_workspace_destroy(w, &error), DUOFORGE_OK);
}
int main(int argc, char **argv)
{
    const duoforge_context_config config = {DUOFORGE_DATA_KIND_CLOSURE, 6u, 4u, 0u, 0u, NULL};
    duoforge_context *context = NULL;
    if (duoforge_context_create(&config, &context) != DUOFORGE_OK) { return 2; }
    uint8_t context_hash[32];
    (void)duoforge_context_fingerprint(context, context_hash);
    if (argc == 2 && strcmp(argv[1], "--context") == 0) {
        for (size_t i = 0; i < sizeof context_hash; ++i) { (void)printf("%02x", context_hash[i]); }
        (void)printf(" %u %u\n", context->species_count, context->move_count); duoforge_context_destroy(context); return 0;
    }
    df_test t; df_test_begin(&t, "duoforge.eval.lifecycle");
    df_sentinel sentinel;
    duoforge_evaluator *model = (duoforge_evaluator *)&sentinel;
    duoforge_eval_error error;
    if (argc == 1) {
        uint8_t hash[32] = {0};
        DF_CHECK_EQ_U64(&t, duoforge_evaluator_load(NULL, hash, context, 6u, 0u, &model, &error), DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK_EQ_U64(&t, duoforge_evaluator_load("relative", hash, context, 6u, 0u, &model, &error), DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK_EQ_U64(&t, duoforge_evaluator_load("/never-open", NULL, context, 6u, 0u, &model, &error), DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, model == (duoforge_evaluator *)&sentinel);
        DF_CHECK_EQ_U64(&t, duoforge_eval_workspace_create(NULL, 1u, 1u, NULL, &error), DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK_EQ_U64(&t, duoforge_eval_workspace_destroy(NULL, &error), DUOFORGE_OK);
        duoforge_evaluator_destroy(NULL);
    } else if (argc == 5) {
        uint8_t hash[32];
        if (!DF_CHECK(&t, df_hex_to_bytes(argv[3], hash, sizeof hash))) { return df_test_end(&t); }
        allocations a = {0u, 0u, SIZE_MAX, NULL};
        const dfi_eval_allocator allocator = {allocate, release, &a};
        if (strcmp(argv[1], "--oom") == 0) {
            for (size_t i = 0; i < 3u; ++i) {
                a.fail = a.count + i;
                const size_t frees = a.frees;
                DF_CHECK_EQ_U64(&t, dfi_eval_load_descriptor(argv[2], hash, context, 6u, 0u, &graph, &allocator, &model, &error), DUOFORGE_E_OUT_OF_MEMORY);
                DF_CHECK(&t, model == (duoforge_evaluator *)&sentinel);
                DF_CHECK_EQ_U64(&t, a.frees - frees, i);
            }
        } else {
            dfi_eval_graph selected = graph;
            dfi_eval_tensor_spec selected_tensors[2] = {tensors[0], tensors[1]};
            selected.tensors = selected_tensors;
            if (strcmp(argv[1], "--i16") == 0) {
                selected_tensors[0].dtype = 2u; selected_tensors[0].bias_bound = 32768u;
            }
            if (strcmp(argv[1], "--i32") == 0) {
                selected_tensors[0].dtype = 3u; selected_tensors[0].bias_bound = UINT64_C(2147483648);
            }
            if (strcmp(argv[1], "--bound") == 0) { selected_tensors[0].bias_bound = INT64_MAX; }
            if (strcmp(argv[1], "--product") == 0) { selected_tensors[0].bias_bound = INT64_MAX / 2u; }
            if (strcmp(argv[1], "--shape") == 0) {
                selected_tensors[0].rank = 4u;
                for (size_t i = 0; i < 4u; ++i) { selected_tensors[0].dims[i] = UINT32_MAX; }
            }
            if (strcmp(argv[1], "--scratch") == 0) { selected.scratch_per_worker = SIZE_MAX; }
            if (strcmp(argv[1], "--race") == 0) { a.mutate = argv[2]; }
            const duoforge_status status = strcmp(argv[1], "--public") == 0 ?
                duoforge_evaluator_load(argv[2], hash, context, 6u, 0u, &model, &error) :
                dfi_eval_load_descriptor(argv[2], hash, context, 6u, 0u, &selected, &allocator, &model, &error);
            if (strcmp(argv[4], "SCRATCH") == 0) {
                if (DF_CHECK_EQ_U64(&t, status, DUOFORGE_OK)) {
                    duoforge_eval_workspace *w = (duoforge_eval_workspace *)&sentinel;
                    DF_CHECK_EQ_U64(&t, duoforge_eval_workspace_create(model, 32u, 8u, &w, &error), DUOFORGE_E_CAPACITY);
                    DF_CHECK(&t, w == (duoforge_eval_workspace *)&sentinel);
                    duoforge_evaluator_destroy(model);
                }
            } else if (strcmp(argv[4], "OK") == 0) {
                if (status != DUOFORGE_OK) { (void)fprintf(stderr, "unexpected refusal: %s\n", error.reason); }
                if (DF_CHECK_EQ_U64(&t, status, DUOFORGE_OK)) {
                    DF_CHECK_BYTES(&t, model->sha256, hash, 32u, "expected opened-file hash");
                    DF_CHECK_BYTES(&t, model->context, context_hash, 32u, "context snapshot");
                    duoforge_evaluator *other = NULL;
                    if (!DF_CHECK_EQ_U64(&t, dfi_eval_load_descriptor(argv[2], hash, context, 6u, 0u,
                            &selected, &allocator, &other, &error), DUOFORGE_OK)) {
                        duoforge_evaluator_destroy(model);
                        duoforge_context_destroy(context); return df_test_end(&t);
                    }
                    /* No later file I/O: unlink before every workspace operation. */
                    DF_CHECK_EQ_U64(&t, remove(argv[2]), 0u);
                    workspace_checks(&t, model, other, &a);
                    duoforge_evaluator_destroy(other);
                }
            } else {
                DF_CHECK(&t, status != DUOFORGE_OK);
                DF_CHECK(&t, strcmp(error.reason, argv[4]) == 0);
                DF_CHECK(&t, model == (duoforge_evaluator *)&sentinel);
                DF_CHECK_EQ_U64(&t, error.leaf, UINT32_MAX);
                DF_CHECK(&t, strcmp(error.phase, "load") == 0);
            }
        }
    } else { DF_CHECK(&t, false); }
    duoforge_context_destroy(context);
    return df_test_end(&t);
}
