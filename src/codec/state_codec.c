#include "codec/state_codec.h"

#include <string.h>

#include "core/alloc.h"
#include "core/bytes.h"
#include "core/sha256.h"
#include "state/context_internal.h"

void dfi_encode_unchecked(const struct duoforge_battle *b, uint8_t out[DUOFORGE_STATE_V2_ENCODED_SIZE])
{
    dfi_write_envelope(out, DFI_ARTIFACT_BATTLE_STATE, (uint16_t)DUOFORGE_STATE_SCHEMA_VERSION,
                       DUOFORGE_SEMANTICS_ID, DUOFORGE_STATE_V2_ENCODED_SIZE);
    for (uint32_t i = 0u; i < DUOFORGE_DIGEST_SIZE; ++i) {
        out[DFI_ENC_FINGERPRINT_OFF + i] = b->context_fingerprint[i];
    }
    dfi_store_u64le(out + DFI_ENC_RNG_STATE_OFF, b->rng.state);
    dfi_store_u64le(out + DFI_ENC_RNG_INC_OFF, b->rng.inc);
    dfi_store_u64le(out + DFI_ENC_RNG_DRAWS_OFF, b->rng.draws);
    dfi_store_u32le(out + DFI_ENC_NEXT_ACTIVATION_OFF, b->next_activation_id);
    out[DFI_ENC_BOUNDARY_OFF] = b->boundary_kind;
    out[DFI_ENC_REQUEST_MASK_OFF] = b->request_mask;
    dfi_store_u32le(out + DFI_ENC_EPOCH_OFF, b->request_epoch);
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const dfi_side *side = &b->sides[s];
        uint8_t *so = out + DFI_ENC_SIDE_OFF + s * DFI_ENC_SIDE_SIZE;
        so[DFI_ENC_SIDE_MEMBER_COUNT_OFF] = side->member_count;
        so[DFI_ENC_SIDE_BROUGHT_OFF] = side->brought_mask;
        so[DFI_ENC_SIDE_REQUESTED_OFF] = side->requested_slots;
        so[DFI_ENC_SIDE_MEGA_USED_OFF] = side->mega_used;
        so[DFI_ENC_SIDE_SEALED_OFF] = side->sealed;
        so[DFI_ENC_SIDE_SEEN_OFF] = side->seen_mask;
        for (uint32_t i = 0u; i < DUOFORGE_MAX_ROSTER; ++i) {
            so[DFI_ENC_SIDE_ORDER_OFF + i] = side->brought_order[i];
        }
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            uint8_t *po = so + DFI_ENC_SIDE_POS_OFF + p * DFI_ENC_POS_SIZE;
            po[0] = side->positions[p].occupant;
            dfi_store_u32le(po + 1, side->positions[p].activation_id);
            uint8_t *co = so + DFI_ENC_SIDE_SEALED_CMD_OFF + p * DFI_ENC_CMD_SIZE;
            co[0] = side->sealed_cmds[p].kind;
            co[1] = side->sealed_cmds[p].move_slot;
            co[2] = side->sealed_cmds[p].target;
            co[3] = side->sealed_cmds[p].mega;
            co[4] = side->sealed_cmds[p].reserve;
        }
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            const dfi_member *mem = &side->members[m];
            uint8_t *mo = so + DFI_ENC_SIDE_MEMBERS_OFF + m * DFI_ENC_MEMBER_SIZE;
            dfi_store_u16le(mo + DFI_ENC_MEMBER_SPECIES_OFF, mem->species_id);
            dfi_store_u16le(mo + DFI_ENC_MEMBER_HP_OFF, mem->hp);
            dfi_store_u16le(mo + DFI_ENC_MEMBER_HP_MAX_OFF, mem->hp_max);
            mo[DFI_ENC_MEMBER_MOVE_COUNT_OFF] = mem->move_count;
            mo[DFI_ENC_MEMBER_MEGA_OFF] = mem->mega_capable;
            for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
                uint8_t *ko = mo + DFI_ENC_MOVE_OFF + k * DFI_ENC_MOVE_SIZE;
                dfi_store_u16le(ko, mem->moves[k].move_id);
                ko[2] = mem->moves[k].pp;
                ko[3] = mem->moves[k].pp_max;
            }
        }
    }
}

