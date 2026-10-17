#ifndef DUOFORGE_COMBAT_ABILITIES_ENTRY_H
#define DUOFORGE_COMBAT_ABILITIES_ENTRY_H

/* Private abilities implementation (restructure step 4, abilities): the SwitchIn handlers of the entry abilities:
 * Hospitality, Frisk, Trace and the entry ability dispatch. Split from src/combat/turn.c@98915957; included by turn.c
 * where the code stood, so its dependencies and the turn order are unchanged. */
#include "combat/run_internal.h"

/* A SwitchIn handler: an entry ability (priority 0), a terrain seed's onStart (onSwitchInPriority -1), Hospitality's onStart
 * (onSwitchInPriority -2, step G30), or the toxic status's onSwitchIn (data/conditions.ts:151, the stage back to 0; a status
 * of the entering Pokemon, which stays through a switch). Its effect is internal, but the reference runs it in the switch-in
 * order, so two entering badly poisoned Pokemon of one Speed draw the tie (the G36 Toxic row, fixed by step G47; the campaign
 * seed 9800000 battle 96 showed it). The converter's switch-order rule counts the same handler. */
static bool dfi_has_switch_in(const struct duoforge_battle *b, const dfi_member *m)
{
    return dfi_has_entry(b, m) || dfi_seed_terrain(b, m) != DFI_TERRAIN_NONE ||
           dfi_ability(b, m, DFI_ABILITY_HOSPITALITY) || dfi_ability(b, m, DFI_ABILITY_CLOUDNINE) ||
           m->status == DFI_STATUS_TOX ||
           dfi_holds(b, m, DFI_ITEM_AIRBALLOON); /* its onStart is a SwitchIn handler too (step G67) */
}

/* Hospitality (step G30, data/abilities.ts:1874-1887, onStart): the holder heals every adjacent ally by a quarter of its
 * base maximum HP (Battle.heal truncates and gives at least 1; a full ally or one that Heal Block bars gets nothing):
 * [-heal] ally [from] ability: Hospitality [of] the holder. In doubles the one ally is the other position of the side.
 * It runs as the handler of the SwitchIn event at priority -2, after the entry abilities and the seeds
 * (dfi_run_entries), and at once when Trace copies it (setAbility's Start event). */
static void dfi_hospitality(dfi_run *r, uint32_t flat)
{
    const uint32_t ally = flat ^ 1u;
    const dfi_member *am = dfi_at(r->b, ally);
    if (am == NULL || am->hp == 0u) {
        return;
    }
    dfi_heal(r, ally, (uint32_t)am->hp_max / 4u, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_HOSPITALITY, flat);
}

/* An entry ability: a weather or a terrain setter (the families of
 * decision 0015: Drizzle, Drought, Grassy Surge, Psychic Surge), Intimidate,
 * Fairy Aura (whose onStart only shows the ability) or Trace. */
static bool dfi_has_entry(const struct duoforge_battle *b, const dfi_member *m)
{
    const dfi_ability_family fam = dfi_ability_family_now(b, m);
    const uint32_t now = dfi_ability_code(b, m);
    return dfi_weather_set_by_fam(fam) != DFI_WEATHER_NONE || dfi_terrain_set_by_fam(fam) != DFI_TERRAIN_NONE ||
           now == 1u + DFI_ABILITY_INTIMIDATE || now == 1u + DFI_ABILITY_FAIRYAURA || now == 1u + DFI_ABILITY_TRACE ||
           now == 1u + DFI_ABILITY_UNNERVE || now == 1u + DFI_ABILITY_PRESSURE || now == 1u + DFI_ABILITY_FRISK;
}

