#ifndef DUOFORGE_COMBAT_MOVES_OHKO_H
#define DUOFORGE_COMBAT_MOVES_OHKO_H

#include <stdbool.h>
#include <stdint.h>

#include "data/formats/reg-mc/pool_tables.h"

/* The OHKO moves: Sheer Cold (ohko 'Ice', step G64) and the moves with ohko true (Fissure, Guillotine, Horn Drill; step G92).
 * Their accuracy and immunity steps are the same (hitStepAccuracy's ohko branch); they differ in the accuracy (dfi_ohko_accuracy)
 * and in the Ice-type immunity, which only Sheer Cold has. */
static inline bool dfi_is_ohko(const dfi_move_data *md)
{
    return md->special == DFI_SPECIAL_SHEER_COLD || md->special == DFI_SPECIAL_OHKO;
}

#endif
