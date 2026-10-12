#ifndef DUOFORGE_COMBAT_ABILITIES_ATE_H
#define DUOFORGE_COMBAT_ABILITIES_ATE_H

#include "combat/abilities/current.h"
#include "combat/damage_chain.h"

#define DFI_ATE_MODIFIER 4915u /* chainModify([4915, 4096]) */

/* The moves of the pool that the -ate abilities leave alone (their noModifyType list: judgment, multiattack,
 * naturalgift, revelationdance, technoblast, terrainpulse, weatherball; of those only Weather Ball and, since step G25,
 * Terrain Pulse are modelled: the generator checks the list). Such a move changes its type by its own onModifyType, so an
 * -ate ability neither turns it nor boosts it: typeChangerBoosted is only set by the ability's own change. */
static inline bool dfi_ate_excluded(const dfi_move_data *md)
{
    return md->special == DFI_SPECIAL_WEATHER_BALL || md->special == DFI_SPECIAL_TERRAIN_PULSE;
}

/* onModifyType of an -ate ability: a Normal move becomes the ability's type;
 * any other type is as it was, and so is the type of a move that the handler
 * lists as not to be changed (noModifyType: of the pool's moves only Weather
 * Ball, which the cross-check of the pool ids confirms). The typeless hit of
 * Struggle is not Normal. */
static inline uint32_t dfi_ate_type_fam(dfi_ability_family fam, const dfi_move_data *md, uint32_t move_type)
{
    if (fam.family == DFI_ABILITY_FAMILY_ATE && move_type == DFI_TYPE_NORMAL && !dfi_ate_excluded(md)) {
        return fam.param;
    }
    return move_type;
}

/* onBasePower of an -ate ability (typeChangerBoosted): the move was Normal
 * and its type is now the ability's. */
static inline bool dfi_ate_boosts_fam(dfi_ability_family fam, uint32_t base_type, uint32_t move_type)
{
    return fam.family == DFI_ABILITY_FAMILY_ATE && base_type == DFI_TYPE_NORMAL && move_type == fam.param;
}

static inline bool dfi_ate_base_power(const struct duoforge_battle *b, const dfi_member *a,
                                      const dfi_move_data *md, uint32_t move_type, bool ok, uint32_t *bp_chain)
{
    /* An -ate ability (the ATE family: Aerilate, Pixilate and Refrigerate,
     * decision 0015): a Normal move it turned into its type gets 4915/4096
     * (data/abilities.ts, onBasePowerPriority 23: first). */
    if (!dfi_ate_excluded(md) && dfi_ate_boosts_fam(dfi_ability_family_now(b, a), md->type, move_type)) {
        ok = ok && dfi_chain_modify(*bp_chain, DFI_ATE_MODIFIER, bp_chain);
    }
    return ok;
}

#endif
