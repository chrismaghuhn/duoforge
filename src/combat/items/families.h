#ifndef DUOFORGE_COMBAT_ITEM_FAMILY_H
#define DUOFORGE_COMBAT_ITEM_FAMILY_H
/*
 * The item families of decision 0015 as the battle reads them: the type
 * booster, the resist berry, and the cure and heal berries with the isBerry
 * column (batch I2, entry 5eg). An item has the family and the type that the
 * family columns of data/pool_tables.h give it, and the rule below reads only
 * that; the only items named here are Sitrus Berry and Lum Berry (by id: a
 * closure row and an engine row), which share the berry paths of their
 * families, and Focus Sash. What each rule does to the damage (the
 * modifier and weaken event) is in combat/items/families.c; combat/turn.c
 * chooses its place in the chain and retains the useItem/AfterUseItem path.
 *
 * The functions are pure and take the item the holder has now (1 + id, 0 for
 * none: items/held.h's dfi_item_code, which knows what is used up or taken), so that
 * a test can run every item against every type (tests/items/test_item_family.c). No
 * item means no family.
 */
#include <stdbool.h>
#include <stdint.h>

#include "core/modifier.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"

/* The modifiers, in 4096ths (data/items.ts: chainModify([4915, 4096]) in the
 * onBasePower of every type booster, chainModify(0.5) in the
 * onSourceModifyDamage of every resist berry). */
#define DFI_TYPE_BOOSTER_MODIFIER 4915u
#define DFI_RESIST_BERRY_MODIFIER 2048u

/* The family row of an item, given as 1 + id (0 = no item: what a member holds now, the used-up and the lost item
 * included, is the caller's: items/held.h's dfi_item_code); the row of no family without one. The member invariant bounds
 * the item id, so the guard on it only keeps the read in the table. */
static inline dfi_item_family dfi_held_family(uint32_t item)
{
    dfi_item_family none = {DFI_ITEM_FAMILY_NONE, DFI_FAMILY_PARAM_NONE};
    if (item == 0u || item > DFI_POOL_ITEM_COUNT) {
        return none;
    }
    return dfi_pool_item_family[item - 1u];
}

/* A type booster: its holder's move of the booster's type (BasePower x4915/4096). */
static inline bool dfi_type_booster_applies(uint32_t user_item, uint32_t move_type)
{
    const dfi_item_family held = dfi_held_family(user_item);
    return held.family == DFI_ITEM_FAMILY_TYPE_BOOSTER && move_type == held.type;
}

/* A resist berry: a hit of the berry's type on its holder, when the hit is
 * super effective (type_mod above the neutral DFI_BIAS6); the Normal berry
 * (Chilan) halves any Normal hit, as the handler asks for the type alone and
 * a Normal hit is never super effective (data/items.ts, chilanberry). */
static inline bool dfi_resist_berry_applies(uint32_t target_item, uint32_t move_type, uint32_t type_mod)
{
    const dfi_item_family held = dfi_held_family(target_item);
    return held.family == DFI_ITEM_FAMILY_RESIST_BERRY && move_type == held.type &&
           (type_mod > DFI_BIAS6 || held.type == DFI_TYPE_NORMAL);
}

/* isBerry (batch I2, decision 0015 entry 5eg): the item, given as 1 + id, is a berry of data/items.ts (the generated
 * column, from the base entry). It decides the eaten flag of an item's end and what Bug Bite takes. */
static inline bool dfi_item_is_berry(uint32_t item)
{
    return item != 0u && item <= DFI_POOL_ITEM_COUNT && dfi_pool_item_berry[item - 1u] != 0u;
}

/* A cure berry's one condition (batch I2, the CURE_BERRY family; data/items.ts Cheri, Chesto, Pecha, Rawst, Aspear: onUpdate
 * and onEat test `pokemon.status === X`, Pecha psn or tox) against a status of the eater: the status it cures. The confusion
 * of Persim Berry (DFI_FAMILY_CURE_CONFUSION) is a volatile, never a status. */
static inline bool dfi_cure_berry_status(uint32_t cure, uint32_t status)
{
    switch (cure) {
    case DFI_FAMILY_CURE_SLP:
        return status == DFI_STATUS_SLP;
    case DFI_FAMILY_CURE_PAR:
        return status == DFI_STATUS_PAR;
    case DFI_FAMILY_CURE_PSN:
        return status == DFI_STATUS_PSN || status == DFI_STATUS_TOX;
    case DFI_FAMILY_CURE_BRN:
        return status == DFI_STATUS_BRN;
    case DFI_FAMILY_CURE_FRZ:
        return status == DFI_STATUS_FRZ;
    default:
        return false;
    }
}

/* What an eaten berry's onEat cures on its eater (batch I2): Lum Berry (step G47, data/items.ts:3554-3557) any status and
 * the confusion; a cure berry its one condition, only when the eater has it (the onEat test). `confused` is the eater's
 * confusion now. Every other item cures nothing. */
static inline void dfi_berry_cures(uint32_t item, uint32_t status, bool confused, bool *cure_status, bool *cure_confusion)
{
    const dfi_item_family held = dfi_held_family(item);
    const bool lum = item == 1u + DFI_ITEM_LUMBERRY;
    const bool cure = held.family == DFI_ITEM_FAMILY_CURE_BERRY;
    *cure_status = (lum && status != DFI_STATUS_NONE) || (cure && dfi_cure_berry_status(held.type, status));
    *cure_confusion = confused && (lum || (cure && held.type == DFI_FAMILY_CURE_CONFUSION));
}

/* The HP an HP berry heals its eater (batch I2): Sitrus Berry a quarter of the maximum (data/items.ts:5760-5762,
 * `this.heal(pokemon.baseMaxhp / 4)`, truncated), a heal berry (HEAL_BERRY, Oran Berry) the amount of its parameter; 0 for
 * every other item. Both are eaten at half HP or less, after TryHeal (Heal Block). */
static inline uint32_t dfi_hp_berry_heal(uint32_t item, uint32_t hp_max)
{
    const dfi_item_family held = dfi_held_family(item);
    if (item == 1u + DFI_ITEM_SITRUSBERRY) {
        return hp_max / 4u;
    }
    return held.family == DFI_ITEM_FAMILY_HEAL_BERRY ? (uint32_t)held.type : 0u;
}

/* Focus Sash (data/items.ts:2275-2282, onDamage priority -40): the holder is
 * at full HP, the damage is at least its HP, and the effect of the damage is a
 * Move (effect.effectType === 'Move'). Its damage events are, at the pin:
 *   - a move's hit (spreadMoveHit, a Move),
 *   - the confusion self-hit, which passes { id: 'confused', effectType:
 *     'Move', type: '???' } (data/conditions.ts:193-194), so a Move too;
 *   - not Recoil and not Drain (conditions built by getByID, whose
 *     effectType is 'Condition': sim/dex-conditions.ts:650 and :698-702),
 *     nor Struggle's recoil (strugglerecoil skips the event,
 *     sim/battle.ts:2115), nor items (Life Orb, Rocky Helmet: effectType
 *     'Item', sim/dex-items.ts:110), nor status and weather damage
 *     (effectType 'Status' and 'Weather', sim/dex-conditions.ts:650).
 * The callers are the two places that deal a Move's damage in turn.c; the
 * item is used and the damage becomes hp - 1 there. */
static inline bool dfi_focus_sash_saves(uint32_t holder_item, const dfi_member *holder, uint32_t damage)
{
    return holder != NULL && holder_item == 1u + DFI_ITEM_FOCUSSASH && holder->hp == holder->hp_max &&
           damage >= holder->hp;
}

#endif
