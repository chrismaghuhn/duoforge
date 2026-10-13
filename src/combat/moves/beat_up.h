#ifndef DUOFORGE_COMBAT_MOVES_BEAT_UP_H
#define DUOFORGE_COMBAT_MOVES_BEAT_UP_H

#include "combat/run_internal.h"
#include "data/pool_tables.h"
#include "state/context_internal.h"

/* Beat Up (step G64, data/moves.ts:1150-1179): onModifyMove keeps the Pokemon of the user's side that are the user or are not
 * fainted and have no status, in side.pokemon order (party_order, the brought members), and sets multihit to their number; each
 * hit's basePowerCallback takes the next of them and gives 5 + floor(base Attack of its set species / 10). The set species is
 * the member's forme, never its Mega forme (species_id stays the set's). Returns the hit count and fills r->beat_up_bp; a
 * member that is fainted or has a status is no hit, and nothing of the user's side changes during the move but the user's own
 * HP, which never removes the user from the list. */
static inline uint32_t dfi_beat_up_hits(dfi_run *r, uint32_t user)
{
    struct duoforge_battle *b = r->b;
    const uint32_t side = user / 2u;
    const dfi_member *self = dfi_at(b, user);
    uint32_t hits = 0u;
    for (uint32_t k = 0u; k < r->ctx->brought_count && k < DUOFORGE_MAX_ROSTER; ++k) {
        const uint32_t e = dfi_party_entry(&b->tail, side, k);
        if (e == 0u) {
            break;
        }
        const dfi_member *m = &b->sides[side].members[e - 1u];
        if (m == self || (m->hp != 0u && m->status == DFI_STATUS_NONE)) {
            r->beat_up_bp[hits] = 5u + (uint32_t)dfi_pool_formes[m->species_id].base[DFI_STAT_ATK] / 10u;
            hits += 1u;
        }
    }
    return hits;
}

#endif
