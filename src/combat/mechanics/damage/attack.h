#ifndef DUOFORGE_COMBAT_MECHANICS_DAMAGE_ATTACK_H
#define DUOFORGE_COMBAT_MECHANICS_DAMAGE_ATTACK_H

/* Private damage implementation (restructure step 4, damage): one phase of dfi_get_damage. Split from
 * src/combat/turn.c@dc9ce14b, lines 1491-1543 of dfi_get_damage; every line of it is unchanged, the phase only loads its inputs
 * from the stack context and stores its outputs. Included by turn.c before dfi_get_damage, so its dependencies and
 * the damage order are unchanged. */
#include "combat/mechanics/damage/context.h"

/* Phase of dfi_get_damage: the ModifyAtk / ModifySpA chain on the attack stat; the BasePower chain's `ok` arrives in the
 * context and is tested here, as before the cut. */
static DFI_ALWAYS_INLINE duoforge_status
dfi_damage_attack(dfi_run *r, uint32_t user, uint32_t target, const dfi_move_data *md, uint32_t move_type,
                  dfi_damage_ctx *c)
{
    (void)md;
    const dfi_member *a = c->a;
    const dfi_member *d = c->d;
    const dfi_active_slot *ap = c->ap;
    const bool physical = c->physical;
    const uint32_t atk_index = c->atk_index;
    uint32_t attack = c->attack;
    bool ok = c->ok;
    /* ModifyAtk / ModifySpA, one chained modifier: a pinch ability (the
     * PINCH family: Blaze, Overgrow, Torrent and Swarm, decision 0015) for a
     * move of its type at a third of the HP or less, Flash Fire's boost for
     * Fire moves once it took one; 1.5 each. */
    uint32_t atk_chain = 4096u;
    ok = dfi_pinch_attack(r->b, a, move_type, ok, &atk_chain);
    if (move_type == DFI_TYPE_FIRE && dfi_ability(r->b, a, DFI_ABILITY_FLASHFIRE) &&
        ((uint32_t)ap->flags & DFI_VOL_FLASH_FIRE) != 0u) {
        ok = ok && dfi_chain_modify(atk_chain, 6144u, &atk_chain);
    }
    /* Solar Power (step G39, data/abilities.ts:4396-4413, onModifySpA priority 5): x1.5 for the Special Attack stat in sun
     * (Desolate Land is not a weather of the state). It is the holder's one ability, so it never meets a pinch ability or
     * Flash Fire, the other chained ability modifiers. */
    if (atk_index == DFI_STAGE_SPA && dfi_field_weather(r) == DFI_WEATHER_SUN && dfi_ability(r->b, a, DFI_ABILITY_SOLARPOWER)) {
        ok = ok && dfi_chain_modify(atk_chain, 6144u, &atk_chain);
    }
    /* The three step-G59 abilities of the Attack and Special Attack events, all dyadic (8192, 6144, 2048 out of 4096), so
     * their order and the one rounding of the chain give the same value in every order. The events follow the move's
     * CATEGORY, not the stat that the move uses (sim/battle-actions.ts:1694-1697: `Modify` + Atk or SpA of the category), so
     * Body Press's Defense is multiplied by Huge Power in the ModifyAtk event and Foul Play's Attack by the user's
     * abilities, the user being the event's holder (the source of the runEvent call; `source`, sim/battle-actions.ts:1697).
     *   Huge Power (data/abilities.ts:1886-1896, onModifyAtkPriority 5): x2 for a physical move of its holder.
     *   Fire Mane (data/abilities.ts:1295-1310, onModifyAtkPriority 5 and onModifySpAPriority 5): x1.5 for a Fire move of its
     *     holder, either category; the Champions mod inherits it (Future tag dropped).
     *   Thick Fat (data/abilities.ts:5014-5030, onSourceModifyAtkPriority 6 and onSourceModifySpAPriority 5, breakable: no
     *     Mold Breaker is marked): x0.5 for an Ice or Fire move against its holder (the target, the `source` of the
     *     event), either category. */
    /* Pure Power (step G75, data/abilities.ts:3608-3617, as Huge Power: onModifyAtk x2 for a physical move of its holder). */
    if (physical && (dfi_ability(r->b, a, DFI_ABILITY_HUGEPOWER) || dfi_ability(r->b, a, DFI_ABILITY_PUREPOWER))) {
        ok = ok && dfi_chain_modify(atk_chain, 8192u, &atk_chain);
    }
    if (move_type == DFI_TYPE_FIRE && dfi_ability(r->b, a, DFI_ABILITY_FIREMANE)) {
        ok = ok && dfi_chain_modify(atk_chain, 6144u, &atk_chain);
    }
    if ((move_type == DFI_TYPE_ICE || move_type == DFI_TYPE_FIRE) && dfi_ability(r->b, d, DFI_ABILITY_THICKFAT)) {
        ok = ok && dfi_chain_modify(atk_chain, 2048u, &atk_chain);
    }
    /* Water Bubble (step G65, data/abilities.ts:5377-5417, breakable, Mold Breaker not marked): onModifyAtk and onModifySpA of
     * the holder, x2 for its Water moves of either category (priority 0; every factor of this chain is dyadic, so their order does not change the value);
     * onSourceModifyAtk and onSourceModifySpA of the target (priority 5), x0.5 for a Fire move against its holder, either
     * category, as Thick Fat. The two are the holder's one ability, so they never meet a Thick Fat. */
    if (move_type == DFI_TYPE_WATER && dfi_ability(r->b, a, DFI_ABILITY_WATERBUBBLE)) {
        ok = ok && dfi_chain_modify(atk_chain, 8192u, &atk_chain);
    }
    if (move_type == DFI_TYPE_FIRE && dfi_ability(r->b, d, DFI_ABILITY_WATERBUBBLE)) {
        ok = ok && dfi_chain_modify(atk_chain, 2048u, &atk_chain);
    }
    /* Batch A1b, four more members of this chain. Each is the holder's one ability or its one item, and every product of the chain
     * stays exact (at most one 1.5 of the attacker's ability, the rest powers of two), so their priorities (5 and 6, Light Ball's
     * 1) and the holders' Speeds do not change the value.
     *   Plus and Minus (data/abilities.ts:3317-3330 and 2643-2656, onModifySpAPriority 5): x1.5 in the ModifySpA event (a special
     *     move) when one of pokemon.allies() (sim/pokemon.ts:720-722, sim/side.ts:390-396: the partner with HP) has Plus or Minus.
     *   Stakeout (data/abilities.ts:4476-4495, onModifyAtkPriority 5 and onModifySpAPriority 5): x2 in either event while the
     *     defender's activeTurns is 0: from its switch-in (sim/battle-actions.ts:137) to the end of the turn (sim/battle.ts:1765),
     *     the state's NEWLY_SWITCHED flag of its position (as Speed Boost reads it).
     *   Heatproof (data/abilities.ts:1833-1857, onSourceModifyAtkPriority 6 and onSourceModifySpAPriority 5, breakable: no Mold
     *     Breaker is marked): x0.5 for a Fire move against its holder, either category, as Thick Fat and Water Bubble.
     *   Light Ball (data/items.ts:3421-3443, onModifyAtkPriority 1 and onModifySpAPriority 1): x2 in either event for a holder
     *     whose baseSpecies is Pikachu (the member's base forme; the pool has no other Pikachu forme). */
    if (!physical && (dfi_ability(r->b, a, DFI_ABILITY_PLUS) || dfi_ability(r->b, a, DFI_ABILITY_MINUS))) {
        const dfi_member *pm_ally = dfi_at(r->b, user ^ 1u);
        if (pm_ally != NULL && pm_ally->hp != 0u &&
            (dfi_ability(r->b, pm_ally, DFI_ABILITY_PLUS) || dfi_ability(r->b, pm_ally, DFI_ABILITY_MINUS))) {
            ok = ok && dfi_chain_modify(atk_chain, 6144u, &atk_chain);
        }
    }
    if (dfi_ability(r->b, a, DFI_ABILITY_STAKEOUT) && ((uint32_t)dfi_pos(r->b, target)->flags & DFI_VOL_NEWLY_SWITCHED) != 0u) {
        ok = ok && dfi_chain_modify(atk_chain, 8192u, &atk_chain);
    }
    if (move_type == DFI_TYPE_FIRE && dfi_ability(r->b, d, DFI_ABILITY_HEATPROOF)) {
        ok = ok && dfi_chain_modify(atk_chain, 2048u, &atk_chain);
    }
    if (dfi_holds(r->b, a, DFI_ITEM_LIGHTBALL) && a->species_id == DFI_FORME_PIKACHU) {
        ok = ok && dfi_chain_modify(atk_chain, 8192u, &atk_chain);
    }
    if (!ok) {
        return DUOFORGE_E_INVARIANT;
    }
    if (atk_chain != 4096u) {
        attack = dfi_modify(attack, atk_chain);
    }
    c->attack = attack;
    c->ok = ok;
    return DUOFORGE_OK;
}

#endif
