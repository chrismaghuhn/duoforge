#ifndef DUOFORGE_COMBAT_MECHANICS_DAMAGE_BASE_DAMAGE_H
#define DUOFORGE_COMBAT_MECHANICS_DAMAGE_BASE_DAMAGE_H

/* Private damage implementation (restructure step 4, damage): one phase of dfi_get_damage. Split from
 * src/combat/turn.c@dc9ce14b, lines 1544-1605 of dfi_get_damage; every line of it is unchanged, the phase only loads its inputs
 * from the stack context and stores its outputs. Included by turn.c before dfi_get_damage, so its dependencies and
 * the damage order are unchanged. */
#include "combat/mechanics/damage/context.h"

/* Phase of dfi_get_damage: the base damage: the formula, the spread and weather modifiers, the crit multiplier, the
 * DAMAGE_ROLL draw, STAB and the type effectiveness with its lines, and the [-crit] line. */
static DFI_ALWAYS_INLINE duoforge_status
dfi_damage_base(dfi_run *r, uint32_t user, uint32_t target, const dfi_move_data *md, uint32_t move_type,
                dfi_damage_ctx *c)
{
    (void)user;
    const dfi_member *a = c->a;
    const dfi_member *d = c->d;
    const bool crit = c->crit;
    const uint32_t base_power = c->base_power;
    const uint32_t attack = c->attack;
    const uint32_t defense = c->defense;
    const bool spread = c->spread;
    uint32_t damage = c->damage;
    if (!dfi_base_damage(DFI_LEVEL, base_power, attack, defense, &damage)) {
        return DUOFORGE_E_INVARIANT;
    }
    damage += 2u;
    if (spread) {
        damage = dfi_modify(damage, 3072u); /* 0.75 */
    }
    /* WeatherModifyDamage: rain and sun boost their type by half and halve
     * the other (data/conditions.ts raindance, sunnyday). */
    const uint32_t weather = dfi_field_weather(r);
    if (dfi_ability(r->b, a, DFI_ABILITY_MEGASOL)) {
        /* Mega Sol (step G59, data/abilities.ts:2558-2569, onWeatherModifyDamagePriority 1): the holder's own handler, first
         * of the event (the field's handlers are priority 0, and it returns the damage: a fast exit), calls sunnyday's
         * onWeatherModifyDamage with the holder's moves as sun: Fire x1.5 and Water x0.5 (data/conditions.ts:556-578), whatever
         * the field's weather is (the field's raindance and the rest do not run). Hydro Steam is not marked. */
        if (move_type == DFI_TYPE_FIRE) {
            damage = dfi_modify(damage, 6144u);
        } else if (move_type == DFI_TYPE_WATER) {
            damage = dfi_modify(damage, 2048u);
        }
    } else if ((weather == DFI_WEATHER_RAIN && move_type == DFI_TYPE_WATER) ||
               (weather == DFI_WEATHER_SUN && move_type == DFI_TYPE_FIRE)) {
        damage = dfi_modify(damage, 6144u);
    } else if ((weather == DFI_WEATHER_RAIN && move_type == DFI_TYPE_FIRE) ||
               (weather == DFI_WEATHER_SUN && move_type == DFI_TYPE_WATER)) {
        damage = dfi_modify(damage, 2048u);
    }
    if (crit) {
        damage = dfi_crit_damage(damage);
    }
    uint32_t roll = 0u;
    const duoforge_status st = dfi_draw(r->draws, DFI_SITE_DAMAGE_ROLL, 0u, 16u, &roll);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (!dfi_randomize(damage, roll, &damage)) {
        return DUOFORGE_E_INVARIANT;
    }
    uint32_t mod = DFI_BIAS6; /* neutral for Struggle's typeless hit */
    if (move_type < DFI_TYPE_COUNT) {
        /* STAB 1.5; Adaptability 2 (Team C, data/abilities.ts:43-56; no Tera) */
        const uint32_t stab = !dfi_has_type(r->b, a, move_type) ? 4096u
                              : dfi_ability(r->b, a, DFI_ABILITY_ADAPTABILITY) ? 8192u
                                                                         : 6144u;
        damage = dfi_modify(damage, stab);
        mod = dfi_type_mod(r->b, d, move_type, md);
        if (!dfi_type_damage(damage, mod, &damage)) {
            return DUOFORGE_E_INVARIANT;
        }
        /* -supereffective or -resisted with min(|typeMod|, 2) (the
         * Champions modifyDamage, data/mods/champions/scripts.ts:269-279) */
        if (mod != DFI_BIAS6) {
            const uint32_t by = mod > DFI_BIAS6 ? mod - DFI_BIAS6 : DFI_BIAS6 - mod;
            duoforge_event e =
                dfi_event_make(mod > DFI_BIAS6 ? DUOFORGE_EVENT_SUPER_EFFECTIVE : DUOFORGE_EVENT_RESISTED, target);
            e.amount = (uint8_t)(by > 2u ? 2u : by); /* wide-operands-reviewed: <= 2 */
            dfi_emit(r, &e);
        }
    }
    if (crit) {
        dfi_emit_plain(r, DUOFORGE_EVENT_CRIT, target); /* [-crit] */
    }
    c->damage = damage;
    c->mod = mod;
    return DUOFORGE_OK;
}

#endif
