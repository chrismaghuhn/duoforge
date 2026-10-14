#ifndef DUOFORGE_COMBAT_FIELD_DURATION_H
#define DUOFORGE_COMBAT_FIELD_DURATION_H

/* Private field-family implementation. Included by turn.c at the
 * existing helper dependency boundary; turn flow owns evaluation order. */
#include "combat/run_internal.h"

#include "combat/items/held.h"

/* Step G55: the turns that a weather or terrain lasts when its setter starts it. Field.setWeather and Field.setTerrain call the
 * durationCallback with the setter as the source (sim/field.ts:78-81 and :147-149; a setter from an ability has the holder as
 * the event target, :41-42): 8 while the setter holds the lengthening item (the rock of the weather, or Terrain Extender for a
 * terrain: data/moves.ts terrains), else 5. The item is read when the field starts, as the callback reads it. */
static inline uint32_t dfi_field_start_turns(const struct duoforge_battle *b, const dfi_member *setter, uint32_t item)
{
    return dfi_holds(b, setter, item) ? DFI_FIELD_TURNS_EXTENDED_MAX : DFI_FIELD_TURNS_MAX;
}

#endif
