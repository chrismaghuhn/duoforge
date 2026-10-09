#ifndef DUOFORGE_COMBAT_SHEER_FORCE_H
#define DUOFORGE_COMBAT_SHEER_FORCE_H

/*
 * Sheer Force (step G61, data/abilities.ts:4202-4221) as two predicates on the holder's ability and the move's data, so that
 * the white-box test tests/test_pool_g61.c can run them on every move of the pool. Internal header: no public value, no state.
 *
 * The pinned onModifyMove deletes a move's secondaries and self effects, and sets hasSheerForce, only when the move has
 * secondaries and is not hasSheerForceBoost. The engine's secondary columns of a move are sec_chance (the chance of its
 * secondary, 0 for none) and special. A move with a secondary is one whose sec_chance is not 0, or one whose secondary runs in
 * its own code: Stone Axe and Ceaseless Edge (`secondary: {}`, the empty placeholder), Ice Fang and Tri Attack. Electro Shot is
 * hasSheerForceBoost: it gets the x5325/4096 and keeps everything. No other move is affected, self-only moves included.
 *
 * The generator (tools/datagen/pool_families.js checkG61) checks these predicates against the pin for every pool move, marked or
 * not, in both directions.
 */
#include <stdbool.h>
#include <stdint.h>

#include "data/closure_tables.h"
#include "data/pool_tables.h"

/* True when the holder's Sheer Force strips the move's secondaries and self effects (hasSheerForce). */
static inline bool dfi_sf_strips_move(bool holder_sheer_force, const dfi_move_data *md)
{
    return holder_sheer_force &&
           (md->sec_chance != 0u || md->special == DFI_SPECIAL_STONE_AXE || md->special == DFI_SPECIAL_CEASELESS_EDGE ||
            md->special == DFI_SPECIAL_ICE_FANG || md->special == DFI_SPECIAL_TRI_ATTACK);
}

/* True when the holder's Sheer Force multiplies the move's base power by 5325/4096: a stripped move, and Electro Shot. */
static inline bool dfi_sf_boosts_move(bool holder_sheer_force, const dfi_move_data *md)
{
    return dfi_sf_strips_move(holder_sheer_force, md) || (holder_sheer_force && md->special == DFI_SPECIAL_ELECTRO_SHOT);
}

#endif
