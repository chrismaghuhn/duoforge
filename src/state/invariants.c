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
        const bool target_ok = c->move_slot == DUOFORGE_MOVE_SLOT_STRUGGLE || c->move_slot == DUOFORGE_MOVE_SLOT_RECHARGE
                                   ? c->target == DUOFORGE_TARGET_NONE
                                   : (c->move_slot < DUOFORGE_MAX_MOVE_SLOTS &&
                                      (c->target < DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE ||
                                       c->target == DUOFORGE_TARGET_NONE));
        /* Struggle never carries a Mega declaration (the request offers none). */
        const uint32_t mega_max =
            c->move_slot == DUOFORGE_MOVE_SLOT_STRUGGLE || c->move_slot == DUOFORGE_MOVE_SLOT_RECHARGE ? 0u : 1u;
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
            /* The item the occupant holds now: its sheet's unless that was used up, or the one that the POOL tail's
             * item_now holds for it (DFI_TAIL_ITEM_NONE after a Knock Off; zero under every other kind: the tail is
             * absent there). */
            const uint32_t item_now = lim.pool_rules ? b->tail.sides[s].item_now[slot->occupant] : 0u;
            const uint32_t held = occupant->item_consumed != 0u ? 0u
                                  : item_now == DFI_TAIL_ITEM_NONE ? 0u
                                  : item_now != 0u                 ? item_now
                                                                   : occupant->item;
            /* A choice lock needs its Choice item: one that a move took ends the lock with it (Knock Off, step G16;
             * nothing else of the data takes a Choice Scarf). */
            if (((uint32_t)slot->flags & DFI_VOL_CHOICE_LOCK) != 0u && held != 1u + DFI_ITEM_CHOICESCARF) {
                return DFI_INV_VOLATILE;
            }
            /* Unburden's volatile: set when its holder used its item or lost it to a move. The holder is the Pokemon
             * whose ability now is Unburden: the sheet's, or the one that the POOL tail's ability_now holds (zero under
             * every other kind). The item is gone: used up, or taken (or it stays: a Mega Stone on its own species
             * that refused Knock Off, which Unburden's onTakeItem answered first, data/abilities.ts:5240-5242). */
            const uint32_t now = lim.pool_rules ? b->tail.sides[s].ability_now[slot->occupant] : 0u; /* the tail is absent elsewhere */
            const bool item_gone = item_now == DFI_TAIL_ITEM_NONE ||
                                   (occupant->item_consumed != 0u && (occupant->item != 0u || item_now != 0u));
            if (((uint32_t)slot->flags & DFI_VOL_UNBURDEN) != 0u &&
                ((now != 0u ? now : occupant->ability) != 1u + DFI_ABILITY_UNBURDEN ||
                 (!item_gone && occupant->mega_capable == 0u))) {
                return DFI_INV_VOLATILE;
            }
            /* Follow Me's and Helping Hand's volatiles end in the residual and
             * newlySwitched at the end of the turn (sim/battle.ts:1673): a TURN
             * boundary holds none of them, a REPLACEMENT boundary (after the
             * residual) neither of the two volatiles. */
            const uint32_t residual_bits = DFI_VOL_FOLLOW_ME | DFI_VOL_HELPING_HAND;
            const uint32_t turn_bits = residual_bits | DFI_VOL_NEWLY_SWITCHED;
            if ((b->boundary_kind == DUOFORGE_BOUNDARY_TURN && ((uint32_t)slot->flags & turn_bits) != 0u) ||
                (b->boundary_kind == DUOFORGE_BOUNDARY_REPLACEMENT && ((uint32_t)slot->flags & residual_bits) != 0u)) {
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
        /* The old item_used: the item is gone, used up or taken by a move (the tail's item_now, step G16). */
        if ((k->revealed & DFI_REVEALED_ITEM_CONSUMED) != 0u && mem->item_consumed != 1u &&
            b->tail.sides[1u - p].item_now[m] != DFI_TAIL_ITEM_NONE) {
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
        return bound && r->reserve == 0u && r->move_slot <= DUOFORGE_MOVE_SLOT_RECHARGE &&
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

static bool dfi_field_valid(const duoforge_context *ctx, const struct duoforge_battle *b)
{
    const dfi_kind_limits lim = dfi_kind_limits_of(ctx->data_kind);
    return b->weather <= lim.weather_max && b->weather_turns <= DFI_FIELD_TURNS_MAX &&
           (b->weather == DFI_WEATHER_NONE) == (b->weather_turns == 0u) && b->terrain <= lim.terrain_max &&
           b->terrain_turns <= DFI_FIELD_TURNS_MAX &&
           (b->terrain == DFI_TERRAIN_NONE) == (b->terrain_turns == 0u) &&
           b->trick_room_turns <= DFI_FIELD_TURNS_MAX;
}


/* True iff every byte of `n` bytes at p is zero (the tail structs have no padding: static asserts in
 * codec/state_codec.h). */
static bool dfi_bytes_zero(const void *p, size_t n)
{
    const uint8_t *q = (const uint8_t *)p;
    uint32_t any = 0u;
    for (size_t i = 0u; i < n; ++i) {
        any |= q[i];
    }
    return any == 0u;
}

/* The tail of a standing occupant's position: the ranges, the pairs that are zero together and the sources that are
 * never the occupant itself (flat is its position, side * 2 + slot). */
static bool dfi_tail_pos_valid(const dfi_kind_limits *lim, const dfi_tail_pos *tp, uint32_t flat,
                               const dfi_member *occupant)
{
    const uint32_t move_count = occupant->move_count;
    const bool encore_ok = tp->last_move <= DFI_TAIL_MOVE_MAX &&
                           (tp->last_move == DFI_TAIL_MOVE_MAX || tp->last_move <= move_count) &&
                           tp->encore_slot <= DFI_TAIL_ENCORE_SLOT_MAX && tp->encore_slot <= move_count &&
                           tp->encore_turns <= DFI_TAIL_ENCORE_TURNS_MAX &&
                           (tp->encore_slot == 0u) == (tp->encore_turns == 0u);
    const bool bars_ok = tp->throat_chop_turns <= DFI_TAIL_THROAT_CHOP_MAX &&
                         tp->heal_block_turns <= DFI_TAIL_HEAL_BLOCK_MAX && tp->perish <= DFI_TAIL_PERISH_MAX &&
                         tp->taunt_turns <= DFI_TAIL_TAUNT_MAX && tp->yawn_turns <= DFI_TAIL_YAWN_MAX;
    const bool disable_ok = tp->disable_slot <= DFI_TAIL_DISABLE_SLOT_MAX && tp->disable_slot <= move_count &&
                            tp->disable_turns <= DFI_TAIL_DISABLE_TURNS_MAX &&
                            (tp->disable_slot == 0u) == (tp->disable_turns == 0u);
    const bool flags_ok = tp->imprison <= DFI_TAIL_FLAG_MAX && tp->must_recharge <= DFI_TAIL_FLAG_MAX &&
                          tp->focus_energy <= DFI_TAIL_FLAG_MAX && tp->charge <= DFI_TAIL_FLAG_MAX &&
                          tp->glaive_rush <= DFI_TAIL_FLAG_MAX;
    /* A Substitute has at most a quarter of the maximum HP (floor), as it is made. */
    const bool substitute_ok = tp->substitute_hp <= (uint32_t)occupant->hp_max / 4u;
    /* A partial trap: turns, source (another position) and move together, the band only with them. */
    const bool trap_ok = tp->trap_turns <= DFI_TAIL_TRAP_TURNS_MAX && tp->trap_source <= DFI_TAIL_SOURCE_MAX &&
                         tp->trap_source != flat + 1u && tp->trap_move <= lim->move_count &&
                         (tp->trap_turns == 0u) == (tp->trap_source == 0u) &&
                         (tp->trap_turns == 0u) == (tp->trap_move == 0u) && tp->trap_band <= DFI_TAIL_FLAG_MAX &&
                         (tp->trap_turns != 0u || tp->trap_band == 0u);
    const bool leech_ok = tp->leech_seed_source <= DFI_TAIL_SOURCE_MAX && tp->leech_seed_source != flat + 1u;
    const bool stockpile_ok = tp->stockpile <= DFI_TAIL_STOCKPILE_MAX && tp->stockpile_def <= tp->stockpile &&
                              tp->stockpile_spd <= tp->stockpile;
    return encore_ok && bars_ok && disable_ok && flags_ok && substitute_ok && trap_ok && leech_ok && stockpile_ok;
}

/* The POOL tail (decision 0015 section 7). Runs after the side checks, so every occupant is below the member count
 * and every move count is 1..4; each index is still bounded here. Under the other kinds the tail is absent: zero. */
static dfi_invariant dfi_check_tail(const duoforge_context *ctx, const struct duoforge_battle *b)
{
    const dfi_kind_limits lim = dfi_kind_limits_of(ctx->data_kind);
    if (!lim.pool_rules) {
        return dfi_bytes_zero(&b->tail, sizeof b->tail) ? DFI_INV_NONE : DFI_INV_TAIL_KIND;
    }
    if (b->tail.gravity_turns > DFI_TAIL_GRAVITY_MAX || b->tail.field_pad != 0u) {
        return DFI_INV_TAIL_FIELD;
    }
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const dfi_tail_side *ts = &b->tail.sides[s];
        const dfi_side *side = &b->sides[s];
        if (ts->wide_guard > DFI_TAIL_WIDE_GUARD_MAX || ts->aurora_veil_turns > DFI_TAIL_AURORA_VEIL_MAX ||
            ts->toxic_spikes > DFI_TAIL_TOXIC_SPIKES_MAX || ts->stealth_rock > DFI_TAIL_STEALTH_ROCK_MAX ||
            ts->spikes > DFI_TAIL_SPIKES_MAX || ts->sticky_web > DFI_TAIL_STICKY_WEB_MAX) {
            return DFI_INV_TAIL_SIDE;
        }
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const dfi_tail_pos *tp = &ts->positions[p];
            const uint32_t occupant = side->positions[p].occupant;
            const bool standing = occupant < DUOFORGE_MAX_ROSTER && occupant < side->member_count &&
                                  side->members[occupant].hp != 0u;
            if (!standing) {
                if (!dfi_bytes_zero(tp, sizeof *tp)) {
                    return DFI_INV_TAIL_POSITION; /* cleared when the occupant leaves or faints */
                }
                continue;
            }
            if (!dfi_tail_pos_valid(&lim, tp, s * DUOFORGE_ACTIVE_PER_SIDE + p, &side->members[occupant])) {
                return DFI_INV_TAIL_POSITION;
            }
        }
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            const bool any = ts->soak_type[m] != 0u || ts->ability_now[m] != 0u || ts->forme_now[m] != 0u ||
                             ts->item_now[m] != 0u || ts->toxic_stage[m] != 0u;
            if (!any) {
                continue;
            }
            if (m >= side->member_count) {
                return DFI_INV_TAIL_MEMBER; /* a member that does not exist has no tail */
            }
            const dfi_member *mem = &side->members[m];
            const bool standing_on_field =
                mem->hp != 0u && (side->positions[0].occupant == m || side->positions[1].occupant == m);
            /* The type ends when the member leaves or faints, and a Mega Evolution that comes after it ends it too
             * (setSpecies); a Pokemon that is already Mega Evolved can be Soaked, so is_mega is no part of the rule
             * (step G11: the research note had assumed it was; the rule is only weaker, no encoded state changes). */
            if (ts->soak_type[m] != 0u && (ts->soak_type[m] > DFI_TYPE_COUNT || !standing_on_field)) {
                return DFI_INV_TAIL_MEMBER;
            }
            /* A current ability that something swapped in ends when the member leaves or faints. */
            if (ts->ability_now[m] != 0u && (ts->ability_now[m] > lim.ability_count || !standing_on_field)) {
                return DFI_INV_TAIL_MEMBER;
            }
            if (ts->forme_now[m] > lim.forme_count) {
                return DFI_INV_TAIL_MEMBER;
            }
            if (ts->item_now[m] != 0u && ts->item_now[m] != DFI_TAIL_ITEM_NONE && ts->item_now[m] > lim.item_count) {
                return DFI_INV_TAIL_MEMBER;
            }
            /* The toxic counter belongs to a badly poisoned member on the field. */
            if (ts->toxic_stage[m] != 0u &&
                (ts->toxic_stage[m] > DFI_TAIL_TOXIC_STAGE_MAX || !standing_on_field ||
                 mem->status != DFI_TAIL_TOXIC_STATUS)) {
                return DFI_INV_TAIL_MEMBER;
            }
        }
    }
    return DFI_INV_NONE;
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
    } else if (!dfi_field_valid(ctx, b)) {
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
    if (inv == DFI_INV_NONE) {
        inv = dfi_check_tail(ctx, b);
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
    case DFI_INV_TAIL_KIND:
        return "TAIL_KIND";
    case DFI_INV_TAIL_SIDE:
        return "TAIL_SIDE";
    case DFI_INV_TAIL_POSITION:
        return "TAIL_POSITION";
    case DFI_INV_TAIL_MEMBER:
        return "TAIL_MEMBER";
    case DFI_INV_TAIL_SCHEMA:
        return "TAIL_SCHEMA";
    case DFI_INV_TAIL_RESERVED:
        return "TAIL_RESERVED";
    case DFI_INV_TAIL_FIELD:
        return "TAIL_FIELD";
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
