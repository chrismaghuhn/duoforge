#include "codec/state_codec.h"

#include <string.h>

#include "core/alloc.h"
#include "core/bytes.h"
#include "core/sha256.h"
#include "state/context_internal.h"

bool dfi_context_has_pool_tail(const struct duoforge_context *ctx)
{
    return ctx->data_kind == DUOFORGE_DATA_KIND_POOL || ctx->data_kind == DUOFORGE_DATA_KIND_POOL_DEV;
}

uint16_t dfi_state_schema_of(const struct duoforge_context *ctx)
{
    return dfi_context_has_pool_tail(ctx) ? (uint16_t)DFI_STATE_SCHEMA_POOL_TAIL_REV1 : (uint16_t)DFI_STATE_SCHEMA_V3;
}

size_t dfi_state_encoded_size_of(const struct duoforge_context *ctx)
{
    return dfi_context_has_pool_tail(ctx) ? (size_t)DFI_STATE_POOL_ENCODED_SIZE : (size_t)DUOFORGE_STATE_V3_ENCODED_SIZE;
}

/* The tail of the POOL kinds, byte by byte, with the reserved bytes zero. */
static void dfi_encode_tail(const dfi_pool_tail *tail, uint8_t *out)
{
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const dfi_tail_side *ts = &tail->sides[s];
        uint8_t *so = out + s * DFI_ENC_TAIL_SIDE_SIZE;
        so[DFI_ENC_TAIL_WIDE_GUARD_OFF] = ts->wide_guard;
        for (uint32_t i = 0u; i < DFI_ENC_TAIL_SIDE_RESERVED_SIZE; ++i) {
            so[DFI_ENC_TAIL_SIDE_RESERVED_OFF + i] = 0u;
        }
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const dfi_tail_pos *tp = &ts->positions[p];
            uint8_t *po = so + DFI_ENC_TAIL_POS_OFF + p * DFI_ENC_TAIL_POS_SIZE;
            po[DFI_ENC_TAIL_POS_LAST_MOVE_OFF] = tp->last_move;
            po[DFI_ENC_TAIL_POS_ENCORE_SLOT_OFF] = tp->encore_slot;
            po[DFI_ENC_TAIL_POS_ENCORE_TURNS_OFF] = tp->encore_turns;
            po[DFI_ENC_TAIL_POS_THROAT_CHOP_OFF] = tp->throat_chop_turns;
            po[DFI_ENC_TAIL_POS_HEAL_BLOCK_OFF] = tp->heal_block_turns;
            po[DFI_ENC_TAIL_POS_RESERVED_OFF] = 0u;
        }
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            so[DFI_ENC_TAIL_SOAK_OFF + m] = ts->soak_type[m];
        }
    }
}

/* True iff the reserved bytes of an encoded tail are all zero (bounded loops, no stored index). */
static bool dfi_tail_reserved_zero(const uint8_t *in)
{
    uint32_t any = 0u;
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const uint8_t *so = in + s * DFI_ENC_TAIL_SIDE_SIZE;
        for (uint32_t i = 0u; i < DFI_ENC_TAIL_SIDE_RESERVED_SIZE; ++i) {
            any |= so[DFI_ENC_TAIL_SIDE_RESERVED_OFF + i];
        }
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            any |= so[DFI_ENC_TAIL_POS_OFF + p * DFI_ENC_TAIL_POS_SIZE + DFI_ENC_TAIL_POS_RESERVED_OFF];
        }
    }
    return any == 0u;
}

static void dfi_parse_tail(const uint8_t *in, dfi_pool_tail *tail)
{
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        dfi_tail_side *ts = &tail->sides[s];
        const uint8_t *so = in + s * DFI_ENC_TAIL_SIDE_SIZE;
        ts->wide_guard = so[DFI_ENC_TAIL_WIDE_GUARD_OFF];
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            dfi_tail_pos *tp = &ts->positions[p];
            const uint8_t *po = so + DFI_ENC_TAIL_POS_OFF + p * DFI_ENC_TAIL_POS_SIZE;
            tp->last_move = po[DFI_ENC_TAIL_POS_LAST_MOVE_OFF];
            tp->encore_slot = po[DFI_ENC_TAIL_POS_ENCORE_SLOT_OFF];
            tp->encore_turns = po[DFI_ENC_TAIL_POS_ENCORE_TURNS_OFF];
            tp->throat_chop_turns = po[DFI_ENC_TAIL_POS_THROAT_CHOP_OFF];
            tp->heal_block_turns = po[DFI_ENC_TAIL_POS_HEAL_BLOCK_OFF];
        }
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            ts->soak_type[m] = so[DFI_ENC_TAIL_SOAK_OFF + m];
        }
    }
}