/* Trace (data/abilities.ts:5118-5148, onStart then its Update): the holder copies the ability of one of the foes that
 * are standing and whose ability can be copied. `adjacentFoes()` is every foe in doubles (sim/pokemon.ts:732-735),
 * a foe is a candidate unless its ability is none or has the notrace flag: of the abilities that a battle can hold
 * (the marked ones) only Trace and Stance Change (step G66) have it (tests/test_pool_tables.c; the pin's nine notrace abilities
 * are checked by tools/datagen/pool_families.js), so a foe that is still Trace, or whose Trace has not run yet, is not
 * a candidate. The pick is `this.sample(possibleTargets)`, always one draw random(n), also for a single candidate
 * (site TRACE). The copy is the POOL tail's ability_now of the holder until it leaves the field (the switch-out reset
 * of clearVolatile, sim/pokemon.ts:1522) or Mega Evolves, and is shown as
 * -ability|holder|NEW|OLD|[from] ability: Trace|[of] foe (sim/pokemon.ts:1930-1945: the event has the new ability in
 * id2, the cause ability and the foe in `other`; the old ability is the holder's own and public). setAbility then
 * starts the new ability (singleEvent Start): a copied Intimidate or weather setter runs at once, before the
 * entries of the Pokemon that come later in the order.
 * With no candidate Trace goes on seeking at every later Update (`effectState.seek`): not modelled, so the entry is
 * E_UNSUPPORTED (two Trace holders against each other, say, are the case; a battle never has no foe left). */
static duoforge_status dfi_entry_ability(dfi_run *r, uint32_t flat);

/* Frisk (step G81, data/abilities.ts:1545-1557, onStart): for each foe in foes() order (the standing foes, slot 0 then 1) that
 * holds an item, `-item|X|Item|[from] ability: Frisk|[of] Y`: ITEM_SHOWN with the foe as the position, the Frisk user in other,
 * cause ABILITY, id = Frisk + 1 and id2 = the item + 1 (decision 0033, the form mapped by step G81). The item is the one held
 * now (dfi_item_code: a used-up item prints nothing, as Showdown's target.item is then empty). No state changes: the open team
 * sheet already shows the item (the view and the knowledge are unchanged). A foe whose Illusion disguise is up (decision 0026)
 * and that holds an item is refused (E_UNSUPPORTED) before any line is emitted: the line would name the disguise, not measured. */
static duoforge_status dfi_frisk(dfi_run *r, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    const uint32_t foe = 1u - flat / 2u;
    for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
        const dfi_member *t = dfi_at(b, foe * 2u + slot);
        if (t != NULL && t->hp != 0u && dfi_item_code(b, t) != 0u &&
            dfi_illusion_disguise_up(&b->sides[foe], &b->tail.sides[foe], slot) != 0) {
            return DUOFORGE_E_UNSUPPORTED;
        }
    }
    for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
        const dfi_member *t = dfi_at(b, foe * 2u + slot);
        const uint32_t code = (t != NULL && t->hp != 0u) ? dfi_item_code(b, t) : 0u;
        if (code != 0u) {
            duoforge_event e = dfi_ev(DUOFORGE_EVENT_ITEM_SHOWN, foe * 2u + slot, DUOFORGE_CAUSE_ABILITY, code, flat);
            e.id = (uint16_t)(1u + DFI_ABILITY_FRISK); /* wide-operands-reviewed: 67, below 2^16 */
            dfi_emit(r, &e);
        }
    }
    return DUOFORGE_OK;
}

