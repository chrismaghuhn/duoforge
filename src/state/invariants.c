#include "state/invariants.h"

#include "core/arith.h"
#include "core/bytes.h"
#include "state/closure_member.h"
#include "state/context_internal.h"
#include "state/identity.h"
#include "state/knowledge.h"

static bool dfi_move_slot_is_zero(const dfi_move_slot *mv)
{
    return mv->move_id == 0u && mv->pp == 0u && mv->pp_max == 0u;
}

/* The v3 member fields that SYNTHETIC data never has. */
static bool dfi_member_extra_is_zero(const dfi_member *m)
{
    for (uint32_t i = 0u; i < DFI_MEMBER_STAT_COUNT; ++i) {
        if (m->stats[i] != 0u) {
            return false;
        }
    }
    for (uint32_t i = 0u; i < DFI_STAT_POINT_COUNT; ++i) {
        if (m->stat_points[i] != 0u) {
            return false;
        }
    }
    return m->is_mega == 0u && m->gender == 0u && m->nature == 0u && m->status == 0u &&
           m->status_counter == 0u && m->item == 0u && m->item_consumed == 0u && m->ability == 0u;
}

static bool dfi_member_is_zero(const dfi_member *m)
{
    if (m->species_id != 0u || m->hp != 0u || m->hp_max != 0u || m->move_count != 0u || m->mega_capable != 0u) {
        return false;
    }
    if (!dfi_member_extra_is_zero(m)) {
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
        const bool target_ok = c->move_slot == DUOFORGE_MOVE_SLOT_STRUGGLE
                                   ? c->target == DUOFORGE_TARGET_NONE
                                   : (c->move_slot < DUOFORGE_MAX_MOVE_SLOTS &&
                                      (c->target < DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE ||
                                       c->target == DUOFORGE_TARGET_NONE));
        /* Struggle never carries a Mega declaration (the request offers none). */
        const uint32_t mega_max = c->move_slot == DUOFORGE_MOVE_SLOT_STRUGGLE ? 0u : 1u;
        return target_ok && c->mega <= mega_max && c->reserve == 0u;
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

/* `full`: also the derived values and the move legality of a CLOSURE member
 * (dfi_state_check_query passes false). */
static dfi_invariant dfi_check_member(const struct duoforge_context *ctx, const dfi_member *m, bool full)
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
    /* SYNTHETIC data has no stats, natures, statuses, items or abilities;
     * CLOSURE members must agree with the generated tables and formulas. */
    if (dfi_context_is_closure(ctx)) {
        const dfi_kind_limits lim = dfi_kind_limits_of(ctx->data_kind);
        if (!(full ? dfi_closure_member_valid(&lim, m) : dfi_closure_member_ranges(&lim, m))) {
            return DFI_INV_MEMBER_EXTRA;
        }
    } else if (!dfi_member_extra_is_zero(m)) {
        return DFI_INV_MEMBER_EXTRA;
    }
    return DFI_INV_NONE;
}

/* Value ranges of an occupied position's volatile block. move_count is the
 * occupant's (already range-checked) move count; switch_flag_max is the
 * kind's (dfi_kind_limits). */
static bool dfi_volatile_valid(const dfi_active_slot *slot, uint32_t move_count, const dfi_kind_limits *lim)
{
    if (slot->switch_flag > lim->switch_flag_max) {
        return false;
    }
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        if (slot->stages[i] > DFI_STAGE_MAX) {
            return false;
        }
    }
    if (((uint32_t)slot->flags & ~lim->vol_flags_mask) != 0u) {
        return false;
    }
    if (slot->stall_level > DFI_STALL_LEVEL_MAX || slot->stall_turns > DFI_STALL_TURNS_MAX) {
        return false;
    }
    if ((slot->stall_level == 0u) != (slot->stall_turns == 0u)) {
        return false;
    }
    if (slot->confusion_turns > DFI_CONFUSION_TURNS_MAX || slot->charge_turns > DFI_CHARGE_TURNS_MAX) {
        return false;
    }
    /* The locked-move byte belongs to a charging two-turn move, to a choice
     * lock (Team C) or to both, then on the same move; the target only to
     * the charge. */
    const bool choice = ((uint32_t)slot->flags & DFI_VOL_CHOICE_LOCK) != 0u;
    if (slot->locked_move > move_count || (slot->locked_move != 0u) != (slot->charge_turns != 0u || choice)) {
        return false;
    }
    if (slot->charge_turns == 0u) {
        return slot->locked_target == 0u;
    }
    return slot->locked_target < DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE ||
           slot->locked_target == DUOFORGE_TARGET_NONE;
}

