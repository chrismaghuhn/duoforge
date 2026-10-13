#ifndef DUOFORGE_COMBAT_ABILITIES_FAIRY_AURA_H
#define DUOFORGE_COMBAT_ABILITIES_FAIRY_AURA_H

#include "combat/abilities/current.h"
#include "combat/run_internal.h"
#include "core/modifier.h"

#define DFI_FAIRY_AURA_MODIFIER 5448u /* chainModify([5448, 4096]) */

/* Fairy Aura (data/abilities.ts:1266-1282, onAnyBasePower, priority 20): a Pokemon on the field with the ability (the
 * Mega Floette's only one; a fainted Pokemon is no longer on the field). It boosts the Fairy moves of every Pokemon on
 * the field once each (move.auraBooster: a second holder changes nothing), the foes' included. Aura Break (3072/4096
 * instead) is in no pool forme's legal abilities (checked by tests/data/test_pool_tables.c). */
static inline bool dfi_fairy_aura_on_field(struct duoforge_battle *b)
{
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        const dfi_member *m = dfi_at(b, flat);
        if (m != NULL && m->hp != 0u && dfi_ability(b, m, DFI_ABILITY_FAIRYAURA)) {
            return true;
        }
    }
    return false;
}

/* The turn retains this effect's priority and position in the BasePower chain. */
static inline bool dfi_fairy_aura_base_power(struct duoforge_battle *b, uint32_t user, uint32_t target,
                                           uint32_t move_type, bool ok, uint32_t *bp_chain)
{
    /* Fairy Aura (the Mega Floette's ability, onAnyBasePower priority 20: after Tough Claws, before the items): a
     * Fairy move of anyone on the field, unless it targets its own user, 5448/4096 once. */
    if (move_type == DFI_TYPE_FAIRY && user != target && dfi_fairy_aura_on_field(b)) {
        ok = ok && dfi_chain_modify(*bp_chain, DFI_FAIRY_AURA_MODIFIER, bp_chain);
    }
    return ok;
}

#endif
