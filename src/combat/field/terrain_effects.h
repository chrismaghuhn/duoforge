#ifndef DUOFORGE_COMBAT_FIELD_TERRAIN_EFFECTS_H
#define DUOFORGE_COMBAT_FIELD_TERRAIN_EFFECTS_H

/* Private field-family implementation. Included by turn.c at the
 * existing helper dependency boundary; turn flow owns evaluation order. */
#include "combat/run_internal.h"

/* Steel Roller's onHit (step G34, data/moves.ts:17893-17913): Field.clearTerrain after the damage of the hit, once for the
 * move: -fieldend|move: the terrain, then the TerrainChange event of the seeds on the field. Step G25 extends it to Electric
 * and Misty Terrain: the FIELD_END detail is the one of the terrain that ends (dfi_terrain_field_detail, as at the end of its
 * turns), and the converter reads Misty Terrain's line, which has no "move: " (data/moves.ts onFieldEnd). */
static inline duoforge_status dfi_clear_terrain(dfi_run *r)
{
    struct duoforge_battle *b = r->b;
    if (b->terrain == DFI_TERRAIN_NONE) {
        return DUOFORGE_OK;
    }
    const uint32_t ended = b->terrain;
    b->terrain = (uint8_t)DFI_TERRAIN_NONE;
    b->terrain_turns = 0u;
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_FIELD_END, DUOFORGE_NO_POSITION);
    e.detail = (uint8_t)dfi_terrain_field_detail(ended); /* wide-operands-reviewed: < 6 */
    dfi_emit(r, &e); /* [-fieldend] */
    return dfi_terrain_change(r);
}

#endif
