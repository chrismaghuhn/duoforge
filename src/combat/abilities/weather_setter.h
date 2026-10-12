#ifndef DUOFORGE_COMBAT_ABILITIES_WEATHER_SETTER_H
#define DUOFORGE_COMBAT_ABILITIES_WEATHER_SETTER_H

#include "combat/abilities/current.h"

/* The weather that an ability sets on entry (onStart, setWeather) as a
 * state value DFI_WEATHER_*, or DFI_WEATHER_NONE when it is no weather
 * setter. The column holds a family code, so each code is named here; a code
 * that is none of them is no setter, which the table test excludes. */
static inline uint32_t dfi_weather_set_by_fam(dfi_ability_family fam)
{
    if (fam.family != DFI_ABILITY_FAMILY_WEATHER_SETTER) {
        return DFI_WEATHER_NONE;
    }
    return fam.param == DFI_FAMILY_WEATHER_RAIN   ? DFI_WEATHER_RAIN
           : fam.param == DFI_FAMILY_WEATHER_SUN  ? DFI_WEATHER_SUN
           : fam.param == DFI_FAMILY_WEATHER_SAND ? DFI_WEATHER_SAND
           : fam.param == DFI_FAMILY_WEATHER_SNOW ? DFI_WEATHER_SNOW
                                                  : DFI_WEATHER_NONE;
}

#endif
