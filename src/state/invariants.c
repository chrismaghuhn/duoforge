#include "state/invariants.h"

#include "core/arith.h"
#include "state/context_internal.h"

static bool dfi_move_slot_is_zero(const dfi_move_slot *mv)
{
    return mv->move_id == 0u && mv->pp == 0u && mv->pp_max == 0u;
}

static bool dfi_member_is_zero(const dfi_member *m)
{
    if (m->species_id != 0u || m->hp != 0u || m->hp_max != 0u || m->move_count != 0u || m->mega_capable != 0u) {
        return false;
    }
    for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        if (!dfi_move_slot_is_zero(&m->moves[k])) {
            return false;
        }
    }
    return true;
}

static bool dfi_cmd_is_zero(const dfi_slot_cmd *c)
{
    return c->kind == 0u && c->move_slot == 0u && c->target == 0u && c->mega == 0u && c->reserve == 0u;
}

/* Structural validity of a sealed command (not domain membership). */
static bool dfi_sealed_cmd_valid(const dfi_slot_cmd *c, uint32_t member_count)
{
    const uint32_t kind = c->kind;
    if (kind == DFI_SLOT_MOVE) {
        return c->move_slot < DUOFORGE_MAX_MOVE_SLOTS &&
               (c->target < DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE || c->target == DUOFORGE_TARGET_NONE) &&
               c->mega <= 1u && c->reserve == 0u;
    }
    if (kind == DFI_SLOT_SWITCH) {
        return c->reserve < member_count && c->move_slot == 0u && c->target == 0u && c->mega == 0u;
    }
    if (kind == DFI_SLOT_NONE || kind == DFI_SLOT_PASS) {
        return c->move_slot == 0u && c->target == 0u && c->mega == 0u && c->reserve == 0u;
    }
    return false;
}

uint32_t dfi_side_occupied_mask(const dfi_side *side)
{
    uint32_t mask = 0u;
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        if (side->positions[p].occupant != DFI_OCCUPANT_NONE) {
            mask |= 1u << p;
        }
    }
    return mask;
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
    if (m->mega_capable > 1u) {
        return DFI_INV_MEGA_CAPABLE_RANGE;
    }
    return DFI_INV_NONE;
}

static dfi_invariant dfi_check_side(const struct duoforge_context *ctx, const struct duoforge_battle *b,
                                    uint32_t s)
{
    const dfi_side *side = &b->sides[s];
    const uint32_t kind = b->boundary_kind;
    const bool requested = (((uint32_t)b->request_mask >> s) & 1u) == 1u;
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
    const uint32_t brought = dfi_popcount8(side->brought_mask);
    if (brought != (kind == DUOFORGE_BOUNDARY_TEAM_SELECTION ? 0u : (uint32_t)ctx->brought_count)) {
        return DFI_INV_BROUGHT_COUNT;
    }
    for (uint32_t i = 0u; i < DUOFORGE_MAX_ROSTER; ++i) {
        const uint32_t o = side->brought_order[i];
        if (i < brought) {
            if (o >= member_count) { /* before the bit test */
                return DFI_INV_BROUGHT_ORDER;
            }
            if (((mask >> o) & 1u) == 0u) {
                return DFI_INV_BROUGHT_ORDER;
            }
            for (uint32_t j = 0u; j < i; ++j) {
                if (side->brought_order[j] == o) {
                    return DFI_INV_BROUGHT_ORDER;
                }
            }
        } else if (o != DUOFORGE_ROSTER_NONE) {
            return DFI_INV_BROUGHT_ORDER;
        }
    }
    if (side->mega_used > 1u) {
        return DFI_INV_MEGA_USED_RANGE;
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
        if (slot->activation_id >= b->next_activation_id) {
            return DFI_INV_ACTIVATION_NOT_ISSUED;
        }
    }
    if (side->positions[0].occupant != DFI_OCCUPANT_NONE &&
        side->positions[0].occupant == side->positions[1].occupant) {
        return DFI_INV_OCCUPANT_DUPLICATE;
    }
    const uint32_t occupied = dfi_side_occupied_mask(side);
    const uint32_t rs = side->requested_slots;
    if (rs > 3u) {
        return DFI_INV_REQUESTED_SLOTS;
    }
    if (!requested || kind == DUOFORGE_BOUNDARY_TEAM_SELECTION) {
        if (rs != 0u) {
            return DFI_INV_REQUESTED_SLOTS;
        }
    } else if (kind == DUOFORGE_BOUNDARY_TURN) {
        if (rs != occupied) {
            return DFI_INV_REQUESTED_SLOTS;
        }
    } else {
        if (rs == 0u || (rs & ~occupied) != 0u) {
            return DFI_INV_REQUESTED_SLOTS;
        }
    }
    const uint32_t sealed = side->sealed;
    if (sealed > 1u) {
        return DFI_INV_SEALED_RANGE;
    }
    if (kind == DUOFORGE_BOUNDARY_TEAM_SELECTION || kind == DUOFORGE_BOUNDARY_REPLACEMENT) {
        if (sealed != 0u) {
            return DFI_INV_SEALED_RULE;
        }
    } else if (kind == DUOFORGE_BOUNDARY_TURN) {
        if (sealed != (requested ? 0u : 1u)) {
            return DFI_INV_SEALED_RULE;
        }
    }
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        const dfi_slot_cmd *c = &side->sealed_cmds[p];
        if (sealed == 0u) {
            if (!dfi_cmd_is_zero(c)) {
                return DFI_INV_SEALED_COMMAND;
            }
        } else if (!dfi_sealed_cmd_valid(c, member_count)) {
            return DFI_INV_SEALED_COMMAND;
        }
    }
    return DFI_INV_NONE;
}

