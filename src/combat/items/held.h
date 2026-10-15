#ifndef DUOFORGE_COMBAT_ITEMS_HELD_H
#define DUOFORGE_COMBAT_ITEMS_HELD_H

/* Hot held-item access stays visible to every caller, including without IPO. */
#include "state/battle_internal.h"

/* The item a member holds now, stored as 1 + id (0 = none): the one the member's sheet says unless it has been used
 * up, or the one that the POOL tail's item_now holds for it (zero under every other kind, and zero unless something
 * took or changed the item: DFI_TAIL_ITEM_NONE after a Knock Off, an item id + 1 after a Trick, which nothing does
 * yet). Every rule of the turn code reads the item through this, never through dfi_member.item, which is the sheet's
 * (and what the Mega Evolution reads: a Mega Stone is never taken from its own species). `m` is a member of `b`; no
 * heap, one tail read for a member that is found on a side. */
static inline uint32_t dfi_item_code(const struct duoforge_battle *b, const dfi_member *m)
{
    if (m == NULL || m->item_consumed != 0u) {
        return 0u; /* used up, whichever item it was */
    }
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const dfi_member *first = &b->sides[s].members[0];
        if (m >= first && m < first + DUOFORGE_MAX_ROSTER) {
            const uint32_t now = b->tail.sides[s].item_now[m - first];
            if (now == DFI_TAIL_ITEM_NONE) {
                return 0u;
            }
            if (now != 0u) {
                return now;
            }
            break;
        }
    }
    return m->item;
}

/* The member holds item `id` and has not used it up or lost it (items are stored as 1 + id). */
static inline bool dfi_holds(const struct duoforge_battle *b, const dfi_member *m, uint32_t id)
{
    return m != NULL && dfi_item_code(b, m) == 1u + id;
}

/* Step K5 (#475, decision 0015 5dm): the item EFFECTS of a member. Magic Room (data/moves.ts:10754-10797) makes every Pokemon ignore
 * its item (sim/pokemon.ts:879-885 ignoringItem, the pseudo weather test at :882): hasItem() is false and no item handler runs
 * (sim/battle.ts:609 singleEvent, :877 runEvent), while getItem() and takeItem() are untouched. So the rules that run an item's
 * effect (a berry, a boost, the Choice lock, Life Orb, Air Balloon, a herb) ask dfi_holds_effect / dfi_item_effect_code, and the rules
 * that move or read the item itself (Knock Off, Trick, Thief, Covet, Bug Bite, Frisk, Poltergeist, Acrobatics, the Mega Stone, the
 * removal of a Choice lock) keep dfi_holds / dfi_item_code, which see the item whatever the room says. Every effect site is called
 * for a member on the field, so the benched-holder half of ignoringItem (sim/pokemon.ts:881) holds by construction. Persistent,
 * Klutz, Embargo and Primal Orbs are not in the pool. */
static inline bool dfi_items_suppressed(const struct duoforge_battle *b)
{
    return b->tail.magic_room_turns != 0u;
}

/* dfi_item_code for an item's EFFECT: 0 while Magic Room is up. */
static inline uint32_t dfi_item_effect_code(const struct duoforge_battle *b, const dfi_member *m)
{
    return dfi_items_suppressed(b) ? 0u : dfi_item_code(b, m);
}

/* dfi_holds for an item's EFFECT (Pokemon.hasItem): false while Magic Room is up. */
static inline bool dfi_holds_effect(const struct duoforge_battle *b, const dfi_member *m, uint32_t id)
{
    return !dfi_items_suppressed(b) && dfi_holds(b, m, id);
}

/* singleEvent TakeItem of the item (data/items.ts, the onTakeItem of the Mega Stones: they refuse their own species,
 * Floettite's variant at :2194 gives the same result; the Champions mod changes none): a Pokemon that holds an item
 * that can be taken from it. The only items of the pool with an onTakeItem are the Mega Stones, and takeItem() asks
 * with the Pokemon itself as the source, so a Mega Stone on another species, and every other item, is taken.
 * dfi_member.mega_capable is exactly "holds the stone of its own base forme" (the member invariant) and stays after
 * the Mega Evolution, as the Pokemon's baseSpecies does. */
static inline bool dfi_item_takeable(const struct duoforge_battle *b, const dfi_member *m)
{
    const uint32_t item = dfi_item_code(b, m);
    return item != 0u && !(m->mega_capable != 0u && item == m->item);
}

#endif
