#include "state/context_internal.h"

#include "codec/envelope.h"
#include "core/alloc.h"
#include "core/arith.h"
#include "core/bytes.h"
#include "core/sha256.h"

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
    if (c.data_kind != DUOFORGE_DATA_KIND_SYNTHETIC) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    if (c.max_roster < 1u || c.max_roster > DUOFORGE_MAX_ROSTER) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    if (c.brought_count < 1u || c.brought_count > c.max_roster) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    if (c.species_count < 1u || c.species_count > UINT16_MAX) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    if (c.move_count < 1u || c.move_count > UINT16_MAX) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }

    struct duoforge_context tmp = {0};
    if (!dfi_u32_to_u8(c.data_kind, &tmp.data_kind) || !dfi_u32_to_u8(c.max_roster, &tmp.max_roster) ||
        !dfi_u32_to_u8(c.brought_count, &tmp.brought_count) ||
        !dfi_u32_to_u16(c.species_count, &tmp.species_count) ||
        !dfi_u32_to_u16(c.move_count, &tmp.move_count)) {
        return DUOFORGE_E_INVARIANT; /* unreachable after validation */
    }
    uint8_t canonical[DFI_CONTEXT_BYTES_SIZE] = {0};
    dfi_context_canonical_bytes(&tmp, canonical);
    if (!dfi_sha256(canonical, sizeof canonical, tmp.fingerprint)) {
        return DUOFORGE_E_INVARIANT; /* unreachable: 31 bytes */
    }

    struct duoforge_context *p = dfi_alloc_zeroed(sizeof *p);
    if (p == NULL) {
        return DUOFORGE_E_OUT_OF_MEMORY;
    }
    *p = tmp;
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
