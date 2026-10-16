#ifndef DUOFORGE_COMBAT_FORMS_STANCE_CHANGE_H
#define DUOFORGE_COMBAT_FORMS_STANCE_CHANGE_H

/* Private forms implementation (restructure step 4, forms): Stance Change. Split from src/combat/turn.c@342770b3;
 * included by turn.c where the function stood, so its dependencies and the turn flow are unchanged. */
#include "combat/run_internal.h"

/* Step G66 (decision 0040, decision 0015 5cb): Stance Change, onModifyMove of data/abilities.ts:4523-4535, in the ModifyMove
 * stage (after the move's own ModifyMove and before the move line). A Status move other than King's Shield changes nothing;
 * King's Shield takes the Shield forme and any other move the Blade. The change is a TEMPORARY formeChange (no isPermanent):
 * the forme's stats (the HP stays), forme_now (0 = the sheet's Shield forme, else the Blade's id + 1) and the FORME event
 * with cause ABILITY, id2 = Stance Change + 1, printed as -formechange. The forme ends with the switch-out
 * (dfi_tail_clear_occupant). A transformed Aegislash is not modelled: Transform is unmarked (refused by the pool). */
static duoforge_status dfi_stance_change(dfi_run *r, uint32_t user, uint32_t move_id, const dfi_move_data *md)
{
    struct duoforge_battle *b = r->b;
    dfi_member *m = dfi_at(b, user);
    const uint32_t side = user / 2u;
    if (m == NULL || m->species_id != DFI_FORME_AEGISLASH || !dfi_ability(b, m, DFI_ABILITY_STANCECHANGE)) {
        return DUOFORGE_OK;
    }
    const bool king = move_id == DFI_MOVE_KINGSSHIELD;
    if (md->category == DFI_CATEGORY_STATUS && !king) {
        return DUOFORGE_OK;
    }
    const bool want_blade = !king;
    const uint32_t idx = (uint32_t)(m - &b->sides[side].members[0]); /* wide-operands-reviewed: below DUOFORGE_MAX_ROSTER */
    uint16_t *forme_slot = &b->tail.sides[side].forme_now[idx];
    const bool blade_now = *forme_slot != 0u;
    if (blade_now == want_blade) {
        return DUOFORGE_OK; /* already in the forme that the move asks for: no line */
    }
    const uint32_t forme = want_blade ? DFI_FORME_AEGISLASHBLADE : DFI_FORME_AEGISLASH;
    uint16_t stats[DFI_MEMBER_STAT_COUNT];
    if (!dfi_closure_member_forme_stats(m, forme, stats)) {
        return DUOFORGE_E_INVARIANT;
    }
    for (uint32_t i = 0u; i < DFI_MEMBER_STAT_COUNT; ++i) {
        m->stats[i] = stats[i];
    }
    *forme_slot = want_blade ? (uint16_t)(DFI_FORME_AEGISLASHBLADE + 1u) : 0u; /* wide-operands-reviewed: a forme id + 1, < 348 */
    /* setSpecies -> setType(species.types, true) (sim/pokemon.ts:1387-1392): a type that Soak or Double Shock set ends, without
     * a line. Both formes are Steel/Ghost. */
    b->tail.sides[side].soak_type[idx] = 0u;
    b->tail.sides[side].type2[idx] = 0u;
    /* Step K3 (decision 0015 5de): formeChange -> setSpecies rebuilds the stored stats, so a live Speed Swap ends here. */
    b->tail.sides[user / 2u].positions[user % 2u].single_turn = (uint8_t)((uint32_t)b->tail.sides[user / 2u].positions[user % 2u].single_turn & ~(uint32_t)DFI_SINGLE_TURN_SPEED_SWAP); /* wide-operands-reviewed */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_FORME, user);
    e.id = (uint16_t)forme;
    e.cause = (uint8_t)DUOFORGE_CAUSE_ABILITY;
    e.id2 = (uint16_t)(DFI_ABILITY_STANCECHANGE + 1u); /* wide-operands-reviewed: an ability id + 1, < 255 */
    dfi_emit(r, &e);
    return DUOFORGE_OK;
}

#endif
