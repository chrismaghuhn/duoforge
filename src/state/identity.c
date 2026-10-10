#include "state/identity.h"

#include "core/arith.h"
#include "state/closure_member.h"

bool dfi_position_valid(dfi_position_id p)
{
    return p.side < DUOFORGE_SIDE_COUNT && p.slot < DUOFORGE_ACTIVE_PER_SIDE;
}

uint32_t dfi_position_flat(dfi_position_id p)
{
    return (uint32_t)p.side * DUOFORGE_ACTIVE_PER_SIDE + (uint32_t)p.slot;
}

void dfi_slot_clear(dfi_active_slot *slot)
{
    slot->activation_id = 0u;
    slot->occupant = DFI_OCCUPANT_NONE;
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        slot->stages[i] = (uint8_t)DFI_STAGE_NEUTRAL;
    }
    slot->flags = 0u;
    slot->stall_level = 0u;
    slot->stall_turns = 0u;
    slot->confusion_turns = 0u;
    slot->charge_turns = 0u;
    slot->locked_move = 0u;
    slot->locked_target = 0u;
    slot->move_actions = 0u;
    slot->switch_flag = 0u;
}

void dfi_tail_clear_occupant(struct duoforge_battle *b, uint32_t flat)
{
    if (flat >= DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE) {
        return;
    }
    dfi_tail_side *ts = &b->tail.sides[flat / DUOFORGE_ACTIVE_PER_SIDE];
    const uint32_t occupant = b->sides[flat / DUOFORGE_ACTIVE_PER_SIDE].positions[flat % DUOFORGE_ACTIVE_PER_SIDE].occupant;
    /* Step G82 (decision 0045): bit 0 (Healing Wish) belongs to the slot, not to the occupant (side.slotConditions[position]):
     * it stays across a switch-out, a faint and the replacement's entry, and only the heal of an entrant clears it. The other
     * bits end with the occupant, as before. */
    dfi_tail_pos *tp = &ts->positions[flat % DUOFORGE_ACTIVE_PER_SIDE];
    const uint8_t healing_wish = (uint8_t)(tp->position_flags & DFI_POSFLAG_HEALING_WISH);
    *tp = (dfi_tail_pos){0u};
    tp->position_flags = healing_wish;
    if (occupant < DUOFORGE_MAX_ROSTER) {
        /* What ends with the occupant's time on the field: the type Soak set, a current ability that something
         * swapped in, the toxic counter. The current item and a permanent forme outlive the switch (a Trick or a Mega
         * Evolution stay); a temporary forme ends here (forme_now, below). */
        ts->soak_type[occupant] = 0u;
        ts->ability_now[occupant] = 0u;
        ts->toxic_stage[occupant] = 0u;
        ts->type2[occupant] = 0u; /* tail rev 4: a type that a move took away comes back with the Pokemon */
        /* Step G66 (decision 0040): the temporary forme (Stance Change's Blade, forme_now = its id + 1) ends with the time on
         * the field: the sheet's forme comes back with its stats (setSpecies in clearVolatile, sim/pokemon.ts:1559). Other
         * forme_now values are permanent formes and stay. The stats of a pool row always derive (the member's nature and
         * Stat Points are valid). */
        if (ts->forme_now[occupant] == DFI_FORME_AEGISLASHBLADE + 1u) {
            dfi_member *mem = &b->sides[flat / DUOFORGE_ACTIVE_PER_SIDE].members[occupant];
            uint16_t stats[DFI_MEMBER_STAT_COUNT];
            ts->forme_now[occupant] = 0u;
            if (dfi_closure_member_forme_stats(mem, mem->species_id, stats)) {
                for (uint32_t i = 0u; i < DFI_MEMBER_STAT_COUNT; ++i) {
                    mem->stats[i] = stats[i];
                }
            }
        }
    }
}

bool dfi_slot_volatile_is_clear(const dfi_active_slot *slot)
{
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        if (slot->stages[i] != DFI_STAGE_NEUTRAL) {
            return false;
        }
    }
    return slot->flags == 0u && slot->stall_level == 0u && slot->stall_turns == 0u &&
           slot->confusion_turns == 0u && slot->charge_turns == 0u && slot->locked_move == 0u &&
           slot->locked_target == 0u && slot->move_actions == 0u && slot->switch_flag == 0u;
}

