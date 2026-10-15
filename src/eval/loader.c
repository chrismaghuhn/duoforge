#include "eval/model.h"
#include "core/alloc.h"
#include "core/sha256.h"
#include "state/context_internal.h"
#include <stdio.h>
#include <string.h>
#include <limits.h>

static uint32_t dfi_u32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t dfi_u64(const uint8_t *p)
{
    return (uint64_t)dfi_u32(p) | (uint64_t)dfi_u32(p + 4) << 32;
}
static bool dfi_equal(const void *left, const void *right, size_t bytes)
{
    const uint8_t *a = left, *b = right;
    for (size_t i = 0; i < bytes; ++i) { if (a[i] != b[i]) { return false; } }
    return true;
}
static bool dfi_zero(const uint8_t *p, size_t n)
{
    for (size_t i = 0; i < n; ++i) { if (p[i] != 0u) { return false; } }
    return true;
}
static bool dfi_absolute(const char *p)
{
#if defined(_WIN32)
    return (((p[0] >= 'A' && p[0] <= 'Z') || (p[0] >= 'a' && p[0] <= 'z')) &&
            p[1] == ':' && (p[2] == '\\' || p[2] == '/')) ||
           (p[0] == '\\' && p[1] == '\\' && p[2] != '\0');
#else
    return p[0] == '/';
#endif
}
static void *dfi_allocate(size_t bytes, void *user) { (void)user; return dfi_alloc_zeroed(bytes); }
static void dfi_release(void *p, void *user) { (void)user; dfi_free(p); }
static const dfi_eval_allocator dfi_default_allocator = {dfi_allocate, dfi_release, NULL};

duoforge_status dfi_eval_error(duoforge_eval_error *error, duoforge_status status,
                               const char *phase, const char *reason)
{
    if (error != NULL) {
        memset(error, 0, sizeof *error);
        error->leaf = UINT32_MAX;
        if (status != DUOFORGE_OK) {
            (void)snprintf(error->phase, sizeof error->phase, "%s", phase);
            (void)snprintf(error->reason, sizeof error->reason, "%s", reason);
        }
    }
    return status;
}
/* Exactly this six-key ASCII subset is canonical UTF-8. No arbitrary metadata
 * is accepted; artifact-level hashes and schema live in the fixed header. */
