#ifndef DUOFORGE_COMBAT_MOVE_RULES_H
#define DUOFORGE_COMBAT_MOVE_RULES_H
/*
 * Rules that several moves share, read by the turn code and by the request
 * (step G10 of the content expansion). They decide from the handler id of the
 * move (the special column) or from the move extra column of the pool
 * tables; no move is named here.
 */
#include <stdbool.h>
#include <stdint.h>

#include "data/pool_tables.h"

/* Fake Out and First Impression: usable on the first move action since the
 * user entered only. The request disables the move once the user has acted
 * (onDisableMove, data/mods/champions/moves.ts:354-361 and :386-394), and the
 * move itself fails with [-fail] if it is used after that (onTry:
 * activeMoveActions > 1, data/moves.ts:5482-5487 and the Fake Out twin). */
static inline bool dfi_move_first_turn_only(const dfi_move_data *md)
{
    return md->special == DFI_SPECIAL_FAKE_OUT || md->special == DFI_SPECIAL_FIRST_IMPRESSION;
}

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

#endif
