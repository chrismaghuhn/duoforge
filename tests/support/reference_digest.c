#include "reference_digest.h"
#include <inttypes.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>

static void append(df_reference_digest *d, const char *format, ...)
{
    va_list args;
    va_start(args, format);
    va_list copy;
    va_copy(copy, args);
    const int needed = vsnprintf(NULL, 0u, format, copy);
    va_end(copy);
    if (needed < 0 || d->length > SIZE_MAX - (size_t)needed - 1u) {
        fputs("reference digest: encoding failed\n", stderr);
        exit(2);
    }
    const size_t size = d->length + (size_t)needed + 1u;
    if (size > d->capacity) {
        size_t capacity = d->capacity == 0u ? 4096u : d->capacity;
        while (capacity < size) {
            if (capacity > SIZE_MAX / 2u) {
                capacity = size;
                break;
            }
            capacity *= 2u;
        }
        char *bytes = realloc(d->bytes, capacity);
        if (bytes == NULL) {
            fputs("reference digest: out of memory\n", stderr);
            exit(2);
        }
        d->bytes = bytes;
        d->capacity = capacity;
    }
    (void)vsnprintf(d->bytes + d->length, d->capacity - d->length, format, args);
    va_end(args);
    d->length += (size_t)needed;
}

static void number(df_reference_digest *d, uint64_t value)
{
    append(d, "%" PRIu64 " ", value);
}

static void state(df_reference_digest *d, const duoforge_context *ctx, const duoforge_battle *b)
{
    uint8_t digest[DUOFORGE_DIGEST_SIZE];
    if (duoforge_battle_digest(ctx, b, digest) != DUOFORGE_OK) {
        fputs("reference digest: state query failed\n", stderr);
        exit(2);
    }
    append(d, "state ");
    for (unsigned i = 0u; i < sizeof digest; ++i) {
        append(d, "%02x", digest[i]);
    }
    append(d, "\n");
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        duoforge_request r = {0};
        const duoforge_status status = duoforge_battle_request(ctx, b, side, &r);
        append(d, "request ");
        number(d, side);
        number(d, status);
        if (status == DUOFORGE_OK) {
            number(d, r.epoch);
            number(d, r.candidate_count);
            number(d, r.boundary_kind);
            number(d, r.player);
            number(d, r.requested);
            number(d, r.slot_mask);
        }
        append(d, "\n");
    }
}

bool df_reference_digest_open(df_reference_digest *d, int argc, char **argv)
{
    memset(d, 0, sizeof *d);
    if (argc == 1) {
        return true;
    }
    if (argc != 3 || strcmp(argv[1], "--digest-out") != 0) {
        fprintf(stderr, "usage: %s [--digest-out <file>]\n", argv[0]);
        return false;
    }
    d->out = fopen(argv[2], "wb");
    if (d->out == NULL) {
        fprintf(stderr, "reference digest: cannot open %s\n", argv[2]);
        return false;
    }
    return true;
}

void df_reference_digest_begin(df_reference_digest *d, const char *name,
                               const duoforge_context *ctx, const duoforge_battle *b)
{
    if (d->out == NULL) {
        return;
    }
    d->name = name;
    d->length = 0u;
    d->steps = 0u;
    d->stops = 0u;
    state(d, ctx, b);
}

void df_reference_digest_step(df_reference_digest *d, const duoforge_context *ctx,
                              const duoforge_battle *b, uint32_t used, const duoforge_step_result *r)
{
    if (d->out == NULL) {
        return;
    }
    append(d, "step ");
    number(d, used);
    number(d, r->epoch);
    number(d, r->kind);
    number(d, r->boundary_kind);
    number(d, r->request_mask);
    number(d, r->reserved);
    append(d, "\n");
    state(d, ctx, b);
    ++d->steps;
}

void df_reference_digest_events(df_reference_digest *d, const duoforge_event_buffer *buffers)
{
    if (d->out == NULL) {
        return;
    }
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        append(d, "events ");
        number(d, side);
        number(d, buffers[side].count);
        append(d, "\n");
        for (uint32_t i = 0u; i < buffers[side].count; ++i) {
            const duoforge_event *e = &buffers[side].events[i];
            number(d, e->kind);
            number(d, e->position);
            number(d, e->other);
            number(d, e->cause);
            number(d, e->id);
            number(d, e->id2);
            number(d, e->hp);
            number(d, e->hp_max);
            number(d, e->hp_kind);
            number(d, e->hp_flag);
            number(d, e->status);
            number(d, e->detail);
            number(d, e->amount);
            number(d, e->flags);
            number(d, e->reserved[0]);
            number(d, e->reserved[1]);
            append(d, "\n");
        }
    }
}

void df_reference_digest_tiebreak(df_reference_digest *d, uint32_t prefix, bool ended,
                                  const dfi_tiebreak_report *r, duoforge_status rs,
                                  duoforge_status ps, uint32_t out)
{
    if (d->out == NULL) {
        return;
    }
    append(d, "tiebreak ");
    number(d, prefix);
    number(d, rs);
    number(d, ps);
    number(d, out);
    if (rs == DUOFORGE_OK) {
        number(d, r->result);
        number(d, r->result_mask);
        if (!ended) {
            for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
                number(d, r->not_fainted[side]);
                number(d, r->hp_total[side]);
                number(d, r->pct_count[side]);
                for (uint32_t i = 0u; i < r->pct_count[side]; ++i) {
                    number(d, r->pct_bits[side][i]);
                }
            }
        }
    }
    append(d, "\n");
    ++d->stops;
}

void df_reference_digest_end(df_reference_digest *d)
{
    if (d->out == NULL) {
        return;
    }
    uint8_t digest[DFI_SHA256_SIZE];
    if (!dfi_sha256((const uint8_t *)d->bytes, d->length, digest)) {
        fputs("reference digest: SHA-256 failed\n", stderr);
        exit(2);
    }
    (void)fprintf(d->out, "%s\t", d->name);
    for (unsigned i = 0u; i < sizeof digest; ++i) {
        (void)fprintf(d->out, "%02x", digest[i]);
    }
    (void)fprintf(d->out, "\t%u\t%u\n", d->steps, d->stops);
}

bool df_reference_digest_close(df_reference_digest *d)
{
    free(d->bytes);
    bool ok = true;
    if (d->out != NULL) {
        ok = ferror(d->out) == 0;
        if (fclose(d->out) != 0) {
            ok = false;
        }
    }
    memset(d, 0, sizeof *d);
    return ok;
}
