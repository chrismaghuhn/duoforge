#ifndef DUOFORGE_COMBAT_ABILITIES_PINCH_H
#define DUOFORGE_COMBAT_ABILITIES_PINCH_H

#include "combat/abilities/current.h"
#include "core/modifier.h"

#define DFI_PINCH_MODIFIER 6144u /* chainModify(1.5) */

/* onModifyAtk and onModifySpA of a pinch ability: a move of its type at a
 * third of the maximum HP or less (hp <= maxhp / 3 in the handler, so
 * 3 hp <= maxhp). */
static inline bool dfi_pinch_applies_fam(dfi_ability_family fam, const dfi_member *user, uint32_t move_type)
{
    return fam.family == DFI_ABILITY_FAMILY_PINCH && move_type == fam.param &&
           (uint32_t)user->hp * 3u <= (uint32_t)user->hp_max;
}

/* The turn keeps this at the original ModifyAtk/ModifySpA chain position. */
static inline bool dfi_pinch_attack(const struct duoforge_battle *b, const dfi_member *a,
                                   uint32_t move_type, bool ok, uint32_t *atk_chain)
{
    if (dfi_pinch_applies_fam(dfi_ability_family_now(b, a), a, move_type)) {
        ok = ok && dfi_chain_modify(*atk_chain, DFI_PINCH_MODIFIER, atk_chain);
    }
    return ok;
}

#endif
