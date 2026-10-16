#ifndef DUOFORGE_COMBAT_FORMS_MEGA_H
#define DUOFORGE_COMBAT_FORMS_MEGA_H

/* Private forms implementation (restructure step 4, forms): Mega Evolution. Split from src/combat/turn.c@342770b3;
 * included by turn.c where the function stood, so its dependencies and the turn flow are unchanged. */
#include "combat/run_internal.h"

/* runMegaEvo (sim/battle-actions.ts): the Mega forme with its stats and
 * ability, once per side; the opponent sees it; the new ability starts
 * (setAbility's Start event: Drought). */
static duoforge_status dfi_run_mega(dfi_run *r, const dfi_queue_record *q)
{
    struct duoforge_battle *b = r->b;
    const uint32_t flat = (uint32_t)q->side * 2u + (uint32_t)q->slot;
    dfi_member *m = dfi_at(b, flat);
    dfi_side *sd = &b->sides[q->side];
    if (m == NULL || m->hp == 0u || dfi_pos(b, flat)->activation_id != q->activation_id || sd->mega_used != 0u) {
        return DUOFORGE_OK;
    }
    if (!dfi_closure_member_mega_evolve(m)) {
        return DUOFORGE_E_INVARIANT; /* the domain offers Mega only to a holder of its stone */
    }
    sd->mega_used = 1u;
    /* Step K3 (decision 0015 5de): formeChange -> setSpecies rebuilds the stored stats (the swapped Speed is gone). */
    b->tail.sides[q->side].positions[q->slot].single_turn = (uint8_t)((uint32_t)b->tail.sides[q->side].positions[q->slot].single_turn & ~(uint32_t)DFI_SINGLE_TURN_SPEED_SWAP); /* wide-operands-reviewed */
    /* formeChange -> setSpecies -> setType(species.types, true): a type that Soak set ends (sim/pokemon.ts:1392,
     * 1427-1434), without a line. */
    b->tail.sides[q->side].soak_type[dfi_pos(b, flat)->occupant] = 0u;
    /* The Mega forme's ability replaces one that Trace copied (formeChange -> setAbility, sim/pokemon.ts:1487). */
    b->tail.sides[q->side].ability_now[dfi_pos(b, flat)->occupant] = 0u;
    /* setAbility ends the old ability first (sim/pokemon.ts:1923, singleEvent End), and of the abilities that the engine
     * models three have an onEnd (data/abilities.ts; the Champions mod has none): Unburden's removes its volatile
     * (:5243-5245; a holder of its own Mega Stone may have it since a Knock Off, dfi_knock_off), Flash Fire's removes the
     * flashfire volatile (:1351-1353; a Trace holder that copied Flash Fire has it after a Fire move hit it, shown as
     * `-end|X|ability: Flash Fire|[silent]`), and Unnerve's (:5265-5267) clears the `unnerved` flag of its ability state, which the
     * engine does not keep (the foes' berries follow the ability that the holder has). Nothing else that the engine keeps
     * on a position belongs to an ability, and no ability of a Mega forme in the pool is Unburden or Flash Fire. */
    {
        dfi_active_slot *mega_pos = dfi_pos(b, flat);
        mega_pos->flags = (uint8_t)((uint32_t)mega_pos->flags & ~((uint32_t)DFI_VOL_UNBURDEN | (uint32_t)DFI_VOL_FLASH_FIRE)); /* wide-operands-reviewed */
    }
    duoforge_event forme = dfi_event_make(DUOFORGE_EVENT_FORME, flat);
    forme.id = (uint16_t)dfi_mega_of(m->species_id, m->item); /* [detailschange]: < DFI_POOL_FORME_COUNT */
    dfi_emit(r, &forme);
    duoforge_event mega = dfi_event_make(DUOFORGE_EVENT_MEGA, flat);
    mega.id2 = m->item; /* [-mega] the stone, item + 1 */
    dfi_emit(r, &mega);
    if (dfi_has_entry(b, m)) {
        const duoforge_status st = dfi_entry_ability(r, flat);
        if (st != DUOFORGE_OK) {
            return st;
        }
    }
    /* AfterMega: White Herb's onAnyAfterMega (Team C;
     * sim/battle-actions.ts:1914). */
    return dfi_herb_event(r, flat);
}

#endif
