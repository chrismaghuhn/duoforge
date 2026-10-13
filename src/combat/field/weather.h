#ifndef DUOFORGE_COMBAT_FIELD_WEATHER_H
#define DUOFORGE_COMBAT_FIELD_WEATHER_H

/* Private field-family implementation. Included by turn.c at the
 * existing helper dependency boundary; turn flow owns evaluation order. */
#include "combat/run_internal.h"

/* Step G55: the rock that lengthens the weather w (data/conditions.ts durationCallback: Rain Dance with Damp Rock, Sunny Day
 * with Heat Rock, Sandstorm with Smooth Rock, Snowscape with Icy Rock; Champions changes none). */
static inline uint32_t dfi_weather_rock(uint32_t w)
{
    switch (w) {
    case DFI_WEATHER_RAIN:
        return DFI_ITEM_DAMPROCK;
    case DFI_WEATHER_SUN:
        return DFI_ITEM_HEATROCK;
    case DFI_WEATHER_SAND:
        return DFI_ITEM_SMOOTHROCK;
    default:
        return DFI_ITEM_ICYROCK; /* DFI_WEATHER_SNOW, the last weather of the POOL kinds */
    }
}

/* Cloud Nine suppresses the weather while a holder stands (data/abilities.ts:543-562; Field.suppressingWeather,
 * sim/field.ts:106-116). A holder stands while it is not fainted (`!pokemon.fainted`, field.ts:109). The flag is set when
 * faintMessages shows the faint (sim/battle.ts:2564), and the holder's End (:2556, the ability ends) comes in the same
 * loop: a position with HP 0 stops suppressing once its faint is shown, and a faint that is still queued keeps suppressing
 * (dfi_faint_pending). A switch-out ends the holder before the replacement (sim/battle-actions.ts:103), which here is the
 * occupant that changes. The ability is read as it is now (Trace, Skill Swap and Mega Evolution change it). */
static inline bool dfi_weather_suppressed(const dfi_run *r)
{
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        const dfi_member *m = dfi_at(r->b, flat);
        if (dfi_ability(r->b, m, DFI_ABILITY_CLOUDNINE) && (m->hp != 0u || dfi_faint_pending(r, flat))) {
            return true;
        }
    }
    return false;
}

/* Field.effectiveWeather (sim/field.ts:101-104): the weather the field reads, NONE while it is suppressed. */
static inline uint32_t dfi_field_weather(const dfi_run *r)
{
    return dfi_weather_suppressed(r) ? (uint32_t)DFI_WEATHER_NONE : (uint32_t)r->b->weather;
}

/* Pokemon#effectiveWeather (sim/pokemon.ts:2190-2212) as the active user's move reads it: sun while the user holds Mega Sol
 * and the reading effect is a Move, a Weather or Mega Sol itself (step G59; `move_reads` is false for Electro Shot, which
 * the pin excludes by id), whatever the field is. Otherwise the field's weather. */
static inline uint32_t dfi_move_weather(const dfi_run *r, const dfi_member *user, bool move_reads)
{
    if (move_reads && dfi_ability(r->b, user, DFI_ABILITY_MEGASOL)) {
        return DFI_WEATHER_SUN;
    }
    return dfi_field_weather(r);
}

/* Whether the member has the Speed ability of the weather that is up: Swift Swim in rain, Chlorophyll in sun, Sand Rush
 * in a sandstorm, Slush Rush in snow (step G22; the callbacks are cited at dfi_speed_key). The weather is the
 * battle's: Hail is not in the format, and Primordial Sea and Desolate Land (also named by the Swift Swim and
 * Chlorophyll handlers) are not weathers of the state. */
static inline bool dfi_weather_speed_ability(const dfi_run *r, const dfi_member *m)
{
    /* The ability reads the field (pokemon.effectiveWeather with its own ability as the source: no Mega Sol, and
     * Cloud Nine suppresses it, field.ts:101-104). */
    const uint32_t w = dfi_field_weather(r);
    return (w == DFI_WEATHER_RAIN && dfi_ability(r->b, m, DFI_ABILITY_SWIFTSWIM)) ||
           (w == DFI_WEATHER_SUN && dfi_ability(r->b, m, DFI_ABILITY_CHLOROPHYLL)) ||
           (w == DFI_WEATHER_SAND && dfi_ability(r->b, m, DFI_ABILITY_SANDRUSH)) ||
           (w == DFI_WEATHER_SNOW && dfi_ability(r->b, m, DFI_ABILITY_SLUSHRUSH));
}

#endif
