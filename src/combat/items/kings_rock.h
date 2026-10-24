#ifndef DUOFORGE_COMBAT_ITEMS_KINGS_ROCK_H
#define DUOFORGE_COMBAT_ITEMS_KINGS_ROCK_H

/*
 * King's Rock (batch I1, decision 0015 entry 5ef; data/items.ts:3209-3231, no Champions entry) as predicates on the holder and the
 * move's data, so that the white-box test tests/items/test_move_hook_items.c can run them on every move of the pool. Internal
 * header: no public value, no state.
 *
 * The pinned onModifyMove (priority -1) adds `{chance: 10, volatileStatus: 'flinch'}` to the secondaries of a move that is not
 * Status, unless one of its secondaries is a flinch already. Sheer Force's onModifyMove (priority 0) runs first and deletes the
 * secondaries of a move it strips (dfi_sf_strips_move), so for a Sheer Force holder a stripped move has no flinch secondary left
 * and gets the item's. The engine's flinch secondaries are the generic column (sec_kind VOLATILE, sec_param FLINCH: Fake Out,
 * Rock Slide, Upper Hand, ...) and Ice Fang's own code (freeze, then flinch); the generator checks this against the pin for every
 * pool move (tools/datagen/pool_families.js checkI1). The added secondary rolls on the secondaries' draw site (SECONDARY,
 * random(100)) after the move's own secondaries of the same target, as secondaries() loops (sim/battle-actions.ts:1336-1354).
 */
#include <stdbool.h>
#include <stdint.h>

#include "combat/sheer_force.h"
#include "data/formats/reg-mc/closure_tables.h"
#include "data/formats/reg-mc/pool_tables.h"

/* The chance of the added flinch (data/items.ts:3223-3226); Serene Grace, which would double it, is not marked. */
#define DFI_KINGS_ROCK_CHANCE 10u

/* True when one of the move's own secondaries is a flinch (before any Sheer Force). */
static inline bool dfi_move_flinch_secondary(const dfi_move_data *md)
{
    return (md->sec_chance != 0u && md->sec_kind == DFI_SECONDARY_VOLATILE && md->sec_param == DFI_VOLATILE_FLINCH) ||
           md->special == DFI_SPECIAL_ICE_FANG;
}

/* True when the holder's King's Rock adds its flinch secondary to the move: a damaging move whose secondaries, after the
 * holder's Sheer Force, hold no flinch. */
static inline bool dfi_kings_rock_adds(bool holder_kings_rock, bool holder_sheer_force, bool status_move, const dfi_move_data *md)
{
    return holder_kings_rock && !status_move &&
           (dfi_sf_strips_move(holder_sheer_force, md) || !dfi_move_flinch_secondary(md));
}

#endif
