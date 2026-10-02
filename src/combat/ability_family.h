#ifndef DUOFORGE_COMBAT_ABILITY_FAMILY_H
#define DUOFORGE_COMBAT_ABILITY_FAMILY_H
/*
 * The ability families of decision 0015 as the battle reads them: the "-ate"
 * abilities, the pinch abilities and the weather and terrain setters of the
 * entry. An ability has the family and the
 * parameter (a type) that the family columns of data/pool_tables.h give it,
 * and the rules below read only that: no ability is named here. What each
 * rule does to the damage (the modifier, its place in the chain) is in
 * combat/turn.c.
 *
 * The functions are pure and take the holder, so that a test can run every
 * ability against every type (tests/test_ability_family.c).
 */
#include <stdbool.h>
#include <stdint.h>

#include "core/modifier.h"
#include "data/pool_tables.h"
#include "state/battle_internal.h"

/* The modifiers, in 4096ths (data/abilities.ts: chainModify([4915, 4096]) in
 * the onBasePower of every -ate ability, chainModify(1.5) in the onModifyAtk
 * and onModifySpA of every pinch ability). */
#define DFI_ATE_MODIFIER 4915u
#define DFI_PINCH_MODIFIER 6144u

/* The family row of the member's ability (stored as 1 + id, 0 for none); the
 * row of no family without one. The member invariant bounds the ability id,
 * so the guard on it only keeps the read in the table. */
static inline dfi_ability_family dfi_ability_family_of(const dfi_member *m)
{
    dfi_ability_family none = {DFI_ABILITY_FAMILY_NONE, DFI_FAMILY_PARAM_NONE};
    if (m == NULL || m->ability == 0u || m->ability > DFI_POOL_ABILITY_COUNT) {
        return none;
    }
    return dfi_pool_ability_family[m->ability - 1u];
}

/* onModifyType of an -ate ability: a Normal move becomes the ability's type;
 * any other type is as it was, and so is the type of a move that the handler
 * lists as not to be changed (noModifyType: of the pool's moves only Weather
 * Ball, which the cross-check of the pool ids confirms). The typeless hit of
 * Struggle is not Normal. */
static inline uint32_t dfi_ate_type_of(const dfi_member *user, const dfi_move_data *md, uint32_t move_type)
{
    const dfi_ability_family fam = dfi_ability_family_of(user);
    if (fam.family == DFI_ABILITY_FAMILY_ATE && move_type == DFI_TYPE_NORMAL &&
        md->special != DFI_SPECIAL_WEATHER_BALL) {
        return fam.param;
    }
    return move_type;
}

/* onBasePower of an -ate ability (typeChangerBoosted): the move was Normal
 * and its type is now the ability's. */
static inline bool dfi_ate_boosts(const dfi_member *user, uint32_t base_type, uint32_t move_type)
{
    const dfi_ability_family fam = dfi_ability_family_of(user);
    return fam.family == DFI_ABILITY_FAMILY_ATE && base_type == DFI_TYPE_NORMAL && move_type == fam.param;
}

/* onModifyAtk and onModifySpA of a pinch ability: a move of its type at a
 * third of the maximum HP or less (hp <= maxhp / 3 in the handler, so
 * 3 hp <= maxhp). */
static inline bool dfi_pinch_applies(const dfi_member *user, uint32_t move_type)
{
    const dfi_ability_family fam = dfi_ability_family_of(user);
    return fam.family == DFI_ABILITY_FAMILY_PINCH && move_type == fam.param &&
           (uint32_t)user->hp * 3u <= (uint32_t)user->hp_max;
}

/* The weather that an ability sets on entry (onStart, setWeather) as a
 * state value DFI_WEATHER_*, or DFI_WEATHER_NONE when it is no weather
 * setter. The column holds a family code, so each code is named here; a code
 * that is none of them is no setter, which the table test excludes. */
static inline uint32_t dfi_weather_set_by(const dfi_member *m)
{
    const dfi_ability_family fam = dfi_ability_family_of(m);
    if (fam.family != DFI_ABILITY_FAMILY_WEATHER_SETTER) {
        return DFI_WEATHER_NONE;
    }
    return fam.param == DFI_FAMILY_WEATHER_RAIN  ? DFI_WEATHER_RAIN
           : fam.param == DFI_FAMILY_WEATHER_SUN ? DFI_WEATHER_SUN
                                                 : DFI_WEATHER_NONE;
}

/* The terrain that an ability sets on entry (onStart, setTerrain) as a state
 * value DFI_TERRAIN_*, or DFI_TERRAIN_NONE. */
static inline uint32_t dfi_terrain_set_by(const dfi_member *m)
{
    const dfi_ability_family fam = dfi_ability_family_of(m);
    if (fam.family != DFI_ABILITY_FAMILY_TERRAIN_SETTER) {
        return DFI_TERRAIN_NONE;
    }
    return fam.param == DFI_FAMILY_TERRAIN_GRASSY    ? DFI_TERRAIN_GRASSY
           : fam.param == DFI_FAMILY_TERRAIN_PSYCHIC ? DFI_TERRAIN_PSYCHIC
                                                     : DFI_TERRAIN_NONE;
}

#endif
