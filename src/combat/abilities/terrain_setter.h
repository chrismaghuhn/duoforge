#ifndef DUOFORGE_COMBAT_ABILITIES_TERRAIN_SETTER_H
#define DUOFORGE_COMBAT_ABILITIES_TERRAIN_SETTER_H

#include "combat/abilities/current.h"

/* The terrain that an ability sets on entry (onStart, setTerrain) as a state
 * value DFI_TERRAIN_*, or DFI_TERRAIN_NONE. */
static inline uint32_t dfi_terrain_set_by_fam(dfi_ability_family fam)
{
    if (fam.family != DFI_ABILITY_FAMILY_TERRAIN_SETTER) {
        return DFI_TERRAIN_NONE;
    }
    return fam.param == DFI_FAMILY_TERRAIN_GRASSY    ? DFI_TERRAIN_GRASSY
           : fam.param == DFI_FAMILY_TERRAIN_PSYCHIC ? DFI_TERRAIN_PSYCHIC
           : fam.param == DFI_FAMILY_TERRAIN_ELECTRIC ? DFI_TERRAIN_ELECTRIC
           : fam.param == DFI_FAMILY_TERRAIN_MISTY    ? DFI_TERRAIN_MISTY
                                                      : DFI_TERRAIN_NONE;
}

#endif