static bool dfi_metadata(const uint8_t *p, size_t bytes)
{
    static const char *const keys[] = {
        "export_commit=", "export_dirty=", "seed=", "split_sha256=", "training_commit=", "training_dirty="
    };
    size_t off = 0u;
    for (size_t i = 0; i < 6u; ++i) {
        const size_t key = strlen(keys[i]);
        if (bytes - off < key || !dfi_equal(p + off, keys[i], key)) { return false; }
        off += key;
        size_t n = 0u;
        uint64_t seed = 0u;
        while (off < bytes && p[off] != '\n') {
            const uint8_t c = p[off++];
            if (i == 2u) {
                if (c < '0' || c > '9' || (n > 0u && seed == 0u) ||
                    seed > (UINT64_MAX - ((uint64_t)c - (uint64_t)'0')) / 10u) { return false; }
                seed = seed * 10u + ((uint64_t)c - (uint64_t)'0');
            } else if (i == 1u || i == 5u) {
                if (n != 0u || (c != '0' && c != '1')) { return false; }
            } else if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) { return false; }
            ++n;
        }
        const size_t required = i == 3u ? 64u : (i == 0u || i == 4u ? 40u : 1u);
        if (off >= bytes || (i == 2u ? n == 0u || n > 20u : n != required)) { return false; }
        ++off;
    }
    return off == bytes;
}
static bool dfi_span(size_t size, uint64_t offset, uint64_t bytes)
{
    return offset <= (uint64_t)size && bytes <= (uint64_t)size - offset;
}
static bool dfi_align(size_t *offset, const uint8_t *bytes, size_t size)
{
    if (*offset > SIZE_MAX - 7u) { return false; }
    const size_t next = (*offset + 7u) & ~(size_t)7u;
    if (next > size || !dfi_zero(bytes + *offset, next - *offset)) { return false; }
    *offset = next;
    return true;
}
static bool dfi_tensor(const uint8_t *file, size_t size, const uint8_t *entry,
                       const dfi_eval_tensor_spec *spec, size_t *cursor)
{
    const size_t name = strlen(spec->name);
    if (name == 0u || name >= 32u || !dfi_equal(entry, spec->name, name) ||
        !dfi_zero(entry + name, 32u - name) || dfi_u32(entry + 32) != spec->dtype ||
        dfi_u32(entry + 36) != spec->rank || spec->rank == 0u || spec->rank > 4u ||
        !dfi_zero(entry + 84, 44u)) { return false; }
    uint64_t elements = 1u;
    for (size_t i = 0; i < 4u; ++i) {
        if (dfi_u32(entry + 40u + 4u * i) != spec->dims[i]) { return false; }
        if (i < spec->rank) {
            if (spec->dims[i] == 0u || elements > UINT64_MAX / spec->dims[i]) { return false; }
            elements *= spec->dims[i];
        } else if (spec->dims[i] != 0u) { return false; }
    }
    if (spec->dtype < 1u || spec->dtype > 4u) { return false; }
    const uint64_t width = UINT64_C(1) << (spec->dtype - 1u);
    if (elements > UINT64_MAX / width || dfi_u64(entry + 64) != elements * width ||
        dfi_u64(entry + 56) != *cursor || !dfi_span(size, *cursor, elements * width)) { return false; }
    const uint8_t *data = file + *cursor;
    uint64_t weight_abs = 0u, bias_abs = spec->bias_bound;
    if (spec->dtype == 1u) {
        for (uint64_t i = 0; i < elements; ++i) {
            const uint64_t a = data[i] >= 128u ? 256u - data[i] : data[i];
            if (a > weight_abs) { weight_abs = a; }
        }
    } else if (spec->dtype == 2u || spec->dtype == 3u) {
        const uint64_t sign = UINT64_C(1) << (width * 8u - 1u);
        const uint64_t mask = (sign << 1u) - 1u;
        for (uint64_t i = 0; i < elements; ++i) {
            const uint8_t *p = data + (size_t)i * (size_t)width;
            const uint64_t bits = spec->dtype == 2u ? (uint64_t)p[0] | (uint64_t)p[1] << 8u : dfi_u32(p);
            const uint64_t a = (bits & sign) != 0u ? (~bits & mask) + 1u : bits;
            if (a > spec->bias_bound) { return false; }
            if (a > weight_abs) { weight_abs = a; }
        }
    } else if (spec->dtype == 4u) {
        for (uint64_t i = 0; i < elements; ++i) {
            const uint64_t bits = dfi_u64(data + (size_t)i * 8u);
            const uint64_t a = bits >> 63 ? ~bits + 1u : bits;
            if (a > spec->bias_bound || a > INT64_MAX) { return false; }
        }
    }
    *cursor += (size_t)elements * (size_t)width;
    if (!dfi_align(cursor, file, size) || dfi_u32(entry + 80) != spec->scale_count) { return false; }
    if (spec->scale_count == 0u) { return dfi_u64(entry + 72) == 0u; }
    if (dfi_u64(entry + 72) != *cursor || !dfi_span(size, *cursor, (uint64_t)spec->scale_count * 8u) ||
        spec->input_bound > 32768u || spec->bias_bound > INT64_MAX) { return false; }
    /* No magnitude multiplication until its absolute bound has been proved. */
    uint64_t bound = (uint64_t)spec->fan_in * spec->input_bound;
    if (weight_abs != 0u && bound > (uint64_t)INT64_MAX / weight_abs) { return false; }
    bound *= weight_abs;
    if (bound > (uint64_t)INT64_MAX - bias_abs) { return false; }
    bound += bias_abs;
    for (uint32_t i = 0; i < spec->scale_count; ++i) {
        const uint8_t *scale = file + *cursor + (size_t)i * 8u;
        const uint32_t multiplier = dfi_u32(scale), shift = dfi_u32(scale + 4);
        if (multiplier == 0u || shift > 63u || bound > (uint64_t)INT64_MAX / multiplier) { return false; }
    }
    *cursor += (size_t)spec->scale_count * 8u;
    return true;
}
static duoforge_status dfi_validate(const uint8_t *file, size_t size, const duoforge_context *context,
    uint32_t version, uint64_t mask, const dfi_eval_graph *graph, duoforge_eval_error *error)
{
#define REFUSE(code, reason) return dfi_eval_error(error, (code), "load", (reason))
    if (size < DFI_EVAL_HEADER_BYTES || !dfi_equal(file, "DFEVAL\0\0", 8u)) {
        REFUSE(DUOFORGE_E_MALFORMED, "eval_header");
    }
    if (dfi_u32(file + 8) != 1u || dfi_u32(file + 12) != DFI_EVAL_HEADER_BYTES) {
        REFUSE(DUOFORGE_E_SCHEMA_MISMATCH, "eval_format_version");
    }
    if (dfi_u64(file + 16) != size) {
        REFUSE(DUOFORGE_E_MALFORMED, "eval_file_length");
    }
    if (dfi_u32(file + 48) != DUOFORGE_SEMANTICS_ID ||
        dfi_u32(file + 52) != DUOFORGE_CONTEXT_SCHEMA_VERSION) {
        REFUSE(DUOFORGE_E_SEMANTICS_MISMATCH, "eval_semantics");
    }
    if (!dfi_equal(file + 96, context->fingerprint, 32u) ||
        dfi_u32(file + 88) != context->species_count || dfi_u32(file + 92) != context->move_count) {
        REFUSE(DUOFORGE_E_CONTEXT_MISMATCH, "eval_context");
    }
    if (dfi_u32(file + 32) != version || dfi_u64(file + 40) != mask) {
        REFUSE(DUOFORGE_E_SCHEMA_MISMATCH, "eval_encoder_mask");
    }
    if (graph == NULL || dfi_u32(file + 24) != graph->id) {
        REFUSE(DUOFORGE_E_UNSUPPORTED, "eval_graph_unregistered");
    }
    if (graph->encoder != version || graph->mask != mask || graph->width != dfi_u32(file + 36) ||
        graph->arithmetic != dfi_u32(file + 28) ||
        !dfi_equal(graph->features, file + 192, 32u) || !dfi_equal(graph->layout, file + 224, 32u)) {
        REFUSE(DUOFORGE_E_SCHEMA_MISMATCH, "eval_graph_schema");
    }
    const uint32_t count = dfi_u32(file + 56), metadata = dfi_u32(file + 60);
    if (count != graph->tensor_count || count == 0u || count > DFI_EVAL_MAX_TENSORS) {
        REFUSE(DUOFORGE_E_MALFORMED, "eval_tensor_inventory");
    }
    if (metadata > DFI_EVAL_METADATA_MAX) { REFUSE(DUOFORGE_E_CAPACITY, "eval_metadata_capacity"); }
    const uint64_t meta = DFI_EVAL_HEADER_BYTES + (uint64_t)count * DFI_EVAL_TENSOR_BYTES;
    if (dfi_u64(file + 64) != DFI_EVAL_HEADER_BYTES || dfi_u64(file + 72) != meta ||
        !dfi_span(size, meta, metadata) || !dfi_metadata(file + (size_t)meta, metadata) ||
        dfi_zero(file + 128, 32u) || dfi_zero(file + 160, 32u)) {
        REFUSE(DUOFORGE_E_MALFORMED, "eval_metadata");
    }
    size_t cursor = (size_t)meta + metadata;
    if (!dfi_align(&cursor, file, size) || dfi_u64(file + 80) != cursor) {
        REFUSE(DUOFORGE_E_MALFORMED, "eval_data_offset");
    }
    for (uint32_t i = 0; i < count; ++i) {
        const dfi_eval_tensor_spec *spec = &graph->tensors[i];
        if (!dfi_tensor(file, size, file + DFI_EVAL_HEADER_BYTES + (size_t)i * DFI_EVAL_TENSOR_BYTES,
                        spec, &cursor)) {
            char reason[128];
            (void)snprintf(reason, sizeof reason, "eval_tensor_invalid:%s", spec->name);
            return dfi_eval_error(error, DUOFORGE_E_MALFORMED, "load", reason);
        }
    }
    if (cursor != size) { REFUSE(DUOFORGE_E_MALFORMED, "eval_trailing_data"); }
    return DUOFORGE_OK;
#undef REFUSE
}
static duoforge_status dfi_read(const char *path, const uint8_t expected[32],
    const duoforge_context *context, uint32_t version, uint64_t mask, const dfi_eval_graph *graph,
    const dfi_eval_allocator *allocator, duoforge_evaluator **out, duoforge_eval_error *error)
{
#define FAIL(code, reason) do { status = dfi_eval_error(error, (code), "load", (reason)); goto done; } while (0)
    duoforge_status status = DUOFORGE_OK;
    if (path == NULL || expected == NULL || context == NULL || out == NULL) {
        return dfi_eval_error(error, DUOFORGE_E_NULL_ARGUMENT, "load", "eval_load_argument");
    }
    if (!dfi_absolute(path)) { return dfi_eval_error(error, DUOFORGE_E_INVALID_ARGUMENT, "load", "eval_private_absolute_path"); }
    if (version != 6u || (mask >> 47u) != 0u) {
        return dfi_eval_error(error, DUOFORGE_E_SCHEMA_MISMATCH, "load", "eval_encoder_mask");
    }
    FILE *stream = NULL;
#if defined(_MSC_VER)
    if (fopen_s(&stream, path, "rb") != 0) { stream = NULL; }
#else
    stream = fopen(path, "rb");
#endif
    uint8_t *bytes = NULL;
    duoforge_evaluator *model = NULL;
    if (stream == NULL) { FAIL(DUOFORGE_E_INVALID_ARGUMENT, "eval_file_open"); }
    const uint64_t cap = graph == NULL ? DFI_EVAL_FILE_MAX : graph->file_max;
    /* First pass measures and hashes the actual opened stream, bounded before
     * any model-sized allocation; no platform-dependent file-offset type. */
    uint8_t header[DFI_EVAL_HEADER_BYTES], chunk[4096], digest[32];
    dfi_sha256_state hash;
    dfi_sha256_init(&hash);
    size_t size = 0u;
    for (;;) {
        const size_t n = fread(chunk, 1u, sizeof chunk, stream);
        if ((uint64_t)n > cap || (uint64_t)size > cap - n ||
            (uint64_t)size + n > DFI_EVAL_FILE_MAX || size > SIZE_MAX - n) {
            FAIL(DUOFORGE_E_CAPACITY, "eval_file_capacity");
        }
        if (size < sizeof header) {
            const size_t first = n < sizeof header - size ? n : sizeof header - size;
            memcpy(header + size, chunk, first);
        }
        if (!dfi_sha256_update(&hash, chunk, n)) { FAIL(DUOFORGE_E_MALFORMED, "eval_file_read"); }
        size += n;
        if (n != sizeof chunk) { break; }
    }
    if (ferror(stream) || !dfi_sha256_final(&hash, digest)) { FAIL(DUOFORGE_E_MALFORMED, "eval_file_read"); }
    if (size < sizeof header) { FAIL(DUOFORGE_E_MALFORMED, "eval_header"); }
    if (!dfi_equal(digest, expected, 32u)) { FAIL(DUOFORGE_E_MALFORMED, "eval_file_sha256"); }
    /* Production registry is deliberately empty. No weight slab allocation. */
    if (graph == NULL) {
        status = dfi_validate(header, size, context, version, mask, NULL, error);
        goto done;
    }
    if (fseek(stream, 0, SEEK_SET) != 0) { FAIL(DUOFORGE_E_MALFORMED, "eval_file_seek"); }
    bytes = allocator->allocate(size, allocator->user);
    if (bytes == NULL) { FAIL(DUOFORGE_E_OUT_OF_MEMORY, "eval_file_allocation"); }
    if (fread(bytes, 1u, size, stream) != size || fgetc(stream) != EOF || ferror(stream)) {
        FAIL(DUOFORGE_E_MALFORMED, "eval_file_read");
    }
    if (!dfi_sha256(bytes, size, digest) || !dfi_equal(digest, expected, 32u)) {
        FAIL(DUOFORGE_E_MALFORMED, "eval_file_sha256");
    }
    status = dfi_validate(bytes, size, context, version, mask, graph, error);
    if (status != DUOFORGE_OK) { goto done; }
    model = allocator->allocate(sizeof *model, allocator->user);
    if (model == NULL) { FAIL(DUOFORGE_E_OUT_OF_MEMORY, "eval_model_allocation"); }
    memset(model, 0, sizeof *model);
    model->lifetime = allocator->allocate(sizeof *model->lifetime, allocator->user);
    if (model->lifetime == NULL) { FAIL(DUOFORGE_E_OUT_OF_MEMORY, "eval_lifetime_allocation"); }
    memset(model->lifetime, 0, sizeof *model->lifetime);
#if defined(_WIN32)
    InitializeSRWLock(&model->lifetime->lock);
#else
    if (pthread_mutex_init(&model->lifetime->lock, NULL) != 0) { FAIL(DUOFORGE_E_OUT_OF_MEMORY, "eval_model_lock"); }
#endif
    model->graph = graph;
    memcpy(model->sha256, digest, 32u);
    memcpy(model->context, context->fingerprint, 32u);
    model->file = bytes;
    model->file_bytes = size;
    model->allocator = *allocator;
    model->lifetime->references = 1u;
    model->lifetime->owner = model;
    bytes = NULL;
    *out = model;
    model = NULL;
    status = dfi_eval_error(error, DUOFORGE_OK, "load", "");
done:
    if (stream != NULL && fclose(stream) != 0 && status == DUOFORGE_OK) {
        /* An opened immutable snapshot is already verified; close errors do
         * not change its bytes or turn success into a half-published handle. */
    }
    if (bytes != NULL) { allocator->release(bytes, allocator->user); }
    if (model != NULL) {
        allocator->release(model->lifetime, allocator->user);
        allocator->release(model, allocator->user);
    }
    return status;
#undef FAIL
}
duoforge_status dfi_eval_load(const char *path, const uint8_t expected[32],
    const duoforge_context *context, uint32_t version, uint64_t mask,
    duoforge_evaluator **out, duoforge_eval_error *error)
{
    /* E3g installs explicit compiled registry lookup here, never a file graph. */
    return dfi_read(path, expected, context, version, mask, NULL, &dfi_default_allocator, out, error);
}
duoforge_status dfi_eval_load_descriptor(const char *path, const uint8_t expected[32],
    const duoforge_context *context, uint32_t version, uint64_t mask,
    const dfi_eval_graph *graph, const dfi_eval_allocator *allocator,
    duoforge_evaluator **out, duoforge_eval_error *error)
{
    if (graph == NULL || allocator == NULL || allocator->allocate == NULL || allocator->release == NULL ||
        graph->tensors == NULL || graph->file_max == 0u) {
        return dfi_eval_error(error, DUOFORGE_E_NULL_ARGUMENT, "load", "eval_descriptor_argument");
    }
    return dfi_read(path, expected, context, version, mask, graph, allocator, out, error);
}
void dfi_eval_model_release(const duoforge_evaluator *immutable)
{
    if (immutable == NULL) { return; }
    const duoforge_evaluator *model = immutable;
    dfi_error_lock_enter(&model->lifetime->lock);
    --model->lifetime->references;
    const bool last = model->lifetime->references == 0u;
    dfi_error_lock_leave(&model->lifetime->lock);
    if (last) {
        const dfi_eval_allocator allocator = model->allocator;
        allocator.release(model->file, allocator.user);
        dfi_error_lock_destroy(&model->lifetime->lock);
        void *owner = model->lifetime->owner;
        allocator.release(model->lifetime, allocator.user);
        allocator.release(owner, allocator.user);
    }
}
