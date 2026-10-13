#ifndef DUOFORGE_COMBAT_SECONDARY_ROLLS_H
#define DUOFORGE_COMBAT_SECONDARY_ROLLS_H

/*
 * The thresholds of the step G44 secondaries, as one-line predicates on the roll of a SECONDARY draw (random(100)), so that
 * the white-box test duoforge.state.pool_g44 checks both edges of each. Internal header: no public value, no state.
 *
 * Tri Attack (data/moves.ts:19845-19864): the secondary of chance 20 passes when the roll is below 20, the reference's
 * randomChance(20, 100) of sim/battle-actions.ts:1336-1354. Ice Fang's 10 percent rolls are checked in turn.c as they are.
 */
#include <stdbool.h>
#include <stdint.h>

static inline bool dfi_tri_attack_chance_hit(uint32_t roll)
{
    return roll < 20u;
}

#endif
