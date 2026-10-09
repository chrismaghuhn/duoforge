#ifndef DUOFORGE_COMBAT_POWER_TRIP_H
#define DUOFORGE_COMBAT_POWER_TRIP_H

/*
 * Power Trip's positiveBoosts (step G44, sim/pokemon.ts:1201-1208): the sum of the user's positive stages over every
 * stat stage the battle keeps (attack, defense, special attack, special defense, speed, accuracy and evasion). A stored
 * stage is biased by DFI_STAGE_NEUTRAL, so a stored value above it is a positive stage. A negative stage adds nothing.
 * turn.c's basePowerCallback for Power Trip is 20 + 20 times this sum.
 *
 * Internal header: no public value, no state. The white-box test duoforge.state.pool_g44 calls it at every stat.
 */
#include <stdint.h>

#include "state/battle_internal.h"

static inline uint32_t dfi_power_trip_positive_stages(const uint8_t stages[DFI_STAT_STAGE_COUNT])
{
    uint32_t positive = 0u;
    for (uint32_t s = 0u; s < DFI_STAT_STAGE_COUNT; ++s) {
        if (stages[s] > DFI_STAGE_NEUTRAL) {
            positive += (uint32_t)stages[s] - DFI_STAGE_NEUTRAL;
        }
    }
    return positive;
}

#endif
