#ifndef DUOFORGE_COMBAT_MOVES_STAT_SWAP_H
#define DUOFORGE_COMBAT_MOVES_STAT_SWAP_H

/*
 * Speed Swap (step K3, decision 0015 5de; data/moves.ts:17430-17449, the Champions mod has no override). Its onHit exchanges
 * target.storedStats.spe and source.storedStats.spe, then prints -activate|source|move: Speed Swap|[of] target. The stored
 * Speed is the stat BEFORE the stages, the items, the abilities and the paralysis: the stages stay with each Pokemon. The
 * swapped values live in dfi_member.stats[SPE] of both members; the presence bit (DFI_SINGLE_TURN_SPEED_SWAP) of both
 * positions is what the view and the public refusal read. The swap ends at a switch-out, a faint, a Mega Evolution and a forme
 * change (Stance Change): the occupant's stats are rebuilt from its forme there (dfi_tail_clear_occupant, dfi_run_mega,
 * dfi_stance_change).
 *
 * The move's flags (protect, bypasssub, reflectable: none) and its accuracy (true) are the generic rules of the pool row.
 *
 * Internal header; the event is the VOLATILE_START of the line (position: the source, other: the target), no END.
 */
#include <stdint.h>

#include "combat/run_internal.h"
#include "state/battle_internal.h"

static inline duoforge_status dfi_speed_swap(dfi_run *r, uint32_t user, uint32_t target)
{
    struct duoforge_battle *b = r->b;
    dfi_member *um = dfi_at(b, user);
    dfi_member *tm = dfi_at(b, target);
    if (um == NULL || tm == NULL || user == target) {
        return DUOFORGE_E_INVARIANT; /* a live target and a source of its own: the pin's onHit has both */
    }
    /* the exchange of the two stored Speeds (storedStats.spe, DFI_STAT_SPE - 1 in the stats array) */
    const uint16_t user_spe = um->stats[DFI_STAT_SPE - 1u];
    um->stats[DFI_STAT_SPE - 1u] = tm->stats[DFI_STAT_SPE - 1u];
    tm->stats[DFI_STAT_SPE - 1u] = user_spe;
    /* the presence bit of both positions (the swapped Speed is live on both) */
    b->tail.sides[user / 2u].positions[user % 2u].single_turn |= (uint8_t)DFI_SINGLE_TURN_SPEED_SWAP;
    b->tail.sides[target / 2u].positions[target % 2u].single_turn |= (uint8_t)DFI_SINGLE_TURN_SPEED_SWAP;
    /* -activate|source|move: Speed Swap|[of] target: a POOL volatile start, the source is the position, the target the other */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_VOLATILE_START, user);
    e.detail = (uint8_t)DUOFORGE_VOLATILE_SPEED_SWAP;
    e.other = (uint8_t)target;
    dfi_emit(r, &e);
    return DUOFORGE_OK;
}

#endif
