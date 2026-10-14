#ifndef DUOFORGE_COMBAT_ABILITIES_PROTECT_BYPASS_H
#define DUOFORGE_COMBAT_ABILITIES_PROTECT_BYPASS_H

#include "combat/abilities/current.h"

/* Step K2 (decision 0015 5dd, #474): Piercing Drill's onHitProtect (data/abilities.ts:3282-3294). The holder's move with the
 * contact flag passes a protection whose check calls checkMoveBypassesProtect with the protect flag (sim/battle.ts:1300-1309):
 * the HitProtect event returns false. The protect flag is required, as in the check itself. The holder is the attacker. */
static inline bool dfi_piercing_drill_passes(const struct duoforge_battle *b, const dfi_member *attacker,
                                             const dfi_move_data *md)
{
    return dfi_ability(b, attacker, DFI_ABILITY_PIERCINGDRILL) && (md->flags & DFI_MOVE_FLAG_CONTACT) != 0u &&
           (md->flags & DFI_MOVE_FLAG_PROTECT) != 0u;
}

/* The damage of such a bypassed hit is modified by 0.25 after the ModifyDamage chain (data/mods/champions/scripts.ts, the
 * bypassProtect block), as 1024/4096; dfi_modify does the rounding of the pin's modify. */
#define DFI_PIERCING_DRILL_BYPASS_MOD 1024u

#endif
