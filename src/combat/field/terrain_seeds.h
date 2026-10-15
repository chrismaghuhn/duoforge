#ifndef DUOFORGE_COMBAT_FIELD_TERRAIN_SEEDS_H
#define DUOFORGE_COMBAT_FIELD_TERRAIN_SEEDS_H

/* Private field-family implementation. Included by turn.c at the
 * existing helper dependency boundary; turn flow owns evaluation order. */
#include "combat/run_internal.h"

/* The terrain seeds (data/items.ts:2595-2614 Grassy Seed, :4903-4922 Psychic Seed, :1799-1818 Electric Seed,
 * :4200-4219 Misty Seed; the generator checks that each is Grassy Seed for its terrain and its stat): onSwitchInPriority
 * -1, onStart (not ignoringItem, the terrain is up) and onTerrainChange (the terrain is up) both call useItem, and the
 * item's boosts raise one stage of one stat: Defense for the Grassy and Electric Seeds, Special Defense for the Psychic and
 * Misty Seeds. The terrain a seed waits for, or DFI_TERRAIN_NONE for a member that holds none, or while Magic Room is up (step K5:
 * an item's handlers are not run for a Pokemon that ignores its item, sim/battle.ts:877). */
static inline uint32_t dfi_seed_terrain(const struct duoforge_battle *b, const dfi_member *m)
{
    if (dfi_holds_effect(b, m, DFI_ITEM_GRASSYSEED)) {
        return DFI_TERRAIN_GRASSY;
    }
    if (dfi_holds_effect(b, m, DFI_ITEM_PSYCHICSEED)) {
        return DFI_TERRAIN_PSYCHIC;
    }
    if (dfi_holds_effect(b, m, DFI_ITEM_ELECTRICSEED)) {
        return DFI_TERRAIN_ELECTRIC;
    }
    if (dfi_holds_effect(b, m, DFI_ITEM_MISTYSEED)) {
        return DFI_TERRAIN_MISTY;
    }
    return DFI_TERRAIN_NONE;
}

/* A terrain seed (useItem): its stat +1 once, when its terrain is up: Grassy Seed's and Electric Seed's Defense, Psychic
 * Seed's and Misty Seed's Special Defense. A holder that fainted does nothing. */
static inline void dfi_terrain_seed(dfi_run *r, uint32_t flat)
{
    static const uint8_t def_up[DFI_STAT_STAGE_COUNT] = {6u, 7u, 6u, 6u, 6u, 6u, 6u};
    static const uint8_t spd_up[DFI_STAT_STAGE_COUNT] = {6u, 6u, 6u, 7u, 6u, 6u, 6u};
    const dfi_member *m = dfi_at(r->b, flat);
    if (m == NULL || m->hp == 0u) {
        return;
    }
    const uint32_t terrain = dfi_seed_terrain(r->b, m);
    if (terrain == DFI_TERRAIN_NONE || r->b->terrain != terrain) {
        return;
    }
    const bool defense = terrain == DFI_TERRAIN_GRASSY || terrain == DFI_TERRAIN_ELECTRIC;
    const uint32_t item = terrain == DFI_TERRAIN_GRASSY     ? DFI_ITEM_GRASSYSEED
                          : terrain == DFI_TERRAIN_PSYCHIC  ? DFI_ITEM_PSYCHICSEED
                          : terrain == DFI_TERRAIN_ELECTRIC ? DFI_ITEM_ELECTRICSEED
                                                            : DFI_ITEM_MISTYSEED;
    dfi_use_item(r, flat);
    dfi_boost(r, flat, defense ? def_up : spd_up, DFI_POSITIONS,
              dfi_effect(DUOFORGE_CAUSE_ITEM, 1u + item, DFI_BOOST_PRIMARY));
}

/* eachEvent('TerrainChange'): every terrain seed on the field in
 * eachEvent's order; a seed acts only while its terrain is up. */
static inline duoforge_status dfi_terrain_change(dfi_run *r)
{
    uint32_t bearers = 0u;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        bearers |= dfi_seed_terrain(r->b, dfi_at(r->b, flat)) != DFI_TERRAIN_NONE ? 1u << flat : 0u;
    }
    if (bearers == 0u) {
        return DUOFORGE_OK;
    }
    uint32_t list[DFI_POSITIONS] = {0u, 0u, 0u, 0u};
    uint32_t n = 0u;
    const duoforge_status st = dfi_each_order(r, bearers, list, &n);
    if (st != DUOFORGE_OK) {
        return st;
    }
    for (uint32_t i = 0u; i < n; ++i) {
        dfi_terrain_seed(r, list[i]);
    }
    return DUOFORGE_OK;
}

#endif