static duoforge_status dfi_trace(dfi_run *r, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    uint32_t candidates[DUOFORGE_ACTIVE_PER_SIDE] = {0u, 0u};
    uint32_t n = 0u;
    const uint32_t foe = 1u - flat / 2u;
    for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
        const dfi_member *t = dfi_at(b, foe * 2u + slot);
        if (t != NULL && t->hp != 0u) {
            const uint32_t code = dfi_ability_code(b, t);
            /* notrace (pin flags): Trace itself, Illusion (decision 0026 section 2) and Stance Change (step G66, decision 0040:
             * Aegislash's ability, marked since G66). */
            if (code != 0u && code != 1u + DFI_ABILITY_TRACE && code != 1u + DFI_ABILITY_ILLUSION &&
                code != 1u + DFI_ABILITY_STANCECHANGE) {
                candidates[n] = foe * 2u + slot;
                n += 1u;
            }
        }
    }
    if (n == 0u) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    uint32_t pick = 0u;
    const duoforge_status st = dfi_draw(r->draws, DFI_SITE_TRACE, 0u, n, &pick);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const uint32_t source = candidates[pick]; /* pick < n <= 2 */
    const uint32_t copied = dfi_ability_code(b, dfi_at(b, source));
    /* Limber's onUpdate (step G39) cures a paralysis that its holder has: a paralysed Trace holder that copies it is not
     * modelled (E_UNSUPPORTED, never a guess; no other Update handler of the marked abilities acts on a status). */
    if (copied == 1u + DFI_ABILITY_LIMBER && dfi_at(b, flat)->status == DFI_STATUS_PAR) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    /* Water Bubble's onUpdate (step G65, data/abilities.ts:5400-5405) cures a burn that its holder has, with its -activate line:
     * a burned Trace holder that copies it is not modelled (E_UNSUPPORTED, never a guess). */
    if (copied == 1u + DFI_ABILITY_WATERBUBBLE && dfi_at(b, flat)->status == DFI_STATUS_BRN) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    /* Magma Armor's onUpdate (step G77, data/abilities.ts:2502-2507) cures a freeze of its holder with its -activate line: a
     * frozen Trace holder that copies it is not modelled (E_UNSUPPORTED, never a guess), as for Limber and Water Bubble. */
    if (copied == 1u + DFI_ABILITY_MAGMAARMOR && dfi_at(b, flat)->status == DFI_STATUS_FRZ) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    /* Oblivious's onUpdate (step G47, data/abilities.ts:3009-3016) removes a taunt of its holder with its -activate line. The
     * copy comes at the entry, where no taunt stands; a taunted holder that copies it is refused, never guessed. */
    if (copied == 1u + DFI_ABILITY_OBLIVIOUS && b->tail.sides[flat / 2u].positions[flat % 2u].taunt_turns != 0u) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    /* Step G79 (lead decision): a copied Cloud Nine is not modelled until there is evidence (E_UNSUPPORTED, never a guess). */
    if (copied == 1u + DFI_ABILITY_CLOUDNINE) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    b->tail.sides[flat / 2u].ability_now[dfi_pos(b, flat)->occupant] = (uint16_t)copied; /* <= the ability count */
    const duoforge_event e = dfi_ev(DUOFORGE_EVENT_ABILITY, flat, DUOFORGE_CAUSE_ABILITY, copied, source);
    dfi_emit(r, &e);
    if (dfi_has_entry(b, dfi_at(b, flat))) {
        return dfi_entry_ability(r, flat); /* setAbility's Start event */
    }
    if (copied == 1u + DFI_ABILITY_HOSPITALITY) {
        dfi_hospitality(r, flat); /* its Start event heals the ally at once */
    }
    return DUOFORGE_OK;
}

/* Drizzle and Drought (setWeather): the same weather is not restarted;
 * otherwise the weather is replaced for 5 turns. Grassy Surge and Psychic
 * Surge (setTerrain, sim/field.ts:130-157) likewise: a terrain that is
 * replaced ends without a line. Intimidate lowers the Attack of every
 * standing adjacent foe by 1. */
