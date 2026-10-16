#ifndef DUOFORGE_COMBAT_ABILITIES_MEGA_SOL_H
#define DUOFORGE_COMBAT_ABILITIES_MEGA_SOL_H

/* Private ability implementation (restructure step 4, forms): Mega Sol. Split from src/combat/turn.c@342770b3;
 * included by turn.c where the function stood, so its dependencies and the turn flow are unchanged. */
#include "combat/run_internal.h"

/* Mega Sol (step G59, data/abilities.ts:2558-2569): Pokemon#effectiveWeather (sim/pokemon.ts:2190-2198) reads the weather as sun for
 * the effects of a Move, a Weather or Mega Sol itself while the Mega Sol holder is the active Pokemon, whatever the field's weather
 * is. The moves that read the weather through it, and that the engine reads from the field: Solar Beam (its charge, sunnyday's
 * prepare test, and its onBasePower, data/moves.ts:17224-17258), Weather Ball (its type and power, :20700-20730), and Thunder and
 * Hurricane (their accuracy, :19447-19460 and :20861-20866). With the field in sun the two readings agree; otherwise the move is
 * refused (E_UNSUPPORTED), not modelled. The Mega Sol holder's legal moves of those kinds are the marked ones (Meganium's
 * Solar Beam and Weather Ball; Thunder and Hurricane are not in its learnset). Refused at the move's own use, after BeforeMove. */
static bool dfi_mega_sol_refused(const dfi_run *r, uint32_t user, const dfi_move_data *md)
{
    if (!dfi_ability(r->b, dfi_at(r->b, user), DFI_ABILITY_MEGASOL)) {
        return false;
    }
    const bool reads = md->special == DFI_SPECIAL_SOLAR_BEAM || md->special == DFI_SPECIAL_WEATHER_BALL ||
                       md->special == DFI_SPECIAL_THUNDER || md->special == DFI_SPECIAL_HURRICANE;
    if (dfi_weather_suppressed(r)) {
        /* Step G79 (lead decision): with a Cloud Nine holder standing, the weather-reading moves of a Mega Sol user are
         * refused, Electro Shot too: the -activate line of Mega Sol (sim/pokemon.ts:2193) is not modelled. */
        return reads || md->special == DFI_SPECIAL_ELECTRO_SHOT;
    }
    return reads && r->b->weather != DFI_WEATHER_SUN;
}

#endif
