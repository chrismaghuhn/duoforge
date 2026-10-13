#ifndef DUOFORGE_COMBAT_MULTIHIT_COUNT_H
#define DUOFORGE_COMBAT_MULTIHIT_COUNT_H

/*
 * The hit count of Icicle Spear and Scale Shot (step G54), as a function of the draw of DFI_SITE_MULTIHIT_COUNT (random(20)).
 * The Champions hit loop picks sample([2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 4, 4, 4, 5, 5, 5]) (data/mods/champions/
 * scripts.ts:437-446, the same list as sim/battle-actions.ts:870): seven 2s, seven 3s, three 4s and three 5s, in this order.
 * The white-box test duoforge.state.pool_g54 checks every index. Internal header: no public value, no state.
 */
#include <stdint.h>

#include "data/pool_tables.h"

static inline uint32_t dfi_multihit_count(uint32_t pick)
{
    static const uint8_t counts[20] = {2u, 2u, 2u, 2u, 2u, 2u, 2u, 3u, 3u, 3u, 3u, 3u, 3u, 3u, 4u, 4u, 4u, 5u, 5u, 5u};
    return counts[pick];
}

/* The number of hits of a move (step G33): the pin's `multihit`, kept in the handler of the three rows that the engine runs
 * (Dual Wingbeat and Twin Beam 2, Triple Axel 3), 1 for every other move. */
static inline uint32_t dfi_move_hits(const dfi_move_data *md)
{
    return md->special == DFI_SPECIAL_MULTI_HIT_2 ? 2u
           : md->special == DFI_SPECIAL_TRIPLE_AXEL ? 3u
           : md->special == DFI_SPECIAL_MULTI_HIT_10 ? 10u
           : md->special == DFI_SPECIAL_DRAGON_DARTS ? 2u /* multihit: 2, a number: no draw (decision 0043) */
           : 1u;
}

#endif
