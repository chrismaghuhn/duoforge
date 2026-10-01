#include "state/context_internal.h"

#include "codec/envelope.h"
#include "core/alloc.h"
#include "core/arith.h"
#include "core/bytes.h"
#include "core/sha256.h"
#include "data/closure_tables.h"

bool dfi_context_is_closure(const struct duoforge_context *ctx)
{
    return ctx->data_kind == DUOFORGE_DATA_KIND_CLOSURE || ctx->data_kind == DUOFORGE_DATA_KIND_CLOSURE_DEV;
}

void dfi_context_canonical_bytes(const struct duoforge_context *ctx, uint8_t out[DFI_CONTEXT_BYTES_SIZE])
{
    dfi_write_envelope(out, DFI_ARTIFACT_CONTEXT, (uint16_t)DUOFORGE_CONTEXT_SCHEMA_VERSION,
                       DUOFORGE_SEMANTICS_ID, DFI_CONTEXT_BYTES_SIZE);
    out[20] = (uint8_t)DUOFORGE_SIDE_COUNT;
    out[21] = (uint8_t)DUOFORGE_ACTIVE_PER_SIDE;
    out[22] = (uint8_t)DUOFORGE_MAX_ROSTER;
    out[23] = (uint8_t)DUOFORGE_MAX_MOVE_SLOTS;
    out[24] = ctx->data_kind;
    out[25] = ctx->max_roster;
    out[26] = ctx->brought_count;
    dfi_store_u16le(out + 27, ctx->species_count);
    dfi_store_u16le(out + 29, ctx->move_count);
    for (uint32_t i = 0u; i < DUOFORGE_DIGEST_SIZE; ++i) {
        out[DFI_CONTEXT_TABLE_HASH_OFF + i] = ctx->table_hash[i];
    }
}

bool dfi_context_fingerprint_matches(const struct duoforge_context *ctx,
                                     const uint8_t fingerprint[DUOFORGE_DIGEST_SIZE])
{
    return dfi_bytes_equal(ctx->fingerprint, fingerprint, DUOFORGE_DIGEST_SIZE);
}

duoforge_status duoforge_context_create(const duoforge_context_config *config,
                                        duoforge_context **out_context)
{
    if (config == NULL || out_context == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    const duoforge_context_config c = *config; /* read the input once */

    /* Validate on the u32 values before any narrowing. */
    const bool closure =
        c.data_kind == DUOFORGE_DATA_KIND_CLOSURE || c.data_kind == DUOFORGE_DATA_KIND_CLOSURE_DEV;
    if (c.data_kind != DUOFORGE_DATA_KIND_SYNTHETIC && !closure) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    if (c.max_roster < 1u || c.max_roster > DUOFORGE_MAX_ROSTER) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    if (c.brought_count < 1u || c.brought_count > c.max_roster) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    if (c.data_kind == DUOFORGE_DATA_KIND_CLOSURE &&
        (c.max_roster != DUOFORGE_MAX_ROSTER || c.brought_count != DFI_CLOSURE_BROUGHT_COUNT)) {
        return DUOFORGE_E_INVALID_ARGUMENT; /* the certified profile: register 6, bring 4 (decision 0010) */
    }
    if (closure) {
        /* The generated tables are built in: no counts, no table. */
        if (c.species_count != 0u || c.move_count != 0u || c.move_target_classes != NULL) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
    } else {
        if (c.species_count < 1u || c.species_count > UINT16_MAX) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
        if (c.move_count < 1u || c.move_count > UINT16_MAX) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
        if (c.move_target_classes == NULL) {
            return DUOFORGE_E_NULL_ARGUMENT;
        }
        /* The table is read exactly once, into the heap candidate below;
         * validate first so a rejected table never leaves an allocation
         * behind. */
        for (uint32_t i = 0u; i < c.move_count; ++i) {
            const uint32_t cls = c.move_target_classes[i];
            if (cls < 1u || cls > DUOFORGE_TARGET_CLASS_COUNT) {
                return DUOFORGE_E_INVALID_ARGUMENT;
            }
        }
    }

    struct duoforge_context *p = dfi_alloc_zeroed(sizeof *p);
    if (p == NULL) {
        return DUOFORGE_E_OUT_OF_MEMORY;
    }
    const uint32_t species_count = closure ? DFI_FORME_COUNT : c.species_count;
    const uint32_t move_count = closure ? DFI_MOVE_COUNT : c.move_count;
    if (!dfi_u32_to_u8(c.data_kind, &p->data_kind) || !dfi_u32_to_u8(c.max_roster, &p->max_roster) ||
        !dfi_u32_to_u8(c.brought_count, &p->brought_count) ||
        !dfi_u32_to_u16(species_count, &p->species_count) || !dfi_u32_to_u16(move_count, &p->move_count)) {
        dfi_free(p);
        return DUOFORGE_E_INVARIANT; /* unreachable after validation */
    }
    if (closure) {
        /* Target classes of the closure moves (Struggle's class 10 is never
         * selectable); the fingerprint covers all closure data by its hash. */
        for (uint32_t i = 0u; i < DFI_MOVE_COUNT; ++i) {
            p->move_target_classes[i] = dfi_closure_moves[i].target_class;
        }
        for (uint32_t i = 0u; i < DUOFORGE_DIGEST_SIZE; ++i) {
            p->table_hash[i] = dfi_closure_table_hash[i];
        }
    } else {
        for (uint32_t i = 0u; i < c.move_count; ++i) {
            p->move_target_classes[i] = c.move_target_classes[i];
        }
        if (!dfi_sha256(p->move_target_classes, (size_t)c.move_count, p->table_hash)) {
            dfi_free(p);
            return DUOFORGE_E_INVARIANT; /* unreachable: at most 65535 bytes */
        }
    }
    uint8_t canonical[DFI_CONTEXT_BYTES_SIZE] = {0};
    dfi_context_canonical_bytes(p, canonical);
    if (!dfi_sha256(canonical, sizeof canonical, p->fingerprint)) {
        dfi_free(p);
        return DUOFORGE_E_INVARIANT; /* unreachable: 63 bytes */
    }
    *out_context = p;
    return DUOFORGE_OK;
}

void duoforge_context_destroy(duoforge_context *context)
{
    dfi_free(context);
}

duoforge_status duoforge_context_fingerprint(const duoforge_context *context,
                                             uint8_t out_fingerprint[DUOFORGE_DIGEST_SIZE])
{
    if (context == NULL || out_fingerprint == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    for (uint32_t i = 0u; i < DUOFORGE_DIGEST_SIZE; ++i) {
        out_fingerprint[i] = context->fingerprint[i];
    }
    return DUOFORGE_OK;
}
