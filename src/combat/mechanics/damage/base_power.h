#ifndef DUOFORGE_COMBAT_MECHANICS_DAMAGE_BASE_POWER_H
#define DUOFORGE_COMBAT_MECHANICS_DAMAGE_BASE_POWER_H

/* Private damage implementation (restructure step 4, damage): one phase of dfi_get_damage. Split from
 * src/combat/turn.c@dc9ce14b, lines 1268-1490 of dfi_get_damage; every line of it is unchanged, the phase only loads its inputs
 * from the stack context and stores its outputs. Included by turn.c before dfi_get_damage, so its dependencies and
 * the damage order are unchanged. */
#include "combat/mechanics/damage/context.h"

/* Phase of dfi_get_damage: the base power: the power callbacks and the BasePower chain. */
static DFI_ALWAYS_INLINE duoforge_status
dfi_damage_base_power(dfi_run *r, uint32_t user, uint32_t target, const dfi_move_data *md, uint32_t move_type,
                      dfi_damage_ctx *c)
{
    const dfi_member *a = c->a;
    const dfi_member *d = c->d;
    const dfi_active_slot *ap = c->ap;
    /* BasePower (after the critical hit roll), one chained modifier: Mystic
     * Water (Water) and Miracle Seed (Grass) 4915/4096, Grassy Terrain
     * 5325/4096 for a grounded user's Grass move. */
    /* Weather Ball doubles in rain or sun (onModifyMove); Grass Knot's and
     * Low Kick's power follow the target's weight (basePowerCallback). */
    uint32_t power = md->base_power;
    if (md->special == DFI_SPECIAL_WEATHER_BALL && dfi_move_weather(r, a, true) != DFI_WEATHER_NONE) {
        power *= 2u;
    } else if (md->special == DFI_SPECIAL_ACROBATICS) {
        /* Acrobatics' basePowerCallback (step G28, data/moves.ts:117-141): doubled while the user holds no item (the item it
         * holds now: one that was eaten, knocked off or used up is gone). */
        if (dfi_item_code(r->b, a) == 0u) {
            power *= 2u;
        }
    } else if (md->special == DFI_SPECIAL_STOMPING_TANTRUM) {
        /* basePowerCallback of Stomping Tantrum (data/moves.ts:18054-18058) and of Temper Flare (data/moves.ts:19189-19195,
         * the same code, step K1, #476): x2 when the user's last move result is FALSE (strictly; null is not a failure). An
         * unclassified last result is refused, never guessed (step G42). */
        const uint32_t last_res = r->b->tail.sides[user / 2u].positions[user % 2u].move_result;
        if ((last_res & DFI_MOVE_RESULT_UNCLASSIFIED_LAST) != 0u) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        if (((last_res >> DFI_MOVE_RESULT_LAST_SHIFT) & 3u) == DFI_MOVE_RESULT_FALSE) {
            power *= 2u;
        }
    } else if (md->special == DFI_SPECIAL_HP_POWER) {
        /* Eruption and Water Spout (step G32, data/moves.ts:4888-4905, :20661-20678): basePower 150 x the user's HP / its
         * maximum HP, the engine takes the integer part and at least 1 (clampIntRange in getDamage). */
        power = (uint32_t)md->base_power * (uint32_t)a->hp / (uint32_t)a->hp_max; /* wide-operands-reviewed: hp <= hp_max */
        power = power < 1u ? 1u : power;
    } else if (md->special == DFI_SPECIAL_TRIPLE_AXEL) {
        /* Triple Axel's basePowerCallback (step G33, data/moves.ts:20005-20023): 20 x move.hit. */
        power = 20u * r->hit_index;
    } else if (md->special == DFI_SPECIAL_BEAT_UP) {
        /* Beat Up's basePowerCallback (step G64): the power of the hit (dfi_beat_up_hits). */
        power = r->beat_up_bp[r->hit_index - 1u];
    } else if (md->special == DFI_SPECIAL_POWER_TRIP) {
        /* Power Trip's basePowerCallback (step G44, data/moves.ts:13851-13859): 20 + 20 x the user's positiveBoosts(), the sum
         * of its positive stages (Pokemon.positiveBoosts, sim/pokemon.ts:1201-1208). A stage is stored biased by 6. */
        const uint32_t positive = dfi_power_trip_positive_stages(ap->stages);
        power = (uint32_t)md->base_power + 20u * positive;
    } else if (md->special == DFI_SPECIAL_ASSURANCE) {
        /* Assurance's basePowerCallback (step G88, data/moves.ts:648-653): doubled when the target was hurt this turn (the
         * HURT_THIS_TURN bit, decision 0046). */
        if (dfi_pos_flag(r->b, target, DFI_POSFLAG_HURT)) {
            power *= 2u;
        }
    } else if (md->special == DFI_SPECIAL_LASH_OUT) {
        /* Lash Out's onBasePower (step G88, data/moves.ts:10055-10059): chainModify(2) when the user's stat fell this turn
         * (LOWERED_THIS_TURN, decision 0046). */
        if (dfi_pos_flag(r->b, user, DFI_POSFLAG_LOWERED)) {
            power *= 2u;
        }
    } else if (md->special == DFI_SPECIAL_RAGE_FIST) {
        /* Rage Fist's basePowerCallback (step G48, data/moves.ts:14583-14596): 50 + 50 x the user's timesAttacked, at most 350.
         * timesAttacked counts the damaging hits the user took since it came in (the Champions loop, scripts.ts:565, and the
         * reset in clearVolatile, scripts.ts:123-170): tail rev 4 hits_taken, saturating at DFI_TAIL_HITS_TAKEN_MAX (6, which
         * already gives 350). */
        const uint32_t taken = r->b->tail.sides[user / 2u].positions[user % 2u].hits_taken;
        power = 50u + 50u * taken;
        power = power > 350u ? 350u : power;
    } else if (md->special == DFI_SPECIAL_RISING_VOLTAGE) {
        /* Rising Voltage's basePowerCallback (step G25, data/moves.ts:15137-15162): doubled while Electric Terrain is up
         * and the target is grounded (whoever the user is). */
        if (r->b->terrain == DFI_TERRAIN_ELECTRIC && dfi_grounded(r->b, d)) {
            power *= 2u;
        }
    } else if (md->special == DFI_SPECIAL_TERRAIN_PULSE) {
        /* Terrain Pulse's onModifyMove (step G25, data/moves.ts:19265-19311): doubled in any terrain for a grounded user. */
        if (r->b->terrain != DFI_TERRAIN_NONE && dfi_grounded(r->b, a)) {
            power *= 2u;
        }
    } else if (md->special == DFI_SPECIAL_HEAVY_SLAM) {
        /* Heavy Slam's basePowerCallback (step G86, data/moves.ts:8533-8552): the user's weight against the target's. */
        power = dfi_heavy_slam_power(dfi_forme_of(a)->weight_hg, dfi_forme_of(d)->weight_hg);
    } else if (md->special == DFI_SPECIAL_HARD_PRESS) {
        /* Hard Press's basePowerCallback (step G86, data/moves.ts:8137-8150): the target's current HP (not the user's). */
        power = dfi_hard_press_power(d->hp, d->hp_max);
    } else if (dfi_move_power_by_weight(md)) {
        power = dfi_weight_power(dfi_forme_of(d)->weight_hg);
    } else if (md->special == DFI_SPECIAL_LAST_RESPECTS) {
        /* Last Respects (Team C): 50 + 50 per fainted member of the user's
         * side (basePowerCallback, data/moves.ts:10091-10105). side.totalFainted
         * is derived: every faint is processed before the next action starts
         * (decision 0009 section 4.1); after a Revival Blessing it is not. */
        if (dfi_revival_spent(r->b, user / 2u)) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        power = 50u + 50u * dfi_fainted_members(r->b, user / 2u);
    }
    uint32_t bp_chain = 4096u;
    bool ok = true;
    const uint32_t bp_move = (uint32_t)(md - dfi_pool_moves); /* wide-operands-reviewed: a pointer into the move table, below DFI_POOL_MOVE_COUNT */
    const uint32_t bp_flags2 = bp_move != DFI_MOVE_STRUGGLE ? (uint32_t)dfi_pool_move_flags2[bp_move] : 0u;
    /* Technician (step G34, data/abilities.ts:4916-4930): onBasePower at priority 30, the first handler, so the chain is
     * still 4096 when it judges `this.modify(basePower, this.event.modifier)`: the move's own power after its callback.
     * 1.5 for 60 or less. */
    if (dfi_ability(r->b, a, DFI_ABILITY_TECHNICIAN) && power <= 60u) {
        ok = dfi_chain_modify(bp_chain, 6144u, &bp_chain);
    }
    ok = dfi_ate_base_power(r->b, a, md, move_type, ok, &bp_chain);
    /* Rivalry (step G83, data/abilities.ts:3881-3898, onBasePowerPriority 24, after Technician's 30 and before Iron Fist's 23): the
     * attacker and the defender both have a gender (male or female): chainModify(1.25) for the same gender, chainModify(0.75)
     * for the other one, and nothing when either is genderless. Its holder is the attacker, and the rival is the defender. */
    if (dfi_ability(r->b, a, DFI_ABILITY_RIVALRY) && dfi_gender_known(a->gender) && dfi_gender_known(d->gender)) {
        ok = ok && dfi_chain_modify(bp_chain, a->gender == d->gender ? 5120u : 3072u, &bp_chain);
    }
    /* Iron Fist (step G34, data/abilities.ts:2236-2248, priority 23 like the -ate abilities, which it never meets: one
     * ability): the punch flag, 4915/4096. */
    if ((bp_flags2 & DFI_MOVE_FLAG2_PUNCH) != 0u && dfi_ability(r->b, a, DFI_ABILITY_IRONFIST)) {
        ok = ok && dfi_chain_modify(bp_chain, 4915u, &bp_chain);
    }
    /* Reckless (step G65, data/abilities.ts:3799-3811, onBasePowerPriority 23, not breakable): chainModify([4915, 4096]) for a move
     * with a recoil of the move data (`move.recoil`, numerator and denominator). Struggle is no such move (its struggleRecoil
     * is a flag, moves.ts:18228), and the crash moves (hasCrashDamage: Axe Kick, High Jump Kick, Supercell Slam) are not modelled:
     * the generator refuses a modelled crash move while this row has no clause for it (pool_families.js checkG65). The priority
     * 23 slot is the one of the -ate abilities and Iron Fist, which the holder cannot have together with it. */
    if (md->recoil[1] != 0u && dfi_ability(r->b, a, DFI_ABILITY_RECKLESS)) {
        ok = ok && dfi_chain_modify(bp_chain, 4915u, &bp_chain);
    }
    if (dfi_ability(r->b, a, DFI_ABILITY_TOUGHCLAWS) && (md->flags & DFI_MOVE_FLAG_CONTACT) != 0u) {
        ok = dfi_chain_modify(bp_chain, 5325u, &bp_chain); /* onBasePowerPriority 21: first */
    }
    /* Sand Force (step G63, data/abilities.ts:3956-3973, onBasePowerPriority 21, the same priority as Tough Claws; a holder has
     * one ability): chainModify([5325, 4096]) for a Rock, Ground or Steel move of its holder while the effective weather is
     * Sandstorm, the field's weather (dfi_field_weather: Cloud Nine suppresses it, step G79; Air Lock is not in the pool). The
     * type is move_type (the attack's type, after the -ate change), which is what the pin's move.type is for these moves. */
    if (dfi_ability(r->b, a, DFI_ABILITY_SANDFORCE) && dfi_field_weather(r) == DFI_WEATHER_SAND &&
        (move_type == DFI_TYPE_ROCK || move_type == DFI_TYPE_GROUND || move_type == DFI_TYPE_STEEL)) {
        ok = ok && dfi_chain_modify(bp_chain, 5325u, &bp_chain);
    }
    /* Sheer Force (step G61, data/abilities.ts:4214-4215, onBasePowerPriority 21 like Tough Claws, which it never meets: one
     * ability): chainModify([5325, 4096]) for a move it stripped and for Electro Shot (hasSheerForceBoost). */
    if (dfi_sf_boosts(r->b, a, md)) {
        ok = ok && dfi_chain_modify(bp_chain, DFI_SHEER_FORCE_MODIFIER, &bp_chain);
    }
    ok = dfi_fairy_aura_base_power(r->b, user, target, move_type, ok, &bp_chain);
    /* Sharpness (step G34, data/abilities.ts:4174-4186, priority 19: after Fairy Aura's 20, before the items' 15): the slicing
     * flag, x1.5. */
    if ((bp_flags2 & DFI_MOVE_FLAG2_SLICING) != 0u && dfi_ability(r->b, a, DFI_ABILITY_SHARPNESS)) {
        ok = ok && dfi_chain_modify(bp_chain, 6144u, &bp_chain);
    }
    /* Mega Launcher (step G59, data/abilities.ts:2546-2556, onBasePowerPriority 19, the same slot as Sharpness, which it never
     * meets: one ability): chainModify(1.5) for a pulse move of its holder (the public static flag PULSE of the pool row,
     * engine column dfi_pool_move_flags3, bit DFI_MOVE_FLAG3_PULSE, which equals the public static PULSE flag of every row; no
     * pulse move is a Struggle). Breakable: no; the Champions mod has no entry. */
    if (bp_move != DFI_MOVE_STRUGGLE && dfi_ability(r->b, a, DFI_ABILITY_MEGALAUNCHER) &&
        (dfi_pool_move_flags3[bp_move] & DFI_MOVE_FLAG3_PULSE) != 0u) {
        ok = ok && dfi_chain_modify(bp_chain, 6144u, &bp_chain);
    }
    /* Muscle Band and Wise Glasses (step G49, data/items.ts:4239-4251 and :7754-7766, onBasePowerPriority 16: after
     * Sharpness's 19 and before the type boosters' 15): 4505/4096 for a Physical move (Muscle Band) or a Special move (Wise
     * Glasses) of its holder. The item the holder has now (dfi_item_code); the move's category is the table's, which is the
     * pinned one for every marked move (no marked move changes its category at the pin). */
    {
        const uint32_t held_now = dfi_item_code(r->b, a);
        if ((held_now == 1u + DFI_ITEM_MUSCLEBAND && md->category == DFI_CATEGORY_PHYSICAL) ||
            (held_now == 1u + DFI_ITEM_WISEGLASSES && md->category == DFI_CATEGORY_SPECIAL)) {
            ok = ok && dfi_chain_modify(bp_chain, 4505u, &bp_chain);
        }
    }
    ok = dfi_type_booster_base_power(r->b, a, move_type, ok, &bp_chain);
    /* Helping Hand's volatile (Team C): chainModify(1.5) at
     * onBasePowerPriority 10, after the items (15) and before Grassy Terrain
     * (6) (data/moves.ts:8590-8597). */
    if (((uint32_t)dfi_pos(r->b, user)->flags & DFI_VOL_HELPING_HAND) != 0u) {
        ok = ok && dfi_chain_modify(bp_chain, 6144u, &bp_chain);
    }
    /* Punk Rock (step G45, data/abilities.ts:3589-3602, onBasePowerPriority 7: after Helping Hand's 10 and the items' 15, before
     * the terrains' 6): chainModify([5325, 4096]) for a sound move of the holder (breakable; Mold Breaker is not marked). */
    if (dfi_ability(r->b, a, DFI_ABILITY_PUNKROCK) && md->special != DFI_SPECIAL_STRUGGLE &&
        (dfi_pool_move_flags2[(uint32_t)(md - dfi_pool_moves)] & DFI_MOVE_FLAG2_SOUND) != 0u) { /* wide-operands-reviewed: a pointer into the move table */
        ok = ok && dfi_chain_modify(bp_chain, 5325u, &bp_chain);
    }
    if (move_type == DFI_TYPE_GRASS && r->b->terrain == DFI_TERRAIN_GRASSY && dfi_grounded(r->b, a)) {
        ok = ok && dfi_chain_modify(bp_chain, 5325u, &bp_chain);
    }
    /* Grassy Terrain's other half (step G28, data/moves.ts:7694-7698): Earthquake (and Bulldoze and Magnitude, which are not
     * marked) at a grounded target is chainModify(0.5), the first branch of the same handler (priority 6); a Ground move is
     * not a Grass move, so the two never both apply. */
    if (md == &dfi_pool_moves[DFI_MOVE_EARTHQUAKE] && r->b->terrain == DFI_TERRAIN_GRASSY && dfi_grounded(r->b, d) &&
        !dfi_semi_invulnerable(r, target)) { /* data/moves.ts:7695 (weakenedMoves: Earthquake is the marked one) */
        ok = ok && dfi_chain_modify(bp_chain, 2048u, &bp_chain);
    }
    /* Psychic Terrain (Team C): 5325/4096 for a grounded user's Psychic move
     * (onBasePowerPriority 6, like Grassy Terrain's, which cannot be up at
     * the same time). */
    if (move_type == DFI_TYPE_PSYCHIC && r->b->terrain == DFI_TERRAIN_PSYCHIC && dfi_grounded(r->b, a) &&
        !dfi_semi_invulnerable(r, user)) { /* data/moves.ts:14132 */
        ok = ok && dfi_chain_modify(bp_chain, 5325u, &bp_chain);
    }
    /* Electric Terrain (step G25, data/moves.ts:4520-4527): 5325/4096 for a grounded user's Electric move, the same
     * handler slot (priority 6). Misty Terrain (:12175-12181): chainModify(0.5), 2048/4096, for a Dragon move at a grounded
     * target. */
    /* The attacker's boost: a semi-invulnerable user gets none (data/moves.ts:4533, :14132; no pool move reads it while the user is
     * semi-invulnerable, the predicate keeps the reading of the pin). */
    if (move_type == DFI_TYPE_ELECTRIC && r->b->terrain == DFI_TERRAIN_ELECTRIC && dfi_grounded(r->b, a) &&
        !dfi_semi_invulnerable(r, user)) {
        ok = ok && dfi_chain_modify(bp_chain, 5325u, &bp_chain);
    }
    if (move_type == DFI_TYPE_DRAGON && r->b->terrain == DFI_TERRAIN_MISTY && dfi_grounded(r->b, d) &&
        !dfi_semi_invulnerable(r, target)) { /* data/moves.ts:12186 */
        ok = ok && dfi_chain_modify(bp_chain, 2048u, &bp_chain);
    }
    /* Expanding Force's own onBasePower (step G15, data/moves.ts:4952-4957): chainModify(1.5) for a grounded user in
     * Psychic Terrain. runEvent puts the move's handler first and sorts by priority: its priority is 0, so it runs
     * after the terrain's (6), Helping Hand's (10) and the items' (15), and the chain rounds once at the end. */
    if (md->special == DFI_SPECIAL_EXPANDING_FORCE && r->b->terrain == DFI_TERRAIN_PSYCHIC && dfi_grounded(r->b, a)) {
        ok = ok && dfi_chain_modify(bp_chain, 6144u, &bp_chain);
    }
    /* Knock Off's onBasePower (data/moves.ts:9959-9984, priority 0, so after every handler above): 1.5x while its
     * target holds an item that can be taken (Sticky Hold does not matter here: only the item's own TakeItem is asked). */
    if (md->special == DFI_SPECIAL_KNOCK_OFF && dfi_item_takeable(r->b, d)) {
        ok = ok && dfi_chain_modify(bp_chain, 6144u, &bp_chain);
    }
    /* Solar Beam's onBasePower (step G30, data/moves.ts:17245-17251, priority 0 like Knock Off's, after every handler
     * above): chainModify(0.5) in rain, Sandstorm or Snow; Utility Umbrella and Mega Sol are not marked. */
    const uint32_t bp_weather = dfi_move_weather(r, a, md->special == DFI_SPECIAL_SOLAR_BEAM);
    if (md->special == DFI_SPECIAL_SOLAR_BEAM &&
        (bp_weather == DFI_WEATHER_RAIN || bp_weather == DFI_WEATHER_SAND || bp_weather == DFI_WEATHER_SNOW)) {
        ok = ok && dfi_chain_modify(bp_chain, 2048u, &bp_chain);
    }
    const uint32_t base_power = bp_chain == 4096u ? power : dfi_modify(power, bp_chain);
    c->ok = ok;
    c->base_power = base_power;
    return DUOFORGE_OK;
}

#endif