static void dfi_parse_state(const uint8_t *in, struct duoforge_battle *b)
{
    for (uint32_t i = 0u; i < DUOFORGE_DIGEST_SIZE; ++i) {
        b->context_fingerprint[i] = in[DFI_ENC_FINGERPRINT_OFF + i];
    }
    b->rng.state = dfi_load_u64le(in + DFI_ENC_RNG_STATE_OFF);
    b->rng.inc = dfi_load_u64le(in + DFI_ENC_RNG_INC_OFF);
    b->rng.draws = dfi_load_u64le(in + DFI_ENC_RNG_DRAWS_OFF);
    b->next_activation_id = dfi_load_u32le(in + DFI_ENC_NEXT_ACTIVATION_OFF);
    b->boundary_kind = in[DFI_ENC_BOUNDARY_OFF];
    b->request_mask = in[DFI_ENC_REQUEST_MASK_OFF];
    b->request_epoch = dfi_load_u32le(in + DFI_ENC_EPOCH_OFF);
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        dfi_side *side = &b->sides[s];
        const uint8_t *so = in + DFI_ENC_SIDE_OFF + s * DFI_ENC_SIDE_SIZE;
        side->member_count = so[DFI_ENC_SIDE_MEMBER_COUNT_OFF];
        side->brought_mask = so[DFI_ENC_SIDE_BROUGHT_OFF];
        side->requested_slots = so[DFI_ENC_SIDE_REQUESTED_OFF];
        side->mega_used = so[DFI_ENC_SIDE_MEGA_USED_OFF];
        side->sealed = so[DFI_ENC_SIDE_SEALED_OFF];
        side->seen_mask = so[DFI_ENC_SIDE_SEEN_OFF];
        for (uint32_t i = 0u; i < DUOFORGE_MAX_ROSTER; ++i) {
            side->brought_order[i] = so[DFI_ENC_SIDE_ORDER_OFF + i];
        }
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const uint8_t *po = so + DFI_ENC_SIDE_POS_OFF + p * DFI_ENC_POS_SIZE;
            side->positions[p].occupant = po[0];
            side->positions[p].activation_id = dfi_load_u32le(po + 1);
            const uint8_t *co = so + DFI_ENC_SIDE_SEALED_CMD_OFF + p * DFI_ENC_CMD_SIZE;
            side->sealed_cmds[p].kind = co[0];
            side->sealed_cmds[p].move_slot = co[1];
            side->sealed_cmds[p].target = co[2];
            side->sealed_cmds[p].mega = co[3];
            side->sealed_cmds[p].reserve = co[4];
        }
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            dfi_member *mem = &side->members[m];
            const uint8_t *mo = so + DFI_ENC_SIDE_MEMBERS_OFF + m * DFI_ENC_MEMBER_SIZE;
            mem->species_id = dfi_load_u16le(mo + DFI_ENC_MEMBER_SPECIES_OFF);
            mem->hp = dfi_load_u16le(mo + DFI_ENC_MEMBER_HP_OFF);
            mem->hp_max = dfi_load_u16le(mo + DFI_ENC_MEMBER_HP_MAX_OFF);
            mem->move_count = mo[DFI_ENC_MEMBER_MOVE_COUNT_OFF];
            mem->mega_capable = mo[DFI_ENC_MEMBER_MEGA_OFF];
            for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
                const uint8_t *ko = mo + DFI_ENC_MOVE_OFF + k * DFI_ENC_MOVE_SIZE;
                mem->moves[k].move_id = dfi_load_u16le(ko);
                mem->moves[k].pp = ko[2];
                mem->moves[k].pp_max = ko[3];
            }
        }
    }
}

duoforge_status dfi_decode_state(const duoforge_context *ctx, const uint8_t *bytes, size_t size,
                                 struct duoforge_battle *out, dfi_invariant *out_invariant)
{
    /* No byte at offset >= 20 is read before the size checks pass. */
    if (size < DFI_ENVELOPE_SIZE) {
        return DUOFORGE_E_MALFORMED;
    }
    if (!dfi_bytes_equal(bytes, dfi_envelope_magic, DFI_ENVELOPE_MAGIC_SIZE)) {
        return DUOFORGE_E_MALFORMED;
    }
    if (dfi_load_u16le(bytes + DFI_ENVELOPE_KIND_OFF) != DFI_ARTIFACT_BATTLE_STATE ||
        dfi_load_u16le(bytes + DFI_ENVELOPE_SCHEMA_OFF) != DUOFORGE_STATE_SCHEMA_VERSION) {
        return DUOFORGE_E_SCHEMA_MISMATCH;
    }
    if (dfi_load_u32le(bytes + DFI_ENVELOPE_SEMANTICS_OFF) != DUOFORGE_SEMANTICS_ID) {
        return DUOFORGE_E_SEMANTICS_MISMATCH;
    }
    /* size is never narrowed. */
    if ((uint64_t)dfi_load_u32le(bytes + DFI_ENVELOPE_LENGTH_OFF) != (uint64_t)size) {
        return DUOFORGE_E_MALFORMED;
    }
    if (size != DUOFORGE_STATE_V2_ENCODED_SIZE) {
        return DUOFORGE_E_MALFORMED;
    }
    if (!dfi_context_fingerprint_matches(ctx, bytes + DFI_ENC_FINGERPRINT_OFF)) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    struct duoforge_battle tmp;
    memset(&tmp, 0, sizeof tmp);
    dfi_parse_state(bytes, &tmp);
    dfi_invariant inv = DFI_INV_NONE;
    if (dfi_state_check(ctx, &tmp, &inv) != DUOFORGE_OK) {
        if (out_invariant != NULL) {
            *out_invariant = inv;
        }
        return DUOFORGE_E_MALFORMED;
    }
    *out = tmp;
    return DUOFORGE_OK;
}

