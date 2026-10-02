#ifndef DUOFORGE_COMBAT_ITEM_FAMILY_H
#define DUOFORGE_COMBAT_ITEM_FAMILY_H
/*
 * The item families of decision 0015 as the battle reads them: the type
 * booster and the resist berry. An item has the family and the type that the
 * family columns of data/pool_tables.h give it, and the rule below reads only
 * that: no item is named here. What each rule does to the damage (the
 * modifier, its place in the chain, the eat and weaken events) is in
 * combat/turn.c.
 *
 * The functions are pure and take the item the holder has now (1 + id, 0 for
 * none: turn.c's dfi_item_code, which knows what is used up or taken), so that
 * a test can run every item against every type (tests/test_item_family.c). No
 * item means no family.
 */
#include <stdbool.h>
#include <stdint.h>

#include "core/modifier.h"
#include "data/pool_tables.h"
#include "state/battle_internal.h"

/* The modifiers, in 4096ths (data/items.ts: chainModify([4915, 4096]) in the
 * onBasePower of every type booster, chainModify(0.5) in the
 * onSourceModifyDamage of every resist berry). */
#define DFI_TYPE_BOOSTER_MODIFIER 4915u
#define DFI_RESIST_BERRY_MODIFIER 2048u

/* The family row of an item, given as 1 + id (0 = no item: what a member holds now, the used-up and the lost item
 * included, is the caller's: turn.c's dfi_item_code); the row of no family without one. The member invariant bounds
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
