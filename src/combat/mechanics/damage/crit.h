#ifndef DUOFORGE_COMBAT_MECHANICS_DAMAGE_CRIT_H
#define DUOFORGE_COMBAT_MECHANICS_DAMAGE_CRIT_H

/* Private damage implementation (restructure step 4, damage): one phase of dfi_get_damage. Split from
 * src/combat/turn.c@dc9ce14b, lines 1147-1180 of dfi_get_damage; every line of it is unchanged, the phase only loads its inputs
 * from the stack context and stores its outputs. Included by turn.c before dfi_get_damage, so its dependencies and
 * the damage order are unchanged. */
#include "combat/mechanics/damage/context.h"

/* Phase of dfi_get_damage: the critical hit: ModifyCritRatio, the CRIT draw and the CriticalHit cancel. */
static DFI_ALWAYS_INLINE duoforge_status
dfi_damage_crit(dfi_run *r, uint32_t user, uint32_t target, const dfi_move_data *md, uint32_t move_type,
                dfi_damage_ctx *c)
{
    (void)target;
    (void)move_type;
    static const uint32_t crit_mult[5] = {0u, 24u, 8u, 2u, 1u};
    const dfi_member *a = c->a;
    const dfi_member *d = c->d;
    bool crit = false;
    /* ModifyCritRatio (sim/battle-actions.ts:1624): the attacker's Dragon Cheer stage and Super Luck (step G65,
     * data/abilities.ts:4703-4711, onModifyCritRatio of the user, not breakable: +1) added to the move's ratio, then the
     * clamp to 0..4 for gen 9 (sim/battle-actions.ts:1623-1633). */
    /* Step G75: Scope Lens (data/items.ts:5554-5565, onModifyCritRatio +1) is the holder's item, one more term of the same sum. */
    /* Leek (step G77, data/items.ts:3322-3337, onModifyCritRatio of the user: +2 when its base species is Farfetch'd or
     * Sirfetch'd; the pool has no other forme of either, and the item's itemUser list is not checked by the sim for it,
     * only for Z-moves, so the holder's species decides). */
    const bool leek_crit = dfi_holds(r->b, a, DFI_ITEM_LEEK) &&
                           (a->species_id == DFI_FORME_FARFETCHD || a->species_id == DFI_FORME_SIRFETCHD);
    uint32_t ratio = (uint32_t)md->crit_ratio + dfi_dragon_cheer_stage(r->b, user) +
                     (dfi_ability(r->b, a, DFI_ABILITY_SUPERLUCK) ? 1u : 0u) +
                     (dfi_holds(r->b, a, DFI_ITEM_SCOPELENS) ? 1u : 0u) + (leek_crit ? 2u : 0u);
    if (ratio > 4u) {
        ratio = 4u;
    }
    if (md->special == DFI_SPECIAL_WILL_CRIT) {
        /* willCrit (step C4, decision 0015 entry 5ct; Storm Throw, Flower Trick, Frost Breath): moveHit.crit = willCrit, so the
         * critical hit is certain and no roll is drawn (sim/battle-actions.ts:1638-1643). The CriticalHit event below still
         * runs (Shell Armor). The ratio above is read and clamped as the pin reads it; it has no draw here. */
        crit = true;
    } else if (ratio > 0u) {
        const duoforge_status st = dfi_draw_chance(r->draws, DFI_SITE_CRIT, 1u, crit_mult[ratio], &crit);
        if (st != DUOFORGE_OK) {
            return st;
        }
    }
    /* Shell Armor (step G63, data/abilities.ts:4222-4228, onCriticalHit false): the target's CriticalHit event runs after the
     * roll (sim/battle-actions.ts:1640-1646), so the draw above is taken and the hit is then not a critical one: no crit
     * modifier and no [-crit] line. Breakable; Mold Breaker is not marked. */
    /* Battle Armor (step G75, data/abilities.ts:355-361, the same onCriticalHit false as Shell Armor, breakable): the same cancel. */
    if (crit && (dfi_ability(r->b, d, DFI_ABILITY_SHELLARMOR) || dfi_ability(r->b, d, DFI_ABILITY_BATTLEARMOR))) {
        crit = false;
    }
    c->crit = crit;
    return DUOFORGE_OK;
}

#endif
