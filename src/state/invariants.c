#include "state/invariants.h"

#include "core/arith.h"
#include "state/context_internal.h"

static bool dfi_move_slot_is_zero(const dfi_move_slot *mv)
{
    return mv->move_id == 0u && mv->pp == 0u && mv->pp_max == 0u;
}

static bool dfi_member_is_zero(const dfi_member *m)
{
    if (m->species_id != 0u || m->hp != 0u || m->hp_max != 0u || m->move_count != 0u) {
        return false;
    }
    for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        if (!dfi_move_slot_is_zero(&m->moves[k])) {
            return false;
        }
    }
    return true;
}

static dfi_invariant dfi_check_member(const struct duoforge_context *ctx, const dfi_member *m)
{
    if (m->species_id >= ctx->species_count) {
        return DFI_INV_SPECIES_RANGE;
    }
    if (m->hp_max == 0u) {
        return DFI_INV_HP_MAX_ZERO;
    }
    if (m->hp > m->hp_max) {
        return DFI_INV_HP_ABOVE_MAX;
    }
    const uint32_t move_count = m->move_count;
    if (move_count < 1u || move_count > DUOFORGE_MAX_MOVE_SLOTS) {
        return DFI_INV_MOVE_COUNT;
    }
    for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        const dfi_move_slot *mv = &m->moves[k];
        if (k < move_count) {
            if (mv->move_id >= ctx->move_count) {
                return DFI_INV_MOVE_ID_RANGE;
            }
            if (mv->pp_max == 0u) {
                return DFI_INV_PP_MAX_ZERO;
            }
            if (mv->pp > mv->pp_max) {
                return DFI_INV_PP_ABOVE_MAX;
            }
        } else if (!dfi_move_slot_is_zero(mv)) {
            return DFI_INV_UNUSED_MOVE_NONZERO;
        }
    }
    return DFI_INV_NONE;
}

static dfi_invariant dfi_check_side(const struct duoforge_context *ctx, const dfi_side *side,
                                    uint32_t next_activation_id)
{
    /* Range-check member_count first: it bounds every later index/shift. */
    const uint32_t member_count = side->member_count;
    if (member_count < ctx->brought_count || member_count > ctx->max_roster) {
        return DFI_INV_MEMBER_COUNT;
    }
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        if (m < member_count) {
            const dfi_invariant inv = dfi_check_member(ctx, &side->members[m]);
            if (inv != DFI_INV_NONE) {
                return inv;
            }
        } else if (!dfi_member_is_zero(&side->members[m])) {
            return DFI_INV_UNUSED_MEMBER_NONZERO;
        }
    }
    const uint32_t mask = side->brought_mask;
    if ((mask >> member_count) != 0u) { /* member_count <= 6 here */
        return DFI_INV_BROUGHT_OUT_OF_RANGE;
    }
    if (dfi_popcount8(side->brought_mask) != ctx->brought_count) {
        return DFI_INV_BROUGHT_COUNT;
    }
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        const dfi_active_slot *slot = &side->positions[p];
        const uint32_t occupant = slot->occupant;
        if (occupant == DFI_OCCUPANT_NONE) {
            if (slot->activation_id != 0u) {
                return DFI_INV_EMPTY_WITH_ACTIVATION;
            }
            continue;
        }
        if (slot->activation_id == 0u) {
            return DFI_INV_OCCUPIED_WITHOUT_ACTIVATION;
        }
        if (occupant >= member_count) { /* before the bit test */
            return DFI_INV_OCCUPANT_RANGE;
        }
        if (((mask >> occupant) & 1u) == 0u) {
            return DFI_INV_OCCUPANT_NOT_BROUGHT;
        }
        if (slot->activation_id >= next_activation_id) {
            return DFI_INV_ACTIVATION_NOT_ISSUED;
        }
    }
    if (side->positions[0].occupant != DFI_OCCUPANT_NONE &&
        side->positions[0].occupant == side->positions[1].occupant) {
        return DFI_INV_OCCUPANT_DUPLICATE;
    }
    return DFI_INV_NONE;
}