duoforge_status duoforge_battle_create_decoded(const duoforge_context *ctx, const uint8_t *bytes,
                                               size_t size, duoforge_battle **out_battle)
{
    if (ctx == NULL || bytes == NULL || out_battle == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    struct duoforge_battle tmp;
    memset(&tmp, 0, sizeof tmp);
    const duoforge_status status = dfi_decode_state(ctx, bytes, size, &tmp, NULL);
    if (status != DUOFORGE_OK) {
        return status;
    }
    struct duoforge_battle *p = dfi_alloc_zeroed(sizeof *p);
    if (p == NULL) {
        return DUOFORGE_E_OUT_OF_MEMORY;
    }
    *p = tmp;
    *out_battle = p;
    return DUOFORGE_OK;
}

duoforge_status duoforge_battle_decode(const duoforge_context *ctx, duoforge_battle *dst,
                                       const uint8_t *bytes, size_t size)
{
    if (ctx == NULL || dst == NULL || bytes == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (!dfi_context_fingerprint_matches(ctx, dst->context_fingerprint)) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    struct duoforge_battle tmp;
    memset(&tmp, 0, sizeof tmp);
    const duoforge_status status = dfi_decode_state(ctx, bytes, size, &tmp, NULL);
    if (status != DUOFORGE_OK) {
        return status;
    }
    *dst = tmp;
    return DUOFORGE_OK;
}

duoforge_status duoforge_battle_equal(const duoforge_context *ctx, const duoforge_battle *a,
                                      const duoforge_battle *b, bool *out_equal)
{
    if (ctx == NULL || a == NULL || b == NULL || out_equal == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (!dfi_context_fingerprint_matches(ctx, a->context_fingerprint) ||
        !dfi_context_fingerprint_matches(ctx, b->context_fingerprint)) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    uint8_t ea[DUOFORGE_STATE_V2_ENCODED_SIZE] = {0};
    uint8_t eb[DUOFORGE_STATE_V2_ENCODED_SIZE] = {0};
    dfi_encode_unchecked(a, ea);
    dfi_encode_unchecked(b, eb);
    *out_equal = dfi_bytes_equal(ea, eb, DUOFORGE_STATE_V2_ENCODED_SIZE);
    return DUOFORGE_OK;
}

duoforge_status duoforge_battle_encoded_size(const duoforge_context *ctx, const duoforge_battle *battle,
                                             size_t *out_size)
{
    if (ctx == NULL || battle == NULL || out_size == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (!dfi_context_fingerprint_matches(ctx, battle->context_fingerprint)) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    *out_size = DUOFORGE_STATE_V2_ENCODED_SIZE;
    return DUOFORGE_OK;
}

duoforge_status duoforge_battle_encode(const duoforge_context *ctx, const duoforge_battle *battle,
                                       uint8_t *buffer, size_t capacity, size_t *out_written)
{
    if (ctx == NULL || battle == NULL || buffer == NULL || out_written == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    const duoforge_status status = dfi_state_check(ctx, battle, NULL);
    if (status != DUOFORGE_OK) {
        return status; /* CONTEXT_MISMATCH or INVARIANT */
    }
    if (capacity < DUOFORGE_STATE_V2_ENCODED_SIZE) {
        return DUOFORGE_E_CAPACITY;
    }
    dfi_encode_unchecked(battle, buffer);
    *out_written = DUOFORGE_STATE_V2_ENCODED_SIZE;
    return DUOFORGE_OK;
}

duoforge_status duoforge_battle_digest(const duoforge_context *ctx, const duoforge_battle *battle,
                                       uint8_t out_digest[DUOFORGE_DIGEST_SIZE])
{
    if (ctx == NULL || battle == NULL || out_digest == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    const duoforge_status status = dfi_state_check(ctx, battle, NULL);
    if (status != DUOFORGE_OK) {
        return status;
    }
    uint8_t encoded[DUOFORGE_STATE_V2_ENCODED_SIZE] = {0};
    uint8_t digest[DUOFORGE_DIGEST_SIZE] = {0};
    dfi_encode_unchecked(battle, encoded);
    if (!dfi_sha256(encoded, sizeof encoded, digest)) {
        return DUOFORGE_E_INVARIANT; /* unreachable: 438 bytes */
    }
    for (uint32_t i = 0u; i < DUOFORGE_DIGEST_SIZE; ++i) {
        out_digest[i] = digest[i];
    }
    return DUOFORGE_OK;
}