bool dfi_member_valid(const struct duoforge_battle *b, dfi_member_id m)
{
    return m.side < DUOFORGE_SIDE_COUNT && m.roster < DUOFORGE_MAX_ROSTER &&
           m.roster < b->sides[m.side].member_count;
}

duoforge_status dfi_place(struct duoforge_battle *b, dfi_position_id p, uint8_t roster,
                          dfi_binding *out_binding)
{
    if (!dfi_position_valid(p)) {
        return DUOFORGE_E_INVARIANT;
    }
    dfi_side *side = &b->sides[p.side];
    /* The capacity bound comes first so a corrupt member_count can never
     * produce an out-of-range index or shift count. */
    if (roster >= DUOFORGE_MAX_ROSTER || roster >= side->member_count) {
        return DUOFORGE_E_INVARIANT;
    }
    if ((((uint32_t)side->brought_mask >> roster) & 1u) == 0u) {
        return DUOFORGE_E_INVARIANT;
    }
    if (side->positions[p.slot].occupant != DFI_OCCUPANT_NONE) {
        return DUOFORGE_E_INVARIANT;
    }
    const uint32_t other = 1u - (uint32_t)p.slot;
    if (side->positions[other].occupant == roster) {
        return DUOFORGE_E_INVARIANT;
    }
    if (b->next_activation_id == 0u) {
        return DUOFORGE_E_INVARIANT;
    }
    if (b->next_activation_id == UINT32_MAX) {
        return DUOFORGE_E_EXHAUSTED;
    }
    uint32_t next = 0u;
    if (!dfi_add_u32(b->next_activation_id, 1u, &next)) {
        return DUOFORGE_E_EXHAUSTED; /* unreachable after the check above */
    }
    const uint32_t id = b->next_activation_id;
    dfi_tail_clear_occupant(b, dfi_position_flat(p)); /* before the old occupant is overwritten */
    dfi_slot_clear(&side->positions[p.slot]); /* a fresh activation has no volatile state */
    side->positions[p.slot].activation_id = id;
    side->positions[p.slot].occupant = roster;
    b->next_activation_id = next;
    /* The opponent sees the member from the [switch] line of the step
     * (dfi_events_fold_knowledge, decision 0007 section 6). */
    out_binding->position = p;
    out_binding->activation_id = id;
    return DUOFORGE_OK;
}

duoforge_status dfi_vacate(struct duoforge_battle *b, dfi_position_id p)
{
    if (!dfi_position_valid(p)) {
        return DUOFORGE_E_INVARIANT;
    }
    dfi_active_slot *slot = &b->sides[p.side].positions[p.slot];
    if (slot->occupant == DFI_OCCUPANT_NONE) {
        return DUOFORGE_E_INVARIANT;
    }
    /* The opponent keeps the HP display it saw last (its knowledge record). */
    dfi_tail_clear_occupant(b, dfi_position_flat(p));
    dfi_slot_clear(slot);
    return DUOFORGE_OK;
}

duoforge_status dfi_current_binding(const struct duoforge_battle *b, dfi_position_id p, dfi_binding *out)
{
    if (!dfi_position_valid(p)) {
        return DUOFORGE_E_INVARIANT;
    }
    const dfi_active_slot *slot = &b->sides[p.side].positions[p.slot];
    out->position = p;
    out->activation_id = slot->occupant == DFI_OCCUPANT_NONE ? 0u : slot->activation_id;
    return DUOFORGE_OK;
}

bool dfi_binding_is_current(const struct duoforge_battle *b, dfi_binding x)
{
    if (!dfi_position_valid(x.position) || x.activation_id == 0u) {
        return false;
    }
    const dfi_active_slot *slot = &b->sides[x.position.side].positions[x.position.slot];
    return slot->occupant != DFI_OCCUPANT_NONE && slot->activation_id == x.activation_id;
}
