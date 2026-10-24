#ifndef DUOFORGE_COMBAT_MOVES_WEIGHT_POWER_H
#define DUOFORGE_COMBAT_MOVES_WEIGHT_POWER_H

#include <stdbool.h>
#include <stdint.h>

#include "data/formats/reg-mc/pool_tables.h"

/* Grass Knot and Low Kick: the base power follows the target's weight in
 * hectograms (basePowerCallback, data/moves.ts:10446-10464 for Low Kick, the
 * same table as Grass Knot's). */
static inline bool dfi_move_power_by_weight(const dfi_move_data *md)
{
    return md->special == DFI_SPECIAL_GRASS_KNOT || md->special == DFI_SPECIAL_LOW_KICK;
}

static inline uint32_t dfi_weight_power(uint32_t weight_hg)
{
    return weight_hg >= 2000u ? 120u
           : weight_hg >= 1000u ? 100u
           : weight_hg >= 500u  ? 80u
           : weight_hg >= 250u  ? 60u
           : weight_hg >= 100u  ? 40u
                                : 20u;
}

/* Heavy Slam's basePowerCallback (step G86, data/moves.ts:8533-8552): the user's weight against the target's, both as
 * getWeight() in hectograms (Math.max(1, weighthg), sim/pokemon.ts:685-688); the ratio tests are the pin's, in integers. */
static inline uint32_t dfi_heavy_slam_power(uint32_t user_hg, uint32_t target_hg)
{
    const uint32_t user = user_hg < 1u ? 1u : user_hg;
    const uint32_t target = target_hg < 1u ? 1u : target_hg;
    return user >= target * 5u ? 120u
           : user >= target * 4u ? 100u
           : user >= target * 3u ? 80u
           : user >= target * 2u ? 60u
                                 : 40u;
}

#endif