duoforge_status dfi_state_check(const duoforge_context *ctx, const struct duoforge_battle *b,
                                dfi_invariant *out_first)
{
    dfi_invariant inv = DFI_INV_NONE;
    if (!dfi_context_fingerprint_matches(ctx, b->context_fingerprint)) {
        if (out_first != NULL) {
            *out_first = DFI_INV_CONTEXT_FINGERPRINT;
        }
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    if (!dfi_rng_is_valid(&b->rng)) {
        inv = DFI_INV_RNG_INC_EVEN;
    } else if (b->next_activation_id == 0u) {
        inv = DFI_INV_NEXT_ACTIVATION_ZERO;
    } else {
        for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT && inv == DFI_INV_NONE; ++s) {
            inv = dfi_check_side(ctx, &b->sides[s], b->next_activation_id);
        }
    }
    if (inv == DFI_INV_NONE) {
        /* Activation ids of occupied positions are unique battle-wide. */
        uint32_t ids[DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE] = {0};
        uint32_t n = 0u;
        for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
            for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
                if (b->sides[s].positions[p].occupant != DFI_OCCUPANT_NONE) {
                    ids[n] = b->sides[s].positions[p].activation_id;
                    ++n;
                }
            }
        }
        for (uint32_t i = 0u; i < n && inv == DFI_INV_NONE; ++i) {
            for (uint32_t j = i + 1u; j < n; ++j) {
                if (ids[i] == ids[j]) {
                    inv = DFI_INV_ACTIVATION_DUPLICATE;
                    break;
                }
            }
        }
    }
    if (inv != DFI_INV_NONE) {
        if (out_first != NULL) {
            *out_first = inv;
        }
        return DUOFORGE_E_INVARIANT;
    }
    return DUOFORGE_OK;
}

const char *dfi_invariant_name(dfi_invariant id)
{
    switch (id) {
    case DFI_INV_NONE:
        return "NONE";
    case DFI_INV_CONTEXT_FINGERPRINT:
        return "CONTEXT_FINGERPRINT";
    case DFI_INV_RNG_INC_EVEN:
        return "RNG_INC_EVEN";
    case DFI_INV_NEXT_ACTIVATION_ZERO:
        return "NEXT_ACTIVATION_ZERO";
    case DFI_INV_MEMBER_COUNT:
        return "MEMBER_COUNT";
    case DFI_INV_SPECIES_RANGE:
        return "SPECIES_RANGE";
    case DFI_INV_HP_MAX_ZERO:
        return "HP_MAX_ZERO";
    case DFI_INV_HP_ABOVE_MAX:
        return "HP_ABOVE_MAX";
    case DFI_INV_MOVE_COUNT:
        return "MOVE_COUNT";
    case DFI_INV_MOVE_ID_RANGE:
        return "MOVE_ID_RANGE";
    case DFI_INV_PP_MAX_ZERO:
        return "PP_MAX_ZERO";
    case DFI_INV_PP_ABOVE_MAX:
        return "PP_ABOVE_MAX";
    case DFI_INV_UNUSED_MOVE_NONZERO:
        return "UNUSED_MOVE_NONZERO";
    case DFI_INV_UNUSED_MEMBER_NONZERO:
        return "UNUSED_MEMBER_NONZERO";
    case DFI_INV_BROUGHT_OUT_OF_RANGE:
        return "BROUGHT_OUT_OF_RANGE";
    case DFI_INV_BROUGHT_COUNT:
        return "BROUGHT_COUNT";
    case DFI_INV_EMPTY_WITH_ACTIVATION:
        return "EMPTY_WITH_ACTIVATION";
    case DFI_INV_OCCUPIED_WITHOUT_ACTIVATION:
        return "OCCUPIED_WITHOUT_ACTIVATION";
    case DFI_INV_OCCUPANT_RANGE:
        return "OCCUPANT_RANGE";
    case DFI_INV_OCCUPANT_NOT_BROUGHT:
        return "OCCUPANT_NOT_BROUGHT";
    case DFI_INV_ACTIVATION_NOT_ISSUED:
        return "ACTIVATION_NOT_ISSUED";
    case DFI_INV_OCCUPANT_DUPLICATE:
        return "OCCUPANT_DUPLICATE";
    case DFI_INV_ACTIVATION_DUPLICATE:
        return "ACTIVATION_DUPLICATE";
    case DFI_INV_COUNT:
    default:
        return "UNKNOWN";
    }
}
