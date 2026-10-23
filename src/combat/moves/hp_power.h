#ifndef DUOFORGE_COMBAT_MOVES_HP_POWER_H
#define DUOFORGE_COMBAT_MOVES_HP_POWER_H

#include <stdbool.h>
#include <stdint.h>

#include "data/formats/reg-mc/pool_tables.h"

/* Hard Press's basePowerCallback (step G86, data/moves.ts:8137-8150): bp = floor(floor((100 * (100 * floor(hp * 4096 / maxhp))
 * + 2048 - 1) / 4096) / 100) || 1, on the target's current HP. The integer forms are exact here (hp * 4096 and the sums fit). */
static inline uint32_t dfi_hard_press_power(uint32_t hp, uint32_t hp_max)
{
    const uint32_t scaled = (hp * 4096u) / hp_max;               /* floor(hp * 4096 / maxHP), hp <= hp_max */
    const uint32_t bp = ((100u * (100u * scaled)) + 2048u - 1u) / 4096u / 100u;
    return bp == 0u ? 1u : bp;
}

#endif
