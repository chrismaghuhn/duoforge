#ifndef DUOFORGE_COMBAT_MECHANICS_DAMAGE_STATS_H
#define DUOFORGE_COMBAT_MECHANICS_DAMAGE_STATS_H

/* Private damage implementation (restructure step 4, damage): one phase of dfi_get_damage. Split from
 * src/combat/turn.c@dc9ce14b, lines 1181-1267 of dfi_get_damage; every line of it is unchanged, the phase only loads its inputs
 * from the stack context and stores its outputs. Included by turn.c before dfi_get_damage, so its dependencies and
 * the damage order are unchanged. */
#include "combat/mechanics/damage/context.h"

/* Phase of dfi_get_damage: the attack and defense stats: the stat overrides, the stages and their crit, Darkest Lariat and Unaware
 * clamps, the staged stats and the ModifyDef / ModifySpD chain. */
static DFI_ALWAYS_INLINE duoforge_status
dfi_damage_stats(dfi_run *r, uint32_t user, uint32_t target, const dfi_move_data *md, uint32_t move_type,
                 dfi_damage_ctx *c)
{
    (void)move_type;
    const dfi_member *a = c->a;
    const dfi_member *d = c->d;
    const dfi_active_slot *ap = c->ap;
    const dfi_active_slot *dp = c->dp;
    const bool crit = c->crit;
    const bool physical = md->category == DFI_CATEGORY_PHYSICAL;
    uint32_t atk_index = physical ? DFI_STAGE_ATK : DFI_STAGE_SPA;
    uint32_t def_index = physical ? DFI_STAGE_DEF : DFI_STAGE_SPD;
    /* Step G32, getDamage (sim/battle-actions.ts:1671-1676): Body Press attacks with the user's Defense
     * (overrideOffensiveStat), Foul Play with the Attack of the target and its stages (overrideOffensivePokemon), Psyshock
     * hits the Defense stat with a special move (overrideDefensiveStat). The category stays the move's: the ModifyAtk and
     * ModifySpA events of the user, the weather's ModifyDef and ModifySpD of the stat that is hit, burn and the screens
     * read it. */
    const dfi_member *astat = a;
    const dfi_active_slot *apos = ap;
    if (md->special == DFI_SPECIAL_BODY_PRESS) {
        atk_index = DFI_STAGE_DEF;
    } else if (md->special == DFI_SPECIAL_FOUL_PLAY) {
        astat = d;
        apos = dp;
    } else if (md->special == DFI_SPECIAL_PSYSHOCK) {
        def_index = DFI_STAGE_DEF;
    }
    uint32_t atk_stage = apos->stages[atk_index];
    uint32_t def_stage = dp->stages[def_index];
    if (crit) {
        /* A critical hit ignores negative offensive and positive defensive stages. */
        if (atk_stage < DFI_BIAS6) {
            atk_stage = DFI_BIAS6;
        }
        if (def_stage > DFI_BIAS6) {
            def_stage = DFI_BIAS6;
        }
    }
    /* Darkest Lariat (Team C): ignoreDefensive, the target's Defense stage in
     * both directions (sim/battle-actions.ts:1691-1700). */
    if (md->special == DFI_SPECIAL_DARKEST_LARIAT) {
        def_stage = DFI_BIAS6;
    }
    /* Unaware (step G65, data/abilities.ts:5214-5234, onAnyModifyBoost, breakable): the stat stages that the handler zeroes
     * follow whose stat is READ, not whose stage it is. Each handler returns for its own holder (`unawareUser === pokemon`),
     * so a self-hit (a confusion hit, user = target) is not touched. When the target holds it, the user's attack-side read
     * is zeroed (atk, def, spa, accuracy of the user): the Attack, Defense or Special Attack stage of the user, and the
     * Foul Play case, whose read is the target's own Attack stage (overrideOffensivePokemon) at the user's statUser.
     * When the user holds it, the target's defence-side read is zeroed (def, spd, evasion of the target), so Psyshock's
     * Defense too. The two holders of one hit may both apply; each zeroes only its own side's reads. Mold Breaker is not
     * marked, so no Unaware is ignored (no Mold Breaker row is modelled). */
    /* The pin's Unaware reads activeTarget (data/abilities.ts:5218, :5223): the attacker-side stages are zeroed when the holder
     * is the activeTarget, and the defender-side stages when the holder is the user and the activeTarget is the defender.
     * activeTarget is the hit target, except in a Substitute hit of a spread move, where it is the last target that reached
     * hitStepAccuracy (sim/battle-actions.ts:693, :1138-1146). Single hits are unchanged: the activeTarget is the target. */
    const uint32_t pin_active = r->sub_hit ? r->sub_active : target;
    if (pin_active != user && dfi_ability(r->b, dfi_at(r->b, pin_active), DFI_ABILITY_UNAWARE)) {
        atk_stage = DFI_BIAS6;
    }
    if (pin_active == target && user != target && dfi_ability(r->b, a, DFI_ABILITY_UNAWARE)) {
        def_stage = DFI_BIAS6;
    }
    uint32_t attack = 0u;
    uint32_t defense = 0u;
    uint32_t damage = 0u;
    if (!dfi_stage_stat(astat->stats[atk_index], atk_stage, &attack) ||
        !dfi_stage_stat(d->stats[def_index], def_stage, &defense)) {
        return DUOFORGE_E_INVARIANT;
    }
    /* ModifyDef and ModifySpD (sim/battle-actions.ts:1707-1709) of the weather conditions, priority 10, so the first
     * handler: Sandstorm's onModifySpD gives a Rock type 1.5x its Special Defense, Snowscape's onModifyDef an Ice
     * type 1.5x its Defense (data/conditions.ts:640-645 and 706-711; this.modify(x, 1.5) is 6144/4096). */
    /* Marvel Scale (step G65, data/abilities.ts:2534-2545, onModifyDefPriority 6, breakable): x1.5 on the holder's Defense while
     * it has a status, in the ModifyDef event (sim/battle-actions.ts:1707). Psyshock's Defense is in that event too (its
     * overrideDefensiveStat is 'def'), a special hit's Special Defense is not. runEvent applies the product of all the
     * handlers' chainModify once (sim/battle.ts:2382), so the weather's 1.5 and this one are one chained modifier. */
    /* Both handlers read the defender's effectiveWeather with the weather condition as the effect (sim/pokemon.ts:2190-2198):
     * while a Mega Sol holder is the active Pokemon that is sun, so a Mega Sol user's hit gets neither boost (issue 521;
     * the pin excludes Electro Shot by the effect's id, and the effect here is the weather, so no move is excluded). */
    const uint32_t def_weather = dfi_move_weather(r, a, true);
    uint32_t dchain = 4096u;
    bool dok = true;
    if (def_weather == DFI_WEATHER_SAND && def_index == DFI_STAGE_SPD && dfi_has_type(r->b, d, DFI_TYPE_ROCK)) {
        dok = dfi_chain_modify(dchain, 6144u, &dchain);
    } else if (def_weather == DFI_WEATHER_SNOW && def_index == DFI_STAGE_DEF && dfi_has_type(r->b, d, DFI_TYPE_ICE)) {
        dok = dfi_chain_modify(dchain, 6144u, &dchain);
    }
    if (def_index == DFI_STAGE_DEF && d->status != DFI_STATUS_NONE && dfi_ability(r->b, d, DFI_ABILITY_MARVELSCALE)) {
        dok = dok && dfi_chain_modify(dchain, 6144u, &dchain);
    }
    if (!dok) {
        return DUOFORGE_E_INVARIANT;
    }
    if (dchain != 4096u) {
        defense = dfi_modify(defense, dchain);
    }
    c->physical = physical;
    c->atk_index = atk_index;
    c->attack = attack;
    c->defense = defense;
    c->damage = damage;
    return DUOFORGE_OK;
}

#endif
