#ifndef DUOFORGE_COMBAT_FIELD_TRICK_ROOM_H
#define DUOFORGE_COMBAT_FIELD_TRICK_ROOM_H

/* Private field-family implementation. Included by turn.c at the
 * existing helper dependency boundary; turn flow owns evaluation order. */
#include "combat/run_internal.h"

/* The speed key of a Pokemon dragged in (step G46): a drag runs its entry at once and queues no insertChoice
 * (sim/battle-actions.ts:153-155, 162-174), so no updateSpeed takes its speed. Its pokemon.speed is the value its
 * setSpecies gave it (sim/pokemon.ts:1418, and again at its clearVolatile): the raw Speed stat, without the boosts,
 * items and status that dfi_speed_key applies to a standing Pokemon. The key keeps the scale of dfi_speed_key: under
 * Trick Room the reference's standing key is 10000 - speed (sim/pokemon.ts:641-649), and the raw value is not reversed,
 * so it is the raw number itself. Without this key the drag-in kept the speed key of the Pokemon that stood in the slot
 * before, so an Update tie of the entrant and an equal-speed holder was missed. */
static inline uint32_t dfi_entrant_speed_key(const struct duoforge_battle *b, const dfi_member *m)
{
    const uint32_t raw = (uint32_t)m->stats[DFI_STAT_SPE - 1u];
    return b->trick_room_turns != 0u ? raw : DFI_SPEED_BIAS + raw;
}

#endif