size_t dfi_encode_unchecked(const struct duoforge_context *ctx, const struct duoforge_battle *b, uint8_t *out)
{
    const size_t size = dfi_state_encoded_size_of(ctx);
    dfi_write_envelope(out, DFI_ARTIFACT_BATTLE_STATE, dfi_state_schema_of(ctx), DUOFORGE_SEMANTICS_ID,
                       (uint32_t)size);
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
    dfi_store_u16le(out + DFI_ENC_TURN_OFF, b->turn);
    out[DFI_ENC_RESULT_OFF] = b->result;
    out[DFI_ENC_WEATHER_OFF] = b->weather;
    out[DFI_ENC_WEATHER_TURNS_OFF] = b->weather_turns;
    out[DFI_ENC_TERRAIN_OFF] = b->terrain;
    out[DFI_ENC_TERRAIN_TURNS_OFF] = b->terrain_turns;
    out[DFI_ENC_TRICK_ROOM_OFF] = b->trick_room_turns;
    out[DFI_ENC_QUEUE_LEN_OFF] = b->queue_len;
    for (uint32_t i = 0u; i < DFI_QUEUE_CAPACITY; ++i) {
        const dfi_queue_record *r = &b->queue[i];
        uint8_t *qo = out + DFI_ENC_QUEUE_OFF + i * DFI_ENC_QUEUE_RECORD_SIZE;
        qo[0] = r->kind;
        qo[1] = r->side;
        qo[2] = r->slot;
        qo[3] = r->move_slot;
        qo[4] = r->target;
        qo[5] = r->reserve;
        dfi_store_u32le(qo + DFI_ENC_QUEUE_ACTIVATION_OFF, r->activation_id);
    }
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
        so[DFI_ENC_SIDE_REFLECT_OFF] = side->reflect_turns;
        so[DFI_ENC_SIDE_LIGHT_SCREEN_OFF] = side->light_screen_turns;
        so[DFI_ENC_SIDE_TAILWIND_OFF] = side->tailwind_turns;
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const dfi_active_slot *slot = &side->positions[p];
            uint8_t *po = so + DFI_ENC_SIDE_POS_OFF + p * DFI_ENC_POS_SIZE;
            po[0] = slot->occupant;
            dfi_store_u32le(po + DFI_ENC_POS_ACTIVATION_OFF, slot->activation_id);
            for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
                po[DFI_ENC_POS_STAGES_OFF + i] = slot->stages[i];
            }
            po[DFI_ENC_POS_FLAGS_OFF] = slot->flags;
            po[DFI_ENC_POS_STALL_LEVEL_OFF] = slot->stall_level;
            po[DFI_ENC_POS_STALL_TURNS_OFF] = slot->stall_turns;
            po[DFI_ENC_POS_CONFUSION_OFF] = slot->confusion_turns;
            po[DFI_ENC_POS_CHARGE_OFF] = slot->charge_turns;
            po[DFI_ENC_POS_LOCKED_MOVE_OFF] = slot->locked_move;
            po[DFI_ENC_POS_LOCKED_TARGET_OFF] = slot->locked_target;
            po[DFI_ENC_POS_MOVE_ACTIONS_OFF] = slot->move_actions;
            po[DFI_ENC_POS_SWITCH_FLAG_OFF] = slot->switch_flag;
            uint8_t *co = so + DFI_ENC_SIDE_SEALED_CMD_OFF + p * DFI_ENC_CMD_SIZE;
            co[0] = side->sealed_cmds[p].kind;
            co[1] = side->sealed_cmds[p].move_slot;
            co[2] = side->sealed_cmds[p].target;
            co[3] = side->sealed_cmds[p].mega;
            co[4] = side->sealed_cmds[p].reserve;
        }
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            const dfi_knowledge *know = &side->knowledge[m];
            uint8_t *ko = so + DFI_ENC_SIDE_KNOWLEDGE_OFF + m * DFI_ENC_KNOWLEDGE_SIZE;
            ko[0] = know->hp_percent;
            ko[1] = know->hp_flag;
            ko[2] = know->revealed;
            for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
                ko[DFI_ENC_KNOWLEDGE_USED_OFF + k] = know->moves_used[k];
            }
        }
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            const dfi_member *mem = &side->members[m];
            uint8_t *mo = so + DFI_ENC_SIDE_MEMBERS_OFF + m * DFI_ENC_MEMBER_SIZE;
            dfi_store_u16le(mo + DFI_ENC_MEMBER_SPECIES_OFF, mem->species_id);
            dfi_store_u16le(mo + DFI_ENC_MEMBER_HP_OFF, mem->hp);
            dfi_store_u16le(mo + DFI_ENC_MEMBER_HP_MAX_OFF, mem->hp_max);
            for (uint32_t i = 0u; i < DFI_MEMBER_STAT_COUNT; ++i) {
                dfi_store_u16le(mo + DFI_ENC_MEMBER_STATS_OFF + 2u * i, mem->stats[i]);
            }
            mo[DFI_ENC_MEMBER_MOVE_COUNT_OFF] = mem->move_count;
            mo[DFI_ENC_MEMBER_MEGA_OFF] = mem->mega_capable;
            mo[DFI_ENC_MEMBER_IS_MEGA_OFF] = mem->is_mega;
            mo[DFI_ENC_MEMBER_GENDER_OFF] = mem->gender;
            mo[DFI_ENC_MEMBER_NATURE_OFF] = mem->nature;
            for (uint32_t i = 0u; i < DFI_STAT_POINT_COUNT; ++i) {
                mo[DFI_ENC_MEMBER_STAT_POINTS_OFF + i] = mem->stat_points[i];
            }
            mo[DFI_ENC_MEMBER_STATUS_OFF] = mem->status;
            mo[DFI_ENC_MEMBER_STATUS_COUNTER_OFF] = mem->status_counter;
            mo[DFI_ENC_MEMBER_ITEM_OFF] = mem->item;
            mo[DFI_ENC_MEMBER_ITEM_CONSUMED_OFF] = mem->item_consumed;
            mo[DFI_ENC_MEMBER_ABILITY_OFF] = mem->ability;
            for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
                uint8_t *ko = mo + DFI_ENC_MOVE_OFF + k * DFI_ENC_MOVE_SIZE;
                dfi_store_u16le(ko, mem->moves[k].move_id);
                ko[2] = mem->moves[k].pp;
                ko[3] = mem->moves[k].pp_max;
            }
        }
    }
    if (dfi_context_has_pool_tail(ctx)) {
        dfi_encode_tail(&b->tail, out + DFI_ENC_TAIL_OFF);
    }
    return size;
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
    b->turn = dfi_load_u16le(in + DFI_ENC_TURN_OFF);
    b->result = in[DFI_ENC_RESULT_OFF];
    b->weather = in[DFI_ENC_WEATHER_OFF];
    b->weather_turns = in[DFI_ENC_WEATHER_TURNS_OFF];
    b->terrain = in[DFI_ENC_TERRAIN_OFF];
    b->terrain_turns = in[DFI_ENC_TERRAIN_TURNS_OFF];
    b->trick_room_turns = in[DFI_ENC_TRICK_ROOM_OFF];
    b->queue_len = in[DFI_ENC_QUEUE_LEN_OFF];
    for (uint32_t i = 0u; i < DFI_QUEUE_CAPACITY; ++i) {
        dfi_queue_record *r = &b->queue[i];
        const uint8_t *qo = in + DFI_ENC_QUEUE_OFF + i * DFI_ENC_QUEUE_RECORD_SIZE;
        r->kind = qo[0];
        r->side = qo[1];
        r->slot = qo[2];
        r->move_slot = qo[3];
        r->target = qo[4];
        r->reserve = qo[5];
        r->activation_id = dfi_load_u32le(qo + DFI_ENC_QUEUE_ACTIVATION_OFF);
    }
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
        side->reflect_turns = so[DFI_ENC_SIDE_REFLECT_OFF];
        side->light_screen_turns = so[DFI_ENC_SIDE_LIGHT_SCREEN_OFF];
        side->tailwind_turns = so[DFI_ENC_SIDE_TAILWIND_OFF];
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            dfi_active_slot *slot = &side->positions[p];
            const uint8_t *po = so + DFI_ENC_SIDE_POS_OFF + p * DFI_ENC_POS_SIZE;
            slot->occupant = po[0];
            slot->activation_id = dfi_load_u32le(po + DFI_ENC_POS_ACTIVATION_OFF);
            for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
                slot->stages[i] = po[DFI_ENC_POS_STAGES_OFF + i];
            }
            slot->flags = po[DFI_ENC_POS_FLAGS_OFF];
            slot->stall_level = po[DFI_ENC_POS_STALL_LEVEL_OFF];
            slot->stall_turns = po[DFI_ENC_POS_STALL_TURNS_OFF];
            slot->confusion_turns = po[DFI_ENC_POS_CONFUSION_OFF];
            slot->charge_turns = po[DFI_ENC_POS_CHARGE_OFF];
            slot->locked_move = po[DFI_ENC_POS_LOCKED_MOVE_OFF];
            slot->locked_target = po[DFI_ENC_POS_LOCKED_TARGET_OFF];
            slot->move_actions = po[DFI_ENC_POS_MOVE_ACTIONS_OFF];
            slot->switch_flag = po[DFI_ENC_POS_SWITCH_FLAG_OFF];
            const uint8_t *co = so + DFI_ENC_SIDE_SEALED_CMD_OFF + p * DFI_ENC_CMD_SIZE;
            side->sealed_cmds[p].kind = co[0];
            side->sealed_cmds[p].move_slot = co[1];
            side->sealed_cmds[p].target = co[2];
            side->sealed_cmds[p].mega = co[3];
            side->sealed_cmds[p].reserve = co[4];
        }
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            dfi_knowledge *know = &side->knowledge[m];
            const uint8_t *ko = so + DFI_ENC_SIDE_KNOWLEDGE_OFF + m * DFI_ENC_KNOWLEDGE_SIZE;
            know->hp_percent = ko[0];
            know->hp_flag = ko[1];
            know->revealed = ko[2];
            for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
                know->moves_used[k] = ko[DFI_ENC_KNOWLEDGE_USED_OFF + k];
            }
        }
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            dfi_member *mem = &side->members[m];
            const uint8_t *mo = so + DFI_ENC_SIDE_MEMBERS_OFF + m * DFI_ENC_MEMBER_SIZE;
            mem->species_id = dfi_load_u16le(mo + DFI_ENC_MEMBER_SPECIES_OFF);
            mem->hp = dfi_load_u16le(mo + DFI_ENC_MEMBER_HP_OFF);
            mem->hp_max = dfi_load_u16le(mo + DFI_ENC_MEMBER_HP_MAX_OFF);
            for (uint32_t i = 0u; i < DFI_MEMBER_STAT_COUNT; ++i) {
                mem->stats[i] = dfi_load_u16le(mo + DFI_ENC_MEMBER_STATS_OFF + 2u * i);
            }
            mem->move_count = mo[DFI_ENC_MEMBER_MOVE_COUNT_OFF];
            mem->mega_capable = mo[DFI_ENC_MEMBER_MEGA_OFF];
            mem->is_mega = mo[DFI_ENC_MEMBER_IS_MEGA_OFF];
            mem->gender = mo[DFI_ENC_MEMBER_GENDER_OFF];
            mem->nature = mo[DFI_ENC_MEMBER_NATURE_OFF];
            for (uint32_t i = 0u; i < DFI_STAT_POINT_COUNT; ++i) {
                mem->stat_points[i] = mo[DFI_ENC_MEMBER_STAT_POINTS_OFF + i];
            }
            mem->status = mo[DFI_ENC_MEMBER_STATUS_OFF];
            mem->status_counter = mo[DFI_ENC_MEMBER_STATUS_COUNTER_OFF];
            mem->item = mo[DFI_ENC_MEMBER_ITEM_OFF];
            mem->item_consumed = mo[DFI_ENC_MEMBER_ITEM_CONSUMED_OFF];
            mem->ability = mo[DFI_ENC_MEMBER_ABILITY_OFF];
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
    /* The two schemas of this build: v3 and v3 + pool tail rev 1. Which one a context takes is decided below. */
    const uint32_t schema = dfi_load_u16le(bytes + DFI_ENVELOPE_SCHEMA_OFF);
    if (dfi_load_u16le(bytes + DFI_ENVELOPE_KIND_OFF) != DFI_ARTIFACT_BATTLE_STATE ||
        (schema != DFI_STATE_SCHEMA_V3 && schema != DFI_STATE_SCHEMA_POOL_TAIL_REV1)) {
        return DUOFORGE_E_SCHEMA_MISMATCH;
    }
    if (dfi_load_u32le(bytes + DFI_ENVELOPE_SEMANTICS_OFF) != DUOFORGE_SEMANTICS_ID) {
        return DUOFORGE_E_SEMANTICS_MISMATCH;
    }
    /* size is never narrowed. */
    if ((uint64_t)dfi_load_u32le(bytes + DFI_ENVELOPE_LENGTH_OFF) != (uint64_t)size) {
        return DUOFORGE_E_MALFORMED;
    }
    const bool tailed = schema == DFI_STATE_SCHEMA_POOL_TAIL_REV1;
    if (size != (tailed ? (size_t)DFI_STATE_POOL_ENCODED_SIZE : (size_t)DUOFORGE_STATE_V3_ENCODED_SIZE)) {
        return DUOFORGE_E_MALFORMED;
    }
    if (!dfi_context_fingerprint_matches(ctx, bytes + DFI_ENC_FINGERPRINT_OFF)) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    /* The schema of the artifact is the one of the context's kind: the POOL kinds carry the tail and no other
     * kind does. A disagreement, or a reserved byte of the tail that is not zero, is an invariant. */
    dfi_invariant inv = DFI_INV_NONE;
    if (tailed != dfi_context_has_pool_tail(ctx)) {
        inv = DFI_INV_TAIL_SCHEMA;
    } else if (tailed && !dfi_tail_reserved_zero(bytes + DFI_ENC_TAIL_OFF)) {
        inv = DFI_INV_TAIL_RESERVED;
    }
    if (inv != DFI_INV_NONE) {
        if (out_invariant != NULL) {
            *out_invariant = inv;
        }
        return DUOFORGE_E_MALFORMED;
    }
    struct duoforge_battle tmp;
    memset(&tmp, 0, sizeof tmp);
    dfi_parse_state(bytes, &tmp);
    if (tailed) {
        dfi_parse_tail(bytes + DFI_ENC_TAIL_OFF, &tmp.tail);
    }
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
    uint8_t ea[DFI_STATE_ENCODED_MAX] = {0};
    uint8_t eb[DFI_STATE_ENCODED_MAX] = {0};
    const size_t size = dfi_encode_unchecked(ctx, a, ea);
    (void)dfi_encode_unchecked(ctx, b, eb);
    *out_equal = dfi_bytes_equal(ea, eb, size);
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
    *out_size = dfi_state_encoded_size_of(ctx);
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
    if (capacity < dfi_state_encoded_size_of(ctx)) {
        return DUOFORGE_E_CAPACITY;
    }
    *out_written = dfi_encode_unchecked(ctx, battle, buffer);
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
    uint8_t encoded[DFI_STATE_ENCODED_MAX] = {0};
    uint8_t digest[DUOFORGE_DIGEST_SIZE] = {0};
    const size_t size = dfi_encode_unchecked(ctx, battle, encoded);
    if (!dfi_sha256(encoded, size, digest)) {
        return DUOFORGE_E_INVARIANT; /* unreachable: at most 1051 bytes */
    }
    for (uint32_t i = 0u; i < DUOFORGE_DIGEST_SIZE; ++i) {
        out_digest[i] = digest[i];
    }
    return DUOFORGE_OK;
}