/* Knowledge of player p about the opponent: every seen bit names a brought
 * member, and every foe occupant is seen. Runs after both sides passed, so
 * member_count and brought_mask are already in range. */
static dfi_invariant dfi_check_seen(const struct duoforge_battle *b, uint32_t p)
{
    const uint32_t seen = b->sides[p].seen_mask;
    const dfi_side *opp = &b->sides[1u - p];
    const uint32_t member_count = opp->member_count;
    if (member_count > DUOFORGE_MAX_ROSTER || (seen >> member_count) != 0u) {
        return DFI_INV_SEEN_MASK;
    }
    if ((seen & ~(uint32_t)opp->brought_mask) != 0u) {
        return DFI_INV_SEEN_MASK;
    }
    for (uint32_t k = 0u; k < DUOFORGE_ACTIVE_PER_SIDE; ++k) {
        const uint32_t occupant = opp->positions[k].occupant;
        if (occupant == DFI_OCCUPANT_NONE) {
            continue;
        }
        if (occupant >= DUOFORGE_MAX_ROSTER || ((seen >> occupant) & 1u) == 0u) {
            return DFI_INV_SEEN_MASK;
        }
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
    } else if (b->boundary_kind < DUOFORGE_BOUNDARY_TEAM_SELECTION || b->boundary_kind > DUOFORGE_BOUNDARY_PIVOT) {
        inv = DFI_INV_BOUNDARY_KIND;
    } else if (b->request_epoch == 0u) {
        inv = DFI_INV_EPOCH_ZERO;
    } else if (b->request_mask < 1u || b->request_mask > 3u) {
        inv = DFI_INV_REQUEST_MASK;
    } else {
        for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT && inv == DFI_INV_NONE; ++s) {
            inv = dfi_check_side(ctx, b, s);
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
    for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT && inv == DFI_INV_NONE; ++p) {
        inv = dfi_check_seen(b, p);
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
    case DFI_INV_BOUNDARY_KIND:
        return "BOUNDARY_KIND";
    case DFI_INV_EPOCH_ZERO:
        return "EPOCH_ZERO";
    case DFI_INV_REQUEST_MASK:
        return "REQUEST_MASK";
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
    case DFI_INV_MEGA_CAPABLE_RANGE:
        return "MEGA_CAPABLE_RANGE";
    case DFI_INV_UNUSED_MEMBER_NONZERO:
        return "UNUSED_MEMBER_NONZERO";
    case DFI_INV_BROUGHT_OUT_OF_RANGE:
        return "BROUGHT_OUT_OF_RANGE";
    case DFI_INV_BROUGHT_COUNT:
        return "BROUGHT_COUNT";
    case DFI_INV_BROUGHT_ORDER:
        return "BROUGHT_ORDER";
    case DFI_INV_MEGA_USED_RANGE:
        return "MEGA_USED_RANGE";
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
    case DFI_INV_REQUESTED_SLOTS:
        return "REQUESTED_SLOTS";
    case DFI_INV_SEALED_RANGE:
        return "SEALED_RANGE";
    case DFI_INV_SEALED_RULE:
        return "SEALED_RULE";
    case DFI_INV_SEALED_COMMAND:
        return "SEALED_COMMAND";
    case DFI_INV_ACTIVATION_DUPLICATE:
        return "ACTIVATION_DUPLICATE";
    case DFI_INV_SEEN_MASK:
        return "SEEN_MASK";
    case DFI_INV_COUNT:
    default:
        return "UNKNOWN";
    }
}
