#ifndef DUOFORGE_COMBAT_MOVES_SPECIAL_HANDLERS_H
#define DUOFORGE_COMBAT_MOVES_SPECIAL_HANDLERS_H

#include <stdbool.h>
#include <stdint.h>

#include "combat/generated/move_handlers.h"

/* The late guard runs only after the early move handlers and generic status
 * handling. A false row is not an unsupported mark: it may be an early handler.
 * Unknown ids retain the old predicate's explicit failure. */
static inline bool dfi_move_special_has_handler(uint32_t special)
{
    return special < DFI_SPECIAL_COUNT && dfi_special_has_handler[special] != 0u;
}

/* These specials bypass generic status handling for their own target hit.
 * Primary statuses, primary target boosts, force-switch and heal columns remain
 * the turn's separate conditions in their original positions. */
static inline bool dfi_move_special_status_hit(uint32_t special)
{
    return special < DFI_SPECIAL_COUNT && dfi_special_status_hit[special] != 0u;
}

#endif