static duoforge_status dfi_entry_ability(dfi_run *r, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    const dfi_member *m = dfi_at(b, flat);
    const uint32_t a = dfi_ability_code(b, m);
    const dfi_ability_family fam = dfi_ability_family_now(b, m);
    const uint32_t w = dfi_weather_set_by_fam(fam);
    const uint32_t terrain = dfi_terrain_set_by_fam(fam);
    if (w != DFI_WEATHER_NONE) {
        if (b->weather != w) {
            b->weather = (uint8_t)w;
            b->weather_turns = (uint8_t)dfi_field_start_turns(b, m, dfi_weather_rock(w)); /* G55 */
            /* -weather|...|[from] ability: X|[of] holder */
            duoforge_event e = dfi_ev(DUOFORGE_EVENT_WEATHER, DUOFORGE_NO_POSITION, DUOFORGE_CAUSE_ABILITY, a, flat);
            e.detail = (uint8_t)w; /* DUOFORGE_WEATHER_* */
            dfi_emit(r, &e);
        }
    } else if (terrain != DFI_TERRAIN_NONE) {
        if (b->terrain != terrain) {
            b->terrain = (uint8_t)terrain;
            b->terrain_turns = (uint8_t)dfi_field_start_turns(b, m, DFI_TERRAIN_EXTENDER); /* G55 */
            /* -fieldstart|move: X Terrain|[from] ability: X|[of] holder */
            duoforge_event e =
                dfi_ev(DUOFORGE_EVENT_FIELD_START, DUOFORGE_NO_POSITION, DUOFORGE_CAUSE_ABILITY, a, flat);
            e.detail = (uint8_t)dfi_terrain_field_detail(terrain);
            dfi_emit(r, &e);
            return dfi_terrain_change(r);
        }
    } else if (a == 1u + DFI_ABILITY_TRACE) {
        return dfi_trace(r, flat);
    } else if (a == 1u + DFI_ABILITY_FAIRYAURA || a == 1u + DFI_ABILITY_UNNERVE || a == 1u + DFI_ABILITY_PRESSURE) {
        /* onStart: -ability|holder|Fairy Aura (the aura itself is onAnyBasePower); Unnerve's is the same announcement
         * (step G32; its `unnerved` flag is derived: dfi_unnerved); Pressure's (step G53, data/abilities.ts:3438-3440)
         * is -ability|holder|Pressure, its charge being dfi_pressure_extra */
        const duoforge_event e = dfi_ev(DUOFORGE_EVENT_ABILITY, flat, DUOFORGE_CAUSE_NONE, a, DUOFORGE_NO_POSITION);
        dfi_emit(r, &e);
    } else if (a == 1u + DFI_ABILITY_INTIMIDATE) {
        static const uint8_t drop[DFI_STAGE_COUNT] = {5u, 6u, 6u, 6u, 6u, 6u, 6u}; /* Attack -1 */
        const uint32_t foe = 1u - flat / 2u;
        bool shown = false;
        for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
            const dfi_member *t = dfi_at(b, foe * 2u + slot);
            if (t != NULL && t->hp != 0u) {
                if (!shown) {
                    /* -ability|holder|Intimidate|boost before the first foe */
                    const duoforge_event e = dfi_ev(DUOFORGE_EVENT_ABILITY, flat, DUOFORGE_CAUSE_NONE, a,
                                                    DUOFORGE_NO_POSITION);
                    dfi_emit(r, &e);
                    shown = true;
                }
                if (b->tail.sides[foe].positions[slot].substitute_hp != 0u) {
                    /* A Substitute is -immune to Intimidate (data/abilities.ts:2201-2202): `-immune|target`, no drop, no [from]. */
                    const duoforge_event im = dfi_ev(DUOFORGE_EVENT_IMMUNE, foe * 2u + slot, DUOFORGE_CAUSE_NONE, 0u,
                                                     DUOFORGE_NO_POSITION);
                    dfi_emit(r, &im);
                    continue;
                }
                dfi_boost(r, foe * 2u + slot, drop, flat,
                          dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_INTIMIDATE, DFI_BOOST_SECONDARY));
            }
        }
    } else if (a == 1u + DFI_ABILITY_FRISK) {
        return dfi_frisk(r, flat); /* step G81: the foes' items, -item lines (ITEM_SHOWN) */
    }
    return DUOFORGE_OK;
}

#endif