static dfi_invariant dfi_check_side(const struct duoforge_context *ctx, const struct duoforge_battle *b,
                                    const struct duoforge_battle *validated, bool full, uint32_t s)
{
    const dfi_side *side = &b->sides[s];
    const uint32_t kind = b->boundary_kind;
    const bool requested = (((uint32_t)b->request_mask >> s) & 1u) == 1u;
    /* Range-check member_count first: it bounds every later index/shift. */
    const uint32_t member_count = side->member_count;
    if (member_count < ctx->brought_count || member_count > ctx->max_roster) {
        return DFI_INV_MEMBER_COUNT;
    }
    if (dfi_kind_full_roster(ctx->data_kind) && member_count != ctx->max_roster) {
        return DFI_INV_MEMBER_COUNT; /* the certified profile registers exactly six (decision 0010) */
    }
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        if (m < member_count) {
            /* dfi_check_member is a function of the member's bytes alone:
             * a member byte-identical to one `validated` checked passes. */
            const dfi_member *seen = validated != NULL ? &validated->sides[s].members[m] : NULL;
            const bool same = seen != NULL && m < validated->sides[s].member_count &&
                              dfi_bytes_equal((const uint8_t *)&side->members[m], (const uint8_t *)seen, sizeof *seen);
            const dfi_invariant inv = same ? DFI_INV_NONE : dfi_check_member(ctx, &side->members[m], full);
            if (inv != DFI_INV_NONE) {
                return inv;
            }
            /* A fainted member keeps its status until the turn's actions are
             * done (checkFainted runs when the queue is empty): at a PIVOT it
             * may still have one, at every other boundary it has none. */
            if (dfi_context_is_closure(ctx) && kind != DUOFORGE_BOUNDARY_PIVOT && side->members[m].hp == 0u &&
                side->members[m].status != DFI_STATUS_NONE) {
                return DFI_INV_MEMBER_EXTRA;
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
    if (side->reflect_turns > DFI_SCREEN_TURNS_MAX || side->light_screen_turns > DFI_SCREEN_TURNS_MAX ||
        side->tailwind_turns > DFI_TAILWIND_TURNS_MAX) {
        return DFI_INV_SIDE_CONDITION;
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
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        const dfi_active_slot *slot = &side->positions[p];
        if (slot->occupant == DFI_OCCUPANT_NONE) {
            if (!dfi_slot_volatile_is_clear(slot)) {
                return DFI_INV_VOLATILE;
            }
        } else {
            const dfi_kind_limits lim = dfi_kind_limits_of(ctx->data_kind);
            const dfi_member *occupant = &side->members[slot->occupant]; /* occupant < member_count <= 6 here */
            if (!dfi_volatile_valid(slot, occupant->move_count, &lim)) {
                return DFI_INV_VOLATILE;
            }
            /* A choice lock needs its Choice item (no item is ever lost while
             * it holds: nothing in the data takes a Choice Scarf). */
            if (((uint32_t)slot->flags & DFI_VOL_CHOICE_LOCK) != 0u &&
                (occupant->item != 1u + DFI_ITEM_CHOICESCARF || occupant->item_consumed != 0u)) {
                return DFI_INV_VOLATILE;
            }
        }
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
    /* A switch flag marks exactly the requested slots of a PIVOT (its cause:
     * a self-switch move or Emergency Exit); it exists nowhere else. */
    uint32_t flagged = 0u;
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        if (side->positions[p].switch_flag != DFI_SWITCH_NONE) {
            flagged |= 1u << p;
        }
    }
    if (flagged != ((kind == DUOFORGE_BOUNDARY_PIVOT && requested) ? rs : 0u)) {
        return DFI_INV_SWITCH_FLAG;
    }
    const uint32_t sealed = side->sealed;
    if (sealed > 1u) {
        return DFI_INV_SEALED_RANGE;
    }
    /* A sealed choice exists only while the other side is re-prompted at
     * TURN; at a PIVOT the rest of the turn is in the queue. */
    if (sealed != ((kind == DUOFORGE_BOUNDARY_TURN && !requested) ? 1u : 0u)) {
        return DFI_INV_SEALED_RULE;
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

/* What player p remembers about the opposing members. Runs after both sides
 * and the seen masks passed, so counts, occupants and hp_max are in range. */
static bool dfi_knowledge_valid(const struct duoforge_battle *b, uint32_t p)
{
    const uint32_t seen = b->sides[p].seen_mask;
    const dfi_side *opp = &b->sides[1u - p];
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        const dfi_knowledge *k = &b->sides[p].knowledge[m];
        if (((seen >> m) & 1u) == 0u) {
            if (k->hp_percent != 0u || k->hp_flag != 0u || k->revealed != 0u) {
                return false;
            }
            if (m < opp->member_count && opp->members[m].is_mega != 0u) {
                return false; /* a Mega Evolution happens on the field, in view */
            }
            for (uint32_t j = 0u; j < DUOFORGE_MAX_MOVE_SLOTS; ++j) {
                if (k->moves_used[j] != 0u) {
                    return false;
                }
            }
            continue;
        }
        const dfi_member *mem = &opp->members[m]; /* seen implies m < member_count */
        if (!dfi_hp_display_valid(k->hp_percent, k->hp_flag)) {
            return false;
        }
        /* A revealed fact is a fact. */
        if (k->revealed > (DFI_REVEALED_ITEM_CONSUMED | DFI_REVEALED_MEGA)) {
            return false;
        }
        if ((k->revealed & DFI_REVEALED_ITEM_CONSUMED) != 0u && mem->item_consumed != 1u) {
            return false;
        }
        if (((k->revealed & DFI_REVEALED_MEGA) != 0u) != (mem->is_mega == 1u)) {
            return false;
        }
        for (uint32_t j = mem->move_count; j < DUOFORGE_MAX_MOVE_SLOTS; ++j) {
            if (k->moves_used[j] != 0u) {
                return false;
            }
        }
        if (opp->positions[0].occupant == m || opp->positions[1].occupant == m) {
            uint8_t percent = 0u;
            uint8_t flag = 0u;
            dfi_hp_display(mem->hp, mem->hp_max, &percent, &flag);
            if (k->hp_percent != percent || k->hp_flag != flag) {
                return false;
            }
        }
    }
    return true;
}

static bool dfi_queue_record_is_zero(const dfi_queue_record *r)
{
    return r->activation_id == 0u && r->kind == 0u && r->side == 0u && r->slot == 0u && r->move_slot == 0u &&
           r->target == 0u && r->reserve == 0u;
}

static bool dfi_queue_record_valid(const struct duoforge_battle *b, const dfi_queue_record *r)
{
    const uint32_t kind = r->kind;
    if (kind < DFI_Q_SWITCH_IN || kind > DFI_Q_RESIDUAL || r->side >= DUOFORGE_SIDE_COUNT ||
        r->slot >= DUOFORGE_ACTIVE_PER_SIDE) {
        return false;
    }
    const uint32_t member_count = b->sides[r->side].member_count;
    const bool bound = r->activation_id != 0u && r->activation_id < b->next_activation_id;
    const bool plain = r->move_slot == 0u && r->target == 0u;
    if (kind == DFI_Q_SWITCH_IN) {
        return plain && r->activation_id == 0u && r->reserve < member_count;
    }
    if (kind == DFI_Q_SWITCH) {
        return plain && bound && r->reserve < member_count;
    }
    if (kind == DFI_Q_RUN_SWITCH || kind == DFI_Q_MEGA) {
        return plain && bound && r->reserve == 0u;
    }
    if (kind == DFI_Q_MOVE) {
        return bound && r->reserve == 0u && r->move_slot <= DFI_MOVE_SLOT_STRUGGLE &&
               (r->target < DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE || r->target == DUOFORGE_TARGET_NONE);
    }
    /* RESIDUAL has no actor and no operand. */
    return r->activation_id == 0u && r->side == 0u && r->slot == 0u && plain && r->reserve == 0u;
}

/* The rest of a paused turn: present exactly at a PIVOT boundary. */
static bool dfi_queue_valid(const struct duoforge_battle *b)
{
    const uint32_t n = b->queue_len;
    if (n > DFI_QUEUE_CAPACITY || (b->boundary_kind == DUOFORGE_BOUNDARY_PIVOT) != (n >= 1u)) {
        return false;
    }
    for (uint32_t i = 0u; i < DFI_QUEUE_CAPACITY; ++i) {
        const dfi_queue_record *r = &b->queue[i];
        if (i >= n) {
            if (!dfi_queue_record_is_zero(r)) {
                return false;
            }
        } else if (!dfi_queue_record_valid(b, r)) {
            return false;
        }
    }
    return true;
}

static bool dfi_field_valid(const struct duoforge_battle *b)
{
    return b->weather <= DFI_WEATHER_SUN && b->weather_turns <= DFI_FIELD_TURNS_MAX &&
           (b->weather == DFI_WEATHER_NONE) == (b->weather_turns == 0u) && b->terrain <= DFI_TERRAIN_GRASSY &&
           b->terrain_turns <= DFI_FIELD_TURNS_MAX &&
           (b->terrain == DFI_TERRAIN_NONE) == (b->terrain_turns == 0u) &&
           b->trick_room_turns <= DFI_FIELD_TURNS_MAX;
}


static duoforge_status dfi_state_check_mode(const duoforge_context *ctx, const struct duoforge_battle *b,
                                           const struct duoforge_battle *validated, bool full,
                                           dfi_invariant *out_first)
{
    dfi_invariant inv = DFI_INV_NONE;
    const bool terminal = b->boundary_kind == DUOFORGE_BOUNDARY_TERMINAL;
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
    } else if (b->boundary_kind < DUOFORGE_BOUNDARY_TEAM_SELECTION ||
               b->boundary_kind > DUOFORGE_BOUNDARY_TERMINAL) {
        inv = DFI_INV_BOUNDARY_KIND;
    } else if (b->request_epoch == 0u) {
        inv = DFI_INV_EPOCH_ZERO;
    } else if (terminal ? b->request_mask != 0u : (b->request_mask < 1u || b->request_mask > 3u)) {
        inv = DFI_INV_REQUEST_MASK;
    } else if ((b->boundary_kind == DUOFORGE_BOUNDARY_TEAM_SELECTION) != (b->turn == 0u)) {
        inv = DFI_INV_TURN_COUNTER;
    } else if (b->result > DFI_RESULT_TIE || terminal != (b->result != DFI_RESULT_NONE)) {
        inv = DFI_INV_RESULT;
    } else if (!dfi_field_valid(b)) {
        inv = DFI_INV_FIELD;
    } else {
        for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT && inv == DFI_INV_NONE; ++s) {
            inv = dfi_check_side(ctx, b, validated, full, s);
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
    for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT && inv == DFI_INV_NONE; ++p) {
        if (!dfi_knowledge_valid(b, p)) {
            inv = DFI_INV_KNOWLEDGE;
        }
    }
    if (inv == DFI_INV_NONE && !dfi_queue_valid(b)) {
        inv = DFI_INV_QUEUE;
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
    case DFI_INV_TURN_COUNTER:
        return "TURN_COUNTER";
    case DFI_INV_RESULT:
        return "RESULT";
    case DFI_INV_FIELD:
        return "FIELD";
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
    case DFI_INV_MEMBER_EXTRA:
        return "MEMBER_EXTRA";
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
    case DFI_INV_SIDE_CONDITION:
        return "SIDE_CONDITION";
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
    case DFI_INV_VOLATILE:
        return "VOLATILE";
    case DFI_INV_REQUESTED_SLOTS:
        return "REQUESTED_SLOTS";
    case DFI_INV_SWITCH_FLAG:
        return "SWITCH_FLAG";
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
    case DFI_INV_KNOWLEDGE:
        return "KNOWLEDGE";
    case DFI_INV_QUEUE:
        return "QUEUE";
    case DFI_INV_COUNT:
    default:
        return "UNKNOWN";
    }
}

duoforge_status dfi_state_check(const duoforge_context *ctx, const struct duoforge_battle *b,
                                dfi_invariant *out_first)
{
    return dfi_state_check_mode(ctx, b, NULL, true, out_first);
}

duoforge_status dfi_state_check_since(const duoforge_context *ctx, const struct duoforge_battle *b,
                                      const struct duoforge_battle *validated, dfi_invariant *out_first)
{
    return dfi_state_check_mode(ctx, b, validated, true, out_first);
}

duoforge_status dfi_state_check_query(const duoforge_context *ctx, const struct duoforge_battle *b,
                                      dfi_invariant *out_first)
{
    return dfi_state_check_mode(ctx, b, NULL, false, out_first);
}
