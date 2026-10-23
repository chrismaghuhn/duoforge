#ifndef DUOFORGE_COMBAT_MOVES_FIRST_TURN_ONLY_H
#define DUOFORGE_COMBAT_MOVES_FIRST_TURN_ONLY_H

#include <stdbool.h>
#include <stdint.h>

#include "data/formats/reg-mc/pool_tables.h"

/* Fake Out and First Impression: usable on the first move action since the
 * user entered only. The request disables the move once the user has acted
 * (onDisableMove, data/mods/champions/moves.ts:354-361 and :386-394), and the
 * move itself fails with [-fail] if it is used after that (onTry:
 * activeMoveActions > 1, data/moves.ts:5482-5487 and the Fake Out twin). */
static inline bool dfi_move_first_turn_only(const dfi_move_data *md)
{
    return md->special == DFI_SPECIAL_FAKE_OUT || md->special == DFI_SPECIAL_FIRST_IMPRESSION;
}

#endif
