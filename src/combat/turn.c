#include "combat/turn.h"

#include "combat/abilities/families.h"
#include "combat/abilities/fairy_aura.h"
#include "combat/abilities/protect_bypass.h"
#include "combat/damage_chain.h"
#include "combat/moves/multiaccuracy.h"
#include "combat/residual_order.h"
#include "combat/events.h"
#include "combat/items/items.h"
#include "combat/moves/families.h"
#include "combat/moves/multihit.h"
#include "combat/moves/power_trip.h"
#include "combat/moves/tri_attack.h"
#include "combat/sheer_force.h"
#include "combat/moves/ohko.h"
#include "combat/moves/beat_up.h"
#include "combat/moves/special_handlers.h"

#include "core/arith.h"
#include "core/inline.h"
#include "core/modifier.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "state/closure_member.h"
#include "state/context_internal.h"
#include "state/identity.h"
#include "state/knowledge.h"

#define DFI_SPEED_BIAS 10000u   /* speed key: 10000 + speed, or 10000 - speed under Trick Room */
#define DFI_SPEED_CAP 10000u    /* getStat caps Speed at 10000 (sim/pokemon.ts:636) */
#define DFI_LEVEL DFI_FORMAT_LEVEL


#define DFI_MOVE_TARGET_NONE DFI_POSITIONS          /* no target Pokemon */
#define DFI_MOVE_TARGET_SPREAD (DFI_POSITIONS + 1u) /* a spread move's random foe, not drawn */

typedef struct dfi_key {
    uint32_t order;
    uint32_t priority; /* biased like the move table */
    uint32_t speed;    /* DFI_SPEED_BIAS +/- speed */
} dfi_key;

/* ---------------------------------------------------------------- access */



/* Tail rev 5 position flags (G72b, decision 0015 5ce): the stats-raised bit of a position (Alluring Voice's statsRaisedThisTurn)
 * and the Dragon Cheer crit stage (0, 1 or 2; the holder's onModifyCritRatio, read in dfi_get_damage). */
static bool dfi_stats_raised(const struct duoforge_battle *b, uint32_t flat)
{
    return (((uint32_t)b->tail.sides[flat / 2u].positions[flat % 2u].position_flags & DFI_POSFLAG_STATS_RAISED) != 0u);
}

static uint32_t dfi_dragon_cheer_stage(const struct duoforge_battle *b, uint32_t flat)
{
    return ((uint32_t)b->tail.sides[flat / 2u].positions[flat % 2u].position_flags & DFI_POSFLAG_DRAGON_CHEER_MASK) >>
           DFI_POSFLAG_DRAGON_CHEER_SHIFT;
}

/* Step G88 (decision 0046): the turn-history bits of a position, LOWERED (Lash Out, statsLoweredThisTurn) and HURT (Assurance,
 * hurtThisTurn). Both are zero at a turn boundary and with the occupant. */
static bool dfi_pos_flag(const struct duoforge_battle *b, uint32_t flat, uint32_t bit)
{
    return (((uint32_t)b->tail.sides[flat / 2u].positions[flat % 2u].position_flags & bit) != 0u);
}

/* The brought members of a side at 0 HP: side.totalFainted, since faints are processed before the next action (decision 0009
 * section 4.1; Last Respects). A revived member (Revival Blessing, decision 0025 item 6) fainted once more than the roster
 * shows, and the state does not count revivals: dfi_revival_spent below refuses that case. */
static uint32_t dfi_fainted_members(const struct duoforge_battle *b, uint32_t side)
{
    const dfi_side *sd = &b->sides[side];
    uint32_t n = 0u;
    for (uint32_t m = 0u; m < sd->member_count && m < DUOFORGE_MAX_ROSTER; ++m) {
        const bool brought = (((uint32_t)sd->brought_mask >> m) & 1u) != 0u;
        n += brought && sd->members[m].hp == 0u ? 1u : 0u;
    }
    return n;
}

/* A brought member of the side has spent PP of Revival Blessing (used it, with or without a revive). side.totalFainted then may
 * exceed the members at 0 HP (sim/battle.ts:2554 counts every faint; the revive returns the member to the roster), so a Last
 * Respects of that side is refused (E_UNSUPPORTED), never played with the roster count. */
static bool dfi_revival_spent(const struct duoforge_battle *b, uint32_t side)
{
    const dfi_side *sd = &b->sides[side];
    for (uint32_t m = 0u; m < sd->member_count && m < DUOFORGE_MAX_ROSTER; ++m) {
        if ((((uint32_t)sd->brought_mask >> m) & 1u) == 0u) {
            continue;
        }
        for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
            const dfi_move_slot *ms = &sd->members[m].moves[k];
            if (ms->move_id == DFI_MOVE_REVIVALBLESSING && ms->pp < ms->pp_max) {
                return true;
            }
        }
    }
    return false;
}

static const dfi_pool_forme_data *dfi_forme_of(const dfi_member *m)
{
    /* The Mega forme is that of the pair (base forme, stone): the member still holds the stone (a Mega Stone is never
     * taken from its own species, dfi_item_takeable). */
    return m->is_mega != 0u ? &dfi_pool_formes[dfi_mega_of(m->species_id, m->item)] : &dfi_pool_formes[m->species_id];
}

/* The member's types now (Pokemon.getTypes): its forme's, or the one type that Soak set (setType, sim/pokemon.ts:2109;
 * the POOL tail's soak_type of the member, zero under every other kind), which lasts until the Pokemon leaves the field,
 * faints, Mega Evolves or changes forme by Stance Change (setSpecies resets the types, sim/pokemon.ts:1392). `m` is a member
 * of `b`. */
/* The move result classes of one move action (step G42; dfi_run_move, the pin's moveThisTurnResult of sim/battle-actions.ts):
 * TRUE when a target took the move, FALSE for a literal `false` of the hit steps (a miss, an immunity, a failed effect, a
 * Psychic Terrain block that returns null and is normalised to false, an action that is stopped before it moves), NULL for a
 * target that Protect or Wide Guard took (NOT_FAIL, which is no failure), and UNCLASSIFIED for any exit the classifier does
 * not map exactly. TRUE wins over FALSE, FALSE over NULL (trySpreadMoveHit: `!targets.length && !atLeastOneFailure` is null). */
#define DFI_MRES_TRUE 1u
#define DFI_MRES_FALSE 2u
#define DFI_MRES_NULL 4u
#define DFI_MRES_UNCLASS 8u

/* Roost's volatile (single_turn bit) of the member's position, when the member is on the field. */
static bool dfi_roosted(const struct duoforge_battle *b, const dfi_member *m)
{
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const dfi_member *first = &b->sides[s].members[0];
        if (m >= first && m < first + DUOFORGE_MAX_ROSTER) {
            const uint32_t idx = (uint32_t)(m - first); /* wide-operands-reviewed: a pointer difference inside one array */
            for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
                if (b->sides[s].positions[p].occupant == idx) {
                    return (b->tail.sides[s].positions[p].single_turn & DFI_SINGLE_TURN_ROOST) != 0u;
                }
            }
            return false;
        }
    }
    return false;
}

static void dfi_types_of(const struct duoforge_battle *b, const dfi_member *m, uint32_t types[2])
{
    const dfi_pool_forme_data *f = dfi_forme_of(m);
    types[0] = f->types[0];
    types[1] = f->types[1];
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const dfi_member *first = &b->sides[s].members[0];
        if (m >= first && m < first + DUOFORGE_MAX_ROSTER) {
            const uint32_t soak = b->tail.sides[s].soak_type[m - first];
            if (soak == DFI_TAIL_TYPE2_TYPELESS) {
                /* Double Shock (decision 0025, data/moves.ts:3960-3964): the first slot is ??? (no type: DFI_CLOSURE_NONE, which
                 * every reader skips, since no chart row is that large) and the second is type2, id + 1 (invariant TAIL_MEMBER). */
                const uint32_t second = b->tail.sides[s].type2[m - first];
                types[0] = DFI_CLOSURE_NONE;
                types[1] = second != 0u ? second - 1u : DFI_CLOSURE_NONE;
            } else if (soak != 0u) {
                types[0] = soak - 1u; /* a single type */
                types[1] = DFI_CLOSURE_NONE;
            }
            break;
        }
    }
    /* Roost (step G42, the onType of data/moves.ts:15444-15455): the Flying type is filtered out after the other types.
     * An empty list is Normal from gen 5 (Pokemon.getTypes, sim/pokemon.ts:2143), so a pure Flying Pokemon is Normal for
     * the turn. Not a type change: type_now and the TYPE_CHANGED view stay as they are. */
    if (dfi_roosted(b, m)) {
        uint32_t kept[2] = {DFI_CLOSURE_NONE, DFI_CLOSURE_NONE};
        uint32_t n = 0u;
        for (uint32_t i = 0u; i < 2u; ++i) {
            if (types[i] != DFI_CLOSURE_NONE && types[i] != DFI_TYPE_FLYING) {
                kept[n] = types[i];
                n += 1u;
            }
        }
        if (n == 0u) {
            kept[0] = DFI_TYPE_NORMAL;
        }
        types[0] = kept[0];
        types[1] = kept[1];
    }
}

/* Double Shock plays only Pawmot (decision 0025 item 2): the user's types are exactly its own Electric and Fighting, and
 * its forme is dex 923. Every other user that has the Electric type is refused (E_UNSUPPORTED) before the move does anything. */
static bool dfi_double_shock_shape(struct duoforge_battle *b, uint32_t user)
{
    const dfi_member *m = dfi_at(b, user);
    uint32_t t[2];
    dfi_types_of(b, m, t);
    return m != NULL && dfi_forme_of(m)->dex_num == 923u && t[0] == DFI_TYPE_ELECTRIC && t[1] == DFI_TYPE_FIGHTING;
}

static DFI_ALWAYS_INLINE bool dfi_has_type(const struct duoforge_battle *b, const dfi_member *m, uint32_t type)
{
    uint32_t t[2];
    dfi_types_of(b, m, t);
    return t[0] == type || t[1] == type;
}

static bool dfi_ability(const struct duoforge_battle *b, const dfi_member *m, uint32_t id);


#include "combat/field/terrain.h"



/* eachEvent('TerrainChange'), defined with the seeds below: a terrain that starts or ends runs it. */
static duoforge_status dfi_terrain_change(dfi_run *r);



/* The genders that Rivalry reads (step G83): a male or a female member. A genderless one (DUOFORGE_GENDER_NONE) has none, so
 * its Rivalry does nothing (data/abilities.ts:3884, `attacker.gender && defender.gender`). */
static bool dfi_gender_known(uint32_t gender)
{
    return gender == DUOFORGE_GENDER_MALE || gender == DUOFORGE_GENDER_FEMALE;
}



#include "combat/field/duration.h"








/* ---------------------------------------------------------------- weather (step G79)
 *
 * The weather that a read sees is one predicate, dfi_field_weather (Field.effectiveWeather, sim/field.ts:101-104), with the
 * move reading of Mega Sol on top (dfi_move_weather, Pokemon#effectiveWeather, sim/pokemon.ts:2190-2212). Every read of the
 * weather in this file goes through one of the two; the raw state b->weather is read only where the reference reads the raw
 * field (the setters, the countdown and the upkeep, the weather's own sun/rain effects are read through the field too). */

/* A faint of the current run that faintMessages has not shown yet: faint_queue[faint_announced..faint_count). */
static bool dfi_faint_pending(const dfi_run *r, uint32_t flat)
{
    for (uint32_t i = r->faint_announced; i < r->faint_count; ++i) {
        if (r->faint_queue[i] == flat) {
            return true;
        }
    }
    return false;
}

#include "combat/field/weather.h"





/* ---------------------------------------------------------------- events */







/* Flower Veil (data/abilities.ts:1419-1457): the holder protects every Grass-type Pokemon of its side, itself
 * included (it is Fairy, so what it covers is its allies), against stat drops and statuses that another Pokemon
 * causes. `flat` is the protected one: its Grass type and a standing holder on its side (the pool has one forme with
 * the ability, and the Species Clause allows one holder). Flower Veil is breakable (Mold Breaker would ignore it): no
 * forme of the pool that has Mold Breaker is marked. */
static bool dfi_flower_veil_holder(struct duoforge_battle *b, uint32_t flat, uint32_t *holder)
{
    const dfi_member *target = dfi_at(b, flat);
    if (target == NULL || !dfi_has_type(b, target, DFI_TYPE_GRASS)) {
        return false;
    }
    for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
        const uint32_t other = (flat / 2u) * 2u + slot;
        const dfi_member *m = dfi_at(b, other);
        if (m != NULL && m->hp != 0u && dfi_ability(b, m, DFI_ABILITY_FLOWERVEIL)) {
            *holder = other;
            return true;
        }
    }
    return false;
}

/* -block|target|ability: Flower Veil|[of] holder: the public ACTIVATE event with the protected Pokemon as its
 * position and the holder in `other` (the ability's own activation has no `other`). */
static void dfi_flower_veil_block(dfi_run *r, uint32_t flat, uint32_t holder)
{
    const duoforge_event e =
        dfi_ev(DUOFORGE_EVENT_ACTIVATE, flat, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_FLOWERVEIL, holder);
    dfi_emit(r, &e);
}

/* Clear Body's -fail|holder|unboost|[from] ability: Clear Body|[of] holder (step G30, data/abilities.ts:523-542): the
 * FAIL event with the ability as its cause and the holder as the `other`, as Inner Focus's (step G22). */
static void dfi_clear_body_block(dfi_run *r, uint32_t flat, uint32_t ability)
{
    const duoforge_event e = dfi_ev(DUOFORGE_EVENT_FAIL, flat, DUOFORGE_CAUSE_ABILITY, 1u + ability, flat);
    dfi_emit(r, &e);
}

/* The natural powder immunity (dex.getImmunity('powder', pokemon)): the types whose chart entry has `powder: 3`, the Grass
 * type alone (data/typechart.ts; the generator checks it, POWDER_IMMUNE_TYPES), judged by the types now. */
static bool dfi_powder_natural_immune(const struct duoforge_battle *b, const dfi_member *m)
{
    return dfi_has_type(b, m, DFI_TYPE_GRASS);
}

/* runStatusImmunity('powder') (sim/pokemon.ts): true when the Pokemon is immune, which is its natural immunity or an
 * Immunity handler that returns false for powder: Overcoat (step G30, data/abilities.ts:3108-3122). Safety Goggles'
 * handler (data/items.ts:5465) has the same answer; the item is not in the pool. */
static bool dfi_powder_immune(const struct duoforge_battle *b, const dfi_member *m)
{
    return dfi_powder_natural_immune(b, m) || dfi_ability(b, m, DFI_ABILITY_OVERCOAT);
}

/* An event that shows the HP of the Pokemon at e.position, exact; each
 * player's projection shows the opponent's as the percent display. */
static void dfi_emit_hp(dfi_run *r, duoforge_event e)
{
    const dfi_member *m = dfi_at(r->b, e.position);
    if (m != NULL) {
        dfi_event_set_hp(&e, m);
    }
    dfi_emit(r, &e);
}

static void dfi_emit_plain(dfi_run *r, uint32_t kind, uint32_t position)
{
    const duoforge_event e = dfi_event_make(kind, position);
    dfi_emit(r, &e);
}

/* attrLastMove and retargetLastMove: the action's move event, amended by a
 * later line; NULL when nothing is recorded. */
static duoforge_event *dfi_last_move(dfi_run *r)
{
    if (r->events == NULL || r->last_move >= r->events->count) {
        return NULL;
    }
    return &r->events->rec[r->last_move];
}

/* attrLastMove('[still]'): no animation, so the target is not shown. */
static void dfi_still(dfi_run *r)
{
    duoforge_event *mv = dfi_last_move(r);
    if (mv != NULL) {
        mv->flags = (uint8_t)((uint32_t)mv->flags | DUOFORGE_EVENT_FLAG_STILL); /* wide-operands-reviewed: < 256 */
        mv->other = (uint8_t)DUOFORGE_NO_POSITION;
    }
}

/* The `-fail` for the user, then [still] on its move line, without a result of the move: a handler that prints them and
 * returns null (the Substitute's onTryPrimaryHit, data/moves.ts:18341-18347) leaves the result to the hit value. */
static void dfi_fail_line(dfi_run *r, uint32_t user)
{
    dfi_emit_plain(r, DUOFORGE_EVENT_FAIL, user);
    dfi_still(r);
}

/* The move failed: -fail for the user, then [still] on its move line. */
static void dfi_fail_still(dfi_run *r, uint32_t user)
{
    dfi_fail_line(r, user);
    r->mres |= DFI_MRES_FALSE; /* a [still] failure returns false (sim/battle-actions.ts, useMoveInner and runMoveEffects) */
}

/* -immune for `flat`, with [from] ability when an ability did it. */
static void dfi_immune(dfi_run *r, uint32_t flat, uint32_t ability)
{
    const uint32_t cause = ability != 0u ? DUOFORGE_CAUSE_ABILITY : DUOFORGE_CAUSE_NONE;
    const duoforge_event e = dfi_ev(DUOFORGE_EVENT_IMMUNE, flat, cause, ability, DUOFORGE_NO_POSITION);
    dfi_emit(r, &e);
}

/* A stat (0 atk .. 4 spe) after its stage (getStat without modifiers). */
static duoforge_status dfi_staged_stat(const dfi_member *m, const dfi_active_slot *pos, uint32_t index,
                                       uint32_t *out)
{
    return dfi_stage_stat(m->stats[index], pos->stages[index], out) ? DUOFORGE_OK : DUOFORGE_E_INVARIANT;
}



/* getActionSpeed of the Champions mod (data/mods/champions/scripts.ts:46-55):
 * the staged Speed times the chained ModifySpe modifiers (Tailwind
 * chainModify(2), Choice Scarf chainModify(1.5), Team C; one rounding), then
 * halved by paralysis (its onModifySpe runs last: finalModify, then floor of
 * 50 of 100), capped, negated under Trick Room. A fainted Pokemon is not active
 * (faintMessages, sim/battle.ts:2566), and getStat runs ModifySpe with no source: Battle.findEventHandlers
 * (sim/battle.ts:1053) then gathers no handler of the Pokemon's or of its side, so neither its Choice Scarf, Unburden
 * or paralysis nor its side's Tailwind counts (a probe at the pin: a fainted Scarf holder under Tailwind has its raw
 * Speed), and Trick Room, which Pokemon.getActionSpeed reads itself, still applies: its queued action or its
 * replacement has the raw Speed. The same isActive decides the abilities and items in dfi_move_priority. */
static duoforge_status dfi_speed_key(const dfi_run *r, uint32_t side, const dfi_member *m,
                                     const dfi_active_slot *pos, uint32_t *out)
{
    const struct duoforge_battle *b = r->b;
    uint32_t spe = 0u;
    const duoforge_status st = dfi_staged_stat(m, pos, DFI_STAT_SPE - 1u, &spe);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const bool active = m->hp != 0u;
    uint32_t chain = 4096u;
    if (active && b->sides[side].tailwind_turns != 0u) {
        chain = 8192u;
    }
    if (active && dfi_holds(b, m, DFI_ITEM_CHOICESCARF) && !dfi_chain_modify(chain, 6144u, &chain)) {
        return DUOFORGE_E_INVARIANT;
    }
    /* Iron Ball (step G83, data/items.ts:3062-3064, onModifySpe): chainModify(0.5) for its standing holder, in the chain of the
     * items (one item per holder: never with Choice Scarf). */
    if (active && dfi_holds(b, m, DFI_ITEM_IRONBALL) && !dfi_chain_modify(chain, 2048u, &chain)) {
        return DUOFORGE_E_INVARIANT;
    }
    /* Unburden's volatile (Team C): chainModify(2) while its holder holds no item (data/abilities.ts:5247-5251): the
     * volatile is set when the item is used or taken, and also when a Mega Stone on its own species refuses Knock Off
     * (dfi_knock_off), so the item is asked for. */
    if (active && ((uint32_t)pos->flags & DFI_VOL_UNBURDEN) != 0u && dfi_item_code(b, m) == 0u &&
        !dfi_chain_modify(chain, 8192u, &chain)) {
        return DUOFORGE_E_INVARIANT;
    }
    /* Sand Rush, Swift Swim, Slush Rush and Chlorophyll (step G22, POOL data): onModifySpe chainModify(2) while their
     * weather is up (data/abilities.ts:3974-3979 sandrush, 4808-4813 swiftswim, 4347-4352 slushrush, 512-517
     * chlorophyll; the Champions mod has no entry of any of them). The holder has one ability, so at most one of the
     * four counts. The weather is dfi_field_weather (Field.isWeather, sim/field.ts:118): Cloud Nine suppresses it while
     * a holder stands (step G79); Air Lock and Utility Umbrella are not in the pool. Like the items and Unburden, only a
     * standing holder counts: a fainted one has its raw Speed (the
     * same isActive rule as above, the ability handler of a Pokemon that is not active is ignored). */
    if (active && dfi_weather_speed_ability(r, m)) {
        if (!dfi_chain_modify(chain, 8192u, &chain)) {
            return DUOFORGE_E_INVARIANT;
        }
    }
    /* Surge Surfer (A2a, decision 0015 entry 5dy; data/abilities.ts:4755-4763, onModifySpe, no priority): chainModify(2) while
     * the field's terrain is Electric Terrain (Field.isTerrain; no TryTerrain handler is in the pool); the terrain twin of the
     * weather abilities above. Quick Feet (data/abilities.ts:3748-3756): chainModify(1.5) while the holder has a status. Every
     * factor of this chain is 2048, 6144 or 8192 out of 4096, so the products are exact and the order of the handlers does not
     * change the value. The holder has one ability, so at most one of the Speed abilities counts. */
    if (active && b->terrain == DFI_TERRAIN_ELECTRIC && dfi_ability(b, m, DFI_ABILITY_SURGESURFER) &&
        !dfi_chain_modify(chain, 8192u, &chain)) {
        return DUOFORGE_E_INVARIANT;
    }
    const bool quick_feet = active && dfi_ability(b, m, DFI_ABILITY_QUICKFEET);
    if (quick_feet && m->status != DFI_STATUS_NONE && !dfi_chain_modify(chain, 6144u, &chain)) {
        return DUOFORGE_E_INVARIANT;
    }
    if (chain != 4096u) {
        spe = dfi_modify(spe, chain); /* spe <= 4 * 65535, chain <= 12 * 4096 */
    }
    /* par's onModifySpe (data/conditions.ts:30-38; the Champions par entry changes only onBeforeMove) halves the Speed after the
     * chain unless the holder has Quick Feet. */
    if (active && m->status == DFI_STATUS_PAR && !quick_feet) {
        spe = spe * 50u / 100u; /* spe <= 48 * 65535: stage x4, chain x12 */
    }
    if (spe > DFI_SPEED_CAP) {
        spe = DFI_SPEED_CAP;
    }
    *out = b->trick_room_turns != 0u ? DFI_SPEED_BIAS - spe : DFI_SPEED_BIAS + spe;
    return DUOFORGE_OK;
}

/* A queued move names a slot its actor has, Struggle or the recharge turn. The checker
 * accepts any slot up to the recharge turn (structure, not reachability), so a
 * decoded state can name an empty slot: that fails loudly instead of
 * running the empty slot. */
static bool dfi_move_slot_ok(const dfi_member *m, uint32_t move_slot)
{
    return move_slot == DUOFORGE_MOVE_SLOT_STRUGGLE || move_slot == DUOFORGE_MOVE_SLOT_RECHARGE ||
           move_slot < m->move_count;
}

/* The move of a queued action. The recharge turn is the action 'recharge' of the reference, a name that is no move
 * (priority 0, no category, no flags, never the Encored move): Struggle's data stands in for it wherever only the
 * priority and "is it another move" are read; dfi_run_move runs it by its slot. */
static uint32_t dfi_move_of(const dfi_member *m, uint32_t move_slot)
{
    return move_slot == DUOFORGE_MOVE_SLOT_STRUGGLE || move_slot == DUOFORGE_MOVE_SLOT_RECHARGE
               ? DFI_MOVE_STRUGGLE
               : m->moves[move_slot].move_id;
}

#include "combat/flow/queue.h"

/* ---------------------------------------------------------------- stages */

/* The effect behind a stat change, for the lines of Battle.boost: a move's
 * lines are plain, an item's say [from] item, an ability's first change
 * follows an -ability line unless the change is secondary. A change of 0
 * shows for a primary move or item effect (without [from]) and for an
 * ability's secondary or self change. */
#define DFI_BOOST_PRIMARY 0u
#define DFI_BOOST_SECONDARY 1u /* isSecondary */
#define DFI_BOOST_SELF 2u      /* isSelf */

typedef struct dfi_boost_effect {
    uint32_t cause; /* DUOFORGE_CAUSE_MOVE, _ITEM or _ABILITY */
    uint32_t id2;   /* 1 + the item or ability id; 0 for a move */
    uint32_t mode;  /* DFI_BOOST_PRIMARY, _SECONDARY or _SELF */
    bool negatives_first; /* the stats that fall are changed before the ones that rise (Shell Smash, step G28) */
    bool positives_first; /* the stats that rise (of the input boost) are changed first, then the others (Moody, step G73: the
                           * reference's key order, raised key inserted first, sim/battle.ts boost loop) */
} dfi_boost_effect;

static dfi_boost_effect dfi_effect(uint32_t cause, uint32_t id2, uint32_t mode)
{
    const dfi_boost_effect e = {cause, id2, mode, false, false};
    return e;
}

/* Battle.boost (sim/battle.ts:2020-2088): nothing for a fainted Pokemon or
 * when its foes have no Pokemon left. Contrary reverses the changes
 * (ChangeBoost); getCappedBoost caps every change against the stages
 * before the first one; then each stat of the boost, in table order, moves
 * by its capped amount and shows its line, and a stat that changed runs
 * AfterEachBoost: Competitive raises Special Attack by 2 (a self change of
 * the ability) when a foe lowered a stat. `source` is the flat position of
 * the Pokemon that caused it, or DFI_POSITIONS for the holder itself. */
static uint32_t dfi_left(const struct duoforge_battle *b, uint32_t side);
static void dfi_apply_boosts(dfi_active_slot *pos, const uint8_t *boosts);

static bool dfi_boost(dfi_run *r, uint32_t flat, const uint8_t *boosts, uint32_t source, dfi_boost_effect effect)
{
    struct duoforge_battle *b = r->b;
    const dfi_member *m = dfi_at(b, flat);
    bool changed = false;
    if (m == NULL || m->hp == 0u) {
        return false;
    }
    /* foePokemonLeft counts a Pokemon until its faint is processed; the
     * reference processes a faint when it announces it. */
    uint32_t foes_left = dfi_left(b, 1u - flat / 2u);
    for (uint32_t i = r->faint_announced; i < r->faint_count; ++i) {
        foes_left += r->faint_queue[i] / 2u != flat / 2u ? 1u : 0u;
    }
    if (foes_left == 0u) {
        return false;
    }
    dfi_active_slot *pos = dfi_pos(b, flat);
    uint8_t capped[DFI_STAT_STAGE_COUNT] = {6u, 6u, 6u, 6u, 6u, 6u, 6u}; /* biased by 6 */
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        const uint32_t want = dfi_ability(r->b, m, DFI_ABILITY_CONTRARY) ? 12u - (uint32_t)boosts[i] : boosts[i];
        const uint32_t sum = (uint32_t)pos->stages[i] + want; /* the target stage, biased by 12 */
        const uint32_t to = sum < 6u ? 0u : (sum - 6u > 12u ? 12u : sum - 6u);
        const uint32_t delta = to + 6u - (uint32_t)pos->stages[i];
        capped[i] = (uint8_t)delta; /* 0..12 */
    }
    /* TryBoost (after Contrary and the cap), its handlers in the pin's order (sim/battle.ts:2034 runEvent): the higher
     * onTryBoostPriority first, Guard Dog's 2 before every other handler here (default 0). */
    bool veil[DFI_STAT_STAGE_COUNT] = {false, false, false, false, false, false, false};
    /* Guard Dog (step G46, data/abilities.ts:1727-1744, onTryBoost of the holder, onTryBoostPriority 2, breakable): an
     * Intimidate change of Attack is deleted and the holder's Attack rises by 1 instead (`this.boost({ atk: 1 }, target,
     * target, null, ...)`: a boost with no effect, so its line has no [from]). Its line is the nested boost's; nothing
     * shows for the deleted drop. It runs before Flower Veil (decision 0015 entry 5ec, issue 640): on a Grass holder
     * (Skill Swap, step G70, gives Guard Dog to one) next to a Flower Veil holder the drop is already gone when Flower
     * Veil looks, so no -block shows. */
    if (effect.cause == DUOFORGE_CAUSE_ABILITY && effect.id2 == 1u + DFI_ABILITY_INTIMIDATE &&
        boosts[DFI_STAGE_ATK] != DFI_BIAS6 && capped[DFI_STAGE_ATK] != DFI_BIAS6 && dfi_ability(r->b, m, DFI_ABILITY_GUARDDOG)) {
        veil[DFI_STAGE_ATK] = true;
        static const uint8_t guard_dog_atk_up[DFI_STAT_STAGE_COUNT] = {7u, 6u, 6u, 6u, 6u, 6u, 6u};
        /* The nested boost's effect is the running handler, Guard Dog (boost() defaults to this.effect): its line is
         * -ability|holder|Guard Dog|boost, then the -boost line (sim/battle.ts boost). */
        (void)dfi_boost(r, flat, guard_dog_atk_up, flat, dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_GUARDDOG, DFI_BOOST_PRIMARY));
    }
    /* Flower Veil deletes every drop that another Pokemon causes on a Grass type of its side (sim/battle.ts:2030-2033,
     * data/abilities.ts:1419-1437) and that is still in the boost (a drop Guard Dog deleted is not); the line shows
     * unless the effect is a move's secondary (effect.secondaries): Intimidate's does, Snarl's does not. */
    uint32_t holder = 0u;
    bool flower_veiled = false; /* Flower Veil deleted a drop (A2a: read by the Illuminate and White Smoke refusals below) */
    if (source != flat && source != DFI_POSITIONS && dfi_flower_veil_holder(b, flat, &holder)) {
        bool any = false;
        for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
            const bool drop = !veil[i] && boosts[i] != DFI_BIAS6 && capped[i] < DFI_BIAS6;
            veil[i] = veil[i] || drop;
            any = any || drop;
        }
        flower_veiled = any;
        if (any && !(effect.cause == DUOFORGE_CAUSE_MOVE && effect.mode == DFI_BOOST_SECONDARY)) {
            dfi_flower_veil_block(r, flat, holder);
        }
    }
    /* Inner Focus (step G22, POOL data, data/abilities.ts:2157-2162): TryBoost, a change that the effect named
     * Intimidate would make to Attack (boost.atk is set: a change the cap already took to 0 is not) is deleted, and
     * -fail|holder|unboost|atk|[from] ability: Inner Focus|[of] holder shows. The Pokemon is no Grass type of a side
     * with Flower Veil, whose own TryBoost handler would race this one by Speed: no Inner Focus holder of the pool is
     * a Grass type (tools/datagen/pool_families.js checkG22). Breakable, like Flower Veil. The same holds for Scrappy and
     * Oblivious below, as forme facts only: Skill Swap (step G70) can still give one of the three to a Grass type next to a
     * Flower Veil holder; that composition is not refused here (decision 0015 entry 5dy, a follow-up). */
    /* Scrappy (step G39, data/abilities.ts:4079-4098) has the same onTryBoost for Intimidate, with the same line (its other
     * half, the immunity of Ghost types to Normal and Fighting moves, is in dfi_get_damage's caller). */
    /* Oblivious (step G47, data/abilities.ts:3026-3031): the same onTryBoost for Intimidate's Attack drop, with the same line
     * (`[of] ${target}`); its Attract half of onUpdate is not reached (no Attract volatile). */
    const uint32_t intimidate_guard = dfi_ability(r->b, m, DFI_ABILITY_INNERFOCUS) ? DFI_ABILITY_INNERFOCUS
                                      : dfi_ability(r->b, m, DFI_ABILITY_SCRAPPY)  ? DFI_ABILITY_SCRAPPY
                                      : dfi_ability(r->b, m, DFI_ABILITY_OBLIVIOUS) ? DFI_ABILITY_OBLIVIOUS
                                                                                    : DFI_POOL_ABILITY_COUNT;
    if (effect.cause == DUOFORGE_CAUSE_ABILITY && effect.id2 == 1u + DFI_ABILITY_INTIMIDATE &&
        boosts[DFI_STAGE_ATK] != DFI_BIAS6 && capped[DFI_STAGE_ATK] != DFI_BIAS6 && intimidate_guard != DFI_POOL_ABILITY_COUNT) {
        veil[DFI_STAGE_ATK] = true;
        const duoforge_event e =
            dfi_ev(DUOFORGE_EVENT_FAIL, flat, DUOFORGE_CAUSE_ABILITY, 1u + intimidate_guard, flat);
        dfi_emit(r, &e);
    }
    /* Hyper Cutter (step G39, data/abilities.ts:1940-1954, onTryBoost of the target itself, breakable): an Attack drop that
     * another Pokemon causes is deleted after Contrary and the cap (boost.atk is then set and negative), and the line
     * -fail|holder|unboost|atk|[from] ability: Hyper Cutter|[of] holder shows unless the effect is a move's secondary
     * (effect.secondaries). No forme of the pool with it is a Grass type (tests/interactions/test_hyper_cutter_flower_veil.c), so as a forme it never meets
     * a Flower Veil holder's handler; Skill Swap (step G70) can still give it to a Grass type next to a Flower Veil holder, and
     * that composition is not refused here (decision 0015 entry 5dy, a follow-up). */
    if (source != flat && source != DFI_POSITIONS && boosts[DFI_STAGE_ATK] != DFI_BIAS6 && capped[DFI_STAGE_ATK] < DFI_BIAS6 &&
        dfi_ability(r->b, m, DFI_ABILITY_HYPERCUTTER)) {
        veil[DFI_STAGE_ATK] = true;
        if (!(effect.cause == DUOFORGE_CAUSE_MOVE && effect.mode == DFI_BOOST_SECONDARY)) {
            const duoforge_event e =
                dfi_ev(DUOFORGE_EVENT_FAIL, flat, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_HYPERCUTTER, flat);
            dfi_emit(r, &e); /* the Inner Focus line: it names the stat */
        }
    }
    /* Keen Eye and Big Pecks (step G51, data/abilities.ts:2260-2276 and :445-455, onTryBoost of the target itself, breakable):
     * an accuracy drop, and a Defense drop, that another Pokemon causes is deleted after Contrary and the cap, as Hyper
     * Cutter deletes the Attack drop, with the same line unless the effect is a move's secondary (effect.secondaries). The
     * pin's Keen Eye also ignores the target's evasion for its holder's own moves (onModifyMove, dfi_accuracy_check). No
     * Mold Breaker is marked, so no move or ability ignores either ability.
     * The source test is the pin's `source && target === source` return (data/abilities.ts:2262, 447): a drop that the holder
     * causes itself is let through, which is DFI_POSITIONS (the holder itself, as above) or the holder as its own source; a drop
     * by another Pokemon is blocked. The pin also blocks a drop with no source at all. That case is not representable here and
     * cannot occur for these stats in the pool: the pin's negative Attack, Defense and accuracy boosts without a source are the
     * Max moves (Max Phantasm, data/moves.ts:11350, and its neighbour at :11484), isNonstandard "Past" and not in Champions.
     * Neither holder can meet another TryBoost of the
     * same stat as a forme: a holder has one ability, and Flower Veil reads a Grass type, which no forme with either ability is
     * (tests/abilities/test_keen_eye.c). Skill Swap (step G70) can still give the ability to a Grass type next to a Flower Veil holder; that composition is not refused here (decision 0015 entry 5dy, a follow-up).
     * Illuminate (A2a, decision 0015 entry 5dy; data/abilities.ts:2037-2054) has Keen Eye's two callbacks word for word, its
     * own name in the line aside (tools/datagen gen_closure.py checks both texts), so it is the same branch with its own id.
     * An Illuminate holder that is a Grass type next to a Flower Veil holder (Skill Swap can make one; no pool forme with
     * Illuminate is Grass) has two TryBoost handlers for one accuracy drop, and only the first of them, by Speed (a tie draws),
     * deletes it and prints its line: not modelled, refused (r->deferred, E_UNSUPPORTED), never both lines. */
    if (flower_veiled && veil[DFI_STAGE_ACCURACY] && dfi_ability(r->b, m, DFI_ABILITY_ILLUMINATE)) {
        r->deferred = DUOFORGE_E_UNSUPPORTED;
    }
    const uint32_t accuracy_guard = dfi_ability(r->b, m, DFI_ABILITY_KEENEYE)      ? DFI_ABILITY_KEENEYE
                                    : dfi_ability(r->b, m, DFI_ABILITY_ILLUMINATE) ? DFI_ABILITY_ILLUMINATE
                                                                                   : DFI_POOL_ABILITY_COUNT;
    if (source != flat && source != DFI_POSITIONS && boosts[DFI_STAGE_ACCURACY] != DFI_BIAS6 &&
        capped[DFI_STAGE_ACCURACY] < DFI_BIAS6 && accuracy_guard != DFI_POOL_ABILITY_COUNT) {
        veil[DFI_STAGE_ACCURACY] = true;
        if (!(effect.cause == DUOFORGE_CAUSE_MOVE && effect.mode == DFI_BOOST_SECONDARY)) {
            const duoforge_event e = dfi_ev(DUOFORGE_EVENT_FAIL, flat, DUOFORGE_CAUSE_ABILITY, 1u + accuracy_guard, flat);
            dfi_emit(r, &e); /* the line names the accuracy stat */
        }
    }
    if (source != flat && source != DFI_POSITIONS && boosts[DFI_STAGE_DEF] != DFI_BIAS6 &&
        capped[DFI_STAGE_DEF] < DFI_BIAS6 && dfi_ability(r->b, m, DFI_ABILITY_BIGPECKS)) {
        veil[DFI_STAGE_DEF] = true;
        if (!(effect.cause == DUOFORGE_CAUSE_MOVE && effect.mode == DFI_BOOST_SECONDARY)) {
            const duoforge_event e = dfi_ev(DUOFORGE_EVENT_FAIL, flat, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_BIGPECKS, flat);
            dfi_emit(r, &e); /* the line names the Defense stat */
        }
    }
    /* Clear Body (step G30, data/abilities.ts:523-542, onTryBoost of the target itself): every drop that another Pokemon
     * causes is deleted, and the line shows unless the effect is a move's secondary (effect.secondaries) or Octolock
     * (not in the pool). Like Flower Veil it sees the drop after Contrary and the cap. A Grass type that has Clear Body
     * and stands next to a Flower Veil holder would need the two handlers' order: no forme of the pool is both, and nothing
     * that Trace could copy it onto is Grass (tests/interactions/test_rage_powder_batch_rows.c checks both), but Skill Swap (step G70) can give it to a
     * Grass type; that composition is not refused for Clear Body here (decision 0015 entry 5dy, a follow-up).
     * White Smoke (A2a, decision 0015 entry 5dy; data/abilities.ts:5473-5487) has Clear Body's callback word for word, its own
     * name in the line aside (gen_closure.py checks both texts): the same branch with its own id. Its only pool holder,
     * Torkoal, is no Grass type; a Grass holder made by Skill Swap next to a Flower Veil holder would have two TryBoost
     * handlers for one drop, of which only the first (by Speed, a tie draws) prints: refused (r->deferred), as Illuminate's. */
    if (flower_veiled && dfi_ability(r->b, m, DFI_ABILITY_WHITESMOKE)) {
        r->deferred = DUOFORGE_E_UNSUPPORTED;
    }
    bool clear[DFI_STAT_STAGE_COUNT] = {false, false, false, false, false, false, false};
    const uint32_t drop_guard = dfi_ability(r->b, m, DFI_ABILITY_CLEARBODY)    ? DFI_ABILITY_CLEARBODY
                                : dfi_ability(r->b, m, DFI_ABILITY_WHITESMOKE) ? DFI_ABILITY_WHITESMOKE
                                                                               : DFI_POOL_ABILITY_COUNT;
    if (source != flat && source != DFI_POSITIONS && drop_guard != DFI_POOL_ABILITY_COUNT) {
        bool any = false;
        for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
            clear[i] = boosts[i] != DFI_BIAS6 && capped[i] < DFI_BIAS6;
            any = any || clear[i];
        }
        if (any && !(effect.cause == DUOFORGE_CAUSE_MOVE && effect.mode == DFI_BOOST_SECONDARY)) {
            dfi_clear_body_block(r, flat, drop_guard);
        }
    }
    /* Mirror Armor (step G33, data/abilities.ts:2657-2679, onTryBoost of the target itself): every drop that another
     * Pokemon causes and that is still one after Contrary and the cap (a stat already at -6 has none) is deleted from the
     * boost, one stat at a time in the table's order; while the source stands, `-ability|holder|Mirror Armor` shows and the
     * source takes that drop itself (boost(negativeBoost, source, target, null, true): the holder is its source, the
     * effect is Mirror Armor's own and a secondary, so no [from] and no second -ability line, and a drop that has been
     * bounced is not bounced again). A source that has fainted loses the drop silently. The holder's own stat lines
     * follow for what is left. Breakable (Mold Breaker would ignore it): no forme of the pool that has Mold Breaker is
     * marked. A Flower Veil holder's TryBoost handler would race this one by Speed on a Grass type that has Mirror Armor:
     * no forme of the pool is (tools/datagen/pool_families.js checkG33). Skill Swap (step G70) can still give the ability to a Grass type next to a Flower Veil holder; that composition is not refused here (decision 0015 entry 5dy, a follow-up). */
    bool mirror[DFI_STAT_STAGE_COUNT] = {false, false, false, false, false, false, false};
    if (source != flat && source != DFI_POSITIONS && dfi_ability(r->b, m, DFI_ABILITY_MIRRORARMOR) &&
        !(effect.cause == DUOFORGE_CAUSE_ABILITY && effect.id2 == 1u + DFI_ABILITY_MIRRORARMOR)) {
        for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
            if (boosts[i] == DFI_BIAS6 || veil[i] || clear[i] || capped[i] >= DFI_BIAS6) {
                continue;
            }
            mirror[i] = true;
            if (dfi_at(b, source)->hp != 0u) {
                const duoforge_event ab =
                    dfi_ev(DUOFORGE_EVENT_ABILITY, flat, DUOFORGE_CAUSE_NONE, 1u + DFI_ABILITY_MIRRORARMOR, DUOFORGE_NO_POSITION);
                dfi_emit(r, &ab); /* [-ability] holder|Mirror Armor */
                uint8_t back[DFI_STAT_STAGE_COUNT] = {6u, 6u, 6u, 6u, 6u, 6u, 6u};
                back[i] = capped[i]; /* the capped drop, biased by 6 */
                (void)dfi_boost(r, source, back, flat,
                                dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_MIRRORARMOR, DFI_BOOST_SECONDARY));
            }
        }
    }
    /* Anger Point (step G77): its line is -setboost with [from] ability: Anger Point, which replaces the -ability line of an
     * ability's boost (sim/battle.ts:2050-2053, the 'angerpoint' case), so the boost is announced already. */
    const bool angerpoint = effect.cause == DUOFORGE_CAUSE_ABILITY && effect.id2 == 1u + DFI_ABILITY_ANGERPOINT;
    bool announced = effect.mode == DFI_BOOST_SECONDARY || angerpoint;
    /* The stats of a boost are changed in the order of the move's table in the data (Battle.boost loops over the keys of
     * the object): the stat order, except Shell Smash, whose pinned entry lists Defense and Special Defense first (data/moves.ts
     * 16255-16275); `negatives_first` is that order, two passes by the sign that the entry gives (Contrary reverses the
     * change, not the order). */
    for (uint32_t k = 0u; k < 2u * DFI_STAT_STAGE_COUNT; ++k) {
        const uint32_t i = k % DFI_STAT_STAGE_COUNT;
        const uint32_t pass = k / DFI_STAT_STAGE_COUNT;
        if (effect.negatives_first ? ((boosts[i] < DFI_BIAS6) != (pass == 0u))
            : effect.positives_first ? ((boosts[i] > DFI_BIAS6) != (pass == 0u))
            : pass != 0u) {
            continue;
        }
        if (boosts[i] == DFI_BIAS6 || veil[i] || clear[i] || mirror[i]) {
            continue; /* not part of this boost, or blocked */
        }
        const uint32_t before = pos->stages[i];
        uint8_t one[DFI_STAT_STAGE_COUNT] = {6u, 6u, 6u, 6u, 6u, 6u, 6u};
        one[i] = capped[i];
        dfi_apply_boosts(pos, one);
        const uint32_t after = pos->stages[i];
        if (after > before && dfi_kind_limits_of(r->ctx->data_kind).pool_rules) {
            /* statsRaisedThisTurn (sim/battle.ts:2085): a positive boost that changed a stage (any source). The flag is a POOL tail
             * field: the other kinds keep their tail all zero (invariants.c, dfi_check_tail). */
            dfi_tail_pos *tp = &r->b->tail.sides[flat / 2u].positions[flat % 2u];
            tp->position_flags = (uint8_t)((uint32_t)tp->position_flags | DFI_POSFLAG_STATS_RAISED); /* wide-operands-reviewed */
        }
        if (after < before && dfi_kind_limits_of(r->ctx->data_kind).pool_rules) {
            /* statsLoweredThisTurn (sim/battle.ts:2086): a real drop of a stage, any source (step G88, decision 0046). */
            dfi_tail_pos *tp = &r->b->tail.sides[flat / 2u].positions[flat % 2u];
            tp->position_flags = (uint8_t)((uint32_t)tp->position_flags | DFI_POSFLAG_LOWERED); /* wide-operands-reviewed */
        }
        const uint32_t by = after > before ? after - before : before - after;
        /* -unboost for a fall, and for any change at -6 */
        const bool down = capped[i] < DFI_BIAS6 || after == 0u;
        duoforge_event e = dfi_event_make(down ? DUOFORGE_EVENT_UNBOOST : DUOFORGE_EVENT_BOOST, flat);
        e.detail = (uint8_t)i;  /* < 7 */
        e.amount = (uint8_t)by; /* <= 12 */
        if (by != 0u) {
            changed = true;
            if (effect.cause == DUOFORGE_CAUSE_ABILITY && !announced) {
                const duoforge_event ab =
                    dfi_ev(DUOFORGE_EVENT_ABILITY, flat, DUOFORGE_CAUSE_NONE, effect.id2, DUOFORGE_NO_POSITION);
                dfi_emit(r, &ab); /* [-ability] holder|Name|boost */
                announced = true;
            }
            if (effect.cause == DUOFORGE_CAUSE_ITEM) {
                e.cause = (uint8_t)DUOFORGE_CAUSE_ITEM;
                e.id2 = (uint16_t)effect.id2;
            }
            if (effect.cause == DUOFORGE_CAUSE_MOVE && effect.id2 != 0u) {
                /* A move's boost that names its move ([from] move: X, Belly Drum's -setboost, step G86): id2 is the move id. */
                e.cause = (uint8_t)DUOFORGE_CAUSE_MOVE;
                e.id2 = (uint16_t)effect.id2;
            }
            if (angerpoint) {
                e.cause = (uint8_t)DUOFORGE_CAUSE_ABILITY; /* the -setboost line's [from] ability: Anger Point (step G77) */
                e.id2 = (uint16_t)effect.id2;
            }
            dfi_emit(r, &e);
            if (capped[i] < DFI_BIAS6 && dfi_ability(r->b, m, DFI_ABILITY_COMPETITIVE) && source < DFI_POSITIONS &&
                source / 2u != flat / 2u) {
                static const uint8_t raise[DFI_STAT_STAGE_COUNT] = {6u, 6u, 8u, 6u, 6u, 6u, 6u}; /* SpA +2 */
                dfi_boost(r, flat, raise, flat,
                          dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_COMPETITIVE, DFI_BOOST_SELF));
            }
            /* Defiant (Team C, decision 0009): Competitive's shape with
             * Attack (data/abilities.ts:901-921). */
            if (capped[i] < DFI_BIAS6 && dfi_ability(r->b, m, DFI_ABILITY_DEFIANT) && source < DFI_POSITIONS &&
                source / 2u != flat / 2u) {
                static const uint8_t raise_atk[DFI_STAT_STAGE_COUNT] = {8u, 6u, 6u, 6u, 6u, 6u, 6u}; /* Atk +2 */
                dfi_boost(r, flat, raise_atk, flat,
                          dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_DEFIANT, DFI_BOOST_SELF));
            }
        } else if (effect.cause == DUOFORGE_CAUSE_ABILITY ? effect.mode != DFI_BOOST_PRIMARY
                                                         : effect.mode == DFI_BOOST_PRIMARY) {
            dfi_emit(r, &e); /* a change of 0 */
        }
    }
    return changed;
}

/* Battle.boost with getCappedBoost: each stage moves by the (biased) amount
 * and stops at -6 or +6. */
static void dfi_apply_boosts(dfi_active_slot *pos, const uint8_t *boosts)
{
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        const uint32_t amount = boosts[i];
        uint32_t stage = pos->stages[i];
        if (amount > DFI_BIAS6) {
            stage += amount - DFI_BIAS6;
            if (stage > DFI_BIAS6_MAX) {
                stage = DFI_BIAS6_MAX;
            }
        } else if (amount < DFI_BIAS6) {
            const uint32_t down = DFI_BIAS6 - amount;
            stage = stage > down ? stage - down : 0u;
        }
        pos->stages[i] = (uint8_t)stage; /* <= 12 */
    }
}

/* ---------------------------------------------------------------- targets */


static DFI_ALWAYS_INLINE bool dfi_alive(struct duoforge_battle *b, uint32_t flat)
{
    const dfi_member *m = dfi_at(b, flat);
    return m != NULL && m->hp != 0u;
}

/* getRandomTarget's foe (sim/battle.ts:2509-2521): side.randomFoe, a sample over the active foes that have not fainted
 * (RANDOM_TARGET); in singles the one foe position, with no draw. *out = DFI_POSITIONS when there is none. */
static duoforge_status dfi_random_foe(dfi_run *r, uint32_t side, uint32_t *out)
{
    uint32_t foes[DUOFORGE_ACTIVE_PER_SIDE] = {0};
    uint32_t n = 0u;
    for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
        const uint32_t flat = (1u - side) * 2u + slot;
        if (dfi_alive(r->b, flat)) {
            foes[n] = flat;
            n += 1u;
        }
    }
    *out = DFI_POSITIONS;
    if (n == 0u) {
        return DUOFORGE_OK;
    }
    if (dfi_context_singles(r->ctx)) {
        /* Singles (decision 0083): getRandomTarget returns pokemon.side.foe.active[0] without a draw
         * (sim/battle.ts:2509). */
        *out = foes[0];
        return DUOFORGE_OK;
    }
    uint32_t v = 0u;
    const duoforge_status st = dfi_draw(r->draws, DFI_SITE_RANDOM_TARGET, 0u, n, &v);
    if (st == DUOFORGE_OK) {
        *out = foes[v];
    }
    return st;
}

/* getTarget and getMoveTargets (sim/battle.ts:2437-2523,
 * sim/pokemon.ts:791-862) for the target classes of the turn core. */
static duoforge_status dfi_move_targets(dfi_run *r, uint32_t user, uint32_t cls, uint32_t chosen,
                                        uint32_t targets[DFI_POSITIONS], uint32_t *count, bool smart)
{
    const uint32_t side = user / 2u;
    *count = 0u;
    if (cls == DUOFORGE_TARGET_CLASS_SELF || cls == DUOFORGE_TARGET_CLASS_ALLY_SIDE ||
        cls == DUOFORGE_TARGET_CLASS_ALL) {
        /* getRandomTarget returns the user for self, side and field moves. */
        targets[0] = user;
        *count = 1u;
        return DUOFORGE_OK;
    }
    if (cls == DFI_TARGET_CLASS_FOE_SIDE) {
        /* foeSide (step G37, the four hazards): getMoveTargets takes every foe position, fainted ones too (foes(true),
         * sim/pokemon.ts:796-807), and the side is what the move acts on; the engine needs no Pokemon of it, so the first
         * foe position stands for the side. The foe that the move line names (getRandomTarget draws it at execution, a
         * label only, as for a spread move) is not drawn. */
        targets[0] = (1u - side) * 2u;
        *count = 1u;
        return DUOFORGE_OK;
    }
    if (cls == DFI_TARGET_CLASS_ALLIES) {
        /* allies (step G32, Life Dew): getMoveTargets takes alliesAndSelf(), the standing members of the user's side in
         * slot order (sim/pokemon.ts:818-819, sim/side.ts:390-395); runMove aims the move at its user whatever was chosen
         * (sim/battle-actions.ts:419). */
        for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
            const uint32_t flat = side * 2u + slot;
            if (dfi_alive(r->b, flat)) {
                targets[*count] = flat;
                *count += 1u;
            }
        }
        return DUOFORGE_OK;
    }
    if (cls == DFI_TARGET_CLASS_ALL_ADJACENT) {
        /* allAdjacent (step G28, Earthquake): getMoveTargets takes the adjacent allies first, then the adjacent foes
         * (sim/pokemon.ts:809-817), so the ally that stands is hit before the foes and each target answers for itself. */
        const uint32_t ally = side * 2u + (1u - user % 2u);
        if (dfi_alive(r->b, ally)) {
            targets[*count] = ally;
            *count += 1u;
        }
        for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
            const uint32_t flat = (1u - side) * 2u + slot;
            if (dfi_alive(r->b, flat)) {
                targets[*count] = flat;
                *count += 1u;
            }
        }
        return DUOFORGE_OK;
    }
    if (cls == DUOFORGE_TARGET_CLASS_ALL_ADJACENT_FOES) {
        for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
            const uint32_t flat = (1u - side) * 2u + slot;
            if (dfi_alive(r->b, flat)) {
                targets[*count] = flat;
                *count += 1u;
            }
        }
        return DUOFORGE_OK;
    }
    if (cls == DFI_TARGET_CLASS_RANDOM_NORMAL) {
        uint32_t t = 0u;
        const duoforge_status st = dfi_random_foe(r, side, &t);
        if (st == DUOFORGE_OK && t < DFI_POSITIONS) {
            targets[0] = t;
            *count = 1u;
        }
        return st;
    }
    if (cls == DUOFORGE_TARGET_CLASS_NORMAL || cls == DUOFORGE_TARGET_CLASS_ANY ||
        cls == DUOFORGE_TARGET_CLASS_ADJACENT_FOE) {
        if (chosen >= DFI_POSITIONS) {
            return DUOFORGE_E_INVARIANT;
        }
        if (chosen == user && cls != DUOFORGE_TARGET_CLASS_ADJACENT_FOE) {
            /* getTarget (sim/battle.ts:2459-2462): a move that targets an adjacent ally, any or normal returns null when the
             * chosen location is the user's own position. Ally Switch (step G80) moves the user onto the slot its target was
             * chosen for, so the move finds nothing to hit ([notarget], then -fail). Not on the locked turn of a two-turn move
             * (the twoturnmove volatile, issue 541): its own location is no valid target (validTargetLoc, sim/battle.ts:
             * 2399-2431), so getTarget retargets at random. */
            if (dfi_pos(r->b, user)->charge_turns == 0u) {
                return DUOFORGE_OK;
            }
            uint32_t t = 0u;
            const duoforge_status st = dfi_random_foe(r, side, &t);
            if (st == DUOFORGE_OK && t < DFI_POSITIONS) {
                targets[0] = t;
                *count = 1u;
            }
            return st;
        }
        if (chosen / 2u == side) {
            /* The ally: hit while it stands; a fainted ally is not
             * retargeted (the move fails); an empty slot falls through to a
             * random foe (sim/battle.ts:2461-2486). */
            const dfi_member *ally = dfi_at(r->b, chosen);
            if (ally != NULL && ally->hp != 0u) {
                targets[0] = chosen;
                *count = 1u;
                return DUOFORGE_OK;
            }
            if (ally != NULL && !smart) {
                return DUOFORGE_OK; /* a fainted ally of a move that is not smart: the move fails (sim/pokemon.ts:829-843) */
            }
            /* step G78 (decision 0043): a smart move (Dragon Darts) retargets a fainted ally at random like any fainted target:
             * getTarget's smartTarget branch returns getRandomTarget when the chosen Pokemon is fainted (sim/battle.ts:2451-2454).
             * A fainted ally falls through to the random foe below, with its draw, as an empty slot does. */
        } else if (dfi_alive(r->b, chosen)) {
            targets[0] = chosen;
            *count = 1u;
            return DUOFORGE_OK;
        }
        /* The chosen foe is gone: retarget randomly. */
        uint32_t t = 0u;
        const duoforge_status st = dfi_random_foe(r, side, &t);
        if (st == DUOFORGE_OK && t < DFI_POSITIONS) {
            targets[0] = t;
            *count = 1u;
        }
        return st;
    }
    if (cls == DUOFORGE_TARGET_CLASS_ADJACENT_ALLY) {
        /* The ally while it stands; a fainted ally is not retargeted (the
         * move fails), and an empty slot falls through to getRandomTarget,
         * which finds no standing adjacent ally in doubles (sim/battle.ts:
         * 2461-2508). */
        const uint32_t ally = side * 2u + (1u - user % 2u);
        if (chosen == DUOFORGE_TARGET_NONE && dfi_context_singles(r->ctx)) {
            return DUOFORGE_OK; /* singles (decision 0083): no target is chosen and getRandomTarget is null (sim/battle.ts:2505) */
        }
        if (chosen == user) {
            return DUOFORGE_OK; /* getTarget's null for the user's own location (sim/battle.ts:2459-2462): [notarget] */
        }
        if (chosen != ally) {
            return DUOFORGE_E_INVARIANT; /* the domain offers only the ally */
        }
        if (dfi_alive(r->b, ally)) {
            targets[0] = ally;
            *count = 1u;
        }
        return DUOFORGE_OK;
    }
    return DUOFORGE_E_UNSUPPORTED; /* the other ally, side and field classes come later */
}

/* ---------------------------------------------------------------- damage */

/* runImmunity for the move's type (typeless never is immune). */
static bool dfi_type_immune(const struct duoforge_battle *b, const dfi_member *target, uint32_t move_type)
{
    if (move_type >= DFI_TYPE_COUNT) {
        return false;
    }
    uint32_t types[2];
    dfi_types_of(b, target, types);
    for (uint32_t i = 0u; i < 2u; ++i) {
        const uint32_t t = types[i];
        if (t < DFI_TYPE_COUNT && dfi_closure_type_chart[t][move_type] == DFI_EFFECT_IMMUNE) {
            return true;
        }
    }
    return false;
}

/* runEffectiveness, biased by 6: +1 per super effective, -1 per resisted
 * defending type. Freeze-Dry (step G32, data/moves.ts:6158-6177) answers the Effectiveness event of its move for the Water
 * type with 1: super effective whatever the chart says (singleEvent('Effectiveness'), sim/pokemon.ts runEffectiveness). */
static uint32_t dfi_type_mod(const struct duoforge_battle *b, const dfi_member *target, uint32_t move_type,
                             const dfi_move_data *md)
{
    uint32_t mod = DFI_BIAS6;
    if (move_type >= DFI_TYPE_COUNT) {
        return mod;
    }
    uint32_t types[2];
    dfi_types_of(b, target, types);
    /* Iron Ball (issue 548, data/items.ts:3056-3060): its onEffectiveness returns 0 for every type of a holder that has the
     * Flying type, the other type included, so a Ground move is neutral against a Flying dual type (Corviknight: not super
     * effective through Steel). Not under Gravity; Ingrain and Smack Down are unmarked rows. */
    if (move_type == DFI_TYPE_GROUND && b->tail.gravity_turns == 0u && dfi_holds(b, target, DFI_ITEM_IRONBALL) &&
        (types[0] == DFI_TYPE_FLYING || types[1] == DFI_TYPE_FLYING)) {
        return mod;
    }
    for (uint32_t i = 0u; i < 2u; ++i) {
        const uint32_t t = types[i];
        if (t >= DFI_TYPE_COUNT) {
            continue;
        }
        if (md->special == DFI_SPECIAL_FREEZE_DRY && t == DFI_TYPE_WATER) {
            mod += 1u;
            continue;
        }
        const uint32_t code = dfi_closure_type_chart[t][move_type];
        if (code == DFI_EFFECT_SUPER) {
            mod += 1u;
        } else if (code == DFI_EFFECT_RESISTED) {
            mod -= 1u;
        }
    }
    return mod;
}

static void dfi_use_item(dfi_run *r, uint32_t flat);
static void dfi_use_item_of(dfi_run *r, uint32_t flat, uint32_t other);
static void dfi_use_item_core(dfi_run *r, uint32_t flat, uint32_t other);
static void dfi_symbiosis(dfi_run *r, uint32_t flat);

/* Unnerve (step G32, data/abilities.ts:5258-5275): while a foe's holder stands, `onFoeTryEatItem` returns false, so a Pokemon
 * on the other side cannot eat a berry (eatItem fails: no -enditem, and a resist berry does not weaken the hit; Sitrus
 * Berry waits for the next Update). The holder's own side is not affected. effectState.unnerved is true from the holder's
 * onStart (which runs at its switch-in, ahead of the other entry abilities) to its onEnd (a switch-out or a faint). */
static bool dfi_unnerved(struct duoforge_battle *b, uint32_t flat)
{
    for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
        const dfi_member *foe = dfi_at(b, (1u - flat / 2u) * 2u + slot);
        if (foe != NULL && foe->hp != 0u && dfi_ability(b, foe, DFI_ABILITY_UNNERVE)) {
            return true;
        }
    }
    return false;
}

/* chainModify (sim/battle.ts:2311-2322), as dfi_chain_modify. Two modifiers
 * from 4096 commute; for the three ModifyDamage modifiers (Life Orb 5324,
 * Chople Berry 2048, a screen 2732) every order gives the same value. A new
 * ModifyDamage modifier needs this check extended, or its handler order. */
#define DFI_CHAIN(a, b) ((((a) * (b)) + 2048u) >> 12)
_Static_assert(DFI_CHAIN(DFI_CHAIN(5324u, 2048u), 2732u) == DFI_CHAIN(DFI_CHAIN(5324u, 2732u), 2048u),
               "ModifyDamage modifiers must chain in any order");
_Static_assert(DFI_CHAIN(DFI_CHAIN(5324u, 2048u), 2732u) == DFI_CHAIN(DFI_CHAIN(2048u, 2732u), 5324u),
               "ModifyDamage modifiers must chain in any order");
/* Expert Belt (step G28, 4915 for a super effective hit) takes the place of the attacker's Life Orb in the chain (one item
 * each): the same three modifiers with 4915 chain to the same value in every order. */
_Static_assert(DFI_CHAIN(DFI_CHAIN(4915u, 2048u), 2732u) == DFI_CHAIN(DFI_CHAIN(4915u, 2732u), 2048u),
               "ModifyDamage modifiers must chain in any order");
_Static_assert(DFI_CHAIN(DFI_CHAIN(4915u, 2048u), 2732u) == DFI_CHAIN(DFI_CHAIN(2048u, 2732u), 4915u),
               "ModifyDamage modifiers must chain in any order");

/* Sheer Force (step G61, data/abilities.ts:4202-4221). The pinned onModifyMove deletes a move's secondaries and self effects,
 * and sets hasSheerForce, only when the move has secondaries and is not hasSheerForceBoost. The engine's rows of such a move
 * are the secondary columns: sec_chance != 0, or the special of Stone Axe and Ceaseless Edge (their empty `secondary: {}`),
 * Ice Fang and Tri Attack (their secondaries run in their own code). The generator checks this against the pin for every
 * pool move (pool_families.js checkG61). dfi_sf_strips is that flag (the holder's current ability, so a Mega forme and a Trace
 * copy count); dfi_sf_boosts adds Electro Shot (hasSheerForceBoost, x5325/4096 only). A move that is not stripped keeps its
 * self effects (Close Combat, Overheat, the recharge moves): the pin strips nothing else. */
static bool dfi_sf_strips(const struct duoforge_battle *b, const dfi_member *a, const dfi_move_data *md)
{
    return dfi_sf_strips_move(dfi_ability(b, a, DFI_ABILITY_SHEERFORCE), md);
}

static bool dfi_sf_boosts(const struct duoforge_battle *b, const dfi_member *a, const dfi_move_data *md)
{
    return dfi_sf_boosts_move(dfi_ability(b, a, DFI_ABILITY_SHEERFORCE), md);
}

/* getDamage and the Champions modifyDamage (sim/battle-actions.ts:1585-1720,
 * data/mods/champions/scripts.ts:196-312) for a turn-core move: CRIT and
 * DAMAGE_ROLL draws in that order. */
/* A Pokemon faints now, queued as faint() queues it (sim/pokemon.ts:1581-1590): its HP is 0, it is the next faint of the
 * queue, with no source and no effect (by_move false). A switch-less build cannot queue a faint (dfi_damage's refusal). */
static duoforge_status dfi_queue_self_faint(dfi_run *r, uint32_t flat)
{
    dfi_member *m = dfi_at(r->b, flat);
    if (m == NULL || m->hp == 0u) {
        return DUOFORGE_OK;
    }
    if (dfi_support.switching == 0u) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    if (r->faint_count < DFI_POSITIONS) {
        m->hp = 0u;
        r->faint_queue[r->faint_count] = flat;
        r->faint_count += 1u;
        r->last_faint_by = DFI_POSITIONS;
        r->last_faint_move = false;
    }
    return DUOFORGE_OK;
}

/* The level of a Champions Pokemon: every one is level 50 (DFI_LEVEL), so a level difference is always 0. */
static uint32_t dfi_level_of(const dfi_member *m)
{
    (void)m;
    return DFI_LEVEL;
}



#include "combat/mechanics/damage/crit.h"
#include "combat/mechanics/damage/stats.h"
#include "combat/mechanics/damage/base_power.h"
#include "combat/mechanics/damage/attack.h"
#include "combat/mechanics/damage/base_damage.h"
#include "combat/mechanics/damage/modify_damage.h"

static duoforge_status dfi_get_damage(dfi_run *r, uint32_t user, uint32_t target, const dfi_move_data *md,
                                      uint32_t move_type, bool spread, uint32_t *out, bool *crit_out)
{
    const dfi_member *a = dfi_at(r->b, user);
    const dfi_member *d = dfi_at(r->b, target);
    /* The critical hit of this hit (the caller's Anger Point test, step G77): false unless the roll below made it one; a move
     * that has no roll (Final Gambit, Super Fang, Sheer Cold) and a target that is not hit never reads true. */
    *crit_out = false;
    /* Final Gambit's damageCallback (step G76, data/moves.ts:5301-5320): getDamage takes the user's current HP and then faints
     * the user (pokemon.faint() in the callback, before the damage is dealt), so the user's faint is queued here, and selfdestruct
     * 'ifHit' faints it again as a no-op. There is no critical hit roll and no formula; the type immunity, Protect and the
     * accuracy were judged before. */
    if (md->special == DFI_SPECIAL_FINAL_GAMBIT) {
        *out = (uint32_t)a->hp;
        return dfi_queue_self_faint(r, user);
    }
    /* Super Fang's damageCallback (step G39, data/moves.ts:18461-18476): getDamage returns clampIntRange(target.hp / 2, 1)
     * before the critical hit roll and the formula (sim/battle-actions.ts:1585-1600), so there is no CRIT or DAMAGE_ROLL
     * draw, no modifier of the damage chain (Multiscale, Friend Guard, the screens, the berries and the items are in
     * modifyDamage) and none of its effectiveness lines; the type immunity (Ghost) was judged before, in the hit steps. */
    if (md->special == DFI_SPECIAL_SUPER_FANG) {
        const uint32_t half = (uint32_t)d->hp / 2u;
        *out = half < 1u ? 1u : half;
        return DUOFORGE_OK;
    }
    /* Endeavor's damageCallback (step C5, data/moves.ts:4784-4804): getDamage returns target.getUndynamaxedHP() - pokemon.hp
     * before the critical hit roll and the formula. Its onTryImmunity (the user's HP below the target's) was judged in
     * hitStepTryImmunity, so the difference is at least 1; the type immunity was judged before too. */
    if (md->special == DFI_SPECIAL_ENDEAVOR) {
        if (d->hp <= a->hp) {
            return DUOFORGE_E_INVARIANT;
        }
        *out = (uint32_t)d->hp - (uint32_t)a->hp;
        return DUOFORGE_OK;
    }
    /* An OHKO move (Sheer Cold, step G64; Fissure, Guillotine and Horn Drill, step G92): getDamage returns target.maxhp
     * (sim/battle-actions.ts:1606) before the critical hit roll, the formula and every effectiveness line; the type and
     * Sturdy immunities were judged before. */
    if (dfi_is_ohko(md)) {
        *out = (uint32_t)d->hp_max;
        return DUOFORGE_OK;
    }
    /* Night Shade (step G92, data/moves.ts:12725-12738: damage 'level'): getDamage returns source.level (sim/battle-actions.ts:
     * 1608-1609) before the critical hit ratio and the formula, so there is no CRIT draw and no modifier; the immunities were
     * judged before. The user is at level DFI_LEVEL. */
    if (md->special == DFI_SPECIAL_LEVEL_DAMAGE) {
        *out = dfi_level_of(a);
        return DUOFORGE_OK;
    }
    const dfi_active_slot *ap = dfi_pos(r->b, user);
    const dfi_active_slot *dp = dfi_pos(r->b, target);
    dfi_damage_ctx ctx = {a, d, ap, dp, spread, false, false, false, 0u, 0u, 0u, 0u, 0u, 0u};
    duoforge_status st = dfi_damage_crit(r, user, target, md, move_type, &ctx);
    if (st != DUOFORGE_OK) {
        return st;
    }
    st = dfi_damage_stats(r, user, target, md, move_type, &ctx);
    if (st != DUOFORGE_OK) {
        return st;
    }
    st = dfi_damage_base_power(r, user, target, md, move_type, &ctx);
    if (st != DUOFORGE_OK) {
        return st;
    }
    st = dfi_damage_attack(r, user, target, md, move_type, &ctx);
    if (st != DUOFORGE_OK) {
        return st;
    }
    st = dfi_damage_base(r, user, target, md, move_type, &ctx);
    if (st != DUOFORGE_OK) {
        return st;
    }
    st = dfi_damage_modify(r, user, target, md, move_type, &ctx);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const uint32_t damage = ctx.damage;
    const bool crit = ctx.crit;
    *out = dfi_final_damage(damage);
    *crit_out = crit; /* the roll's result after the Shell Armor test: the critical hit the holder's Anger Point reads (step G77) */
    return DUOFORGE_OK;
}

/* The class of a damage that dfi_deal applies (step G67, Magic Guard, decision 0015 entry 5bl). Every caller names one, with no
 * default; Magic Guard (data/abilities.ts:2465-2476) blocks a damage whose Showdown effect is not a Move, and a directDamage
 * never reaches its Damage event (sim/battle.ts:2093-2140 runs the event; sim/pokemon.ts:1595 does not). Silent: no line.
 * UNCLASSIFIED is refused for a Magic Guard holder (E_UNSUPPORTED), never guessed. */
typedef enum dfi_dmg_class {
    DFI_DMG_UNCLASSIFIED = 0, /* refused for a Magic Guard holder */
    DFI_DMG_DIRECT,           /* directDamage, no Damage event: Substitute and Clangorous Soul costs, Struggle's recoil */
    DFI_DMG_MOVE,             /* effect Move: a move's hit, confusion's self-hit (conditions.ts:184-190) */
    DFI_DMG_SIDE,             /* side condition: Stealth Rock (moves.ts:17814), Spikes (:17500) */
    DFI_DMG_WEATHER,          /* sandstorm's chip (conditions.ts:628-660) */
    DFI_DMG_STATUS,           /* burn, poison, toxic residual (conditions.ts:2, 123, 138) */
    DFI_DMG_CONDITION,        /* a move's condition: Spiky Shield's contact damage (moves.ts:17562-17568) */
    DFI_DMG_RECOIL,           /* a move's recoil, effect 'recoil' (battle-actions.ts:1391-1392) */
    DFI_DMG_ITEM,             /* an item: Life Orb (items.ts:3413-3416), Rocky Helmet (items.ts:5295) */
    DFI_DMG_ABILITY           /* an ability: Rough Skin (abilities.ts:3938), Solar Power (:4396). Blocked with
                               * -activate|source|ability: name, the source being the ability's holder (`other`). */
} dfi_dmg_class;

/* The one Magic Guard predicate (step G67, data/abilities.ts:2465-2476): a holder takes no damage of a class that Showdown's
 * Damage event blocks (every class but DIRECT and MOVE). dfi_deal skips such a damage, and the order of a weather tie counts
 * only the Pokemon that take the damage: a Magic Guard holder has no order to show (decision 0015 entry 5bl). */
static bool dfi_magic_guard_blocks(const struct duoforge_battle *b, const dfi_member *m, dfi_dmg_class cls)
{
    return dfi_ability(b, m, DFI_ABILITY_MAGICGUARD) && cls != DFI_DMG_DIRECT && cls != DFI_DMG_MOVE;
}

/* Pokemon.damage: HP never below 0; reaching 0 queues the faint. The class (above) is required; a Magic Guard holder takes
 * a DIRECT or MOVE damage and no other, and an UNCLASSIFIED one is refused. An ability's damage blocked by Magic Guard prints
 * -activate with the ability's holder (`other`) as the position, cause ABILITY and id2 the ability, as Showdown's handler does. */
static duoforge_status dfi_deal(dfi_run *r, uint32_t flat, uint32_t amount, uint32_t cause, uint32_t id2,
                                uint32_t other, dfi_dmg_class cls)
{
    dfi_member *m = dfi_at(r->b, flat);
    const uint32_t hp = m->hp;
    if (hp == 0u) {
        return DUOFORGE_OK;
    }
    if (dfi_magic_guard_blocks(r->b, m, cls)) {
        if (cls == DFI_DMG_UNCLASSIFIED) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        if (cls == DFI_DMG_ABILITY) {
            const duoforge_event act = dfi_ev(DUOFORGE_EVENT_ACTIVATE, other, DUOFORGE_CAUSE_ABILITY, id2, DUOFORGE_NO_POSITION);
            dfi_emit(r, &act);
        }
        return DUOFORGE_OK;
    }
    m->hp = (uint16_t)(hp > amount ? hp - amount : 0u); /* wide-operands-reviewed: <= hp */
    if (amount != 0u) {
        dfi_emit_hp(r, dfi_ev(DUOFORGE_EVENT_DAMAGE, flat, cause, id2, other)); /* [-damage] */
        /* Step G88 (sim/battle.ts:2137-2138): every damage but the directDamage class (cost, Struggle's recoil) sets HURT. */
        if (cls != DFI_DMG_DIRECT && m->hp != 0u && dfi_kind_limits_of(r->ctx->data_kind).pool_rules) {
            dfi_tail_pos *tp = &r->b->tail.sides[flat / 2u].positions[flat % 2u];
            tp->position_flags = (uint8_t)((uint32_t)tp->position_flags | DFI_POSFLAG_HURT); /* wide-operands-reviewed */
        }
    }
    if (m->hp == 0u) {
        if (dfi_support.switching == 0u) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        if (r->faint_count < DFI_POSITIONS) {
            r->faint_queue[r->faint_count] = flat;
            r->faint_count += 1u;
            r->last_faint_by = DFI_POSITIONS; /* not a move's damage unless the caller says so (dfi_run_move's hit loop) */
            r->last_faint_move = false;
        }
    }
    return DUOFORGE_OK;
}

/* runStatusImmunity('psn') (Team C; Toxic asks for 'psn' too, sim/pokemon.ts:1713): a type whose chart entry carries the
 * psn key, Poison and Steel (data/typechart.ts). Corrosion skips the test for its holder's poisons (dfi_try_status). */
static bool dfi_poison_immune(const struct duoforge_battle *b, const dfi_member *m)
{
    for (uint32_t type = 0u; type < DFI_TYPE_COUNT; ++type) {
        if ((dfi_pool_type_immunity[type] & DFI_IMMUNE_PSN) != 0u && dfi_has_type(b, m, type)) {
            return true;
        }
    }
    return false;
}

/* The source of a status without a move to name (Dire Claw's pick calls
 * trySetStatus without one): its sleep line has no [from]. */
#define DFI_NO_SOURCE_MOVE UINT32_MAX

/* trySetStatus and setStatus (sim/pokemon.ts): only a standing Pokemon
 * without a status takes one; Fire cannot be burned, Electric cannot be
 * paralyzed, Ice and anything under sun cannot be frozen, Poison and Steel
 * cannot be poisoned (Team C). Sleep lasts sample([2, 3, 3]) attempts,
 * freeze at most 3 (the Champions conditions,
 * data/mods/champions/conditions.ts). */
/* The origin of a status (dfi_try_status), which says what the effect that sets it is to the handlers of the status:
 * OTHER is a secondary, an ability or a pick (Poison Touch, Flame Body, Static, Dire Claw's pick); MOVE is a move's own
 * status (effect.status and no secondaries); SYNC is Synchronize's trySetStatus, whose effect is `{status, id:
 * 'synchronize'}` (data/abilities.ts:4857-4871): the immunity and fail lines read it as a move's status (effect.status),
 * but it has no name and no effectType, so Flower Veil's -block (data/abilities.ts:1438) stays silent for it and its start
 * line has no [from]; HAZARD is Toxic Spikes, which Synchronize does not pass on (effect.id 'toxicspikes'). */
#define DFI_ORIGIN_OTHER 0u
#define DFI_ORIGIN_MOVE 1u
#define DFI_ORIGIN_SYNC 2u
#define DFI_ORIGIN_HAZARD 3u
/* the Yawn residual (step G31 fix): a sleep that Yawn's end sets. Every reader of the origin treats it as OTHER, except
 * the terrains' sleep refusal below, which shows its line for a Yawn (data/moves.ts:4518, 12172: effect.id 'yawn'). */
#define DFI_ORIGIN_YAWN 4u

static duoforge_status dfi_try_status(dfi_run *r, uint32_t flat, uint32_t status, uint32_t user, uint32_t move_id,
                                      uint32_t origin, uint32_t from_ability);
static duoforge_status dfi_after_set_status(dfi_run *r, uint32_t flat, uint32_t status, uint32_t source, uint32_t origin);

/* Leaf Guard's test (step G83, data/abilities.ts:2291-2310, which read Pokemon#effectiveWeather, sim/pokemon.ts:2190-2212): sun
 * is up. The weather it reads is the field's (dfi_field_weather, step G79: a standing Cloud Nine holder suppresses it, so
 * Leaf Guard does not block). Utility Umbrella is not marked (support_manifest.c), so its branch of Pokemon#effectiveWeather
 * (sim/pokemon.ts:2199-2205) is never reached. A Mega Sol holder standing on the field reads as sun for the effects of its own
 * moves, whatever the holder's own ability: Mega Meganium's base learnset has Toxic and Poison Powder, so its
 * Toxic on a Leaf Guard foe outside sun is refused by Leaf Guard in the pin. The field does not show that, so while such a holder
 * stands and the field is not sun the test is not modelled: E_UNSUPPORTED (a white-box test pins it), never a guess. */
static duoforge_status dfi_leaf_guard_sun(const dfi_run *r, bool *sun)
{
    *sun = dfi_field_weather(r) == DFI_WEATHER_SUN;
    if (*sun) {
        return DUOFORGE_OK;
    }
    for (uint32_t p = 0u; p < DFI_POSITIONS; ++p) {
        const dfi_member *mm = dfi_at(r->b, p);
        if (mm != NULL && mm->hp != 0u && dfi_ability(r->b, mm, DFI_ABILITY_MEGASOL)) {
            return DUOFORGE_E_UNSUPPORTED;
        }
    }
    return DUOFORGE_OK;
}

static duoforge_status dfi_try_status(dfi_run *r, uint32_t flat, uint32_t status, uint32_t user, uint32_t move_id,
                                      uint32_t origin, uint32_t from_ability)
{
    static const uint8_t sleep_turns[3] = {2u, 3u, 3u};
    /* the messages that read a move's own status (effect.status): a move's and Synchronize's; the Flower Veil block below is
     * the move's alone */
    const bool primary = origin == DFI_ORIGIN_MOVE || origin == DFI_ORIGIN_SYNC;
    dfi_member *m = dfi_at(r->b, flat);
    if (m == NULL || m->hp == 0u) {
        return DUOFORGE_OK;
    }
    /* Only a move's own status shows why it failed: the same status on
     * the target (-fail|target|status), another one fails the user's move
     * (-fail, [still]), an immunity shows -immune. */
    if (m->status != DFI_STATUS_NONE) {
        if (primary && m->status == status) {
            duoforge_event e = dfi_event_make(DUOFORGE_EVENT_FAIL, flat);
            e.detail = m->status;
            dfi_emit(r, &e);
        } else if (primary) {
            dfi_fail_still(r, user);
        }
        return DUOFORGE_OK;
    }
    /* Corrosion (A2a, decision 0015 entry 5dy; data/abilities.ts:691-697 has no callback, the rule is setStatus's,
     * sim/pokemon.ts:1709-1711): when the source has Corrosion, psn and tox skip runStatusImmunity, so a Poison or Steel
     * type is poisoned. The source is setStatus's `source` (the caller's `user`: the attacker, the Synchronize holder that
     * passes a status back, a contact ability's holder); hasAbility reads the ability while the source is active, which it
     * is from its own move to its faint's processing, the span of every caller here. Toxic Spikes' source (foe.active[0])
     * never meets it: the hazard skips a Poison type (it absorbs) and a Steel type before trySetStatus
     * (data/moves.ts:19772-19776, dfi_entry_hazards). */
    const bool corrosion = (status == DFI_STATUS_PSN || status == DFI_STATUS_TOX) && user < DFI_POSITIONS &&
                           dfi_ability(r->b, dfi_at(r->b, user), DFI_ABILITY_CORROSION);
    if ((status == DFI_STATUS_BRN && dfi_has_type(r->b, m, DFI_TYPE_FIRE)) ||
        (status == DFI_STATUS_PAR && dfi_has_type(r->b, m, DFI_TYPE_ELECTRIC)) ||
        (status == DFI_STATUS_FRZ && (dfi_has_type(r->b, m, DFI_TYPE_ICE) || dfi_field_weather(r) == DFI_WEATHER_SUN)) ||
        ((status == DFI_STATUS_PSN || status == DFI_STATUS_TOX) && !corrosion && dfi_poison_immune(r->b, m))) {
        if (primary) {
            dfi_immune(r, flat, 0u);
        }
        return DUOFORGE_OK;
    }
    /* Magma Armor (step G77, data/abilities.ts:2501-2515, onImmunity 'frz' returns false, breakable; no Champions entry): every
     * freeze of its holder is refused in the Immunity event, after the natural immunities above and before SetStatus (so before
     * Flower Veil's block and the terrains). The -immune line is the plain one (runStatusImmunity, then setStatus's
     * `(sourceEffect as Move)?.status` test, sim/pokemon.ts:1713-1718): a move's own status shows it, a secondary or a pick is
     * silent. No [from] ability, the line of a natural immunity. Mold Breaker is not marked, so breakable is not reached. */
    if (status == DFI_STATUS_FRZ && dfi_ability(r->b, m, DFI_ABILITY_MAGMAARMOR)) {
        if (primary) {
            dfi_immune(r, flat, 0u);
        }
        return DUOFORGE_OK;
    }
    /* SetStatus (sim/pokemon.ts:1724, after the immunities): Flower Veil blocks a status that another Pokemon's move
     * causes on a Grass type of its side (data/abilities.ts:1438-1448); the line shows for a move's own status
     * (effect.secondaries is unset) and not for a secondary (Dire Claw's pick, Flare Blitz's burn).
     * Thermal Exchange (data/abilities.ts:4990-5018, onSetStatus) refuses every burn of its holder: the -immune line
     * shows for a move's own status (effect.status) and not for a secondary or an item. The two handlers of one
     * SetStatus event run in speed order and the first refusal ends the event: with a Flower Veil holder in play for
     * the same Grass-type target the order is not modelled (E_UNSUPPORTED, never a guess). */
    uint32_t holder = 0u;
    if (status == DFI_STATUS_BRN && dfi_ability(r->b, m, DFI_ABILITY_THERMALEXCHANGE)) {
        if (user != flat && dfi_flower_veil_holder(r->b, flat, &holder)) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        if (primary) {
            dfi_immune(r, flat, 1u + DFI_ABILITY_THERMALEXCHANGE); /* [-immune] [from] ability: Thermal Exchange */
        }
        return DUOFORGE_OK;
    }
    /* Water Bubble (step G65, data/abilities.ts:5406-5416, onSetStatus, breakable): every burn of its holder is refused, with the
     * -immune line for a move's own status (effect.status, `primary`) and silently for a secondary, an item or an ability. It is
     * Thermal Exchange's shape: the same Flower Veil order question (E_UNSUPPORTED with a Flower Veil holder on the field for a
     * target that is not the user), and the holder's one ability, so it never meets Thermal Exchange. Its onUpdate, the cure of a
     * burn, can only act for a burned holder that gained the ability (Trace): dfi_trace refuses that. */
    if (status == DFI_STATUS_BRN && dfi_ability(r->b, m, DFI_ABILITY_WATERBUBBLE)) {
        if (user != flat && dfi_flower_veil_holder(r->b, flat, &holder)) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        if (primary) {
            dfi_immune(r, flat, 1u + DFI_ABILITY_WATERBUBBLE); /* [-immune] [from] ability: Water Bubble */
        }
        return DUOFORGE_OK;
    }
    /* Limber (step G39, data/abilities.ts:2368-2386, onSetStatus, breakable): every paralysis of its holder is refused, with
     * the -immune line for a move's own status (effect.status) and silently for a secondary or an ability (Static's); the
     * same order question with a Flower Veil holder as above. Its onUpdate, which cures a paralysis that the holder somehow
     * has, can only act for a holder that copied the ability onto a paralysed Pokemon (Trace): dfi_trace refuses that. */
    if (status == DFI_STATUS_PAR && dfi_ability(r->b, m, DFI_ABILITY_LIMBER)) {
        if (user != flat && dfi_flower_veil_holder(r->b, flat, &holder)) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        if (primary) {
            dfi_immune(r, flat, 1u + DFI_ABILITY_LIMBER); /* [-immune] [from] ability: Limber */
        }
        return DUOFORGE_OK;
    }
    /* Purifying Salt (A2a, decision 0015 entry 5dy; data/abilities.ts:3618-3650, onSetStatus, breakable, no Champions entry):
     * every status of its holder is refused, Limber's shape for all six, with the -immune line for a move's own status
     * (effect.status, `primary`) and silently otherwise; the same Flower Veil order refusal. It has no onUpdate, so a
     * statused Pokemon that gains it (Trace, Skill Swap) keeps its status, as in the pin. Its Yawn refusal is in dfi_yawn and
     * its Ghost halving in the attack chain (combat/mechanics/damage/attack.h). */
    if (dfi_ability(r->b, m, DFI_ABILITY_PURIFYINGSALT)) {
        if (user != flat && dfi_flower_veil_holder(r->b, flat, &holder)) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        if (primary) {
            dfi_immune(r, flat, 1u + DFI_ABILITY_PURIFYINGSALT); /* [-immune] [from] ability: Purifying Salt */
        }
        return DUOFORGE_OK;
    }
    if (user != flat && dfi_flower_veil_holder(r->b, flat, &holder)) {
        /* the block line: effect.effectType 'Move' without secondaries, or the name Synchronize, which the effect of Synchronize
         * does not have (data/abilities.ts:1438): a move's own status alone shows it */
        if (origin == DFI_ORIGIN_MOVE) {
            dfi_flower_veil_block(r, flat, holder);
        }
        return DUOFORGE_OK;
    }
    /* Leaf Guard (step G83, data/abilities.ts:2291-2310, onSetStatus, breakable): in sun every status of its holder is refused,
     * with the -immune line for a move's own status (effect.status, `primary`) and silently for a secondary or the Yawn residual
     * (its effect is the condition, which has no status). A Pokemon's effect, so it comes before the terrains' (below). With a
     * Flower Veil holder in play for the same Grass-type target the order of the two handlers is not modelled (E_UNSUPPORTED,
     * as Thermal Exchange's). */
    if (dfi_ability(r->b, m, DFI_ABILITY_LEAFGUARD)) {
        bool sun = false;
        const duoforge_status lg = dfi_leaf_guard_sun(r, &sun);
        if (lg != DUOFORGE_OK) {
            return lg;
        }
        if (sun) {
            if (user != flat && dfi_flower_veil_holder(r->b, flat, &holder)) {
                return DUOFORGE_E_UNSUPPORTED;
            }
            if (primary) {
                dfi_immune(r, flat, 1u + DFI_ABILITY_LEAFGUARD); /* [-immune] [from] ability: Leaf Guard */
            }
            return DUOFORGE_OK;
        }
    }
    /* The terrains' onSetStatus (step G25, data/moves.ts:4497-4551 and 12151-12205). The field's handlers have no
     * speed (Battle.resolvePriority gives a speed to a Pokemon's effects only, sim/battle.ts:1001-1003), so they run after
     * every handler of an ability above (the speed of a Pokemon is positive): a refusal by Thermal Exchange or Flower
     * Veil comes first and ends the event. Electric Terrain refuses sleep for a grounded Pokemon, Misty Terrain every
     * status; both return false, and show `-activate|target|move: X Terrain` only for a move's own status (Electric:
     * `effect.effectType === 'Move' && !effect.secondaries`; Misty: `effect.status`, which a secondary's move does not
     * have), and nothing for a secondary or an ability (Poison Touch) or an item. A flying Pokemon is not grounded. */
    /* The semi-invulnerable exemption (data/moves.ts:4517 for sleep, :12178 for every status): a charging target is not blocked. */
    if ((r->b->terrain == DFI_TERRAIN_MISTY || (r->b->terrain == DFI_TERRAIN_ELECTRIC && status == DFI_STATUS_SLP)) &&
        dfi_grounded(r->b, m) && !dfi_semi_invulnerable(r, flat)) {
        /* a Yawn's sleep shows the line too (effect.id 'yawn' in both terrains' onSetStatus, data/moves.ts:4518 and
         * 12172; the Yawn residual of step G31 fix passes DFI_ORIGIN_YAWN) */
        if (primary || origin == DFI_ORIGIN_YAWN) {
            const uint32_t terrain_move =
                r->b->terrain == DFI_TERRAIN_MISTY ? DFI_MOVE_MISTYTERRAIN : DFI_MOVE_ELECTRICTERRAIN;
            const duoforge_event e =
                dfi_ev(DUOFORGE_EVENT_ACTIVATE, flat, DUOFORGE_CAUSE_MOVE, terrain_move, DUOFORGE_NO_POSITION);
            dfi_emit(r, &e);
        }
        return DUOFORGE_OK;
    }
    uint32_t counter = 0u;
    if (status == DFI_STATUS_SLP) {
        uint32_t v = 0u;
        const duoforge_status st = dfi_draw(r->draws, DFI_SITE_SLEEP_TURNS, 0u, 3u, &v);
        if (st != DUOFORGE_OK) {
            return st;
        }
        counter = sleep_turns[v];
    } else if (status == DFI_STATUS_FRZ) {
        counter = DFI_FREEZE_TURNS;
    }
    m->status = (uint8_t)status;          /* <= DFI_STATUS_TOX */
    m->status_counter = (uint8_t)counter; /* <= 3 */
    if (status == DFI_STATUS_SLP) {
        /* decision 0066: the cant lines of this sleep start at 0 (the member's byte of the tail, POOL only) */
        r->b->tail.sides[flat / 2u].sleep_cant[dfi_pos(r->b, flat)->occupant] = 0u;
    }
    if (status == DFI_STATUS_TOX) {
        /* tox's onStart sets the stage to 0 (data/conditions.ts:141-150): a toxic status cured by Lum Berry and set again
         * starts from 0 */
        r->b->tail.sides[flat / 2u].toxic_stage[dfi_pos(r->b, flat)->occupant] = 0u;
    }
    /* [-status]; sleep says [from] move when a move is its source
     * (data/mods/champions/conditions.ts:13-20) */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_STATUS, flat);
    e.detail = m->status;
    if (from_ability != 0u) {
        /* psn's onStart names an ability that set it (data/conditions.ts psn): [-status] psn [from] ability: X [of]
         * the source (Poison Touch, POOL data) */
        e.cause = (uint8_t)DUOFORGE_CAUSE_ABILITY;
        e.id2 = (uint16_t)from_ability;
        e.other = (uint8_t)user;
    }
    if (status == DFI_STATUS_SLP && move_id != DFI_NO_SOURCE_MOVE) {
        e.cause = (uint8_t)DUOFORGE_CAUSE_MOVE;
        e.id2 = (uint16_t)move_id;
    }
    dfi_emit(r, &e);
    return dfi_after_set_status(r, flat, status, user, origin);
}

static void dfi_use_item(dfi_run *r, uint32_t flat);
static void dfi_volatile_end(dfi_run *r, uint32_t flat, uint32_t which);

/* Synchronize (step G47, data/abilities.ts:4857-4871, onAfterSetStatus, priority 0): a psn, tox, brn or par that another
 * Pokemon gave the holder is passed back to it. The line -activate|holder|ability: Synchronize comes first, then
 * source.trySetStatus(status, holder, the Synchronize effect): the source's own rules apply (its status, its immunities,
 * its SetStatus handlers), through dfi_try_status with the SYNC origin. The source's own Synchronize, if it has one, answers
 * in turn: the holder already has the status, so the holder's trySetStatus fails with -fail|holder|status (a move's fail line).
 * Not for slp or frz (the caller), not from Toxic Spikes, not when the source is the holder itself (the caller). */
static duoforge_status dfi_synchronize(dfi_run *r, uint32_t holder, uint32_t status, uint32_t source)
{
    const duoforge_event e = dfi_ev(DUOFORGE_EVENT_ACTIVATE, holder, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_SYNCHRONIZE,
                                    DUOFORGE_NO_POSITION);
    dfi_emit(r, &e); /* [-activate] ability: Synchronize */
    return dfi_try_status(r, source, status, holder, DFI_NO_SOURCE_MOVE, DFI_ORIGIN_SYNC, 0u);
}

/* Lum Berry (step G47, data/items.ts:3537-3560): eatItem, which a foe's Unnerve refuses (onFoeTryEatItem, TryEatItem). The
 * berry is eaten (-enditem|X|Lum Berry|[eat], a berry's flag), then onEat cures the holder's status (-curestatus with [msg])
 * and removes its confusion (-end|X|confusion). Its AfterSetStatus (priority -1) and its Update call this. */
static duoforge_status dfi_lum_cure(dfi_run *r, uint32_t flat);

static duoforge_status dfi_lum_berry(dfi_run *r, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    dfi_member *m = dfi_at(b, flat);
    if (m == NULL || m->hp == 0u || !dfi_holds(b, m, DFI_ITEM_LUMBERRY) || dfi_unnerved(b, flat)) {
        return DUOFORGE_OK;
    }
    dfi_use_item_core(r, flat, DUOFORGE_NO_POSITION);
    const duoforge_status cured = dfi_lum_cure(r, flat);
    if (cured == DUOFORGE_OK) {
        dfi_symbiosis(r, flat); /* eatItem: Eat (the cure), then AfterUseItem (step G69) */
    }
    return cured;
}

/* Lum Berry's onEat for the Pokemon at `flat`, which has eaten it (step G64: also a Bug Bite user, which holds no berry): cureStatus
 * (-curestatus with [msg]) and removeVolatile('confusion') (-end). No Unnerve test: that is TryEatItem's, and only the holder's
 * own eating asks it. */
static duoforge_status dfi_lum_cure(dfi_run *r, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    dfi_member *m = dfi_at(b, flat);
    if (m->status != DFI_STATUS_NONE) {
        duoforge_event cure = dfi_event_make(DUOFORGE_EVENT_CURE_STATUS, flat);
        cure.detail = m->status;
        cure.flags = (uint8_t)DUOFORGE_EVENT_FLAG_MESSAGE;
        dfi_emit(r, &cure); /* [-curestatus] [msg] */
        if (m->status == DFI_STATUS_TOX) {
            /* the toxic stage belongs to a tox status (state invariant): cureStatus ends the status and its counter with it */
            b->tail.sides[flat / 2u].toxic_stage[dfi_pos(b, flat)->occupant] = 0u;
        }
        m->status = (uint8_t)DFI_STATUS_NONE;
        m->status_counter = 0u;
        b->tail.sides[flat / 2u].sleep_cant[dfi_pos(b, flat)->occupant] = 0u; /* decision 0066 */
    }
    dfi_active_slot *pos = dfi_pos(b, flat);
    if (pos->confusion_turns != 0u) {
        pos->confusion_turns = 0u;
        dfi_emit_plain(r, DUOFORGE_EVENT_CONFUSION_END, flat); /* [-end] confusion */
    }
    return DUOFORGE_OK;
}

/* sim/pokemon.ts:1746: AfterSetStatus of a status that has just taken. The holder's handlers in priority order: Synchronize
 * (0) and then Lum Berry (-1). The Synchronize step needs the status to be passed on from another Pokemon. */
static duoforge_status dfi_after_set_status(dfi_run *r, uint32_t flat, uint32_t status, uint32_t source, uint32_t origin)
{
    const dfi_member *m = dfi_at(r->b, flat);
    if (m != NULL && origin != DFI_ORIGIN_HAZARD && source != flat &&
        (status == DFI_STATUS_PSN || status == DFI_STATUS_TOX || status == DFI_STATUS_BRN || status == DFI_STATUS_PAR) &&
        dfi_ability(r->b, m, DFI_ABILITY_SYNCHRONIZE)) {
        const duoforge_status st = dfi_synchronize(r, flat, status, source);
        if (st != DUOFORGE_OK) {
            return st;
        }
    }
    return dfi_lum_berry(r, flat);
}

/* removeVolatile (sim/pokemon.ts), for a volatile whose condition has an onEnd line and no cause: the VOLATILE_END event of
 * the residual's ends (the protocol line names the volatile). */
static void dfi_volatile_end(dfi_run *r, uint32_t flat, uint32_t which)
{
    duoforge_event end = dfi_event_make(DUOFORGE_EVENT_VOLATILE_END, flat);
    end.detail = (uint8_t)which;
    dfi_emit(r, &end);
}

/* Mental Herb (step G47, data/items.ts:3889-3926, onUpdate): when its holder has a taunt, an encore, a disable or a heal
 * block, the herb is used (useItem: -enditem|X|Mental Herb with no [eat]; Unnerve does not refuse it, only TryEatItem asks),
 * and then every one of those volatiles is removed, in the pin's list order (taunt, encore, disable, heal block). The pin's
 * torment is not here: no volatile of it exists in the engine (Torment is not modelled), so no state can hold it. Step G71
 * (decision 0034): attract is the list's first condition, and its visible -end line is the herb's
 * (-end|X|move: Attract|[from] item: Mental Herb, cause ITEM); its silent end from onEnd is state only. Each removal shows
 * its own -end line through its condition's onEnd. */
static duoforge_status dfi_mental_herb(dfi_run *r, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    const dfi_member *m = dfi_at(b, flat);
    dfi_tail_pos *tail = &b->tail.sides[flat / 2u].positions[flat % 2u];
    if (m == NULL || m->hp == 0u || !dfi_holds(b, m, DFI_ITEM_MENTALHERB)) {
        return DUOFORGE_OK;
    }
    const bool attract = b->tail.attract_source[flat] != 0u; /* step G71 (decision 0034): the list's first condition */
    if (!attract && tail->taunt_turns == 0u && tail->encore_slot == 0u && tail->disable_slot == 0u &&
        tail->heal_block_turns == 0u) {
        return DUOFORGE_OK;
    }
    dfi_use_item(r, flat);
    if (attract) {
        /* The pin's list runs attract first (data/items.ts:3899-3918): its silent -end comes from onEnd, the visible line is the
         * herb's: -end|X|move: Attract|[from] item: Mental Herb (cause ITEM, id2 = the herb + 1). */
        b->tail.attract_source[flat] = 0u;
        duoforge_event end = dfi_ev(DUOFORGE_EVENT_VOLATILE_END, flat, DUOFORGE_CAUSE_ITEM, 1u + DFI_ITEM_MENTALHERB,
                                    DUOFORGE_NO_POSITION);
        end.detail = DUOFORGE_VOLATILE_ATTRACT;
        dfi_emit(r, &end);
    }
    if (tail->taunt_turns != 0u) {
        tail->taunt_turns = 0u;
        dfi_volatile_end(r, flat, DUOFORGE_VOLATILE_TAUNT);
    }
    if (tail->encore_slot != 0u) {
        tail->encore_slot = 0u;
        tail->encore_turns = 0u;
        dfi_volatile_end(r, flat, DUOFORGE_VOLATILE_ENCORE);
    }
    if (tail->disable_slot != 0u) {
        tail->disable_slot = 0u;
        tail->disable_turns = 0u;
        dfi_volatile_end(r, flat, DUOFORGE_VOLATILE_DISABLE);
    }
    if (tail->heal_block_turns != 0u) {
        tail->heal_block_turns = 0u;
        dfi_volatile_end(r, flat, DUOFORGE_VOLATILE_HEAL_BLOCK);
    }
    return DUOFORGE_OK;
}

/* ---------------------------------------------------------------- entry hazards (step G37) */

static void dfi_process_faints(dfi_run *r);

/* Stealth Rock, Spikes, Toxic Spikes and Sticky Web (data/moves.ts:17814-17839, :17500-17525, :19749-19788, :17935-17956; the
 * Champions mod overrides none of them): a side condition each, its layers in the POOL tail of the side (0 under every other
 * kind). Heavy-Duty Boots are Past in the format, so no holder skips them.
 *
 * Their SwitchIn handlers sort by priority, speed, sub-order and then by effectOrder, the order in which the conditions were
 * created (sim/battle.ts:994-1000: "they should activate in the order they were created"). The tail's side field hazard_order
 * (rev 4) keeps that order: a new kind (layers 0 to 1) takes the next slot, a further layer of Spikes or Toxic Spikes keeps
 * its slot (onSideRestart does not make a new state), an ended kind (Toxic Spikes absorbed) leaves and the later ones move
 * down, a kind that is put up again goes last. The kind codes DFI_HAZARD_* are the DUOFORGE_SIDE_* values minus 5. */
#define DFI_HAZARD_OF_SIDE(kind) ((kind) - DUOFORGE_SIDE_STEALTH_ROCK)
_Static_assert(DUOFORGE_SIDE_STEALTH_ROCK + DFI_HAZARD_STEALTH_ROCK == 5u && DUOFORGE_SIDE_SPIKES - DUOFORGE_SIDE_STEALTH_ROCK == DFI_HAZARD_SPIKES &&
                   DUOFORGE_SIDE_TOXIC_SPIKES - DUOFORGE_SIDE_STEALTH_ROCK == DFI_HAZARD_TOXIC_SPIKES &&
                   DUOFORGE_SIDE_STICKY_WEB - DUOFORGE_SIDE_STEALTH_ROCK == DFI_HAZARD_STICKY_WEB,
               "the hazard kinds of the tail's order are the side values minus the first");

static uint8_t *dfi_hazard_layers(struct duoforge_battle *b, uint32_t side, uint32_t kind)
{
    dfi_tail_side *ts = &b->tail.sides[side];
    return kind == DUOFORGE_SIDE_STEALTH_ROCK ? &ts->stealth_rock
           : kind == DUOFORGE_SIDE_SPIKES     ? &ts->spikes
           : kind == DUOFORGE_SIDE_TOXIC_SPIKES ? &ts->toxic_spikes
                                                : &ts->sticky_web;
}

/* Whether a side has any hazard (a SwitchIn handler on every Pokemon that enters it, also one that does nothing to it). */
static bool dfi_side_has_hazard(const struct duoforge_battle *b, uint32_t side)
{
    const dfi_tail_side *ts = &b->tail.sides[side];
    return ts->stealth_rock != 0u || ts->spikes != 0u || ts->toxic_spikes != 0u || ts->sticky_web != 0u;
}

/* The number of hazard kinds that are up on the side. */
static uint32_t dfi_hazard_count(const struct duoforge_battle *b, uint32_t side)
{
    const dfi_tail_side *ts = &b->tail.sides[side];
    return (ts->stealth_rock != 0u ? 1u : 0u) + (ts->spikes != 0u ? 1u : 0u) + (ts->toxic_spikes != 0u ? 1u : 0u) +
           (ts->sticky_web != 0u ? 1u : 0u);
}

/* The hazard that an ended condition leaves: its slot goes and the later ones move down (the layers are cleared by the caller). */
static void dfi_hazard_remove(struct duoforge_battle *b, uint32_t side, uint32_t kind)
{
    dfi_tail_side *ts = &b->tail.sides[side];
    const uint32_t n = dfi_hazard_count(b, side);
    uint32_t order = 0u;
    uint32_t put = 0u;
    for (uint32_t i = 0u; i < n; ++i) {
        const uint32_t slot = ((uint32_t)ts->hazard_order >> (2u * i)) & 3u;
        if (slot != DFI_HAZARD_OF_SIDE(kind)) {
            order |= slot << (2u * put);
            put += 1u;
        }
    }
    ts->hazard_order = (uint8_t)order; /* wide-operands-reviewed: 4 slots of 2 bits */
}

/* side.addSideCondition of a hazard (sim/side.ts:413-443): *added is false when the condition is at its last layer (Stealth
 * Rock and Sticky Web have no onSideRestart: addSideCondition returns false; Spikes stop at 3 layers and Toxic Spikes at 2) and
 * the caller shows what a failure shows. A new layer shows -sidestart again (SIDE_START, amount the hazard). */
static duoforge_status dfi_add_hazard(dfi_run *r, uint32_t side, uint32_t kind, bool *added)
{
    uint8_t *layers = dfi_hazard_layers(r->b, side, kind);
    const uint32_t most = kind == DUOFORGE_SIDE_SPIKES ? DFI_TAIL_SPIKES_MAX
                          : kind == DUOFORGE_SIDE_TOXIC_SPIKES ? DFI_TAIL_TOXIC_SPIKES_MAX : 1u;
    *added = false;
    if (*layers >= most) {
        return DUOFORGE_OK;
    }
    if (*layers == 0u) {
        /* a new condition has the newest effectOrder: the next slot of the creation order */
        dfi_tail_side *ts = &r->b->tail.sides[side];
        const uint32_t n = dfi_hazard_count(r->b, side);
        ts->hazard_order = (uint8_t)((uint32_t)ts->hazard_order | (DFI_HAZARD_OF_SIDE(kind) << (2u * n))); /* wide-operands-reviewed: n <= 3 */
    }
    *layers = (uint8_t)((uint32_t)*layers + 1u); /* wide-operands-reviewed: <= 3 */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_SIDE_START, DUOFORGE_NO_POSITION);
    e.detail = (uint8_t)side;
    e.amount = (uint8_t)kind; /* DUOFORGE_SIDE_* */
    dfi_emit(r, &e);
    *added = true;
    return DUOFORGE_OK;
}

/* The SwitchIn handlers of the hazards of the side that the Pokemon at `flat` entered, in their creation order, for that
 * Pokemon (the handler's holder is the entering Pokemon, sim/battle.ts:502). A condition that an earlier handler removed (Toxic
 * Spikes that a Poison type absorbed) is skipped (sim/battle.ts:540-543). fieldEvent runs faintMessages after each handler
 * (:569-570): a Pokemon that one hazard knocks out has its faint shown at once and no handler after it (`effectHolder.fainted`,
 * :512), neither a later hazard's nor its ability's (recorded by the differential campaign: Stealth Rock, then no Sticky Web line).
 * The foe of Toxic Spikes' status and Sticky Web's drop is the foe's first position (`foe.active[0]`). */
static duoforge_status dfi_hazards_enter(dfi_run *r, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    const uint32_t side = flat / 2u;
    const uint32_t source = (1u - side) * 2u;
    const dfi_member *m = dfi_at(b, flat);
    dfi_tail_side *ts = &b->tail.sides[side];
    const uint32_t order = ts->hazard_order; /* the handlers are collected before the first runs */
    const uint32_t n = dfi_hazard_count(b, side);
    for (uint32_t i = 0u; i < n; ++i) {
        const uint32_t kind = DUOFORGE_SIDE_STEALTH_ROCK + ((order >> (2u * i)) & 3u);
        if (*dfi_hazard_layers(b, side, kind) == 0u) {
            continue; /* removed by an earlier handler */
        }
        duoforge_status st = DUOFORGE_OK;
        if (kind == DUOFORGE_SIDE_STEALTH_ROCK) {
            /* the Rock effectiveness against the Pokemon's types, clamped to [-6, 6]: maxhp * 2 ** typeMod / 8 */
            const uint32_t biased = dfi_type_mod(b, m, DFI_TYPE_ROCK, &dfi_pool_moves[DFI_MOVE_STEALTHROCK]); /* 6 + typeMod, 4..8 */
            const uint32_t hp = m->hp_max;
            uint32_t amount = biased >= DFI_BIAS6 ? (hp << (biased - DFI_BIAS6)) / 8u : hp / (8u << (DFI_BIAS6 - biased));
            amount = amount == 0u ? 1u : amount;
            st = dfi_deal(r, flat, amount, DUOFORGE_CAUSE_MOVE, DFI_MOVE_STEALTHROCK, DUOFORGE_NO_POSITION, DFI_DMG_SIDE);
        } else if (kind == DUOFORGE_SIDE_SPIKES) {
            if (dfi_grounded(b, m)) {
                static const uint8_t twenty_fourths[4] = {0u, 3u, 4u, 6u}; /* 1/8, 1/6, 1/4 of the maximum HP */
                uint32_t amount = ((uint32_t)twenty_fourths[ts->spikes] * m->hp_max) / 24u;
                amount = amount == 0u ? 1u : amount;
                st = dfi_deal(r, flat, amount, DUOFORGE_CAUSE_MOVE, DFI_MOVE_SPIKES, DUOFORGE_NO_POSITION, DFI_DMG_SIDE);
            }
        } else if (kind == DUOFORGE_SIDE_TOXIC_SPIKES) {
            if (dfi_grounded(b, m)) {
                if (dfi_has_type(b, m, DFI_TYPE_POISON)) {
                    /* -sideend|side|move: Toxic Spikes|[of] the Pokemon, and the condition is gone */
                    dfi_hazard_remove(b, side, kind);
                    ts->toxic_spikes = 0u;
                    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_SIDE_END, DUOFORGE_NO_POSITION);
                    e.detail = (uint8_t)side;
                    e.amount = (uint8_t)DUOFORGE_SIDE_TOXIC_SPIKES;
                    e.other = (uint8_t)flat; /* < 4 */
                    dfi_emit(r, &e);
                } else if (!dfi_has_type(b, m, DFI_TYPE_STEEL)) {
                    /* trySetStatus('psn' or 'tox', foe.active[0]) with the condition as the source effect: no -fail and no
                     * -immune line, and Flower Veil's silent interruption (sim/pokemon.ts:1684-1744) */
                    st = dfi_try_status(r, flat, ts->toxic_spikes >= 2u ? DFI_STATUS_TOX : DFI_STATUS_PSN, source,
                                        DFI_NO_SOURCE_MOVE, DFI_ORIGIN_HAZARD, 0u);
                }
            }
        } else if (dfi_grounded(b, m)) {
            /* Sticky Web: -activate|X|move: Sticky Web, then boost({spe: -1}, X, foe.active[0], the move) */
            static const uint8_t spe_down[DFI_STAT_STAGE_COUNT] = {6u, 6u, 6u, 6u, 5u, 6u, 6u};
            const duoforge_event e =
                dfi_ev(DUOFORGE_EVENT_ACTIVATE, flat, DUOFORGE_CAUSE_MOVE, DFI_MOVE_STICKYWEB, DUOFORGE_NO_POSITION);
            dfi_emit(r, &e);
            (void)dfi_boost(r, flat, spe_down, source, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_PRIMARY));
        }
        if (st != DUOFORGE_OK) {
            return st;
        }
        /* fieldEvent runs faintMessages after each handler (sim/battle.ts:569-570): the faint shows at once and the Pokemon, now
         * fainted, has no handler left (`effectHolder.fainted`, :512), a later hazard's and its ability's included. */
        dfi_process_faints(r);
        if (r->ended || m->hp == 0u) {
            return DUOFORGE_OK;
        }
    }
    return DUOFORGE_OK;
}

/* A volatile from a secondary effect (addVolatile): nothing on a fainted
 * Pokemon; confusion does not restart and lasts random(2, 6) attempts. */
static duoforge_status dfi_add_volatile(dfi_run *r, uint32_t flat, uint32_t which)
{
    const dfi_member *m = dfi_at(r->b, flat);
    dfi_active_slot *pos = dfi_pos(r->b, flat);
    if (m == NULL || m->hp == 0u) {
        return DUOFORGE_OK;
    }
    if (which == DFI_VOLATILE_FLINCH) {
        /* Inner Focus (step G22, POOL data, data/abilities.ts:2153-2167): onTryAddVolatile returns null for the flinch
         * volatile, so it is not added and nothing is shown; the secondary's roll was drawn before (the caller). The
         * ability is breakable (a move or ability that ignores abilities would skip it): Mold Breaker is unmarked
         * (tests/mechanics/test_sand_snow_weather.c), Teravolt and Turboblaze are not in the pool, and a move with ignoreAbility has a
         * field that the generator does not model (UNMODELED). */
        if (dfi_ability(r->b, m, DFI_ABILITY_INNERFOCUS)) {
            return DUOFORGE_OK;
        }
        pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_FLINCH); /* wide-operands-reviewed */
        return DUOFORGE_OK;
    }
    if (which != DFI_VOLATILE_CONFUSION) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    if (pos->confusion_turns != 0u) {
        return DUOFORGE_OK;
    }
    /* Misty Terrain's onTryAddVolatile (step G25, data/moves.ts:12170-12177): confusion on a grounded Pokemon returns
     * null; the -activate line is for a move without secondaries, and this function adds only a secondary's confusion. */
    /* onTryAddVolatile returns null for a grounded target that is not semi-invulnerable (data/moves.ts:12171). */
    if (r->b->terrain == DFI_TERRAIN_MISTY && dfi_grounded(r->b, m) && !dfi_semi_invulnerable(r, flat)) {
        return DUOFORGE_OK;
    }
    uint32_t v = 0u;
    const duoforge_status st = dfi_draw(r->draws, DFI_SITE_CONFUSION_TURNS, 2u, 6u, &v);
    if (st != DUOFORGE_OK) {
        return st;
    }
    pos->confusion_turns = (uint8_t)v; /* 2..5 */
    dfi_emit_plain(r, DUOFORGE_EVENT_CONFUSION_START, flat); /* [-start] confusion */
    return DUOFORGE_OK;
}

/* A primary confusion (step G92, decision 0062): the volatile of a move without secondaries (Confuse Ray, Swagger, Flatter,
 * Teeter Dance; runMoveEffects' addVolatile, sim/battle-actions.ts:1236-1238, sim/pokemon.ts:1969-2009). A fainted Pokemon
 * refuses, and a confused one refuses silently (no TryAddVolatile). Then TryAddVolatile: Misty Terrain's onTryAddVolatile
 * (data/moves.ts:12170-12177) returns null for a grounded Pokemon that is not semi-invulnerable and prints the -activate
 * line with `move: Misty Terrain`, because the effect is the move and has no secondaries; it is the line of Thunder Wave under
 * Misty Terrain (step G68). Otherwise the volatile starts with random(2, 6) turns. `*added` tells whether it did, which the
 * move's result needs (a refused confusion is false). */
static duoforge_status dfi_confuse_primary(dfi_run *r, uint32_t flat, bool *added, bool *terrain)
{
    const dfi_member *m = dfi_at(r->b, flat);
    dfi_active_slot *pos = dfi_pos(r->b, flat);
    *added = false;
    *terrain = false;
    if (m == NULL || m->hp == 0u || pos->confusion_turns != 0u) {
        return DUOFORGE_OK;
    }
    if (r->b->terrain == DFI_TERRAIN_MISTY && dfi_grounded(r->b, m) && !dfi_semi_invulnerable(r, flat)) {
        /* onTryAddVolatile returns null (not false): the move shows no [still] line (the replay of g92_cr_misty) */
        *terrain = true;
        const duoforge_event e =
            dfi_ev(DUOFORGE_EVENT_ACTIVATE, flat, DUOFORGE_CAUSE_MOVE, DFI_MOVE_MISTYTERRAIN, DUOFORGE_NO_POSITION);
        dfi_emit(r, &e);
        return DUOFORGE_OK;
    }
    uint32_t v = 0u;
    const duoforge_status st = dfi_draw(r->draws, DFI_SITE_CONFUSION_TURNS, 2u, 6u, &v);
    if (st != DUOFORGE_OK) {
        return st;
    }
    pos->confusion_turns = (uint8_t)v; /* 2..5 */
    dfi_emit_plain(r, DUOFORGE_EVENT_CONFUSION_START, flat); /* [-start] confusion */
    *added = true;
    return DUOFORGE_OK;
}

/* getConfusionDamage (sim/battle-actions.ts:1850-1862): a typeless 40 power
 * physical hit on itself with its own staged stats, 16-bit, randomized,
 * at least 1. */
static duoforge_status dfi_confusion_damage(dfi_run *r, uint32_t flat, uint32_t *out)
{
    const dfi_member *m = dfi_at(r->b, flat);
    const dfi_active_slot *pos = dfi_pos(r->b, flat);
    uint32_t attack = 0u;
    uint32_t defense = 0u;
    uint32_t damage = 0u;
    if (dfi_staged_stat(m, pos, DFI_STAGE_ATK, &attack) != DUOFORGE_OK ||
        dfi_staged_stat(m, pos, DFI_STAGE_DEF, &defense) != DUOFORGE_OK ||
        !dfi_base_damage(DFI_LEVEL, 40u, attack, defense, &damage)) {
        return DUOFORGE_E_INVARIANT;
    }
    damage = (damage + 2u) & 0xFFFFu;
    uint32_t roll = 0u;
    const duoforge_status st = dfi_draw(r->draws, DFI_SITE_DAMAGE_ROLL, 0u, 16u, &roll);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (!dfi_randomize(damage, roll, &damage)) {
        return DUOFORGE_E_INVARIANT;
    }
    *out = damage == 0u ? 1u : damage;
    return DUOFORGE_OK;
}

/* A standing brought member that is not on the field (canSwitch). */
static bool dfi_can_switch(const struct duoforge_battle *b, uint32_t side)
{
    const dfi_side *sd = &b->sides[side];
    for (uint32_t m = 0u; m < sd->member_count && m < DUOFORGE_MAX_ROSTER; ++m) {
        if (((uint32_t)sd->brought_mask >> m & 1u) != 0u && sd->members[m].hp != 0u &&
            sd->positions[0].occupant != m && sd->positions[1].occupant != m) {
            return true;
        }
    }
    return false;
}

/* Shadow Tag (step G41, data/abilities.ts:4156-4173): at every nextTurn the reference clears `trapped` on each active Pokemon and
 * runs TrapPokemon (sim/battle.ts:1726-1730), where a standing foe's Shadow Tag calls tryTrap(true) on every Pokemon that is not
 * itself a Shadow Tag holder and is adjacent to the holder (in doubles every foe is: sim/pokemon.ts isAdjacent). tryTrap
 * (sim/pokemon.ts:1607-1612) fails for a Pokemon immune to the status 'trapped': a Ghost type (typechart `trapped: 3`,
 * tools/datagen/pool_families.js checkG41), by its current types, so Soak's Water makes it trappable again. The trap is read
 * only where the next request is made, at the TURN boundary, so it is derived from the board and keeps no state: a trapped
 * Pokemon's request refuses every switch (side.chooseSwitch: "Can't switch: The active Pokemon is trapped"; the hint
 * `trapped` or `maybeTrapped` of the request is information, not a rule). Replacements, pivots (a move's selfSwitch, Emergency
 * Exit, Eject Button) and a forced switch ignore it. Shed Shell and Run Away free their holder (items.ts shedshell, the Champions
 * mod's runaway, onTrapPokemon at priority -10 after Shadow Tag's): neither is marked, so no battle has them. The ability is
 * the current one: a Mega's, or one that Trace copied. `flat` must be an occupied position. */
static const dfi_member *dfi_member_at(const struct duoforge_battle *b, uint32_t flat)
{
    const uint32_t occupant = b->sides[flat / 2u].positions[flat % 2u].occupant;
    return occupant < DUOFORGE_MAX_ROSTER ? &b->sides[flat / 2u].members[occupant] : NULL;
}

bool dfi_switch_trapped(const struct duoforge_battle *b, uint32_t flat)
{
    const dfi_member *m = dfi_member_at(b, flat);
    if (m == NULL || m->hp == 0u || dfi_has_type(b, m, DFI_TYPE_GHOST)) {
        return false; /* tryTrap refuses a Ghost type for every trap (typechart trapped: 3) */
    }
    /* The partial trap (step G90, decision 0060): the volatile is up and its source is on the field (a source that left has
     * its tail source cleared, and a fainted one has ended the trap at the residual). The holder itself may have Shadow Tag. */
    if (b->tail.sides[flat / 2u].positions[flat % 2u].trap_turns != 0u &&
        b->tail.sides[flat / 2u].positions[flat % 2u].trap_source != 0u) {
        return true;
    }
    if (dfi_ability(b, m, DFI_ABILITY_SHADOWTAG)) {
        return false;
    }
    const uint32_t foe = 1u - flat / 2u;
    for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
        const dfi_member *f = dfi_member_at(b, foe * 2u + slot);
        if (f != NULL && f->hp != 0u && dfi_ability(b, f, DFI_ABILITY_SHADOWTAG)) {
            return true;
        }
    }
    return false;
}

/* Emergency Exit (onEmergencyExit, data/mods/champions/abilities.ts): a
 * standing holder that fell from above half HP to half or less, with a
 * reserve and no switch flag yet, leaves. Unlike the base game, the
 * Champions handler leaves every other switch flag in place. */
/* `drag_pending`: the positions with a forced switch that has not happened yet (step G46). The Champions Emergency Exit
 * returns when the holder has forceSwitchFlag (abilities.ts:24), so a pending drag stops it. */
static bool dfi_exits(struct duoforge_battle *b, uint32_t flat, uint32_t hp_before, uint32_t drag_pending)
{
    const dfi_member *m = dfi_at(b, flat);
    return m != NULL && m->hp != 0u && dfi_ability_code(b, m) == 1u + DFI_ABILITY_EMERGENCYEXIT &&
           (uint32_t)m->hp * 2u <= m->hp_max && hp_before * 2u > m->hp_max && dfi_can_switch(b, flat / 2u) &&
           dfi_pos(b, flat)->switch_flag == 0u && ((drag_pending >> flat) & 1u) == 0u;
}

static void dfi_emergency_exit(dfi_run *r, uint32_t flat, uint32_t hp_before)
{
    if (dfi_exits(r->b, flat, hp_before, r->drag_pending)) {
        dfi_pos(r->b, flat)->switch_flag = (uint8_t)DFI_SWITCH_EMERGENCY_EXIT;
        const duoforge_event e = dfi_ev(DUOFORGE_EVENT_ACTIVATE, flat, DUOFORGE_CAUSE_ABILITY,
                                        1u + DFI_ABILITY_EMERGENCYEXIT, DUOFORGE_NO_POSITION);
        dfi_emit(r, &e); /* [-activate] ability: Emergency Exit */
    }
}

/* useItem / eatItem: the item is gone and the opponent saw it go
 * ([-enditem], with [eat] for a berry). */
static void dfi_use_item(dfi_run *r, uint32_t flat)
{
    dfi_use_item_of(r, flat, DUOFORGE_NO_POSITION);
}

/* useItem with a position named in the line ([of] other: Red Card names the attacker, step G46). Symbiosis (step G69) is the
 * ally's AfterUseItem, after the Unburden volatile of this user. */
static void dfi_use_item_of(dfi_run *r, uint32_t flat, uint32_t other)
{
    dfi_use_item_core(r, flat, other);
    dfi_symbiosis(r, flat);
}

/* The item line and the Unburden volatile of a use (dfi_use_item_of without Symbiosis). A berry eaten at Update (Sitrus, Lum) calls it
 * and runs dfi_symbiosis itself after its Eat effect (eatItem: Eat, then AfterUseItem; step G69). */
static void dfi_use_item_core(dfi_run *r, uint32_t flat, uint32_t other)
{
    struct duoforge_battle *b = r->b;
    const uint32_t side = flat / 2u;
    const uint32_t occupant = dfi_pos(b, flat)->occupant;
    const uint32_t item = dfi_item_code(b, &b->sides[side].members[occupant]); /* before it is used up */
    b->sides[side].members[occupant].item_consumed = 1u;
    duoforge_event e = dfi_ev(DUOFORGE_EVENT_ITEM_END, flat, DUOFORGE_CAUSE_NONE, item, other);
    const bool berry = item == 1u + DFI_ITEM_SITRUSBERRY || item == 1u + DFI_ITEM_LUMBERRY /* step G47: isBerry */ ||
                       (item != 0u && item <= DFI_POOL_ITEM_COUNT &&
                        dfi_pool_item_family[item - 1u].family == DFI_ITEM_FAMILY_RESIST_BERRY);
    e.flags = berry ? (uint8_t)DUOFORGE_EVENT_FLAG_EATEN : 0u;
    dfi_emit(r, &e);
    /* AfterUseItem: Unburden adds its volatile (Team C, data/abilities.ts). */
    if (dfi_ability(b, &b->sides[side].members[occupant], DFI_ABILITY_UNBURDEN)) {
        dfi_active_slot *pos = dfi_pos(b, flat);
        pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_UNBURDEN); /* wide-operands-reviewed: < 256 */
    }
}

static bool dfi_heal_blocked(const struct duoforge_battle *b, uint32_t flat);
static void dfi_heal(dfi_run *r, uint32_t flat, uint32_t amount, uint32_t cause, uint32_t id2, uint32_t other);

/* Bug Bite (step G64, data/moves.ts:1911-1931, onHit): when the user stands and the target holds a berry (the isBerry items of
 * the pool: Sitrus Berry, Lum Berry and the resist berries, Chilan and Chople included), the target's takeItem(user): a live
 * Sticky Hold shows `-activate|X|ability: Sticky Hold` and keeps the berry (as Knock Off's). The berry is then the user's to
 * eat, at once: `-enditem|X|Berry|[from] stealeat|[move] Bug Bite|[of] user` (ITEM_END, cause ITEM_TAKEN, the move in id, the user
 * in other, the eaten flag), and the Eat handler of the berry runs for the user, with no TryEatItem (no Unnerve test):
 * Sitrus heals the user by a quarter of its maximum HP (`this.heal`, which a Heal Block refuses and a full user does not show),
 * Lum cures the user and ends its confusion (dfi_lum_cure), and a resist berry's onEat is empty. The user is the eater, so
 * Unburden and the holder's item lock are not involved. `user` is the attacker, `target` a damaged foe. */
static duoforge_status dfi_bug_bite(dfi_run *r, uint32_t user, uint32_t target, uint32_t move_id)
{
    struct duoforge_battle *b = r->b;
    dfi_member *um = dfi_at(b, user);
    dfi_member *tm = dfi_at(b, target);
    if (um == NULL || um->hp == 0u || tm == NULL) {
        return DUOFORGE_OK; /* onHit's `source.hp` test */
    }
    const uint32_t item = dfi_item_code(b, tm);
    const bool berry = item == 1u + DFI_ITEM_SITRUSBERRY || item == 1u + DFI_ITEM_LUMBERRY ||
                       (item != 0u && item <= DFI_POOL_ITEM_COUNT &&
                        dfi_pool_item_family[item - 1u].family == DFI_ITEM_FAMILY_RESIST_BERRY);
    if (!berry) {
        return DUOFORGE_OK; /* item.isBerry is false: nothing is taken */
    }
    dfi_active_slot *pos = dfi_pos(b, target);
    if (tm->hp != 0u && dfi_ability(b, tm, DFI_ABILITY_STICKYHOLD)) {
        const duoforge_event block = dfi_ev(DUOFORGE_EVENT_ACTIVATE, target, DUOFORGE_CAUSE_ABILITY,
                                            1u + DFI_ABILITY_STICKYHOLD, DUOFORGE_NO_POSITION);
        dfi_emit(r, &block); /* [-activate] ability: Sticky Hold */
        return DUOFORGE_OK;
    }
    if (tm->hp != 0u && dfi_ability(b, tm, DFI_ABILITY_UNBURDEN)) {
        pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_UNBURDEN); /* wide-operands-reviewed: < 256 */
    }
    b->tail.sides[target / 2u].item_now[pos->occupant] = (uint8_t)DFI_TAIL_ITEM_NONE;
    duoforge_event e = dfi_ev(DUOFORGE_EVENT_ITEM_END, target, DUOFORGE_CAUSE_ITEM_TAKEN, item, user);
    e.id = (uint16_t)move_id;
    e.flags = (uint8_t)DUOFORGE_EVENT_FLAG_EATEN;
    dfi_emit(r, &e); /* [-enditem] [from] stealeat [move] Bug Bite [of] user */
    if (item == 1u + DFI_ITEM_SITRUSBERRY) {
        if (um->hp < um->hp_max && !dfi_heal_blocked(b, user)) {
            dfi_heal(r, user, (uint32_t)um->hp_max / 4u, DUOFORGE_CAUSE_ITEM, 1u + DFI_ITEM_SITRUSBERRY, DUOFORGE_NO_POSITION);
        }
    } else if (item == 1u + DFI_ITEM_LUMBERRY) {
        return dfi_lum_cure(r, user);
    }
    /* No AfterUseItem here: Bug Bite runs only the Eat singleEvent and EatItem of the berry (data/moves.ts:1920-1930), never
     * eatItem, so neither Unburden nor Symbiosis of the eater's side is run (step G69). */
    return DUOFORGE_OK;
}

/* choicelock's two removals (data/conditions.ts:332-336 onBeforeMove and :349-352 onDisableMove): the holder no longer has
 * a Choice item (only the Choice Scarf is one in the pool), so the volatile ends and its locked move with it, unless a
 * charging two-turn move shares the byte. The item leaving does not end the lock by itself (items.ts's Choice items
 * remove it only in their own onStart, i.e. when the holder gets one), so a stop in the middle of a turn still shows it. */
static void dfi_choice_lock_ends(struct duoforge_battle *b, uint32_t flat)
{
    dfi_active_slot *pos = dfi_pos(b, flat);
    if (pos->occupant == DFI_OCCUPANT_NONE || ((uint32_t)pos->flags & DFI_VOL_CHOICE_LOCK) == 0u ||
        dfi_holds(b, dfi_at(b, flat), DFI_ITEM_CHOICESCARF)) {
        return;
    }
    pos->flags = (uint8_t)((uint32_t)pos->flags & ~(uint32_t)DFI_VOL_CHOICE_LOCK); /* wide-operands-reviewed */
    if (pos->charge_turns == 0u) {
        pos->locked_move = 0u;
    }
}

/* lockedmove (step G56, data/conditions.ts:253-285): the volatile is removed, and onEnd adds confusion when the count is 1 or
 * less (trueDuration > 1 returns). dfi_lock_remove is the silent removal (a faint, a switch, the onResidual delete of a holder
 * put to sleep after its restarted use: the pin's clearVolatile and that delete have no onEnd). The locked move is the choice
 * lock's or the charge's too, so it is cleared only when neither holds. The unused-lock bit (issue 606, decision 0015 5dv)
 * goes with the lock. */
static void dfi_lock_remove(struct duoforge_battle *b, uint32_t flat)
{
    dfi_tail_pos *lt = &b->tail.sides[flat / 2u].positions[flat % 2u];
    lt->lock_turns = 0u;
    lt->single_turn = (uint8_t)((uint32_t)lt->single_turn & ~(uint32_t)DFI_SINGLE_TURN_LOCK_UNUSED); /* wide-operands-reviewed: a byte mask */
    dfi_active_slot *pos = dfi_pos(b, flat);
    if (((uint32_t)pos->flags & DFI_VOL_CHOICE_LOCK) == 0u && pos->charge_turns == 0u) {
        pos->locked_move = 0u;
    }
}

/* onEnd of the lock: removed, then confusion (addVolatile) when the count was 1 or less. */
static duoforge_status dfi_lock_end(dfi_run *r, uint32_t flat)
{
    const uint32_t left = r->b->tail.sides[flat / 2u].positions[flat % 2u].lock_turns;
    dfi_lock_remove(r->b, flat);
    if (left > 1u) {
        return DUOFORGE_OK;
    }
    return dfi_add_volatile(r, flat, DFI_VOLATILE_CONFUSION);
}

/* Knock Off's onAfterHit (data/moves.ts:9959-9984; run by spreadMoveHit for each damaged target, also for a target that
 * this hit knocked out (its faint is not processed yet) and, in the Champions mod, also when the user has fainted since
 * (the base game asks whether the user has HP: sim/battle-actions.ts:1123; data/mods/champions/scripts.ts:411 does not)):
 * target.takeItem() (sim/pokemon.ts:1851-1866).
 *   - No item (used up, eaten, already taken): nothing, no line.
 *   - runEvent TakeItem, its handlers by subOrder (sim/battle.ts:956-972), the target's ability before its item:
 *     Sticky Hold (data/abilities.ts:4622-4635) of a Pokemon that is alive shows `-activate|X|ability: Sticky Hold` and
 *     the item stays (a fainted one does not block); then the item's own onTakeItem, which only the Mega Stones have
 *     and which refuses the stone's own species (dfi_item_takeable). Unburden's onTakeItem
 *     (data/abilities.ts:5240-5242) comes with the ability and adds its volatile at this point, also when the item's own
 *     check then refuses: so a Hawlucha (Unburden) that holds its own Hawluchanite gets the volatile although the stone
 *     stays (step G24 marks Hawluchanite). The volatile's Speed doubling asks for no item (:5247-5251), so it changes
 *     nothing while the stone is held (dfi_speed); the state invariant allows the volatile with the item held only for
 *     a member that holds its own Mega Stone.
 *   - The item is gone for good: the tail's item_now holds DFI_TAIL_ITEM_NONE (it stays across a switch-out and a faint;
 *     the pin restores nothing), and `-enditem|X|Item|[from] move: Knock Off|[of] Y` shows it (ITEM_END, cause
 *     ITEM_TAKEN, the move in id, the user in other). Neither the item's End nor AfterTakeItem has a handler in the pool.
 *   - A choice lock ends with the item: choicelock's onBeforeMove and onDisableMove remove it when the item is no Choice
 *     item, and a move that was already chosen still runs, so ending it here is the same. A lock that a charging
 *     two-turn move shares keeps its move.
 * `user` is the Pokemon that used the move, `target` the damaged one. */
static void dfi_knock_off(dfi_run *r, uint32_t user, uint32_t target, uint32_t move_id)
{
    struct duoforge_battle *b = r->b;
    dfi_member *tm = dfi_at(b, target);
    if (tm == NULL || dfi_item_code(b, tm) == 0u) {
        return;
    }
    if (tm->hp != 0u && dfi_ability(b, tm, DFI_ABILITY_STICKYHOLD)) {
        const duoforge_event block = dfi_ev(DUOFORGE_EVENT_ACTIVATE, target, DUOFORGE_CAUSE_ABILITY,
                                            1u + DFI_ABILITY_STICKYHOLD, DUOFORGE_NO_POSITION);
        dfi_emit(r, &block); /* [-activate] ability: Sticky Hold */
        return;
    }
    dfi_active_slot *pos = dfi_pos(b, target);
    if (tm->hp != 0u && dfi_ability(b, tm, DFI_ABILITY_UNBURDEN)) {
        pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_UNBURDEN); /* wide-operands-reviewed: < 256 */
    }
    if (!dfi_item_takeable(b, tm)) {
        return;
    }
    const uint32_t item = dfi_item_code(b, tm);
    b->tail.sides[target / 2u].item_now[pos->occupant] = (uint8_t)DFI_TAIL_ITEM_NONE;
    duoforge_event e = dfi_ev(DUOFORGE_EVENT_ITEM_END, target, DUOFORGE_CAUSE_ITEM_TAKEN, item, user);
    e.id = (uint16_t)move_id;
    dfi_emit(r, &e); /* [-enditem] [from] move: Knock Off [of] user */
    /* The Choice lock stays: the pin ends it only in choicelock's own onBeforeMove (the holder's next move, dfi_run_move)
     * and onDisableMove (every request, endTurn, dfi_end_turn), see dfi_choice_lock_ends. */
}

/* ---------------------------------------------------------------------------------------------------------------------
 * Step G29, the item-transfer moves: Trick and Switcheroo (status), Thief and Covet (damaging). The pin
 * (data/moves.ts:19865-19911 Trick, :18644-18690 Switcheroo, :19302-19330 Thief, :3099-3123 Covet; the Champions mod does
 * not change them) in terms of sim/pokemon.ts:1851-1889 (takeItem, setItem):
 *   - takeItem(source): no item, nothing (undefined: no event runs); otherwise runEvent TakeItem, the holder's ability
 *     before its item: Sticky Hold (data/abilities.ts:4622-4635) of a live holder shows `-activate|X|ability: Sticky Hold`
 *     and refuses when the taker is another Pokemon (a Pokemon that takes its own item is not refused), Unburden's
 *     onTakeItem (:5240-5242) adds its volatile (a live holder; it comes first, so it is set although the item's own check
 *     then refuses: the Mega Stone of the holder's own species, dfi_item_takeable); a refusal is `false`.
 *   - Trick and Switcheroo: onTryImmunity (the hit step before accuracy) fails a Sticky Hold target with `-immune`.
 *     onHit takes the target's item (source = the user), then the user's own; a refusal of either, or two empty hands,
 *     restores both items and fails (-fail|user, [still]); so does the second TakeItem check of each item with the other
 *     Pokemon as the one that receives it: a Mega Stone is refused for a recipient of the species it belongs to
 *     (the handler's second argument is the receiver, data/items.ts:27). Then `-activate|user|move: Trick|[of] target`
 *     (Switcheroo prints Trick too), and for the target, then for the user: setItem and `-item|X|Item|[from] move: M`,
 *     or, when the other one had nothing, the silent `-enditem|X|Item|[silent]|[from] move: M` of the item that left.
 *   - Thief and Covet: onAfterHit, nothing if the user holds an item; takeItem(user) of the target (Sticky Hold shows its
 *     line and keeps the item); the second TakeItem check with the user as receiver; setItem(user) (a user that has
 *     fainted since, which the Champions mod allows, refuses: the item goes back to the target, whose takeItem already
 *     ran the TakeItem handlers); Thief: the silent `-enditem|target|Item|[silent]|[from] move: Thief|[of] user`, then
 *     `-item|user|Item|[from] move: Thief|[of] target`; Covet only the second line, with its own move.
 *   - setItem runs the item's onStart (data/items.ts): a Choice item removes the holder's lock, and a White Herb or a terrain
 *     seed whose condition holds is used on the spot, before the `-item` line. The lock part is dfi_set_held; the use of an
 *     item on the spot is E_UNSUPPORTED, decided before anything changes (dfi_start_uses_item).
 * State: the held item is the tail's item_now (G16): 1 + id for an item that a move put there, DFI_TAIL_ITEM_NONE for none;
 * a Pokemon that gets an item has its item_consumed flag cleared (the flag says that what it held was used up). A lock ends
 * with the item (dfi_set_held), as for Knock Off. Events: `-activate move: Trick` is ACTIVATE, cause MOVE; the `-item` line is
 * ITEM_START (the cause MOVE, id: the move, id2: the item + 1, other: the one it came from when the line says [of]); the silent
 * -enditem line is ITEM_END with the cause ITEM_TAKEN, as Knock Off's.
 * ------------------------------------------------------------------------------------------------------------------ */

/* The item `code` (1 + an item id, 0 none) is a Mega Stone that the second TakeItem check refuses for `recipient`: the stone
 * of the recipient's own species (megaStone[source.baseSpecies.baseSpecies] of the handler's second argument). */
static bool dfi_stone_refused_for(const dfi_member *recipient, uint32_t code)
{
    if (code == 0u || code > DFI_POOL_ITEM_COUNT) {
        return false;
    }
    const uint32_t base = dfi_pool_items[code - 1u].mega_base;
    return base != DFI_FORME_NONE && dfi_pool_formes[base].dex_num == dfi_forme_of(recipient)->dex_num;
}

/* A Pokemon that gets item `code` on the spot uses it in setItem's onStart: a White Herb with a lowered stat, a terrain seed
 * whose terrain is up (data/items.ts whiteherb, grassyseed, psychicseed). The engine refuses that case, not guesses it. */
static bool dfi_start_uses_item(struct duoforge_battle *b, uint32_t flat, uint32_t code)
{
    if (code == 1u + DFI_ITEM_GRASSYSEED) {
        return b->terrain == DFI_TERRAIN_GRASSY;
    }
    if (code == 1u + DFI_ITEM_PSYCHICSEED) {
        return b->terrain == DFI_TERRAIN_PSYCHIC;
    }
    if (code == 1u + DFI_ITEM_WHITEHERB) {
        const dfi_active_slot *pos = dfi_pos(b, flat);
        for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
            if (pos->stages[i] < DFI_STAGE_NEUTRAL) {
                return true;
            }
        }
    }
    return false;
}

/* The TakeItem event of a holder that has an item and is alive: Unburden's onTakeItem adds its volatile. */
static void dfi_unburden_on_take(struct duoforge_battle *b, uint32_t flat)
{
    const dfi_member *m = dfi_at(b, flat);
    if (m != NULL && m->hp != 0u && dfi_ability(b, m, DFI_ABILITY_UNBURDEN)) {
        dfi_active_slot *pos = dfi_pos(b, flat);
        pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_UNBURDEN); /* wide-operands-reviewed: < 256 */
    }
}

/* The member at `flat` now holds item `code` (1 + id) or nothing (0): the tail's item_now, and its consumed flag cleared for
 * an item that it gets. A Choice item that it gets ends its Choice lock at once (the item's onStart, data/items.ts:966-972:
 * setItem runs it); the item that it loses or gets in place of a Choice item does not: the lock stays until choicelock's own
 * onBeforeMove or onDisableMove ends it (dfi_choice_lock_ends). */
static void dfi_set_held(struct duoforge_battle *b, uint32_t flat, uint32_t code)
{
    dfi_active_slot *pos = dfi_pos(b, flat);
    const uint32_t occupant = pos->occupant;
    if (occupant >= DUOFORGE_MAX_ROSTER) {
        return; /* unreachable: every caller passes the user or the target of a move that hit, both on the field */
    }
    dfi_member *m = &b->sides[flat / 2u].members[occupant];
    b->tail.sides[flat / 2u].item_now[occupant] = (uint8_t)(code == 0u ? DFI_TAIL_ITEM_NONE : code); /* wide-operands-reviewed: <= 254 */
    if (code != 0u) {
        m->item_consumed = 0u;
    }
    if (code == 1u + DFI_ITEM_CHOICESCARF && ((uint32_t)pos->flags & DFI_VOL_CHOICE_LOCK) != 0u) {
        pos->flags = (uint8_t)((uint32_t)pos->flags & ~(uint32_t)DFI_VOL_CHOICE_LOCK); /* wide-operands-reviewed */
        if (pos->charge_turns == 0u) {
            pos->locked_move = 0u;
        }
    }
}

/* `-item|X|Item|[from] move: M[|[of] Y]`: ITEM_START (the cause MOVE, id the move, id2 the item + 1, other the Pokemon it
 * came from). */
static void dfi_emit_item_received(dfi_run *r, uint32_t flat, uint32_t code, uint32_t move_id, uint32_t from)
{
    duoforge_event e = dfi_ev(DUOFORGE_EVENT_ITEM_START, flat, DUOFORGE_CAUSE_MOVE, code, from);
    e.id = (uint16_t)move_id;
    dfi_emit(r, &e);
}

/* The silent `-enditem|X|Item|[silent]|[from] move: M[|[of] Y]` of an item that left: ITEM_END, ITEM_TAKEN. */
static void dfi_emit_item_left(dfi_run *r, uint32_t flat, uint32_t code, uint32_t move_id, uint32_t to)
{
    duoforge_event e = dfi_ev(DUOFORGE_EVENT_ITEM_END, flat, DUOFORGE_CAUSE_ITEM_TAKEN, code, to);
    e.id = (uint16_t)move_id;
    dfi_emit(r, &e);
}

/* The item's Start after setItem (sim/pokemon.ts:1885-1887) where it prints a line: Air Balloon's onStart (data/items.ts:191-195)
 * shows the balloon, ITEM_SHOWN, before the line of the move or ability that gave it (issue 520). It prints nothing while Gravity is
 * up (`!this.field.getPseudoWeather('gravity')`, the check of the switch-in line in dfi_switch_in). Klutz, Embargo and Magic Room
 * are not marked, so the holder never ignores the item here. An item whose Start uses it up is refused before
 * (dfi_start_uses_item). */
static void dfi_item_start_shown(dfi_run *r, uint32_t flat)
{
    const dfi_member *m = dfi_at(r->b, flat);
    if (m != NULL && m->hp != 0u && dfi_holds(r->b, m, DFI_ITEM_AIRBALLOON) && r->b->tail.gravity_turns == 0u) {
        const duoforge_event shown = dfi_ev(DUOFORGE_EVENT_ITEM_SHOWN, flat, DUOFORGE_CAUSE_NONE, 1u + DFI_ITEM_AIRBALLOON,
                                            DUOFORGE_NO_POSITION);
        dfi_emit(r, &shown);
    }
}

/* Symbiosis (step G69, data/abilities.ts:4837-4856, onAllyAfterUseItem). `flat` is the Pokemon that has just used its item (useItem
 * or eatItem: AfterUseItem, from dfi_use_item_of, dfi_use_item and the berries of dfi_update and dfi_lum_berry; not Bug Bite, which
 * never runs AfterUseItem); its ally, the other position of its side, is the holder (`source` of the pin). In the pin's order:
 *   1. `pokemon.switchFlag` (an Eject Button sets it before its useItem, items.ts:1692-1694): nothing. The engine sets the flag
 *      first too (dfi_turn_run's Eject Button branch), so the flag is up here.
 *   2. `source.takeItem()` (sim/pokemon.ts:1851-1866): the holder must be alive and hold an item, and the item's own TakeItem
 *      refuses a Mega Stone of the holder's species (dfi_item_takeable). A holder has Symbiosis as its one ability, so no Sticky
 *      Hold stands on it and nothing else of its TakeItem applies.
 *   3. singleEvent TakeItem with the USER as its second argument (sim/battle.ts:571-660, the handler gets (item, target, source)):
 *      a Mega Stone of the user's species is refused (dfi_stone_refused_for). A refusal at 2 or 3 changes nothing, and the pin
 *      gives the item back to the holder without a line.
 *   4. `pokemon.setItem(item)` (sim/pokemon.ts:1868-1890): the user must be alive and on the field. setItem overwrites whatever
 *      the user holds; the user of useItem or eatItem has used its item up, so it holds none here (the engine's guard for a held
 *      item is defensive and E_UNSUPPORTED). The item's Start runs at once: a White Herb with a lowered stat, a terrain seed under
 *      its terrain (dfi_start_uses_item), refused as well.
 * On success: `-activate|holder|ability: Symbiosis|Item|[of] user` (no item line, no -enditem). The event is ACTIVATE with the cause
 * ABILITY, id2 = Symbiosis + 1, position the holder, other the user ([of]), id = the item + 1 (see ACTIVATE in duoforge.h). The
 * holder's item is none and the user's is the item (dfi_set_held, the Choice lock of a Scarf's rule included). The user's Unburden
 * is read from its item (the speed rule, line ~548), so its volatile needs no change. pendingStaleness (setItem's restorative-berry
 * staleness, Trick and Switcheroo only in the pin's own test) has no observable effect here and is not modelled. */
static void dfi_symbiosis(dfi_run *r, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    const uint32_t holder = flat ^ 1u; /* the other position of the same side */
    const dfi_member *hm = dfi_at(b, holder);
    const dfi_member *um = dfi_at(b, flat);
    if (hm == NULL || um == NULL || hm->hp == 0u || um->hp == 0u || !dfi_ability(b, hm, DFI_ABILITY_SYMBIOSIS)) {
        return;
    }
    if (dfi_pos(b, flat)->switch_flag != 0u) {
        return; /* pokemon.switchFlag */
    }
    const uint32_t code = dfi_item_code(b, hm);
    if (code == 0u || !dfi_item_takeable(b, hm) || dfi_stone_refused_for(um, code)) {
        return; /* nothing held, the holder's own stone, or the user's stone: no change, no line */
    }
    if (dfi_item_code(b, um) != 0u) {
        r->deferred = DUOFORGE_E_UNSUPPORTED; /* defensive: setItem would overwrite a held item silently; never reached (used up) */
        return;
    }
    if (dfi_start_uses_item(b, flat, code)) {
        r->deferred = DUOFORGE_E_UNSUPPORTED; /* the item's Start would use it at once: decided before anything changes */
        return;
    }
    dfi_set_held(b, holder, 0u);
    dfi_set_held(b, flat, code);
    dfi_item_start_shown(r, flat); /* setItem's Start comes before the -activate line (data/abilities.ts symbiosis) */
    duoforge_event act = dfi_ev(DUOFORGE_EVENT_ACTIVATE, holder, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_SYMBIOSIS, flat);
    act.id = (uint16_t)code; /* the item + 1 */
    dfi_emit(r, &act); /* -activate|holder|ability: Symbiosis|Item|[of] user */
}

static duoforge_status dfi_skill_swap(dfi_run *r, uint32_t user, uint32_t target, uint32_t move_id, bool *did);

/* Trick's and Switcheroo's onHit for one target (`did` is whether the move did something: a failure prints -fail and stops
 * the hit loop's end). `lines_move` is the move whose name the `[from] move:` attributes carry: the move itself. */
static duoforge_status dfi_trick(dfi_run *r, uint32_t user, uint32_t target, uint32_t move_id, bool *did)
{
    struct duoforge_battle *b = r->b;
    const dfi_member *um = dfi_at(b, user);
    const dfi_member *tm = dfi_at(b, target);
    *did = false;
    if (um == NULL || tm == NULL) {
        return DUOFORGE_E_INVARIANT;
    }
    const uint32_t yours = dfi_item_code(b, tm); /* target.takeItem(source) first */
    const uint32_t mine = dfi_item_code(b, um);  /* then source.takeItem() */
    const bool refused = (yours != 0u && !dfi_item_takeable(b, tm)) || (mine != 0u && !dfi_item_takeable(b, um));
    const bool fails = refused || (yours == 0u && mine == 0u) || (mine != 0u && dfi_stone_refused_for(tm, mine)) ||
                       (yours != 0u && dfi_stone_refused_for(um, yours));
    if (!fails && ((mine != 0u && dfi_start_uses_item(b, target, mine)) ||
                   (yours != 0u && dfi_start_uses_item(b, user, yours)))) {
        return DUOFORGE_E_UNSUPPORTED; /* decided before anything changes */
    }
    if (yours != 0u) {
        dfi_unburden_on_take(b, target); /* the TakeItem handlers ran, whatever came of them */
    }
    if (mine != 0u) {
        dfi_unburden_on_take(b, user);
    }
    if (fails) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    const duoforge_event act = dfi_ev(DUOFORGE_EVENT_ACTIVATE, user, DUOFORGE_CAUSE_MOVE, DFI_MOVE_TRICK, DUOFORGE_NO_POSITION);
    dfi_emit(r, &act); /* -activate|user|move: Trick|[of] target (Switcheroo prints Trick as well) */
    dfi_set_held(b, target, mine);
    if (mine != 0u) {
        dfi_item_start_shown(r, target); /* target.setItem(myItem) runs the item's Start before the -item line */
        dfi_emit_item_received(r, target, mine, move_id, DUOFORGE_NO_POSITION);
    } else {
        dfi_emit_item_left(r, target, yours, move_id, DUOFORGE_NO_POSITION);
    }
    dfi_set_held(b, user, yours);
    if (yours != 0u) {
        dfi_item_start_shown(r, user); /* source.setItem(yourItem): the same */
        dfi_emit_item_received(r, user, yours, move_id, DUOFORGE_NO_POSITION);
    } else {
        dfi_emit_item_left(r, user, mine, move_id, DUOFORGE_NO_POSITION);
    }
    *did = true;
    return DUOFORGE_OK;
}

/* Thief's and Covet's onAfterHit for one damaged target (`silent_enditem`: Thief's extra line). */
static duoforge_status dfi_thief(dfi_run *r, uint32_t user, uint32_t target, uint32_t move_id, bool silent_enditem)
{
    struct duoforge_battle *b = r->b;
    const dfi_member *um = dfi_at(b, user);
    const dfi_member *tm = dfi_at(b, target);
    if (um == NULL || tm == NULL || dfi_item_code(b, um) != 0u) {
        return DUOFORGE_OK; /* source.item: nothing to do */
    }
    const uint32_t yours = dfi_item_code(b, tm);
    if (yours == 0u) {
        return DUOFORGE_OK; /* takeItem answers undefined */
    }
    if (tm->hp != 0u && dfi_ability(b, tm, DFI_ABILITY_STICKYHOLD)) {
        const duoforge_event block = dfi_ev(DUOFORGE_EVENT_ACTIVATE, target, DUOFORGE_CAUSE_ABILITY,
                                            1u + DFI_ABILITY_STICKYHOLD, DUOFORGE_NO_POSITION);
        dfi_emit(r, &block); /* [-activate] ability: Sticky Hold, from another Pokemon's takeItem */
        return DUOFORGE_OK;
    }
    const bool transfers = dfi_item_takeable(b, tm) && !dfi_stone_refused_for(um, yours) && um->hp != 0u;
    if (transfers && dfi_start_uses_item(b, user, yours)) {
        return DUOFORGE_E_UNSUPPORTED; /* decided before anything changes */
    }
    dfi_unburden_on_take(b, target); /* takeItem's TakeItem event, also when the item then stays or goes back */
    if (!transfers) {
        return DUOFORGE_OK;
    }
    dfi_set_held(b, target, 0u);
    dfi_set_held(b, user, yours);
    dfi_item_start_shown(r, user); /* source.setItem(yourItem) comes before Thief's and Covet's lines */
    if (silent_enditem) {
        dfi_emit_item_left(r, target, yours, move_id, user);
    }
    dfi_emit_item_received(r, user, yours, move_id, target);
    return DUOFORGE_OK;
}



/* Battle.speedSort (sim/battle.ts) over handlers that differ only by their
 * holder's speed: a selection sort, faster first, that shuffles each group
 * of equal speeds in place, one draw per step (PRNG.shuffle). `list` holds
 * flat positions in the order the reference collected the handlers. */
static duoforge_status dfi_speed_shuffle(dfi_run *r, uint32_t list[DFI_POSITIONS], uint32_t n)
{
    uint32_t sorted = 0u;
    while (sorted + 1u < n) {
        uint32_t next[DFI_POSITIONS] = {0u, 0u, 0u, 0u};
        uint32_t count = 1u;
        next[0] = sorted;
        for (uint32_t i = sorted + 1u; i < n; ++i) {
            const uint32_t best = r->speed_seen[list[next[0]]];
            const uint32_t speed = r->speed_seen[list[i]];
            if (speed > best) {
                next[0] = i;
                count = 1u;
            } else if (speed == best) {
                next[count] = i;
                count += 1u;
            }
        }
        for (uint32_t i = 0u; i < count; ++i) {
            if (next[i] != sorted + i) {
                const uint32_t e = list[sorted + i];
                list[sorted + i] = list[next[i]];
                list[next[i]] = e;
            }
        }
        for (uint32_t start = sorted; start + 1u < sorted + count; ++start) {
            uint32_t v = 0u;
            const duoforge_status st = dfi_draw(r->draws, DFI_SITE_SPEED_TIE, start - sorted, count, &v);
            if (st != DUOFORGE_OK) {
                return st;
            }
            if (sorted + v != start) {
                const uint32_t e = list[start];
                list[start] = list[sorted + v];
                list[sorted + v] = e;
            }
        }
        sorted += count;
    }
    return DUOFORGE_OK;
}


/* White Herb's onAnyAfterMove and onAnyAfterMega (Team C), the only
 * handlers of these events in the data. runEvent collects them from the
 * holders of the user's side, then of the foe side, each in slot order
 * (sim/battle.ts:1053-1063); speedSort orders them, shuffling equal speeds;
 * then each holder's check runs. `user`: the Pokemon whose event it is. */
static duoforge_status dfi_herb_event(dfi_run *r, uint32_t user)
{
    uint32_t list[DFI_POSITIONS] = {0u, 0u, 0u, 0u};
    uint32_t n = 0u;
    for (uint32_t k = 0u; k < DFI_POSITIONS; ++k) {
        const uint32_t flat = (user / 2u * 2u + k) % DFI_POSITIONS;
        if (dfi_herb_holder(r->b, flat)) {
            list[n] = flat;
            n += 1u;
        }
    }
    const duoforge_status st = dfi_speed_shuffle(r, list, n);
    if (st != DUOFORGE_OK) {
        return st;
    }
    for (uint32_t i = 0u; i < n; ++i) {
        dfi_white_herb(r, list[i], dfi_use_item);
    }
    return DUOFORGE_OK;
}

/* Whether White Herb's Any handlers would do anything: a herb due, or two
 * holders at one speed (a shuffle draw). */
static bool dfi_herbs_matter(dfi_run *r)
{
    for (uint32_t a = 0u; a < DFI_POSITIONS; ++a) {
        if (!dfi_herb_holder(r->b, a)) {
            continue;
        }
        if (dfi_herb_due(r->b, a)) {
            return true;
        }
        for (uint32_t c = a + 1u; c < DFI_POSITIONS; ++c) {
            if (dfi_herb_holder(r->b, c) && r->speed_seen[a] == r->speed_seen[c]) {
                return true;
            }
        }
    }
    return false;
}

/* heal(): at least 1, nothing at full HP, not above the maximum
 * ([-heal] with its cause). */
/* Heal Block (POOL kinds; the tail is zero elsewhere): onTryHeal returns false for every heal of the holder, and
 * Sitrus Berry's onTryEatItem asks the same event, so the berry is not eaten (data/moves.ts:8273-8347 healblock
 * onTryHeal, data/items.ts:5757-5759, sim/pokemon.ts:1779-1782). */
static bool dfi_heal_blocked(const struct duoforge_battle *b, uint32_t flat)
{
    return b->tail.sides[flat / 2u].positions[flat % 2u].heal_block_turns != 0u;
}

/* addVolatile('throatchop') on a standing target without it: no onRestart, so a second hit changes nothing; its
 * -start line is [silent]. */
static void dfi_add_lockout(dfi_run *r, uint32_t flat)
{
    const dfi_member *m = dfi_at(r->b, flat);
    dfi_tail_pos *tail = &r->b->tail.sides[flat / 2u].positions[flat % 2u];
    if (m == NULL || m->hp == 0u || tail->throat_chop_turns != 0u) {
        return;
    }
    tail->throat_chop_turns = (uint8_t)DFI_TAIL_THROAT_CHOP_MAX;
}

/* addVolatile('healblock') from Psychic Noise on a standing target: -start|X|move: Heal Block. A target that has
 * it keeps it (onRestart returns at once for Psychic Noise: no refresh, no line). */
static void dfi_add_heal_block(dfi_run *r, uint32_t flat)
{
    const dfi_member *m = dfi_at(r->b, flat);
    dfi_tail_pos *tail = &r->b->tail.sides[flat / 2u].positions[flat % 2u];
    if (m == NULL || m->hp == 0u || tail->heal_block_turns != 0u) {
        return;
    }
    tail->heal_block_turns = (uint8_t)DFI_HEAL_BLOCK_PSYCHIC_NOISE_TURNS;
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_VOLATILE_START, flat);
    e.detail = (uint8_t)DUOFORGE_VOLATILE_HEAL_BLOCK;
    dfi_emit(r, &e);
}

/* Imprison (step G38, data/moves.ts:9489-9523): the foes of a Pokemon that has used it may not use a move that it knows. The
 * pin's onFoeBeforeMove (priority 4) stops such a move at the BeforeMove event, with `cant|X|move: Imprison|Move`, unless it
 * is Struggle (the user's `hasMove` reads its current move slots: the sheet's). An imprisoner that has fainted or left has
 * lost the volatile with the occupant (the tail's flag goes with it). */
static bool dfi_imprison_forbids(struct duoforge_battle *b, uint32_t user, uint32_t move_id)
{
    if (move_id == DFI_MOVE_STRUGGLE) {
        return false;
    }
    const uint32_t foe = 1u - user / 2u;
    for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
        const dfi_member *im = dfi_at(b, foe * 2u + slot);
        if (im == NULL || im->hp == 0u || b->tail.sides[foe].positions[slot].imprison == 0u) {
            continue;
        }
        for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS && k < im->move_count; ++k) {
            if (im->moves[k].move_id == move_id) {
                return true;
            }
        }
    }
    return false;
}

/* Destiny Bond's volatile ends with the user's next move attempt (step G76, decision 0015 5cg): the pin's onBeforeMove
 * removes it for every move but Destiny Bond itself (data/moves.ts:3505-3516, priority -1, after the other BeforeMove
 * handlers), and onMoveAborted removes it when a BeforeMove stops the attempt (:3517-3519). So an attempt ends it unless
 * Destiny Bond is the move that goes on; that one is judged at its PrepareHit (dfi_run_destiny_bond). Called after
 * dfi_before_move with its `can`. */
static duoforge_status dfi_status_hit_end(dfi_run *r); /* defined with the status moves, below */

static void dfi_destiny_bond_attempt(dfi_run *r, uint32_t user, uint32_t move_id, bool can)
{
    if (can && move_id == DFI_MOVE_DESTINYBOND) {
        return;
    }
    dfi_tail_pos *tail = &r->b->tail.sides[user / 2u].positions[user % 2u];
    tail->position_flags = (uint8_t)((uint32_t)tail->position_flags & ~(uint32_t)DFI_POSFLAG_DESTINY_BOND); /* wide-operands-reviewed */
}

/* Destiny Bond itself (the status move, target self; data/moves.ts:3482-3500). Its PrepareHit fails the move while the
 * volatile is up: removeVolatile returns true, so the volatile ends too (`-fail|user` with [still]). Otherwise the volatile
 * starts with its onStart line, -singlemove|user|Destiny Bond (SINGLE_TURN, id: the move, decision 0015 5cg). */
static duoforge_status dfi_run_destiny_bond(dfi_run *r, uint32_t user, uint32_t move_id)
{
    dfi_tail_pos *tail = &r->b->tail.sides[user / 2u].positions[user % 2u];
    if ((tail->position_flags & DFI_POSFLAG_DESTINY_BOND) != 0u) {
        tail->position_flags = (uint8_t)((uint32_t)tail->position_flags & ~(uint32_t)DFI_POSFLAG_DESTINY_BOND); /* wide-operands-reviewed */
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    tail->position_flags = (uint8_t)((uint32_t)tail->position_flags | DFI_POSFLAG_DESTINY_BOND); /* wide-operands-reviewed */
    duoforge_event e = dfi_ev(DUOFORGE_EVENT_SINGLE_TURN, user, DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION);
    e.id = (uint16_t)move_id;
    dfi_emit(r, &e); /* [-singlemove] user|Destiny Bond */
    /* A successful use goes through the Champions hit loop (scripts.ts:537, 574, via hitStepMoveHitLoop): its Update, the
     * faint lines, then its Update, as a status move that applied (dfi_status_hit_end). A refused use (PrepareHit, above)
     * stops before the loop and has none. */
    return dfi_status_hit_end(r);
}

/* Imprison itself (the status move, target self): addVolatile('imprison'); a Pokemon that has it already fails
 * (`-fail`, the move line with [still]); otherwise `-start|user|move: Imprison` (the condition's onStart). The volatile is
 * added, so the hit returns true and the Champions hit loop runs its two Updates (data/mods/champions/scripts.ts:537, :574;
 * data/moves.ts:9488-9506, bypasssub): dfi_status_hit_end sets the TRUE result. */
static duoforge_status dfi_run_imprison(dfi_run *r, uint32_t user)
{
    dfi_tail_pos *tail = &r->b->tail.sides[user / 2u].positions[user % 2u];
    if (tail->imprison != 0u) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    tail->imprison = 1u;
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_VOLATILE_START, user);
    e.detail = (uint8_t)DUOFORGE_VOLATILE_IMPRISON;
    dfi_emit(r, &e); /* [-start] move: Imprison */
    return dfi_status_hit_end(r);
}

static void dfi_heal(dfi_run *r, uint32_t flat, uint32_t amount, uint32_t cause, uint32_t id2, uint32_t other)
{
    struct duoforge_battle *b = r->b;
    dfi_member *m = dfi_at(b, flat);
    if (m == NULL || m->hp == 0u || m->hp >= m->hp_max || dfi_heal_blocked(b, flat)) {
        return;
    }
    const uint32_t hp = (uint32_t)m->hp + (amount == 0u ? 1u : amount);
    m->hp = (uint16_t)(hp > m->hp_max ? m->hp_max : hp); /* wide-operands-reviewed: <= hp_max */
    dfi_emit_hp(r, dfi_ev(DUOFORGE_EVENT_HEAL, flat, cause, id2, other));
}

/* Sturdy's onDamage (step G39, data/abilities.ts:4673-4691, priority -30, so before Focus Sash's -40): a Move's damage that
 * would take all of a full-HP holder's HP is -ability|holder|Sturdy and leaves 1 HP. The damage of a Move is a move hit and
 * the confusion hit (effectType 'Move', as for the Sash, combat/items/families.h); recoil, items, status and weather are not.
 * Its onTryHit makes the holder immune to OHKO moves: none is modelled (the generator refuses the field), which
 * tests/abilities/test_damp_sturdy_rows.c pins. The ability is breakable: Mold Breaker is not marked. */
static bool dfi_sturdy_saves(dfi_run *r, uint32_t flat, uint32_t *damage)
{
    const dfi_member *tm = dfi_at(r->b, flat);
    if (tm == NULL || !dfi_ability(r->b, tm, DFI_ABILITY_STURDY) || tm->hp != tm->hp_max || *damage < tm->hp) {
        return false;
    }
    const duoforge_event e = dfi_ev(DUOFORGE_EVENT_ABILITY, flat, DUOFORGE_CAUSE_NONE, 1u + DFI_ABILITY_STURDY,
                                    DUOFORGE_NO_POSITION);
    dfi_emit(r, &e); /* [-ability] holder|Sturdy */
    *damage = (uint32_t)tm->hp - 1u;
    return true;
}

/* eachEvent's order (sim/battle.ts:462-476): the active Pokemon that have
 * not fainted (a faint counts once it is processed or announced), in slot
 * order, sorted by their last speed with Battle.speedSort; a tie is
 * shuffled. Each holder acts only on itself, so a tie decides only the
 * order of the lines of two Pokemon with a handler of the event
 * (`bearers`, by flat position): only such a group draws (decision 0007
 * section 6; the converter keeps exactly those draws). */
static duoforge_status dfi_each_order(dfi_run *r, uint32_t bearers, uint32_t list[DFI_POSITIONS], uint32_t *count)
{
    uint32_t n = 0u;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        const dfi_member *m = dfi_at(r->b, flat);
        if (m == NULL) {
            continue;
        }
        bool listed = m->hp != 0u;
        for (uint32_t i = r->faint_announced; i < r->faint_count; ++i) {
            listed = listed || r->faint_queue[i] == flat; /* its faint is not processed yet */
        }
        if (listed) {
            list[n] = flat;
            n += 1u;
        }
    }
    *count = n;
    uint32_t sorted = 0u;
    while (sorted + 1u < n) {
        uint32_t next[DFI_POSITIONS] = {0u, 0u, 0u, 0u};
        uint32_t ties = 1u;
        next[0] = sorted;
        for (uint32_t i = sorted + 1u; i < n; ++i) {
            const uint32_t best = r->speed_seen[list[next[0]]];
            const uint32_t speed = r->speed_seen[list[i]];
            if (speed > best) {
                next[0] = i;
                ties = 1u;
            } else if (speed == best) {
                next[ties] = i;
                ties += 1u;
            }
        }
        uint32_t held = 0u;
        for (uint32_t i = 0u; i < ties; ++i) {
            held += (bearers >> list[next[i]]) & 1u;
        }
        for (uint32_t i = 0u; i < ties; ++i) {
            if (next[i] != sorted + i) {
                const uint32_t e = list[sorted + i];
                list[sorted + i] = list[next[i]];
                list[next[i]] = e;
            }
        }
        for (uint32_t start = sorted; start + 1u < sorted + ties && held >= 2u; ++start) {
            uint32_t v = 0u;
            const duoforge_status st = dfi_draw(r->draws, DFI_SITE_SPEED_TIE, start - sorted, ties, &v);
            if (st != DUOFORGE_OK) {
                return st;
            }
            if (sorted + v != start) {
                const uint32_t e = list[start];
                list[start] = list[sorted + v];
                list[sorted + v] = e;
            }
        }
        sorted += ties;
    }
    return DUOFORGE_OK;
}

/* eachEvent('Update'): Sitrus Berry eats at half HP or less and heals a
 * quarter, holder by holder in eachEvent's order. */
/* Step G71 (decision 0034): the source member of an Attract byte (1 + side * 6 + roster index) is on the field and not fainted: the
 * pin's source.isActive (data/moves.ts:722-727). A member that switched out and came back is a new entry, but the infatuation ended
 * at the first Update after its switch-out, so the check reads the member, not the position. */
static bool dfi_faint_shown(const dfi_run *r, uint32_t flat);

static bool dfi_attract_source_active(const dfi_run *r, uint32_t code)
{
    /* The pin's isActive is false from the faintMessages that shows the faint (sim/battle.ts:2566), and true until then: a source at
     * 0 HP whose faint is queued but not yet shown is still active at the Update before that faintMessages (the in-move hit loop's
     * Update), and inactive at the Update after it (the post-announce Update, step G71 trace of seed 9720000_2 step 25). */
    const struct duoforge_battle *b = r->b;
    const uint32_t side = (code - 1u) / DUOFORGE_MAX_ROSTER;
    const uint32_t src = (code - 1u) % DUOFORGE_MAX_ROSTER;
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        if (b->sides[side].positions[p].occupant != src) {
            continue;
        }
        if (b->sides[side].members[src].hp != 0u) {
            return true;
        }
        const uint32_t flat = side * DUOFORGE_ACTIVE_PER_SIDE + p;
        if (dfi_faint_shown(r, flat)) {
            return false;
        }
        for (uint32_t i = 0u; i < r->faint_count; ++i) {
            if (r->faint_queue[i] == flat) {
                return true;
            }
        }
        return false;
    }
    return false;
}

/* Step G71 (decision 0034): the volatile's onUpdate and the attract half of Oblivious's onUpdate, for the holder at flat (pin order:
 * the volatile first, then the ability, then the item; sim/battle.ts:1107-1130). A source that is not active ends the infatuation
 * silently: state only, no event (decision 0015 5bn, the Yawn precedent). Oblivious's holder (its ability now, a Skill Swap or
 * a Trace copy included) prints -activate|X|ability: Oblivious, ends the infatuation silently and prints the visible
 * -end|X|move: Attract|[from] ability: Oblivious. */
static duoforge_status dfi_attract_update(dfi_run *r, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    const uint8_t code = b->tail.attract_source[flat];
    const dfi_member *m = dfi_at(b, flat);
    if (code == 0u) {
        return DUOFORGE_OK;
    }
    if (m == NULL || m->hp == 0u || !dfi_attract_source_active(r, code)) {
        b->tail.attract_source[flat] = 0u; /* silent end: the source left the field */
        return DUOFORGE_OK;
    }
    if (dfi_ability(b, m, DFI_ABILITY_OBLIVIOUS)) {
        duoforge_event act = dfi_ev(DUOFORGE_EVENT_ACTIVATE, flat, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_OBLIVIOUS,
                                    DUOFORGE_NO_POSITION);
        dfi_emit(r, &act); /* -activate|X|ability: Oblivious */
        b->tail.attract_source[flat] = 0u; /* the pin's removeVolatile: its -end is [silent] */
        duoforge_event end = dfi_ev(DUOFORGE_EVENT_VOLATILE_END, flat, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_OBLIVIOUS,
                                    DUOFORGE_NO_POSITION);
        end.detail = DUOFORGE_VOLATILE_ATTRACT;
        dfi_emit(r, &end); /* -end|X|move: Attract|[from] ability: Oblivious */
    }
    return DUOFORGE_OK;
}

static duoforge_status dfi_update(dfi_run *r)
{
    uint32_t bearers = 0u;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        /* the holders with an Update handler that can act: Sitrus Berry, and step G47's Lum Berry and Mental Herb; step G71: an
         * infatuated occupant that is also Oblivious (its cure prints lines, so its order shows; the converter's each-tie rule, the
         * same as this set). An Attract holder without Oblivious is inert in the order (its source-left removal is silent) and
         * draws no tie order: dfi_attract_update below still ends it. */
        const bool oblivious_infatuated = r->b->tail.attract_source[flat] != 0u &&
                                          dfi_ability(r->b, dfi_at(r->b, flat), DFI_ABILITY_OBLIVIOUS);
        const bool bears = dfi_holds(r->b, dfi_at(r->b, flat), DFI_ITEM_SITRUSBERRY) ||
                           dfi_holds(r->b, dfi_at(r->b, flat), DFI_ITEM_LUMBERRY) ||
                           dfi_holds(r->b, dfi_at(r->b, flat), DFI_ITEM_MENTALHERB) || oblivious_infatuated;
        bearers |= bears ? 1u << flat : 0u;
    }
    /* the inert infatuated holders: their silent end is state only, and nothing else reads it in this update */
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        if (r->b->tail.attract_source[flat] != 0u && ((bearers >> flat) & 1u) == 0u) {
            const duoforge_status inert = dfi_attract_update(r, flat);
            if (inert != DUOFORGE_OK) {
                return inert;
            }
        }
    }
    if (bearers == 0u) {
        return DUOFORGE_OK;
    }
    uint32_t list[DFI_POSITIONS] = {0u, 0u, 0u, 0u};
    uint32_t n = 0u;
    const duoforge_status st = dfi_each_order(r, bearers, list, &n);
    if (st != DUOFORGE_OK) {
        return st;
    }
    for (uint32_t i = 0u; i < n; ++i) {
        const uint32_t flat = list[i];
        /* step G71: the volatile's and the ability's Update handlers come before the item's (sim/battle.ts:1107-1130) */
        const duoforge_status attract = dfi_attract_update(r, flat);
        if (attract != DUOFORGE_OK) {
            return attract;
        }
        const dfi_member *m = dfi_at(r->b, flat);
        if (m->hp != 0u && dfi_holds(r->b, m, DFI_ITEM_SITRUSBERRY) && (uint32_t)m->hp * 2u <= m->hp_max &&
            !dfi_heal_blocked(r->b, flat) && !dfi_unnerved(r->b, flat)) {
            dfi_use_item_core(r, flat, DUOFORGE_NO_POSITION);
            dfi_heal(r, flat, (uint32_t)m->hp_max / 4u, DUOFORGE_CAUSE_ITEM, 1u + DFI_ITEM_SITRUSBERRY,
                     DUOFORGE_NO_POSITION);
            dfi_symbiosis(r, flat); /* eatItem: Eat (the heal), then AfterUseItem (step G69) */
        }
        /* Lum Berry's onUpdate (data/items.ts:3548-3552): a status or a confusion of its holder is eaten (dfi_lum_berry asks
         * Unnerve); Mental Herb's (data/items.ts:3906-3918) cures the holder's volatiles (dfi_mental_herb). One item per holder,
         * so the two never meet on one Pokemon. */
        const dfi_active_slot *pos = dfi_pos(r->b, flat);
        if (m->hp != 0u && dfi_holds(r->b, m, DFI_ITEM_LUMBERRY) && (m->status != DFI_STATUS_NONE || pos->confusion_turns != 0u)) {
            const duoforge_status lum = dfi_lum_berry(r, flat);
            if (lum != DUOFORGE_OK) {
                return lum;
            }
        }
        const duoforge_status herb = dfi_mental_herb(r, flat);
        if (herb != DUOFORGE_OK) {
            return herb;
        }
    }
    return DUOFORGE_OK;
}

/* runStatusImmunity('sandstorm'): a type whose chart entry carries the sandstorm key, Rock, Ground and Steel
 * (data/typechart.ts), judged by the types now (dfi_types_of: a Soaked Pokemon is a Water type alone, step G11), or the
 * ability that gives the immunity: Sand Rush (step G22, data/abilities.ts:3980-3982, onImmunity 'sandstorm' returns
 * false; the Champions mod has no entry), Overcoat (step G30, data/abilities.ts:3108-3111) and Sand Force (step G63). The
 * others that give it (Safety Goggles) or stop indirect damage (Magic Guard) are not marked in the support manifest,
 * so no battle holds one (tests/mechanics/test_sand_snow_weather.c checks that); marking one needs its immunity here. */
static bool dfi_sand_immune(const struct duoforge_battle *b, const dfi_member *m)
{
    if (dfi_ability(b, m, DFI_ABILITY_SANDRUSH) || dfi_ability(b, m, DFI_ABILITY_OVERCOAT) ||
        dfi_ability(b, m, DFI_ABILITY_SANDVEIL) ||
        dfi_ability(b, m, DFI_ABILITY_SANDFORCE)) { /* Sand Veil: step G39, data/abilities.ts:4006-4022, onImmunity 'sandstorm';
                                                       Sand Force (step G63, data/abilities.ts:3956-3973) the same */
        return true;
    }
    for (uint32_t type = 0u; type < DFI_TYPE_COUNT; ++type) {
        if ((dfi_pool_type_immunity[type] & DFI_IMMUNE_SAND) != 0u && dfi_has_type(b, m, type)) {
            return true;
        }
    }
    return false;
}

/* eachEvent('Weather') under Sandstorm (sim/battle.ts:465-476, the onWeather of data/conditions.ts:659-661): every
 * active Pokemon that has not fainted, in eachEvent's order, takes baseMaxhp / 16 (at least 1) as [-damage]
 * [from] Sandstorm unless it is immune (Battle.spreadDamage, sim/battle.ts: a Weather effect on a target that fails
 * runStatusImmunity does no damage). Every active has the handler, so a tie between two Pokemon that both take
 * damage shows in the order of their lines and is drawn (the group is shuffled as a whole, the converter keeps the
 * draws of such a group, see trace_to_c.py drop_reason); a tie with an immune Pokemon changes nothing. The faints
 * wait for the end of the residual handler. */
static duoforge_status dfi_sand_damage(dfi_run *r)
{
    uint32_t bearers = 0u;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        const dfi_member *m = dfi_at(r->b, flat);
        /* the Pokemon that take the Sandstorm damage: alive, not sand-immune and not a Magic Guard holder (decision 0015 5bl) */
        if (m != NULL && m->hp != 0u && !dfi_sand_immune(r->b, m) && !dfi_magic_guard_blocks(r->b, m, DFI_DMG_WEATHER)) {
            bearers |= 1u << flat;
        }
    }
    if (bearers == 0u) {
        return DUOFORGE_OK;
    }
    uint32_t list[DFI_POSITIONS] = {0u, 0u, 0u, 0u};
    uint32_t n = 0u;
    duoforge_status st = dfi_each_order(r, bearers, list, &n);
    if (st != DUOFORGE_OK) {
        return st;
    }
    for (uint32_t i = 0u; i < n; ++i) {
        const uint32_t flat = list[i];
        const dfi_member *m = dfi_at(r->b, flat);
        if (((bearers >> flat) & 1u) == 0u || m->hp == 0u) {
            continue;
        }
        const uint32_t damage = (uint32_t)m->hp_max / 16u;
        st = dfi_deal(r, flat, damage == 0u ? 1u : damage, DUOFORGE_CAUSE_WEATHER, DFI_WEATHER_SAND,
                      DUOFORGE_NO_POSITION, DFI_DMG_WEATHER);
        if (st != DUOFORGE_OK) {
            return st;
        }
    }
    return DUOFORGE_OK;
}

/* eachEvent('Weather') under rain (step G35, the onWeather of Rain Dish, data/abilities.ts:3759-3765): every active Pokemon
 * that has not fainted and holds Rain Dish heals baseMaxhp / 16 (at least 1) as [-heal] [from] ability: Rain Dish, in
 * eachEvent's order; a full-HP holder prints nothing (Battle.heal returns early) but is still in the sort, so two holders
 * that are tied in speed draw whatever their HP (the group is shuffled as a whole; the converter keeps the draws of two
 * holders, trace_to_c.py drop_reason). Primordial Sea is not in the format. */
/* Ice Body (A2a, decision 0015 entry 5dy; data/abilities.ts:1955-1968, onWeather, no Champions entry) is the same handler under
 * snow (effect.id 'snowscape'; Hail is not in the format): `ability` is the one of the weather that is up, Rain Dish in rain
 * and Ice Body in snow. Its onImmunity('hail') has no reader (Snowscape deals no damage). */
static duoforge_status dfi_weather_heal(dfi_run *r, uint32_t ability)
{
    uint32_t bearers = 0u;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        const dfi_member *m = dfi_at(r->b, flat);
        if (m != NULL && m->hp != 0u && dfi_ability(r->b, m, ability)) {
            bearers |= 1u << flat;
        }
    }
    if (bearers == 0u) {
        return DUOFORGE_OK;
    }
    uint32_t list[DFI_POSITIONS] = {0u, 0u, 0u, 0u};
    uint32_t n = 0u;
    const duoforge_status st = dfi_each_order(r, bearers, list, &n);
    if (st != DUOFORGE_OK) {
        return st;
    }
    for (uint32_t i = 0u; i < n; ++i) {
        const uint32_t flat = list[i];
        if (((bearers >> flat) & 1u) != 0u) {
            dfi_heal(r, flat, (uint32_t)dfi_at(r->b, flat)->hp_max / 16u, DUOFORGE_CAUSE_ABILITY,
                     1u + ability, DUOFORGE_NO_POSITION);
        }
    }
    return DUOFORGE_OK;
}

/* eachEvent('Weather') under sun (step G39, the onWeather of Solar Power, data/abilities.ts:4396-4413): every active Pokemon
 * that has not fainted and holds Solar Power takes baseMaxhp / 8 (at least 1) as -damage [from] ability: Solar Power [of] the holder
 * itself (damage(..., target, target): the source is printed, the pin's line has it), in eachEvent's order; two holders at one Speed draw the order as Rain Dish's do
 * (dfi_weather_heal). Desolate Land is not a weather of the state. */
static duoforge_status dfi_solar_power(dfi_run *r)
{
    uint32_t bearers = 0u;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        const dfi_member *m = dfi_at(r->b, flat);
        if (m != NULL && m->hp != 0u && dfi_ability(r->b, m, DFI_ABILITY_SOLARPOWER)) {
            bearers |= 1u << flat;
        }
    }
    if (bearers == 0u) {
        return DUOFORGE_OK;
    }
    uint32_t list[DFI_POSITIONS] = {0u, 0u, 0u, 0u};
    uint32_t n = 0u;
    duoforge_status st = dfi_each_order(r, bearers, list, &n);
    if (st != DUOFORGE_OK) {
        return st;
    }
    for (uint32_t i = 0u; i < n; ++i) {
        const uint32_t flat = list[i];
        const dfi_member *m = dfi_at(r->b, flat);
        if (((bearers >> flat) & 1u) == 0u || m->hp == 0u) {
            continue;
        }
        const uint32_t damage = (uint32_t)m->hp_max / 8u;
        st = dfi_deal(r, flat, damage == 0u ? 1u : damage, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_SOLARPOWER, flat, DFI_DMG_ABILITY);
        if (st != DUOFORGE_OK) {
            return st;
        }
    }
    return DUOFORGE_OK;
}

/* clearVolatile of a fainted Pokemon: the occupant stays in its slot until
 * it is replaced, everything else of the position is cleared. */
static void dfi_clear_volatile(dfi_active_slot *pos)
{
    const dfi_active_slot keep = *pos;
    dfi_slot_clear(pos);
    pos->occupant = keep.occupant;
    pos->activation_id = keep.activation_id;
}

/* Brought members that have not fainted (side.pokemonLeft). */
static uint32_t dfi_left(const struct duoforge_battle *b, uint32_t side)
{
    const dfi_side *sd = &b->sides[side];
    uint32_t n = 0u;
    for (uint32_t m = 0u; m < sd->member_count && m < DUOFORGE_MAX_ROSTER; ++m) {
        if (((uint32_t)sd->brought_mask >> m & 1u) != 0u && sd->members[m].hp != 0u) {
            n += 1u;
        }
    }
    return n;
}

#include "combat/flow/faint.h"

/* Step G71 (decision 0034): the flat position of an Attract source (code = 1 + side * 6 + roster index) while the member stands on
 * the field and is not fainted; DUOFORGE_NO_POSITION otherwise (the pin's source.isActive, data/moves.ts:722-727). */
uint32_t dfi_attract_source_flat(const struct duoforge_battle *b, uint32_t code)
{
    const uint32_t side = (code - 1u) / DUOFORGE_MAX_ROSTER;
    const uint32_t src = (code - 1u) % DUOFORGE_MAX_ROSTER;
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        if (b->sides[side].positions[p].occupant == src && b->sides[side].members[src].hp != 0u) {
            return side * DUOFORGE_ACTIVE_PER_SIDE + p;
        }
    }
    return DUOFORGE_NO_POSITION;
}

/* ---------------------------------------------------------------- moves */

/* runEvent('BeforeMove') in handler priority order: sleep and freeze (10),
 * flinch (8), confusion (3), paralysis (1); the first that stops the move
 * ends the event (data/conditions.ts, data/mods/champions/conditions.ts).
 * A frozen user of a defrost move (Flare Blitz, Team C) skips the freeze
 * check: no draw, no counter (data/mods/champions/conditions.ts:47). */
static duoforge_status dfi_before_move(dfi_run *r, uint32_t user, uint32_t move_id, const dfi_move_data *md, bool *can)
{
    dfi_member *m = dfi_at(r->b, user);
    dfi_active_slot *pos = dfi_pos(r->b, user);
    duoforge_status st = DUOFORGE_OK;
    *can = false;
    /* glaiverush's onBeforeMove (data/moves.ts:6647-6678), priority 100, before every other BeforeMove handler: the
     * user's next action, whatever it is and whether or not it then moves, ends the drawback (silently). */
    r->b->tail.sides[user / 2u].positions[user % 2u].glaive_rush = 0u;
    /* mustrecharge's onBeforeMove (data/conditions.ts:367-373), priority 11, before sleep and freeze (10): whatever
     * move the action holds (the recharge turn itself, or an Encored move that replaced it), it shows cant|recharge,
     * ends the volatile and stops the move: no PP, no move line. Zero under every kind but POOL (TAIL_KIND). */
    {
        dfi_tail_pos *tail = &r->b->tail.sides[user / 2u].positions[user % 2u];
        if (tail->must_recharge != 0u) {
            tail->must_recharge = 0u;
            const duoforge_event e = dfi_ev(DUOFORGE_EVENT_CANT, user, DUOFORGE_CAUSE_RECHARGE, 0u, DUOFORGE_NO_POSITION);
            dfi_emit(r, &e); /* [cant] recharge */
            return DUOFORGE_OK;
        }
    }
    const bool defrost = m->status == DFI_STATUS_FRZ && ((uint32_t)md->flags & DFI_MOVE_FLAG_DEFROST) != 0u;
    if ((m->status == DFI_STATUS_SLP || m->status == DFI_STATUS_FRZ) && !defrost) {
        /* the count of a sleep exists under POOL only (the tail's member byte; invariant TAIL_KIND elsewhere): the other kinds keep
         * their sleep as it was */
        const bool sleep_counted = dfi_kind_limits_of(r->ctx->data_kind).pool_rules;
        if (m->status == DFI_STATUS_SLP && sleep_counted &&
            (move_id == DFI_MOVE_SLEEPTALK || move_id == DFI_MOVE_SNORE || dfi_ability_code(r->b, m) == DFI_ABILITY_EARLYBIRD + 1u)) {
            /* decision 0066 (review of the search lane): a sleeper that decrements its counter twice per attempt (Early
             * Bird, data/conditions.ts:68-69) or that runs a sleepUsable move after its cant line (Sleep Talk, Snore,
             * data/moves.ts:16875, 17161) has no counted posterior: refused, never guessed. Both are unmarked today. */
            return DUOFORGE_E_UNSUPPORTED;
        }
        const uint32_t left = m->status_counter > 0u ? (uint32_t)m->status_counter - 1u : 0u;
        bool cured = left == 0u;
        if (!cured && m->status == DFI_STATUS_FRZ) {
            st = dfi_draw_chance(r->draws, DFI_SITE_FREEZE_THAW, 1u, 4u, &cured);
            if (st != DUOFORGE_OK) {
                return st;
            }
        }
        if (!cured) {
            m->status_counter = (uint8_t)left; /* <= 2 */
            if (m->status == DFI_STATUS_SLP && sleep_counted) {
                /* decision 0066: one more cant line of this sleep (c <= 2: the start is 2 or 3 and the wake is the next attempt) */
                uint8_t *cant = &r->b->tail.sides[user / 2u].sleep_cant[pos->occupant];
                *cant = (uint8_t)(*cant + 1u); /* wide-operands-reviewed: c <= 2 by the start (2 or 3) */
            }
            const uint32_t why = m->status == DFI_STATUS_SLP ? DUOFORGE_CAUSE_SLEEP : DUOFORGE_CAUSE_FREEZE;
            const duoforge_event e = dfi_ev(DUOFORGE_EVENT_CANT, user, why, 0u, DUOFORGE_NO_POSITION);
            dfi_emit(r, &e); /* [cant] slp or frz */
            return DUOFORGE_OK;
        }
        duoforge_event cure = dfi_event_make(DUOFORGE_EVENT_CURE_STATUS, user);
        cure.detail = m->status;
        cure.flags = (uint8_t)DUOFORGE_EVENT_FLAG_MESSAGE;
        dfi_emit(r, &cure); /* [-curestatus] [msg] */
        m->status = (uint8_t)DFI_STATUS_NONE;
        m->status_counter = 0u;
        r->b->tail.sides[user / 2u].sleep_cant[pos->occupant] = 0u; /* decision 0066: the wake ends the count */
    }
    if (((uint32_t)pos->flags & DFI_VOL_FLINCH) != 0u) {
        const duoforge_event e = dfi_ev(DUOFORGE_EVENT_CANT, user, DUOFORGE_CAUSE_FLINCH, 0u, DUOFORGE_NO_POSITION);
        dfi_emit(r, &e); /* [cant] flinch */
        /* Steadfast (step G45, data/abilities.ts:4549-4557, onFlinch: this.boost({spe: 1}) with no source, so the holder is
         * its own source): the Speed of the holder rises by 1 once its flinch stopped the move, after the [cant] line. The
         * change is the ability's primary one: -ability|holder|Steadfast|boost, then -boost|holder|spe|1 (a change of 0 shows
         * nothing). Battle.boost returns at once for a fainted holder. */
        if (dfi_ability(r->b, m, DFI_ABILITY_STEADFAST)) {
            static const uint8_t spe_up[DFI_STAT_STAGE_COUNT] = {6u, 6u, 6u, 6u, 7u, 6u, 6u};
            (void)dfi_boost(r, user, spe_up, DFI_POSITIONS,
                            dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_STEADFAST, DFI_BOOST_PRIMARY));
        }
        return DUOFORGE_OK;
    }
    /* Disable's onBeforeMove (priority 7: after the flinch's 8, before Throat Chop's and Heal Block's 6; data/moves.ts:3697-3703,
     * with the Champions override data/mods/champions/moves.ts:228-238, which only adds that a move with the cantusetwice flag
     * is not stopped: no marked move has it): the move that the volatile bars shows `cant|X|Disable|move` and uses no PP. */
    {
        const dfi_tail_pos *tail = &r->b->tail.sides[user / 2u].positions[user % 2u];
        if (tail->disable_slot != 0u && dfi_move_of(m, (uint32_t)tail->disable_slot - 1u) == move_id) {
            duoforge_event e = dfi_ev(DUOFORGE_EVENT_CANT, user, DUOFORGE_CAUSE_DISABLE, 0u, DUOFORGE_NO_POSITION);
            e.id = (uint16_t)move_id;
            dfi_emit(r, &e); /* [cant] Disable|move */
            return DUOFORGE_OK;
        }
    }
    /* Throat Chop and Heal Block, both onBeforeMovePriority 6: between the flinch and the confusion (data/moves.ts:
     * 19410-19422, 8307-8313). A sound move (Throat Chop) or a move that heals (Heal Block) shows cant and uses no PP;
     * Struggle has neither flag. No move of the pool is both. */
    {
        const dfi_tail_pos *tail = &r->b->tail.sides[user / 2u].positions[user % 2u];
        const uint32_t flags2 = move_id == DFI_MOVE_STRUGGLE ? 0u : dfi_pool_move_flags2[move_id];
        if (tail->throat_chop_turns != 0u && (flags2 & DFI_MOVE_FLAG2_SOUND) != 0u) {
            const duoforge_event e = dfi_ev(DUOFORGE_EVENT_CANT, user, DUOFORGE_CAUSE_MOVE, DFI_MOVE_THROATCHOP,
                                            DUOFORGE_NO_POSITION);
            dfi_emit(r, &e); /* [cant] move: Throat Chop */
            return DUOFORGE_OK;
        }
        if (tail->heal_block_turns != 0u && (flags2 & DFI_MOVE_FLAG2_HEAL) != 0u) {
            duoforge_event e = dfi_ev(DUOFORGE_EVENT_CANT, user, DUOFORGE_CAUSE_HEAL_BLOCK, 0u, DUOFORGE_NO_POSITION);
            e.id = (uint16_t)move_id;
            dfi_emit(r, &e); /* [cant] move: Heal Block|move */
            return DUOFORGE_OK;
        }
    }
    /* Taunt's onBeforeMove (priority 5: after Throat Chop's and Heal Block's 6, before the confusion's 3;
     * data/moves.ts:19004-19010): a move of the Status category shows cant|X|move: Taunt|move and uses no PP (Me First,
     * the one exception, is not in the pool; no Z or Max move exists in the format). */
    if (r->b->tail.sides[user / 2u].positions[user % 2u].taunt_turns != 0u && md->category == DFI_CATEGORY_STATUS) {
        duoforge_event e = dfi_ev(DUOFORGE_EVENT_CANT, user, DUOFORGE_CAUSE_TAUNT, 0u, DUOFORGE_NO_POSITION);
        e.id = (uint16_t)move_id;
        dfi_emit(r, &e); /* [cant] move: Taunt|move */
        return DUOFORGE_OK;
    }
    /* A foe's Imprison (step G38, onFoeBeforeMovePriority 4, data/moves.ts:9511-9519): after Throat Chop and Heal Block (6),
     * before the confusion (3) and the paralysis (1). A move that the foe knows (a move queued before it was used, or
     * an Encored one) shows cant and uses no PP. */
    if (dfi_kind_limits_of(r->ctx->data_kind).pool_rules && dfi_imprison_forbids(r->b, user, move_id)) {
        duoforge_event e = dfi_ev(DUOFORGE_EVENT_CANT, user, DUOFORGE_CAUSE_IMPRISON, 0u, DUOFORGE_NO_POSITION);
        e.id = (uint16_t)move_id;
        dfi_emit(r, &e); /* [cant] move: Imprison|move */
        return DUOFORGE_OK;
    }
    if (pos->confusion_turns != 0u) {
        pos->confusion_turns = (uint8_t)((uint32_t)pos->confusion_turns - 1u); /* wide-operands-reviewed */
        if (pos->confusion_turns == 0u) {
            dfi_emit_plain(r, DUOFORGE_EVENT_CONFUSION_END, user); /* [-end] confusion */
        } else {
            dfi_emit_plain(r, DUOFORGE_EVENT_CONFUSED, user); /* [-activate] confusion */
            bool hit = false;
            st = dfi_draw_chance(r->draws, DFI_SITE_CONFUSION_HIT, 33u, 100u, &hit);
            if (st != DUOFORGE_OK) {
                return st;
            }
            if (hit) {
                uint32_t damage = 0u;
                st = dfi_confusion_damage(r, user, &damage);
                if (st != DUOFORGE_OK) {
                    return st;
                }
                /* The confusion hit is damage with a Move effect
                 * (data/conditions.ts:193-194): a Focus Sash holder at full
                 * HP that it would faint uses the item and keeps 1 HP. */
                (void)dfi_sturdy_saves(r, user, &damage);
                if (dfi_focus_sash_saves(dfi_item_code(r->b, m), m, damage)) {
                    dfi_use_item(r, user);
                    damage = (uint32_t)m->hp - 1u;
                }
                return dfi_deal(r, user, damage, DUOFORGE_CAUSE_CONFUSION, 0u, DUOFORGE_NO_POSITION, DFI_DMG_MOVE);
            }
        }
    }
    /* Attract (step G71, decision 0034; data/moves.ts:731-741, onBeforeMovePriority 2): after confusion (3), before paralysis (1).
     * The line -activate|X|move: Attract|[of] Y comes before the roll; randomChance(1, 2) stops the move (cant, no PP). */
    if (r->b->tail.attract_source[user] != 0u) {
        const uint32_t src = dfi_attract_source_flat(r->b, r->b->tail.attract_source[user]);
        const duoforge_event act = dfi_ev(DUOFORGE_EVENT_ACTIVATE, user, DUOFORGE_CAUSE_MOVE, DFI_MOVE_ATTRACT, src);
        dfi_emit(r, &act);
        bool stop = false;
        st = dfi_draw_chance(r->draws, DFI_SITE_ATTRACT, 1u, 2u, &stop);
        if (st != DUOFORGE_OK) {
            return st;
        }
        if (stop) {
            /* cant|X|Attract names no move (the line is the same for any move), so the id stays zero, as sleep's and freeze's */
            const duoforge_event e = dfi_ev(DUOFORGE_EVENT_CANT, user, DUOFORGE_CAUSE_ATTRACT, 0u, DUOFORGE_NO_POSITION);
            dfi_emit(r, &e); /* [cant] Attract */
            return DUOFORGE_OK;
        }
    }
    if (m->status == DFI_STATUS_PAR) {
        bool full = false;
        st = dfi_draw_chance(r->draws, DFI_SITE_FULL_PARALYSIS, 1u, 8u, &full);
        if (st != DUOFORGE_OK) {
            return st;
        }
        if (full) {
            const duoforge_event e =
                dfi_ev(DUOFORGE_EVENT_CANT, user, DUOFORGE_CAUSE_PARALYSIS, 0u, DUOFORGE_NO_POSITION);
            dfi_emit(r, &e); /* [cant] par */
            return DUOFORGE_OK;
        }
    }
    *can = true;
    return DUOFORGE_OK;
}

/* Double Shock's self effect (the pin's self onHit): the first type becomes ??? (soak_type 255), the second stays as type2, and
 * the line -start|X|typechange|???/Fighting is TYPE_CHANGE with detail DUOFORGE_TYPE_NONE and amount = the second type + 1. */
static duoforge_status dfi_double_shock_self(dfi_run *r, uint32_t user, uint32_t move_id)
{
    struct duoforge_battle *b = r->b;
    if (!dfi_double_shock_shape(b, user)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    const uint32_t occupant = dfi_pos(b, user)->occupant;
    dfi_tail_side *ts = &b->tail.sides[user / 2u];
    ts->soak_type[occupant] = DFI_TAIL_TYPE2_TYPELESS;
    ts->type2[occupant] = (uint8_t)(DFI_TYPE_FIGHTING + 1u); /* wide-operands-reviewed: < 256 */
    duoforge_event e = dfi_ev(DUOFORGE_EVENT_TYPE_CHANGE, user, DUOFORGE_CAUSE_MOVE, move_id, DUOFORGE_NO_POSITION);
    e.detail = (uint8_t)DUOFORGE_TYPE_NONE; /* the ??? slot */
    e.amount = (uint8_t)(DFI_TYPE_FIGHTING + 1u); /* the second type id + 1; wide-operands-reviewed: < 256 */
    dfi_emit(r, &e);
    return DUOFORGE_OK;
}

/* Soak's onHit (data/moves.ts:17186-17208): a target that is already pure Water, or whose type cannot be set, gives
 * -fail|target (the move still animates) and null; otherwise target.setType('Water') and -start|target|typechange|Water.
 * setType refuses (without `enforce`) Arceus and Silvally (species numbers 493 and 773, sim/pokemon.ts:2113-2118; no
 * pool forme is one) and a Terastallized Pokemon (the format has no Terastallization). The type stays until the
 * occupant leaves, faints, Mega Evolves or changes forme by Stance Change (dfi_tail_clear_occupant, dfi_run_mega,
 * dfi_stance_change). True when the type was set. */
static bool dfi_soak(dfi_run *r, uint32_t flat, uint32_t move_id)
{
    struct duoforge_battle *b = r->b;
    const dfi_member *m = dfi_at(b, flat);
    const uint32_t occupant = dfi_pos(b, flat)->occupant;
    if (m == NULL || m->hp == 0u || occupant >= DUOFORGE_MAX_ROSTER) {
        return false;
    }
    uint32_t types[2];
    dfi_types_of(b, m, types);
    const uint32_t dex = dfi_forme_of(m)->dex_num;
    if ((types[0] == DFI_TYPE_WATER && types[1] == DFI_CLOSURE_NONE) || dex == 493u || dex == 773u) {
        dfi_emit_plain(r, DUOFORGE_EVENT_FAIL, flat); /* -fail|target, not the user */
        return false;
    }
    b->tail.sides[flat / 2u].soak_type[occupant] = DFI_TYPE_WATER + 1u; /* 18, a constant that fits the byte */
    b->tail.sides[flat / 2u].type2[occupant] = 0u; /* setType replaces both types (sim/pokemon.ts:2109) */
    duoforge_event e = dfi_ev(DUOFORGE_EVENT_TYPE_CHANGE, flat, DUOFORGE_CAUSE_MOVE, move_id, DUOFORGE_NO_POSITION);
    e.detail = (uint8_t)DFI_TYPE_WATER; /* -start|target|typechange|Water */
    dfi_emit(r, &e);
    return true;
}

/* A status move that did something to a target ends the Champions hit
 * loop like a hit: its Update (data/mods/champions/scripts.ts:537), the
 * faint lines, then the Update after it (:574). A side or field move does
 * not reach the hit loop. */
static duoforge_status dfi_terrain_change(dfi_run *r);
/* The two Updates of the Champions hit loop after a hit step (data/mods/champions/scripts.ts:537 and :574), with the faint lines
 * between them. Every status hit that reaches the loop runs them, whatever its result: a true hit, and a hit whose target result is
 * NOT_FAIL (Ally Switch's onHit when there is no partner: the damage entry is '' (not false), so neither the break at :526 nor the
 * return at :572 is taken). The result is set by the caller. */
static duoforge_status dfi_status_updates(dfi_run *r)
{
    const duoforge_status st = dfi_update(r);
    if (st != DUOFORGE_OK) {
        return st;
    }
    dfi_announce_faints(r, false); /* no status move in the data costs its user HP */
    return dfi_update(r);
}

static duoforge_status dfi_status_hit_end(dfi_run *r)
{
    r->mres |= DFI_MRES_TRUE; /* the effect applied: the move's hit returns true (sim/battle-actions.ts, runMoveEffects) */
    return dfi_status_updates(r);
}

/* Protect (data/moves.ts protect, data/conditions.ts stall): fails without a
 * draw when nobody acts after the user; with a stall counter it succeeds on
 * random(counter) == 0 (STALL) and otherwise loses the counter. Step G20: Spiky Shield (data/moves.ts:17532-17584) has
 * the same onPrepareHit, onHit and stall as Protect and prints `-singleturn|X|move: Protect` (its text is checked by the
 * generator against Protect's); `kind` is the variant that the volatile is (DFI_PROTECT_*), kept in the user's tail
 * until the residual. */
static duoforge_status dfi_run_protect(dfi_run *r, uint32_t user, uint32_t kind)
{
    dfi_active_slot *pos = dfi_pos(r->b, user);
    if (!dfi_will_act(r->b)) {
        r->mres |= DFI_MRES_FALSE;
        dfi_fail_still(r, user); /* onPrepareHit fails; the stall counter stays */
        return DUOFORGE_OK;
    }
    const uint32_t level = pos->stall_level;
    if (level > 0u) {
        uint32_t counter = 1u;
        for (uint32_t i = 0u; i < level; ++i) {
            counter *= 3u; /* level <= 6: at most 729 */
        }
        bool success = false;
        const duoforge_status st = dfi_draw_chance(r->draws, DFI_SITE_STALL, 1u, counter, &success);
        if (st != DUOFORGE_OK) {
            return st;
        }
        if (!success) {
            pos->stall_level = 0u;
            pos->stall_turns = 0u;
            r->mres |= DFI_MRES_FALSE;
            dfi_fail_still(r, user);
            return DUOFORGE_OK;
        }
    }
    pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_PROTECT); /* wide-operands-reviewed: < 256 */
    r->b->tail.sides[user / 2u].positions[user % 2u].protect_kind = (uint8_t)kind; /* <= DFI_TAIL_PROTECT_KIND_MAX */
    pos->stall_level = (uint8_t)(level < DFI_STALL_LEVEL_MAX ? level + 1u : level); /* wide-operands-reviewed */
    pos->stall_turns = (uint8_t)DFI_STALL_DURATION;
    dfi_emit_plain(r, DUOFORGE_EVENT_PROTECT, user); /* [-singleturn] Protect (all three print `move: Protect`) */
    r->mres |= DFI_MRES_TRUE;
    return dfi_status_hit_end(r);
}

/* Poison Touch (POOL data, data/abilities.ts:3370-3383, onSourceDamagingHit): after a contact move that hit, the
 * attacker's roll randomChance(3, 10) (random(10) < 3, one draw per target, also for a target that is down: the
 * handler runs before trySetStatus fails) and then trySetStatus('psn', attacker) on the target: [-status] psn [from]
 * ability: Poison Touch [of] the attacker; nothing for a target that is a Poison or Steel type, has a status or is
 * down. Shield Dust and Covert Cloak, which the pin lets block it, are not marked. */
static duoforge_status dfi_poison_touch(dfi_run *r, uint32_t user, uint32_t target, const dfi_move_data *md)
{
    if ((md->flags & DFI_MOVE_FLAG_CONTACT) == 0u || !dfi_ability(r->b, dfi_at(r->b, user), DFI_ABILITY_POISONTOUCH)) {
        return DUOFORGE_OK;
    }
    uint32_t roll = 0u;
    duoforge_status st = dfi_draw(r->draws, DFI_SITE_POISON_TOUCH, 0u, 10u, &roll);
    if (st != DUOFORGE_OK || roll >= 3u) {
        return st;
    }
    return dfi_try_status(r, target, DFI_STATUS_PSN, user, DFI_NO_SOURCE_MOVE, DFI_ORIGIN_OTHER, 1u + DFI_ABILITY_POISONTOUCH);
}

#include "combat/field/side_conditions.h"


/* Toxic Debris (step G37, data/abilities.ts:5104-5117, onDamagingHit; the Champions mod does not change it): a Physical move
 * that hit its holder adds a layer of Toxic Spikes to the side of the attacker (to the foe's side when an ally of the holder
 * hit it) while that side has fewer than 2: -activate|holder|ability: Toxic Debris, then addSideCondition('toxicspikes', holder).
 * An unordered DamagingHit handler of the target itself, so it runs for a holder that the hit knocked out too (its ability is
 * still on the field until the faint is processed). */
static duoforge_status dfi_toxic_debris(dfi_run *r, uint32_t user, uint32_t target, const dfi_move_data *md)
{
    if (md->category != DFI_CATEGORY_PHYSICAL || !dfi_ability(r->b, dfi_at(r->b, target), DFI_ABILITY_TOXICDEBRIS)) {
        return DUOFORGE_OK;
    }
    const uint32_t side = user / 2u == target / 2u ? 1u - user / 2u : user / 2u;
    if (*dfi_hazard_layers(r->b, side, DUOFORGE_SIDE_TOXIC_SPIKES) >= DFI_TAIL_TOXIC_SPIKES_MAX) {
        return DUOFORGE_OK;
    }
    const duoforge_event e = dfi_ev(DUOFORGE_EVENT_ACTIVATE, target, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_TOXICDEBRIS,
                                    DUOFORGE_NO_POSITION);
    dfi_emit(r, &e);
    bool added = false;
    return dfi_add_hazard(r, side, DUOFORGE_SIDE_TOXIC_SPIKES, &added);
}

/* Flame Body (step G30, data/abilities.ts:1316-1328, onDamagingHit; its holder is the target): after a contact move that
 * hit it, the roll randomChance(3, 10) (random(10) < 3, one draw per target, also when the hit knocked the holder out:
 * the handler still runs, as Rough Skin's does) and then trySetStatus('brn', holder) on the attacker: [-status] brn
 * [from] ability: Flame Body [of] the holder; nothing for a Fire type, an attacker that has a status or is down, or a Flower
 * Veil that covers it. The attacker's Long Reach and Protective Pads, which stop the contact, are not marked. */
static duoforge_status dfi_flame_body(dfi_run *r, uint32_t user, uint32_t holder, const dfi_move_data *md)
{
    if ((md->flags & DFI_MOVE_FLAG_CONTACT) == 0u || !dfi_ability(r->b, dfi_at(r->b, holder), DFI_ABILITY_FLAMEBODY)) {
        return DUOFORGE_OK;
    }
    uint32_t roll = 0u;
    duoforge_status st = dfi_draw(r->draws, DFI_SITE_FLAME_BODY, 0u, 10u, &roll);
    if (st != DUOFORGE_OK || roll >= 3u) {
        return st;
    }
    return dfi_try_status(r, user, DFI_STATUS_BRN, holder, DFI_NO_SOURCE_MOVE, DFI_ORIGIN_OTHER, 1u + DFI_ABILITY_FLAMEBODY);
}

/* Static (step G39, data/abilities.ts:4536-4548, onDamagingHit; its holder is the target): Flame Body's shape with paralysis.
 * After a contact move that hit it, randomChance(3, 10) (one draw of the site STATIC per target, also when the hit knocked
 * the holder out), then trySetStatus('par', holder) on the attacker: [-status] par [from] ability: Static [of] the holder;
 * nothing for an Electric type, an attacker with a status or down, or Limber, or a Flower Veil that covers it. */
/* Step G71 (decision 0034): Cute Charm's addVolatile('attract', holder) on the attacker at `inf` (data/moves.ts:706-761, onStart).
 * The caller has drawn the roll already. Silent refusals, as the pin: the attacker is down (addVolatile returns false), it is
 * infatuated already (no onRestart), Oblivious blocks it (runStatusImmunity: an ability source, so no -immune line), and a gender
 * pair that is not 1 and 2 fails the Start (no line). Otherwise the byte is the holder's member code and the line is
 * -start|X|Attract|[from] ability: Cute Charm|[of] Y (VOLATILE_START, cause ABILITY, id2 = Cute Charm + 1, other = the holder).
 * A holder that faints from the hit still starts it (the pin runs DamagingHit while the holder is active); the next Update ends
 * it, as its source is not active (dfi_attract_update). */
static duoforge_status dfi_attract_start(dfi_run *r, uint32_t holder, uint32_t inf)
{
    struct duoforge_battle *b = r->b;
    const dfi_member *im = dfi_at(b, inf);
    const dfi_member *hm = dfi_at(b, holder);
    if (im == NULL || hm == NULL || im->hp == 0u || b->tail.attract_source[inf] != 0u) {
        return DUOFORGE_OK;
    }
    if (dfi_ability(b, im, DFI_ABILITY_OBLIVIOUS)) {
        return DUOFORGE_OK;
    }
    const bool pair = (im->gender == DFI_GENDER_MALE && hm->gender == DFI_GENDER_FEMALE) ||
                      (im->gender == DFI_GENDER_FEMALE && hm->gender == DFI_GENDER_MALE);
    if (!pair) {
        return DUOFORGE_OK;
    }
    const uint32_t hside = holder / DUOFORGE_ACTIVE_PER_SIDE;
    const uint32_t hmember = b->sides[hside].positions[holder % DUOFORGE_ACTIVE_PER_SIDE].occupant;
    b->tail.attract_source[inf] = (uint8_t)(1u + hside * DUOFORGE_MAX_ROSTER + hmember); /* wide-operands-reviewed: 1..12 (side 0..1, member 0..5) */
    duoforge_event start = dfi_ev(DUOFORGE_EVENT_VOLATILE_START, inf, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_CUTECHARM, holder);
    start.detail = DUOFORGE_VOLATILE_ATTRACT;
    dfi_emit(r, &start);
    return DUOFORGE_OK;
}

/* Cute Charm (step G71, data/abilities.ts:798-810, onDamagingHit): a contact hit on a damaged holder draws randomChance(3, 10), and
 * the draw is taken for every such hit, also when the attacker cannot be infatuated (the refusals are in dfi_attract_start). */
static duoforge_status dfi_cute_charm(dfi_run *r, uint32_t user, uint32_t holder, const dfi_move_data *md)
{
    if ((md->flags & DFI_MOVE_FLAG_CONTACT) == 0u || !dfi_ability(r->b, dfi_at(r->b, holder), DFI_ABILITY_CUTECHARM)) {
        return DUOFORGE_OK;
    }
    uint32_t roll = 0u;
    const duoforge_status st = dfi_draw(r->draws, DFI_SITE_CUTE_CHARM, 0u, 10u, &roll);
    if (st != DUOFORGE_OK || roll >= 3u) {
        return st;
    }
    return dfi_attract_start(r, holder, user);
}

static duoforge_status dfi_static(dfi_run *r, uint32_t user, uint32_t holder, const dfi_move_data *md)
{
    if ((md->flags & DFI_MOVE_FLAG_CONTACT) == 0u || !dfi_ability(r->b, dfi_at(r->b, holder), DFI_ABILITY_STATIC)) {
        return DUOFORGE_OK;
    }
    uint32_t roll = 0u;
    duoforge_status st = dfi_draw(r->draws, DFI_SITE_STATIC, 0u, 10u, &roll);
    if (st != DUOFORGE_OK || roll >= 3u) {
        return st;
    }
    return dfi_try_status(r, user, DFI_STATUS_PAR, holder, DFI_NO_SOURCE_MOVE, DFI_ORIGIN_OTHER, 1u + DFI_ABILITY_STATIC);
}

/* Poison Point (A2a, decision 0015 entry 5dy; data/abilities.ts:3344-3356, onDamagingHit; its holder is the target, no Champions
 * entry): Static's callback word for word with psn (gen_closure.py checks both texts): after a contact move that hit it,
 * randomChance(3, 10) (one draw of its own site POISON_POINT, 26, per target, also when the hit knocked the holder out), then
 * source.trySetStatus('psn', target) on the attacker: [-status] psn [from] ability: Poison Point [of] the holder; nothing for a
 * Poison or Steel type (unless the holder has Corrosion, which it does not: one ability), an attacker with a status or down, or a
 * Flower Veil that covers it. The draw stands where Static's and Flame Body's stand: a holder has one ability, so only one of the
 * three draws for a hit. */
static duoforge_status dfi_poison_point(dfi_run *r, uint32_t user, uint32_t holder, const dfi_move_data *md)
{
    if ((md->flags & DFI_MOVE_FLAG_CONTACT) == 0u || !dfi_ability(r->b, dfi_at(r->b, holder), DFI_ABILITY_POISONPOINT)) {
        return DUOFORGE_OK;
    }
    uint32_t roll = 0u;
    duoforge_status st = dfi_draw(r->draws, DFI_SITE_POISON_POINT, 0u, 10u, &roll);
    if (st != DUOFORGE_OK || roll >= 3u) {
        return st;
    }
    return dfi_try_status(r, user, DFI_STATUS_PSN, holder, DFI_NO_SOURCE_MOVE, DFI_ORIGIN_OTHER, 1u + DFI_ABILITY_POISONPOINT);
}

/* Gooey (A2a, decision 0015 entry 5dy; data/abilities.ts:1642-1653, onDamagingHit; its holder is the target, no Champions entry):
 * after a contact move that hit it, `-ability|holder|Gooey` and then this.boost({ spe: -1 }, source, target, null, true): the
 * attacker's Speed -1 with the holder as the source, Gooey as the effect and isSecondary, so no second -ability line, a drop at -6
 * prints `-unboost|X|spe|0`, and the attacker's TryBoost handlers (Clear Body, White Smoke, Mirror Armor, Flower Veil) see an
 * ability's drop (their line shows). Mirror Armor's shape (dfi_boost). No draw. It runs also when the hit knocked the holder out
 * (DamagingHit runs before the faint is processed); an attacker that is down takes nothing (boost returns at once) but the
 * -ability line stands, as in the pin. */
static void dfi_gooey(dfi_run *r, uint32_t user, uint32_t holder, const dfi_move_data *md)
{
    if ((md->flags & DFI_MOVE_FLAG_CONTACT) == 0u || !dfi_ability(r->b, dfi_at(r->b, holder), DFI_ABILITY_GOOEY)) {
        return;
    }
    const duoforge_event ab = dfi_ev(DUOFORGE_EVENT_ABILITY, holder, DUOFORGE_CAUSE_NONE, 1u + DFI_ABILITY_GOOEY, DUOFORGE_NO_POSITION);
    dfi_emit(r, &ab); /* [-ability] holder|Gooey */
    static const uint8_t spe_down[DFI_STAT_STAGE_COUNT] = {6u, 6u, 6u, 6u, 5u, 6u, 6u};
    (void)dfi_boost(r, user, spe_down, holder, dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_GOOEY, DFI_BOOST_SECONDARY));
}

/* Spicy Spray (step G59, data/abilities.ts:4466-4475, onDamagingHit; its holder is the target): after EVERY damaging hit, contact or
 * not, and with no roll, source.trySetStatus('brn', target): the attacker is burned, from the holder, through the status path of
 * the other sources (dfi_try_status: the Fire type, a status already up, a Flower Veil, a fainted attacker and Synchronize on the
 * attacker, which passes the burn back to the holder). It runs also when the hit knocked the holder out (the handler still runs,
 * as Flame Body's does). The Champions mod inherits it. Mold Breaker is not marked; the holder has one ability. */
static duoforge_status dfi_spicy_spray(dfi_run *r, uint32_t user, uint32_t holder)
{
    if (!dfi_ability(r->b, dfi_at(r->b, holder), DFI_ABILITY_SPICYSPRAY)) {
        return DUOFORGE_OK;
    }
    return dfi_try_status(r, user, DFI_STATUS_BRN, holder, DFI_NO_SOURCE_MOVE, DFI_ORIGIN_OTHER, 1u + DFI_ABILITY_SPICYSPRAY);
}

/* Wide Guard (data/moves.ts:20808-20851; POOL kinds, the side's flag is in the state tail). Its onTry (:20818) fails
 * unless another action is pending (queue.willAct), as Protect's does. Its side condition lasts the turn:
 * addSideCondition prints [-singleturn] user|Wide Guard once (onSideStart, :20825-20827); a second Wide Guard of the
 * same side adds nothing and prints nothing but is no failure (the side condition's false result is combined with
 * onHitSide's success, sim/battle-actions.ts:1240-1243, 1273-1275, 1561-1575). onHitSide gives the user the stall
 * volatile (:20821-20823) without Protect's roll: the counter goes up as after a successful Protect, so a later Protect
 * rolls against it (data/conditions.ts:439-461). A side move does not reach the Champions hit loop (no Update). */
static duoforge_status dfi_run_wide_guard(dfi_run *r, uint32_t user)
{
    struct duoforge_battle *b = r->b;
    if (!dfi_will_act(b)) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    dfi_tail_side *ts = &b->tail.sides[user / 2u];
    if (ts->wide_guard == 0u) {
        ts->wide_guard = (uint8_t)DFI_TAIL_WIDE_GUARD_MAX;
        duoforge_event e = dfi_ev(DUOFORGE_EVENT_SINGLE_TURN, user, DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION);
        e.id = (uint16_t)DFI_MOVE_WIDEGUARD;
        dfi_emit(r, &e); /* [-singleturn] user|Wide Guard */
    }
    dfi_active_slot *pos = dfi_pos(b, user);
    pos->stall_level = (uint8_t)(pos->stall_level < DFI_STALL_LEVEL_MAX ? pos->stall_level + 1u : pos->stall_level); /* wide-operands-reviewed */
    pos->stall_turns = (uint8_t)DFI_STALL_DURATION;
    r->mres |= DFI_MRES_TRUE; /* Wide Guard's effect applies (a second one of the side prints nothing, and is still a success) */
    return DUOFORGE_OK;
}

/* Quick Guard (step G54, data/moves.ts:14489-14531): Wide Guard's shape for the priority moves. Its onTry fails unless a
 * move is still to come (queue.willAct, as Wide Guard's does); the side gets the turn's flag and its -singleturn line
 * (id Quick Guard), the user the stall counter of onHitSide without a roll, and a second one of the side changes nothing.
 * The flag ends in the residual of the turn (the tail's quick_guard, cleared with Wide Guard's). */
static duoforge_status dfi_run_quick_guard(dfi_run *r, uint32_t user)
{
    struct duoforge_battle *b = r->b;
    if (!dfi_will_act(b)) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    dfi_tail_side *ts = &b->tail.sides[user / 2u];
    if (ts->quick_guard == 0u) {
        ts->quick_guard = (uint8_t)DFI_TAIL_QUICK_GUARD_MAX;
        duoforge_event e = dfi_ev(DUOFORGE_EVENT_SINGLE_TURN, user, DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION);
        e.id = (uint16_t)DFI_MOVE_QUICKGUARD;
        dfi_emit(r, &e); /* [-singleturn] user|Quick Guard */
    }
    dfi_active_slot *pos = dfi_pos(b, user);
    pos->stall_level = (uint8_t)(pos->stall_level < DFI_STALL_LEVEL_MAX ? pos->stall_level + 1u : pos->stall_level); /* wide-operands-reviewed */
    pos->stall_turns = (uint8_t)DFI_STALL_DURATION;
    return DUOFORGE_OK;
}

/* Aurora Veil (POOL data, data/moves.ts:830-877; the side's turns are in the state tail). Its onTry (:840) fails the
 * move unless the weather is snow (Field.isWeather, sim/field.ts:118: dfi_field_weather, so Cloud Nine suppresses it, step
 * G79): -fail with [still], as every failed side move. addSideCondition does not restart an active
 * condition, so a second one fails the same way. The duration is 5, or 8 when the user holds Light Clay
 * (durationCallback, :842-847); the line is -sidestart|side|move: Aurora Veil (:861-863). A side move does not reach the
 * Champions hit loop (no Update), as Wide Guard's does not. */
static duoforge_status dfi_run_aurora_veil(dfi_run *r, uint32_t user)
{
    struct duoforge_battle *b = r->b;
    const uint32_t side = user / 2u;
    uint8_t *turns = &b->tail.sides[side].aurora_veil_turns;
    if (dfi_field_weather(r) != DFI_WEATHER_SNOW || *turns != 0u) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    const uint32_t duration = dfi_holds(b, dfi_at(b, user), DFI_SCREEN_EXTENDER) ? DFI_SCREEN_TURNS_MAX : DFI_SCREEN_TURNS;
    *turns = (uint8_t)duration; /* <= 8 */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_SIDE_START, DUOFORGE_NO_POSITION);
    e.detail = (uint8_t)side;
    e.amount = (uint8_t)DUOFORGE_SIDE_AURORA_VEIL;
    dfi_emit(r, &e);
    r->mres |= DFI_MRES_TRUE; /* addSideCondition returns true */
    return DUOFORGE_OK;
}

/* Perish Song (step G26, POOL data, data/moves.ts:13233-13277; the Champions mod has no entry; the volatile's counter is
 * the position's `perish` of the state tail: the duration, 4 when it is added). A field move (target `all`): its
 * onHitField (:13242-13260) goes over every Pokemon that is active and has not fainted, in side and slot order
 * (Battle.getAllActive). One that already has the volatile is left alone and counts for nothing; one whose TryHit is
 * stopped counts as hit (result = true) and gets nothing: of the abilities of a battle only Good as Gold (data/
 * abilities.ts:1630-1641, onTryHit: a status move of another Pokemon, -immune [from] ability: Good as Gold) stops it,
 * the user's own never does (target !== source); Soundproof (:4436-4452, a sound move) is unmarked, the other marked
 * abilities with an onTryHit read a type that Perish Song (Normal) is not (Flash Fire, Lightning Rod) or a priority
 * above 0 (Armor Tail; Psychic Terrain: refused below), Protect and Wide Guard let a move without the protect flag
 * through (checkMoveBypassesProtect, sim/battle.ts:1300-1309), and no semi-invulnerable move is marked, so the
 * Invulnerability event misses nothing. A Pokemon that gets the volatile shows nothing now (-start perish3 is [silent];
 * the first count is the residual's); if at least one did, -fieldactivate|move: Perish Song follows. A move that did
 * nothing (every active Pokemon has it already) fails with -fail and [still] (moveHit, sim/battle-actions.ts:1302-1308).
 * The hit loop's Update does not run, as for the other field moves. */
static duoforge_status dfi_run_perish_song(dfi_run *r, uint32_t user, const dfi_move_data *md)
{
    struct duoforge_battle *b = r->b;
    if (dfi_move_priority(b, dfi_at(b, user), md) > DFI_PRIORITY_BIAS) {
        return DUOFORGE_E_UNSUPPORTED; /* Prankster's +1 meets Psychic Terrain's and Armor Tail's TryHit and TryMove */
    }
    bool result = false;
    bool message = false;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        const dfi_member *t = dfi_at(b, flat);
        if (t == NULL || t->hp == 0u) {
            continue;
        }
        if (flat != user && dfi_ability(b, t, DFI_ABILITY_GOODASGOLD)) {
            dfi_immune(r, flat, 1u + DFI_ABILITY_GOODASGOLD);
            result = true;
            continue;
        }
        /* Soundproof's onTryHit (step G32, data/abilities.ts:4436-4452): Perish Song has the sound flag, so the holder, if
         * it is not the user, is -immune|holder|[from] ability: Soundproof and the handler returns null: it gets no
         * volatile, and that counts as a result (onHitField, data/moves.ts:13242-13260). */
        if (flat != user && dfi_ability(b, t, DFI_ABILITY_SOUNDPROOF)) {
            dfi_immune(r, flat, 1u + DFI_ABILITY_SOUNDPROOF);
            result = true;
            continue;
        }
        dfi_tail_pos *tail = &b->tail.sides[flat / 2u].positions[flat % 2u];
        if (tail->perish == 0u) {
            tail->perish = (uint8_t)DFI_TAIL_PERISH_MAX;
            result = true;
            message = true;
        }
    }
    if (!result) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    r->mres |= DFI_MRES_TRUE; /* at least one holder took the volatile or was stopped: the hit returns true */
    if (message) {
        /* -fieldactivate|move: Perish Song: the ACTIVATE event of the move, with no position */
        const duoforge_event e = dfi_ev(DUOFORGE_EVENT_ACTIVATE, DUOFORGE_NO_POSITION, DUOFORGE_CAUSE_MOVE,
                                        DFI_MOVE_PERISHSONG, DUOFORGE_NO_POSITION);
        dfi_emit(r, &e);
    }
    return DUOFORGE_OK;
}

/* Nothing to hit: [notarget] on the last move line, then -fail. */
static duoforge_status dfi_no_target(dfi_run *r, uint32_t user)
{
    r->mres |= DFI_MRES_FALSE; /* the move returns false with no target (sim/battle-actions.ts:461-465, :510-514) */
    duoforge_event *mv = dfi_last_move(r);
    if (mv != NULL) {
        mv->flags = (uint8_t)((uint32_t)mv->flags | DUOFORGE_EVENT_FLAG_NOTARGET); /* wide-operands-reviewed: < 256 */
    }
    dfi_emit_plain(r, DUOFORGE_EVENT_FAIL, user);
    return DUOFORGE_OK;
}

/* queue.willMove (sim/battle-queue.ts:324-332): the queued move action of the
 * Pokemon at `flat`, bound by its activation; NULL when it has fainted or
 * has none (it already moved, or it switches). */
static const dfi_queue_record *dfi_will_move(struct duoforge_battle *b, uint32_t flat)
{
    const dfi_member *m = dfi_at(b, flat);
    if (m == NULL || m->hp == 0u) {
        return NULL;
    }
    const dfi_active_slot *pos = dfi_pos(b, flat);
    for (uint32_t i = 0u; i < b->queue_len; ++i) {
        const dfi_queue_record *q = &b->queue[i];
        if (q->kind == DFI_Q_MOVE && (uint32_t)q->side * 2u + (uint32_t)q->slot == flat &&
            q->activation_id == pos->activation_id) {
            return q;
        }
    }
    return NULL;
}

/* The failencore flag (data/moves.ts flags.failencore): Struggle and Encore itself are the only moves with it that a
 * marked member can have (duoforge.moves.encore checks the predicate over every pool move against the pinned flag). */
static bool dfi_fails_encore(uint32_t move_id)
{
    return move_id == DFI_MOVE_STRUGGLE || move_id == DFI_MOVE_ENCORE;
}

static void dfi_cancel_actions(struct duoforge_battle *b, uint32_t activation_id);

/* The target that resolveAction gives an action without one (Battle.getRandomTarget, sim/battle.ts:2490-2522): the
 * user for self, side and field moves; the standing ally for an ally move (sample over one: one draw); otherwise a
 * random foe (RANDOM_TARGET: side.randomFoe(), or the foe in slot 0 when none stands). */
static duoforge_status dfi_resolve_target(dfi_run *r, uint32_t flat, uint32_t cls, uint32_t *out)
{
    const uint32_t side = flat / 2u;
    if (cls == DUOFORGE_TARGET_CLASS_SELF || cls == DUOFORGE_TARGET_CLASS_ALLY_SIDE ||
        cls == DUOFORGE_TARGET_CLASS_ALL || cls == DUOFORGE_TARGET_CLASS_ADJACENT_ALLY_OR_SELF) {
        *out = flat;
        return DUOFORGE_OK;
    }
    if (cls == DUOFORGE_TARGET_CLASS_ADJACENT_ALLY) {
        const uint32_t ally = side * 2u + (1u - flat % 2u);
        *out = ally;
        if (!dfi_alive(r->b, ally)) {
            return DUOFORGE_OK; /* null: the move finds nothing to hit */
        }
        uint32_t v = 0u;
        return dfi_draw(r->draws, DFI_SITE_RANDOM_TARGET, 0u, 1u, &v);
    }
    uint32_t t = DFI_POSITIONS;
    const duoforge_status st = dfi_random_foe(r, side, &t);
    *out = t < DFI_POSITIONS ? t : (1u - side) * 2u;
    return st;
}

/* Champions' Encore, the branch of onStart for a target that still has another move queued
 * (data/mods/champions/moves.ts:326-342): queue.changeAction(target, {choice: 'move', moveid, order}) cancels the
 * target's actions and inserts a new move action that has no target (BattleQueue.changeAction and insertChoice,
 * sim/battle-queue.ts:301-305 and 369-403). resolveAction picks its target (RANDOM_TARGET), then the action goes where
 * comparePriority puts it among the queued actions: the order of its kind, the priority of the new move with its
 * user's ModifyPriority handlers, the user's action speed. It goes before the first action that it beats; among
 * actions that it ties it is placed at random(first, last + 1) (INSERT_TIE, drawn only when that range has more than
 * one index). Every later sort takes every priority from the move again (sim/battle.ts:2921-2925), so the priority
 * that the reference then writes into the action (the old action's priority adjusted by the two moves' base
 * priorities) never decides anything. */
static duoforge_status dfi_encore_replace(dfi_run *r, uint32_t flat, uint32_t slot)
{
    struct duoforge_battle *b = r->b;
    const dfi_queue_record *old = dfi_will_move(b, flat);
    const dfi_member *tm = dfi_at(b, flat);
    if (old == NULL || tm == NULL || slot >= tm->move_count) {
        return DUOFORGE_E_INVARIANT;
    }
    dfi_queue_record rec = *old;
    rec.move_slot = (uint8_t)slot;
    rec.reserve = 0u;
    uint32_t cls = dfi_pool_moves[tm->moves[slot].move_id].target_class;
    /* The Champions resolveAction gives a non-Ghost user's Curse the target self before it picks one (sim/battle-queue.ts:263-266),
     * so getRandomTarget returns the user and draws nothing (issue 556: a frozen Sylveon Encored into Curse). */
    if (tm->moves[slot].move_id == DFI_MOVE_CURSE && !dfi_has_type(b, tm, DFI_TYPE_GHOST)) {
        cls = DUOFORGE_TARGET_CLASS_SELF;
    }
    dfi_cancel_actions(b, old->activation_id); /* `old` is not valid from here */
    uint32_t target = 0u;
    duoforge_status st = dfi_resolve_target(r, flat, cls, &target);
    if (st != DUOFORGE_OK) {
        return st;
    }
    rec.target = (uint8_t)target; /* < 4 */
    st = dfi_update_position_speed(r, flat); /* insertChoice: pokemon.updateSpeed() */
    if (st != DUOFORGE_OK) {
        return st;
    }
    dfi_key key;
    st = dfi_key_of(r, &rec, &key);
    if (st != DUOFORGE_OK) {
        return st;
    }
    uint32_t first = UINT32_MAX;
    uint32_t last = UINT32_MAX;
    const uint32_t len = b->queue_len;
    for (uint32_t i = 0u; i < len && i < DFI_QUEUE_CAPACITY; ++i) {
        dfi_key other;
        st = dfi_key_of(r, &b->queue[i], &other);
        if (st != DUOFORGE_OK) {
            return st;
        }
        const uint32_t c = dfi_compare(&key, &other); /* 0: the new action first, 1: a tie */
        if (c != 2u && first == UINT32_MAX) {
            first = i;
        }
        if (c == 0u) {
            last = i;
            break;
        }
    }
    uint32_t index = len;
    if (first != UINT32_MAX) {
        if (last == UINT32_MAX) {
            last = len;
        }
        index = first;
        if (first != last) {
            st = dfi_draw(r->draws, DFI_SITE_INSERT_TIE, first, last + 1u, &index);
            if (st != DUOFORGE_OK) {
                return st;
            }
        }
    }
    if (len >= DFI_QUEUE_CAPACITY || index > len) {
        return DUOFORGE_E_INVARIANT;
    }
    for (uint32_t i = len; i > index; --i) {
        b->queue[i] = b->queue[i - 1u];
    }
    b->queue[index] = rec;
    b->queue_len = (uint8_t)(len + 1u); /* wide-operands-reviewed: <= DFI_QUEUE_CAPACITY */
    return DUOFORGE_OK;
}

/* Encore (data/moves.ts:4724-4783, Champions onStart at data/mods/champions/moves.ts:309-345) on the target at `flat`.
 * addVolatile fails for a target that has it already (the condition has no onRestart); onStart fails without a last
 * move, for a failencore move, for a move that is not among the target's slots or has no PP left; a failure is
 * -fail|user with [still] (the move did nothing). Otherwise the lock starts: -start|target|Encore, duration 3, or 4
 * when the target has no move queued (it has moved this turn, or switches); a target that has another move queued has
 * it replaced by the Encored one (dfi_encore_replace), unless it holds a Mental Herb: then it keeps its queued move (step
 * G47). *did tells whether the lock started. */
static duoforge_status dfi_encore(dfi_run *r, uint32_t user, uint32_t flat, bool *did)
{
    struct duoforge_battle *b = r->b;
    *did = false;
    dfi_member *tm = dfi_at(b, flat);
    dfi_tail_pos *tail = &b->tail.sides[flat / 2u].positions[flat % 2u];
    if (tm == NULL || tm->hp == 0u) {
        return DUOFORGE_OK;
    }
    const uint32_t last = tail->last_move; /* 0 none, 1..4 slot + 1, 5 Struggle */
    if (tail->encore_slot != 0u || last == 0u || last > DUOFORGE_MAX_MOVE_SLOTS || last > tm->move_count ||
        dfi_fails_encore(tm->moves[last - 1u].move_id) || tm->moves[last - 1u].pp == 0u) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    const uint32_t slot = last - 1u;
    const uint32_t move_id = tm->moves[slot].move_id;
    const dfi_queue_record *queued = dfi_will_move(b, flat);
    const bool replace = queued != NULL && dfi_move_of(tm, queued->move_slot) != move_id;
    tail->encore_slot = (uint8_t)last;
    tail->encore_turns = queued == NULL ? DFI_ENCORE_TURNS + 1u : DFI_ENCORE_TURNS; /* 4 or 3: fits the byte */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_VOLATILE_START, flat);
    e.detail = (uint8_t)DUOFORGE_VOLATILE_ENCORE;
    dfi_emit(r, &e);
    *did = true;
    /* A target that holds Mental Herb keeps its queued move: the Champions onStart changes the action only when the target has
     * no Mental Herb (data/mods/champions/moves.ts:330, `!target.hasItem('mentalherb')`). The herb's Update, which follows the
     * move, removes the lock before the target acts (dfi_mental_herb), so the target's own move runs. */
    if (replace && !dfi_holds(b, tm, DFI_ITEM_MENTALHERB)) {
        return dfi_encore_replace(r, flat, slot);
    }
    return DUOFORGE_OK;
}

/* Disable's condition onStart (data/moves.ts:3666-3692, the Champions mod does not change it; POOL kinds, the state is the
 * tail's disable_slot and disable_turns). addVolatile refuses a fainted Pokemon and one that already has the volatile (it has
 * no onRestart); onStart fails for a Pokemon without a last move and for a last move without PP; the volatile lasts 5 turns,
 * 4 when the target has not taken its turn yet (queue.willMove) or when the effect comes from the Pokemon's own action in
 * progress (Cursed Body: pokemon is the active Pokemon and the move is not external). The line is `-start|X|Disable|MOVE`
 * with [from] ability: Cursed Body [of] holder for the ability. Struggle (last move 5) is never barred: Disable's
 * onTryHit refuses it and Cursed Body skips it. */
static bool dfi_disable_start(dfi_run *r, uint32_t flat, uint32_t holder, bool by_ability)
{
    struct duoforge_battle *b = r->b;
    dfi_member *tm = dfi_at(b, flat);
    dfi_tail_pos *tail = &b->tail.sides[flat / 2u].positions[flat % 2u];
    if (tm == NULL || tm->hp == 0u || tail->disable_slot != 0u) {
        return false;
    }
    const uint32_t last = tail->last_move; /* 0 none, 1..4 slot + 1, 5 Struggle */
    if (last == 0u || last > DUOFORGE_MAX_MOVE_SLOTS || last > tm->move_count || tm->moves[last - 1u].pp == 0u) {
        return false;
    }
    const uint32_t move_id = tm->moves[last - 1u].move_id;
    uint32_t turns = DFI_DISABLE_TURNS;
    if (by_ability || dfi_will_move(b, flat) != NULL) {
        turns -= 1u;
    }
    tail->disable_slot = (uint8_t)last; /* <= 4 */
    tail->disable_turns = (uint8_t)turns; /* 4 or 5 */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_VOLATILE_START, flat);
    e.detail = (uint8_t)DUOFORGE_VOLATILE_DISABLE;
    e.id = (uint16_t)move_id;
    if (by_ability) {
        e.cause = (uint8_t)DUOFORGE_CAUSE_ABILITY;
        e.id2 = (uint16_t)(1u + DFI_ABILITY_CURSEDBODY); /* wide-operands-reviewed: an ability id + 1 */
        e.other = (uint8_t)holder;
    }
    dfi_emit(r, &e);
    return true;
}

/* Taunt (data/moves.ts:18974-19016, the Champions mod changes nothing) on the target at `flat`: the move's accuracy is
 * drawn by the caller; addVolatile fails for a target that has the volatile already (no onRestart): -fail|user with
 * [still]. Otherwise -start|target|move: Taunt, duration 3, and 4 when the target has been out for a turn
 * (activeTurns; here: not newlySwitched) and has no move queued (it has moved this turn). True when it started. The
 * Status moves of the target are barred in the request (onDisableMove) and stopped by cant (dfi_before_move), the end is
 * in the residual at order 15. */
static bool dfi_taunt(dfi_run *r, uint32_t user, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    const dfi_member *tm = dfi_at(b, flat);
    dfi_tail_pos *tail = &b->tail.sides[flat / 2u].positions[flat % 2u];
    if (tm == NULL || tm->hp == 0u) {
        return false;
    }
    if (tail->taunt_turns != 0u) {
        dfi_fail_still(r, user);
        return false;
    }
    const uint32_t newly = dfi_kind_limits_of(r->ctx->data_kind).vol_flags_mask & DFI_VOL_NEWLY_SWITCHED;
    const bool out_a_turn = ((uint32_t)dfi_pos(b, flat)->flags & newly) == 0u;
    const uint32_t turns = (out_a_turn && dfi_will_move(b, flat) == NULL) ? DFI_TAUNT_TURNS + 1u : DFI_TAUNT_TURNS;
    tail->taunt_turns = (uint8_t)turns; /* <= DFI_TAIL_TAUNT_MAX */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_VOLATILE_START, flat);
    e.detail = (uint8_t)DUOFORGE_VOLATILE_TAUNT;
    dfi_emit(r, &e);
    return true;
}

/* Dragon Cheer (data/moves.ts:4056-4086, no Champions change; accuracy true, target adjacentAlly; step G72b, decision 0015 5ce).
 * Its volatile's onStart fails when the target has Focus Energy (the tail's focus_energy byte, which nothing writes yet: the
 * pin's focusenergy is unmarked) and when the target has the volatile already (addVolatile refuses a second one: no onRestart),
 * with -fail and [still]. Otherwise the volatile starts (-start|X|move: Dragon Cheer, no END) and stores whether the target is
 * Dragon-type at its start (hasDragonType): the crit stage is +2 for a Dragon, +1 otherwise, read for the holder when it attacks
 * (dfi_get_damage). The stage is a position flag, so a switch-out clears it with the rest of the position's tail. */
static bool dfi_dragon_cheer(dfi_run *r, uint32_t user, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    const dfi_member *tm = dfi_at(b, flat);
    dfi_tail_pos *tail = &b->tail.sides[flat / 2u].positions[flat % 2u];
    if (tm == NULL || tm->hp == 0u) {
        return false;
    }
    if (tail->focus_energy != 0u || dfi_dragon_cheer_stage(b, flat) != 0u) {
        dfi_fail_still(r, user);
        return false;
    }
    const uint32_t stage = dfi_has_type(b, tm, DFI_TYPE_DRAGON) ? DFI_POSFLAG_DRAGON_CHEER_MAX : 1u;
    tail->position_flags = (uint8_t)((uint32_t)tail->position_flags | (stage << DFI_POSFLAG_DRAGON_CHEER_SHIFT)); /* wide-operands-reviewed */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_VOLATILE_START, flat);
    e.detail = (uint8_t)DUOFORGE_VOLATILE_DRAGONCHEER;
    dfi_emit(r, &e);
    return true;
}

/* Psych Up (data/moves.ts:14211-14240, no Champions change; step G80, decision 0044). Accuracy true, no onTry: it always
 * succeeds, even when the target has nothing to copy. The user takes the target's seven stages (a plain assignment in the pin:
 * no boost event, so no statsRaisedThisTurn flag). Its crit-stage volatiles go first (Focus Energy, Dragon Cheer; Laser Focus
 * and Gmax Chi Strike are not in the pool), then the target's copies: Focus Energy is the focus_energy byte, and the Dragon Cheer
 * stage is copied as stored (the pin copies hasDragonType, it does not recompute it from the user's type). The copies' starts
 * are [silent] and write no event. Then -copyboost|user|target|[from] move: Psych Up: DUOFORGE_EVENT_COPY_BOOST, other the target.
 * The flat target `flat` is the one the hit loop gives (normal: a Pokemon other than the user). */
static bool dfi_psych_up(dfi_run *r, uint32_t user, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    const dfi_member *tm = dfi_at(b, flat);
    if (tm == NULL || tm->hp == 0u || flat == user) {
        return false;
    }
    const dfi_active_slot *tp = dfi_pos(b, flat);
    dfi_active_slot *up = dfi_pos(b, user);
    const dfi_tail_pos *ttail = &b->tail.sides[flat / 2u].positions[flat % 2u];
    dfi_tail_pos *utail = &b->tail.sides[user / 2u].positions[user % 2u];
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        up->stages[i] = tp->stages[i];
    }
    utail->focus_energy = ttail->focus_energy;
    const uint32_t dc_mask = (uint32_t)DFI_POSFLAG_DRAGON_CHEER_MASK;
    utail->position_flags = (uint8_t)(((uint32_t)utail->position_flags & ~dc_mask) | ((uint32_t)ttail->position_flags & dc_mask)); /* wide-operands-reviewed */
    const duoforge_event act = dfi_ev(DUOFORGE_EVENT_COPY_BOOST, user, DUOFORGE_CAUSE_MOVE, DFI_MOVE_PSYCHUP, flat);
    dfi_emit(r, &act);
    return true;
}

/* Ally Switch's onPrepareHit (data/moves.ts:311-313 and the allyswitch condition :332-357; step G80, decision 0044). No volatile:
 * it starts at level 1 (counter 3) with 2 turns, with no draw (onStart). A live volatile restarts: the success roll is
 * randomChance(1, 3^level) (DFI_SITE_ALLY_SWITCH, random(3^level) == 0); on success the level rises while the counter is below
 * 729 (level 6 holds) and the turns are 2 again; on a failed roll the volatile is deleted and the move fails (`passed` false). The
 * counter advances here, before the hit, so a later failure (no partner, onHit) keeps it. */
static duoforge_status dfi_ally_switch_prepare(dfi_run *r, uint32_t user, bool *passed)
{
    dfi_tail_pos *tail = &r->b->tail.sides[user / 2u].positions[user % 2u];
    *passed = true;
    if (tail->ally_switch == 0u) {
        tail->ally_switch = (uint8_t)((1u << DFI_ALLY_SWITCH_LEVEL_SHIFT) | DFI_ALLY_SWITCH_TURNS_MAX); /* wide-operands-reviewed: <= DFI_ALLY_SWITCH_MAX */
        return DUOFORGE_OK;
    }
    const uint32_t level = (uint32_t)tail->ally_switch >> DFI_ALLY_SWITCH_LEVEL_SHIFT;
    uint32_t counter = 1u;
    for (uint32_t i = 0u; i < level; ++i) {
        counter *= 3u; /* level <= 6: at most 729 */
    }
    bool success = false;
    const duoforge_status st = dfi_draw_chance(r->draws, DFI_SITE_ALLY_SWITCH, 1u, counter, &success);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (!success) {
        tail->ally_switch = 0u; /* the volatile is deleted: the next use starts at level 1 */
        *passed = false;
        return DUOFORGE_OK;
    }
    const uint32_t next = level < DFI_ALLY_SWITCH_LEVEL_MAX ? level + 1u : level;
    tail->ally_switch = (uint8_t)((next << DFI_ALLY_SWITCH_LEVEL_SHIFT) | DFI_ALLY_SWITCH_TURNS_MAX); /* wide-operands-reviewed: <= 26 */
    return DUOFORGE_OK;
}

/* The flat position `f` after the two Pokemon of a swap have exchanged their positions. */
static uint32_t dfi_perm_flat(uint32_t f, uint32_t user, uint32_t partner)
{
    if (f == user) {
        return partner;
    }
    if (f == partner) {
        return user;
    }
    return f;
}

/* Bit `a` and bit `b` of `bits` exchanged. */
static uint32_t dfi_swap_bits(uint32_t bits, uint32_t a, uint32_t b)
{
    const uint32_t ba = (bits >> a) & 1u;
    const uint32_t bb = (bits >> b) & 1u;
    return (bits & ~((1u << a) | (1u << b))) | (ba << a) | (bb << b);
}

/* The run's scratch that belongs to a Pokemon, not to its slot, moves with it on a swap of two positions. Battle.swapPosition
 * (sim/battle.ts:1588-1607) moves the Pokemon objects and leaves every field of the Pokemon alone, and the Pokemon's own speed is
 * the speed it had at its last updateSpeed (sim/pokemon.ts:556-558, `this.speed = this.getActionSpeed()`). So the cached speed
 * (speed_seen: dfi_each_order, the Lightning Rod comparison, the ejectors, the residual order) moves with the Pokemon; so do its
 * residual HP, its queued faint, and the drag and lock bits. The slot-bound parts of the run stay where they are. */
static void dfi_run_swap_scratch(dfi_run *r, uint32_t user, uint32_t partner)
{
    uint32_t t = r->speed_seen[user];
    r->speed_seen[user] = r->speed_seen[partner];
    r->speed_seen[partner] = t;
    t = r->residual_hp[user];
    r->residual_hp[user] = r->residual_hp[partner];
    r->residual_hp[partner] = t;
    for (uint32_t i = 0u; i < r->faint_count && i < DFI_POSITIONS; ++i) {
        r->faint_queue[i] = dfi_perm_flat(r->faint_queue[i], user, partner);
    }
    r->last_fainted = dfi_perm_flat(r->last_fainted, user, partner);
    r->last_faint_by = dfi_perm_flat(r->last_faint_by, user, partner);
    r->drag_pending = dfi_swap_bits(r->drag_pending, user, partner);
    r->lock_restarted = dfi_swap_bits(r->lock_restarted, user, partner);
}

/* The position-bound state of a battle (step G80, decision 0044; the lead's inventory). When two positions a and c of one side
 * exchange their occupants (sim/battle.ts:1588-1607 moves the Pokemon objects, every field of the Pokemon with them), each of
 * the following moves with the Pokemon:
 *   - sides[side].positions[a/c] (dfi_active_slot): activation_id, occupant, stages, flags, stall, confusion, charge, locked_move,
 *     move_actions, switch_flag, locked_target: yes (they belong to the activation; the locked target is the Pokemon's
 *     lastMoveTargetLoc, sim/pokemon.ts:913 and sim/side.ts:677, a location that names the same position from either slot; issue
 *     541).
 *   - tail.sides[side].positions[a/c] (dfi_tail_pos): every field: yes (moves, Follow Me and Protect, counters, Dragon Cheer,
 *     move_result, ally_switch). position_flags bit 0 (Healing Wish): NO (a slot condition; the Swap rule of Healing Wish belongs
 *     to its own step, decision 0044).
 *   - trap_source of EVERY position that names a or c: relinked to the new flat position (a reference to the trapper's Pokemon).
 *     leech_seed_source is not relinked (its sourceSlot is a slot: sim/pokemon.ts:2002, data/moves.ts:10218).
 *   - attract_source[a] and [c]: exchanged (the infatuation moves with the infatuated Pokemon; the member code is unchanged).
 *   - party_order[side] entries a and c: yes (the side.pokemon order exchanges, sim/battle.ts:1598-1599).
 * Not moved, slot-bound: sealed_cmds[a/c] and requested_slots (the request of the slot), and sides[].knowledge, ability_now,
 * forme_now, soak_type, item_now, toxic_stage, type2, member_flags, illusion, hazards and screens (per roster member or per side).
 * The run's scratch (speed_seen, residual_hp, faint queue, drag and lock bits) is dfi_run_swap_scratch, and the queued actions are
 * remapped by the caller. Field test: tests/moves/test_ally_switch.c (dfi_swap_position_state moves every listed field and no other). */
bool dfi_ally_swap_wish_blocked(const struct duoforge_battle *b, uint32_t side, uint32_t a, uint32_t c)
{
    /* Healing Wish (step G82, slotCondition 'healingwish', data/moves.ts:8348-8382): bit 0 of the slot's flags. The Swap event of
     * sim/battle.ts:1588-1607 runs its onSwap for the Pokemon that arrives (data/moves.ts:8366-8377: a heal and the wish's end).
     * Batch 8 does not model that: an Ally Switch onto such a slot is refused (E_UNSUPPORTED), a known gap in decision 0044. */
    return ((uint32_t)b->tail.sides[side].positions[a].position_flags & (uint32_t)DFI_POSFLAG_HEALING_WISH) != 0u ||
           ((uint32_t)b->tail.sides[side].positions[c].position_flags & (uint32_t)DFI_POSFLAG_HEALING_WISH) != 0u;
}

void dfi_swap_position_state(struct duoforge_battle *b, uint32_t side, uint32_t a, uint32_t c)
{
    dfi_active_slot *sa = &b->sides[side].positions[a];
    dfi_active_slot *sc = &b->sides[side].positions[c];
    const dfi_active_slot slot_tmp = *sa;
    *sa = *sc;
    *sc = slot_tmp;
    dfi_tail_pos *ta = &b->tail.sides[side].positions[a];
    dfi_tail_pos *tc = &b->tail.sides[side].positions[c];
    const uint32_t hw = (uint32_t)DFI_POSFLAG_HEALING_WISH;
    const uint8_t hw_a = (uint8_t)((uint32_t)ta->position_flags & hw); /* wide-operands-reviewed: one bit */
    const uint8_t hw_c = (uint8_t)((uint32_t)tc->position_flags & hw); /* wide-operands-reviewed: one bit */
    const dfi_tail_pos tail_tmp = *ta;
    *ta = *tc;
    *tc = tail_tmp;
    ta->position_flags = (uint8_t)(((uint32_t)ta->position_flags & ~hw) | hw_a); /* wide-operands-reviewed: the slot condition stays */
    tc->position_flags = (uint8_t)(((uint32_t)tc->position_flags & ~hw) | hw_c); /* wide-operands-reviewed: the slot condition stays */
    /* Attract (step G71, rev 5 reserve bytes 0..3): the infatuation is on the infatuated Pokemon, so its byte goes with it. The byte is
     * a member code (side * 6 + roster index), which names the source Pokemon and does not change. The source's position (G87) is
     * derived from that code when it is read (dfi_attract_source_flat, observation.c), so nothing is stored to relink. */
    {
        const uint32_t fa = side * DUOFORGE_ACTIVE_PER_SIDE + a;
        const uint32_t fc = side * DUOFORGE_ACTIVE_PER_SIDE + c;
        const uint8_t byte_a = b->tail.attract_source[fa];
        b->tail.attract_source[fa] = b->tail.attract_source[fc];
        b->tail.attract_source[fc] = byte_a;
    }
    /* trap_source (partially trapped, data/conditions.ts:235, :238: the trapper's Pokemon object, source.isActive) follows the
     * trapper. leech_seed_source is NOT relinked: the seed's sourceSlot is a slot (sim/pokemon.ts:2002, sourceSlot = source.getSlot();
     * data/moves.ts:10218, the drain goes to getAtSlot(sourceSlot)), so the seed stays on the flat position it was set on. */
    const uint32_t up = side * DUOFORGE_ACTIVE_PER_SIDE + a + 1u;
    const uint32_t pp = side * DUOFORGE_ACTIVE_PER_SIDE + c + 1u;
    for (uint32_t f = 0u; f < DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE; ++f) {
        dfi_tail_pos *tp = &b->tail.sides[f / DUOFORGE_ACTIVE_PER_SIDE].positions[f % DUOFORGE_ACTIVE_PER_SIDE];
        if ((uint32_t)tp->trap_source == up) {
            tp->trap_source = (uint8_t)pp; /* wide-operands-reviewed: a flat position + 1 */
        } else if ((uint32_t)tp->trap_source == pp) {
            tp->trap_source = (uint8_t)up; /* wide-operands-reviewed: a flat position + 1 */
        }
    }
    const uint32_t e_a = dfi_party_entry(&b->tail, side, a);
    const uint32_t e_c = dfi_party_entry(&b->tail, side, c);
    dfi_party_put(&b->tail, side, a, e_c);
    dfi_party_put(&b->tail, side, c, e_a);
}

/* The swap of Ally Switch (sim/battle.ts swapPosition, sim/battle.ts:1588-1607; step G80, decision 0044 section 2). The two slots
 * of the user's side exchange their occupant with everything that goes with it: the slot record (stages, flags, stall, confusion,
 * charge, locked move and its target, move actions, switch flag, activation id), and the position's tail (the moves, the Follow Me
 * and Protect state, the Ally Switch counter, the stats-raised flag and the Dragon Cheer stage). What stays with the slot:
 * position_flags bit 0 (Healing Wish, a slot condition). A flat trapper or seeder named by another
 * position's trap_source follows the Pokemon to its new slot; a seed (leech_seed_source) stays on its slot. party_order entries 0 and 1
 * of the side swap.
 * Queued moves and switches of the two Pokemon follow them (their slot); the target of a queued move is a slot and does not change.
 * `|swap|` is the event SWAP: position the user's old slot, other the new one. The Healing Wish slot bit stays with the slot (see
 * decision 0044, "Healing Wish slot bit interaction": the Swap rule belongs to the Healing Wish step). */
static void dfi_ally_switch_swap(dfi_run *r, uint32_t user, uint32_t partner)
{
    struct duoforge_battle *b = r->b;
    const uint32_t side = user / 2u;
    const uint32_t us = user % 2u;
    const uint32_t ps = partner % 2u;
    dfi_swap_position_state(b, side, us, ps);
    for (uint32_t i = 0u; i < b->queue_len; ++i) {
        dfi_queue_record *q = &b->queue[i];
        if (q->side != side || (q->kind != DFI_Q_MOVE && q->kind != DFI_Q_SWITCH)) {
            continue; /* a replacement enters its slot and keeps it; an action of the two Pokemon follows them */
        }
        if (q->slot == us) {
            q->slot = (uint8_t)ps;
        } else if (q->slot == ps) {
            q->slot = (uint8_t)us;
        }
    }
    dfi_run_swap_scratch(r, user, partner);
    const duoforge_event e = dfi_ev(DUOFORGE_EVENT_SWAP, user, DUOFORGE_CAUSE_MOVE, DFI_MOVE_ALLYSWITCH, partner);
    dfi_emit(r, &e);
}

/* Ally Switch (data/moves.ts:302-357; step G80, decision 0044): the user's onPrepareHit (dfi_ally_switch_prepare), then onHit: the
 * other slot of its side must hold a standing Pokemon, else the move fails with `-fail|X|move: Ally Switch` and [still] (the cause
 * MOVE with Ally Switch, detail 0, lead's approval). A side whose partner may be Illusion (the Illusion row is unmodelled until
 * decision 0026) is refused with E_UNSUPPORTED before anything changes. The move's own fail (the failed roll) is dfi_fail_still. */
static duoforge_status dfi_run_ally_switch(dfi_run *r, uint32_t user, bool *ok, bool *hit_ran)
{
    struct duoforge_battle *b = r->b;
    const uint32_t partner = (user / 2u) * 2u + (1u - user % 2u);
    *ok = false;
    *hit_ran = false; /* true when the onHit ran (the hit loop's Updates follow it, even for the NOT_FAIL of no partner) */
    const dfi_member *um = dfi_at(b, user);
    const dfi_member *pm = dfi_at(b, partner);
    if ((um != NULL && dfi_ability(b, um, DFI_ABILITY_ILLUSION)) || (pm != NULL && dfi_ability(b, pm, DFI_ABILITY_ILLUSION))) {
        return DUOFORGE_E_UNSUPPORTED; /* Ally Switch with a possible Illusion holder: refused until decision 0026 lands */
    }
    bool passed = false;
    const duoforge_status st = dfi_ally_switch_prepare(r, user, &passed);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (!passed) {
        dfi_fail_still(r, user); /* -fail|X with [still]: the consecutive roll failed; PrepareHit fails, no hit loop (no Update) */
        return DUOFORGE_OK;
    }
    if (!dfi_alive(b, partner)) {
        *hit_ran = true; /* onHit ran: -fail|X|move: Ally Switch, then the hit loop's Updates (the caller) */
        const duoforge_event f = dfi_ev(DUOFORGE_EVENT_FAIL, user, DUOFORGE_CAUSE_MOVE, DFI_MOVE_ALLYSWITCH, DUOFORGE_NO_POSITION);
        dfi_emit(r, &f);
        dfi_still(r);
        /* The pin's onHit returns NOT_FAIL here (data/moves.ts:326-328), not false: hitStepMoveHitLoop drops the target without
         * atLeastOneFailure (sim/battle-actions.ts:605-606, 616), so moveThisTurnResult becomes null, not false. The PrepareHit
         * failure above is the one that returns false (dfi_fail_still). */
        r->mres |= DFI_MRES_NULL;
        return DUOFORGE_OK;
    }
    if (dfi_ally_swap_wish_blocked(b, user / 2u, user % 2u, partner % 2u)) {
        /* a pending Healing Wish on either slot: the arrival's onSwap would heal it (data/moves.ts:8366-8377), not modelled in
         * batch 8 (decision 0044, known gap): refused explicitly, never guessed */
        return DUOFORGE_E_UNSUPPORTED;
    }
    dfi_ally_switch_swap(r, user, partner);
    *ok = true;
    return DUOFORGE_OK;
}

/* Yawn (data/moves.ts:21131-21162, no Champions change; accuracy true: no draw). Its own onTryHit fails the move
 * (-fail|user with [still]) for a target that has a status or is immune to sleep (no marked ability, item or type of
 * the pool is: the Immunity handlers of Insomnia, Vital Spirit, Sweet Veil and Comatose are unmarked; Electric Terrain's
 * refusal is below and Misty Terrain's sleep refusal is in dfi_try_status). addVolatile order (sim/pokemon.ts:1983-1994):
 * a target that yawns already is refused first and silently (no onRestart: -fail|user [still], the move's own fail);
 * then TryAddVolatile, where the Pokemon's effects run before the field (speed, sim/battle.ts:1001-1003): Flower Veil of
 * the target's side blocks it on a Grass type (-block, then the move did nothing; data/abilities.ts:1445-1452), and
 * Electric Terrain blocks it on a grounded target (-activate|target|move: Electric Terrain, return null;
 * data/moves.ts:4525-4530). Both blocks return null, and the move's hit then has result false with no line of its
 * own (no [still], no -fail): so moveThisTurnResult is false (moveHit's didSomething null -> false, the target drops out
 * of the hit list, and atLeastOneFailure keeps the result from becoming null: sim/battle-actions.ts:1298-1300, 616, 374).
 * Electric Terrain does not block a target that is not grounded (a Flying type, a Levitate holder), nor a semi-invulnerable
 * one: the pin's test is `!target.isSemiInvulnerable()` (data/moves.ts:4525; step G58, dfi_semi_invulnerable), added to
 * the grounded test of Electric Terrain below.
 * Otherwise -start|target|move: Yawn|[of] user, and the target falls asleep at the end of the next turn
 * (duration 2, the residual at order 23: the Yawn pass of dfi_residual). True when it started. */
static duoforge_status dfi_yawn(dfi_run *r, uint32_t user, uint32_t flat, bool *started)
{
    *started = false;
    struct duoforge_battle *b = r->b;
    const dfi_member *tm = dfi_at(b, flat);
    dfi_tail_pos *tail = &b->tail.sides[flat / 2u].positions[flat % 2u];
    if (tm == NULL || tm->hp == 0u) {
        return DUOFORGE_OK;
    }
    if (tm->status != DFI_STATUS_NONE) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    /* addVolatile: a target that yawns already is refused silently before TryAddVolatile (the fix of G31's second bug:
     * this check was after Flower Veil's block, which made a yawning Grass target print -block; recorded in
     * g31_yawn_flower_veil_yawning). */
    if (tail->yawn_turns != 0u) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    /* TryAddVolatile, the target's own effects first: Leaf Guard (step G83, data/abilities.ts:2300-2305, onTryAddVolatile) refuses
     * the yawn volatile in sun with -immune and [from] ability: Leaf Guard, and returns null (the move's hit has no line of its own,
     * as the blocks below). With a Flower Veil holder on the side the order of the two is not modelled (E_UNSUPPORTED). */
    if (dfi_ability(b, tm, DFI_ABILITY_LEAFGUARD)) {
        bool sun = false;
        const duoforge_status lg = dfi_leaf_guard_sun(r, &sun);
        if (lg != DUOFORGE_OK) {
            return lg;
        }
        if (sun) {
            uint32_t veil_holder = 0u;
            if (dfi_flower_veil_holder(b, flat, &veil_holder)) {
                return DUOFORGE_E_UNSUPPORTED;
            }
            dfi_immune(r, flat, 1u + DFI_ABILITY_LEAFGUARD);
            return DUOFORGE_OK;
        }
    }
    /* Purifying Salt (A2a, decision 0015 entry 5dy; data/abilities.ts:3625-3630, onTryAddVolatile): the yawn volatile is refused
     * with -immune|target|[from] ability: Purifying Salt and null, Leaf Guard's refusal without the sun test, with the same
     * Flower Veil order refusal (E_UNSUPPORTED). */
    if (dfi_ability(b, tm, DFI_ABILITY_PURIFYINGSALT)) {
        uint32_t veil_holder = 0u;
        if (dfi_flower_veil_holder(b, flat, &veil_holder)) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        dfi_immune(r, flat, 1u + DFI_ABILITY_PURIFYINGSALT);
        return DUOFORGE_OK;
    }
    /* TryAddVolatile: Flower Veil of the target's side blocks it on a Grass type (-block, then the move did nothing);
     * the Pokemon's effects run before the field's, so Flower Veil comes before Electric Terrain. */
    uint32_t veil = 0u;
    if (dfi_flower_veil_holder(b, flat, &veil)) {
        dfi_flower_veil_block(r, flat, veil); /* -block only: neither [still] nor -fail (recorded in g31_yawn_flower_veil) */
        return DUOFORGE_OK;
    }
    /* Electric Terrain (step G31 fix, data/moves.ts:4525-4530): a grounded target does not take the volatile; the line
     * is the move's cause and the terrain move as id2, as the sleep refusal's (recorded in g31_yawn_electric). The
     * result is false, as the Flower Veil block's. */
    if (b->terrain == DFI_TERRAIN_ELECTRIC && dfi_grounded(b, tm) && !dfi_semi_invulnerable(r, flat)) {
        const duoforge_event e =
            dfi_ev(DUOFORGE_EVENT_ACTIVATE, flat, DUOFORGE_CAUSE_MOVE, DFI_MOVE_ELECTRICTERRAIN, DUOFORGE_NO_POSITION);
        dfi_emit(r, &e);
        return DUOFORGE_OK;
    }
    tail->yawn_turns = (uint8_t)DFI_TAIL_YAWN_MAX; /* 2 */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_VOLATILE_START, flat);
    e.detail = (uint8_t)DUOFORGE_VOLATILE_YAWN;
    e.other = (uint8_t)user;
    dfi_emit(r, &e);
    *started = true;
    return DUOFORGE_OK;
}

/* Leech Seed (decision 0047; data/moves.ts:10202-10231): onTryImmunity refuses a Grass target (`-immune`, no volatile); the
 * volatile's source is the user's slot (addVolatile, sim/pokemon.ts:2000-2003). A target that already has a seed is not modelled
 * (the pin's addVolatile refusal is not verified): refused explicitly. The Substitute and Protect come before this (the generic
 * steps of the hit), since the move's flags are protect and no bypasssub. */
static duoforge_status dfi_leech_seed(dfi_run *r, uint32_t user, uint32_t flat, bool *started)
{
    struct duoforge_battle *b = r->b;
    *started = false;
    const dfi_member *tm = dfi_at(b, flat);
    dfi_tail_pos *tail = &b->tail.sides[flat / 2u].positions[flat % 2u];
    if (tm == NULL || tm->hp == 0u) {
        return DUOFORGE_OK;
    }
    if (dfi_has_type(b, tm, DFI_TYPE_GRASS)) {
        const duoforge_event im = dfi_ev(DUOFORGE_EVENT_IMMUNE, flat, DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION);
        dfi_emit(r, &im); /* -immune|target (onTryImmunity returns false; no volatile, no [still]) */
        r->mres |= DFI_MRES_FALSE; /* the failed TryImmunity is a false hit result (sim/battle-actions.ts): classified, no Updates */
        return DUOFORGE_OK;
    }
    if (tail->leech_seed_source != 0u) {
        /* A standing seed: addVolatile returns false (no onRestart, sim/pokemon.ts:1983-1984), so the hit fails: `|move|...Leech Seed||
         * [still]` and `-fail` on the user, the seed unchanged (the trace g84_l7_second_seed: the drain goes on). As Yawn's refusal,
         * the result is false and the hit loop runs no Updates (nothing started). */
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    tail->leech_seed_source = (uint8_t)(user + 1u); /* wide-operands-reviewed: the source's flat position + 1 (0047) */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_VOLATILE_START, flat);
    e.detail = (uint8_t)DUOFORGE_VOLATILE_LEECH_SEED;
    e.other = (uint8_t)DUOFORGE_NO_POSITION;
    dfi_emit(r, &e); /* -start|target|move: Leech Seed (no [of]) */
    *started = true;
    return DUOFORGE_OK;
}

/* Cursed Body (POOL data, data/abilities.ts:784-797, onDamagingHit; no order, so it runs after Rough Skin's 1 and Rocky
 * Helmet's 2): a damaging hit that is not Struggle's (nor a max or future move: none in the format) at its holder makes
 * the attacker roll randomChance(3, 10) (random(10) < 3, one draw per hit target) and a success disables the attacker's
 * last move (the move it just used), unless the attacker already has Disable (checked before the roll: no draw then). A
 * fainted attacker still rolls (the roll comes first), and addVolatile then refuses it. */
static duoforge_status dfi_cursed_body(dfi_run *r, uint32_t user, uint32_t holder, uint32_t move_id)
{
    const dfi_tail_pos *tail = &r->b->tail.sides[user / 2u].positions[user % 2u];
    if (tail->disable_slot != 0u || move_id == DFI_MOVE_STRUGGLE) {
        return DUOFORGE_OK;
    }
    uint32_t roll = 0u;
    const duoforge_status st = dfi_draw(r->draws, DFI_SITE_CURSED_BODY, 0u, 10u, &roll);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (roll < 3u) {
        (void)dfi_disable_start(r, user, holder, true);
    }
    return DUOFORGE_OK;
}

/* Helping Hand (Team C, data/moves.ts:8573-8606). The TryHit step comes
 * first (sim/battle-actions.ts:643-653): Good as Gold stops a status move of
 * any other Pokemon, its ally's included (data/abilities.ts:1630-1636), with
 * -immune and no -fail. Then its own onTryHit fails unless the ally switched
 * in this turn (newlySwitched) or still has a move queued; then the ally
 * gets the volatile for this turn: [-singleturn] ally|Helping Hand|[of]
 * user. A second one on the same Pokemon in a turn (onRestart) would need a
 * second user, which doubles never has. */
static duoforge_status dfi_run_helping_hand(dfi_run *r, uint32_t user, uint32_t ally)
{
    if (dfi_ability(r->b, dfi_at(r->b, ally), DFI_ABILITY_GOODASGOLD)) {
        dfi_immune(r, ally, 1u + DFI_ABILITY_GOODASGOLD); /* the move steps stop: no Update */
        r->mres |= DFI_MRES_FALSE; /* the TryHit of the ally returns false: the move fails */
        return DUOFORGE_OK;
    }
    dfi_active_slot *pos = dfi_pos(r->b, ally);
    if (((uint32_t)pos->flags & DFI_VOL_NEWLY_SWITCHED) == 0u && dfi_will_move(r->b, ally) == NULL) {
        dfi_fail_still(r, user); /* the hit loop stops at its first hit */
        return DUOFORGE_OK;
    }
    if (((uint32_t)pos->flags & DFI_VOL_HELPING_HAND) != 0u) {
        return DUOFORGE_E_INVARIANT;
    }
    pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_HELPING_HAND); /* wide-operands-reviewed: < 256 */
    duoforge_event e = dfi_ev(DUOFORGE_EVENT_SINGLE_TURN, ally, DUOFORGE_CAUSE_NONE, 0u, user);
    e.id = (uint16_t)DFI_MOVE_HELPINGHAND;
    dfi_emit(r, &e);
    return dfi_status_hit_end(r);
}

/* Coaching (step G19, data/moves.ts:2590-2605): a status move of the adjacent ally (target adjacentAlly, accuracy true,
 * no protect flag: Protect does not stop it) whose primary boosts, Attack and Defense by 1, go to that ally. With no
 * standing ally it fails before this point (dfi_no_target, as Helping Hand). The TryHit step comes first: Good as Gold
 * stops a status move of any other Pokemon, its ally's included, with -immune and no -fail. The boosts are the ally's own
 * (a Contrary or Simple ally changes them; Defiant and Competitive only answer a drop caused by a foe), so they take
 * the ordinary path, with the user as the source; `-boost|ally|atk|1`, `-boost|ally|def|1`. */
static duoforge_status dfi_run_coaching(dfi_run *r, uint32_t user, uint32_t ally, const dfi_move_data *md)
{
    if (dfi_invulnerable_to(r, user, ally, DFI_MOVE_COACHING)) {
        /* The Invulnerability step (step G58) comes before Good as Gold's TryHit: a -miss, and nothing else. */
        duoforge_event *mv = dfi_last_move(r);
        if (mv != NULL) {
            mv->flags = (uint8_t)((uint32_t)mv->flags | DUOFORGE_EVENT_FLAG_MISS); /* wide-operands-reviewed */
        }
        const duoforge_event miss = dfi_ev(DUOFORGE_EVENT_MISS, user, DUOFORGE_CAUSE_NONE, 0u, ally);
        dfi_emit(r, &miss);
        r->mres |= DFI_MRES_FALSE;
        return DUOFORGE_OK;
    }
    if (dfi_ability(r->b, dfi_at(r->b, ally), DFI_ABILITY_GOODASGOLD)) {
        dfi_immune(r, ally, 1u + DFI_ABILITY_GOODASGOLD); /* the move steps stop: no Update */
        r->mres |= DFI_MRES_FALSE; /* the TryHit of the ally returns false: the move fails */
        return DUOFORGE_OK;
    }
    if (dfi_boost(r, ally, md->boosts, user, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_PRIMARY))) {
        return dfi_status_hit_end(r);
    }
    r->mres |= DFI_MRES_FALSE; /* nothing changed: the hit returns false (runMoveEffects) */
    return DUOFORGE_OK; /* the hit loop stops */
}

/* Clangorous Soul (step G34, data/moves.ts:2498-2526; the Champions mod makes its accuracy true, mods/champions/moves.ts:121-124):
 * onTry fails the move (-fail, [still]) when the user's HP is at most 33 percent of its maximum (or the maximum is 1);
 * onTryHit boosts the user by +1 in all five stats (-boost lines; nothing changed ends the move without a line) and deletes
 * the boosts; onHit then costs it directDamage(floor(maxhp * 33 / 100)), at least 1, shown as a plain -damage. The Update of
 * the hit follows. */
static duoforge_status dfi_run_clangorous_soul(dfi_run *r, uint32_t user, const dfi_move_data *md)
{
    dfi_member *m = dfi_at(r->b, user);
    if ((uint32_t)m->hp * 100u <= (uint32_t)m->hp_max * 33u || m->hp_max == 1u) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    if (!dfi_boost(r, user, md->boosts, DFI_POSITIONS, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_PRIMARY))) {
        r->mres |= DFI_MRES_FALSE; /* nothing changed: the hit returns false (runMoveEffects) */
    return DUOFORGE_OK; /* the hit loop stops */
    }
    uint32_t cost = (uint32_t)m->hp_max * 33u / 100u;
    cost = cost == 0u ? 1u : cost;
    const duoforge_status st = dfi_deal(r, user, cost, DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION, DFI_DMG_DIRECT);
    if (st != DUOFORGE_OK) {
        return st;
    }
    return dfi_status_hit_end(r);
}

#include "combat/field/terrain_effects.h"

/* Rage Powder (step G30, data/moves.ts:14598-14630) is Follow Me with one more condition: it shares the position's
 * DFI_VOL_FOLLOW_ME bit, and the last move of the position tells them apart (dfi_last_move_id: the volatile is set by the
 * move that the occupant is using this turn). Its onTry and its condition have the text of Follow Me's (the generator
 * checks it); the redirection (onFoeRedirectTarget) asks that the attacker is not immune to powder: runStatusImmunity
 * ('powder'), which is a Grass type, or Overcoat (Safety Goggles are not in the pool).
 *
 * Follow Me (Team C, data/moves.ts:6039-6074). Its onTry needs two active
 * Pokemon per side (activePerHalf > 1), which doubles always has; its target
 * is the user, so Psychic Terrain and Protect never stop it. The volatile
 * lasts this turn: [-singleturn] user|move: Follow Me. The user cannot hold
 * it already: one action per turn, and the residual ends it. */
static duoforge_status dfi_run_follow_me(dfi_run *r, uint32_t user, uint32_t move_id)
{
    if (dfi_context_singles(r->ctx)) {
        /* Singles (decision 0083): onTry returns activePerHalf > 1, false; trySpreadMoveHit shows -fail with [still]
         * (sim/battle-actions.ts trySpreadMoveHit, the Try event). */
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    dfi_active_slot *pos = dfi_pos(r->b, user);
    if (((uint32_t)pos->flags & DFI_VOL_FOLLOW_ME) != 0u) {
        return DUOFORGE_E_INVARIANT;
    }
    pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_FOLLOW_ME); /* wide-operands-reviewed: < 256 */
    duoforge_event e = dfi_ev(DUOFORGE_EVENT_SINGLE_TURN, user, DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION);
    e.id = (uint16_t)move_id;
    dfi_emit(r, &e);
    return dfi_status_hit_end(r);
}

/* A move that heals its user by a fraction of the maximum HP (Recover: heal:
 * [1, 2], data/moves.ts:14806-14820; the fraction is the heal column dfi_pool_move_heal).
 * runMoveEffects (sim/battle-actions.ts:1201-1222): at full HP [-fail|user|heal]
 * with [still] (the event is a plain FAIL), otherwise Battle.heal of
 * Math.round(baseMaxhp * a / b), at least 1, shown as a plain [-heal]. The
 * heal goes through dfi_heal, the one place that every kind of healing (items,
 * drain, this move) passes, where Heal Block refuses it (dfi_heal_blocked). A
 * blocked user never gets here: its heal moves are disabled in the request and
 * stopped before the move (the heal flag, flags2 bit 2: [cant] Heal Block). */
/* The heal of a heal move by the fraction num/den of the target's maximum HP (step G54: Heal Pulse, 1/2, at the table's
 * rounding: Math.round, which is Math.ceil for the halves of Heal Pulse's Math.ceil(baseMaxhp * 0.5), at least 1). */
static duoforge_status dfi_run_heal_fraction(dfi_run *r, uint32_t num, uint32_t den, bool still, uint32_t user,
                                             uint32_t move_id, const uint32_t *targets, uint32_t count);
static void dfi_try_hit_abilities(dfi_run *r, uint32_t user, const uint32_t *targets, uint32_t count, bool *hit,
                                  const dfi_move_data *md, uint32_t move_id, uint32_t move_type, uint32_t *accuracy);

static duoforge_status dfi_run_heal_move(dfi_run *r, uint32_t user, uint32_t move_id, const uint32_t *targets,
                                         uint32_t count)
{
    /* A heal move reaches its targets through trySpreadMoveHit (sim/battle-actions.ts:550-620), so a target other than the user
     * runs its TryHit abilities first (hitStepTryHitEvent, :643-652; data/abilities.ts onTryHit: `target !== source`), as in the
     * hit steps: decision 0015 entry 5ed (#641). For Life Dew (Water, Status, target allies) at its ally that is Good as Gold's
     * -immune (data/abilities.ts:1630-1636) and Water Absorb's heal by a quarter with [of] the user, or -immune at full HP or
     * under Heal Block (:5363-5376, A2a's branch); the handler returns null, so the ally leaves the targets (a literal false of
     * the hit steps) before the heal loop, and the user's heal and the [spread] list see only the targets left. The user's own
     * TryHit is not asked. No accuracy is read after it (Life Dew's accuracy is true). Heal Pulse ran the hit steps already. */
    bool hit[DFI_POSITIONS] = {true, true, true, true};
    uint32_t left[DFI_POSITIONS] = {0u, 0u, 0u, 0u};
    uint32_t n = 0u;
    uint32_t no_accuracy = 0u;
    dfi_try_hit_abilities(r, user, targets, count, hit, &dfi_pool_moves[move_id], move_id,
                          dfi_move_type_now(r, dfi_at(r->b, user), &dfi_pool_moves[move_id]), &no_accuracy);
    for (uint32_t i = 0u; i < count; ++i) {
        if (hit[i]) {
            left[n] = targets[i];
            n += 1u;
        } else {
            r->mres |= DFI_MRES_FALSE; /* a TryHit stop is a failure of the hit steps (atLeastOneFailure) */
        }
    }
    return dfi_run_heal_fraction(r, dfi_pool_move_heal[move_id][0], dfi_pool_move_heal[move_id][1], true, user, move_id,
                                 left, n);
}

static duoforge_status dfi_run_heal_fraction(dfi_run *r, uint32_t num, uint32_t den, bool still, uint32_t user,
                                             uint32_t move_id, const uint32_t *targets, uint32_t count)
{
    bool did = false;
    bool full_hp_fail = false; /* Heal Pulse (!still) at full HP: its onHit's NOT_FAIL, see the tail */
    /* moveHit's heal, once per target in the order of the list (sim/battle-actions.ts:1201-1222; Life Dew, step G32, heals
     * the user and its standing ally, each at its own full-HP check and with its own -fail or -heal line). A target under
     * Heal Block that is not the user is refused (the heal is `false`, which the engine does not show for an ally). */
    for (uint32_t i = 0u; i < count; ++i) {
        const uint32_t t = targets[i];
        dfi_member *m = dfi_at(r->b, t);
        if (m == NULL || m->hp == 0u) {
            continue;
        }
        if (m->hp >= m->hp_max) {
            if (still) {
                dfi_fail_still(r, t);
            } else {
                dfi_emit_plain(r, DUOFORGE_EVENT_FAIL, t); /* Heal Pulse: -fail|X|heal, no [still] (data/moves.ts:8418-8420) */
                full_hp_fail = true;
            }
            continue;
        }
        if (dfi_heal_blocked(r->b, t)) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        uint32_t amount = ((uint32_t)m->hp_max * num * 2u + den) / (2u * den); /* Math.round(hp_max * num / den) */
        /* Heal Pulse of a user with Mega Launcher (step G59, data/moves.ts:8410): this.heal(this.modify(target.baseMaxhp, 0.75)),
         * i.e. the three quarters of the target's maximum HP by the modifier's rounding (dfi_modify, 3072/4096). */
        if (move_id == DFI_MOVE_HEALPULSE && dfi_ability(r->b, dfi_at(r->b, user), DFI_ABILITY_MEGALAUNCHER)) {
            amount = dfi_modify((uint32_t)m->hp_max, 3072u);
        }
        amount = amount < 1u ? 1u : amount;
        dfi_heal(r, t, amount, DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION);
        did = true;
    }
    /* The `[spread]` list of the move line is the move's hitTargets after the hit steps (sim/battle-actions.ts:614-618): when
     * the heal did something for at least one target every target stays in it, a target at full HP too, and when it did
     * nothing for any the list is empty (the move line keeps its [spread] with no slot). The list is of the targets left after
     * the TryHit abilities (dfi_run_heal_move): a spread move whose ally a TryHit stopped keeps its [spread] with the user alone. */
    {
        duoforge_event *mv = dfi_last_move(r);
        if (mv != NULL && (mv->flags & DUOFORGE_EVENT_FLAG_SPREAD) != 0u) {
            uint32_t mask = 0u;
            for (uint32_t i = 0u; did && i < count; ++i) {
                mask |= 1u << targets[i];
            }
            mv->amount = (uint8_t)mask; /* < 16 */
        }
    }
    /* spreadMoveHit's `if (!moveDamage.some(val => val !== false)) break;` (data/mods/champions/scripts.ts:526, the Champions hit
     * loop; its Update is at :537) leaves the hit loop before that Update when every target's value is a literal false. For
     * Recover, Roost and Life Dew (still) a target at full HP gives that false (moveData.heal, sim/battle-actions.ts:1201-1208):
     * no Update, so no Sitrus Berry check. Heal Pulse (not still) is different: its onHit returns NOT_FAIL at full HP
     * (data/moves.ts:8408-8421, the value is '' and not false), so the loop does run both Updates and the result is TRUE. */
    /* Roost (step G42): selfDrops applies its self volatile only to a target that did not fail (battle-actions.ts:1088-1096),
     * after the heal's line and before the hit end. A full-HP user gets no volatile and a false result. */
    if (did && move_id == DFI_MOVE_ROOST) {
        const dfi_tail_pos *tail = &r->b->tail.sides[user / 2u].positions[user % 2u];
        if ((tail->single_turn & DFI_SINGLE_TURN_ROOST) != 0u) {
            return DUOFORGE_E_INVARIANT;
        }
        r->b->tail.sides[user / 2u].positions[user % 2u].single_turn |= DFI_SINGLE_TURN_ROOST;
        duoforge_event e = dfi_ev(DUOFORGE_EVENT_SINGLE_TURN, user, DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION);
        e.id = (uint16_t)move_id;
        dfi_emit(r, &e); /* -singleturn|user|move: Roost */
    }
    /* Heal Pulse at full HP for its one target is a hit that returns true (NOT_FAIL, see above): the same hit end as a heal. */
    if (!did && !full_hp_fail) {
        r->mres |= DFI_MRES_FALSE;
        return DUOFORGE_OK;
    }
    return dfi_status_hit_end(r);
}

/* queue.willMove (sim/battle-queue.ts:324-331): true with the index of the queued move of the Pokemon at `flat` in `*out`, false
 * when it has none. A fainted or empty
 * position has none (willMove's `pokemon.fainted`); the record must belong to the occupant (its activation), as `action.pokemon`
 * is that Pokemon. */
static bool dfi_queued_move_index(struct duoforge_battle *b, uint32_t flat, uint32_t *out)
{
    const dfi_member *m = dfi_at(b, flat);
    if (m == NULL || m->hp == 0u) {
        return false;
    }
    const dfi_active_slot *pos = dfi_pos(b, flat);
    for (uint32_t i = 0u; i < b->queue_len; ++i) {
        const dfi_queue_record *q = &b->queue[i];
        if (q->kind == DFI_Q_MOVE && (uint32_t)q->side * 2u + (uint32_t)q->slot == flat &&
            q->activation_id == pos->activation_id) {
            *out = i;
            return true;
        }
    }
    return false;
}

/* A successful hit of a single-target move that is not a damaging one (After You, Quash): the Champions hit loop runs the Update
 * after the hit (data/mods/champions/scripts.ts:537), then the faint lines and the Update after the damage check (:574; the
 * target's damage entry is 0 for an undefined hit result, so the check passes). Its hit result is undefined, not TRUE. A failed
 * hit (false) breaks the loop before either (:531-532) and shows nothing here. */
static duoforge_status dfi_after_hit_updates(dfi_run *r)
{
    const duoforge_status st = dfi_update(r);
    if (st != DUOFORGE_OK) {
        return st;
    }
    dfi_announce_faints(r, false);
    return dfi_update(r);
}

/* The queue record at `idx` goes to the front; the records before it move one place back, the rest keep their places
 * (battle-queue.ts prioritizeAction: splice out, unshift). */
static void dfi_queue_move_to_front(struct duoforge_battle *b, uint32_t idx)
{
    const dfi_queue_record q = b->queue[idx];
    for (uint32_t i = idx; i > 0u; --i) {
        b->queue[i] = b->queue[i - 1u];
    }
    b->queue[0] = q;
}

/* After You (step G62, decision 0015 entry 5az; data/moves.ts:195-218), onHit of its target: `if (this.activePerHalf === 1)
 * return false` is singles only, so the format is doubles and it never fails there. The target's queued move (willMove) is
 * prioritized (prioritizeAction: its order class becomes 3, the reserve DFI_QRES_PRIORITIZED) and the line is
 * `-activate|target|move: After You`. With no queued move (the target moved, fainted, or switches) the hit returns false.
 * The hit returns undefined on success (the move result stays unclassified, as Haze's). Its accuracy is true and it has no
 * protect flag: a Protect does not stop it, and the hit steps before this one (accuracy) are the generic ones. */
static duoforge_status dfi_run_after_you(dfi_run *r, uint32_t user, uint32_t move_id, const uint32_t *targets, uint32_t count,
                                         const bool *hit)
{
    if (count == 0u || !hit[0]) {
        return DUOFORGE_OK;
    }
    const uint32_t t = targets[0];
    uint32_t idx = 0u;
    /* Singles (decision 0083): `if (this.activePerHalf === 1) return false` comes first in onHit. */
    if (dfi_context_singles(r->ctx) || !dfi_queued_move_index(r->b, t, &idx)) {
        r->mres |= DFI_MRES_FALSE; /* onHit returns false */
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    /* prioritizeAction (sim/battle-queue.ts:282-292) removes the action and unshifts it: the front of the list, the rest in their
     * order. The sort's ties read the list's positions (a selection sort that swaps), so the record moves too. */
    dfi_queue_move_to_front(r->b, idx);
    r->b->queue[0].reserve = (uint8_t)(((uint32_t)r->b->queue[0].reserve & ~DFI_QRES_ORDER_MASK) | DFI_QRES_PRIORITIZED); /* wide-operands-reviewed: < 256 */
    const duoforge_event e = dfi_ev(DUOFORGE_EVENT_ACTIVATE, t, DUOFORGE_CAUSE_MOVE, move_id, DUOFORGE_NO_POSITION);
    dfi_emit(r, &e);
    return dfi_after_hit_updates(r);
}

/* Quash (step G62, decision 0015 entry 5az; data/moves.ts:14454-14475): a protect move, accuracy 100, whose onHit (doubles, as
 * After You) finds the target's queued move and gives it order 201 (reserve DFI_QRES_QUASHED): it goes after every other move of
 * the turn, and its line is `-activate|target|move: Quash`. No queued move: the hit returns false. */
static duoforge_status dfi_run_quash(dfi_run *r, uint32_t user, uint32_t move_id, const uint32_t *targets, uint32_t count,
                                     const bool *hit)
{
    if (count == 0u || !hit[0]) {
        return DUOFORGE_OK;
    }
    const uint32_t t = targets[0];
    uint32_t idx = 0u;
    /* Singles (decision 0083): `if (this.activePerHalf === 1) return false` comes first in onHit. */
    if (dfi_context_singles(r->ctx) || !dfi_queued_move_index(r->b, t, &idx)) {
        r->mres |= DFI_MRES_FALSE; /* onHit returns false */
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    r->b->queue[idx].reserve = (uint8_t)(((uint32_t)r->b->queue[idx].reserve & ~DFI_QRES_ORDER_MASK) | DFI_QRES_QUASHED); /* wide-operands-reviewed: < 256 */
    const duoforge_event e = dfi_ev(DUOFORGE_EVENT_ACTIVATE, t, DUOFORGE_CAUSE_MOVE, move_id, DUOFORGE_NO_POSITION);
    dfi_emit(r, &e);
    return dfi_after_hit_updates(r);
}

/* Haze (step G62, decision 0031; data/moves.ts:8156-8172, onHitField): the move prints `-clearallboost` (no position, no
 * cause, public), then clearBoosts for each of getAllActive(), which skips a fainted Pokemon (sim/battle.ts:1365-1375; the
 * default includeFainted is off). clearBoosts (sim/pokemon.ts:1232-1237) zeroes the seven boosts only: volatiles such as
 * Focus Energy and the stall counters stay. A standing active position is one whose member is alive (dfi_alive); the
 * stages go to DFI_STAGE_NEUTRAL. The hit returns undefined (no DFI_MRES bit: the move result stays unclassified, which
 * only Stomping Tantrum and Roost read, and they refuse). Haze has no protect flag, so Protect does not stop it. */
static duoforge_status dfi_run_haze(dfi_run *r)
{
    struct duoforge_battle *b = r->b;
    dfi_emit_plain(r, DUOFORGE_EVENT_CLEAR_ALL_BOOSTS, DUOFORGE_NO_POSITION);
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        if (!dfi_alive(b, flat)) {
            continue;
        }
        dfi_active_slot *pos = dfi_pos(b, flat);
        for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
            pos->stages[i] = (uint8_t)DFI_STAGE_NEUTRAL;
        }
    }
    return DUOFORGE_OK;
}

/* Heal Pulse's heal after the hit steps (step G54, data/moves.ts:8399-8428): a target that Protect (or an immunity) stopped is
 * not healed and shows no fail; the others heal by half of their maximum HP, or fail at full HP with the plain line. A user
 * with Mega Launcher heals by three quarters instead (step G59: the same entry's `source.hasAbility('megalauncher')` branch,
 * in dfi_run_heal_fraction). */
static duoforge_status dfi_run_heal_pulse(dfi_run *r, uint32_t user, const uint32_t *targets, const bool *hit, uint32_t count)
{
    uint32_t live[DFI_POSITIONS] = {0u, 0u, 0u, 0u};
    uint32_t n = 0u;
    for (uint32_t i = 0u; i < count; ++i) {
        if (hit[i]) {
            live[n] = targets[i];
            n += 1u;
        }
    }
    if (n == 0u) {
        return DUOFORGE_OK;
    }
    /* The user is read for the Mega Launcher branch of the heal, and by the Roost branch (which Heal Pulse is not) */
    return dfi_run_heal_fraction(r, 1u, 2u, false, user, DFI_MOVE_HEALPULSE, live, n);
}

/* Strength Sap (step G54, data/moves.ts:18174-18193, data/mods/champions/moves.ts:981-984): onHit. A target at -6 Attack fails
 * it (return false). Otherwise the target's Attack stat as it is now (the stage applied; getStat(atk, false, true) has no item
 * or ability modifier) is drained: the target's Attack falls one stage (boost with no effect of its own, the user as the
 * source, so Mirror Armor bounces it), then the user heals by that stat (heal(atk, source, target): the user, through
 * dfi_heal, so Heal Block refuses it). The move fails when neither the heal nor the drop did anything. */
static duoforge_status dfi_run_strength_sap(dfi_run *r, uint32_t user, const uint32_t *targets, uint32_t count,
                                            const bool *hit)
{
    struct duoforge_battle *b = r->b;
    if (count == 0u || !hit[0]) {
        return DUOFORGE_OK; /* a miss or a Protect: its line is shown by the hit loop */
    }
    const uint32_t t = targets[0];
    dfi_member *tm = dfi_at(b, t);
    dfi_active_slot *tp = dfi_pos(b, t);
    if (tm == NULL || tm->hp == 0u) {
        return DUOFORGE_OK;
    }
    /* A target at Attack -6 fails it (`if (target.boosts.atk === -6) return false`). The reference draws the accuracy first
     * and fails after it (tests/reference/traces/g54_strength_sap_b.json, step 7: ACCURACY, then -fail with [still]). */
    if (tp->stages[DFI_STAGE_ATK] == 0u) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    uint32_t atk = 0u;
    const duoforge_status st = dfi_staged_stat(tm, tp, 0u, &atk); /* index 0: attack */
    if (st != DUOFORGE_OK) {
        return st;
    }
    static const uint8_t atk_down[DFI_STAT_STAGE_COUNT] = {5u, 6u, 6u, 6u, 6u, 6u, 6u};
    const bool dropped = dfi_boost(r, t, atk_down, user, dfi_effect(DUOFORGE_CAUSE_NONE, 0u, DFI_BOOST_PRIMARY));
    dfi_member *um = dfi_at(b, user);
    const bool healed = um != NULL && um->hp != 0u && um->hp < um->hp_max && !dfi_heal_blocked(b, user);
    if (healed) {
        dfi_heal(r, user, atk, DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION);
    }
    if (!healed && !dropped) {
        dfi_fail_still(r, user); /* `!!(heal || success)` is false (data/moves.ts:18184-18187): the hit loop breaks, no Update */
        return DUOFORGE_OK;
    }
    /* `!!(...)` is true: the hit returns true, so the loop runs its two Updates (scripts.ts:537, :574) and the hit end
     * (data/moves.ts:18184-18190, data/mods/champions/scripts.ts:526). */
    return dfi_status_hit_end(r);
}

/* The recharge turn (step G17): the action {choice: 'move', moveid: 'recharge'} of a Pokemon with mustrecharge
 * (sim/side.ts:675-689). runMove (sim/battle-actions.ts:210-264) gets no target for it (the name is no move), asks
 * OverrideAction (Encore, :227-235: an Encored Pokemon has the action turned into the Encored move and a random target
 * for it, getRandomTarget, drawn before BeforeMove although the move is never used), and BeforeMove ends it
 * (dfi_before_move: cant|recharge, no PP, lastMove untouched). The caller counted the action (activeMoveActions). */
static duoforge_status dfi_run_recharge(dfi_run *r, uint32_t user)
{
    struct duoforge_battle *b = r->b;
    const dfi_tail_pos *tail = &b->tail.sides[user / 2u].positions[user % 2u];
    dfi_member *m = dfi_at(b, user);
    if (!dfi_kind_limits_of(r->ctx->data_kind).pool_rules || tail->must_recharge == 0u || m == NULL) {
        return DUOFORGE_E_INVARIANT; /* nothing but a recharging POOL occupant is offered this action */
    }
    /* Stalwart (issue 542): getTarget returns the action's original target, with no draw, while it is active (sim/battle.ts:
     * 2437-2447). That target is getAtLoc of the recharge action's location, the Pokemon's lastMoveTargetLoc (sim/side.ts:
     * 675-689, sim/battle-queue.ts:263-273, sim/pokemon.ts:913), which the state does not keep: whether runMove draws is not
     * known, so the turn is refused rather than guessed. */
    if (dfi_ability(b, m, DFI_ABILITY_STALWART)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    /* getTarget('recharge', the stored location) has no target class and takes getRandomTarget: a random foe (one draw with
     * two foes standing), before OverrideAction and BeforeMove; it decides nothing. */
    uint32_t ignored = 0u;
    duoforge_status st = dfi_resolve_target(r, user, DUOFORGE_TARGET_CLASS_NORMAL, &ignored);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (tail->encore_slot != 0u) {
        const uint32_t encored = dfi_move_of(m, (uint32_t)tail->encore_slot - 1u);
        st = dfi_resolve_target(r, user, dfi_pool_moves[encored].target_class, &ignored); /* the draw decides nothing */
        if (st != DUOFORGE_OK) {
            return st;
        }
    }
    bool can = false;
    st = dfi_before_move(r, user, DFI_MOVE_STRUGGLE, &dfi_pool_moves[DFI_MOVE_STRUGGLE], &can);
    dfi_destiny_bond_attempt(r, user, DFI_MOVE_STRUGGLE, can); /* step G76 */
    if (st == DUOFORGE_OK && !can) {
        r->mres |= DFI_MRES_NULL; /* mustrecharge's BeforeMove returns null (data/conditions.ts:367-377) */
    }
    return st != DUOFORGE_OK ? st : (can ? DUOFORGE_E_INVARIANT : DUOFORGE_OK);
}

/* The accuracy of an OHKO move (Sheer Cold, step G64; hitStepAccuracy's ohko branch, sim/battle-actions.ts:696-713): 30, or 20
 * when the user is not an Ice type (gen 7 on), with no stage and no ModifyAccuracy (the item and ability modifiers stay out),
 * plus the level difference, which is 0 here (every Champions Pokemon is level 50). The Accuracy event still runs: No Guard
 * and Glaive Rush's onAccuracy answer first, with no draw. The Ice-type target is judged by the caller (-immune [ohko]). */
static duoforge_status dfi_ohko_accuracy(dfi_run *r, uint32_t user, uint32_t target, bool sheer_cold, bool *out)
{
    struct duoforge_battle *b = r->b;
    *out = true;
    /* The level test of hitStepAccuracy (sim/battle-actions.ts:700-706): the accuracy gains the user's level minus the target's,
     * and an OHKO move against a higher target is -immune [ohko] without a draw. Every Pokemon is DFI_LEVEL, so the difference
     * is 0 and the higher-target branch is never taken; it is refused here, not played. */
    if (dfi_level_of(dfi_at(b, target)) > dfi_level_of(dfi_at(b, user))) {
        return DUOFORGE_E_INVARIANT;
    }
    if (dfi_ability(b, dfi_at(b, user), DFI_ABILITY_NOGUARD) || dfi_ability(b, dfi_at(b, target), DFI_ABILITY_NOGUARD)) {
        return DUOFORGE_OK;
    }
    if (b->tail.sides[target / 2u].positions[target % 2u].glaive_rush != 0u) {
        return DUOFORGE_OK;
    }
    /* accuracy 30, and for Sheer Cold (ohko 'Ice') 20 when the user is not an Ice type (gen 7 on); the stages are not read.
     * The OHKO moves with ohko true (step G92) have 30 flat. */
    const uint32_t accuracy = sheer_cold && !dfi_has_type(b, dfi_at(b, user), DFI_TYPE_ICE) ? 20u : 30u;
    return dfi_draw_chance(r->draws, DFI_SITE_ACCURACY, accuracy, 100u, out);
}

/* The accuracy check of one hit against one target (hitStepAccuracy, sim/battle-actions.ts:719-744; the loop of a move with
 * multiaccuracy makes the same one for each hit after the first, data/mods/champions/scripts.ts:481-510): No Guard on
 * either Pokemon and Glaive Rush's volatile on the target make the hit certain with no draw, otherwise the user's accuracy
 * stage minus the target's evasion stage (Darkest Lariat ignores evasion) scales the accuracy and one draw decides.
 * `base_accuracy` 0 is a move that never misses.
 *
 * `later_hit` is the check of the loop's multiaccuracy before the second and the third hit, which is NOT the first
 * hit's check: the Champions loop scales the accuracy by the two stages one after the other in floating point,
 * `accuracy /= boostTable[-boost]` or `*= boostTable[boost]` with the table [1, 4/3, 5/3, 2, 7/3, 8/3, 3] and no
 * floor (data/mods/champions/scripts.ts:481-510), where hitStepAccuracy floors the combined stage's product
 * (sim/battle-actions.ts:719-744), then randomChance(accuracy, 100) = random(100) < accuracy. With the accuracy 90 of
 * Triple Axel the real value is 90 x (3 or 3 + |a|) x ... / ..., a rational with the denominator (3 or 3 + a) x
 * (3 or 3 + e); the engine compares `v x D < N` exactly (the source lint has no floating point outside
 * state/tiebreak.c). tools/datagen/pool_families.js checkG33 proves that this equals the reference's
 * binary64 arithmetic for the accuracy 90 and every pair of stages (169 of 169; a stage -1 gives 67.5, which a plain integer
 * accuracy of 67 would miss on the value 67). */
static duoforge_status dfi_accuracy_check(dfi_run *r, uint32_t user, uint32_t target, const dfi_move_data *md,
                                          uint32_t base_accuracy, bool later_hit, bool *out)
{
    struct duoforge_battle *b = r->b;
    *out = true;
    if (base_accuracy == 0u) {
        return DUOFORGE_OK;
    }
    /* No Guard on the user or the target: the move cannot miss. */
    if (dfi_ability(b, dfi_at(b, user), DFI_ABILITY_NOGUARD) || dfi_ability(b, dfi_at(b, target), DFI_ABILITY_NOGUARD)) {
        return DUOFORGE_OK;
    }
    /* Glaive Rush's onAccuracy on the target (data/moves.ts:6647-6678): the move cannot miss, no draw
     * (sim/battle-actions.ts:736-738). */
    if (b->tail.sides[target / 2u].positions[target % 2u].glaive_rush != 0u) {
        return DUOFORGE_OK;
    }
    /* The user's accuracy stage minus the target's evasion, clamped. Unaware (step G65, data/abilities.ts:5214-5234, through
     * sim/battle-actions.ts:716-720): the target's holder zeroes the user's accuracy stage, the user's holder the target's
     * evasion; a self-target is not touched (the handler returns for its own holder). */
    const bool unaware_target = user != target && dfi_ability(b, dfi_at(b, target), DFI_ABILITY_UNAWARE);
    const bool unaware_user = user != target && dfi_ability(b, dfi_at(b, user), DFI_ABILITY_UNAWARE);
    const uint32_t acc = unaware_target ? DFI_BIAS6 : (uint32_t)dfi_pos(b, user)->stages[DFI_STAGE_ACCURACY];
    /* Darkest Lariat (Team C): ignoreEvasion (sim/battle-actions.ts:719). Keen Eye (step G51, data/abilities.ts:2260-2276,
     * onModifyMove: move.ignoreEvasion = true for the holder's own moves) sets the same flag, read by the same check, and so
     * does Illuminate's identical onModifyMove (A2a, data/abilities.ts:2047-2049). */
    const bool keen_eye_user = dfi_ability(b, dfi_at(b, user), DFI_ABILITY_KEENEYE) ||
                               dfi_ability(b, dfi_at(b, user), DFI_ABILITY_ILLUMINATE);
    const uint32_t eva = md->special == DFI_SPECIAL_DARKEST_LARIAT || keen_eye_user || unaware_user
                             ? DFI_BIAS6
                             : (uint32_t)dfi_pos(b, target)->stages[DFI_STAGE_EVASION];
    if (later_hit) {
        if (acc > DFI_BIAS6_MAX || eva > DFI_BIAS6_MAX) {
            return DUOFORGE_E_INVARIANT;
        }
        /* The loop applies ModifyAccuracy (Compound Eyes, Wide Lens: step G34) AFTER the stages, to the fractional accuracy,
         * and truncates; the first hit applies it before them (the chain above, already in `base_accuracy`). The two orders
         * differ and the second is not modelled, so a user with either is refused here, never played with the first's
         * arithmetic. */
        const dfi_member *shooter = dfi_at(b, user);
        if (dfi_ability(b, shooter, DFI_ABILITY_COMPOUNDEYES) || dfi_holds(b, shooter, DFI_ITEM_WIDELENS)) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        /* The same for the target's Snow Cloak in snow and Sand Veil in a sandstorm (step G39: 3277/4096 in the same event). */
        const dfi_member *victim = dfi_at(b, target);
        if ((dfi_field_weather(r) == DFI_WEATHER_SNOW && dfi_ability(b, victim, DFI_ABILITY_SNOWCLOAK)) ||
            (dfi_field_weather(r) == DFI_WEATHER_SAND && dfi_ability(b, victim, DFI_ABILITY_SANDVEIL))) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        /* And the target's Tangled Feet while it is confused (A2a: the same event, priority -1, after the stages). */
        if (dfi_pos(b, target)->confusion_turns != 0u && dfi_ability(b, victim, DFI_ABILITY_TANGLEDFEET)) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        /* And the target's Bright Powder (step G49): it is the same ModifyAccuracy event, after the stages. */
        if (dfi_holds(b, victim, DFI_ITEM_BRIGHTPOWDER)) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        /* The rational comparison below is proved for the accuracy 90 only (combat/moves/multiaccuracy.h, checkG33), and so is
         * Gravity's branch after it and its two binary64 exceptions (checkK4): any other base is refused here, before either
         * is reached. A new multiaccuracy move extends both proofs before it runs. */
        if (!dfi_multiaccuracy_proven(base_accuracy)) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        /* accuracy stage a = acc - 6: above 0 x (3 + a) / 3, otherwise x 3 / (3 - a); evasion stage e = eva - 6: above 0
         * x 3 / (3 + e), otherwise x (3 - e) / 3. */
        const uint32_t num_a = acc > DFI_BIAS6 ? 3u + (acc - DFI_BIAS6) : 3u;
        const uint32_t den_a = acc > DFI_BIAS6 ? 3u : 3u + (DFI_BIAS6 - acc);
        const uint32_t num_e = eva > DFI_BIAS6 ? 3u : 3u + (DFI_BIAS6 - eva);
        const uint32_t den_e = eva > DFI_BIAS6 ? 3u + (eva - DFI_BIAS6) : 3u;
        uint32_t numerator = base_accuracy * num_a * num_e; /* <= 100 x 9 x 9 */
        uint32_t denominator = den_a * den_e;               /* <= 81 */
        /* Step K4 (#475, Gravity): the later hit's ModifyAccuracy runs after the stages (sim/battle-actions.ts:935; the Champions
         * loop, data/mods/champions/scripts.ts:481-510). Gravity's chainModify([6840, 4096]) (data/moves.ts:7807-7810) only sets
         * the event's modifier, and runEvent applies that modifier only to an INTEGER value (sim/battle.ts:929-932). The stage
         * value is an integer when the rational is, with two exceptions for the accuracy 90 (the only proven base) where
         * binary64 rounds it off the integer (126.00000000000001 for stages -2 and -4, 490.00000000000006 for 4 and -4;
         * tools/datagen/pool_families.js checkK4). Both values are above 100, so every draw hits with or without the
         * modifier: the exception below is not observable and stays as the exact statement of the reference.
         * Then the value is trunc((trunc(acc x 6840) + 2047) / 4096) and the draw is v < that integer; otherwise nothing changes. */
        if (b->tail.gravity_turns != 0u && denominator != 0u && numerator % denominator == 0u) {
            /* stage a is -2 or 4 and stage e is -4, compared on the biased values (acc and eva are at least 0) */
            const bool float_off_integer = (acc + 2u == DFI_BIAS6 || acc == DFI_BIAS6 + 4u) && eva + 4u == DFI_BIAS6;
            if (!float_off_integer) {
                const uint32_t exact_floor = (numerator * 6840u) / denominator;
                numerator = (exact_floor + 2047u) / 4096u;
                denominator = 1u;
            }
        }
        uint32_t v = 0u;
        const duoforge_status st = dfi_draw(r->draws, DFI_SITE_ACCURACY, 0u, 100u, &v);
        if (st != DUOFORGE_OK) {
            return st;
        }
        *out = v * denominator < numerator;
        return DUOFORGE_OK;
    }
    uint32_t combined = acc + 12u - eva; /* 12 means 0 */
    combined = combined < 6u ? 6u : (combined > 18u ? 18u : combined);
    uint32_t accuracy = 0u;
    if (!dfi_stage_accuracy(base_accuracy, combined - 6u, &accuracy)) {
        return DUOFORGE_E_INVARIANT;
    }
    return dfi_draw_chance(r->draws, DFI_SITE_ACCURACY, accuracy, 100u, out);
}



/* A Pokemon that stands and has Pressure (step G53). */
static bool dfi_pressure_holder(struct duoforge_battle *b, uint32_t flat)
{
    const dfi_member *t = dfi_at(b, flat);
    return t != NULL && t->hp != 0u && dfi_ability(b, t, DFI_ABILITY_PRESSURE);
}

/* The extra PP of one move (step G53, Pressure: data/abilities.ts:3437-3444, onDeductPP returns 1 for a foe that is a target
 * of the move; useMoveInner sums the returns over `pressureTargets` and deducts them, sim/battle-actions.ts:473-484). The
 * pressure targets are the targets of getMoveTargets (sim/pokemon.ts:847-853), the ones after any redirection, except: a
 * foeSide move has none; a field move (target all) and a mustpressure move (the flag of the move table) count every standing
 * foe (foes(), sim/pokemon.ts:850-853). An ally, the user and a fainted holder count nothing (runEvent skips a fainted
 * holder). */
static uint32_t dfi_pressure_extra(struct duoforge_battle *b, uint32_t user, uint32_t cls, uint32_t move_id,
                                   const uint32_t *targets, uint32_t count)
{
    const uint32_t foes = (1u - user / 2u) * 2u; /* the first foe position */
    if ((dfi_pool_move_flags3[move_id] & DFI_MOVE_FLAG3_MUST_PRESSURE) != 0u || cls == DUOFORGE_TARGET_CLASS_ALL) {
        uint32_t holders = 0u;
        for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
            holders += dfi_pressure_holder(b, foes + slot) ? 1u : 0u;
        }
        return holders;
    }
    if (cls == DFI_TARGET_CLASS_FOE_SIDE) {
        return 0u;
    }
    uint32_t extra = 0u;
    for (uint32_t i = 0u; i < count; ++i) {
        if (targets[i] / 2u != user / 2u && dfi_pressure_holder(b, targets[i])) {
            extra += 1u;
        }
    }
    return extra;
}



/* Revival Blessing (decision 0025 item 6; data/moves.ts revivalblessing): onTryHit fails with a plain -fail when the user's
 * side has no fainted Pokemon. Otherwise the user's slot is flagged to switch at a PIVOT, with no check of a living reserve
 * (the request is made anyway); the revive comes with the answer (dfi_resume_pivot). */
static duoforge_status dfi_run_revival_blessing(dfi_run *r, uint32_t user)
{
    struct duoforge_battle *b = r->b;
    const uint32_t side = user / 2u;
    bool any = false;
    for (uint32_t x = 0u; x < DUOFORGE_MAX_ROSTER && x < b->sides[side].member_count; ++x) {
        const bool brought = ((uint32_t)b->sides[side].brought_mask >> x & 1u) != 0u;
        any = any || (brought && b->sides[side].members[x].hp == 0u);
    }
    if (!any) {
        /* the reference's line: no target, then -fail and [still] (the move line is kept with no target) */
        duoforge_event *mv = dfi_last_move(r);
        if (mv != NULL) {
            mv->other = (uint8_t)DUOFORGE_NO_POSITION; /* wide-operands-reviewed: a position or NO_POSITION, < 256 */
        }
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    dfi_pos(b, user)->switch_flag = DFI_SWITCH_REVIVE_BLESSING;
    /* The hit returns true (slotCondition's addSlotCondition true and selfSwitch, battle-actions.ts:1244-1247, 1290-1296; the
     * onTryHit returns undefined, true by singleEvent, sim/battle.ts:593-594): the hit loop's Updates (scripts.ts:537, :574)
     * run now, during the move, before the action epilogue's Update (sim/battle.ts:2860-2861) and the PIVOT request that
     * dfi_resume_pivot answers. */
    return dfi_status_hit_end(r);
}

static bool dfi_has_reserve(const struct duoforge_battle *b, uint32_t side);

/* The slot condition of a position: bit 0 of its position_flags (side.slotConditions[position], sim/side.ts:464-495). */
static bool dfi_wish_pending(const struct duoforge_battle *b, uint32_t flat)
{
    return (b->tail.sides[flat / 2u].positions[flat % 2u].position_flags & DFI_POSFLAG_HEALING_WISH) != 0u;
}

/* Healing Wish (data/moves.ts:8348-8382; decision 0045, step G82). onTryHit fails with [still] when the user's side has no living
 * bench (canSwitch, sim/battle.ts:1566-1586). Otherwise addSlotCondition: a position that already holds the wish refuses the
 * second one (sim/side.ts:474-476), and then the move does nothing more: no faint and no -fail (sim/battle-actions.ts:1287,
 * 1303-1306, selfdestruct skips it). A new wish sets bit 0 of the user's position, and the user faints (selfdestruct ifHit,
 * sim/battle-actions.ts:1287-1289). A hit that did something runs the Champions hit loop's Updates: the Update, the faint lines,
 * the Update (data/mods/champions/scripts.ts:537, :574), that is dfi_status_hit_end. A refused second wish runs none (the loop
 * breaks before :537, and :574 returns on the all-false damage). */
/* selfdestruct ifHit (sim/battle-actions.ts:1287-1289): the user faints in the hit. The check reads damage[i] from BEFORE this
 * hit's result is folded in (line 1299), and the first hit of the move has none (undefined), so a Healing Wish that is refused
 * as a second wish faints the user too (the trace of tests/reference/specs/g82_r3_second_wish_false: |move| then |faint|). */
static duoforge_status dfi_wish_user_faints(dfi_run *r, uint32_t user)
{
    struct duoforge_battle *b = r->b;
    dfi_member *m = dfi_at(b, user);
    if (m == NULL || m->hp == 0u) {
        return DUOFORGE_E_INVARIANT;
    }
    if (dfi_support.switching == 0u) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    m->hp = 0u;
    if (r->faint_count < DFI_POSITIONS) {
        r->faint_queue[r->faint_count] = user;
        r->faint_count += 1u;
        r->last_faint_by = user;
        r->last_faint_move = true;
    }
    return DUOFORGE_OK;
}

static duoforge_status dfi_run_healing_wish(dfi_run *r, uint32_t user)
{
    struct duoforge_battle *b = r->b;
    const uint32_t side = user / 2u;
    if (!dfi_has_reserve(b, side)) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    if (dfi_wish_pending(b, user)) {
        /* The second wish (decision 0045, corrected with the trace of g82_r3): addSlotCondition returns false (sim/side.ts:474-476),
         * the slot is unchanged, and the hit's result is false: the hit-result filter leaves no target and atLeastOneFailure keeps
         * moveThisTurnResult (sim/battle-actions.ts:616), and the wrapper stores FALSE (sim/battle-actions.ts:371-374). The user
         * still faints (selfdestruct, see dfi_wish_user_faints). The Champions loop breaks before its Updates (data/mods/champions/
         * scripts.ts:526: no hit, hit === 1 returns before the faint messages and the Updates at :537 and :574). No -fail line:
         * selfdestruct skips it (sim/battle-actions.ts:1303-1306). */
        r->mres |= DFI_MRES_FALSE;
        return dfi_wish_user_faints(r, user);
    }
    b->tail.sides[side].positions[user % 2u].position_flags =
        (uint8_t)(b->tail.sides[side].positions[user % 2u].position_flags | DFI_POSFLAG_HEALING_WISH); /* wide-operands-reviewed */
    const duoforge_status fs = dfi_wish_user_faints(r, user);
    if (fs != DUOFORGE_OK) {
        return fs;
    }
    return dfi_status_hit_end(r);
}

/* Double Shock's onTryMove (decision 0025, data/moves.ts:3954-3959): without the Electric type it fails, -fail and [still]
 * (*stopped). A user that has the type is played only as Pawmot with its own two types (dfi_double_shock_shape); any other
 * shape is refused, never guessed. Shared by the hit path and the no-target path, since TryMove runs before the no-targets
 * test (sim/battle-actions.ts:486-513). */
static duoforge_status dfi_double_shock_try(dfi_run *r, uint32_t user, bool *stopped)
{
    uint32_t own[2];
    dfi_types_of(r->b, dfi_at(r->b, user), own);
    *stopped = own[0] != DFI_TYPE_ELECTRIC && own[1] != DFI_TYPE_ELECTRIC;
    if (*stopped) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    return dfi_double_shock_shape(r->b, user) ? DUOFORGE_OK : DUOFORGE_E_UNSUPPORTED;
}

/* A move with nothing to hit: Showdown runs TryMove before the no-targets test (sim/battle-actions.ts:486-513), and the
 * target is not null there (the foe in slot 0 is an object even when it has fainted), so Double Shock's onTryMove fails
 * first (recorded: g50_double_shock_no_target). */
/* Substitute (decision 0032). Its HP is never in an event: the amount of a hit is hidden on both sides. The tail's position
 * field substitute_hp holds it (0: no Substitute). */
static uint16_t *dfi_sub_hp_of(struct duoforge_battle *b, uint32_t flat)
{
    return &b->tail.sides[flat / 2u].positions[flat % 2u].substitute_hp;
}

/* The partial trap (step G90, decision 0060): its four fields are the volatile. A silent end (the Substitute's start, a trapper that
 * left, a fainted trapper at the residual) clears them with no line. */
static void dfi_trap_clear(dfi_tail_pos *tp)
{
    tp->trap_turns = 0u;
    tp->trap_source = 0u;
    tp->trap_move = 0u;
    tp->trap_band = 0u;
    tp->trap_elapsed = 0u; /* step G90: the counter goes with the trap (decision 0060) */
}

/* The Substitute move (data/moves.ts:18314-18326 and 18328-18340): onTryHit fails in order (the Substitute is up, then the
 * user's HP is a quarter or less, or its maximum is 1), then the volatile starts with floor(maxhp / 4) HP, and onHit takes
 * directDamage(maxhp / 4) from the user (clamped to at least 1, sim/battle.ts:2215). */
/* Curse (decisions 0047 and 0063; the Champions override data/mods/champions/moves.ts:165-196). The variant is the user's type at
 * execution (onModifyMove, onTryHit and onHit read source.hasType('Ghost') then, not at the choice).
 * A user without the Ghost type is boosted, Speed -1 then Attack +1 and Defense +1 (the pin's order: the falls first,
 * negatives_first, sim/battle.ts boost table order), and no volatile is set. The target is the user (dfi_curse_targets).
 * A Ghost user: the target's Good as Gold refuses it (-immune, status move, `target !== source`); a target that has Curse
 * fails (-fail on the user, [still], no halving); otherwise onHit takes directDamage(maxhp / 2) from the user (at least 1,
 * floor), then, when the target is the user itself (a non-Ghost choice executed as Ghost), redirects to a random foe (one
 * RANDOM_TARGET draw, getRandomTarget), and the target gets the Curse (-start|X|Curse|[of] user, its flag). Protect does not
 * stop it (no protect flag), and it goes through a Substitute (bypasssub). A failed hit or an immune one returns before the hit
 * loop's Updates (dfi_status_hit_end is the success path). */
static duoforge_status dfi_run_curse(dfi_run *r, uint32_t user, uint32_t target, uint32_t count)
{
    struct duoforge_battle *b = r->b;
    if (!dfi_has_type(b, dfi_at(b, user), DFI_TYPE_GHOST)) {
        uint8_t stages[DFI_STAT_STAGE_COUNT];
        for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
            stages[i] = (uint8_t)DFI_STAGE_NEUTRAL;
        }
        stages[DFI_STAGE_SPE] = (uint8_t)(DFI_STAGE_NEUTRAL - 1u); /* wide-operands-reviewed: a stage of 5 */
        stages[DFI_STAGE_ATK] = (uint8_t)(DFI_STAGE_NEUTRAL + 1u); /* wide-operands-reviewed: a stage of 7 */
        stages[DFI_STAGE_DEF] = (uint8_t)(DFI_STAGE_NEUTRAL + 1u); /* wide-operands-reviewed: a stage of 7 */
        /* The boosts of the non-Ghost Curse have no [from] (its boost line is a bare -boost): cause NONE, not the move. The G86 rule in
         * dfi_boost names a move's own boost only where the line carries [from] move (Belly Drum's -setboost). */
        dfi_boost_effect eff = dfi_effect(DUOFORGE_CAUSE_NONE, 0u, DFI_BOOST_PRIMARY);
        eff.negatives_first = true;
        const bool any = dfi_boost(r, user, stages, user, eff);
        if (!any) {
            /* onHit returns the boost's result (champions/moves.ts:185): a failed hit breaks the hit loop before its Updates (:531-532).
             * The move line of a failed hit is [still] with no target (campaign seed 84, fz_84_267: `|move|p1a: Tauros|Curse||[still]`
             * after the three zero boosts and their -fail). */
            dfi_fail_line(r, user); /* -fail on the user (the boosts printed none), then [still] with no target */
            r->mres |= DFI_MRES_FALSE;
            return DUOFORGE_OK;
        }
        /* A successful hit: the hit loop's Update, the faint lines and the Update after (scripts.ts:537, :574). */
        return dfi_status_hit_end(r);
    }
    if (count != 1u || target >= DFI_POSITIONS) {
        return DUOFORGE_E_INVARIANT; /* dfi_curse_targets always leaves one target for a Ghost user */
    }
    if (target != user && dfi_invulnerable_to(r, user, target, DFI_MOVE_CURSE)) {
        /* The Invulnerability step (step G58, sim/battle-actions.ts:556) comes before Good as Gold's TryHit, as for Coaching: a
         * -miss and nothing else, so no HP cost and no curse (issue 522: a Ghost Curse into Phantom Force). */
        duoforge_event *mv = dfi_last_move(r);
        if (mv != NULL) {
            mv->flags = (uint8_t)((uint32_t)mv->flags | DUOFORGE_EVENT_FLAG_MISS); /* wide-operands-reviewed */
        }
        const duoforge_event miss = dfi_ev(DUOFORGE_EVENT_MISS, user, DUOFORGE_CAUSE_NONE, 0u, target);
        dfi_emit(r, &miss);
        r->mres |= DFI_MRES_FALSE;
        return DUOFORGE_OK;
    }
    /* TryHit: Good as Gold on a foe (data/abilities.ts:1630-1636): -immune, the status move stops, no Update */
    if (target != user && dfi_ability(b, dfi_at(b, target), DFI_ABILITY_GOODASGOLD)) {
        dfi_immune(r, target, 1u + DFI_ABILITY_GOODASGOLD);
        r->mres |= DFI_MRES_FALSE;
        return DUOFORGE_OK;
    }
    /* onTryHit (champions/moves.ts:178-180): the target already has Curse, so it fails: -fail on the user, [still] */
    if ((b->tail.sides[target / 2u].positions[target % 2u].position_flags & DFI_POSFLAG_CURSED) != 0u) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    /* hitStepTryImmunity (sim/battle-actions.ts:676-684), after TryHit: a Prankster-boosted Curse fails on a Dark foe, -immune and
     * nothing else, so no HP cost and no curse (issue 556: Mega Banette's Curse into Sharpedo), as in the general step. */
    if (target / 2u != user / 2u && dfi_ability(b, dfi_at(b, user), DFI_ABILITY_PRANKSTER) &&
        dfi_has_type(b, dfi_at(b, target), DFI_TYPE_DARK)) {
        dfi_immune(r, target, 0u);
        r->mres |= DFI_MRES_FALSE;
        return DUOFORGE_OK;
    }
    /* onHit: directDamage(source.maxhp / 2) to the user (sim/battle.ts directDamage: at least 1; no [from] on the line) */
    {
        const dfi_member *um = dfi_at(b, user);
        uint32_t amount = (uint32_t)um->hp_max / 2u;
        amount = amount == 0u ? 1u : amount;
        const duoforge_status cost = dfi_deal(r, user, amount, DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION, DFI_DMG_DIRECT);
        if (cost != DUOFORGE_OK) {
            return cost;
        }
    }
    uint32_t hit = target;
    if (target == user) {
        /* onHit: source.isAlly(target) is true for the user itself: getRandomTarget(source, 'Curse'), one draw over the foes */
        uint32_t v = DFI_POSITIONS;
        const duoforge_status st = dfi_random_foe(r, user / 2u, &v);
        if (st != DUOFORGE_OK) {
            return st;
        }
        if (v >= DFI_POSITIONS) {
            return DUOFORGE_E_INVARIANT; /* a foe stands: the battle has not ended */
        }
        hit = v;
    }
    /* addVolatile after delete: the flag is set and -start|X|Curse|[of] user shows, with or without an old Curse */
    b->tail.sides[hit / 2u].positions[hit % 2u].position_flags =
        (uint8_t)((uint32_t)b->tail.sides[hit / 2u].positions[hit % 2u].position_flags | DFI_POSFLAG_CURSED); /* wide-operands-reviewed */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_VOLATILE_START, hit);
    e.detail = (uint8_t)DUOFORGE_VOLATILE_CURSE;
    e.other = (uint8_t)user; /* -start|X|Curse|[of] source */
    dfi_emit(r, &e);
    return dfi_status_hit_end(r);
}

/* Curse's targets at execution (step G84b, decision 0063). runMove's own target is the class of runMove (dfi_user_target_class,
 * read before BeforeMove); this is the ModifyMove change of the Champions override, read after it. For a Ghost user:
 *   - its target is itself (a non-Ghost choice that executed as Ghost): kept, dfi_run_curse redirects it with one draw;
 *   - its target is an ally (the partner, or a fainted one, or no target): onModifyMove sets randomNormal, and
 *     battle-actions.ts useMove draws getRandomTarget twice (after singleEvent ModifyMove and after runEvent ModifyMove); the
 *     second draw is the target (verified by the trace of g84b_ally_random: two RANDOM_TARGET draws, one line).
 *   - a foe: kept, no draw.
 * A user without the Ghost type targets itself (onModifyMove sets 'self'), with no draw. */
static duoforge_status dfi_curse_targets(dfi_run *r, uint32_t user, uint32_t targets[DFI_POSITIONS], uint32_t *count)
{
    struct duoforge_battle *b = r->b;
    if (!dfi_has_type(b, dfi_at(b, user), DFI_TYPE_GHOST)) {
        targets[0] = user;
        *count = 1u;
        return DUOFORGE_OK;
    }
    const uint32_t side = user / 2u;
    const bool own = *count == 0u || (targets[0] / 2u == side);
    if (!own || (*count == 1u && targets[0] == user)) {
        return DUOFORGE_OK;
    }
    uint32_t first = DFI_POSITIONS;
    uint32_t second = DFI_POSITIONS;
    duoforge_status st = dfi_random_foe(r, side, &first);
    if (st != DUOFORGE_OK) {
        return st;
    }
    st = dfi_random_foe(r, side, &second);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (second >= DFI_POSITIONS) {
        return DUOFORGE_E_INVARIANT;
    }
    targets[0] = second;
    *count = 1u;
    return DUOFORGE_OK;
}

static duoforge_status dfi_run_substitute(dfi_run *r, uint32_t user)
{
    struct duoforge_battle *b = r->b;
    const dfi_member *m = dfi_at(b, user);
    uint16_t *sub = dfi_sub_hp_of(b, user);
    duoforge_event e;
    if (*sub != 0u) {
        e = dfi_ev(DUOFORGE_EVENT_FAIL, user, DUOFORGE_CAUSE_MOVE, DFI_MOVE_SUBSTITUTE, DUOFORGE_NO_POSITION);
        e.detail = (uint8_t)DUOFORGE_FAIL_SUBSTITUTE_EXISTS;
        dfi_emit(r, &e);
        /* onTryHit returns NOT_FAIL (data/moves.ts:18314-18318; hitStepTryHitEvent keeps '' at battle-actions.ts:650). The
         * reference's next Stomping Tantrum DOUBLES after this fail (trace h18_substitute_exists_stomping_sitrus_mirror, step
         * 3; the mutant that makes the result NULL leaves the power single and fails the replay), so the move result is FALSE
         * (doubling is `=== false`, data/moves.ts:18054). The line-by-line path from NOT_FAIL to FALSE through the empty target
         * list (battle-actions.ts:601-616, :371-374) is not traced here: the trace is the evidence. */
        r->mres |= DFI_MRES_FALSE;
        return DUOFORGE_OK;
    }
    /* source.hp <= source.maxhp / 4 (a fractional compare, so 4 * hp <= maxhp) or maxhp === 1 (data/moves.ts:18319) */
    if (4u * (uint32_t)m->hp <= (uint32_t)m->hp_max || m->hp_max == 1u) {
        e = dfi_ev(DUOFORGE_EVENT_FAIL, user, DUOFORGE_CAUSE_MOVE, DFI_MOVE_SUBSTITUTE, DUOFORGE_NO_POSITION);
        e.detail = (uint8_t)DUOFORGE_FAIL_SUBSTITUTE_WEAK;
        dfi_emit(r, &e);
        r->mres |= DFI_MRES_FALSE; /* the same NOT_FAIL as EXISTS (data/moves.ts:18319-18321): FALSE, see the EXISTS branch above */
        return DUOFORGE_OK;
    }
    const uint32_t quarter = (uint32_t)m->hp_max / 4u;
    /* volatileStatus: onStart sets the HP (floor(maxhp / 4)) and shows -start|X|Substitute, before onHit's cost */
    *sub = (uint16_t)quarter;
    e = dfi_ev(DUOFORGE_EVENT_VOLATILE_START, user, DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION);
    e.detail = (uint8_t)DUOFORGE_VOLATILE_SUBSTITUTE;
    dfi_emit(r, &e);
    /* onStart (data/moves.ts:18335-18340): a partial trap on the user ends with the Substitute, silently ([silent] line). */
    dfi_trap_clear(&b->tail.sides[user / 2u].positions[user % 2u]);
    /* onHit: the -damage line of the user has no [from] (sim/battle.ts directDamage, default branch) */
    /* onHit: the cost, inside spreadMoveHit, before the hit loop's Update (data/mods/champions/scripts.ts:537), and the
     * Update after the damage check (:574): both run on this success path, which gives the status result true. The two
     * fail paths above (EXISTS and WEAK) return NOT_FAIL from onTryHit (data/moves.ts:18314-18321); hitStepTryHitEvent keeps
     * that result as '' and the step loop drops the target before hitStepMoveHitLoop (sim/battle-actions.ts:602-611 the
     * loop and its break, 643-652 hitStepTryHitEvent, 577 the hit-loop step), so neither fail path runs an Update. dfi_status_hit_end is that pair of Updates (plus the faint check). */
    const duoforge_status cost = dfi_deal(r, user, quarter == 0u ? 1u : quarter, DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION, DFI_DMG_DIRECT);
    if (cost != DUOFORGE_OK) {
        return cost;
    }
    return dfi_status_hit_end(r);
}

/* Belly Drum (step G86, data/moves.ts:1216-1234; no Champions override, data/mods/champions/moves.ts has no entry). Its onHit
 * returns false, and the move fails with -fail|user and [still] (no Update), when the user has half its HP or less, Attack at
 * +6 or more, or a maximum HP of 1 (the Shedinja clause). Otherwise directDamage(maxhp / 2) (floor, clampIntRange; cause NONE
 * with no [from], sim/battle.ts:2207-2250) and boost({atk: 12}) capped at +6 (Battle.boost: one -setboost line with the new
 * stage, shown as the BOOST event of cause MOVE with the amount of the change). The directDamage sets no hurtThisTurn (the
 * pin's directDamage does not), which matters for Counter-like moves (G88, not here). A Contrary holder is refused: its
 * ChangeBoost reverses the +12 (sim/battle.ts:2032), a case this step does not model. The move result is TRUE after the
 * effect (dfi_status_hit_end), also when no foe is left for the boost (onHit then returns undefined, not false). */
static duoforge_status dfi_run_belly_drum(dfi_run *r, uint32_t user)
{
    struct duoforge_battle *b = r->b;
    const dfi_member *m = dfi_at(b, user);
    if (dfi_ability(b, m, DFI_ABILITY_CONTRARY)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    dfi_active_slot *pos = dfi_pos(b, user);
    /* target.hp <= target.maxhp / 2 (a fractional compare: 2 * hp <= maxhp); boosts.atk >= 6 (stages are biased by 6: 12 is +6). */
    if (2u * (uint32_t)m->hp <= (uint32_t)m->hp_max || pos->stages[DFI_STAGE_ATK] >= 12u || m->hp_max == 1u) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    const uint32_t half = (uint32_t)m->hp_max / 2u;
    const duoforge_status cost = dfi_deal(r, user, half, DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION, DFI_DMG_DIRECT);
    if (cost != DUOFORGE_OK) {
        return cost;
    }
    /* boost({atk: 12}): +12 in biased stages (6 + 12), capped at +6 by dfi_boost; the source is the holder itself. */
    static const uint8_t atk_twelve[DFI_STAT_STAGE_COUNT] = {18u, 6u, 6u, 6u, 6u, 6u, 6u};
    const dfi_boost_effect eff = dfi_effect(DUOFORGE_CAUSE_MOVE, DFI_MOVE_BELLYDRUM, DFI_BOOST_PRIMARY);
    (void)dfi_boost(r, user, atk_twelve, DFI_POSITIONS, eff);
    return dfi_status_hit_end(r);
}

/* Baton Pass (decision 0042; data/moves.ts:1092-1116, sim/battle-actions.ts:1290-1313). A status move on the user: onHit fails
 * with [still] when no switch is possible (the commanded case is unmarked), otherwise the user's slot is flagged to pivot, and
 * the switch that follows copies the leaver's volatiles (dfi_switch_in). The pin's self block skips the BeforeSwitchOut of the
 * switch; no BeforeSwitchOut handler is marked (Pursuit is not, decision 0042 section 3.4), so the engine runs none for it.
 * The no-reserve failure comes first; then the refusals of decision 0042 section 6, each one E_UNSUPPORTED (the cause is named here and in the test):
 *   - Encore or Disable on the passer (decision 0042 lead's B: the pin stores a move id, the receiver may not know it);
 *   - a move lock, a two-turn charge, a recharge or Protect on the passer (the pin copies these; no pool passer has one);
 *   - Illusion on the passer's side (decision 0026, until 0026 lands: the tail struct is written by the test only).
 * Transform and Imposter: unmarked (guard test), no engine state yet. */
static duoforge_status dfi_run_baton_pass(dfi_run *r, uint32_t user)
{
    struct duoforge_battle *b = r->b;
    const uint32_t side = user / DUOFORGE_ACTIVE_PER_SIDE;
    const uint32_t slot = user % DUOFORGE_ACTIVE_PER_SIDE;
    const dfi_tail_pos *tp = &b->tail.sides[side].positions[slot];
    const dfi_active_slot *act = dfi_pos(b, user);
    /* No reserve (or a commanded passer, unmarked): onHit fails first, cleanly (data/moves.ts:1097-1103): attrLastMove('[still]')
     * on the move line (no target shown: dfi_still), then -fail|user. The Hit event returns NOT_FAIL (data/moves.ts:1101),
     * the selfSwitch block combines false (sim/battle-actions.ts:1292-1295), so damage[0] is false in runMoveEffects
     * (combineResults keeps the boolean), and the hit loop breaks before its Updates (data/mods/champions/scripts.ts:526, the
     * fill at :544): no Update on this path. Nothing is copied, so no refusal below applies to it. */
    if (!dfi_can_switch(b, side)) {
        /* The move's result is false (issue 389; the selfSwitch block of runMoveEffects combines false, sim/battle-actions.ts:1292-
         * 1295, trySpreadMoveHit sets moveResult false, sim/battle-actions.ts:606-616): dfi_fail_still sets DFI_MRES_FALSE. */
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    /* The refusals of decision 0042 section 6: the pass would copy these states, and the engine does not model the copy of them. */
    if (tp->encore_slot != 0u || tp->disable_slot != 0u) {
        return DUOFORGE_E_UNSUPPORTED; /* Encore or Disable on the passer (decision 0042, lead's B) */
    }
    if (act->locked_move != 0u || act->charge_turns != 0u || tp->must_recharge != 0u ||
        (act->flags & DFI_VOL_PROTECT) != 0u || (act->flags & DFI_VOL_CHOICE_LOCK) != 0u) {
        return DUOFORGE_E_UNSUPPORTED; /* a lock, a charge, a recharge or Protect on the passer */
    }
    if (b->tail.sides[side].illusion.shown != 0u) {
        return DUOFORGE_E_UNSUPPORTED; /* Illusion on the passer's side (decision 0026, until 0026 lands) */
    }
    /* The PIVOT of the user's slot: runMoveEffects sets switchFlag = move.id after the hit (sim/battle-actions.ts:1290-1296,
     * 1311-1312, reached through data/mods/champions/scripts.ts:374). Success: onHit returns nothing, the hit is true
     * (sim/battle.ts singleEvent, relayVar true), damage[0] is true, so the hit loop runs its two Updates after the flag is set
     * and before the switch request, which is made after the action (sim/battle.ts:2877 switches, 2912 makeRequest):
     * data/mods/champions/scripts.ts:537 and :574, the same pair as dfi_status_hit_end. */
    dfi_pos(b, user)->switch_flag = DFI_SWITCH_BATON_PASS;
    return dfi_status_hit_end(r);
}

/* The Substitute of a target takes a hit of a move (decision 0032, data/moves.ts:18341-18366: onTryPrimaryHit, run for every
 * target that is not the user, before any effect of the hit). *taken = true: the hit goes to the Substitute and the target is
 * not hit (no damage, secondary, boost, status or contact effect). A status move prints the handler's -fail and [still] on the
 * user; its result is null in the pin, not false (the caller ends the hit as TRUE, see the move body). A damaging move
 * computes its damage as for the target (one roll, the target's resist berry not eaten), the Substitute loses at most its HP
 * of it, and the user takes the recoil and the drain of the damage the Substitute took. A move with flags.bypasssub (flags3 bit 2) and a
 * user with Infiltrator are not taken. */
static duoforge_status dfi_substitute_takes(dfi_run *r, uint32_t user, uint32_t target, uint32_t move_id,
                                            const dfi_move_data *md, uint32_t move_type, bool spread, bool status_move,
                                            bool *taken, uint32_t active)
{
    struct duoforge_battle *b = r->b;
    uint16_t *sub = dfi_sub_hp_of(b, target);
    *taken = false;
    if (target == user || *sub == 0u || (dfi_pool_move_flags3[move_id] & DFI_MOVE_FLAG3_BYPASSSUB) != 0u ||
        dfi_ability(b, dfi_at(b, user), DFI_ABILITY_INFILTRATOR)) {
        return DUOFORGE_OK;
    }
    *taken = true;
    if (status_move) {
        /* the handler's `-fail|source` and [still] (data/moves.ts:18341-18347): a status move has no damage (getDamage undefined),
         * and the handler returns null, so the move's result is not false (the caller ends the hit as true). */
        dfi_fail_line(r, user);
        return DUOFORGE_OK;
    }
    uint32_t dealt = 0u;
    bool sub_crit = false; /* a critical hit on a Substitute never reaches the holder's Anger Point: no Hit event (step G77) */
    r->sub_hit = true;
    r->sub_active = active;
    const duoforge_status st = dfi_get_damage(r, user, target, md, move_type, spread, &dealt, &sub_crit);
    r->sub_hit = false;
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (dealt > (uint32_t)*sub) {
        dealt = (uint32_t)*sub; /* the damage is capped at the Substitute's HP (data/moves.ts:18351-18353) */
    }
    *sub = (uint16_t)((uint32_t)*sub - dealt); /* wide-operands-reviewed: dealt <= *sub <= 65535, the difference fits 16 bits */
    if (*sub == 0u) {
        /* the break: a one-hit KO (Sheer Cold, step G64) shows a bare `-ohko` first, which carries no state and is dropped by the
         * converter (tools/reference/trace_to_c.py, the sub-break form), then removeVolatile's -end line (onEnd) */
        duoforge_event end = dfi_ev(DUOFORGE_EVENT_VOLATILE_END, target, DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION);
        end.detail = (uint8_t)DUOFORGE_VOLATILE_SUBSTITUTE;
        dfi_emit(r, &end);
    } else {
        /* the absorbed hit: `-activate|X|move: Substitute|[damage]`, with no amount */
        const duoforge_event act = dfi_ev(DUOFORGE_EVENT_ACTIVATE, target, DUOFORGE_CAUSE_MOVE, DFI_MOVE_SUBSTITUTE,
                                          DUOFORGE_NO_POSITION);
        dfi_emit(r, &act);
    }
    /* Rock Head cancels a recoil move's recoil on the user (data/abilities.ts rockhead, onDamage with effect 'recoil' returns null,
     * except Struggle): applyRecoilDamage calls battle.damage(recoil, pokemon, pokemon, 'recoil') (sim/battle-actions.ts:1391-1392)
     * from the totalDamage gate of the hit loop (data/mods/champions/scripts.ts:552-553). The same gate runs for a hit that a
     * Substitute took, so the cancel applies here as in the normal recoil path (turn.c, Rock Head, the recoil block of the hit loop). */
    if (dealt != 0u && md->recoil[1] != 0u && !dfi_ability(b, dfi_at(b, user), DFI_ABILITY_ROCKHEAD)) {
        /* applyRecoilDamage(damage, move, source): round(damage * recoil[0] / recoil[1]), at least 1 (sim/battle-actions.ts:1384) */
        uint32_t recoil = (dealt * md->recoil[0] * 2u + md->recoil[1]) / (2u * md->recoil[1]);
        recoil = recoil < 1u ? 1u : recoil;
        const duoforge_status rst = dfi_deal(r, user, recoil, DUOFORGE_CAUSE_RECOIL, 0u, DUOFORGE_NO_POSITION, DFI_DMG_RECOIL);
        if (rst != DUOFORGE_OK) {
            return rst;
        }
    }
    if (dealt != 0u && md->drain[1] != 0u) {
        /* heal(Math.ceil(damage * drain[0] / drain[1]), source, target, 'drain') (data/moves.ts:18363) */
        const uint32_t amount = (dealt * md->drain[0] + md->drain[1] - 1u) / md->drain[1];
        dfi_heal(r, user, amount, DUOFORGE_CAUSE_DRAIN, 0u, target);
    }
    /* AfterSubDamage on the Substitute's holder (data/moves.ts:18368-18369, after the recoil and the drain): an Air Balloon pops.
     * Struggle's recoil is not in this function (the move body applies it after the hit loop), so for Struggle the pop waits
     * for that recoil: the move body pops it (step G67, measured in fz_6700000_3: Struggle, the sub's [damage], [from] recoil,
     * then -enditem). */
    /* The move's own AfterSubDamage first (singleEvent, data/moves.ts:18368): Stone Axe and Ceaseless Edge lay their hazard on the
     * user's foe side when the user still stands and has no Sheer Force (data/moves.ts stoneaxe and ceaselessedge
     * onAfterSubDamage; issue 518). The hit's own onAfterHit does not run for the Substitute's holder. */
    if ((md->special == DFI_SPECIAL_STONE_AXE || md->special == DFI_SPECIAL_CEASELESS_EDGE) && dfi_at(b, user)->hp != 0u &&
        !dfi_sf_strips(b, dfi_at(b, user), md)) {
        const uint32_t kind = md->special == DFI_SPECIAL_STONE_AXE ? DUOFORGE_SIDE_STEALTH_ROCK : DUOFORGE_SIDE_SPIKES;
        bool added = false;
        const duoforge_status hz = dfi_add_hazard(r, 1u - user / 2u, kind, &added);
        if (hz != DUOFORGE_OK) {
            return hz;
        }
    }
    /* Ice Spinner's onAfterSubDamage (data/moves.ts:9429-9433, issue 547): the terrain ends when the user has HP. */
    if (md->special == DFI_SPECIAL_ICE_SPINNER && dfi_at(b, user)->hp != 0u) {
        const duoforge_status ct = dfi_clear_terrain(r);
        if (ct != DUOFORGE_OK) {
            return ct;
        }
    }
    if ((md->flags & DFI_MOVE_FLAG_STRUGGLE_RECOIL) == 0u && dfi_holds(r->b, dfi_at(r->b, target), DFI_ITEM_AIRBALLOON)) {
        dfi_use_item(r, target);
    }
    return DUOFORGE_OK;
}

static duoforge_status dfi_no_target_or_try(dfi_run *r, uint32_t user, const dfi_move_data *md)
{
    if (md->special == DFI_SPECIAL_DOUBLE_SHOCK) {
        bool stopped = false;
        const duoforge_status ds = dfi_double_shock_try(r, user, &stopped);
        if (ds != DUOFORGE_OK || stopped) {
            return ds;
        }
    }
    return dfi_no_target(r, user);
}

/* runMove and useMove for one move action (sim/battle-actions.ts:210-548,
 * the hit steps at 550-620 and the Champions hit loop). */
static duoforge_status dfi_run_move(dfi_run *r, const dfi_queue_record *q, bool *ran);

/* Forced switches (step G46: the drag of Roar, Whirlwind, Dragon Tail, Circle Throw and the attacker of Red Card).
 * dfi_drag_blocked is DragOut of Suction Cups and Guard Dog (data/abilities.ts:4693-4698, :1728-1732): the holder's
 * onDragOut returns null and prints -activate, so no switch flag is set and nothing else shows. */
static bool dfi_drag_blocked(dfi_run *r, uint32_t flat)
{
    const dfi_member *m = dfi_at(r->b, flat);
    const uint32_t blockers[2] = {DFI_ABILITY_SUCTIONCUPS, DFI_ABILITY_GUARDDOG};
    for (uint32_t i = 0u; i < 2u; ++i) {
        if (m != NULL && m->hp != 0u && dfi_ability(r->b, m, blockers[i])) {
            const duoforge_event e =
                dfi_ev(DUOFORGE_EVENT_ACTIVATE, flat, DUOFORGE_CAUSE_ABILITY, 1u + blockers[i], DUOFORGE_NO_POSITION);
            dfi_emit(r, &e); /* [-activate] ability: Suction Cups / Guard Dog */
            return true;
        }
    }
    return false;
}

/* DragOut at the hit (battle-actions.ts:1356-1367, the forceSwitch step, after the damage and the secondaries): the target is
 * flagged for a drag when it stands, the user stands, and the target's side has a reserve (canSwitch) and no blocker says
 * no. The flag is pending until the phazing step after the action (step G46). */
static void dfi_drag_at_hit(dfi_run *r, uint32_t user, uint32_t target)
{
    const dfi_member *tm = dfi_at(r->b, target);
    const dfi_member *um = dfi_at(r->b, user);
    if (tm == NULL || tm->hp == 0u || um == NULL || um->hp == 0u || !dfi_can_switch(r->b, target / 2u)) {
        return;
    }
    if (!dfi_drag_blocked(r, target)) {
        r->drag_pending |= 1u << target;
    }
}

/* The forceSwitch of a status move (Roar, Whirlwind): each hit target with a reserve is dragged (DragOut at the hit). When
 * no hit target has a reserve, the move fails: -fail for the user and [still] (runMoveEffects, battle-actions.ts:1260-1262
 * hitResult = canSwitch, then 1306-1307; Champions reaches it through scripts.ts:374). Targets that were not hit do not count. */
static void dfi_force_switch_status(dfi_run *r, uint32_t user, const uint32_t *targets, bool *hit, uint32_t count)
{
    bool any_hit = false;
    bool any_reserve = false;
    for (uint32_t i = 0u; i < count; ++i) {
        if (hit[i]) {
            any_hit = true;
            any_reserve = any_reserve || dfi_can_switch(r->b, targets[i] / 2u);
        }
    }
    if (!any_hit) {
        return;
    }
    if (!any_reserve) {
        dfi_fail_still(r, user);
        for (uint32_t i = 0u; i < count; ++i) {
            hit[i] = false;
        }
        return;
    }
    for (uint32_t i = 0u; i < count; ++i) {
        if (hit[i]) {
            dfi_drag_at_hit(r, user, targets[i]);
        }
    }
}

/* Red Card (step G46, data/items.ts:5152-5171, AfterMoveSecondary of the holder): a damaging move that hit the holder, with
 * the holder and the attacker standing, the attacker active with a reserve and no switch flag pending on either, uses the
 * item ([-enditem] holder, [of] attacker, consumed even when the drag is then blocked) and the attacker's DragOut decides the
 * drag. Not for a Dragon Tail holder (its flag is pending), nor behind a Substitute (the engine has none: unsupported). */
static void dfi_red_card(dfi_run *r, uint32_t user, uint32_t holder)
{
    struct duoforge_battle *b = r->b;
    const dfi_member *hm = dfi_at(b, holder);
    const dfi_member *um = dfi_at(b, user);
    if (holder == user || hm == NULL || um == NULL || hm->hp == 0u || um->hp == 0u || !dfi_holds(b, hm, DFI_ITEM_REDCARD)) {
        return;
    }
    if (dfi_pos(b, user)->occupant == DFI_OCCUPANT_NONE || !dfi_can_switch(b, user / 2u) ||
        ((r->drag_pending >> user) & 1u) != 0u || ((r->drag_pending >> holder) & 1u) != 0u) {
        return;
    }
    dfi_use_item_of(r, holder, user);
    if (!dfi_drag_blocked(r, user)) {
        r->drag_pending |= 1u << user;
    }
}

static duoforge_status dfi_hazard_move(dfi_run *r, uint32_t user, const dfi_move_data *md)
{
    const uint32_t side = user / 2u;
    /* The four hazards (step G37): the move's own hit is addSideCondition on the foe's side (a foeSide move has no
     * Protect or accuracy step: tryMoveHit runs TryHitSide, which no pool handler answers); a condition that is at its
     * last layer fails the move like any side condition that is up (-fail, [still]); a new layer is -sidestart. */
    bool added = false;
    const duoforge_status hs = dfi_add_hazard(r, 1u - side, md->side_condition, &added);
    if (hs != DUOFORGE_OK) {
        return hs;
    }
    if (!added) {
        dfi_fail_still(r, user);
    } else {
        r->mres |= DFI_MRES_TRUE; /* addSideCondition succeeded */
    }
    return DUOFORGE_OK;
}

static const bool dfi_no_inv_miss[DFI_POSITIONS] = {false, false, false, false}; /* a holder that bounces: no Invulnerability step */
static duoforge_status dfi_protect_targets(dfi_run *r, uint32_t user, const uint32_t *targets, uint32_t count,
                                           const bool *guarded, const bool *inv_miss, bool psychic_block, bool *hit,
                                           const dfi_move_data *md)
{
    struct duoforge_battle *b = r->b;
    const uint32_t side = user / 2u;
    const dfi_member *m = dfi_at(b, user);
    duoforge_status st = DUOFORGE_OK;
    uint32_t stops = 0u; /* step G78: Protect stops of this move (two of a smart move are refused, R1) */
    for (uint32_t i = 0u; i < count; ++i) {
        const uint32_t t = targets[i];
        const dfi_active_slot *tp = dfi_pos(b, t);
        if (inv_miss[i]) {
            continue; /* the Invulnerability step stopped it: no TryHit of its own */
        }
        if (guarded[i]) {
            r->mres |= DFI_MRES_NULL; /* Wide Guard's TryHit returns NOT_FAIL (data/moves.ts:20838-20848) */
            continue;
        }
        /* psychicterrain's onTryHit returns for a semi-invulnerable target (data/moves.ts:14119): a No Guard charger is not blocked. */
        if (psychic_block && t / 2u != side && dfi_grounded(b, dfi_at(b, t)) && !dfi_semi_invulnerable(r, t)) {
            duoforge_event e = dfi_event_make(DUOFORGE_EVENT_BLOCKED, t);
            e.detail = (uint8_t)DUOFORGE_FIELD_PSYCHIC_TERRAIN; /* [-activate] move: Psychic Terrain */
            dfi_emit(r, &e);
            r->mres |= DFI_MRES_FALSE; /* its TryHit returns null, which the hit steps normalise to false (battle-actions.ts:650) */
            continue;
        }
        /* Step G66, King's Shield (protect_kind 2; data/moves.ts:9905-9955): checkMoveBypassesProtect with blockStatus false, so a
         * Status move passes it; a move without the protect flag passes every variant (the flag test above). */
        const uint32_t kind = r->b->tail.sides[t / 2u].positions[t % 2u].protect_kind;
        const bool kings_passes = kind == DFI_PROTECT_KINGS_SHIELD && md->category == DFI_CATEGORY_STATUS;
        const bool guard_up = (((uint32_t)tp->flags & DFI_VOL_PROTECT) != 0u) && ((md->flags & DFI_MOVE_FLAG_PROTECT) != 0u) && !kings_passes;
        /* Step K2 (Piercing Drill, data/abilities.ts:3282-3294): the holder's HitProtect returns false, so the check passes the
         * move: no block, no -activate, no punishment, and the hit's damage gets the bypass (dfi_get_damage). */
        if (guard_up && dfi_piercing_drill_passes(r->b, dfi_at(r->b, user), md)) {
            r->protect_bypass |= 1u << t;
            hit[i] = true;
            continue;
        }
        hit[i] = !guard_up;
        if (!hit[i]) {
            r->mres |= DFI_MRES_NULL; /* Protect's TryHit returns NOT_FAIL (data/moves.ts:13998): no failure */
            stops += 1u;
            if (r->smart) {
                r->smart = false; /* step G78: Protect's handler clears smartTarget and prints nothing (data/moves.ts:1010-1011) */
            } else {
                dfi_emit_plain(r, DUOFORGE_EVENT_BLOCKED, t); /* [-activate] move: Protect */
            }
            /* Step G20: the contact punishment of Spiky Shield, in the same onTryHit after the -activate line
             * (data/moves.ts:17550-17559; checkMoveMakesContact is the contact flag: Protective Pads are not in the
             * pool). It costs the attacker floor(maxHP / 8), at least 1, with [-damage] ... [from] Spiky Shield [of] the
             * holder (CAUSE_MOVE, the move in id2, the holder in other), also when the attacker is knocked out. Only the
             * Spiky Shield kind punishes (King's Shield, kind 2, drops Attack instead, below). */
            if (kind == DFI_PROTECT_SPIKY_SHIELD && (md->flags & DFI_MOVE_FLAG_CONTACT) != 0u) {
                const uint32_t spikes = (uint32_t)m->hp_max / 8u;
                st = dfi_deal(r, user, spikes == 0u ? 1u : spikes, DUOFORGE_CAUSE_MOVE, DFI_MOVE_SPIKYSHIELD, t, DFI_DMG_CONDITION);
                if (st != DUOFORGE_OK) {
                    return st;
                }
            }
            /* Step G94: Baneful Bunker's contact poison, in the same onTryHit after the -activate line (data/moves.ts:1022-1024):
             * source.trySetStatus('psn', target), the attacker poisoned by the holder as the source (its effect is the condition,
             * so the line is a plain -status and no [from]; dfi_try_status with the OTHER origin shows no -immune or -fail line).
             * Poison and Steel are immune (Team C's psn refusal), and the other status blockers are the existing ones. */
            if (kind == DFI_PROTECT_BANEFUL_BUNKER && (md->flags & DFI_MOVE_FLAG_CONTACT) != 0u) {
                st = dfi_try_status(r, user, DFI_STATUS_PSN, t, DFI_NO_SOURCE_MOVE, DFI_ORIGIN_OTHER, 0u);
                if (st != DUOFORGE_OK) {
                    return st;
                }
            }
            /* Step G66: King's Shield's contact drop, in the same onTryHit after the -activate line (data/moves.ts:9936-9941):
             * the attacker's Attack by -1, the holder as the source (Defiant, Competitive and Mirror Armor see it so). */
            if (kind == DFI_PROTECT_KINGS_SHIELD && (md->flags & DFI_MOVE_FLAG_CONTACT) != 0u) {
                static const uint8_t kings_drop[DFI_STAT_STAGE_COUNT] = {5u, 6u, 6u, 6u, 6u, 6u, 6u};
                (void)dfi_boost(r, user, kings_drop, t, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_PRIMARY));
            }
        }
    }
    /* step G78, R1 (decision 0043): Protect stopping both targets of a smart move: the second stop's line depends on the order
     * of two stopping handlers (a speed tie draws), not modelled. */
    if (stops >= 2u && md->special == DFI_SPECIAL_DRAGON_DARTS) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    return DUOFORGE_OK;
}

static void dfi_try_hit_abilities(dfi_run *r, uint32_t user, const uint32_t *targets, uint32_t count, bool *hit,
                                 const dfi_move_data *md, uint32_t move_id, uint32_t move_type, uint32_t *accuracy)
{
    struct duoforge_battle *b = r->b;
    const bool status_move = md->category == DFI_CATEGORY_STATUS;
    const bool powder_move = move_id != DFI_MOVE_STRUGGLE && (dfi_pool_move_flags2[move_id] & DFI_MOVE_FLAG2_POWDER) != 0u;
    uint32_t base_accuracy = *accuracy;
    /* TryHit after Protect: Flash Fire takes Fire moves (and starts its
     * boost), Lightning Rod takes Electric moves (Special Attack +1, the
     * attacker as source), Good as Gold takes status moves; only aimed at
     * the holder by another Pokemon. */
    for (uint32_t i = 0u; i < count; ++i) {
        const uint32_t t = targets[i];
        const dfi_member *tm = dfi_at(b, t);
        if (!hit[i] || t == user || tm == NULL) {
            continue;
        }
        if (dfi_ability(r->b, tm, DFI_ABILITY_FLASHFIRE) && move_type == DFI_TYPE_FIRE) {
            dfi_active_slot *tp = dfi_pos(b, t);
            /* -start ability: Flash Fire, or -immune when it is already on */
            if (((uint32_t)tp->flags & DFI_VOL_FLASH_FIRE) != 0u) {
                dfi_immune(r, t, 1u + DFI_ABILITY_FLASHFIRE);
            } else {
                dfi_emit_plain(r, DUOFORGE_EVENT_FLASH_FIRE, t);
            }
            tp->flags = (uint8_t)((uint32_t)tp->flags | DFI_VOL_FLASH_FIRE); /* wide-operands-reviewed */
            hit[i] = false;
            /* Its onTryHit sets move.accuracy = true on the shared active
             * move: the other targets of a spread move need no accuracy draw. */
            base_accuracy = 0u;
        } else if (dfi_ability(r->b, tm, DFI_ABILITY_LIGHTNINGROD) && move_type == DFI_TYPE_ELECTRIC) {
            static const uint8_t spa_up[DFI_STAT_STAGE_COUNT] = {6u, 6u, 7u, 6u, 6u, 6u, 6u};
            if (!dfi_boost(r, t, spa_up, user,
                           dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_LIGHTNINGROD, DFI_BOOST_PRIMARY))) {
                dfi_immune(r, t, 1u + DFI_ABILITY_LIGHTNINGROD);
            }
            hit[i] = false;
        } else if (dfi_ability(r->b, tm, DFI_ABILITY_GOODASGOLD) && status_move) {
            dfi_immune(r, t, 1u + DFI_ABILITY_GOODASGOLD);
            hit[i] = false;
        } else if (dfi_is_ohko(md) && dfi_ability(r->b, tm, DFI_ABILITY_STURDY)) {
            /* Sturdy's onTryHit (step G64, data/abilities.ts:4675-4680; every ohko move, step G92): an OHKO move is -immune with [from] ability: Sturdy, and
             * the hit returns null (no -fail). A target holds one ability, so no other holder's TryHit is in this branch. */
            dfi_immune(r, t, 1u + DFI_ABILITY_STURDY);
            hit[i] = false;
        } else if (dfi_ability(r->b, tm, DFI_ABILITY_BULLETPROOF) && (dfi_pool_move_flags3[move_id] & DFI_MOVE_FLAG3_BULLET) != 0u) {
            /* Step G83, Bulletproof (data/abilities.ts:480-491, onTryHit, breakable): a move with the bullet flag stops for its holder
             * with -immune and [from] ability: Bulletproof, and the TryHit returns null. The target takes no accuracy draw and no
             * draw after it (the hit step is before the accuracy step). No marked ability ignores breakable (no Mold Breaker family
             * in the pool). Its onTryHit runs after Protect (priority 3) and Magic Bounce (1): Protect's block above has hit false. */
            dfi_immune(r, t, 1u + DFI_ABILITY_BULLETPROOF);
            hit[i] = false;
        } else if (dfi_ability(r->b, tm, DFI_ABILITY_VOLTABSORB) && tm->hp != 0u && move_type == DFI_TYPE_ELECTRIC) {
            /* Volt Absorb (step G45, data/abilities.ts:5340-5353, onTryHit, breakable): an Electric move of another Pokemon,
             * a status move included, heals the holder by baseMaxHP / 4 through this.heal, whose source is the user (so
             * `[of]` shows) and whose TryHeal refuses at full HP and under Heal Block; when that heal does nothing it is
             * -immune|holder|[from] ability: Volt Absorb. The move is stopped for this target either way. */
            if (tm->hp >= tm->hp_max || dfi_heal_blocked(b, t)) {
                dfi_immune(r, t, 1u + DFI_ABILITY_VOLTABSORB);
            } else {
                dfi_heal(r, t, (uint32_t)tm->hp_max / 4u, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_VOLTABSORB, user);
            }
            hit[i] = false;
        } else if (tm->hp != 0u && ((dfi_ability(r->b, tm, DFI_ABILITY_WATERABSORB) && move_type == DFI_TYPE_WATER) ||
                                    (dfi_ability(r->b, tm, DFI_ABILITY_EARTHEATER) && move_type == DFI_TYPE_GROUND))) {
            /* Water Absorb and Earth Eater (A2a, decision 0015 entry 5dy; data/abilities.ts:5363-5376 and :1133-1146, onTryHit,
             * breakable, no Champions entry): Volt Absorb's callback word for word with a Water resp. Ground move and their own
             * names (gen_closure.py checks the texts), so Volt Absorb's branch with the type and the id. A Ground move reaches the
             * holder's TryHit before the type immunity (hitStepTryHitEvent before hitStepTypeImmunity), as in this order. */
            const uint32_t absorb = dfi_ability(r->b, tm, DFI_ABILITY_WATERABSORB) ? DFI_ABILITY_WATERABSORB
                                                                                   : DFI_ABILITY_EARTHEATER;
            if (tm->hp >= tm->hp_max || dfi_heal_blocked(b, t)) {
                dfi_immune(r, t, 1u + absorb);
            } else {
                dfi_heal(r, t, (uint32_t)tm->hp_max / 4u, DUOFORGE_CAUSE_ABILITY, 1u + absorb, user);
            }
            hit[i] = false;
        } else if (dfi_ability(r->b, tm, DFI_ABILITY_MOTORDRIVE) && move_type == DFI_TYPE_ELECTRIC) {
            /* Motor Drive (A2a, data/abilities.ts:2735-2747, onTryHit, breakable): an Electric move of another Pokemon raises
             * the holder's Speed by 1 (this.boost({ spe: 1 }): the event's target and source, the ability as the effect) or,
             * when that changes nothing (+6), -immune|holder|[from] ability: Motor Drive; the move stops either way. Lightning
             * Rod's TryHit above without the redirect. */
            static const uint8_t spe_up[DFI_STAT_STAGE_COUNT] = {6u, 6u, 6u, 6u, 7u, 6u, 6u};
            if (!dfi_boost(r, t, spe_up, user,
                           dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_MOTORDRIVE, DFI_BOOST_PRIMARY))) {
                dfi_immune(r, t, 1u + DFI_ABILITY_MOTORDRIVE);
            }
            hit[i] = false;
        } else if (dfi_ability(r->b, tm, DFI_ABILITY_TELEPATHY) && !status_move && t / 2u == user / 2u) {
            /* Telepathy (step G45, data/abilities.ts:4931-4942, onTryHit, breakable): a non-Status move of an ally (target !==
             * source, target.isAlly(source)) is stopped for the holder with -activate|holder|ability: Telepathy. A spread move
             * still hits the others. */
            const duoforge_event act = dfi_ev(DUOFORGE_EVENT_ACTIVATE, t, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_TELEPATHY,
                                              DUOFORGE_NO_POSITION);
            dfi_emit(r, &act);
            hit[i] = false;
        } else if (dfi_ability(r->b, tm, DFI_ABILITY_OBLIVIOUS) && move_id == DFI_MOVE_TAUNT) {
            /* Oblivious's onTryHit (step G47, data/abilities.ts:3018-3024): a Taunt aimed at the holder by another Pokemon is
             * -immune|holder|[from] ability: Oblivious and does nothing (breakable: no Mold Breaker is marked, so nothing
             * ignores it). Its Attract and Captivate halves need moves that are unmarked, so they are not modelled. */
            dfi_immune(r, t, 1u + DFI_ABILITY_OBLIVIOUS);
            hit[i] = false;
        } else if (powder_move && dfi_ability(r->b, tm, DFI_ABILITY_OVERCOAT) && !dfi_powder_natural_immune(b, tm)) {
            /* Overcoat's onTryHit (priority 1, step G30, data/abilities.ts:3112-3118): a powder move of another Pokemon
             * that a natural immunity does not stop already; the Grass-type holder is stopped by the plain -immune of
             * hitStepTryImmunity below. */
            dfi_immune(r, t, 1u + DFI_ABILITY_OVERCOAT);
            hit[i] = false;
        } else if (dfi_ability(r->b, tm, DFI_ABILITY_SOUNDPROOF) && (dfi_pool_move_flags2[move_id] & DFI_MOVE_FLAG2_SOUND) != 0u) {
            /* Soundproof's onTryHit (step G32, data/abilities.ts:4436-4452): a sound move aimed at the holder by another
             * Pokemon is -immune|holder|[from] ability: Soundproof and does nothing. */
            dfi_immune(r, t, 1u + DFI_ABILITY_SOUNDPROOF);
            hit[i] = false;
        }
    }
    /* Thunder Wave (step G68, data/moves.ts:19591-19606: ignoreImmunity false) is the one status move whose type immunity is
     * judged: hitStepTypeImmunity runs before the accuracy check, so a Ground target is -immune with no accuracy draw. */
    const bool thunder_wave = md->special == DFI_SPECIAL_THUNDER_WAVE;
    /* step G78: hitStepTypeImmunity prints with runImmunity(move, !smartTarget), the flag as the step starts; a drop clears it
     * after the step (sim/battle-actions.ts:607, :661). */
    const bool smart_step = r->smart;
    bool smart_dropped = false;
    for (uint32_t i = 0u; i < count && (!status_move || thunder_wave); ++i) { /* a status move ignores type immunity */
        if (!hit[i]) {
            continue;
        }
        const dfi_member *tm = dfi_at(b, targets[i]);
        /* Scrappy (step G39, data/abilities.ts:4079-4098, onModifyMove): ignoreImmunity for the Fighting and Normal types, so
         * a Ghost type is hit by them (its other type decides the effectiveness: an immunity adds nothing, dfi_type_mod). */
        const bool scrappy = dfi_ability(b, dfi_at(b, user), DFI_ABILITY_SCRAPPY) &&
                             (move_type == DFI_TYPE_NORMAL || move_type == DFI_TYPE_FIGHTING);
        /* Step G83, Iron Ball: runImmunity('Ground') asks isGrounded alone (sim/pokemon.ts:2252-2254), not the type chart, so an
         * Iron Ball holder is hit by a Ground move whatever its types and ability (the Flying component of the effectiveness
         * is still neutral: its chart immunity counts 0 in dfi_type_mod, as the holder's Effectiveness handler returns 0). */
        const bool iron_ground = move_type == DFI_TYPE_GROUND && tm != NULL && dfi_holds(b, tm, DFI_ITEM_IRONBALL);
        /* Step K4 (#475, sim/pokemon.ts:2149, :2252-2254): under Gravity every Pokemon is grounded, so runImmunity('Ground')
         * is isGrounded alone: no Flying chart immunity, no Levitate, no Air Balloon. The Iron Ball rule above is the same test. */
        const bool gravity_ground = move_type == DFI_TYPE_GROUND && tm != NULL && b->tail.gravity_turns != 0u;
        const bool ground_free = iron_ground || gravity_ground;
        if (!scrappy && !ground_free && dfi_type_immune(b, tm, move_type)) {
            hit[i] = false;
            smart_dropped = true;
            if (!smart_step) {
                dfi_immune(r, targets[i], 0u);
            }
        } else if (move_type == DFI_TYPE_GROUND && !ground_free && dfi_ability(b, tm, DFI_ABILITY_LEVITATE)) {
            /* runImmunity('Ground'): isGrounded is null for a Levitate holder (sim/pokemon.ts:2156), shown as
             * -immune|X|[from] ability: Levitate (:2257-2258); a Flying type is immune first, without the line. */
            hit[i] = false;
            smart_dropped = true;
            if (!smart_step) {
                dfi_immune(r, targets[i], 1u + DFI_ABILITY_LEVITATE);
            }
        } else if (move_type == DFI_TYPE_GROUND && !gravity_ground && dfi_holds(r->b, tm, DFI_ITEM_AIRBALLOON)) {
            /* step G67: isGrounded is false for an Air Balloon holder (sim/pokemon.ts:2159, `return item !== 'airballoon'`), so
             * runImmunity prints the plain -immune (its else branch, sim/pokemon.ts:2265); no [from]. */
            hit[i] = false;
            smart_dropped = true;
            if (!smart_step) {
                dfi_immune(r, targets[i], 0u);
            }
        }
    }
    if (smart_dropped) {
        r->smart = false; /* step G78: atLeastOneFailure clears smartTarget after the step */
    }
    *accuracy = base_accuracy;
}

static duoforge_status dfi_accuracy_targets(dfi_run *r, uint32_t user, const uint32_t *targets, uint32_t count,
                                           bool *hit, const dfi_move_data *md, uint32_t base_accuracy,
                                           bool acc_compound_eyes, bool acc_wide_lens, bool spread)
{
    struct duoforge_battle *b = r->b;
    duoforge_status st = DUOFORGE_OK;
    bool hit_pre_accuracy[DFI_POSITIONS];
    for (uint32_t i = 0u; i < DFI_POSITIONS; ++i) {
        hit_pre_accuracy[i] = hit[i];
    }
    if (base_accuracy != 0u) {
        for (uint32_t i = 0u; i < count; ++i) {
            if (!hit[i]) {
                continue;
            }
            if (dfi_is_ohko(md)) {
                /* OHKO (step G64; step G92 for ohko true): an Ice-type target is -immune with [ohko] and no draw (no miss line
                 * either; Sheer Cold only, the ohko 'Ice' test of hitStepAccuracy, sim/battle-actions.ts:703); otherwise the
                 * OHKO accuracy of dfi_ohko_accuracy, and a miss is the same -miss as any single-target move. */
                if (md->special == DFI_SPECIAL_SHEER_COLD && dfi_has_type(b, dfi_at(b, targets[i]), DFI_TYPE_ICE)) {
                    dfi_immune(r, targets[i], 0u);
                    hit[i] = false;
                    continue;
                }
                st = dfi_ohko_accuracy(r, user, targets[i], md->special == DFI_SPECIAL_SHEER_COLD, &hit[i]);
                if (st != DUOFORGE_OK) {
                    return st;
                }
                if (!hit[i]) {
                    duoforge_event *mv = dfi_last_move(r);
                    if (mv != NULL && !spread) {
                        mv->flags = (uint8_t)((uint32_t)mv->flags | DUOFORGE_EVENT_FLAG_MISS); /* wide-operands-reviewed */
                    }
                    const duoforge_event miss = dfi_ev(DUOFORGE_EVENT_MISS, user, DUOFORGE_CAUSE_NONE, 0u, targets[i]);
                    dfi_emit(r, &miss);
                }
                continue;
            }
            uint32_t move_accuracy = base_accuracy;
            {
                uint32_t acc_chain = 4096u;
                bool acc_ok = true;
                const dfi_member *acc_target = dfi_at(b, targets[i]);
                /* Step K4 (#475, data/moves.ts:7807-7810, the field's ModifyAccuracy with no priority: 0): Gravity's 6840/4096
                 * runs BEFORE the priority -1 modifiers (Compound Eyes, Snow Cloak, Sand Veil, data/abilities.ts:667, :4010,
                 * :4374) and the priority -2 group (Wide Lens, Bright Powder, data/items.ts:7713, :659), so it is the first step
                 * of the chain; sim/battle.ts:resolvePriority and comparePriority order the handlers by priority first. */
                if (base_accuracy != 0u && b->tail.gravity_turns != 0u) {
                    acc_ok = dfi_chain_modify(acc_chain, 6840u, &acc_chain);
                }
                if (acc_compound_eyes) {
                    acc_ok = dfi_chain_modify(acc_chain, 5325u, &acc_chain);
                }
                if ((dfi_field_weather(r) == DFI_WEATHER_SNOW && dfi_ability(r->b, acc_target, DFI_ABILITY_SNOWCLOAK)) ||
                    (dfi_field_weather(r) == DFI_WEATHER_SAND && dfi_ability(r->b, acc_target, DFI_ABILITY_SANDVEIL))) {
                    acc_ok = acc_ok && dfi_chain_modify(acc_chain, 3277u, &acc_chain);
                }
                /* Tangled Feet (A2a, decision 0015 entry 5dy; data/abilities.ts:4890-4902, onModifyAccuracyPriority -1, breakable):
                 * chainModify(0.5) while the target has the confusion volatile (confusion_turns), for a numeric accuracy only (the
                 * chain is not reached for an accuracy of true, base_accuracy 0). It is in the priority -1 group with Compound Eyes
                 * (the user's); 2048 is dyadic, so the two orders give the same chain from 4096 and from Gravity's 6840
                 * (tests/abilities/test_tangled_feet.c computes both). The target's one ability: never with Snow Cloak or Sand Veil. */
                if (base_accuracy != 0u && dfi_pos(b, targets[i])->confusion_turns != 0u &&
                    dfi_ability(r->b, acc_target, DFI_ABILITY_TANGLEDFEET)) {
                    acc_ok = acc_ok && dfi_chain_modify(acc_chain, 2048u, &acc_chain);
                }
                /* The priority -2 group (step G49): Wide Lens (the attacker, data/items.ts:7719-7726) and Bright Powder (the
                 * target, data/items.ts:665-670, chainModify([3686, 4096]), a number only) run in one event at the same
                 * priority, so the pin's order between them is the holders' Speed, and an exact tie draws. The chain rounds
                 * at each step, so the two orders agree only for some prefixes: when they differ the order is not modelled
                 * (E_UNSUPPORTED, never a guess). With no powder the chain is Wide Lens's alone. */
                const bool acc_bright_powder = base_accuracy != 0u && dfi_holds(r->b, acc_target, DFI_ITEM_BRIGHTPOWDER);
                if (acc_wide_lens && acc_bright_powder) {
                    uint32_t wide_first = acc_chain;
                    uint32_t powder_first = acc_chain;
                    acc_ok = acc_ok && dfi_chain_modify(acc_chain, 4505u, &wide_first) &&
                             dfi_chain_modify(wide_first, 3686u, &wide_first);
                    acc_ok = acc_ok && dfi_chain_modify(acc_chain, 3686u, &powder_first) &&
                             dfi_chain_modify(powder_first, 4505u, &powder_first);
                    if (!acc_ok) {
                        return DUOFORGE_E_INVARIANT;
                    }
                    /* The accuracy that the chain modifies is this move's own (base_accuracy, an integer): the orders agree
                     * when they give the same modified accuracy, which is all the stages read. */
                    if (dfi_modify(base_accuracy, wide_first) != dfi_modify(base_accuracy, powder_first)) {
                        return DUOFORGE_E_UNSUPPORTED; /* the two orders round apart for this move: not modelled */
                    }
                    acc_chain = wide_first;
                } else {
                    if (acc_wide_lens) {
                        acc_ok = acc_ok && dfi_chain_modify(acc_chain, 4505u, &acc_chain);
                    }
                    if (acc_bright_powder) {
                        acc_ok = acc_ok && dfi_chain_modify(acc_chain, 3686u, &acc_chain);
                    }
                }
                if (!acc_ok) {
                    return DUOFORGE_E_INVARIANT;
                }
                if (acc_chain != 4096u) {
                    move_accuracy = dfi_modify(base_accuracy, acc_chain);
                }
            }
            st = dfi_accuracy_check(r, user, targets[i], md, move_accuracy, false, &hit[i]);
            if (st != DUOFORGE_OK) {
                return st;
            }
            if (!hit[i]) {
                if (r->smart) {
                    r->smart = false; /* step G78: a smart move's first miss is silent (sim/battle-actions.ts:739-742) */
                } else {
                    /* [miss] on a single-target move's line, then -miss */
                    duoforge_event *mv = dfi_last_move(r);
                    if (mv != NULL && !spread) {
                        mv->flags = (uint8_t)((uint32_t)mv->flags | DUOFORGE_EVENT_FLAG_MISS); /* wide-operands-reviewed */
                    }
                    const duoforge_event miss = dfi_ev(DUOFORGE_EVENT_MISS, user, DUOFORGE_CAUSE_NONE, 0u, targets[i]);
                    dfi_emit(r, &miss);
                }
            }
        }
    }
    for (uint32_t i = 0u; i < count; ++i) {
        r->mres |= hit_pre_accuracy[i] && !hit[i] ? DFI_MRES_FALSE : 0u; /* a miss: the accuracy step is a literal false */
    }
    return DUOFORGE_OK;
}

static duoforge_status dfi_status_effects(dfi_run *r, uint32_t user, uint32_t move_id, const dfi_move_data *md,
                                         const uint32_t *targets, bool *hit, uint32_t count)
{
    struct duoforge_battle *b = r->b;
    dfi_member *m = dfi_at(b, user);
    dfi_active_slot *pos = dfi_pos(b, user);
    const uint32_t side = user / 2u;
    const bool status_move = md->category == DFI_CATEGORY_STATUS;
    duoforge_status st = DUOFORGE_OK;
    /* Confusion moves (step G92): whether a target refused the change without the terrain (a failed move: [still] and -fail,
     * the replay of g92_cr_hit and g92_flatter_teeter). */
    bool confuse_plain_fail = false;
    /* forceSwitch of a status move (Roar, Whirlwind; step G46), before its other effects (runMoveEffects, battle-actions.ts:1260). */
    if (status_move && (dfi_pool_move_flags2[move_id] & DFI_MOVE_FLAG2_FORCE_SWITCH) != 0u) {
        dfi_force_switch_status(r, user, targets, hit, count);
    }
    /* A status move's primary status (runMoveEffects); sleep draws its turns.
     * Parting Shot lowers Attack and Special Attack and, if a stat fell and
     * a reserve stands, flags its user to switch out (selfSwitch). */
    if (status_move) {
        bool did = false; /* Parting Shot's onHit always counts */
        for (uint32_t i = 0u; i < count; ++i) {
            if (!hit[i]) {
                continue;
            }
            if (md->special == DFI_SPECIAL_PARTING_SHOT) {
                static const uint8_t drop[DFI_STAT_STAGE_COUNT] = {5u, 6u, 5u, 6u, 6u, 6u, 6u};
                /* onHit (data/moves.ts:13174-13180): the selfSwitch is deleted when the boost changed nothing, unless the target
                 * has Mirror Armor (step G33), whose bounced drops are no change of the target's but keep the switch. */
                const bool success =
                    dfi_boost(r, targets[i], drop, user, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_PRIMARY));
                if ((success || dfi_ability(b, dfi_at(b, targets[i]), DFI_ABILITY_MIRRORARMOR)) && m->hp != 0u &&
                    dfi_can_switch(b, side)) {
                    pos->switch_flag = (uint8_t)DFI_SWITCH_MOVE;
                }
                did = true;
                continue;
            }
            if (md->special == DFI_SPECIAL_SOAK) {
                did = dfi_soak(r, targets[i], move_id) || did;
                continue;
            }
            if (md->special == DFI_SPECIAL_TAUNT) {
                did = dfi_taunt(r, user, targets[i]) || did;
                continue;
            }
            if (md->special == DFI_SPECIAL_DISABLE) {
                /* The move's own onTryHit (data/moves.ts:3658-3662) runs in spreadMoveHit, after the accuracy (recorded in
                 * g27_disable_b: the draw comes first): a target without a last move, or whose last move is Struggle, fails
                 * the move with -fail and [still]. Then the volatile's onStart fails it when it does not start (no PP
                 * left, already disabled). */
                const uint32_t last = b->tail.sides[targets[i] / 2u].positions[targets[i] % 2u].last_move;
                if (last == 0u || last == DFI_TAIL_MOVE_MAX) {
                    dfi_fail_still(r, user);
                } else if (dfi_disable_start(r, targets[i], DUOFORGE_NO_POSITION, false)) {
                    did = true;
                } else {
                    dfi_fail_still(r, user);
                }
                continue;
            }
            if (md->special == DFI_SPECIAL_SKILL_SWAP) {
                /* Skill Swap's onHit (step G70, decision 0041): the two abilities are exchanged, its own failure line is the
                 * move's [still]. */
                bool swapped = false;
                st = dfi_skill_swap(r, user, targets[i], move_id, &swapped);
                if (st != DUOFORGE_OK) {
                    return st;
                }
                did = did || swapped;
                continue;
            }
            if (md->special == DFI_SPECIAL_SPEED_SWAP) {
                /* Speed Swap's onHit (step K3, decision 0015 5de): the stored Speeds of the two are exchanged; it cannot fail. */
                st = dfi_speed_swap(r, user, targets[i]);
                if (st != DUOFORGE_OK) {
                    return st;
                }
                did = true;
                continue;
            }
            if (md->special == DFI_SPECIAL_TRICK || md->special == DFI_SPECIAL_SWITCHEROO) {
                bool swapped = false;
                st = dfi_trick(r, user, targets[i], move_id, &swapped);
                if (st != DUOFORGE_OK) {
                    return st;
                }
                did = did || swapped;
                continue;
            }
            if (md->special == DFI_SPECIAL_DRAGON_CHEER) {
                did = dfi_dragon_cheer(r, user, targets[i]) || did;
                continue;
            }
            if (md->special == DFI_SPECIAL_PSYCH_UP) {
                did = dfi_psych_up(r, user, targets[i]) || did;
                continue;
            }
            if (md->special == DFI_SPECIAL_ALLY_SWITCH) {
                /* self-targeted: the one target is the user (its ally is found in dfi_run_ally_switch) */
                bool swapped = false;
                bool hit_ran = false;
                st = dfi_run_ally_switch(r, user, &swapped, &hit_ran);
                if (st != DUOFORGE_OK) {
                    return st;
                }
                if (hit_ran) {
                    /* The partner-missing fail: the result stays NULL (dfi_run_ally_switch), and the hit loop's two Updates run
                     * (scripts.ts:537, :574); no generic else-branch (the FALSE bits of the hit targets) follows it. */
                    return dfi_status_updates(r);
                }
                if (swapped) {
                    r->mres |= DFI_MRES_TRUE;
                }
                did = swapped || did;
                continue;
            }
            if (md->special == DFI_SPECIAL_YAWN) {
                bool started = false;
                st = dfi_yawn(r, user, targets[i], &started);
                if (st != DUOFORGE_OK) {
                    return st;
                }
                did = did || started;
                continue;
            }
            if (md->special == DFI_SPECIAL_LEECH_SEED) {
                bool started = false;
                st = dfi_leech_seed(r, user, targets[i], &started);
                if (st != DUOFORGE_OK) {
                    return st;
                }
                did = did || started;
                continue;
            }
            if (md->special == DFI_SPECIAL_ENCORE) {
                bool started = false;
                st = dfi_encore(r, user, targets[i], &started);
                if (st != DUOFORGE_OK) {
                    return st;
                }
                did = did || started;
                continue;
            }
            if (md->special == DFI_SPECIAL_CONFUSE) {
                /* Confuse Ray, Swagger, Flatter and Teeter Dance (step G92, decision 0062): moveHit runs the boosts first
                 * (sim/battle-actions.ts:1197-1200, the target's, a move's own change), then the volatile, whose result
                 * joins the boosts' (:1236-1238). Swagger's attack +2 and Flatter's special attack +1 come through the
                 * PRIMARY_TARGET role, as Charm's do; a refused change does not stop the confusion. */
                bool changed_i = false;
                if (md->boost_role == DFI_BOOST_ROLE_PRIMARY_TARGET) {
                    changed_i = dfi_boost(r, targets[i], md->boosts, user, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_PRIMARY));
                }
                bool added = false;
                bool terrain = false;
                st = dfi_confuse_primary(r, targets[i], &added, &terrain);
                if (st != DUOFORGE_OK) {
                    return st;
                }
                /* The boost result (sim/battle.ts:2035, `let success = null`; set true only when a stat changed, :2042-2050; a
                 * boost at the cap prints -boost 0 and stays null, :2079-2080, returned at :2088) and the volatile's (false when
                 * already confused, true when started, null from Misty Terrain's onTryAddVolatile). combineResults
                 * (battle-actions.ts:1561-1573): true beats any, false beats null. So a target is false only when the volatile
                 * answers false and no boost changed: a capped boost with Misty (null + null) is null, not a failure. */
                if (!(changed_i || added) && !terrain) {
                    confuse_plain_fail = true;
                }
                did = did || added || changed_i;
                continue;
            }
            if (md->special == DFI_SPECIAL_MEMENTO) {
                /* Memento (step G92, decision 0062; data/moves.ts:11620-11638): the target's attack and special attack -2, then
                 * selfdestruct 'ifHit' (runMoveEffects, sim/battle-actions.ts:1287): the user faints when this target's
                 * damage is not false, which the hit steps decided, not the boosts (a refused boost still faints it). The
                 * faint is queued like Final Gambit's; the hit loop's Updates are the caller's (dfi_status_hit_end). */
                did = dfi_boost(r, targets[i], md->boosts, user, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_PRIMARY)) || did;
                st = dfi_queue_self_faint(r, user);
                if (st != DUOFORGE_OK) {
                    return st;
                }
                continue;
            }
            if (md->boost_role == DFI_BOOST_ROLE_PRIMARY_TARGET) {
                /* Charm and Fake Tears (step G39, data/moves.ts:2339-2355 and :5110-5126): the primary boosts go to the
                 * target (moveHit's boosts, isSecondary false): the changes go through the target's TryBoost handlers (Clear
                 * Body, Hyper Cutter, Flower Veil, Inner Focus's and Scrappy's, which are for Intimidate only) with a line for
                 * a stat that cannot change (-unboost ... 0); Defiant and Competitive answer a drop, Contrary reverses it. A
                 * move that changed nothing fails silently here like a self boost does (the hit loop stops). */
                did = dfi_boost(r, targets[i], md->boosts, user, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_PRIMARY)) || did;
                continue;
            }
            if (md->primary_status == DFI_STATUS_NONE && (dfi_pool_move_flags2[move_id] & DFI_MOVE_FLAG2_FORCE_SWITCH) != 0u) {
                /* a forced switch alone (Roar, Whirlwind; step G46): no status is set, and no [-status] line. The hit of the
                 * target is true when its side has a reserve (moveHit's hitResult = canSwitch, battle-actions.ts:1260-1262,
                 * kept by dfi_force_switch_status), whatever the drag then does: a blocker's DragOut answers null, not false
                 * (Suction Cups, Guard Dog; data/abilities.ts). So the hit loop of the Champions mod runs its Updates
                 * (data/mods/champions/scripts.ts:537 and :574), before the phazing (step G46). The DragOut that answers
                 * false (Commanding, data/conditions.ts:815-829) is not in the pool. */
                did = true;
                continue;
            }
            const uint32_t before = dfi_at(b, targets[i])->status;
            st = dfi_try_status(r, targets[i], md->primary_status, user, move_id, DFI_ORIGIN_MOVE, 0u);
            if (st != DUOFORGE_OK) {
                return st;
            }
            did = did || dfi_at(b, targets[i])->status != before;
        }
        if (md->special == DFI_SPECIAL_CONFUSE) {
            /* The spread list of a spread move (sim/battle-actions.ts:955-974, 1299, 605): once one target is affected, the hit
             * loop keeps every target that reached it (a refused one is damage 0, `md === true || !md ? 0 : md` at :963, which the
             * filter at :605 keeps), so the list is the hit mask set before the effects. Only when no target is affected does the
             * loop break (every damage false, :955) and the list is empty (:974 damage.fill(false)). */
            duoforge_event *mv = dfi_last_move(r);
            if (mv != NULL && md->target_class == DFI_TARGET_CLASS_ALL_ADJACENT && !did) {
                mv->amount = 0u;
            }
            if (!did && confuse_plain_fail) {
                dfi_fail_still(r, user); /* -fail for the user and [still] on the move line; the result is false */
                return DUOFORGE_OK;
            }
        }
        if (did) {
            r->mres |= DFI_MRES_TRUE;
        } else {
            /* Without a did, the reference's damage of a hit target may be false or undefined (battle-actions.ts:1296-1310):
             * not classified. A status move with no target left keeps the classes of the hit steps. */
            for (uint32_t i = 0u; i < count; ++i) {
                r->mres |= hit[i] ? DFI_MRES_FALSE : 0u; /* the hit's moveHit returns false: -fail [still] (runMoveEffects) */
            }
        }
        return did ? dfi_status_hit_end(r) : DUOFORGE_OK;
    }
    return DUOFORGE_OK;
}

/* Magic Bounce (step G57, data/abilities.ts:2437-2464): the kinds of a reflectable move that the bounced run models, the
 * rest is refused. Every one is a Status move: Roar, Whirlwind (the forced switch of the source), the four hazards, Parting
 * Shot, Soak, Encore, Disable, Taunt, Yawn, a primary status (Hypnosis, Will-O-Wisp, Sleep Powder, Stun Spore, Poison Powder,
 * Toxic) and the boosts of the target (Charm, Fake Tears). A spread reflectable move is refused at the caller. */
static bool dfi_bounce_kind_ok(uint32_t move_id, const dfi_move_data *md)
{
    if (md->category != DFI_CATEGORY_STATUS) {
        return false;
    }
    if ((dfi_pool_move_flags2[move_id] & DFI_MOVE_FLAG2_FORCE_SWITCH) != 0u || md->side_condition >= DUOFORGE_SIDE_STEALTH_ROCK ||
        md->boost_role == DFI_BOOST_ROLE_PRIMARY_TARGET || md->primary_status != DFI_STATUS_NONE) {
        return true;
    }
    /* Confuse Ray, Swagger and Flatter (step G92; Teeter Dance is not reflectable) take the same run: the boosts of the holder's
     * bounce go to the original user, then the confusion (dfi_confuse_primary, with the holder as the source). */
    return md->special == DFI_SPECIAL_PARTING_SHOT || md->special == DFI_SPECIAL_SOAK || md->special == DFI_SPECIAL_ENCORE ||
           md->special == DFI_SPECIAL_DISABLE || md->special == DFI_SPECIAL_TAUNT || md->special == DFI_SPECIAL_YAWN ||
           md->special == DFI_SPECIAL_LEECH_SEED ||
           md->special == DFI_SPECIAL_CONFUSE; /* G84 (decision 0047): the seed bounces like Yawn (the reflectable flag); G92: Confuse Ray, Swagger, Flatter */
}

/* The bounced run (useMove, battle-actions.ts:365-548) of a reflectable move: `holder` runs `move_id` aimed at `user`, the
 * original move's user. It skips the queue, BeforeMove, PP and the pressure drain (the sourceEffect is an ability, which has
 * no pp), and it does not set the holder's Choice lock (hasBounced), nor apply the holder's Prankster immunity
 * (pranksterBoosted = false). Its move line carries `[from] ability: Magic Bounce` (cause ABILITY, id2 + 1, other = the
 * source). Its own steps are those of the move body, in order: the foeSide hazard (TryHitSide), else Protect of the source,
 * the TryHit abilities of the source, the powder immunity, the accuracy check, then the effects. The original move ends with
 * a null TryHit (false) and no line of its own. The holder's move result becomes the bounced move's (moveThisTurnResult). */
static duoforge_status dfi_bounce(dfi_run *r, uint32_t user, uint32_t holder, uint32_t move_id, const dfi_move_data *md)
{
    struct duoforge_battle *b = r->b;
    const dfi_member *um = dfi_at(b, user);
    dfi_member *hm = dfi_at(b, holder);
    /* Refusals come before any event or state change. */
    if (!dfi_bounce_kind_ok(move_id, md) || um == NULL || um->hp == 0u || hm == NULL || hm->hp == 0u) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    /* The bounced move is redirected by RedirectTarget (pokemon.ts getMoveTargets, the holder as its user): a Follow Me or
     * Rage Powder holder on the source's side takes it. Not modelled. */
    for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
        const uint32_t flat = (user / 2u) * 2u + slot;
        if (dfi_alive(b, flat) && ((uint32_t)dfi_pos(b, flat)->flags & DFI_VOL_FOLLOW_ME) != 0u) {
            return DUOFORGE_E_UNSUPPORTED;
        }
    }
    /* The original move's priority is the bounced move's (useMoveInner, battle-actions.ts:409-412: the activeMove's, a
     * Prankster boost or a move's own, Baby-Doll Eyes). Psychic Terrain then stops it at a grounded source: not modelled. An
     * Armor Tail or Queenly Majesty holder on the source's side stops it in TryMove (onFoeTryMove, data/abilities.ts:3716-3734;
     * issue 543), after the move line: [still], then cant|holder|ability|move|[of] the bouncer, and the bounced move is false. */
    uint32_t shield_flat = DFI_POSITIONS;
    uint32_t shield = 0u;
    if (dfi_move_priority(b, um, md) > DFI_PRIORITY_BIAS) {
        if (b->terrain == DFI_TERRAIN_PSYCHIC) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        const bool exempt = md->target_class == DFI_TARGET_CLASS_FOE_SIDE || md->target_class == DUOFORGE_TARGET_CLASS_ALL;
        for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE && !exempt && shield == 0u; ++slot) {
            const uint32_t flat = (user / 2u) * 2u + slot;
            const dfi_member *sm = dfi_at(b, flat);
            if (dfi_alive(b, flat)) {
                shield = dfi_ability(b, sm, DFI_ABILITY_ARMORTAIL)        ? 1u + DFI_ABILITY_ARMORTAIL
                         : dfi_ability(b, sm, DFI_ABILITY_QUEENLYMAJESTY) ? 1u + DFI_ABILITY_QUEENLYMAJESTY
                                                                         : 0u;
                shield_flat = flat;
            }
        }
    }
    /* Throat Chop's onModifyMove (data/moves.ts:19417-19422): useMoveInner runs ModifyMove before the move line
     * (sim/battle-actions.ts:439), so a holder under Throat Chop shows `cant|holder|move: Throat Chop` for a sound move and the
     * bounced run ends there with false (`!move`, :444-445): no move line, and the holder's result is false (useMove).
     * Before that test the false move's target no longer equals the base target (:440-442), so getRandomTarget runs with
     * no move (sim/battle.ts:2490-2521): in singles the foe's slot 0 without a draw (:2509), in doubles randomFoe (:2521),
     * one sample over the holder's standing foes (sim/side.ts:369-373, 390-403) whose result nothing reads. */
    if (b->tail.sides[holder / 2u].positions[holder % 2u].throat_chop_turns != 0u &&
        (dfi_pool_move_flags2[move_id] & DFI_MOVE_FLAG2_SOUND) != 0u) {
        const duoforge_event e =
            dfi_ev(DUOFORGE_EVENT_CANT, holder, DUOFORGE_CAUSE_MOVE, DFI_MOVE_THROATCHOP, DUOFORGE_NO_POSITION);
        dfi_emit(r, &e); /* [cant] move: Throat Chop */
        if (!dfi_context_singles(r->ctx)) {
            uint32_t foes = 0u;
            for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
                foes += dfi_alive(b, (1u - holder / 2u) * 2u + slot) ? 1u : 0u;
            }
            if (foes != 0u) {
                uint32_t unused = 0u;
                const duoforge_status ds = dfi_draw(r->draws, DFI_SITE_RANDOM_TARGET, 0u, foes, &unused);
                if (ds != DUOFORGE_OK) {
                    return ds;
                }
            }
        }
        dfi_tail_pos *tp = &b->tail.sides[holder / 2u].positions[holder % 2u];
        tp->move_result = (uint8_t)(((uint32_t)tp->move_result & ~0x13u) | DFI_MOVE_RESULT_FALSE); /* wide-operands-reviewed: <= 0x3F */
        r->mres |= DFI_MRES_FALSE; /* the original move's TryHit returns null, normalised to false */
        return DUOFORGE_OK;
    }
    const uint32_t saved_mres = r->mres;
    const uint32_t saved_last = r->last_move;
    const uint32_t saved_target = r->move_target;
    {
        duoforge_event e = dfi_event_make(DUOFORGE_EVENT_MOVE, holder);
        e.id = (uint16_t)move_id;
        e.other = (uint8_t)user; /* the bounced move's target: the original user, also for a hazard (the label is real here) */
        e.cause = (uint8_t)DUOFORGE_CAUSE_ABILITY;
        e.id2 = (uint16_t)(1u + DFI_ABILITY_MAGICBOUNCE); /* wide-operands-reviewed: 106 */
        r->last_move = r->events != NULL ? r->events->count : UINT32_MAX;
        dfi_emit(r, &e);
    }
    r->mres = 0u;
    duoforge_status st = DUOFORGE_OK;
    uint32_t targets[DFI_POSITIONS] = {user, 0u, 0u, 0u};
    bool hit[DFI_POSITIONS] = {false, false, false, false};
    bool guarded[DFI_POSITIONS] = {false, false, false, false};
    const uint32_t count = 1u;
    if (shield != 0u) {
        dfi_still(r);
        r->mres |= DFI_MRES_FALSE; /* onFoeTryMove returns false */
        duoforge_event e = dfi_ev(DUOFORGE_EVENT_CANT, shield_flat, DUOFORGE_CAUSE_ABILITY, shield, holder);
        e.id = (uint16_t)move_id;
        dfi_emit(r, &e);
    } else if (md->side_condition >= DUOFORGE_SIDE_STEALTH_ROCK) {
        st = dfi_hazard_move(r, holder, md); /* TryHitSide: no Protect, no accuracy */
    } else {
        st = dfi_protect_targets(r, holder, targets, count, guarded, dfi_no_inv_miss, false, hit, md);
        if (st == DUOFORGE_OK && hit[0]) {
            /* The accuracy modifiers are read before the TryHit steps, as the move body reads them (acc_compound_eyes and
             * acc_wide_lens take base_accuracy != 0 at that point). */
            uint32_t base_accuracy = md->accuracy;
            if (move_id == DFI_MOVE_TOXIC && dfi_has_type(b, hm, DFI_TYPE_POISON)) {
                base_accuracy = 0u;
            }
            const bool acc_compound_eyes = base_accuracy != 0u && dfi_ability(b, hm, DFI_ABILITY_COMPOUNDEYES);
            const bool acc_wide_lens = base_accuracy != 0u && dfi_holds(b, hm, DFI_ITEM_WIDELENS);
            const uint32_t move_type = dfi_move_type_now(r, hm, md);
            const bool powder_move = (dfi_pool_move_flags2[move_id] & DFI_MOVE_FLAG2_POWDER) != 0u;
            const bool pre_try = hit[0];
            dfi_try_hit_abilities(r, holder, targets, count, hit, md, move_id, move_type, &base_accuracy);
            if (pre_try && !hit[0]) {
                r->mres |= DFI_MRES_FALSE;
            }
            /* hitStepTryImmunity: the natural powder immunity of a Grass source (the bouncer is not the target). */
            if (powder_move && hit[0] && dfi_powder_natural_immune(b, dfi_at(b, user))) {
                hit[0] = false;
                dfi_immune(r, user, 0u);
                r->mres |= DFI_MRES_FALSE;
            }
            /* hitStepTryImmunity: Leech Seed's onTryImmunity refuses a Grass source (data/moves.ts:10202-10231), before the
             * accuracy step, so no accuracy draw (issue 543), as in the move body. */
            if (md->special == DFI_SPECIAL_LEECH_SEED && hit[0] && dfi_has_type(b, dfi_at(b, user), DFI_TYPE_GRASS)) {
                hit[0] = false;
                dfi_immune(r, user, 0u);
                r->mres |= DFI_MRES_FALSE;
            }
            if (hit[0]) {
                st = dfi_accuracy_targets(r, holder, targets, count, hit, md, base_accuracy, acc_compound_eyes, acc_wide_lens, false);
            }
            if (st == DUOFORGE_OK && hit[0]) {
                /* The bounced move's target is the original user: its Substitute takes a status move without bypasssub, before
                 * the effects (data/moves.ts:18341-18347 onTryPrimaryHit, data/mods/champions/scripts.ts:343-347; the holder is the
                 * source). A taken hit is null, not false: its Updates run and the holder's result is TRUE (scripts.ts:537, :574;
                 * battle-actions.ts:605, :615), as in the move body (dfi_substitute_takes, dfi_status_hit_end). */
                bool taken = false;
                st = dfi_substitute_takes(r, holder, user, move_id, md, move_type, false, true, &taken, user);
                if (st == DUOFORGE_OK && taken) {
                    hit[0] = false;
                    st = dfi_status_hit_end(r);
                } else if (st == DUOFORGE_OK) {
                    st = dfi_status_effects(r, holder, move_id, md, targets, hit, count);
                }
            }
        }
    }
    if (st != DUOFORGE_OK) {
        return st;
    }
    /* The bounced move's result (sim/battle.ts useMove: moveThisTurnResult of the holder): true, false or null, as the
     * classification of the move body; nothing classified is not modelled. */
    const uint32_t res = r->mres;
    r->mres = saved_mres;
    r->last_move = saved_last;
    r->move_target = saved_target;
    uint32_t value = DFI_MOVE_RESULT_UNDEFINED;
    if ((res & DFI_MRES_TRUE) != 0u) {
        value = DFI_MOVE_RESULT_TRUE;
    } else if ((res & DFI_MRES_FALSE) != 0u) {
        value = DFI_MOVE_RESULT_FALSE;
    } else if ((res & DFI_MRES_NULL) != 0u) {
        value = DFI_MOVE_RESULT_NULL;
    } else {
        return DUOFORGE_E_UNSUPPORTED;
    }
    dfi_tail_pos *tp = &b->tail.sides[holder / 2u].positions[holder % 2u];
    tp->move_result = (uint8_t)(((uint32_t)tp->move_result & ~0x13u) | value); /* wide-operands-reviewed: <= 0x3F */
    /* The original move's TryHit returns null: the hit steps normalise it to false, and it ends (useMoveInner). */
    r->mres |= DFI_MRES_FALSE;
    return DUOFORGE_OK;
}

#include "combat/forms/stance_change.h"

#include "combat/abilities/mega_sol.h"

/* step G78, Dragon Darts (decision 0043): getSmartTargets (sim/pokemon.ts:757-767), after the RedirectTarget event
 * (sim/pokemon.ts:829-834). The foe the user chose is hit first; its partner, the other standing slot of its side, second.
 * With no standing partner, or when the chosen Pokemon is the user's ally (the partner would be the user), the move has one
 * target and smartTarget is off. Refused (E_UNSUPPORTED) for a split with a Substitute on either target (the hit mapping of
 * a Substitute under smartTarget is not traced) and with Red Card or Eject Button held by either target (their order of
 * AfterMoveSecondary with two targets is not traced). */
static duoforge_status dfi_smart_targets(dfi_run *r, uint32_t user, uint32_t targets[DFI_POSITIONS], uint32_t *count)
{
    struct duoforge_battle *b = r->b;
    r->smart = false;
    if (*count != 1u || targets[0] / 2u == user / 2u) {
        return DUOFORGE_OK;
    }
    const uint32_t partner = (targets[0] / 2u) * 2u + (1u - targets[0] % 2u);
    if (!dfi_alive(b, partner)) {
        return DUOFORGE_OK;
    }
    for (uint32_t i = 0u; i < 2u; ++i) {
        const uint32_t flat = i == 0u ? targets[0] : partner;
        const dfi_member *held = dfi_at(b, flat);
        if (*dfi_sub_hp_of(b, flat) != 0u || dfi_holds(b, held, DFI_ITEM_REDCARD) || dfi_holds(b, held, DFI_ITEM_EJECTBUTTON)) {
            return DUOFORGE_E_UNSUPPORTED;
        }
    }
    targets[1] = partner;
    *count = 2u;
    r->smart = true;
    return DUOFORGE_OK;
}

/* The partial trap's volatile (step G90, decision 0060; runMoveEffects' volatileStatus after the damage of a hit, Champions hit
 * loop: data/mods/champions/scripts.ts:374). addVolatile (sim/pokemon.ts:1969-2030) refuses a fainted target and a target that
 * has the volatile already: no draw, no line, no reset (the damage stands). Otherwise the duration is drawn (random(5, 7),
 * durationCallback before onStart), the band is the source's held Binding Band at the start, and the line is
 * -activate|T|move: M|[of] S (an ACTIVATE with cause MOVE). A Ghost target keeps the volatile (and its damage) with no trap:
 * dfi_switch_trapped reads that. */
static duoforge_status dfi_partial_trap_start(dfi_run *r, uint32_t user, uint32_t target, uint32_t move_id)
{
    struct duoforge_battle *b = r->b;
    dfi_tail_pos *tp = &b->tail.sides[target / 2u].positions[target % 2u];
    if (tp->trap_turns != 0u || dfi_at(b, target)->hp == 0u) {
        return DUOFORGE_OK;
    }
    uint32_t turns = 0u;
    const duoforge_status st = dfi_draw(r->draws, DFI_SITE_PARTIAL_TRAP_TURNS, 5u, 7u, &turns);
    if (st != DUOFORGE_OK) {
        return st;
    }
    tp->trap_turns = (uint8_t)turns; /* wide-operands-reviewed: 5 or 6 */
    tp->trap_source = (uint8_t)(user + 1u); /* wide-operands-reviewed: <= 4 */
    tp->trap_move = (uint16_t)(move_id + 1u); /* wide-operands-reviewed: a move id + 1 */
    tp->trap_band = dfi_holds(b, dfi_at(b, user), DFI_ITEM_BINDINGBAND) ? 1u : 0u;
    tp->trap_elapsed = 0u; /* step G90: the residual phases counted from the start (decision 0060, hidden counters) */
    const duoforge_event e = dfi_ev(DUOFORGE_EVENT_ACTIVATE, target, DUOFORGE_CAUSE_MOVE, move_id, user);
    dfi_emit(r, &e);
    return DUOFORGE_OK;
}

/* The locals of dfi_run_move_body that more than one phase uses (restructure step 4, move body), on the caller's
 * stack: each phase starts from them and leaves its changes in them. The arrays (targets, hit) stay the caller's. */
typedef struct dfi_move_body_state {
    struct duoforge_battle *b;
    uint32_t side;
    uint32_t user;
    dfi_active_slot *pos;
    dfi_member *m;
    uint32_t move_id;
    const dfi_move_data *md;
    uint32_t count;
    uint32_t chosen;
    duoforge_status st;
    bool locked;
    bool lock_move;
    uint32_t target_class;
    uint32_t aimed;
    bool status_move;
    bool powder_move;
    uint32_t base_accuracy;
    uint32_t move_type;
    bool spread;
    uint32_t act_target;
    uint32_t total;
    bool any;
    bool absorbed_any;
    bool split;
} dfi_move_body_state;

/* A return of dfi_run_move_body inside a phase: the move ends there with `value`, as the one function returned it. */
static DFI_ALWAYS_INLINE duoforge_status dfi_move_body_stop(bool *stop, duoforge_status value)
{
    *stop = true;
    return value;
}

/* Phase 1 of dfi_run_move_body: the actor and its targets, getTarget, BeforeMove, Mega Sol. */
static DFI_ALWAYS_INLINE duoforge_status dfi_move_body_prepare(dfi_run *r, const dfi_queue_record *q, bool *ran,
                                                               dfi_move_body_state *c, uint32_t *targets, bool *stop)
{
    struct duoforge_battle *b = c->b;
    const uint32_t side = c->side;
    const uint32_t user = c->user;
    dfi_active_slot *pos = c->pos;
    dfi_member *m = c->m;
    /* runAction: an inactive or fainted actor does nothing (no epilogue). */
    if (m == NULL || m->hp == 0u || pos->activation_id != q->activation_id) {
        return dfi_move_body_stop(stop, DUOFORGE_OK);
    }
    if (!dfi_move_slot_ok(m, q->move_slot)) {
        return dfi_move_body_stop(stop, DUOFORGE_E_INVARIANT);
    }
    /* A choice-locked actor queues only its locked move or Struggle (the
     * request offers nothing else), so choicelock's onBeforeMove, which
     * would fail another move (data/conditions.ts), never runs; a decoded
     * state that queues another move fails loudly (Team C). */
    if (((uint32_t)pos->flags & DFI_VOL_CHOICE_LOCK) != 0u && q->move_slot != DUOFORGE_MOVE_SLOT_STRUGGLE &&
        q->move_slot != DUOFORGE_MOVE_SLOT_RECHARGE && q->move_slot + 1u != pos->locked_move) {
        return dfi_move_body_stop(stop, DUOFORGE_E_INVARIANT);
    }
    *ran = true;
    r->move_used = false;
    if (pos->move_actions < UINT8_MAX) {
        pos->move_actions = (uint8_t)((uint32_t)pos->move_actions + 1u); /* wide-operands-reviewed */
    }
    if (q->move_slot == DUOFORGE_MOVE_SLOT_RECHARGE) {
        return dfi_move_body_stop(stop, dfi_run_recharge(r, user));
    }
    const uint32_t move_id = dfi_move_of(m, q->move_slot);
    const dfi_move_data *md = &dfi_pool_moves[move_id];
    if (move_id != DFI_MOVE_STRUGGLE && dfi_support.moves[move_id] == 0u) {
        return dfi_move_body_stop(stop, DUOFORGE_E_UNSUPPORTED);
    }
    /* getTarget and getMoveTargets (the spread classes need no draw): the
     * reference picks a random target in runMove, before BeforeMove, so the
     * draw happens even when the Pokemon then cannot move. */
    uint32_t count = 0u;
    /* Curse (step G84b): a non-Ghost choice has no target (TARGET_NONE); a Ghost user that Mega Evolved or was typed into
     * Ghost before its move has no chosen Pokemon either, so runMove aims at the user (no draw), as the trace shows. */
    uint32_t run_class = dfi_user_target_class(r->b, user, md->special, md->target_class);
    if (md->special == DFI_SPECIAL_CURSE && q->target >= DFI_POSITIONS) {
        run_class = DUOFORGE_TARGET_CLASS_SELF;
    }
    /* Stalwart (issue 541): getTarget returns the original target while it is active (tracksTarget, sim/battle.ts:2437-2447),
     * wherever an Ally Switch put it. Its record names it (DFI_QRES_ORIGINAL_*); a record made in a turn that could not track
     * has none, and that case is refused rather than guessed. */
    uint32_t chosen = q->target;
    if (run_class == DFI_TARGET_CLASS_RANDOM_NORMAL && dfi_ability(b, m, DFI_ABILITY_STALWART)) {
        /* A randomNormal move's original target is the one resolveAction drew when the move was queued, and Stalwart aims at it
         * with no draw of its own (sim/battle-queue.ts:268-273); that draw is not modelled: refused. */
        return dfi_move_body_stop(stop, DUOFORGE_E_UNSUPPORTED);
    }
    if (chosen < DFI_POSITIONS && dfi_ability(b, m, DFI_ABILITY_STALWART)) {
        const uint32_t orig = ((uint32_t)q->reserve >> DFI_QRES_ORIGINAL_SHIFT) & DFI_QRES_ORIGINAL_MASK;
        if (orig == 0u) {
            return dfi_move_body_stop(stop, DUOFORGE_E_UNSUPPORTED);
        }
        for (uint32_t slot = 0u; orig != DFI_QRES_ORIGINAL_NONE && slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
            const uint32_t flat = (chosen / 2u) * 2u + slot;
            if (b->sides[chosen / 2u].positions[slot].occupant == orig - 1u && dfi_alive(b, flat)) {
                chosen = flat;
            }
        }
    }
    duoforge_status st = dfi_move_targets(r, user, run_class, chosen, targets, &count, md->special == DFI_SPECIAL_DRAGON_DARTS);
    if (st != DUOFORGE_OK) {
        return dfi_move_body_stop(stop, st);
    }
    /* runMove's target, which AfterMove gets: getTarget's result, before
     * any redirection; a spread move's is a random foe that only labels
     * its line, which the engine does not draw. */
    r->move_target = md->target_class == DUOFORGE_TARGET_CLASS_ALL_ADJACENT_FOES || md->target_class == DFI_TARGET_CLASS_ALL_ADJACENT ||
                             md->target_class == DFI_TARGET_CLASS_FOE_SIDE
                         ? DFI_MOVE_TARGET_SPREAD
                     : count != 0u                                              ? targets[0]
                                                                                : DFI_MOVE_TARGET_NONE;
    /* BeforeMove: a Pokemon that cannot move uses no PP and shows nothing;
     * on the locked turn of a two-turn move its charge ends (twoturnmove's
     * onMoveAborted). */
    const bool locked = pos->charge_turns != 0u;
    /* A recharging occupant's BeforeMove (mustrecharge) returns null, every other stop returns false (step G42). */
    const bool recharging = b->tail.sides[side].positions[q->slot].must_recharge != 0u;
    bool can = false;
    st = dfi_before_move(r, user, move_id, md, &can);
    dfi_destiny_bond_attempt(r, user, move_id, can); /* step G76: the attempt ends Destiny Bond (BeforeMove / MoveAborted) */
    if (st != DUOFORGE_OK) {
        return dfi_move_body_stop(stop, st);
    }
    if (!can) {
        r->mres |= recharging ? DFI_MRES_NULL : DFI_MRES_FALSE;
        if (locked) {
            pos->charge_turns = 0u;
            pos->locked_target = 0u;
            if (((uint32_t)pos->flags & DFI_VOL_CHOICE_LOCK) == 0u) {
                pos->locked_move = 0u; /* a choice lock outlives the charge */
            }
        }
        return dfi_move_body_stop(stop, DUOFORGE_OK);
    }
    /* Mega Sol's weather reading (step G59): refused before the move's PP and its lines, for a move that reads the weather. */
    if (dfi_mega_sol_refused(r, user, md)) {
        return dfi_move_body_stop(stop, DUOFORGE_E_UNSUPPORTED);
    }
    c->b = b;
    c->pos = pos;
    c->m = m;
    c->move_id = move_id;
    c->md = md;
    c->count = count;
    c->chosen = chosen;
    c->st = st;
    c->locked = locked;
    return DUOFORGE_OK;
}

/* Phase 2 of dfi_run_move_body: the PP, ModifyMove, Stance Change and the move line. */
static DFI_ALWAYS_INLINE duoforge_status dfi_move_body_announce(dfi_run *r, const dfi_queue_record *q, bool *ran,
                                                                dfi_move_body_state *c, uint32_t *targets, bool *stop)
{
    struct duoforge_battle *b = c->b;
    const uint32_t side = c->side;
    const uint32_t user = c->user;
    dfi_active_slot *pos = c->pos;
    dfi_member *m = c->m;
    const uint32_t move_id = c->move_id;
    const dfi_move_data *md = c->md;
    uint32_t count = c->count;
    uint32_t chosen = c->chosen;
    duoforge_status st = c->st;
    const bool locked = c->locked;
    (void)ran;
    /* choicelock's onBeforeMove, reached by a holder that can move: its Choice item is gone, so the lock ends here. */
    dfi_choice_lock_ends(b, user);
    /* deductPP; a locked move uses none. The opponent counts the use from
     * the move line (dfi_events_fold_knowledge). */
    /* A lockedmove's move is the locked one too: getLockedMove skips the PP (sim/battle-actions.ts:286-291; step G56). */
    const bool lock_move = b->tail.sides[side].positions[q->slot].lock_turns != 0u;
    if (q->move_slot < DUOFORGE_MAX_MOVE_SLOTS && !locked && !lock_move) {
        dfi_move_slot *slot = &m->moves[q->move_slot];
        if (slot->pp == 0u) {
            r->mres |= DFI_MRES_FALSE; /* "cant nopp": the move returns false (battle-actions.ts useMoveInner) */
            return dfi_move_body_stop(stop, DUOFORGE_OK); /* "cant nopp"; the domain never offers it */
        }
        slot->pp = (uint8_t)((uint32_t)slot->pp - 1u); /* wide-operands-reviewed: pp > 0 */
    }
    r->move_used = true; /* useMove runs; AfterMove follows it */
    /* pokemon.moveUsed (sim/pokemon.ts:903-914, called by runMove after the PP are deducted, also for a locked turn):
     * the move that Encore takes; Struggle is 5. The tail is zero under every kind but POOL (invariant TAIL_KIND). */
    if (dfi_kind_limits_of(r->ctx->data_kind).pool_rules) {
        b->tail.sides[side].positions[q->slot].last_move =
            (uint8_t)(q->move_slot == DUOFORGE_MOVE_SLOT_STRUGGLE ? 5u : (uint32_t)q->move_slot + 1u); /* wide-operands-reviewed: <= 5 */
    }
    /* The freeze's onModifyMove thaws a user of a defrost move before the
     * move line: -curestatus|frz|[from] move (data/conditions.ts:106-111,
     * inherited by Champions; Team C, Flare Blitz). */
    if (m->status == DFI_STATUS_FRZ && ((uint32_t)md->flags & DFI_MOVE_FLAG_DEFROST) != 0u) {
        duoforge_event cure = dfi_event_make(DUOFORGE_EVENT_CURE_STATUS, user);
        cure.detail = (uint8_t)DFI_STATUS_FRZ;
        cure.cause = (uint8_t)DUOFORGE_CAUSE_MOVE;
        cure.id2 = (uint16_t)move_id;
        dfi_emit(r, &cure);
        m->status = (uint8_t)DFI_STATUS_NONE;
        m->status_counter = 0u;
        r->b->tail.sides[user / 2u].sleep_cant[dfi_pos(r->b, user)->occupant] = 0u; /* decision 0066 */
    }
    /* Choice Scarf's onModifyMove (Team C, data/items.ts:983-1005) adds
     * choicelock, whose onStart stores the move used (data/conditions.ts);
     * the lock stays until the holder leaves the field. Struggle sets none:
     * Struggle is not in the move slots, so its lock would end at the next
     * DisableMove before it could matter. */
    if (dfi_holds(r->b, m, DFI_ITEM_CHOICESCARF) && q->move_slot < DUOFORGE_MAX_MOVE_SLOTS &&
        ((uint32_t)pos->flags & DFI_VOL_CHOICE_LOCK) == 0u) {
        pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_CHOICE_LOCK);    /* wide-operands-reviewed: < 256 */
        pos->locked_move = (uint8_t)((uint32_t)q->move_slot + 1u);           /* wide-operands-reviewed: <= 4 */
    }
    /* Struggle's onModifyMove shows -activate|move: Struggle first. */
    if (move_id == DFI_MOVE_STRUGGLE) {
        const duoforge_event e =
            dfi_ev(DUOFORGE_EVENT_ACTIVATE, user, DUOFORGE_CAUSE_MOVE, DFI_MOVE_STRUGGLE, DUOFORGE_NO_POSITION);
        dfi_emit(r, &e);
    }
    /* Stance Change (step G66, decision 0040): its forme change comes in ModifyMove, before the move line. */
    {
        const duoforge_status sc = dfi_stance_change(r, user, move_id, md);
        if (sc != DUOFORGE_OK) {
            return dfi_move_body_stop(stop, sc);
        }
    }
    /* ModifyMove's change of the target class (Expanding Force in Psychic Terrain): useMoveInner takes the target again
     * with the new class (getRandomTarget, whose draw only labels the move line, as for any spread move), and
     * getMoveTargets then collects the foes. runMove's own target (r->move_target, AfterMove's) stays the old one. */
    const uint32_t target_class = dfi_effective_target_class(b, m, md);
    if (target_class != md->target_class) {
        st = dfi_move_targets(r, user, target_class, chosen, targets, &count,
                              md->special == DFI_SPECIAL_DRAGON_DARTS);
        if (st != DUOFORGE_OK) {
            return dfi_move_body_stop(stop, st);
        }
    }
    /* Curse's execution-time targets (step G84b): the variant is the user's type now (dfi_curse_targets). */
    if (md->special == DFI_SPECIAL_CURSE) {
        st = dfi_curse_targets(r, user, targets, &count);
        if (st != DUOFORGE_OK) {
            return dfi_move_body_stop(stop, st);
        }
    }
    /* The move line's target (useMoveInner, sim/battle-actions.ts:457): the
     * one Pokemon to hit, or, when there is none, the chosen fainted ally or
     * else the foe in slot 0 (side.randomFoe() || foe.active[0],
     * sim/battle.ts:2521; sim/pokemon.ts:822-843 does not retarget a fainted
     * ally). A spread move's target is only a label ([spread] replaces it). */
    uint32_t aimed = DUOFORGE_NO_POSITION;
    if (count == 1u) {
        aimed = targets[0];
    } else if (count == 0u) {
        aimed = (chosen < DFI_POSITIONS && chosen / 2u == side && dfi_at(b, chosen) != NULL) ? chosen : (1u - side) * 2u;
        aimed = dfi_at(b, aimed) != NULL ? aimed : DUOFORGE_NO_POSITION;
        /* getTarget's null for the user's own location (sim/battle.ts:2459-2462; Ally Switch put the user there, issue 541):
         * useMoveInner prints the line with no target, then [notarget] and -fail before getMoveTargets and TryMove
         * (sim/battle-actions.ts:457-465), so a two-turn move does not charge. */
        if (chosen == user) {
            aimed = DUOFORGE_NO_POSITION;
        }
    }
    /* The move line; a locked turn says [from] lockedmove. Later lines
     * amend it. */
    {
        duoforge_event e = dfi_event_make(DUOFORGE_EVENT_MOVE, user);
        e.id = (uint16_t)move_id;
        /* A fainted Pokemon is printed without its slot ("p1: Name"): with
         * nothing to hit, the line names no position. */
        e.other = (uint8_t)(count == 1u && target_class != DFI_TARGET_CLASS_FOE_SIDE ? aimed : DUOFORGE_NO_POSITION); /* wide-operands-reviewed: < 256 */
        const uint32_t spread_flag = count > 1u ? DUOFORGE_EVENT_FLAG_SPREAD : 0u;
        const uint32_t locked_flag = locked || lock_move ? DUOFORGE_EVENT_FLAG_LOCKED : 0u; /* a lockedmove's use: [from] lockedmove */
        e.flags = (uint8_t)(spread_flag | locked_flag); /* wide-operands-reviewed: flags < 256 */
        r->last_move = r->events != NULL ? r->events->count : UINT32_MAX;
        dfi_emit(r, &e);
    }
    if (aimed == DUOFORGE_NO_POSITION && count == 0u) {
        return dfi_move_body_stop(stop, dfi_no_target_or_try(r, user, md)); /* no target at all: before getMoveTargets */
    }
    c->b = b;
    c->pos = pos;
    c->m = m;
    c->count = count;
    c->st = st;
    c->lock_move = lock_move;
    c->target_class = target_class;
    c->aimed = aimed;
    return DUOFORGE_OK;
}

/* Phase 3 of dfi_run_move_body: the redirections, Dragon Darts, Pressure, the charge turn and TryMove. */
static DFI_ALWAYS_INLINE duoforge_status dfi_move_body_try_move(dfi_run *r, const dfi_queue_record *q, bool *ran,
                                                                dfi_move_body_state *c, uint32_t *targets, bool *stop)
{
    struct duoforge_battle *b = c->b;
    const uint32_t side = c->side;
    const uint32_t user = c->user;
    dfi_active_slot *pos = c->pos;
    dfi_member *m = c->m;
    const uint32_t move_id = c->move_id;
    const dfi_move_data *md = c->md;
    uint32_t count = c->count;
    duoforge_status st = c->st;
    const bool locked = c->locked;
    const bool lock_move = c->lock_move;
    const uint32_t target_class = c->target_class;
    uint32_t aimed = c->aimed;
    (void)ran;
    /* getMoveTargets' RedirectTarget event (sim/pokemon.ts:829-831), after
     * the retarget of a fainted foe and before TryMove. priorityEvent stops
     * at the first handler that returns, in compareRedirectOrder
     * (sim/battle.ts:413-419): the higher priority first.
     *
     * Follow Me (Team C, onFoeRedirectTarget at priority 1, data/moves.ts:
     * 6061-6068): a standing foe of the user with the volatile takes the
     * move when validTarget holds for the move's own class (sim/battle.ts:
     * 2399-2435). In doubles that is every single-target class here but
     * self and the ally classes, also when the user aimed at its own ally
     * or at a fainted ally. No line; the move line is retargeted. Two
     * holders on one side would need the handlers' Speed order; only
     * Indeedee-F learns Follow Me, and Species Clause keeps one per side. */
    /* Stalwart (step G63, data/abilities.ts:4503-4513, onModifyMove: move.tracksTarget = move.target !== 'scripted'): the
     * RedirectTarget event is not run for a move with tracksTarget (sim/pokemon.ts:829, `activePerHalf > 1 &&
     * !move.tracksTarget`), and ModifyMove runs before getMoveTargets (sim/battle-actions.ts:431-439 and :467). So the
     * holder's single-target moves are not redirected, by Follow Me and by Lightning Rod alike. The pin's test is on the
     * move's target: every class that `single` admits is not 'scripted' (DFI_TARGET_CLASS_SCRIPTED is not among them), so
     * the holder's gate is the whole of Stalwart here. */
    const bool stalwart = m != NULL && dfi_ability(b, m, DFI_ABILITY_STALWART);
    /* A Curse of a user that is not a Ghost now (issue 550): its onModifyMove sets move.target = 'self' before getMoveTargets
     * (data/moves.ts:3276-3281), so no RedirectTarget handler takes it (validTarget of self); it hits the user (dfi_curse_targets). */
    const bool curse_self = md->special == DFI_SPECIAL_CURSE && m != NULL && !dfi_has_type(b, m, DFI_TYPE_GHOST);
    const bool single = count <= 1u && !stalwart && !curse_self && (target_class == DUOFORGE_TARGET_CLASS_NORMAL ||
                                                     target_class == DUOFORGE_TARGET_CLASS_ANY ||
                                                     target_class == DUOFORGE_TARGET_CLASS_ADJACENT_FOE ||
                                                     target_class == DFI_TARGET_CLASS_RANDOM_NORMAL);
    uint32_t follow = DFI_POSITIONS;
    for (uint32_t slot = 0u; single && slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
        const uint32_t flat = (1u - side) * 2u + slot;
        if (dfi_alive(b, flat) && ((uint32_t)dfi_pos(b, flat)->flags & DFI_VOL_FOLLOW_ME) != 0u) {
            /* Rage Powder's handler returns the holder only for an attacker that is not immune to powder (step G30);
             * for an immune one it returns nothing and the next handler (or the aimed target) stands. */
            if (dfi_last_move_id(b, flat) == DFI_MOVE_RAGEPOWDER && dfi_powder_immune(b, m)) {
                continue;
            }
            if (follow != DFI_POSITIONS) {
                return dfi_move_body_stop(stop, DUOFORGE_E_UNSUPPORTED);
            }
            follow = flat;
        }
    }
    if (follow < DFI_POSITIONS) {
        if (follow != aimed) {
            duoforge_event *mv = dfi_last_move(r);
            if (mv != NULL) {
                mv->other = (uint8_t)follow; /* retargetLastMove; < 4 */
            }
        }
        targets[0] = follow;
        count = 1u;
        aimed = follow;
    }
    /* Lightning Rod (onAnyRedirectTarget, priority 0): an Electric
     * single-target move goes to a standing holder the user may target.
     * With two holders the higher Speed (pokemon.speed) comes first, then
     * the earlier switch-in (abilityState.effectOrder, set in switchIn,
     * sim/battle-actions.ts:142), which is the lower activation id; the
     * first handler returns its holder. This runs also when the chosen
     * target is gone (a fainted ally, no foe left). */
    if (follow == DFI_POSITIONS && dfi_move_type_now(r, m, md) == DFI_TYPE_ELECTRIC && single) {
        uint32_t rod = DFI_POSITIONS;
        for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
            const dfi_member *holder = dfi_at(b, flat);
            if (flat == user || holder == NULL || holder->hp == 0u || !dfi_ability(r->b, holder, DFI_ABILITY_LIGHTNINGROD)) {
                continue;
            }
            if (rod == DFI_POSITIONS || r->speed_seen[flat] > r->speed_seen[rod] ||
                (r->speed_seen[flat] == r->speed_seen[rod] &&
                 dfi_pos(b, flat)->activation_id < dfi_pos(b, rod)->activation_id)) {
                rod = flat;
            }
        }
        if (rod < DFI_POSITIONS) {
            if (rod != aimed) {
                /* [-activate] ability: Lightning Rod, then retargetLastMove */
                const duoforge_event act = dfi_ev(DUOFORGE_EVENT_ACTIVATE, rod, DUOFORGE_CAUSE_ABILITY,
                                                  1u + DFI_ABILITY_LIGHTNINGROD, DUOFORGE_NO_POSITION);
                dfi_emit(r, &act);
                duoforge_event *mv = dfi_last_move(r);
                if (mv != NULL) {
                    mv->other = (uint8_t)rod; /* < 4 */
                }
            }
            targets[0] = rod;
            count = 1u;
            aimed = rod;
        }
    }
    /* step G78: the partner of a Dragon Darts target, after the redirections (getMoveTargets, sim/pokemon.ts:829-834). */
    if (md->special == DFI_SPECIAL_DRAGON_DARTS) {
        st = dfi_smart_targets(r, user, targets, &count);
        if (st != DUOFORGE_OK) {
            return dfi_move_body_stop(stop, st);
        }
    } else {
        r->smart = false;
    }
    /* Electro Shot's onTryMove (a singleEvent before the TryMove event):
     * on the charge turn Special Attack +1, then in rain the attack goes on,
     * otherwise twoturnmove locks the move and the chosen target for the
     * next turn (duration 2). On the locked turn the attack goes on.
     * Solar Beam's (step G30, data/moves.ts:17224-17258) is the same without the boost, with the sun in place of the
     * rain: the lines, the lock and its end are the two-turn move's, whichever move it is. The pin's
     * effectiveWeather asks Utility Umbrella (sun and rain are ignored for its holder) and Mega Sol (sun for a Mega Sol
     * user's moves): neither is marked, tests/interactions/test_rage_powder_batch_rows.c checks it; ChargeMove is Power Herb's event, which is not
     * in the pool either. */
    const bool charge_move = md->special == DFI_SPECIAL_ELECTRO_SHOT || md->special == DFI_SPECIAL_SOLAR_BEAM ||
                             md->special == DFI_SPECIAL_PHANTOM_FORCE;
    /* Pressure (step G53, dfi_pressure_extra): after the move's own PP and the redirection, before TryMove (the pin's order,
     * sim/battle-actions.ts:473-484). The extra comes off the user's slot as deductPP does, clamped at 0. A locked turn has
     * none (its source is the lockedmove condition, sim/battle-actions.ts:289, not a move with PP), the turn of a lockedmove
     * (Outrage) included (issue 544). The state is exact whatever the move line shows; what the viewer can attribute is the
     * view's business (the fold in events.c). */
    if (q->move_slot < DUOFORGE_MAX_MOVE_SLOTS && !locked && !lock_move) {
        const uint32_t extra = dfi_pressure_extra(b, user, target_class, move_id, targets, count);
        if (extra != 0u) {
            dfi_move_slot *pressed = &m->moves[q->move_slot];
            const uint32_t take = extra < (uint32_t)pressed->pp ? extra : (uint32_t)pressed->pp;
            pressed->pp = (uint8_t)((uint32_t)pressed->pp - take); /* wide-operands-reviewed: take <= pp */
        }
    }
    if (charge_move && !locked) {
        static const uint8_t spa_up[DFI_STAT_STAGE_COUNT] = {6u, 6u, 7u, 6u, 6u, 6u, 6u};
        duoforge_event *mv = dfi_last_move(r);
        if (mv != NULL) {
            mv->flags = (uint8_t)((uint32_t)mv->flags | DUOFORGE_EVENT_FLAG_STILL); /* wide-operands-reviewed: flags < 256 */
            mv->other = (uint8_t)DUOFORGE_NO_POSITION; /* "the target should never be known" */
        }
        duoforge_event prep = dfi_event_make(DUOFORGE_EVENT_PREPARE, user);
        prep.id = (uint16_t)move_id;
        dfi_emit(r, &prep);
        if (md->special == DFI_SPECIAL_ELECTRO_SHOT) {
            dfi_boost(r, user, spa_up, DFI_POSITIONS, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_PRIMARY));
        }
        /* Step G58: Phantom Force (data/moves.ts:13307-13335) has no weather that skips its charge (no ChargeMove but Power Herb's,
         * which is unmarked): its charge always stands. */
        const uint32_t skip_weather = md->special == DFI_SPECIAL_SOLAR_BEAM ? DFI_WEATHER_SUN : DFI_WEATHER_RAIN;
        /* Solar Beam reads its user's effectiveWeather (Mega Sol's sun); Electro Shot the field (its id is excluded). */
        const uint32_t charge_weather = dfi_move_weather(r, dfi_at(b, user), md->special == DFI_SPECIAL_SOLAR_BEAM);
        if (md->special != DFI_SPECIAL_PHANTOM_FORCE && charge_weather == skip_weather) {
            /* addMove('-anim'): from now on the last move line, which later
             * attributes ([miss], [notarget]) amend. */
            duoforge_event anim = dfi_event_make(DUOFORGE_EVENT_ANIMATION, user);
            anim.id = (uint16_t)move_id;
            anim.other = (uint8_t)(count == 1u ? aimed : DUOFORGE_NO_POSITION); /* wide-operands-reviewed: < 256 */
            r->last_move = r->events != NULL ? r->events->count : UINT32_MAX;
            dfi_emit(r, &anim);
        }
        if (md->special == DFI_SPECIAL_PHANTOM_FORCE || charge_weather != skip_weather) {
            pos->charge_turns = (uint8_t)DFI_CHARGE_TURNS_MAX;
            pos->locked_move = (uint8_t)((uint32_t)q->move_slot + 1u); /* wide-operands-reviewed: <= 4 */
            pos->locked_target = q->target;
            r->mres |= DFI_MRES_NULL; /* the charge turn's onTryMove returns null (data/moves.ts) */
            return dfi_move_body_stop(stop, DUOFORGE_OK);
        }
    }
    /* TryMove: Armor Tail on a standing foe stops a move with positive
     * priority aimed at the holder's side (with nothing to hit, the aimed
     * Pokemon is fainted: no standing holder is its ally). */
    if (count != 0u) {
        const uint32_t priority = dfi_move_priority(b, m, md);
        aimed = targets[count - 1u];
        if (priority > DFI_PRIORITY_BIAS && aimed / 2u != side && md->target_class != DUOFORGE_TARGET_CLASS_SELF &&
            md->target_class != DUOFORGE_TARGET_CLASS_ALLY_SIDE && md->target_class != DUOFORGE_TARGET_CLASS_ALL &&
            md->target_class != DFI_TARGET_CLASS_FOE_SIDE) {
            for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
                const dfi_member *holder = dfi_at(b, (1u - side) * 2u + slot);
                /* Queenly Majesty (step G39, data/abilities.ts:3716-3734) is Armor Tail's handler under its own name, and
                 * Dazzling's: the same text but for the ability's name in the line (the generator compares the two). */
                const uint32_t shield = holder == NULL || holder->hp == 0u                            ? 0u
                                        : dfi_ability(r->b, holder, DFI_ABILITY_ARMORTAIL)           ? 1u + DFI_ABILITY_ARMORTAIL
                                        : dfi_ability(r->b, holder, DFI_ABILITY_QUEENLYMAJESTY)      ? 1u + DFI_ABILITY_QUEENLYMAJESTY
                                                                                                     : 0u;
                if (shield != 0u) {
                    /* [still], then cant|holder|ability: Armor Tail|move|[of] user */
                    dfi_still(r);
                    r->mres |= DFI_MRES_FALSE; /* onFoeTryMove returns false (data/abilities.ts armortail) */
                    duoforge_event e = dfi_ev(DUOFORGE_EVENT_CANT, (1u - side) * 2u + slot, DUOFORGE_CAUSE_ABILITY, shield, user);
                    e.id = (uint16_t)move_id;
                    dfi_emit(r, &e);
                    return dfi_move_body_stop(stop, DUOFORGE_OK);
                }
            }
        }
    }
    if (count == 0u) {
        return dfi_move_body_stop(stop, dfi_no_target_or_try(r, user, md)); /* after TryMove (sim/battle-actions.ts:509-513) */
    }
    c->b = b;
    c->pos = pos;
    c->m = m;
    c->count = count;
    c->st = st;
    return DUOFORGE_OK;
}

/* Phase 4 of dfi_run_move_body: the status moves with their own handler. */
static DFI_ALWAYS_INLINE duoforge_status dfi_move_body_status_handlers(dfi_run *r, const dfi_queue_record *q,
                                                                       bool *ran, dfi_move_body_state *c,
                                                                       uint32_t *targets, bool *stop)
{
    struct duoforge_battle *b = c->b;
    const uint32_t side = c->side;
    const uint32_t user = c->user;
    dfi_member *m = c->m;
    const uint32_t move_id = c->move_id;
    const dfi_move_data *md = c->md;
    uint32_t count = c->count;
    (void)ran;
    (void)q;
    if (md->special == DFI_SPECIAL_HELPING_HAND) {
        return dfi_move_body_stop(stop, dfi_run_helping_hand(r, user, targets[0]));
    }
    if (md->special == DFI_SPECIAL_PROTECT) {
        return dfi_move_body_stop(stop, dfi_run_protect(r, user, DFI_PROTECT_PLAIN));
    }
    if (md->special == DFI_SPECIAL_KINGS_SHIELD) {
        return dfi_move_body_stop(stop, dfi_run_protect(r, user, DFI_PROTECT_KINGS_SHIELD));
    }
    if (md->special == DFI_SPECIAL_SPIKY_SHIELD) {
        return dfi_move_body_stop(stop, dfi_run_protect(r, user, DFI_PROTECT_SPIKY_SHIELD));
    }
    if (md->special == DFI_SPECIAL_BANEFUL_BUNKER) {
        return dfi_move_body_stop(stop, dfi_run_protect(r, user, DFI_PROTECT_BANEFUL_BUNKER));
    }
    if (md->special == DFI_SPECIAL_WIDE_GUARD) {
        return dfi_move_body_stop(stop, dfi_run_wide_guard(r, user));
    }
    if (md->special == DFI_SPECIAL_QUICK_GUARD) {
        return dfi_move_body_stop(stop, dfi_run_quick_guard(r, user));
    }
    if (md->special == DFI_SPECIAL_AURORA_VEIL) {
        return dfi_move_body_stop(stop, dfi_run_aurora_veil(r, user));
    }
    if (md->special == DFI_SPECIAL_PERISH_SONG) {
        return dfi_move_body_stop(stop, dfi_run_perish_song(r, user, md));
    }
    if (md->special == DFI_SPECIAL_FOLLOW_ME) {
        return dfi_move_body_stop(stop, dfi_run_follow_me(r, user, DFI_MOVE_FOLLOWME));
    }
    if (md->special == DFI_SPECIAL_RAGE_POWDER) {
        return dfi_move_body_stop(stop, dfi_run_follow_me(r, user, DFI_MOVE_RAGEPOWDER));
    }
    if (md->special == DFI_SPECIAL_CLANGOROUS_SOUL) {
        return dfi_move_body_stop(stop, dfi_run_clangorous_soul(r, user, md));
    }
    if (md->special == DFI_SPECIAL_IMPRISON) {
        return dfi_move_body_stop(stop, dfi_run_imprison(r, user));
    }
    if (md->special == DFI_SPECIAL_DESTINY_BOND) {
        return dfi_move_body_stop(stop, dfi_run_destiny_bond(r, user, move_id));
    }
    if (move_id == DFI_MOVE_REVIVALBLESSING) {
        return dfi_move_body_stop(stop, dfi_run_revival_blessing(r, user));
    }
    if (move_id == DFI_MOVE_HEALINGWISH) {
        return dfi_move_body_stop(stop, dfi_run_healing_wish(r, user));
    }
    const bool status_move = md->category == DFI_CATEGORY_STATUS;
    /* flags.powder (step G30): the second flags byte's bit; Struggle has none. */
    const bool powder_move = move_id != DFI_MOVE_STRUGGLE && (dfi_pool_move_flags2[move_id] & DFI_MOVE_FLAG2_POWDER) != 0u;
    if (status_move && md->boost_role == DFI_BOOST_ROLE_PRIMARY_ALLY) {
        return dfi_move_body_stop(stop, dfi_run_coaching(r, user, targets[0], md));
    }
    if (status_move && md->side_condition >= DUOFORGE_SIDE_STEALTH_ROCK) {
        /* Magic Bounce (step G57): a standing holder on the foes' side bounces a reflectable hazard back to the user (its
         * onAllyTryHitSide, data/abilities.ts:2449-2459); two holders are not modelled (the speed order of the TryHitSide
         * handlers, with a shuffle on a tie). */
        if ((dfi_pool_move_flags3[move_id] & DFI_MOVE_FLAG3_REFLECTABLE) != 0u) {
            uint32_t holders = 0u;
            uint32_t holder = DFI_POSITIONS;
            for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
                const uint32_t flat = (1u - side) * 2u + slot;
                if (dfi_alive(b, flat) && !dfi_semi_invulnerable(r, flat) && dfi_ability(b, dfi_at(b, flat), DFI_ABILITY_MAGICBOUNCE)) {
                    holders += 1u;
                    holder = flat;
                }
            }
            if (holders > 1u) {
                return dfi_move_body_stop(stop, DUOFORGE_E_UNSUPPORTED);
            }
            if (holders == 1u) {
                return dfi_move_body_stop(stop, dfi_bounce(r, user, holder, move_id, md));
            }
        }
        return dfi_move_body_stop(stop, dfi_hazard_move(r, user, md));
    }
    if (status_move && md->side_condition != 0u) {
        /* addSideCondition: an active condition is not restarted (the move
         * fails); Tailwind lasts 4 turns, the screens 5, or 8 with Light Clay. */
        dfi_side *us = &b->sides[side];
        uint8_t *turns = md->side_condition == DFI_SIDE_CONDITION_TAILWIND  ? &us->tailwind_turns
                         : md->side_condition == DFI_SIDE_CONDITION_REFLECT ? &us->reflect_turns
                                                                            : &us->light_screen_turns;
        if (md->side_condition > DFI_SIDE_CONDITION_LIGHT_SCREEN) {
            return dfi_move_body_stop(stop, DUOFORGE_E_UNSUPPORTED);
        }
        if (*turns != 0u) {
            dfi_fail_still(r, user);
            return dfi_move_body_stop(stop, DUOFORGE_OK);
        }
        const uint32_t screen = dfi_holds(r->b, m, DFI_SCREEN_EXTENDER) ? DFI_SCREEN_TURNS_MAX : DFI_SCREEN_TURNS;
        const uint32_t duration = md->side_condition == DFI_SIDE_CONDITION_TAILWIND ? DFI_TAILWIND_TURNS_MAX : screen;
        *turns = (uint8_t)duration; /* <= 8 */
        duoforge_event e = dfi_event_make(DUOFORGE_EVENT_SIDE_START, DUOFORGE_NO_POSITION);
        e.detail = (uint8_t)side;
        e.amount = (uint8_t)md->side_condition; /* DUOFORGE_SIDE_* */
        dfi_emit(r, &e);
        r->mres |= DFI_MRES_TRUE; /* addSideCondition returns true */
        return dfi_move_body_stop(stop, DUOFORGE_OK);
    }
    if (status_move && md->special == DFI_SPECIAL_HAZE) {
        return dfi_move_body_stop(stop, dfi_run_haze(r)); /* step G62: the field hit of Haze (decision 0031) */
    }
    if (status_move && (md->special == DFI_SPECIAL_SANDSTORM || md->special == DFI_SPECIAL_SNOWSCAPE ||
                        md->special == DFI_SPECIAL_RAIN_DANCE || md->special == DFI_SPECIAL_SUNNY_DAY)) {
        /* Sandstorm and Snowscape (moveHit, sim/battle-actions.ts:1248-1251): Field.setWeather (sim/field.ts:39-82)
         * fails when the same weather is up (the move fails), and otherwise replaces the weather for 5 turns
         * (the rock items that make it 8 are not marked) with -weather|X, no [from]. Rain Dance and Sunny Day (step G32)
         * are the same move for their weather. */
        const uint32_t w = md->special == DFI_SPECIAL_SANDSTORM    ? DFI_WEATHER_SAND
                           : md->special == DFI_SPECIAL_SNOWSCAPE  ? DFI_WEATHER_SNOW
                           : md->special == DFI_SPECIAL_RAIN_DANCE ? DFI_WEATHER_RAIN
                                                                   : DFI_WEATHER_SUN;
        if (b->weather == w) {
            dfi_fail_still(r, user);
            return dfi_move_body_stop(stop, DUOFORGE_OK);
        }
        b->weather = (uint8_t)w;
        b->weather_turns = (uint8_t)dfi_field_start_turns(b, dfi_at(b, user), dfi_weather_rock(w)); /* G55 */
        duoforge_event e = dfi_event_make(DUOFORGE_EVENT_WEATHER, DUOFORGE_NO_POSITION);
        e.detail = (uint8_t)w; /* DUOFORGE_WEATHER_* */
        dfi_emit(r, &e);
        r->mres |= DFI_MRES_TRUE; /* Field.setWeather returns true */
        return dfi_move_body_stop(stop, DUOFORGE_OK);
    }
    if (status_move && (md->special == DFI_SPECIAL_ELECTRIC_TERRAIN || md->special == DFI_SPECIAL_MISTY_TERRAIN ||
                        md->special == DFI_SPECIAL_PSYCHIC_TERRAIN)) {
        /* Electric Terrain and Misty Terrain (moveHit, sim/battle-actions.ts:1252-1255): Field.setTerrain
         * (sim/field.ts:130-157) fails when the same terrain is up (the move fails) and otherwise replaces the terrain
         * for 5 turns (8 with Terrain Extender, G55) with `-fieldstart|move: X Terrain` and no [from]; the replaced
         * terrain ends without a line, and TerrainChange runs the seeds. Psychic Terrain (step G96, data/moves.ts:14095-14160)
         * is the same setter; its block and boost are the terrain rules above. */
        const uint32_t terrain = md->special == DFI_SPECIAL_ELECTRIC_TERRAIN ? DFI_TERRAIN_ELECTRIC
                                 : md->special == DFI_SPECIAL_MISTY_TERRAIN ? DFI_TERRAIN_MISTY : DFI_TERRAIN_PSYCHIC;
        if (b->terrain == terrain) {
            dfi_fail_still(r, user);
            return dfi_move_body_stop(stop, DUOFORGE_OK);
        }
        b->terrain = (uint8_t)terrain;
        b->terrain_turns = (uint8_t)dfi_field_start_turns(b, dfi_at(b, user), DFI_TERRAIN_EXTENDER); /* G55 */
        duoforge_event e = dfi_event_make(DUOFORGE_EVENT_FIELD_START, DUOFORGE_NO_POSITION);
        e.detail = (uint8_t)dfi_terrain_field_detail(terrain);
        dfi_emit(r, &e);
        r->mres |= DFI_MRES_TRUE; /* Field.setTerrain returns true */
        return dfi_move_body_stop(stop, dfi_terrain_change(r));
    }
    if (status_move && md->pseudo_weather == DFI_PSEUDO_WEATHER_TRICK_ROOM) {
        /* addPseudoWeather: Trick Room again ends it (onFieldRestart). */
        const bool ends = b->trick_room_turns != 0u;
        const uint32_t duration = ends ? 0u : DFI_FIELD_TURNS_MAX;
        b->trick_room_turns = (uint8_t)duration; /* <= 5 */
        const uint32_t of = ends ? DUOFORGE_NO_POSITION : user; /* -fieldstart|...|[of] user */
        duoforge_event e = dfi_ev(ends ? DUOFORGE_EVENT_FIELD_END : DUOFORGE_EVENT_FIELD_START, DUOFORGE_NO_POSITION,
                                  DUOFORGE_CAUSE_NONE, 0u, of);
        e.detail = (uint8_t)DUOFORGE_FIELD_TRICK_ROOM;
        dfi_emit(r, &e);
        r->mres |= DFI_MRES_TRUE; /* addPseudoWeather (or its end) returns true */
        return dfi_move_body_stop(stop, DUOFORGE_OK);
    }
    if (status_move && md->pseudo_weather == DFI_PSEUDO_WEATHER_GRAVITY) {
        /* Step K4 (#475, data/moves.ts:7754-7842, sim/field.ts:186-212): Gravity has no onFieldRestart, so a Gravity that is
         * up makes addPseudoWeather return false: the move fails with -fail|user and [still] (sim/battle-actions.ts:1303-1307),
         * and the timer is not reset. Otherwise 5 turns (the Persistent ability is not in the pool) and -fieldstart|move:
         * Gravity with no [of] (onFieldStart, :7773-7778). The field's own counter is the tail's (gravity_turns). */
        if (b->tail.gravity_turns != 0u) {
            dfi_fail_still(r, user);
            return dfi_move_body_stop(stop, DUOFORGE_OK);
        }
        b->tail.gravity_turns = (uint8_t)DFI_TAIL_GRAVITY_MAX;
        duoforge_event e = dfi_event_make(DUOFORGE_EVENT_FIELD_START, DUOFORGE_NO_POSITION);
        e.detail = (uint8_t)DUOFORGE_FIELD_GRAVITY;
        dfi_emit(r, &e); /* [-fieldstart] */
        r->mres |= DFI_MRES_TRUE; /* addPseudoWeather returns true */
        return dfi_move_body_stop(stop, DUOFORGE_OK);
    }
    /* Substitute (decision 0032, data/moves.ts:18305-18374): onTryHit, then the Substitute's start and its cost. A status move with
     * no effect of its own, so it is dispatched before the generic status check below. */
    if (md->special == DFI_SPECIAL_SUBSTITUTE) {
        return dfi_move_body_stop(stop, dfi_run_substitute(r, user));
    }
    /* Belly Drum (step G86): its own onHit (the refusal, the half-HP cost and the boost), dfi_run_belly_drum. */
    if (md->special == DFI_SPECIAL_BELLY_DRUM) {
        return dfi_move_body_stop(stop, dfi_run_belly_drum(r, user));
    }
    if (md->special == DFI_SPECIAL_CURSE) {
        return dfi_move_body_stop(stop, dfi_run_curse(r, user, count == 1u ? targets[0] : DFI_POSITIONS, count));
    }
    /* Baton Pass (decision 0042): its onHit and self block, then the PIVOT of the user (dfi_run_baton_pass). */
    if (md->special == DFI_SPECIAL_BATON_PASS) {
        return dfi_move_body_stop(stop, dfi_run_baton_pass(r, user));
    }
    /* A status move whose only effect is its forced switch (Roar, Whirlwind; step G46) is modelled by the forced-switch step
     * below, not refused here. */
    if (status_move && md->primary_status == DFI_STATUS_NONE && !dfi_move_special_status_hit(md->special) &&
        md->boost_role != DFI_BOOST_ROLE_PRIMARY_TARGET &&
        (dfi_pool_move_flags2[move_id] & DFI_MOVE_FLAG2_FORCE_SWITCH) == 0u) {
        if (dfi_pool_move_heal[move_id][1] != 0u) {
            return dfi_move_body_stop(stop, dfi_run_heal_move(r, user, move_id, targets, count));
        }
        if (md->boost_role != DFI_BOOST_ROLE_PRIMARY_SELF || md->target_class != DUOFORGE_TARGET_CLASS_SELF) {
            return dfi_move_body_stop(stop, DUOFORGE_E_UNSUPPORTED);
        }
        dfi_boost_effect own = dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_PRIMARY);
        own.negatives_first = md->special == DFI_SPECIAL_SHELL_SMASH;
        if (dfi_boost(r, user, md->boosts, DFI_POSITIONS, own)) {
            return dfi_move_body_stop(stop, dfi_status_hit_end(r));
        }
        r->mres |= DFI_MRES_FALSE; /* nothing changed: the hit returns false (runMoveEffects) */
    return dfi_move_body_stop(stop, DUOFORGE_OK); /* the hit loop stops */
    }
    c->b = b;
    c->m = m;
    c->count = count;
    c->status_move = status_move;
    c->powder_move = powder_move;
    return DUOFORGE_OK;
}

/* Phase 5 of dfi_run_move_body: onTry, the accuracy modifiers and the hit steps, the status hit. */
static DFI_ALWAYS_INLINE duoforge_status dfi_move_body_hit_steps(dfi_run *r, const dfi_queue_record *q, bool *ran,
                                                                 dfi_move_body_state *c, uint32_t *targets, bool *hit,
                                                                 bool *stop)
{
    struct duoforge_battle *b = c->b;
    const uint32_t side = c->side;
    const uint32_t user = c->user;
    dfi_active_slot *pos = c->pos;
    dfi_member *m = c->m;
    const uint32_t move_id = c->move_id;
    const dfi_move_data *md = c->md;
    uint32_t count = c->count;
    duoforge_status st = c->st;
    const uint32_t target_class = c->target_class;
    const bool status_move = c->status_move;
    const bool powder_move = c->powder_move;
    (void)ran;
    (void)q;
    /* A handler this build does not have fails explicitly; the Team C
     * specials of later steps are also kept out by the support manifest. */
    if (!dfi_move_special_has_handler(md->special)) {
        return dfi_move_body_stop(stop, DUOFORGE_E_INVARIANT);
    }
    /* Steel Roller's onTry (step G34, data/moves.ts:17893-17913): it fails without a terrain, with -fail and [still]. */
    if (md->special == DFI_SPECIAL_STEEL_ROLLER && b->terrain == DFI_TERRAIN_NONE) {
        dfi_fail_still(r, user);
        return dfi_move_body_stop(stop, DUOFORGE_OK);
    }
    /* Double Shock's onTryMove (decision 0025, data/moves.ts:3954-3959): without the Electric type it fails, -fail and [still].
     * A user that has the type is played only as Pawmot with its own two types (dfi_double_shock_shape); any other shape is
     * refused, never guessed. */
    if (md->special == DFI_SPECIAL_DOUBLE_SHOCK) {
        bool stopped = false;
        const duoforge_status ds = dfi_double_shock_try(r, user, &stopped);
        if (ds != DUOFORGE_OK || stopped) {
            return dfi_move_body_stop(stop, ds);
        }
    }
    /* Fake Out's and First Impression's onTry (in trySpreadMoveHit, after
     * TryMove): only on the first move action since it entered. */
    if (dfi_move_first_turn_only(md) && pos->move_actions > 1u) {
        dfi_fail_still(r, user);
        return dfi_move_body_stop(stop, DUOFORGE_OK);
    }
    /* Sucker Punch's onTry (Team C, data/moves.ts:18405-18411, at the same
     * point): it fails unless its target still has a move queued that is
     * not a status move (no Me First, no recharge in the data). */
    if (md->special == DFI_SPECIAL_SUCKER_PUNCH) {
        const dfi_queue_record *next = dfi_will_move(b, targets[0]);
        bool attacks = false;
        if (next != NULL) {
            const dfi_member *t = dfi_at(b, targets[0]);
            /* A recharging target fails it too (`|| target.volatiles['mustrecharge']`, :18408): the queued action of
             * the recharge turn has no category, and an Encored move that replaced it still recharges. */
            attacks = (next->move_slot == DUOFORGE_MOVE_SLOT_STRUGGLE ||
                       dfi_pool_moves[dfi_move_of(t, next->move_slot)].category != DFI_CATEGORY_STATUS) &&
                      next->move_slot != DUOFORGE_MOVE_SLOT_RECHARGE &&
                      b->tail.sides[targets[0] / 2u].positions[targets[0] % 2u].must_recharge == 0u;
        }
        if (!attacks) {
            dfi_fail_still(r, user);
            return dfi_move_body_stop(stop, DUOFORGE_OK);
        }
    }
    /* Poltergeist's onTry (step G64, data/moves.ts:13595-13608, the Try event): `return !!target.item`, so a target that holds
     * no item (dfi_item_code: the item now, the tail's item_now included) fails with -fail and [still], before any draw. */
    if (md->special == DFI_SPECIAL_POLTERGEIST && dfi_item_code(b, dfi_at(b, targets[0])) == 0u) {
        dfi_fail_still(r, user);
        return dfi_move_body_stop(stop, DUOFORGE_OK);
    }
    /* Upper Hand (step G54, data/moves.ts:20187-20209): its onTry fails unless the target's queued action is a move (willMove)
     * with priority above 0 that is not a Status move; a recharge turn and a Struggle are not. A holder of Prankster or Gale
     * Wings can raise the priority of its queued move beyond what the table shows (dfi_move_priority, at the queue), so such a
     * target is refused (E_UNSUPPORTED) rather than judged on the table. The flinch is the move's secondary (the generic path). */
    if (md->special == DFI_SPECIAL_UPPER_HAND) {
        const dfi_member *ut = dfi_at(b, targets[0]);
        if (dfi_ability(b, ut, DFI_ABILITY_PRANKSTER) || dfi_ability(b, ut, DFI_ABILITY_GALEWINGS)) {
            return dfi_move_body_stop(stop, DUOFORGE_E_UNSUPPORTED);
        }
        const dfi_queue_record *next = dfi_will_move(b, targets[0]);
        bool first = false;
        if (next != NULL && next->move_slot != DUOFORGE_MOVE_SLOT_RECHARGE && next->move_slot != DUOFORGE_MOVE_SLOT_STRUGGLE) {
            const dfi_move_data *qm = &dfi_pool_moves[dfi_move_of(ut, next->move_slot)];
            first = qm->priority > DFI_PRIORITY_BIAS && qm->category != DFI_CATEGORY_STATUS;
        }
        if (!first) {
            dfi_fail_still(r, user);
            return dfi_move_body_stop(stop, DUOFORGE_OK);
        }
    }
    /* Hurricane never misses in rain and has 50 accuracy under sun. Thunder (step G44, data/moves.ts:19438-19458) is the same
     * onModifyMove: move.accuracy = true in rain, 50 under sun (target.effectiveWeather(), which is the field's weather). */
    uint32_t base_accuracy = md->accuracy;
    if (md->special == DFI_SPECIAL_HURRICANE || md->special == DFI_SPECIAL_THUNDER) {
        /* target.effectiveWeather() (sim/pokemon.ts:2190): the user's Mega Sol reads sun, else the field. */
        const uint32_t target_weather = dfi_move_weather(r, dfi_at(b, user), true);
        if (target_weather == DFI_WEATHER_RAIN) {
            base_accuracy = 0u;
        } else if (target_weather == DFI_WEATHER_SUN) {
            base_accuracy = 50u;
        }
    }
    /* Blizzard's onModifyMove (step G28, data/moves.ts:1491-1510): in snow it never misses. */
    if (md->special == DFI_SPECIAL_BLIZZARD && dfi_field_weather(r) == DFI_WEATHER_SNOW) {
        base_accuracy = 0u;
    }
    /* Toxic never misses when its user is a Poison type (gen 8 on: the accuracy step and the invulnerability step,
     * sim/battle-actions.ts:627 and :731; the move's accuracy is 90 otherwise, data/moves.ts:19733-19748). */
    if (move_id == DFI_MOVE_TOXIC && dfi_has_type(b, m, DFI_TYPE_POISON)) {
        base_accuracy = 0u;
    }
    /* hitStepAccuracy's ModifyAccuracy event (sim/battle-actions.ts:711), before the stages: the attacker's Compound Eyes
     * (priority -1, 5325/4096, step G34, data/abilities.ts:666-677), the target's Snow Cloak in snow and Sand Veil in a
     * sandstorm (priority -1, 3277/4096, step G39, data/abilities.ts:4370-4386 and :4006-4022) and the attacker's Wide Lens
     * (priority -2, 4505/4096, data/items.ts:7713-7727) chain into one modifier that modifies a numeric accuracy (a move that
     * never misses is `true`: untouched). The two of priority -1 run in the order of their holders' speeds and commute (two
     * modifiers always do), Wide Lens always follows them, so the chain is the same in every order; it is computed per
     * target, in the accuracy loop below. The target's Bright Powder (step G49, priority -2 like Wide Lens) joins the
     * chain there; the two of priority -2 are checked for order in that loop. */
    const bool acc_compound_eyes = base_accuracy != 0u && dfi_ability(r->b, m, DFI_ABILITY_COMPOUNDEYES);
    const bool acc_wide_lens = base_accuracy != 0u && dfi_holds(r->b, m, DFI_ITEM_WIDELENS);
    /* Struggle is typeless; Weather Ball turns Water in rain, Fire under sun
     * (its onModifyType, before the hit steps). */
    uint32_t move_type = dfi_move_type_now(r, m, md);
    const bool spread = count > 1u && md->special != DFI_SPECIAL_DRAGON_DARTS; /* step G78: spreadHit is never set for smartTarget */
    /* Hit steps: Psychic Terrain and Protect (TryHit), type immunity,
     * accuracy per target. Psychic Terrain's onTryHit (Team C, priority 4,
     * before Protect's 3) stops a move with positive priority (Prankster's
     * included) at a grounded foe: [-activate] move: Psychic Terrain, and no
     * -fail (it returns null; data/moves.ts psychicterrain). */
    const bool psychic_block =
        b->terrain == DFI_TERRAIN_PSYCHIC && dfi_move_priority(b, m, md) > DFI_PRIORITY_BIAS;
    /* For a spread move the reference runs every target's Psychic Terrain
     * handler before any Protect handler (one TryHit event, sorted by
     * priority); this loop takes the targets one by one. No spread move in
     * the data has positive priority (Prankster raises status moves, none of
     * them spread): E_UNSUPPORTED rather than a different order. */
    if (psychic_block && count > 1u) {
        return dfi_move_body_stop(stop, DUOFORGE_E_UNSUPPORTED);
    }
    /* Step G58, the Invulnerability step: the first of the hit steps (sim/battle-actions.ts:556, before TryHit, so before Wide
     * Guard, Quick Guard and Protect). A semi-invulnerable target is a miss: one -miss line (with [miss] on a single target's
     * move line) and no more part in the hit (the steps below skip it, as Showdown filters it out of the targets). */
    bool inv_miss[DFI_POSITIONS] = {false, false, false, false};
    for (uint32_t i = 0u; i < count; ++i) {
        if (dfi_invulnerable_to(r, user, targets[i], move_id)) {
            inv_miss[i] = true;
            if (r->smart) {
                r->smart = false; /* step G78: hitStepInvulnerabilityEvent clears smartTarget silently (sim/battle-actions.ts:633-637) */
            } else {
                duoforge_event *mv = dfi_last_move(r);
                if (mv != NULL && !spread) {
                    mv->flags = (uint8_t)((uint32_t)mv->flags | DUOFORGE_EVENT_FLAG_MISS); /* wide-operands-reviewed */
                }
                const duoforge_event miss = dfi_ev(DUOFORGE_EVENT_MISS, user, DUOFORGE_CAUSE_NONE, 0u, targets[i]);
                dfi_emit(r, &miss);
            }
            r->mres |= DFI_MRES_FALSE; /* the Invulnerability result is false: the move has one target fewer */
        }
    }
    /* Wide Guard's onTryHit (priority 4, data/moves.ts:20828-20844) runs for every target before Protect's (3): it
     * stops a move whose target class is allAdjacentFoes (or allAdjacent, which the tables do not have yet) and that
     * has the protect flag (checkMoveBypassesProtect, sim/battle.ts:1300-1309), whatever its category and however many
     * targets are left, one -activate line per guarded target. A guarded target that also protects gets this line
     * only (its Protect handler is skipped). */
    /* Step K2: the protect bypass of this hit starts empty (Piercing Drill, protect_bypass.h). */
    r->protect_bypass = 0u;
    bool guarded[DFI_POSITIONS] = {false, false, false, false};
    if ((target_class == DUOFORGE_TARGET_CLASS_ALL_ADJACENT_FOES || target_class == DFI_TARGET_CLASS_ALL_ADJACENT) &&
        (md->flags & DFI_MOVE_FLAG_PROTECT) != 0u) {
        for (uint32_t i = 0u; i < count; ++i) {
            const uint32_t t = targets[i];
            if (!inv_miss[i] && b->tail.sides[t / 2u].wide_guard != 0u) {
                /* Step K2: a Piercing Drill holder's move passes Wide Guard's check (HitProtect returns false): no line */
                if (dfi_piercing_drill_passes(b, dfi_at(b, user), md)) {
                    r->protect_bypass |= 1u << t;
                    continue;
                }
                guarded[i] = true;
                duoforge_event e = dfi_event_make(DUOFORGE_EVENT_BLOCKED, t);
                e.detail = (uint8_t)DUOFORGE_BLOCK_WIDE_GUARD; /* [-activate] move: Wide Guard */
                dfi_emit(r, &e);
            }
        }
    }
    /* Quick Guard (step G54, data/moves.ts:14489-14531): its onTryHit at priority 4 stops a move with positive priority
     * (dfi_move_priority, Prankster and Gale Wings included) that has the protect flag and targets a side with the guard. The
     * test is checkMoveBypassesProtect (sim/battle.ts:1300-1313): a protect move is not bypassing, a move without the flag is,
     * so only the protect moves are stopped. One -activate line per guarded target (the BLOCKED event, detail 6). */
    if ((md->flags & DFI_MOVE_FLAG_PROTECT) != 0u && dfi_move_priority(b, dfi_at(b, user), md) > DFI_PRIORITY_BIAS) {
        for (uint32_t i = 0u; i < count; ++i) {
            const uint32_t t = targets[i];
            if (b->tail.sides[t / 2u].quick_guard != 0u && !guarded[i] && !inv_miss[i]) {
                /* Step K2: a Piercing Drill holder's move passes Quick Guard's check too (see Wide Guard above) */
                if (dfi_piercing_drill_passes(b, dfi_at(b, user), md)) {
                    r->protect_bypass |= 1u << t;
                    continue;
                }
                guarded[i] = true;
                duoforge_event e = dfi_event_make(DUOFORGE_EVENT_BLOCKED, t);
                e.detail = (uint8_t)DUOFORGE_BLOCK_QUICK_GUARD; /* [-activate] move: Quick Guard */
                dfi_emit(r, &e);
            }
        }
    }
    /* One TryHit event runs the handlers of every target ordered by priority, then by the holders' speed (a tie draws):
     * two holders of a punishing variant that both stop a contact move would show their lines in that order, which is not
     * modelled (E_UNSUPPORTED, never a guess). */
    if ((md->flags & DFI_MOVE_FLAG_CONTACT) != 0u && (md->flags & DFI_MOVE_FLAG_PROTECT) != 0u) {
        uint32_t punishers = 0u;
        for (uint32_t i = 0u; i < count; ++i) {
            const uint32_t t = targets[i];
            punishers += (!guarded[i] && !inv_miss[i] && ((uint32_t)dfi_pos(b, t)->flags & DFI_VOL_PROTECT) != 0u &&
                          b->tail.sides[t / 2u].positions[t % 2u].protect_kind != DFI_PROTECT_PLAIN)
                             ? 1u
                             : 0u;
        }
        if (punishers > 1u) {
            return dfi_move_body_stop(stop, DUOFORGE_E_UNSUPPORTED);
        }
    }
    st = dfi_protect_targets(r, user, targets, count, guarded, inv_miss, psychic_block, hit, md);
    if (st != DUOFORGE_OK) {
        return dfi_move_body_stop(stop, st);
    }
    /* Magic Bounce (step G57): the TryHit of a standing holder that the reflectable move aims at (data/abilities.ts:2437-2448,
     * priority 1, after Protect's 3 and Psychic Terrain's 4, both above). A spread reflectable move is not modelled (none is
     * marked): a holder among its targets refuses it. */
    if ((dfi_pool_move_flags3[move_id] & DFI_MOVE_FLAG3_REFLECTABLE) != 0u) {
        for (uint32_t i = 0u; i < count; ++i) {
            const uint32_t t = targets[i];
            /* isSemiInvulnerable() returns the Bounce (data/abilities.ts:2440): a semi-invulnerable holder does not bounce. */
            if (!hit[i] || t == user || dfi_semi_invulnerable(r, t) || !dfi_ability(b, dfi_at(b, t), DFI_ABILITY_MAGICBOUNCE)) {
                continue;
            }
            if (count != 1u) {
                return dfi_move_body_stop(stop, DUOFORGE_E_UNSUPPORTED);
            }
            return dfi_move_body_stop(stop, dfi_bounce(r, user, t, move_id, md));
        }
    }
    /* Snapshot for the drops of the immunity steps below (each a literal false of the hit steps). */
    bool hit_pre_immunity[DFI_POSITIONS];
    for (uint32_t i = 0u; i < DFI_POSITIONS; ++i) {
        hit_pre_immunity[i] = hit[i];
    }
    dfi_try_hit_abilities(r, user, targets, count, hit, md, move_id, move_type, &base_accuracy);

    /* hitStepTryImmunity (sim/battle-actions.ts:666-689): the natural powder immunity comes first (step G30): a powder
     * move of another Pokemon is stopped by a Grass type with a plain -immune and no failure line. */
    for (uint32_t i = 0u; i < count && powder_move; ++i) {
        if (hit[i] && targets[i] != user && dfi_powder_natural_immune(b, dfi_at(b, targets[i]))) {
            hit[i] = false;
            dfi_immune(r, targets[i], 0u);
        }
    }
    /* hitStepTryImmunity: Trick's and Switcheroo's onTryImmunity fails a target that has Sticky Hold
     * (data/moves.ts:19871-19873): -immune, with no reason. After the powder test and before the Prankster test. */
    for (uint32_t i = 0u; i < count; ++i) {
        if (hit[i] && (md->special == DFI_SPECIAL_TRICK || md->special == DFI_SPECIAL_SWITCHEROO) &&
            dfi_ability(r->b, dfi_at(b, targets[i]), DFI_ABILITY_STICKYHOLD)) {
            hit[i] = false;
            dfi_immune(r, targets[i], 0u);
        }
    }
    /* hitStepTryImmunity: Leech Seed's onTryImmunity refuses a Grass target (data/moves.ts:10202-10231): -immune, no volatile and
     * no accuracy roll (the immunity step is before the accuracy step, sim/battle-actions.ts:565-568; step G84). */
    for (uint32_t i = 0u; i < count; ++i) {
        if (hit[i] && md->special == DFI_SPECIAL_LEECH_SEED && dfi_has_type(b, dfi_at(b, targets[i]), DFI_TYPE_GRASS)) {
            hit[i] = false;
            dfi_immune(r, targets[i], 0u);
        }
    }
    /* hitStepTryImmunity (step C5, data/moves.ts:4796-4798): Endeavor's onTryImmunity fails a target whose HP is not above the
     * user's: -immune with no reason (battle-actions.ts:673-675), before the accuracy check, so no accuracy draw. */
    for (uint32_t i = 0u; i < count; ++i) {
        if (hit[i] && md->special == DFI_SPECIAL_ENDEAVOR && m->hp >= dfi_at(b, targets[i])->hp) {
            hit[i] = false;
            dfi_immune(r, targets[i], 0u);
        }
    }
    /* hitStepTryImmunity, last: a Prankster-boosted status move fails on a Dark foe. */
    for (uint32_t i = 0u; i < count && status_move && dfi_ability(r->b, m, DFI_ABILITY_PRANKSTER); ++i) {
        if (hit[i] && targets[i] / 2u != side && dfi_has_type(b, dfi_at(b, targets[i]), DFI_TYPE_DARK)) {
            hit[i] = false;
            dfi_immune(r, targets[i], 0u);
        }
    }
    for (uint32_t i = 0u; i < count; ++i) {
        r->mres |= hit_pre_immunity[i] && !hit[i] ? DFI_MRES_FALSE : 0u;
    }
    /* The pin's activeTarget after hitStepAccuracy's loop (sim/battle-actions.ts:693): the last target that reached it, i.e.
     * the last hit flag set before the accuracy check (the TryHit, type and move immunity steps above have cleared the rest). */
    uint32_t act_target = count != 0u ? targets[0] : 0u;
    for (uint32_t i = 0u; i < count; ++i) {
        if (hit[i]) {
            act_target = targets[i];
        }
    }
    st = dfi_accuracy_targets(r, user, targets, count, hit, md, base_accuracy, acc_compound_eyes, acc_wide_lens,
                              spread);
    if (st != DUOFORGE_OK) {
        return dfi_move_body_stop(stop, st);
    }

    /* hitStepBreakProtect, after the accuracy check (sim/battle-actions.ts:568-571): Feint removes the protections of every
     * target that is still hit. */
    if (md->special == DFI_SPECIAL_FEINT || md->special == DFI_SPECIAL_PHANTOM_FORCE) {
        for (uint32_t i = 0u; i < count; ++i) {
            if (hit[i]) {
                dfi_break_protect(r, targets[i], move_id);
            }
        }
    }
    if (md->special == DFI_SPECIAL_AFTER_YOU) {
        return dfi_move_body_stop(stop, dfi_run_after_you(r, user, move_id, targets, count, hit)); /* step G62 (decision 0015 entry 5az) */
    }
    /* A status move's hit on a foe with a Substitute (decision 0032, onTryPrimaryHit before the move's effects): the Substitute
     * takes it, the move fails on the user, and no effect of the move reaches the target. Damaging moves are gated per hit, in
     * the hit loop below. This comes before Quash, below: Quash has no bypasssub (data/moves.ts:14454-14475), so a Substitute
     * takes it before its onHit runs (spreadMoveHit's TryPrimaryHit, data/mods/champions/scripts.ts:343-347, before :374). */
    bool absorbed = false;
    if (status_move) {
        for (uint32_t i = 0u; i < count; ++i) {
            bool taken = false;
            if (hit[i]) {
                st = dfi_substitute_takes(r, user, targets[i], move_id, md, move_type, spread, true, &taken, act_target);
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
                if (taken) {
                    hit[i] = false;
                    absorbed = true;
                }
            }
        }
    }
    /* A status move whose only target was absorbed by a Substitute: its onTryPrimaryHit returns null, not false
     * (data/moves.ts:18341-18347 after its -fail), and spreadMoveHit's hit value is null (data/mods/champions/scripts.ts:343-347,
     * 357). The loop does not break at :526 (null is not false), so both Updates run (:537, :574), and the hit keeps its target
     * (battle-actions.ts:605), so the move result is TRUE (battle-actions.ts:615, :374). That result is what Stomping Tantrum reads
     * next turn (data/moves.ts:18054). The handlers below do not run: no target is left for them. A spread status move with a
     * target still hit beside the absorbed one is not modelled (no pool row has it): an explicit refusal. */
    if (status_move && absorbed) {
        if (count != 1u) {
            return dfi_move_body_stop(stop, DUOFORGE_E_UNSUPPORTED);
        }
        /* Memento into a Substitute does not faint its user (step G92, recorded in g92_memento_sub): the Substitute's
         * onTryPrimaryHit returns null, spreadMoveHit leaves the target at null, which is not HIT_SUBSTITUTE, so the target is
         * false (battle-actions.ts:1058-1070) and runMoveEffects skips it before its selfdestruct check (:1287 is inside the
         * target loop after `if (target === false) continue`). */
        return dfi_move_body_stop(stop, dfi_status_hit_end(r));
    }
    if (md->special == DFI_SPECIAL_QUASH) {
        return dfi_move_body_stop(stop, dfi_run_quash(r, user, move_id, targets, count, hit)); /* step G62 (decision 0015 entry 5az) */
    }
    if (md->special == DFI_SPECIAL_STRENGTH_SAP) {
        return dfi_move_body_stop(stop, dfi_run_strength_sap(r, user, targets, count, hit));
    }
    if (md->special == DFI_SPECIAL_HEAL_PULSE) {
        return dfi_move_body_stop(stop, dfi_run_heal_pulse(r, user, targets, hit, count));
    }
    /* trySpreadMoveHit ends a spread move's line with [spread] and the
     * slots still hit (sim/battle-actions.ts:618): the hit loop keeps every
     * target that reaches it. */
    if (spread) {
        uint32_t mask = 0u;
        for (uint32_t i = 0u; i < count; ++i) {
            mask |= hit[i] ? 1u << targets[i] : 0u;
        }
        duoforge_event *mv = dfi_last_move(r);
        if (mv != NULL) {
            mv->amount = (uint8_t)mask; /* < 16 */
        }
    }
    if (status_move) {
        const duoforge_status res = dfi_status_effects(r, user, move_id, md, targets, hit, count);
        /* Only a primary boost's spread list is recomputed here (Howl). Any other status spread move keeps the list its own
         * effects wrote: the Teeter Dance confusion sets 0 when no target was affected (dfi_status_effects, CONFUSE branch,
         * sim/battle-actions.ts:955-974), and this recomputation would overwrite that 0 with the hit mask (step G92 vs G80). */
        if (res == DUOFORGE_OK && spread && md->boost_role == DFI_BOOST_ROLE_PRIMARY_TARGET) {
            /* A primary boost (Howl) that changed no stat of any target fails the whole hit loop: no target is left for the
             * [spread] line (sim/battle-actions.ts:614-618, hitTargets). If some stat changed, every target that reached the
             * hit stays, including one whose own stat was already at its maximum (recorded: fz_90_7 step 21 and fz_90_37 step 8). */
            bool changed = true;
            if (r->events != NULL) {
                changed = false;
                for (uint32_t k = r->last_move + 1u; k < r->events->count; ++k) {
                    const duoforge_event *ev = &r->events->rec[k];
                    if ((ev->kind == DUOFORGE_EVENT_BOOST || ev->kind == DUOFORGE_EVENT_UNBOOST) && ev->amount != 0u) {
                        changed = true;
                    }
                }
            }
            uint32_t mask = 0u;
            for (uint32_t i = 0u; i < count && changed; ++i) {
                mask |= hit[i] ? 1u << targets[i] : 0u;
            }
            duoforge_event *mv = dfi_last_move(r);
            if (mv != NULL) {
                mv->amount = (uint8_t)mask; /* < 16 */
            }
        }
        return dfi_move_body_stop(stop, res);
    }

    /* Psychic Fangs' and Brick Break's onTryHit (step G30, data/moves.ts:14060-14078; step G34, 1822-1840, the same text): spreadMoveHit's singleEvent TryHit, after the
     * accuracy check and before the damage (the Substitute check follows it: no Substitute in the pool): the target's
     * side loses Reflect, Light Screen and Aurora Veil, in that order, each with its -sideend line, when it has it, so
     * that this hit is already without them. A miss, a Protect or an immunity never gets here. */
    if (md->special == DFI_SPECIAL_PSYCHIC_FANGS || md->special == DFI_SPECIAL_BRICK_BREAK) {
        for (uint32_t i = 0u; i < count; ++i) {
            if (hit[i]) {
                dfi_break_screens(r, targets[i] / 2u);
            }
        }
    }
    /* Poltergeist's onTryHit (step G64, data/moves.ts:13601-13604, run by spreadMoveHit's singleEvent TryHit at
     * sim/battle-actions.ts:1044, after the accuracy and the type immunity: a miss, an immunity or a Protect shows no line):
     * -activate|target|move: Poltergeist|Item, the item the target holds now (the converter checks its name). The line is an
     * ACTIVATE of the move with no state of its own. */
    if (md->special == DFI_SPECIAL_POLTERGEIST) {
        for (uint32_t i = 0u; i < count; ++i) {
            if (hit[i]) {
                const duoforge_event act = dfi_ev(DUOFORGE_EVENT_ACTIVATE, targets[i], DUOFORGE_CAUSE_MOVE, DFI_MOVE_POLTERGEIST,
                                                  DUOFORGE_NO_POSITION);
                dfi_emit(r, &act);
            }
        }
    }
    c->b = b;
    c->pos = pos;
    c->m = m;
    c->count = count;
    c->st = st;
    c->base_accuracy = base_accuracy;
    c->move_type = move_type;
    c->spread = spread;
    c->act_target = act_target;
    return DUOFORGE_OK;
}

/* Illusion (decision 0026 section 4): a damaging move hit of any user, an ally included, ends the disguise of the target.
 * Its replace and -end lines are one ILLUSION_END event; the owner's and the foe's folds read it. The pin's handler is the
 * holder's onDamagingHit with no order (data/abilities.ts:2071-2075), so it sorts after the ordered handlers (Rough Skin 1,
 * Rocky Helmet 2: their -damage on the attacker comes first) and among the unordered ones by the target's index
 * (compareLeftToRightOrder, sim/battle.ts:421-426: an earlier target's Weak Armor or Cursed Body lines come first; issue
 * 552). It is the holder's one ability, so its place among the holder's own handlers is the ability's: after its status
 * (a thaw), before its item (Air Balloon) and the attacker's Poison Touch. A holder the hit knocked out runs it too (the
 * faint is not processed yet). */
static void dfi_illusion_break(dfi_run *r, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    dfi_tail_pos *dp = &b->tail.sides[flat / 2u].positions[flat % 2u];
    if (dp->ability_state != 0u && dfi_ability(b, dfi_at(b, flat), DFI_ABILITY_ILLUSION)) {
        dp->ability_state = 0u;
        duoforge_event ie = dfi_event_make(DUOFORGE_EVENT_ILLUSION_END, flat);
        ie.id = (uint16_t)b->sides[flat / 2u].positions[flat % 2u].occupant;
        dfi_emit_hp(r, ie);
    }
}

/* Phase 6 of dfi_run_move_body: the hit loop. */
static DFI_ALWAYS_INLINE duoforge_status dfi_move_body_hit_loop(dfi_run *r, const dfi_queue_record *q, bool *ran,
                                                                dfi_move_body_state *c, uint32_t *targets, bool *hit,
                                                                uint32_t *hp_before, bool *sub_struggle, bool *stop)
{
    struct duoforge_battle *b = c->b;
    const uint32_t side = c->side;
    const uint32_t user = c->user;
    dfi_active_slot *pos = c->pos;
    dfi_member *m = c->m;
    const uint32_t move_id = c->move_id;
    const dfi_move_data *md = c->md;
    uint32_t count = c->count;
    duoforge_status st = c->st;
    const bool status_move = c->status_move;
    uint32_t base_accuracy = c->base_accuracy;
    uint32_t move_type = c->move_type;
    const bool spread = c->spread;
    uint32_t act_target = c->act_target;
    (void)ran;
    /* The hit loop (hitStepMoveHitLoop, data/mods/champions/scripts.ts:427-549, the base game's sim/battle-actions.ts:857-979;
     * step G33): a move with several hits (Dual Wingbeat, Twin Beam, Triple Axel: one target, a count that
     * is fixed) makes the hit steps below once for each hit: its damage (own critical hit roll and damage roll, the power of
     * Triple Axel rising with the hit), the self effects and secondaries, the DamagingHit handlers (a contact ability or
     * Rocky Helmet each time), AfterHit and the user's Emergency Exit, then an Update. The accuracy, Protect and immunity
     * checks above are made once; a move with multiaccuracy checks the accuracy again before every later hit, and a miss
     * ends the loop with no line. The loop also ends when the target is down, when the user is asleep and when the user
     * has fainted (that hit still counts). The faints are shown once, after the last hit; recoil, Life Orb and the
     * AfterMoveSecondary handlers come once, after the loop. The hit count is the number of -damage lines on the target:
     * the converter checks it against `-hitcount` and drops that line. */
    for (uint32_t i = 0u; i < count; ++i) {
        r->mres |= hit[i] ? DFI_MRES_TRUE : 0u; /* spreadDamage returns a number for a hit target (also 0): true */
    }
    uint32_t hits_total = dfi_move_hits(md);
    if (md->special == DFI_SPECIAL_BEAT_UP) {
        hits_total = dfi_beat_up_hits(r, user); /* step G64: one hit per eligible member of the user's side */
    }
    bool reaches_loop = false; /* hitStepMoveHitLoop is entered only when a target survived the hit steps (an immunity: no) */
    for (uint32_t i = 0u; i < count; ++i) {
        reaches_loop = reaches_loop || hit[i];
    }
    if ((md->special == DFI_SPECIAL_MULTI_HIT_2_5 || md->special == DFI_SPECIAL_SCALE_SHOT) && reaches_loop) {
        /* Icicle Spear and Scale Shot (step G54, Champions hit loop scripts.ts:437-446, data/mods/champions/scripts.ts): the count
         * is sample([2 x7, 3 x7, 4 x3, 5 x3]) at the start of the loop, one draw of random(20) (SITE_MULTIHIT_COUNT), after the
         * accuracy, Protect and immunity checks above. Skill Link (the count is its maximum) and Loaded Dice are not marked. */
        uint32_t pick = 0u;
        st = dfi_draw(r->draws, DFI_SITE_MULTIHIT_COUNT, 0u, 20u, &pick);
        if (st != DUOFORGE_OK) {
            return dfi_move_body_stop(stop, st);
        }
        hits_total = dfi_multihit_count(pick);
    }    if (hits_total != 1u && md->special != DFI_SPECIAL_DRAGON_DARTS && (count != 1u || spread)) {
        return dfi_move_body_stop(stop, DUOFORGE_E_UNSUPPORTED); /* a multi-hit spread move: Dragon Darts and the like are not modelled */
    }
    const bool multi_accuracy = md->special == DFI_SPECIAL_TRIPLE_AXEL || md->special == DFI_SPECIAL_MULTI_HIT_10; /* multiaccuracy: true */
    uint32_t total = 0u;
    bool any = false;
    bool sub_any = false; /* decision 0032: a hit of this iteration that a Substitute took (it still counts for the next hit) */
    /* decision 0032: a target whose damaging hit a Substitute took. The pin's targets entry is null, not false, so selfDrops
     * (battle-actions.ts:1318-1331) still rolls for it and applies the self effect: it counts as reached, as a hit does. */
    bool absorbed_any = false;
    /* The targets whose hit of the previous iteration a Substitute took: their hit is back on for the next hit (the target is
     * still hit by the move; only this hit went to the Substitute). */
    bool sub_off[DFI_POSITIONS] = {false, false, false, false};
    /* step G67: a target whose Struggle hit a Substitute took: its Air Balloon pops after the Struggle recoil, not at the hit */
    /* step G78: a split (both targets still hit) is a loop over the targets one by one: hit k goes to the k-th target
     * (data/mods/champions/scripts.ts:466-470). hit_all keeps the targets that the steps left. */
    const bool dd = md->special == DFI_SPECIAL_DRAGON_DARTS;
    const bool split = dd && r->smart && hit[0] && hit[1];
    bool hit_all[DFI_POSITIONS];
    bool hp_set[DFI_POSITIONS] = {false, false, false, false};
    for (uint32_t i = 0u; i < DFI_POSITIONS; ++i) {
        hit_all[i] = hit[i];
    }
    for (uint32_t hit_no = 1u; hit_no <= hits_total; ++hit_no) {
        if (hit_no > 1u) {
            if (!any) {
                break; /* nothing was hit (a miss, Protect, an immunity): the loop is never entered */
            }
            bool standing = false; /* the loop ends when no target it hits still stands (scripts.ts:463 `targets.every`) */
            for (uint32_t i = 0u; i < count; ++i) {
                standing = standing || (hit_all[i] && dfi_at(b, targets[i])->hp != 0u);
            }
            if (!standing || m->status == DFI_STATUS_SLP) {
                break;
            }
            if (multi_accuracy) {
                bool ok = true;
                st = dfi_accuracy_check(r, user, targets[0], md, base_accuracy, true, &ok);
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
                if (!ok) {
                    break;
                }
            }
        }
        r->hit_index = hit_no;
        if (dd) {
            if (split) {
                for (uint32_t i = 0u; i < count; ++i) {
                    hit[i] = hit_all[i] && i == hit_no - 1u;
                }
            }
            uint32_t lead = 0u;
            for (uint32_t i = 0u; i < count; ++i) {
                if (hit[i]) {
                    lead = i;
                    break;
                }
            }
            if (hit_no == 1u) {
                /* retargetLastMove on the first hit (scripts.ts:477, sim/battle.ts:3141): the move line names the target that
                 * takes the first hit */
                duoforge_event *mv = dfi_last_move(r);
                if (mv != NULL) {
                    mv->other = (uint8_t)targets[lead];
                }
            } else {
                /* addMove('-anim') before the later hits (scripts.ts:474-475) */
                duoforge_event anim = dfi_event_make(DUOFORGE_EVENT_ANIMATION, user);
                anim.id = (uint16_t)move_id;
                anim.other = (uint8_t)targets[lead];
                r->last_move = r->events != NULL ? r->events->count : UINT32_MAX;
                dfi_emit(r, &anim);
            }
        }
        /* Substitute (decision 0032): onTryPrimaryHit of each target of this hit, before the damage. A hit that a Substitute takes
         * is no hit of the target; the loop continues, as spreadMoveHit's true does (sim/battle-actions.ts:1061-1065). */
        sub_any = false;
        for (uint32_t i = 0u; i < count; ++i) {
            if (sub_off[i]) {
                hit[i] = true; /* the previous hit went to the Substitute; this one is the target's again */
                sub_off[i] = false;
            }
        }
        if (!status_move) {
            for (uint32_t i = 0u; i < count; ++i) {
                bool taken = false;
                if (hit[i]) {
                    st = dfi_substitute_takes(r, user, targets[i], move_id, md, move_type, spread, false, &taken, act_target);
                    if (st != DUOFORGE_OK) {
                        return dfi_move_body_stop(stop, st);
                    }
                    if (taken) {
                        hit[i] = false;
                        sub_off[i] = true;
                        sub_any = true;
                        absorbed_any = true;
                        sub_struggle[i] = (md->flags & DFI_MOVE_FLAG_STRUGGLE_RECOIL) != 0u;
                    }
                }
            }
        }
        /* getSpreadDamage: every target's damage (crit, roll), then spreadDamage. */
        uint32_t damage[DFI_POSITIONS] = {0u, 0u, 0u, 0u};
        /* the critical hit of each target of this hit (Anger Point, step G77): false for a target that is not hit or has no roll */
        bool crit_hit[DFI_POSITIONS] = {false, false, false, false};
        for (uint32_t i = 0u; i < count; ++i) {
            if (hit[i]) {
                st = dfi_get_damage(r, user, targets[i], md, move_type, spread, &damage[i], &crit_hit[i]);
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
            }
        }
        /* spreadDamage, per target: the damage, then a drain heals the user by
         * round(dealt * drain) (sim/battle.ts:2170-2173). The HP actually lost
         * adds up to the move's total damage. */
        for (uint32_t i = 0u; i < count; ++i) {
            if (hit[i]) {
                const uint32_t before = dfi_at(b, targets[i])->hp;
                if (!hp_set[i]) {
                    hp_before[i] = before; /* Emergency Exit asks for the HP before the whole move */
                    hp_set[i] = true;
                }
                /* Focus Sash (combat/items/families.h): a move hit that would take
                 * all of a full-HP holder's HP uses the item up ([-enditem],
                 * before the [-damage] line) and leaves 1 HP. Each target decides
                 * for itself. Only the damage of a Move comes here (and the
                 * confusion hit, below): recoil, Life Orb, Rocky Helmet, weather
                 * and status damage are not Move effects and go through dfi_deal
                 * on their own. */
                const dfi_member *tm = dfi_at(b, targets[i]);
                (void)dfi_sturdy_saves(r, targets[i], &damage[i]); /* step G39, priority -30: before the Sash's -40, which then sees hp - 1 */
                if (dfi_focus_sash_saves(dfi_item_code(b, tm), tm, damage[i])) {
                    dfi_use_item(r, targets[i]);
                    damage[i] = (uint32_t)tm->hp - 1u;
                }
                const uint32_t queued_before = r->faint_count;
                st = dfi_deal(r, targets[i], damage[i], DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION, DFI_DMG_MOVE);
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
                if (r->faint_count != queued_before) {
                    r->last_faint_by = user; /* the Move's damage: Battle.damage's source and effect (Moxie reads them) */
                    r->last_faint_move = true;
                }
                /* timesAttacked (step G48): a damaging hit of another Pokemon's move counts for the target, once per hit (the
                 * Champions loop adds the hits after the move, data/mods/champions/scripts.ts:565; the same count, and no reader
                 * sees it in between, since Rage Fist is one hit). The target still stands here: a faint clears its position later. */
                if (targets[i] != user && dfi_kind_limits_of(r->ctx->data_kind).pool_rules) {
                    /* The tail is all zero under the other kinds (invariant TAIL_KIND): only the POOL kinds count. */
                    dfi_tail_pos *victim = &b->tail.sides[targets[i] / 2u].positions[targets[i] % 2u];
                    if (victim->hits_taken < DFI_TAIL_HITS_TAKEN_MAX) {
                        victim->hits_taken = (uint8_t)((uint32_t)victim->hits_taken + 1u); /* wide-operands-reviewed: <= 6 */
                    }
                }
                const uint32_t dealt = before - (uint32_t)dfi_at(b, targets[i])->hp;
                total += dealt;
                if (md->drain[1] != 0u && dealt != 0u) {
                    const uint32_t num = dealt * md->drain[0] * 2u + md->drain[1];
                    dfi_heal(r, user, num / (2u * md->drain[1]), DUOFORGE_CAUSE_DRAIN, 0u, targets[i]); /* round */
                }
            }
        }
        /* The partial trap (step G90): the volatile of each hit target, after the damage of the hit (runMoveEffects). */
        if (md->special == DFI_SPECIAL_PARTIAL_TRAP) {
            for (uint32_t i = 0u; i < count; ++i) {
                if (hit[i]) {
                    st = dfi_partial_trap_start(r, user, targets[i], move_id);
                    if (st != DUOFORGE_OK) {
                        return dfi_move_body_stop(stop, st);
                    }
                }
            }
        }
        /* Steel Roller's onHit (runMoveEffects, right after the damage of the hit): the terrain ends. */
        if (md->special == DFI_SPECIAL_STEEL_ROLLER) {
            bool any_hit = false;
            for (uint32_t i = 0u; i < count; ++i) {
                any_hit = any_hit || hit[i];
            }
            if (any_hit) {
                st = dfi_clear_terrain(r);
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
            }
        }
        /* onHit of Bug Bite (step G64; data/moves.ts:1920-1930): runMoveEffects runs it right after the damage of the hit and before
         * the self effects, the selfSwitch, the secondaries and the DamagingHit handlers (sim/battle-actions.ts:1085-1086, 1096,
         * 1099, 1119-1121). For each target that took damage, in order (hit[] is false for a target that a Substitute absorbed, and
         * a target that fainted from the hit keeps its hit: takeItem has no HP test). The source.hp test and the berry and
         * Sticky Hold checks are inside dfi_bug_bite. */
        if (md->special == DFI_SPECIAL_BUG_BITE) {
            for (uint32_t i = 0u; i < count; ++i) {
                if (hit[i]) {
                    st = dfi_bug_bite(r, user, targets[i], move_id);
                    if (st != DUOFORGE_OK) {
                        return dfi_move_body_stop(stop, st);
                    }
                }
            }
        }
        /* selfSwitch of a damaging move (Flip Turn, U-turn): runMoveEffects
         * flags the user with the move's id when the move hit a target and the
         * user still stands; with no reserve the request would clear it again
         * (sim/battle-actions.ts:1290-1312), so the engine sets it only when a
         * reserve can come in, as for Parting Shot. The flag is the move's own
         * (dfi_pivot_moves), so that the switch is named for the move that made
         * it ([from] U-turn, not [from] Flip Turn). A self-switch move that has
         * no flag is refused here, never made to pivot as another one. A user
         * that a Rocky Helmet then knocks out loses it again (faint(),
         * sim/pokemon.ts:1585): here with the position's other state when the
         * faint is processed. */
        if ((md->flags & DFI_MOVE_FLAG_SELF_SWITCH) != 0u) {
            const dfi_pivot_move *pivot = dfi_pivot_of_move(move_id);
            if (pivot == NULL) {
                return dfi_move_body_stop(stop, DUOFORGE_E_UNSUPPORTED);
            }
            /* A target whose hit a Substitute took is null, not false (data/mods/champions/scripts.ts:349-352), and
             * runMoveEffects' selfSwitch block runs for it too (sim/battle-actions.ts:1290-1296, 1311-1312; issue 519). */
            bool hit_any = false;
            for (uint32_t i = 0u; i < count; ++i) {
                hit_any = hit_any || hit[i] || sub_off[i];
            }
            if (hit_any && m->hp != 0u && dfi_can_switch(b, side)) {
                pos->switch_flag = pivot->flag;
            }
        }
        /* Anger Point (step G77, data/abilities.ts:131-142, onHit of the holder): the Hit event runs in Champions' runMoveEffects
         * (scripts.ts:373), after the damage and before the user's self drops (scripts.ts:Champions step 4), the secondaries
         * (scripts.ts:387) and the DamagingHit of the holder (scripts.ts:409). A critical hit that the holder took from this move's hit (crit_hit, no Substitute: hit[i] false)
         * raises its Attack by 12, capped at +6 by the boost; a fainted holder does nothing (dfi_boost). The line is
         * -setboost with [from] ability: Anger Point, no -ability line. */
        for (uint32_t i = 0u; i < count; ++i) {
            if (hit[i] && crit_hit[i] && dfi_ability(r->b, dfi_at(r->b, targets[i]), DFI_ABILITY_ANGERPOINT)) {
                static const uint8_t atk_up12[DFI_STAT_STAGE_COUNT] = {18u, 6u, 6u, 6u, 6u, 6u, 6u}; /* Atk +12, biased by 6 */
                dfi_boost(r, targets[i], atk_up12, targets[i],
                          dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_ANGERPOINT, DFI_BOOST_PRIMARY));
            }
        }
        /* selfDrops: once, after the first target that was hit, a roll of
         * random(100) that always passes (no chance), then the user's own stat
         * changes (Close Combat, Make It Rain). */
        if (md->boost_role == DFI_BOOST_ROLE_SELF_AFTER_HIT) {
            bool hit_any = absorbed_any; /* a Substitute's hit is a non-false target (decision 0032) */
            for (uint32_t i = 0u; i < count; ++i) {
                hit_any = hit_any || hit[i];
            }
            if (hit_any) {
                uint32_t roll = 0u;
                st = dfi_draw(r->draws, DFI_SITE_SECONDARY, 0u, 100u, &roll);
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
                dfi_boost(r, user, md->boosts, DFI_POSITIONS, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_SELF));
            }
        }
        /* A recharge move (flags.recharge, self: {volatileStatus: 'mustrecharge'}; step G17): selfDrops (sim/battle-actions.ts:
         * 1096, 1317-1335) puts the volatile on the user for every target that was not ruled out (a miss, a Protect or an
         * immunity make it `false`; a knocked-out target is still a hit), once: a second addVolatile changes nothing.
         * -mustrecharge|user (data/conditions.ts:374-376, onStart). A target whose hit a Substitute took is null, not false
         * (data/mods/champions/scripts.ts:349-352), so it counts too (issue 517). */
        if ((dfi_pool_move_flags2[move_id] & DFI_MOVE_FLAG2_RECHARGE) != 0u && move_id != DFI_MOVE_STRUGGLE) {
            bool hit_any = false;
            for (uint32_t i = 0u; i < count; ++i) {
                hit_any = hit_any || hit[i] || sub_off[i];
            }
            dfi_tail_pos *tail = &b->tail.sides[side].positions[q->slot];
            if (hit_any && tail->must_recharge == 0u) {
                tail->must_recharge = 1u;
                duoforge_event e = dfi_event_make(DUOFORGE_EVENT_VOLATILE_START, user);
                e.detail = (uint8_t)DUOFORGE_VOLATILE_MUST_RECHARGE;
                dfi_emit(r, &e); /* [-mustrecharge] */
            }
        }
        /* Glaive Rush (step G19): its self effect, applied like the recharge's by selfDrops to the user once a target was not
         * ruled out (a miss or a Protect gives none), shows nothing: -singlemove|user|Glaive Rush|[silent]
         * (data/moves.ts:6647-6678; the public view infers it from the move line, decision 0018 section 6.1). A target whose hit a
         * Substitute took is null, not false, and counts too (issue 556, the cause of issue 518). */
        if (md->special == DFI_SPECIAL_GLAIVE_RUSH) {
            /* A target whose hit a Substitute took is null, not false (data/mods/champions/scripts.ts:349-352): selfDrops sets
             * the effect for it too (sim/battle-actions.ts:1317-1335). */
            bool hit_any = false;
            for (uint32_t i = 0u; i < count; ++i) {
                hit_any = hit_any || hit[i] || sub_off[i];
            }
            if (hit_any) {
                b->tail.sides[side].positions[q->slot].glaive_rush = 1u;
            }
        }
        /* Outrage, Thrash and Petal Dance (step G56; the self volatile lockedmove, data/moves.ts:13082-13097, 13291-13306,
         * 19373-19388, applied like the recharge's selfDrops once a target was not ruled out). A new lock draws its count,
         * random(2, 4) (onStart, data/conditions.ts:265); a lock already up is restarted (onRestart): its duration is 2 only
         * when the count is 2 or more. Either way the duration is 2 in this step (lock_restarted), which the countdown and the
         * end of the lock read. */
        if (md->special == DFI_SPECIAL_LOCKED_MOVE) {
            /* A target whose hit a Substitute took is null, not false (data/mods/champions/scripts.ts:349-352): selfDrops puts the
             * lock on the user for it too (sim/battle-actions.ts:1317-1335; issue 518). */
            bool hit_any = false;
            for (uint32_t i = 0u; i < count; ++i) {
                hit_any = hit_any || hit[i] || sub_off[i];
            }
            if (hit_any) {
                dfi_tail_pos *ut = &b->tail.sides[side].positions[q->slot];
                if (ut->lock_turns == 0u) {
                    uint32_t count_turns = 0u;
                    st = dfi_draw(r->draws, DFI_SITE_LOCK_TURNS, 2u, 4u, &count_turns);
                    if (st != DUOFORGE_OK) {
                        return dfi_move_body_stop(stop, st);
                    }
                    ut->lock_turns = (uint8_t)count_turns; /* wide-operands-reviewed: 2 or 3 */
                    dfi_pos(b, user)->locked_move = (uint8_t)((uint32_t)q->move_slot + 1u); /* wide-operands-reviewed: <= 4 */
                    r->lock_restarted |= 1u << user;
                } else if (ut->lock_turns >= 2u) {
                    r->lock_restarted |= 1u << user;
                }
            }
        }
        /* The empty secondary of Stone Axe and Ceaseless Edge (step G48, `secondary: {}`, the Sheer Force placeholder): without
         * Sheer Force the pin runs it for every target that was not ruled out (sim/battle-actions.ts:1336-1349: a secondary
         * with no chance always applies, after the roll), so one SECONDARY roll per hit target and nothing else. Sheer Force
         * (step G61) strips the secondary: no roll. A target whose hit a Substitute took is null, not false, and draws its roll
         * too (issue 518). */
        if ((md->special == DFI_SPECIAL_STONE_AXE || md->special == DFI_SPECIAL_CEASELESS_EDGE) && !dfi_sf_strips(r->b, m, md)) {
            for (uint32_t i = 0u; i < count; ++i) {
                if (hit[i] || sub_off[i]) {
                    uint32_t roll = 0u;
                    st = dfi_draw(r->draws, DFI_SITE_SECONDARY, 0u, 100u, &roll);
                    if (st != DUOFORGE_OK) {
                        return dfi_move_body_stop(stop, st);
                    }
                }
            }
        }
        /* Double Shock's self onHit (decision 0025, data/moves.ts:3960-3964, selfDrops: once for every target that was not ruled out,
         * with no test of the user's HP): the type Electric becomes ??? and the -start line shows ???/Fighting. */
        if (md->special == DFI_SPECIAL_DOUBLE_SHOCK) {
            bool hit_any = false;
            for (uint32_t i = 0u; i < count; ++i) {
                hit_any = hit_any || hit[i];
            }
            if (hit_any) {
                st = dfi_double_shock_self(r, user, move_id);
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
            }
        }
        /* Alluring Voice's secondary (data/moves.ts:282-301: chance 100, confusion when the target's statsRaisedThisTurn; owned by
         * its handler, the pool row has no secondary field). The draw is the secondaries' (sim/battle-actions.ts:1336-1349: one
         * random(100) per hit target, even at 100), then the moveHit of the secondary runs the confusion on a raised target. */
        if (md->special == DFI_SPECIAL_ALLURING_VOICE && !dfi_sf_strips(r->b, m, md)) {
            /* Sheer Force strips this secondary for its holder (pool_families checkG61; the pin deletes secondaries): no draw, no confusion. */
            for (uint32_t i = 0u; i < count; ++i) {
                /* A target whose last hit a Substitute took is a non-false target too: the roll is drawn (sim/battle-actions.ts
                 * 1336-1349, the null target), and the effect is not (moveHit of a null target does nothing). Decision 0042 / G60. */
                if (!hit[i] && !sub_off[i]) {
                    continue;
                }
                uint32_t roll = 0u;
                st = dfi_draw(r->draws, DFI_SITE_SECONDARY, 0u, 100u, &roll);
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
                if (hit[i] && roll < 100u && dfi_stats_raised(r->b, targets[i])) {
                    st = dfi_add_volatile(r, targets[i], DFI_VOLATILE_CONFUSION);
                    if (st != DUOFORGE_OK) {
                        return dfi_move_body_stop(stop, st);
                    }
                }
            }
        }
        /* secondaries: one SECONDARY draw per hit target, even at 100; a status
         * or volatile reaches only a standing target. Sheer Force (step G61) strips
         * them all for its holder: no draw, no effect (sim/battle-actions.ts:1099, the
         * `moveData.secondaries` test of a stripped move). */
        if (md->sec_chance != 0u && !dfi_sf_strips(r->b, m, md)) {
            for (uint32_t i = 0u; i < count; ++i) {
                /* the absorbed target draws too (see Alluring Voice above) but takes no effect */
                if (!hit[i] && !sub_off[i]) {
                    continue;
                }
                uint32_t roll = 0u;
                st = dfi_draw(r->draws, DFI_SITE_SECONDARY, 0u, 100u, &roll);
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
                if (roll >= md->sec_chance) {
                    continue;
                }
                /* A self-boost secondary (Ancient Power, Charge Beam) acts on the user even when the target's hit went to a Substitute:
                 * secondaries() calls moveHit for every target that is not false, and the null target still runs the secondary's
                 * self (selfDrops, sim/battle-actions.ts:1317-1333 and :1336-1350). The target effects need a hit target. */
                if (!hit[i] && md->sec_kind != DFI_SECONDARY_SELF_BOOST) {
                    continue;
                }
                if (md->sec_kind == DFI_SECONDARY_BOOST) {
                    dfi_boost(r, targets[i], md->boosts, user, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_SECONDARY));
                } else if (md->sec_kind == DFI_SECONDARY_STATUS) {
                    st = dfi_try_status(r, targets[i], md->sec_param, user, move_id, DFI_ORIGIN_OTHER, 0u);
                } else if (md->sec_kind == DFI_SECONDARY_VOLATILE) {
                    st = dfi_add_volatile(r, targets[i], md->sec_param);
                } else if (md->sec_kind == DFI_SECONDARY_SELF_BOOST) {
                    /* Ancient Power (step G28, data/moves.ts:396-418): the secondary's own boosts go to the user, a self change
                     * without a line of its own (moveHit of the secondary's `self`, isSelf). */
                    dfi_boost(r, user, md->boosts, DFI_POSITIONS, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_SELF));
                } else if (md->sec_kind == DFI_SECONDARY_LOCKOUT) {
                    dfi_add_lockout(r, targets[i]); /* Throat Chop (POOL data) */
                } else if (md->sec_kind == DFI_SECONDARY_HEAL_BLOCK) {
                    dfi_add_heal_block(r, targets[i]); /* Psychic Noise (POOL data) */
                } else if (md->sec_kind == DFI_SECONDARY_STATUS_PICK) {
                    /* Dire Claw (Team C, data/mods/champions/moves.ts:217-227):
                     * sample(['psn', 'par', 'slp']), then trySetStatus without a
                     * source move. The reference draws the pick after every
                     * successful roll, also for a target that fainted, has a
                     * status or is immune; so does the engine (decision 0009
                     * section 10.6). */
                    static const uint8_t pick[3] = {DFI_STATUS_PSN, DFI_STATUS_PAR, DFI_STATUS_SLP};
                    uint32_t v = 0u;
                    st = dfi_draw(r->draws, DFI_SITE_STATUS_PICK, 0u, 3u, &v);
                    if (st == DUOFORGE_OK) {
                        st = dfi_try_status(r, targets[i], pick[v], user, DFI_NO_SOURCE_MOVE, DFI_ORIGIN_OTHER, 0u);
                    }
                } else {
                    st = DUOFORGE_E_UNSUPPORTED;
                }
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
            }
            if (md->boost_role == DFI_BOOST_ROLE_SELF_AFTER_HIT) {
                return dfi_move_body_stop(stop, DUOFORGE_E_UNSUPPORTED); /* no closure move has both */
            }
        }
        /* Ice Fang (step G44, data/moves.ts:9347-9368): two secondaries in order, and for each hit target the loop of
         * secondaries() draws random(100) before each one (sim/battle-actions.ts:1336-1354): a freeze at 10 (a status of the
         * move, dfi_try_status as a status secondary does), then a flinch at 10 (a volatile of the target). Both rolls are
         * drawn for a target that fainted, as for any secondary, and for a target whose hit a Substitute took (a null target,
         * not false; issue 518): it takes no effect (moveHit of a null target does nothing), as for the other secondaries. */
        if (md->special == DFI_SPECIAL_ICE_FANG && !dfi_sf_strips(r->b, m, md)) {
            for (uint32_t i = 0u; i < count; ++i) {
                if (!hit[i] && !sub_off[i]) {
                    continue;
                }
                uint32_t roll = 0u;
                st = dfi_draw(r->draws, DFI_SITE_SECONDARY, 0u, 100u, &roll);
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
                if (hit[i] && roll < 10u) {
                    st = dfi_try_status(r, targets[i], DFI_STATUS_FRZ, user, move_id, DFI_ORIGIN_OTHER, 0u);
                    if (st != DUOFORGE_OK) {
                        return dfi_move_body_stop(stop, st);
                    }
                }
                st = dfi_draw(r->draws, DFI_SITE_SECONDARY, 0u, 100u, &roll);
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
                if (hit[i] && roll < 10u) {
                    st = dfi_add_volatile(r, targets[i], DFI_VOLATILE_FLINCH);
                    if (st != DUOFORGE_OK) {
                        return dfi_move_body_stop(stop, st);
                    }
                }
            }
        }
        /* Tri Attack (step G44, data/moves.ts:19845-19864): a secondary of chance 20, one SECONDARY roll per hit target, and
         * its onHit draws sample(['brn', 'par', 'frz']) (SITE_STATUS_PICK, random(3)) then trySetStatus without a source move,
         * as Dire Claw's pick does (the reference draws the pick after every successful roll, also for a target that fainted,
         * has a status or is immune). A target whose hit a Substitute took (null, not false; issue 518) draws the roll, and its
         * onHit does not run (moveHit of a null target does nothing): no pick. */
        if (md->special == DFI_SPECIAL_TRI_ATTACK && !dfi_sf_strips(r->b, m, md)) {
            static const uint8_t tri_pick[3] = {DFI_STATUS_BRN, DFI_STATUS_PAR, DFI_STATUS_FRZ};
            for (uint32_t i = 0u; i < count; ++i) {
                if (!hit[i] && !sub_off[i]) {
                    continue;
                }
                uint32_t roll = 0u;
                st = dfi_draw(r->draws, DFI_SITE_SECONDARY, 0u, 100u, &roll);
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
                if (!hit[i] || !dfi_tri_attack_chance_hit(roll)) {
                    continue;
                }
                uint32_t v = 0u;
                st = dfi_draw(r->draws, DFI_SITE_STATUS_PICK, 0u, 3u, &v);
                if (st == DUOFORGE_OK) {
                    st = dfi_try_status(r, targets[i], tri_pick[v], user, DFI_NO_SOURCE_MOVE, DFI_ORIGIN_OTHER, 0u);
                }
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
            }
        }
        /* forceSwitch of a damaging move (Dragon Tail, Circle Throw; step G46): step 6 of the Champions spreadMoveHit
         * (data/mods/champions/scripts.ts:391), after the damage is dealt (step 2) and the secondaries (step 5), before the
         * DamagingHit handlers (issue 545): a Guard Dog or Suction Cups line follows the damage, and a target the hit knocked
         * out is not dragged (forceSwitch asks target.hp > 0). */
        if (!status_move && (dfi_pool_move_flags2[move_id] & DFI_MOVE_FLAG2_FORCE_SWITCH) != 0u) {
            for (uint32_t i = 0u; i < count; ++i) {
                if (hit[i]) {
                    dfi_drag_at_hit(r, user, targets[i]);
                }
            }
        }
        /* DamagingHit, its handlers by order, then target (compareLeftToRightOrder,
         * sim/battle.ts:421-426). Rocky Helmet (Team C, onDamagingHitOrder 2,
         * data/items.ts:5295-5309) comes first, also when the hit knocked its
         * holder out (the faint is not processed yet): a contact move costs the
         * attacker floor(maxHP / 6), at least 1. */
        const uint32_t user_before_hit = m->hp;
        /* Rough Skin (POOL data, data/abilities.ts:3938-3950) is the order-1 handler, before Rocky Helmet's 2: a contact
         * move costs the attacker floor(maxHP / 8), at least 1, with [from] ability: Rough Skin [of] the holder, also
         * when the hit knocked the holder out. A contact move is one with the contact flag (checkMoveMakesContact,
         * sim/battle.ts:1289-1298: Protective Pads are not in the pool; Long Reach, which would remove the flag from the
         * attacker's moves, is not marked). */
        for (uint32_t i = 0u; i < count; ++i) {
            if (hit[i] && (md->flags & DFI_MOVE_FLAG_CONTACT) != 0u &&
                dfi_ability(r->b, dfi_at(b, targets[i]), DFI_ABILITY_ROUGHSKIN)) {
                const uint32_t skin = (uint32_t)m->hp_max / 8u;
                st = dfi_deal(r, user, skin == 0u ? 1u : skin, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_ROUGHSKIN,
                              targets[i], DFI_DMG_ABILITY);
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
            }
        }
        for (uint32_t i = 0u; i < count; ++i) {
            if (hit[i] && (md->flags & DFI_MOVE_FLAG_CONTACT) != 0u &&
                dfi_holds(r->b, dfi_at(b, targets[i]), DFI_ITEM_ROCKYHELMET)) {
                const uint32_t helmet = (uint32_t)m->hp_max / 6u;
                st = dfi_deal(r, user, helmet == 0u ? 1u : helmet, DUOFORGE_CAUSE_ITEM, 1u + DFI_ITEM_ROCKYHELMET,
                              targets[i], DFI_DMG_ITEM);
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
            }
        }
        /* Then, per standing damaged target: a damaging Fire move thaws a frozen
         * target (frz, status first), Stamina raises Defense by 1. */
        for (uint32_t i = 0u; i < count; ++i) {
            dfi_member *tm = dfi_at(b, targets[i]);
            if (!hit[i]) {
                continue;
            }
            if (tm->hp == 0u) {
                /* The unordered handlers of a target that is down do nothing, except Cursed Body (a holder that the hit knocked
                 * out still makes its attacker roll: its onDamagingHit runs before the faint is processed and `-start|...|Disable
                 * ... [from] ability: Cursed Body [of] holder` shows before the faint line, recorded in g27_cursed_body_a) and
                 * Flame Body (step G30: it draws its roll too) and the attacker's Poison Touch: it draws its roll (the handler
                 * runs, trySetStatus then fails). */
                dfi_illusion_break(r, targets[i]); /* issue 552: the holder's own ability handler, a down holder too */
                st = dfi_toxic_debris(r, user, targets[i], md); /* step G37: the target's own handler, one ability per holder */
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
                if (dfi_ability(r->b, tm, DFI_ABILITY_CURSEDBODY)) {
                    st = dfi_cursed_body(r, user, targets[i], move_id);
                    if (st != DUOFORGE_OK) {
                        return dfi_move_body_stop(stop, st);
                    }
                }
                st = dfi_flame_body(r, user, targets[i], md);
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
                st = dfi_spicy_spray(r, user, targets[i]); /* step G59: the holder's one ability, a down holder too */
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
                st = dfi_static(r, user, targets[i], md); /* step G39: one ability per holder, so never with Flame Body's */
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
                st = dfi_poison_point(r, user, targets[i], md); /* A2a: one ability per holder, as Static's */
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
                dfi_gooey(r, user, targets[i], md); /* A2a: a holder that is down still runs it */
                st = dfi_cute_charm(r, user, targets[i], md); /* step G71: one ability per holder too (Cute Charm) */
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
                st = dfi_poison_touch(r, user, targets[i], md);
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
                /* Air Balloon (step G67): the hit that knocks its holder out still pops it, before the faint (measured in
                 * g67_balloon_ground: -enditem, then |faint|). The holder's ability (above) comes before its item. */
                if (dfi_holds(r->b, tm, DFI_ITEM_AIRBALLOON)) {
                    dfi_use_item(r, targets[i]);
                }
                continue;
            }
            if (move_type == DFI_TYPE_FIRE && tm->status == DFI_STATUS_FRZ) {
                duoforge_event cure = dfi_event_make(DUOFORGE_EVENT_CURE_STATUS, targets[i]);
                cure.detail = tm->status;
                cure.flags = (uint8_t)DUOFORGE_EVENT_FLAG_MESSAGE;
                dfi_emit(r, &cure); /* [-curestatus] frz [msg] */
                tm->status = (uint8_t)DFI_STATUS_NONE;
                tm->status_counter = 0u;
                r->b->tail.sides[targets[i] / 2u].sleep_cant[dfi_pos(r->b, targets[i])->occupant] = 0u; /* decision 0066 */
            }
            dfi_illusion_break(r, targets[i]); /* issue 552: the holder's own ability handler, after its status's (the thaw) */
            if (dfi_ability(r->b, tm, DFI_ABILITY_STAMINA)) {
                static const uint8_t def_up[DFI_STAT_STAGE_COUNT] = {6u, 7u, 6u, 6u, 6u, 6u, 6u};
                dfi_boost(r, targets[i], def_up, user,
                          dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_STAMINA, DFI_BOOST_PRIMARY));
            }
            /* Thermal Exchange (POOL data, data/abilities.ts:4990-5018, onDamagingHit): a Fire move that hit raises the
             * holder's Attack by 1 (-ability ... boost, then -boost), as Stamina does for Defense; its holder has one
             * ability, so it never comes with Stamina. */
            if (dfi_ability(r->b, tm, DFI_ABILITY_THERMALEXCHANGE) && move_type == DFI_TYPE_FIRE) {
                static const uint8_t atk_up[DFI_STAT_STAGE_COUNT] = {7u, 6u, 6u, 6u, 6u, 6u, 6u};
                dfi_boost(r, targets[i], atk_up, user,
                          dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_THERMALEXCHANGE, DFI_BOOST_PRIMARY));
            }
            /* Poison Point and Gooey (A2a): the target's own unordered handlers. A holder's ability handler comes before its
             * item's (findPokemonEventHandlers gathers the ability before the item, sim/battle.ts:1117-1130, and DamagingHit sorts by order,
             * priority and the target index only, compareLeftToRightOrder, :421-426, a stable sort), so both stand before Air
             * Balloon's pop. One ability per holder: never with Stamina, Thermal Exchange or one another. */
            st = dfi_poison_point(r, user, targets[i], md);
            if (st != DUOFORGE_OK) {
                return dfi_move_body_stop(stop, st);
            }
            dfi_gooey(r, user, targets[i], md);
            /* Cursed Body (POOL data): the target's own onDamagingHit, after Thermal Exchange's place and before the attacker's
             * Poison Touch; the target is standing here (a holder that is down rolls too: see above). Two holders hit by one
             * spread move: DamagingHit is sorted by compareLeftToRightOrder (sim/battle.ts:789-790 and :421-426: order, then
             * priority, then the target's index in the move's target list), not by Speed, so the holders roll in target order
             * with no tie draw (the damaged targets go in as one array, sim/battle-actions.ts:1109-1121); the second holder
             * finds the attacker already disabled when the first one's roll succeeded and does not roll (data/abilities.ts:784-797). */
            st = dfi_toxic_debris(r, user, targets[i], md); /* step G37: the target's own handler, one ability per holder */
            if (st != DUOFORGE_OK) {
                return dfi_move_body_stop(stop, st);
            }
            if (dfi_ability(r->b, tm, DFI_ABILITY_CURSEDBODY)) {
                st = dfi_cursed_body(r, user, targets[i], move_id);
                if (st != DUOFORGE_OK) {
                    return dfi_move_body_stop(stop, st);
                }
            }
            /* Flame Body (step G30): the target's own handler, one ability per holder, so never with Stamina or Thermal
             * Exchange. */
            st = dfi_flame_body(r, user, targets[i], md);
            if (st != DUOFORGE_OK) {
                return dfi_move_body_stop(stop, st);
            }
            /* Justified (step G39, data/abilities.ts:2249-2259, onDamagingHit): a Dark move that hit raises the holder's Attack by
             * 1 (-ability ... boost, then -boost), as Stamina does for Defense. */
            if (move_type == DFI_TYPE_DARK && dfi_ability(r->b, tm, DFI_ABILITY_JUSTIFIED)) {
                static const uint8_t atk_up_j[DFI_STAT_STAGE_COUNT] = {7u, 6u, 6u, 6u, 6u, 6u, 6u};
                dfi_boost(r, targets[i], atk_up_j, user,
                          dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_JUSTIFIED, DFI_BOOST_PRIMARY));
            }
            /* Weak Armor (step G45, data/abilities.ts:5448-5458, onDamagingHit: a Physical move of another Pokemon or of its
             * own, every hit): this.boost({def: -1, spe: 2}, target, target), the holder its own source, so no block by another
             * Pokemon's ability. -unboost|holder|def|1 then -boost|holder|spe|2; a Defense already at -6 shows nothing for it. */
            if (md->category == DFI_CATEGORY_PHYSICAL && dfi_ability(r->b, tm, DFI_ABILITY_WEAKARMOR)) {
                static const uint8_t def_down_spe_up[DFI_STAT_STAGE_COUNT] = {6u, 5u, 6u, 6u, 8u, 6u, 6u};
                dfi_boost(r, targets[i], def_down_spe_up, targets[i],
                          dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_WEAKARMOR, DFI_BOOST_PRIMARY));
            }
            /* Spicy Spray (step G59): the target's own handler, one ability per holder, so never with Flame Body's or Static's. */
            st = dfi_spicy_spray(r, user, targets[i]);
            if (st != DUOFORGE_OK) {
                return dfi_move_body_stop(stop, st);
            }
            /* Static (step G39): the target's own unordered handler, like Flame Body's. */
            st = dfi_static(r, user, targets[i], md);
            if (st != DUOFORGE_OK) {
                return dfi_move_body_stop(stop, st);
            }
            /* Cute Charm (step G71): the target's own handler too (one ability per holder). */
            st = dfi_cute_charm(r, user, targets[i], md);
            if (st != DUOFORGE_OK) {
                return dfi_move_body_stop(stop, st);
            }
            /* Air Balloon (step G67, data/items.ts:197-202, onDamagingHit): a damaging hit uses it up (-enditem with no [from]).
             * Indirect damage does not pop it: every indirect path goes through dfi_deal, which never calls this. The holder's
             * unordered handlers are collected ability before item (sim/battle.ts:1117-1130) and the sort is stable, so it comes
             * after the target's own ability handlers above (issue 546: Weak Armor's lines, then -enditem). */
            if (dfi_holds(r->b, tm, DFI_ITEM_AIRBALLOON)) {
                dfi_use_item(r, targets[i]);
            }
            /* The attacker's Poison Touch comes after the target's own handlers (its onSourceDamagingHit is appended
             * after them, sim/battle.ts:1035-1063, and the sort is stable). */
            st = dfi_poison_touch(r, user, targets[i], md);
            if (st != DUOFORGE_OK) {
                return dfi_move_body_stop(stop, st);
            }
        }
        /* AfterHit (step G16): Knock Off's onAfterHit, for each damaged target in the order of the targets. The Champions mod
         * does not ask whether the user still stands (data/mods/champions/scripts.ts:411; the base game's test of the user's
         * HP is at sim/battle-actions.ts:1123): a user that a Rocky Helmet just knocked out takes the item all the same. It
         * comes after the DamagingHit handlers above and before the Emergency Exit check below (scripts.ts:416-418). */
        if (md->special == DFI_SPECIAL_KNOCK_OFF) {
            for (uint32_t i = 0u; i < count; ++i) {
                if (hit[i]) {
                    dfi_knock_off(r, user, targets[i], move_id);
                }
            }
        }
        /* Thief's and Covet's onAfterHit (step G29), at the same point (and also for a user that has fainted since: the
         * Champions mod does not ask, data/mods/champions/scripts.ts:411; setItem then refuses). */
        if (md->special == DFI_SPECIAL_THIEF || md->special == DFI_SPECIAL_COVET) {
            for (uint32_t i = 0u; i < count; ++i) {
                if (hit[i]) {
                    st = dfi_thief(r, user, targets[i], move_id, md->special == DFI_SPECIAL_THIEF);
                    if (st != DUOFORGE_OK) {
                        return dfi_move_body_stop(stop, st);
                    }
                }
            }
        }
        /* AfterHit of Stone Axe (Stealth Rock) and Ceaseless Edge (a Spikes layer), step G48: the foe's side of the user gets the
         * hazard after each damaged target (`source.side.foeSidesWithConditions()`, the Champions loop calls onAfterHit for every
         * damaged target without asking whether the user stands: data/mods/champions/scripts.ts:411-414; the base game's HP test is
         * at sim/battle-actions.ts:1123). addSideCondition adds a layer or does nothing (no line) when the side is full, and the
         * hazard of the same kind is not restarted: dfi_add_hazard. A holder of Sheer Force lays none (step G61: both the
         * onAfterHit and the onAfterSubDamage of the pin test `!move.hasSheerForce`, data/moves.ts:2230-2242, 18079-18086).
         * The foe's side is the side the hit went to (single target: the other side of the user). */
        if ((md->special == DFI_SPECIAL_STONE_AXE || md->special == DFI_SPECIAL_CEASELESS_EDGE) && !dfi_sf_strips(r->b, m, md)) {
            const uint32_t kind = md->special == DFI_SPECIAL_STONE_AXE ? DUOFORGE_SIDE_STEALTH_ROCK : DUOFORGE_SIDE_SPIKES;
            for (uint32_t i = 0u; i < count; ++i) {
                if (hit[i]) {
                    bool added = false;
                    st = dfi_add_hazard(r, (1u - side), kind, &added);
                    if (st != DUOFORGE_OK) {
                        return dfi_move_body_stop(stop, st);
                    }
                }
            }
        }
        /* AfterHit of Ice Spinner (step G86, data/moves.ts:9426-9428): clearTerrain for each damaged target, after the
         * DamagingHit handlers (issue 547: after Weak Armor's lines) and with no test of the user's HP (the Champions loop,
         * data/mods/champions/scripts.ts:411-414). With no terrain the clear does nothing and prints nothing
         * (field.clearTerrain returns false). A hit on a Substitute ends it in dfi_substitute_takes (onAfterSubDamage). */
        if (md->special == DFI_SPECIAL_ICE_SPINNER) {
            for (uint32_t i = 0u; i < count; ++i) {
                if (hit[i]) {
                    st = dfi_clear_terrain(r);
                    if (st != DUOFORGE_OK) {
                        return dfi_move_body_stop(stop, st);
                    }
                }
            }
        }
        /* The attacker's own Emergency Exit when DamagingHit (Rocky Helmet) took
         * it to half (data/mods/champions/scripts.ts:406, 419-420). */
        dfi_emergency_exit(r, user, user_before_hit);
        any = false;
        for (uint32_t i = 0u; i < count; ++i) {
            any = any || hit[i];
        }
        any = any || sub_any; /* a Substitute's hit counts for the next hit of a multi-hit move (decision 0032) */
        /* The hit loop's Update (sim/battle-actions.ts:967), after every hit. */
        if (any) {
            st = dfi_update(r);
            if (st != DUOFORGE_OK) {
                return dfi_move_body_stop(stop, st);
            }
        }
        if (m->hp == 0u) {
            if (split) {
                return dfi_move_body_stop(stop, DUOFORGE_E_UNSUPPORTED); /* step G78: the pin's loop goes on after the user's faint with two targets */
            }
            break; /* the user fainted: that hit counts and the loop ends (:969) */
        }
    }
    if (split) {
        for (uint32_t i = 0u; i < DFI_POSITIONS; ++i) {
            hit[i] = hit_all[i]; /* step G78: the split's per-hit mask ends with the loop; the post-loop reads the whole hit */
        }
    }
    r->hit_index = 1u;
    /* Then the loop's faintMessages. */
    if (any) {
        dfi_announce_faints(r, m->hp == 0u);
    }
    c->b = b;
    c->m = m;
    c->count = count;
    c->st = st;
    c->total = total;
    c->any = any;
    c->absorbed_any = absorbed_any;
    c->split = split;
    return DUOFORGE_OK;
}

/* Phase 7 of dfi_run_move_body: recoil, MoveFail, selfBoost and Life Orb (the last phase). */
static DFI_ALWAYS_INLINE duoforge_status dfi_move_body_after_loop(dfi_run *r, const dfi_queue_record *q, bool *ran,
                                                                  dfi_move_body_state *c, uint32_t *targets, bool *hit,
                                                                  uint32_t *hp_before, bool *sub_struggle)
{
    struct duoforge_battle *b = c->b;
    const uint32_t user = c->user;
    dfi_member *m = c->m;
    const uint32_t move_id = c->move_id;
    const dfi_move_data *md = c->md;
    uint32_t count = c->count;
    duoforge_status st = c->st;
    const bool status_move = c->status_move;
    uint32_t total = c->total;
    bool any = c->any;
    bool absorbed_any = c->absorbed_any;
    const bool split = c->split;
    (void)ran;
    (void)q;
    /* applyRecoilDamage after the hit loop: Struggle round(maxHP / 4), a
     * recoil move round(total * a / b), at least 1; then Update again
     * (:1003). */
    if (any) {
        uint32_t recoil = 0u;
        uint32_t recoil_cause = DUOFORGE_CAUSE_RECOIL;
        uint32_t recoil_id2 = 0u;
        if ((md->flags & DFI_MOVE_FLAG_STRUGGLE_RECOIL) != 0u) {
            recoil = ((uint32_t)m->hp_max + 2u) / 4u; /* Math.round(hp_max / 4) */
            recoil = recoil < 1u ? 1u : recoil;
        } else if (md->special == DFI_SPECIAL_STEEL_BEAM) {
            /* mindBlownRecoil (step G68, sim/battle-actions.ts:1380-1393): Math.round(maxhp / 2) when the total damage is not 0
             * (the pin's `if (move.totalDamage)` gate above), with the move's own condition as the effect: the line
             * `[from] steelbeam`, cause MOVE with the move in id2. Rock Head cancels only the effect 'recoil' (abilities.ts
             * rockhead, onDamage), so it does not cancel this one. */
            if (total != 0u) {
                recoil = ((uint32_t)m->hp_max + 1u) / 2u; /* Math.round(hp_max / 2): .5 rounds up */
                recoil_cause = DUOFORGE_CAUSE_MOVE;
                recoil_id2 = move_id;
            }
        } else if (md->recoil[1] != 0u && total != 0u) {
            recoil = (total * md->recoil[0] * 2u + md->recoil[1]) / (2u * md->recoil[1]);
            recoil = recoil < 1u ? 1u : recoil;
            /* Rock Head (data/abilities.ts rockhead, onDamage): the damage of
             * a recoil move's recoil is cancelled, with no line. Struggle's
             * recoil (the branch above) is directDamage and never reaches
             * the handler. The Emergency Exit check that follows sees no
             * change of HP. */
            if (dfi_ability(r->b, m, DFI_ABILITY_ROCKHEAD)) {
                recoil = 0u;
            }
        }
        if (recoil != 0u) {
            const uint32_t user_before = m->hp;
            st = dfi_deal(r, user, recoil, recoil_cause, recoil_id2, DUOFORGE_NO_POSITION,
                          ((md->flags & DFI_MOVE_FLAG_STRUGGLE_RECOIL) != 0u ? DFI_DMG_DIRECT
                           : md->special == DFI_SPECIAL_STEEL_BEAM ? DFI_DMG_CONDITION : DFI_DMG_RECOIL));
            if (st != DUOFORGE_OK) {
                return st;
            }
            dfi_emergency_exit(r, user, user_before); /* inside applyRecoilDamage */
        }
        /* step G67: the Air Balloon of a Substitute's holder that a Struggle hit went to pops after the recoil (see
         * dfi_substitute_takes). */
        for (uint32_t i = 0u; i < count; ++i) {
            if (sub_struggle[i] && dfi_holds(r->b, dfi_at(r->b, targets[i]), DFI_ITEM_AIRBALLOON)) {
                dfi_use_item(r, targets[i]);
            }
        }
        st = dfi_update(r);
        if (st != DUOFORGE_OK) {
            return st;
        }
        /* AfterMoveSecondary, Eject Button first (step G32, the Champions mod's onAfterMoveSecondary, data/mods/champions/
         * items.ts:266-281, priority 2, so before the frozen cure at 0): a holder that a damaging move of another Pokemon
         * hit and that stands, with a member to send in and no switch flag that is `true` on any active Pokemon (an
         * Emergency Exit that is already set: Pokemon.switchFlag === true; the pivot flags are strings), sets its own and
         * uses the item (-enditem). Two eligible holders are ordered by Speed with a tie drawn: refused. */
        if (!status_move) {
            uint32_t ejectors = 0u;
            uint32_t ejector = DFI_POSITIONS;
            bool tie = false;
            for (uint32_t i = 0u; i < count; ++i) {
                const uint32_t t = targets[i];
                const dfi_member *tm = dfi_at(b, t);
                if (hit[i] && t != user && tm != NULL && tm->hp != 0u && dfi_holds(b, tm, DFI_ITEM_EJECTBUTTON) &&
                    dfi_can_switch(b, t / 2u) && ((r->drag_pending >> t) & 1u) == 0u) { /* items.ts:270 (forceSwitchFlag) */
                    /* AfterMoveSecondary is no left-to-right event (sim/battle.ts:788-796 lists Invulnerability, TryHit,
                     * DamagingHit and EntryHazard only): the handlers go by speedSort, the faster holder first. The one that
                     * runs first sets a switch flag, so the other returns. */
                    if (ejectors == 0u || r->speed_seen[t] > r->speed_seen[ejector]) {
                        ejector = t;
                        tie = false;
                    } else if (r->speed_seen[t] == r->speed_seen[ejector]) {
                        tie = true;
                    }
                    ejectors += 1u;
                }
            }
            if (ejectors > 1u && tie) {
                return DUOFORGE_E_UNSUPPORTED; /* an exact speed tie draws; no such draw is converted */
            }
            bool pending = false;
            for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
                pending = pending || dfi_pos(b, flat)->switch_flag == DFI_SWITCH_EMERGENCY_EXIT;
            }
            if (ejectors == 1u && !pending) {
                dfi_pos(b, ejector)->switch_flag = (uint8_t)DFI_SWITCH_EMERGENCY_EXIT; /* switchFlag = true */
                dfi_use_item(r, ejector); /* [-enditem] */
            }
        }
        /* AfterMoveSecondary: a move that thaws its target (Scald,
         * thawsTarget) cures a frozen one after the secondaries and the second
         * Update (frz.onAfterMoveSecondary, data/conditions.ts:112-116, run by
         * afterMoveSecondaryEvent, data/mods/champions/scripts.ts:574-576),
         * before the targets' Emergency Exit. */
        if ((dfi_pool_move_flags2[move_id] & DFI_MOVE_FLAG2_THAWS_TARGET) != 0u) {
            for (uint32_t i = 0u; i < count; ++i) {
                dfi_member *tm = dfi_at(b, targets[i]);
                if (hit[i] && tm->hp != 0u && tm->status == DFI_STATUS_FRZ) {
                    duoforge_event cure = dfi_event_make(DUOFORGE_EVENT_CURE_STATUS, targets[i]);
                    cure.detail = tm->status;
                    cure.flags = (uint8_t)DUOFORGE_EVENT_FLAG_MESSAGE;
                    dfi_emit(r, &cure); /* [-curestatus] frz [msg] */
                    tm->status = (uint8_t)DFI_STATUS_NONE;
                    tm->status_counter = 0u;
                    r->b->tail.sides[targets[i] / 2u].sleep_cant[dfi_pos(r->b, targets[i])->occupant] = 0u; /* decision 0066 */
                }
            }
        }
        /* Red Card (step G46): AfterMoveSecondary of each target that the damaging move hit, after the forced switch of the
         * move and before the target's own Emergency Exit (data/mods/champions/scripts.ts:576-600, no Sheer Force gate). */
        if (!status_move) {
            for (uint32_t i = 0u; i < count; ++i) {
                if (hit[i]) {
                    dfi_red_card(r, user, targets[i]);
                }
            }
        }
        /* After the secondaries of the hit loop: a target that fell to half
         * HP (sim/battle-actions.ts:1005-1017). A Sheer Force holder's stripped move
         * does not check it (step G61, data/mods/champions/scripts.ts:578, the
         * `!(move.hasSheerForce && pokemon.hasAbility('sheerforce'))` test). */
        if (!dfi_sf_strips(r->b, m, md)) {
            for (uint32_t i = 0u; i < count; ++i) {
                if (hit[i]) {
                    if (split && i == 0u) {
                        continue; /* step G78: after a split the pin checks only the second target (its damage array is [undefined, d2]) */
                    }
                    dfi_emergency_exit(r, targets[i], hp_before[i]);
                }
            }
        }
    }
    /* MoveFail (sim/battle-actions.ts:527-533, step G68): when the hit steps left no target (a miss, a Protect, an
     * invulnerability), Steel Beam's onMoveFail deals round(maxhp / 2) to the user with the move's own condition: the line
     * `[from] steelbeam`, cause MOVE with the move in id2, then the EmergencyExit check of useMoveInner (the user is not
     * the target). A move that stops before its hit steps (TryMove, a failed PP, no target) is not a MoveFail and returned
     * above. A Substitute's hit counts as a hit (any), so no MoveFail follows it. */
    /* A Substitute's hit leaves the target null (the pin's HIT_SUBSTITUTE, data/mods/champions/scripts.ts:350-352), so the
     * move's result is false: a MoveFail for the single target of Steel Beam, even though `any` counts the absorbed hit. */
    if ((!any || absorbed_any) && md->special == DFI_SPECIAL_STEEL_BEAM && m->hp != 0u) {
        const uint32_t user_before = m->hp;
        const uint32_t fail_damage = ((uint32_t)m->hp_max + 1u) / 2u; /* Math.round(maxhp / 2) */
        st = dfi_deal(r, user, fail_damage, DUOFORGE_CAUSE_MOVE, move_id, DUOFORGE_NO_POSITION, DFI_DMG_CONDITION);
        if (st != DUOFORGE_OK) {
            return st;
        }
        dfi_emergency_exit(r, user, user_before);
    }
    /* selfBoost (step G32, sim/battle-actions.ts:520): once the hit loop is done and the move hit something, the user's
     * own stat change of the move (Clanging Scales: Defense -1), before AfterMoveSecondarySelf; moveHit with isSelf, so a
     * stat that cannot change shows nothing. */
    if (any && md->special == DFI_SPECIAL_CLANGING_SCALES && m->hp != 0u) {
        static const uint8_t def_down[DFI_STAT_STAGE_COUNT] = {6u, 5u, 6u, 6u, 6u, 6u, 6u};
        (void)dfi_boost(r, user, def_down, DFI_POSITIONS, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_SELF));
    }
    /* Scale Shot (step G54, data/moves.ts:15779-15799): selfBoost {def: -1, spe: 1}, the same moveHit with isSelf after the loop
     * and only when the move hit something; the boosts go in the pin's order (def, then spe: the stage index order). */
    if (any && md->special == DFI_SPECIAL_SCALE_SHOT && m->hp != 0u) {
        static const uint8_t def_down_spe_up[DFI_STAT_STAGE_COUNT] = {6u, 5u, 6u, 6u, 7u, 6u, 6u};
        (void)dfi_boost(r, user, def_down_spe_up, DFI_POSITIONS, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_SELF));
    }
    /* AfterMoveSecondarySelf: Life Orb takes a tenth of the holder's HP
     * (at least 1) after a damaging move that hit something, unless the holder
     * has a forceSwitchFlag (items.ts:3414): a Red Card drag of the user, which
     * runs before this, sets it (drag_pending, step G46). */
    /* Sheer Force (step G61): the holder's own AfterMoveSecondarySelf is not run for a move it stripped
     * (sim/battle-actions.ts:536, useMoveInner), so no Life Orb recoil and no user Emergency Exit from it. */
    if (any && dfi_holds(r->b, m, DFI_ITEM_LIFEORB) && ((r->drag_pending >> user) & 1u) == 0u &&
        !dfi_sf_strips(r->b, m, md)) {
        const uint32_t recoil = (uint32_t)m->hp_max / 10u;
        const uint32_t user_before = m->hp;
        st = dfi_deal(r, user, recoil == 0u ? 1u : recoil, DUOFORGE_CAUSE_ITEM, 1u + DFI_ITEM_LIFEORB,
                      DUOFORGE_NO_POSITION, DFI_DMG_ITEM);
        if (st != DUOFORGE_OK) {
            return st;
        }
        dfi_emergency_exit(r, user, user_before); /* after AfterMoveSecondarySelf */
    }
    return DUOFORGE_OK;
}

static duoforge_status dfi_run_move_body(dfi_run *r, const dfi_queue_record *q, bool *ran)
{
    r->hit_index = 1u;
    struct duoforge_battle *b = r->b;
    const uint32_t side = q->side;
    const uint32_t user = side * 2u + (uint32_t)q->slot;
    dfi_active_slot *pos = dfi_pos(b, user);
    dfi_member *m = dfi_at(b, user);
    *ran = false;
    uint32_t targets[DFI_POSITIONS] = {0};
    bool hit[DFI_POSITIONS] = {false, false, false, false};
    uint32_t hp_before[DFI_POSITIONS] = {0u, 0u, 0u, 0u};
    bool sub_struggle[DFI_POSITIONS] = {false, false, false, false};
    dfi_move_body_state c;
    bool stop = false;
    duoforge_status st = DUOFORGE_OK;
    c.b = b;
    c.side = side;
    c.user = user;
    c.pos = pos;
    c.m = m;
    st = dfi_move_body_prepare(r, q, ran, &c, targets, &stop);
    if (stop) {
        return st;
    }
    st = dfi_move_body_announce(r, q, ran, &c, targets, &stop);
    if (stop) {
        return st;
    }
    st = dfi_move_body_try_move(r, q, ran, &c, targets, &stop);
    if (stop) {
        return st;
    }
    st = dfi_move_body_status_handlers(r, q, ran, &c, targets, &stop);
    if (stop) {
        return st;
    }
    st = dfi_move_body_hit_steps(r, q, ran, &c, targets, hit, &stop);
    if (stop) {
        return st;
    }
    st = dfi_move_body_hit_loop(r, q, ran, &c, targets, hit, hp_before, sub_struggle, &stop);
    if (stop) {
        return st;
    }
    return dfi_move_body_after_loop(r, q, ran, &c, targets, hit, hp_before, sub_struggle);
}

#include "combat/flow/switch.h"

/* The entry abilities of the closure: an ability's onStart runs as a
 * SwitchIn handler (Battle.getCallback). */
static bool dfi_has_entry(const struct duoforge_battle *b, const dfi_member *m);

#include "combat/field/terrain_seeds.h"





#include "combat/abilities/entry.h"

#include "combat/abilities/skill_swap.h"

/* The entrant of a slot with a pending wish (decision 0045, step G82): the condition's onSwitchIn runs its onSwap
 * (data/moves.ts:8366-8377, found by sim/battle.ts:1139-1151 for the occupant). A fainted entrant does nothing (the pin's
 * !target.fainted). The heal is full HP and the status ends with it (clearStatus is silent: sim/pokemon.ts:1755-1761, "does not give
 * cure message"; no CURE event, decision 0045 option A). The -heal line is the HEAL event (cause MOVE, id2 the move). A full-HP entrant
 * without a status keeps the wish. */
static duoforge_status dfi_wish_heal(dfi_run *r, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    if (!dfi_wish_pending(b, flat)) {
        return DUOFORGE_OK;
    }
    dfi_member *m = dfi_at(b, flat);
    if (m == NULL || m->hp == 0u) {
        return DUOFORGE_OK;
    }
    if (m->hp >= m->hp_max && m->status == DFI_STATUS_NONE) {
        return DUOFORGE_OK; /* the wish waits for the next entrant */
    }
    m->hp = m->hp_max;
    if (m->status == DFI_STATUS_TOX) {
        b->tail.sides[flat / 2u].toxic_stage[dfi_pos(b, flat)->occupant] = 0u;
    }
    m->status = (uint8_t)DFI_STATUS_NONE;
    m->status_counter = 0u;
    b->tail.sides[flat / 2u].sleep_cant[dfi_pos(b, flat)->occupant] = 0u; /* decision 0066 */
    b->tail.sides[flat / 2u].positions[flat % 2u].position_flags =
        (uint8_t)(b->tail.sides[flat / 2u].positions[flat % 2u].position_flags & ~DFI_POSFLAG_HEALING_WISH); /* wide-operands-reviewed */
    dfi_emit_hp(r, dfi_ev(DUOFORGE_EVENT_HEAL, flat, DUOFORGE_CAUSE_MOVE, DFI_MOVE_HEALINGWISH, DUOFORGE_NO_POSITION));
    return DUOFORGE_OK;
}

/* runSwitch (sim/battle-actions.ts:177-192): every active Pokemon, a
 * fainted one included, is sorted by its last speed (Battle.speedSort, ties
 * shuffled); the SwitchIn handlers then run in that order. A tie decides
 * something only between two entering Pokemon with an entry ability, or
 * between two standing White Herb holders, whose onAnySwitchIn runs for
 * every holder on the field (Team C): only such a group draws (decision
 * 0006 section 5.1). The hazards of the entering Pokemon's side (step G37) are SwitchIn handlers too, so a Pokemon that
 * enters a side with a hazard counts as a bearer (the reference's own count: ps_trace.js adds the side's handlers). */
static duoforge_status dfi_run_entries(dfi_run *r, uint32_t entering)
{
    struct duoforge_battle *b = r->b;
    uint32_t list[DFI_POSITIONS] = {0u, 0u, 0u, 0u};
    uint32_t n = 0u;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        if (dfi_at(b, flat) != NULL) {
            list[n] = flat;
            n += 1u;
        }
    }
    uint32_t sorted = 0u;
    while (sorted + 1u < n) {
        uint32_t next[DFI_POSITIONS] = {0u, 0u, 0u, 0u};
        uint32_t count = 1u;
        next[0] = sorted;
        for (uint32_t i = sorted + 1u; i < n; ++i) {
            const uint32_t best = r->speed_seen[list[next[0]]];
            const uint32_t speed = r->speed_seen[list[i]];
            if (speed > best) {
                next[0] = i;
                count = 1u;
            } else if (speed == best) {
                next[count] = i;
                count += 1u;
            }
        }
        uint32_t bearers = 0u;
        uint32_t herbs = 0u;
        for (uint32_t i = 0u; i < count; ++i) {
            const uint32_t flat = list[next[i]];
            const dfi_member *m = dfi_at(b, flat);
            /* A pending wish of the entrant's slot is a SwitchIn handler whatever its HP and status: the callback exists, so
             * ps_trace.js:186-189 counts it in the group, and trace_to_c.py:541-548 keeps the tie when that count is not 0. The engine
             * counts it the same way (decision 0045, the lead's rule), so a full-HP wish entrant keeps the draw too (R6). */
            bearers += (((entering >> flat) & 1u) != 0u && m->hp != 0u &&
                        (dfi_has_switch_in(b, m) || dfi_side_has_hazard(b, flat / 2u) || dfi_wish_pending(b, flat)))
                           ? 1u
                           : 0u;
            herbs += dfi_herb_holder(b, flat) ? 1u : 0u;
        }
        for (uint32_t i = 0u; i < count; ++i) {
            if (next[i] != sorted + i) {
                const uint32_t e = list[sorted + i];
                list[sorted + i] = list[next[i]];
                list[next[i]] = e;
            }
        }
        for (uint32_t start = sorted; start + 1u < sorted + count && (bearers >= 2u || herbs >= 2u); ++start) {
            uint32_t v = 0u;
            const duoforge_status st = dfi_draw(r->draws, DFI_SITE_SPEED_TIE, start - sorted, count, &v);
            if (st != DUOFORGE_OK) {
                return st;
            }
            if (sorted + v != start) {
                const uint32_t e = list[start];
                list[start] = list[sorted + v];
                list[sorted + v] = e;
            }
        }
        sorted += count;
    }
    /* The hazards and the abilities (priority 0) in that order, then the terrain seeds
     * (Grassy and Psychic Seed, priority -1), then White Herb's onAnySwitchIn of every holder on the
     * field (priority -2, Team C), in the same order: the handlers'
     * fractional speeds follow it (sim/battle.ts:1008-1013). Within one Pokemon the side conditions (sub-order 4, the
     * hazards in their creation order) come before the ability (sub-order 7). Each handler is followed by faintMessages. */
    /* Unnerve first (onSwitchInPriority 1, data/abilities.ts:5259): comparePriority puts the priority before the speed, so its
     * announcements come before the other entry abilities whatever the Speed order, in the order of the list among
     * themselves. The speed ties were drawn above for every group of two bearers (Unnerve's onStart is a SwitchIn handler
     * like the others': the converter counts it), the priority only reorders the result. */
    for (uint32_t i = 0u; i < n; ++i) {
        const uint32_t flat = list[i];
        const dfi_member *m = dfi_at(b, flat);
        if (((entering >> flat) & 1u) != 0u && m->hp != 0u && dfi_ability_code(b, m) == 1u + DFI_ABILITY_UNNERVE) {
            const duoforge_status st = dfi_entry_ability(r, flat);
            if (st != DUOFORGE_OK) {
                return st;
            }
        }
    }
    for (uint32_t pass = 0u; pass < 2u; ++pass) {
        for (uint32_t i = 0u; i < n; ++i) {
            const uint32_t flat = list[i];
            const dfi_member *m = dfi_at(b, flat);
            if (((entering >> flat) & 1u) == 0u) {
                continue;
            }
            if (pass == 0u) {
                /* The slot condition (subOrder 3, sim/battle.ts:975-977) runs before the hazards (4) and the ability (7) of the same
                 * entrant (comparePriority, sim/battle.ts:393-411): the Healing Wish heal comes first, after the priority +1 pass. */
                const duoforge_status ws = dfi_wish_heal(r, flat);
                if (ws != DUOFORGE_OK) {
                    return ws;
                }
                const duoforge_status hs = dfi_hazards_enter(r, flat); /* faintMessages after each of its handlers */
                if (hs != DUOFORGE_OK) {
                    return hs;
                }
                if (r->ended) {
                    return DUOFORGE_OK;
                }
                if (m->hp != 0u && dfi_has_entry(b, m) && dfi_ability_code(b, m) != 1u + DFI_ABILITY_UNNERVE) {
                    const duoforge_status st = dfi_entry_ability(r, flat);
                    if (st != DUOFORGE_OK) {
                        return st;
                    }
                    dfi_process_faints(r);
                    if (r->ended) {
                        return DUOFORGE_OK;
                    }
                }
                if (m->hp != 0u && dfi_ability(r->b, m, DFI_ABILITY_CLOUDNINE)) {
                    /* Cloud Nine's onSwitchIn: -ability|holder|Cloud Nine (no [from]); its onStart only clears the ending flag
                     * and runs WeatherChange, which prints nothing (data/abilities.ts:546-553). From here the weather is
                     * suppressed (dfi_weather_suppressed). It is not an entry of dfi_has_entry: a copy or a swap starts it
                     * without a line (dfi_skill_swap_start, dfi_trace). */
                    const duoforge_event cn = dfi_ev(DUOFORGE_EVENT_ABILITY, flat, DUOFORGE_CAUSE_NONE,
                                                     1u + DFI_ABILITY_CLOUDNINE, DUOFORGE_NO_POSITION);
                    dfi_emit(r, &cn);
                }
                /* The holder's own SwitchIn handlers keep their subOrder: an ability (7) before an item (8)
                 * (sim/battle.ts effectTypeOrder), so Cloud Nine's line comes before Air Balloon's on one holder. */
                /* Air Balloon's onStart (step G67, data/items.ts:191-195): the holder's own -item line, ITEM_SHOWN (decision
                 * 0033). Its place among the handlers is measured against recorded battles (the order of the item's onStart
                 * against the entry abilities is not pinned yet). */
                /* Step K4 (#475, data/items.ts:191-195): no line under Gravity (`!this.field.getPseudoWeather('gravity')`). */
                if (m->hp != 0u && dfi_holds(b, m, DFI_ITEM_AIRBALLOON) && b->tail.gravity_turns == 0u) {
                    duoforge_event shown = dfi_ev(DUOFORGE_EVENT_ITEM_SHOWN, flat, DUOFORGE_CAUSE_NONE, 1u + DFI_ITEM_AIRBALLOON,
                                                  DUOFORGE_NO_POSITION);
                    dfi_emit(r, &shown);
                }
            } else if (m->hp != 0u && dfi_seed_terrain(r->b, m) != DFI_TERRAIN_NONE) {
                dfi_terrain_seed(r, flat);
                dfi_process_faints(r);
                if (r->ended) {
                    return DUOFORGE_OK;
                }
            }
        }
    }
    /* The handlers of priority -2, in the order of the list (the holders' speeds): Hospitality's onStart of an entering
     * Pokemon (an ability: sub-order 7) and White Herb's onAnySwitchIn of every holder on the field (an item: sub-order
     * 8), so the ability of one Pokemon comes before its own herb. */
    for (uint32_t i = 0u; i < n; ++i) {
        const dfi_member *m = dfi_at(b, list[i]);
        /* The handler of the sheet's ability: a Trace holder that copied it ran it at once (dfi_trace), and the SwitchIn
         * handlers were collected before. */
        if (((entering >> list[i]) & 1u) != 0u && m->hp != 0u && dfi_ability(b, m, DFI_ABILITY_HOSPITALITY) &&
            m->ability == 1u + DFI_ABILITY_HOSPITALITY) {
            dfi_hospitality(r, list[i]);
        }
        dfi_white_herb(r, list[i], dfi_use_item);
    }
    return DUOFORGE_OK;
}

#include "combat/forms/mega.h"

/* ---------------------------------------------------------------- turn */

/* fieldEvent('Residual') (sim/battle.ts:484-567). The reference lists the
 * handlers of the field (weather: order 1 with its duration; Grassy
 * Terrain's duration: order 27), then per active Pokemon in slot order, a
 * fainted one included: its status handler with a callback (burn, order
 * 10; poison, order 9, Team C), one handler per volatile with a duration (Protect, the stall
 * counter, flinch: no order), and the per-Pokemon field handler of Grassy
 * Terrain (heal, order 5, sub-order 2). Battle.speedSort orders the list by
 * order, speed (the speed each Pokemon had at its last updateSpeed; 0 for
 * the field) and sub-order; ties among callbacks draw (relative to their
 * group), ties among duration handlers change nothing and are not drawn
 * (decision 0006 section 5.1). The list is sorted once, with all its draws,
 * before any handler runs. The callbacks of orders 1 to 10 sort ahead of
 * the duration handlers of orders 26 and 27; White Herb's (order 29, Team
 * C) sorts after them. After each callback faints are processed, and a
 * finished battle stops the residual phase. */

#include "combat/flow/residual_collect.h"

/* Battle.speedSort over the residual handlers, continued from *sorted until `want` callbacks are placed (*placed counts
 * them) or `want_sorted` entries are sorted. A group of equal handlers is shuffled in the reference, one draw per step;
 * the engine draws a group that holds two callbacks or more (the tie shows: two ends, two sleeps, a heal order) and
 * not one that shows nothing (a duration that ends nowhere, or one of two): the converter drops that draw from the tape
 * the same way. A group may mix both kinds (two Yawns, one of which ends now). */
static duoforge_status dfi_residual_sort(dfi_run *r, dfi_residual_entry *list, uint32_t n, uint32_t *sorted,
                                         uint32_t *placed, uint32_t want, uint32_t want_sorted)
{
    while (*placed < want && *sorted < want_sorted && *sorted < n) {
        const uint32_t at = *sorted;
        uint32_t next[DFI_RES_MAX] = {0};
        uint32_t count = 1u;
        next[0] = at;
        for (uint32_t i = at + 1u; i < n; ++i) {
            const uint32_t c = dfi_residual_compare(&list[next[0]], &list[i]);
            if (c == 2u) {
                next[0] = i;
                count = 1u;
            } else if (c == 1u) {
                next[count] = i;
                count += 1u;
            }
        }
        for (uint32_t i = 0u; i < count; ++i) {
            if (next[i] != at + i) {
                const dfi_residual_entry e = list[at + i];
                list[at + i] = list[next[i]];
                list[next[i]] = e;
            }
        }
        uint32_t calls = 0u;
        for (uint32_t i = at; i < at + count; ++i) {
            calls += list[i].callback ? 1u : 0u;
        }
        const bool callbacks = calls >= 2u;
        for (uint32_t start = at; start + 1u < at + count && callbacks; ++start) {
            uint32_t v = 0u;
            const duoforge_status st = dfi_draw(r->draws, DFI_SITE_SPEED_TIE, start - at, count, &v);
            if (st != DUOFORGE_OK) {
                return st;
            }
            if (at + v != start) {
                const dfi_residual_entry e = list[start];
                list[start] = list[at + v];
                list[at + v] = e;
            }
        }
        *placed += calls;
        *sorted = at + count;
    }
    return DUOFORGE_OK;
}

/* fieldEvent (sim/battle.ts:484-575) runs faintMessages after every handler that does not end: a handler whose duration
 * runs out ends and the loop goes on at once (`continue`), any other, with or without a callback, is followed by it. A
 * faint that an ending handler queued (Perish Song's perish0, step G26) is shown and its win rule applied there: after
 * the first later handler that does not end, so before the `upkeep` line when there is one, after it (the epilogue of the
 * action) when there is none. */
static void dfi_residual_faints(dfi_run *r)
{
    if (r->faint_count != 0u) {
        dfi_process_faints(r);
    }
}

/* Whether the volatiles of the Pokemon at `flat` still exist at this point of the residual: it stands, or its faint is
 * queued and not yet processed (Pokemon.faint() only sets hp 0 and queues it; faintMessages clears the volatiles, and
 * a handler whose state is gone is skipped, sim/battle.ts:525-554). Their handlers run, and the faintMessages after
 * each is a faint point; those of a Pokemon whose faint was already processed are not. */
static bool dfi_residual_holder_stands(dfi_run *r, uint32_t flat)
{
    const dfi_member *m = dfi_at(r->b, flat);
    if (m != NULL && m->hp != 0u) {
        return true;
    }
    for (uint32_t i = 0u; i < r->faint_count; ++i) {
        if (r->faint_queue[i] == flat) {
            return true;
        }
    }
    return false;
}

/* What the no-order duration handlers of the residual look like before any of them runs (see the pair draws below):
 * `pair`: a standing Pokemon whose only no-order handlers are Protect's volatile (either variant) and a stall counter,
 * `had`: a no-order handler of any kind (a lockedmove included: issue 633), `key`: the Speed key that sorts it;
 * `ended_at`: the position whose no-order faint point ended the battle, DFI_POSITIONS when none did. */
typedef struct dfi_noorder_snapshot {
    bool pair[DFI_POSITIONS];
    bool had[DFI_POSITIONS];
    uint32_t key[DFI_POSITIONS];
    uint32_t ended_at;
    uint32_t drawn_slowest; /* the Speed key of the slowest no-order group drawn in phase 2, UINT32_MAX when none was */
    uint32_t draws_after_order; /* the draw count at the end of phase 2 (dfi_draws.log_len) */
} dfi_noorder_snapshot;

static duoforge_status dfi_residual_events(dfi_run *r);

/* The residual action. It keeps each position's HP from before its events
 * (residualPokemon): Emergency Exit looks at it after the Update that
 * follows, at the end of the turn (decision 0006 section 4.12). */
static duoforge_status dfi_residual(dfi_run *r)
{
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        const dfi_member *m = dfi_at(r->b, flat);
        r->residual_hp[flat] = m != NULL ? m->hp : 0u;
    }
    const duoforge_status st = dfi_residual_events(r);
    if (st == DUOFORGE_OK && !r->ended) {
        dfi_emit_plain(r, DUOFORGE_EVENT_UPKEEP, DUOFORGE_NO_POSITION); /* [upkeep] */
    }
    return st;
}

/* Speed Boost's onResidual (step G32, data/abilities.ts:4453-4465): +1 Speed once the Pokemon has been active for a turn
 * (`activeTurns` is 0 in the turn it came in: the state's NEWLY_SWITCHED flag, which ends with the turn). The boost is the
 * ability's own, so it shows `-ability|holder|Speed Boost|boost` before the -boost line, and nothing at +6. */
static void dfi_speed_boost(dfi_run *r, uint32_t flat)
{
    static const uint8_t spe_up[DFI_STAT_STAGE_COUNT] = {6u, 6u, 6u, 6u, 7u, 6u, 6u};
    const dfi_member *m = dfi_at(r->b, flat);
    if (m == NULL || m->hp == 0u || !dfi_ability(r->b, m, DFI_ABILITY_SPEEDBOOST) ||
        ((uint32_t)dfi_pos(r->b, flat)->flags & DFI_VOL_NEWLY_SWITCHED) != 0u) {
        return;
    }
    (void)dfi_boost(r, flat, spe_up, DFI_POSITIONS, dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_SPEEDBOOST, DFI_BOOST_PRIMARY));
}

/* Moody's onResidual (step G73, data/abilities.ts:2701-2734). The stats that can rise are those below +6 (accuracy and
 * evasion are not in the list), in the table order of the reference's boosts object (atk, def, spa, spd, spe); one of them
 * is drawn (random(n), n the list length: a list of one still draws, and an empty list does not draw). Then the stats that
 * can fall are those above -6 and not the raised one, drawn the same way. The boost is the ability's own: one boost call
 * {raised: +2, lowered: -1} with the raised key first (positives_first), so its line is -ability|holder|Moody|boost, then
 * -boost for the rise and -unboost for the fall. The draws come before the boost, so a boost that is refused (no foe left)
 * still draws. A holder whose faint was processed (or that is no longer on the field) does not run it; one whose faint is
 * only queued (Perish Song's perish0 earlier in this residual, dfi_residual_holder_stands) runs it: Pokemon.faint() only
 * sets hp 0, so the handler draws, and the boost of a Pokemon at 0 HP does nothing. */
static duoforge_status dfi_moody(dfi_run *r, uint32_t flat)
{
    const dfi_member *m = dfi_at(r->b, flat);
    if (m == NULL || !dfi_ability(r->b, m, DFI_ABILITY_MOODY)) {
        return DUOFORGE_OK;
    }
    dfi_active_slot *pos = dfi_pos(r->b, flat);
    uint32_t up[DFI_STAGE_ACCURACY] = {0u, 0u, 0u, 0u, 0u};
    uint32_t n_up = 0u;
    for (uint32_t i = 0u; i < DFI_STAGE_ACCURACY; ++i) {
        if (pos->stages[i] < DFI_STAGE_MAX) {
            up[n_up] = i;
            n_up += 1u;
        }
    }
    uint32_t raised = DFI_STAT_STAGE_COUNT; /* none */
    if (n_up > 0u) {
        uint32_t v = 0u;
        const duoforge_status st = dfi_draw(r->draws, DFI_SITE_MOODY, 0u, n_up, &v);
        if (st != DUOFORGE_OK) {
            return st;
        }
        raised = up[v];
    }
    uint32_t down[DFI_STAGE_ACCURACY] = {0u, 0u, 0u, 0u, 0u};
    uint32_t n_down = 0u;
    for (uint32_t i = 0u; i < DFI_STAGE_ACCURACY; ++i) {
        if (pos->stages[i] > 0u && i != raised) {
            down[n_down] = i;
            n_down += 1u;
        }
    }
    uint32_t lowered = DFI_STAT_STAGE_COUNT;
    if (n_down > 0u) {
        uint32_t v = 0u;
        const duoforge_status st = dfi_draw(r->draws, DFI_SITE_MOODY, 0u, n_down, &v);
        if (st != DUOFORGE_OK) {
            return st;
        }
        lowered = down[v];
    }
    uint8_t boosts[DFI_STAT_STAGE_COUNT] = {6u, 6u, 6u, 6u, 6u, 6u, 6u}; /* biased by 6: no change */
    if (raised < DFI_STAT_STAGE_COUNT) {
        boosts[raised] = 8u; /* +2 */
    }
    if (lowered < DFI_STAT_STAGE_COUNT) {
        boosts[lowered] = 5u; /* -1 */
    }
    dfi_boost_effect effect = dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_MOODY, DFI_BOOST_PRIMARY);
    effect.positives_first = true;
    (void)dfi_boost(r, flat, boosts, DFI_POSITIONS, effect);
    return DUOFORGE_OK;
}

/* lockedmove's handler in the Residual event (step G56; issue 606, decision 0015 5dv; data/conditions.ts:253-285), in the
 * pin's two phases of one handler (sim/battle.ts:515-522):
 *   - the duration phase: a lock that was not restarted this turn (DFI_SINGLE_TURN_LOCK_UNUSED: its holder's move was stopped
 *     before its use, which with the refusals of the stopped use is only a sleep) is at duration 1 here, so its countdown
 *     reaches 0 and ends it with onEnd (dfi_lock_end: confusion when the count is 1 or less), and its onResidual does not run;
 *   - the callback phase, onResidual: otherwise the lock was restarted by its use this turn (the duration goes 2 -> 1, no
 *     end), its count went down at the use (the AfterMove block), and a holder that is asleep now (put to sleep after its
 *     use) loses the lock silently (the delete, no end, no confusion).
 * A lock not used this turn whose holder is not asleep (a flinch, a full paralysis, a freeze, a confusion self-hit) is still
 * refused where its move is stopped. The bit is read, not the status: a holder cured after its `cant` line is ended too. */
static duoforge_status dfi_residual_lock(dfi_run *r, uint32_t flat)
{
    dfi_tail_pos *lt = &r->b->tail.sides[flat / 2u].positions[flat % 2u];
    if (lt->lock_turns == 0u) {
        return DUOFORGE_OK;
    }
    if (((uint32_t)lt->single_turn & DFI_SINGLE_TURN_LOCK_UNUSED) != 0u) {
        return dfi_lock_end(r, flat); /* dfi_lock_remove clears the bit */
    }
    const dfi_member *lm = dfi_at(r->b, flat);
    if (lm != NULL && lm->status == DFI_STATUS_SLP) {
        dfi_lock_remove(r->b, flat);
    }
    return DUOFORGE_OK;
}

/* Leech Seed's residual (decision 0047; data/moves.ts:10216-10226, onResidualOrder 8): the holder's target is the Pokemon that
 * stands in the source's slot now (getAtSlot(sourceSlot), so a switched-in source's slot still drains into whoever is there), and
 * nothing happens when it is absent, fainted or at 0 HP. The holder loses baseMaxhp / 8 (this.damage, `[from] Leech Seed [of]
 * target`); the target then gains that amount (this.heal, silent: no line, so the HEAL event carries cause LEECH_SEED). A holder
 * that is down does not drain (its volatile handlers do not run: fieldEvent skips fainted holders, sim/battle.ts:514-517). The
 * source's slot is `leech_seed_source` - 1 (a flat position). Big Root's x1.3 is not modelled (not in the pool). */
static duoforge_status dfi_leech_drain(dfi_run *r, uint32_t holder)
{
    struct duoforge_battle *b = r->b;
    const uint8_t src = b->tail.sides[holder / 2u].positions[holder % 2u].leech_seed_source;
    if (src == 0u || src - 1u >= DFI_POSITIONS) {
        return DUOFORGE_OK;
    }
    const uint32_t target = (uint32_t)src - 1u;
    dfi_member *h = dfi_at(b, holder);
    dfi_member *t = dfi_at(b, target);
    if (h == NULL || h->hp == 0u || t == NULL || t->hp == 0u) {
        return DUOFORGE_OK; /* "Nothing to leech into" (sim/moves.ts:10219-10222), or the holder is down */
    }
    const uint32_t amount = (uint32_t)h->hp_max / 8u; /* baseMaxhp / 8 (trunc) */
    if (amount == 0u) {
        return DUOFORGE_OK;
    }
    const uint32_t before = h->hp;
    /* this.damage in the volatile's onResidual: its effect is the condition (DFI_DMG_CONDITION; Magic Guard refuses it) */
    /* An Ally Switch can put the holder on its source's slot (issue 541): it drains into itself, and the line has no [of] (spreadDamage
     * names the source only when it is not the target, sim/battle.ts:2155). */
    const uint32_t of = target == holder ? DUOFORGE_NO_POSITION : target;
    const duoforge_status st = dfi_deal(r, holder, amount, DUOFORGE_CAUSE_LEECH_SEED, 0u, of, DFI_DMG_CONDITION); /* -damage [from] Leech Seed [of] */
    if (st != DUOFORGE_OK) {
        return st;
    }
    const uint32_t lost = before - (uint32_t)h->hp; /* the HP the holder really lost (dfi_deal caps it at its HP) */
    if (lost == 0u || t->hp == 0u) {
        return DUOFORGE_OK;
    }
    /* Pokemon.heal (sim/pokemon.ts:1640-1652): nothing at full HP, else the amount, capped at the max; the line is silent */
    if (t->hp >= t->hp_max) {
        return DUOFORGE_OK;
    }
    const uint32_t hp = (uint32_t)t->hp + lost;
    t->hp = (uint16_t)(hp > t->hp_max ? t->hp_max : hp); /* wide-operands-reviewed: <= hp_max */
    dfi_emit_hp(r, dfi_ev(DUOFORGE_EVENT_HEAL, target, DUOFORGE_CAUSE_LEECH_SEED, 0u, DUOFORGE_NO_POSITION));
    return DUOFORGE_OK;
}

/* Curse's residual (step G84b, decision 0063; data/moves.ts:3295-3303, the Champions override keeps the condition): onResidualOrder
 * 12, this.damage(baseMaxhp / 4) on the holder with no source, so the line is `-damage|T|hp|[from] Curse` (no [of]). Nothing when the
 * holder is down or the amount is zero. The flag is the holder's own (dfi_tail_clear_occupant ends it with the occupant). */
static duoforge_status dfi_curse_residual(dfi_run *r, uint32_t holder)
{
    struct duoforge_battle *b = r->b;
    dfi_member *h = dfi_at(b, holder);
    if (h == NULL || h->hp == 0u ||
        (b->tail.sides[holder / 2u].positions[holder % 2u].position_flags & DFI_POSFLAG_CURSED) == 0u) {
        return DUOFORGE_OK;
    }
    const uint32_t amount = (uint32_t)h->hp_max / 4u;
    if (amount == 0u) {
        return DUOFORGE_OK;
    }
    return dfi_deal(r, holder, amount, DUOFORGE_CAUSE_CURSE, 0u, DUOFORGE_NO_POSITION, DFI_DMG_CONDITION);
}

/* The phases of dfi_residual_events_run (restructure step 4, residual runner), in its order. Each is inlined into it
 * (DFI_ALWAYS_INLINE), so the cut changes no code. A phase that ends the residual early because the battle ended
 * sets *stop and returns DUOFORGE_OK, as the one function returned DUOFORGE_OK there. */
static DFI_ALWAYS_INLINE duoforge_status dfi_residual_stop(bool *stop)
{
    *stop = true;
    return DUOFORGE_OK;
}

/* Phase 2: the sort with its draws, and the draws of the side conditions' ties. */
static DFI_ALWAYS_INLINE duoforge_status dfi_residual_order(dfi_run *r, struct duoforge_battle *b, dfi_residual_entry *list,
                                                           uint32_t n, uint32_t first[DFI_SIDE_KINDS], uint32_t *early_out,
                                                           uint32_t *sorted_out, uint32_t *herbs_from_out)
{
    duoforge_status st = DUOFORGE_OK;
    /* The order in which a Pokemon's volatiles were added is not stored: the engine lists them in one fixed order, which
     * is the reference's or changes nothing except in the cases of dfi_residual_order_ambiguous (combat/
     * residual_order.h); those it refuses. */
    if (dfi_residual_order_ambiguous(list, n)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    uint32_t early = 0u;       /* the entries of orders 1 to 23: everything that sorts before the side conditions (26) */
    uint32_t early_calls = 0u; /* ... of which the callbacks (a tie of them draws) */
    uint32_t herbs = 0u;       /* White Herb's, order 29 */
    for (uint32_t i = 0u; i < n; ++i) {
        if (list[i].kind == DFI_RES_WHITE_HERB || list[i].kind == DFI_RES_SPEED_BOOST || list[i].kind == DFI_RES_MOODY) {
            herbs += 1u; /* the late callbacks: Speed Boost and Moody (28) and White Herb (29) */
        } else if (list[i].order < 26u) {
            early += 1u;
            early_calls += list[i].callback ? 1u : 0u;
        }
    }
    /* The sort's draws in the reference's order: the early callbacks, the
     * side conditions (26), then White Herb (29). */
    uint32_t sorted = 0u;
    uint32_t placed = 0u;
    st = dfi_residual_sort(r, list, n, &sorted, &placed, UINT32_MAX, early);
    if (st != DUOFORGE_OK) {
        return st;
    }
    /* The side conditions end in the group of order 26, sub-order by kind
     * (Reflect 1, Light Screen 2, Tailwind 5, Aurora Veil 10: data/moves.ts:864-865). The same kind on both sides
     * ties; the shuffle decides the order of the two end lines when both
     * run out now: only then a draw (decision 0007 section 6). `first`: the
     * side whose line comes first, per kind. */
    for (uint32_t k = 0u; k < DFI_SIDE_KINDS; ++k) {
        const uint8_t *t0 = dfi_side_turns(b, 0u, k);
        const uint8_t *t1 = dfi_side_turns(b, 1u, k);
        if (*t0 == 1u && *t1 == 1u) {
            st = dfi_draw(r->draws, DFI_SITE_SPEED_TIE, 0u, 2u, &first[k]);
            if (st != DUOFORGE_OK) {
                return st;
            }
        }
    }
    const uint32_t herbs_from = sorted; /* the herbs follow the duration handlers of 26 and 27 */
    st = dfi_residual_sort(r, list, n, &sorted, &placed, early_calls + herbs, n);
    if (st != DUOFORGE_OK) {
        return st;
    }
    /* The third pass (issues 630 and 633, docs/mechanics/flow/5ga-residual-noorder-tie.md): the rest of the list, the duration
     * handlers of 26 and 27 and the no-order handlers, which sort last, the fastest Speed first. The reference shuffles each
     * group of them in this same sort, before any handler runs; a group with two callbacks or more (two lockedmoves of one
     * Speed) draws here, with the group's size as the bound, and phase 6 runs it in the order the draws leave. A group with
     * fewer is not drawn here (the conversion drops its draw unless the battle ends inside it: dfi_residual_pair_draws). */
    uint32_t rest = sorted;
    st = dfi_residual_sort(r, list, n, &rest, &placed, UINT32_MAX, n);
    if (st != DUOFORGE_OK) {
        return st;
    }
    *early_out = early;
    *sorted_out = sorted;
    *herbs_from_out = herbs_from;
    return DUOFORGE_OK;
}

/* Phase 3: the handlers before the side conditions (orders 1 to 25), in the sorted order. */
static DFI_ALWAYS_INLINE duoforge_status dfi_residual_early(dfi_run *r, struct duoforge_battle *b, const dfi_residual_entry *list,
                                                           uint32_t early, bool *stop)
{
    duoforge_status st = DUOFORGE_OK;
    for (uint32_t i = 0u; i < early; ++i) {
        const dfi_residual_entry *e = &list[i];
        if (e->kind == DFI_RES_WEATHER) {
            /* The duration counts down first; at 0 the weather ends. */
            b->weather_turns = (uint8_t)((uint32_t)b->weather_turns - 1u); /* wide-operands-reviewed: >= 1 */
            duoforge_event w = dfi_event_make(DUOFORGE_EVENT_WEATHER, DUOFORGE_NO_POSITION);
            if (b->weather_turns == 0u) {
                b->weather = (uint8_t)DFI_WEATHER_NONE;
                dfi_emit(r, &w); /* -weather|none */
            } else {
                w.detail = b->weather;
                w.flags = (uint8_t)DUOFORGE_EVENT_FLAG_UPKEEP;
                dfi_emit(r, &w); /* -weather|...|[upkeep] */
                /* Cloud Nine suppresses the Weather handlers (battle.ts:618, :891): no damage and no heal here, and the
                 * 'Update' that eachEvent('Weather') ends with is not run either, because sandstorm and snowscape call it only
                 * while their weather is effective (conditions.ts sandstorm and snowscape onFieldResidual, isWeather). Rain and
                 * sun call it unconditionally (conditions.ts raindance and sunnyday), so their 'Update' runs (battle.ts:472). */
                const bool suppressed = dfi_weather_suppressed(r);
                if (!suppressed) {
                    if (b->weather == DFI_WEATHER_SAND) {
                        st = dfi_sand_damage(r); /* eachEvent('Weather'): Sandstorm's onWeather */
                        if (st != DUOFORGE_OK) {
                            return st;
                        }
                    } else if (b->weather == DFI_WEATHER_RAIN) {
                        st = dfi_weather_heal(r, DFI_ABILITY_RAINDISH); /* eachEvent('Weather'): Rain Dish's onWeather */
                        if (st != DUOFORGE_OK) {
                            return st;
                        }
                    } else if (b->weather == DFI_WEATHER_SNOW) {
                        /* Snowscape's onFieldResidual runs eachEvent('Weather') while snow is up (data/conditions.ts:721-724):
                         * Ice Body's onWeather (A2a) */
                        st = dfi_weather_heal(r, DFI_ABILITY_ICEBODY);
                        if (st != DUOFORGE_OK) {
                            return st;
                        }
                    } else if (b->weather == DFI_WEATHER_SUN) {
                        st = dfi_solar_power(r); /* eachEvent('Weather'): Solar Power's onWeather (step G39) */
                        if (st != DUOFORGE_OK) {
                            return st;
                        }
                    }
                }
                if (!suppressed || b->weather == DFI_WEATHER_RAIN || b->weather == DFI_WEATHER_SUN) {
                    st = dfi_update(r); /* the upkeep: eachEvent('Weather') ends with 'Update' */
                    if (st != DUOFORGE_OK) {
                        return st;
                    }
                }
                dfi_process_faints(r); /* fieldEvent: faintMessages after each handler (sim/battle.ts:569-570) */
                if (r->ended) {
                    return dfi_residual_stop(stop);
                }
            }
            continue;
        }
        dfi_member *m = dfi_at(b, e->flat);
        if (m->hp == 0u) {
            continue; /* the holder fainted */
        }
        if (e->kind == DFI_RES_PARTIAL_TRAP) {
            /* The partial trap (step G90, decision 0060; data/conditions.ts:222-258). The turns go down first, and at 0 the end
             * line shows with no damage that turn (sim/battle.ts:516-523). Otherwise a source that is gone (its position emptied
             * or refilled: the tail's source is then 0, or its holder fainted) ends the trap silently, and the holder takes
             * floor(maxhp / 6 with Binding Band, else 8), at least 1 (Battle.damage clamps). */
            dfi_tail_pos *tail = &b->tail.sides[e->flat / 2u].positions[e->flat % 2u];
            if (tail->trap_turns == 0u) {
                continue; /* removed by an earlier handler */
            }
            tail->trap_turns = (uint8_t)((uint32_t)tail->trap_turns - 1u); /* wide-operands-reviewed: >= 1 */
            const uint32_t move_id = (uint32_t)tail->trap_move - 1u;
            if (tail->trap_turns == 0u) {
                duoforge_event end = dfi_event_make(DUOFORGE_EVENT_VOLATILE_END, e->flat);
                end.detail = (uint8_t)DUOFORGE_VOLATILE_PARTIAL_TRAP;
                end.id = (uint16_t)move_id;
                dfi_trap_clear(tail);
                dfi_emit(r, &end);
                continue;
            }
            /* One more residual phase has run with the trap up (decision 0060, hidden counters): the public counter. It stays
             * below 6 while the trap is up (d <= 6), so the 3-bit field never saturates in a legal state. */
            if (tail->trap_elapsed < 7u) {
                tail->trap_elapsed = (uint8_t)(tail->trap_elapsed + 1u); /* wide-operands-reviewed: < 7 */
            }
            const dfi_member *src = tail->trap_source == 0u ? NULL : dfi_member_at(b, (uint32_t)tail->trap_source - 1u);
            if (src == NULL || src->hp == 0u) {
                dfi_trap_clear(tail); /* silent: the source is not on the field any more */
                continue;
            }
            const uint32_t divisor = tail->trap_band != 0u ? 6u : 8u;
            uint32_t amount = (uint32_t)m->hp_max / divisor;
            if (amount == 0u) {
                amount = 1u;
            }
            st = dfi_deal(r, e->flat, amount, DUOFORGE_CAUSE_MOVE, move_id, DUOFORGE_NO_POSITION, DFI_DMG_CONDITION);
            if (st != DUOFORGE_OK) {
                return st;
            }
            dfi_process_faints(r);
            if (r->ended) {
                return dfi_residual_stop(stop);
            }
            continue;
        }
        if (e->kind == DFI_RES_PERISH) {
            /* fieldEvent (sim/battle.ts:484-575): the duration goes down; at 0 onEnd shows -start|X|perish0 and
             * faints the holder (target.faint(): queued, hp 0) and the loop goes on with no faintMessages; otherwise
             * onResidual shows the count (-start|X|perishN) and the faintMessages that follows every callback
             * processes the faints that earlier handlers queued (and may end the battle). */
            dfi_tail_pos *tail = &b->tail.sides[e->flat / 2u].positions[e->flat % 2u];
            if (tail->perish == 0u) {
                continue; /* removed by an earlier handler */
            }
            tail->perish = (uint8_t)((uint32_t)tail->perish - 1u); /* wide-operands-reviewed: >= 1 */
            duoforge_event ev = dfi_event_make(DUOFORGE_EVENT_VOLATILE_START, e->flat);
            ev.detail = (uint8_t)DUOFORGE_VOLATILE_PERISH;
            ev.amount = tail->perish; /* 0 to 3 */
            dfi_emit(r, &ev);
            if (tail->perish == 0u) {
                m->hp = 0u;
                if (dfi_support.switching == 0u) {
                    return DUOFORGE_E_UNSUPPORTED;
                }
                if (r->faint_count < DFI_POSITIONS) {
                    r->faint_queue[r->faint_count] = e->flat;
                    r->last_faint_by = DFI_POSITIONS;
                    r->last_faint_move = false;
                    r->faint_count += 1u;
                }
                continue;
            }
            dfi_process_faints(r);
            if (r->ended) {
                return dfi_residual_stop(stop);
            }
            continue;
        }
        if (e->kind == DFI_RES_ENCORE) {
            /* fieldEvent: the duration goes down and at 0 the volatile ends (-end|X|Encore, onEnd); otherwise the
             * callback ends it early when the Encored move has no PP left (data/moves.ts:4724-4783). */
            dfi_tail_pos *tail = &b->tail.sides[e->flat / 2u].positions[e->flat % 2u];
            if (tail->encore_slot == 0u) {
                continue; /* removed by an earlier handler */
            }
            tail->encore_turns = (uint8_t)((uint32_t)tail->encore_turns - 1u); /* wide-operands-reviewed: >= 1 */
            if (tail->encore_turns == 0u || m->moves[(uint32_t)tail->encore_slot - 1u].pp == 0u) {
                tail->encore_slot = 0u;
                tail->encore_turns = 0u;
                duoforge_event end = dfi_event_make(DUOFORGE_EVENT_VOLATILE_END, e->flat);
                end.detail = (uint8_t)DUOFORGE_VOLATILE_ENCORE;
                dfi_emit(r, &end);
            }
            continue;
        }
        if (e->kind == DFI_RES_TAUNT) {
            /* fieldEvent: the duration goes down and at 0 the volatile ends (-end|X|move: Taunt, onEnd; order 15,
             * data/moves.ts:18992-18995). */
            dfi_tail_pos *tail = &b->tail.sides[e->flat / 2u].positions[e->flat % 2u];
            if (tail->taunt_turns == 0u) {
                continue; /* removed by an earlier handler */
            }
            tail->taunt_turns = (uint8_t)((uint32_t)tail->taunt_turns - 1u); /* wide-operands-reviewed: >= 1 */
            if (tail->taunt_turns == 0u) {
                duoforge_event end = dfi_event_make(DUOFORGE_EVENT_VOLATILE_END, e->flat);
                end.detail = (uint8_t)DUOFORGE_VOLATILE_TAUNT;
                dfi_emit(r, &end);
            }
            continue;
        }
        if (e->kind == DFI_RES_HEAL_BLOCK) {
            /* the duration goes down and at 0 the volatile ends (-end|X|move: Heal Block, onEnd; order 20) */
            dfi_tail_pos *tail = &b->tail.sides[e->flat / 2u].positions[e->flat % 2u];
            if (tail->heal_block_turns == 0u) {
                continue; /* removed by an earlier handler */
            }
            tail->heal_block_turns = (uint8_t)((uint32_t)tail->heal_block_turns - 1u); /* wide-operands-reviewed: >= 1 */
            if (tail->heal_block_turns == 0u) {
                duoforge_event end = dfi_event_make(DUOFORGE_EVENT_VOLATILE_END, e->flat);
                end.detail = (uint8_t)DUOFORGE_VOLATILE_HEAL_BLOCK;
                dfi_emit(r, &end);
            }
            continue;
        }
        if (e->kind == DFI_RES_DISABLE) {
            /* the duration goes down and at 0 the volatile ends (-end|X|Disable, onEnd; order 17) */
            dfi_tail_pos *tail = &b->tail.sides[e->flat / 2u].positions[e->flat % 2u];
            if (tail->disable_slot == 0u) {
                continue; /* removed by an earlier handler */
            }
            tail->disable_turns = (uint8_t)((uint32_t)tail->disable_turns - 1u); /* wide-operands-reviewed: >= 1 */
            if (tail->disable_turns == 0u) {
                tail->disable_slot = 0u;
                duoforge_event end = dfi_event_make(DUOFORGE_EVENT_VOLATILE_END, e->flat);
                end.detail = (uint8_t)DUOFORGE_VOLATILE_DISABLE;
                dfi_emit(r, &end);
            }
            continue;
        }
        if (e->kind == DFI_RES_YAWN) {
            /* the duration goes down; at 0 the end line is silent and the holder falls asleep: trySetStatus('slp',
             * source) with the holder as its own source for Flower Veil, whose onAllySetStatus skips yawn (the
             * sleep draws its turns; a holder with a status by now, or a fainted one, takes none) */
            dfi_tail_pos *tail = &b->tail.sides[e->flat / 2u].positions[e->flat % 2u];
            if (tail->yawn_turns == 0u) {
                continue; /* removed by an earlier handler */
            }
            tail->yawn_turns = (uint8_t)((uint32_t)tail->yawn_turns - 1u); /* wide-operands-reviewed: >= 1 */
            if (tail->yawn_turns == 0u) {
                st = dfi_try_status(r, e->flat, DFI_STATUS_SLP, e->flat, DFI_NO_SOURCE_MOVE, DFI_ORIGIN_YAWN, 0u);
                if (st != DUOFORGE_OK) {
                    return st;
                }
            }
            continue;
        }
        if (e->kind == DFI_RES_LOCK) {
            continue; /* a lockedmove has no order: its countdown runs in the order-less stage (dfi_residual_lock) */
        }
        if (e->kind == DFI_RES_DURATION) {
            if (e->order == 25u) { /* Roost's end (step G42): silent, the Flying type is back for the rest of the residual */
                uint8_t *single = &r->b->tail.sides[e->flat / 2u].positions[e->flat % 2u].single_turn;
                *single = (uint8_t)((uint32_t)*single & ~(uint32_t)DFI_SINGLE_TURN_ROOST); /* wide-operands-reviewed: MSVC C4310 */
            }
            continue; /* Throat Chop's (order 22): silent, its count goes down below */
        }
        if (e->kind == DFI_RES_LEFTOVERS) {
            dfi_heal(r, e->flat, (uint32_t)m->hp_max / 16u, DUOFORGE_CAUSE_ITEM, 1u + DFI_ITEM_LEFTOVERS,
                     DUOFORGE_NO_POSITION); /* heal(baseMaxhp / 16) */
            continue;
        }
        if (e->kind == DFI_RES_GRASSY) {
            /* heal(baseMaxhp / 16): at least 1, not above the maximum, not
             * for a Pokemon that is not grounded or at full HP. */
            /* A semi-invulnerable Pokemon takes no heal (data/moves.ts:7714). At this entry the charge turn's count is still 2
             * (the decrement below comes after the entries), and the locked turn's volatile is gone: see dfi_semi_invulnerable. */
            if (dfi_grounded(b, m) && m->hp < m->hp_max && !dfi_heal_blocked(b, e->flat) &&
                !dfi_semi_invulnerable(r, e->flat)) {
                uint32_t heal = (uint32_t)m->hp_max / 16u;
                heal = heal == 0u ? 1u : heal;
                const uint32_t hp = (uint32_t)m->hp + heal;
                m->hp = (uint16_t)(hp > m->hp_max ? m->hp_max : hp); /* wide-operands-reviewed: <= hp_max */
                dfi_emit_hp(r, dfi_ev(DUOFORGE_EVENT_HEAL, e->flat, DUOFORGE_CAUSE_TERRAIN, 0u, DUOFORGE_NO_POSITION));
            }
            continue;
        }
        if (e->kind == DFI_RES_LEECH) {
            st = dfi_leech_drain(r, e->flat);
            if (st != DUOFORGE_OK) {
                return st;
            }
            dfi_process_faints(r);
            if (r->ended) {
                return dfi_residual_stop(stop);
            }
            continue;
        }
        if (e->kind == DFI_RES_CURSE) {
            st = dfi_curse_residual(r, e->flat);
            if (st != DUOFORGE_OK) {
                return st;
            }
            dfi_process_faints(r);
            if (r->ended) {
                return dfi_residual_stop(stop);
            }
            continue;
        }
        /* burn: baseMaxhp / 16; poison: baseMaxhp / 8 (data/conditions.ts:
         * 123-137); at least 1. Any other callback here is a missing case. */
        if (e->kind != DFI_RES_BURN && e->kind != DFI_RES_POISON) {
            return DUOFORGE_E_INVARIANT;
        }
        const bool poison = e->kind == DFI_RES_POISON;
        uint32_t damage = (uint32_t)m->hp_max / (poison ? 8u : 16u);
        damage = damage == 0u ? 1u : damage;
        if (poison && m->status == DFI_STATUS_TOX) {
            /* tox (data/conditions.ts:138-161): the stage goes up first (to 15 at most), then the damage is
             * clampIntRange(baseMaxhp / 16, 1) * stage; the stage is the tail's, zero at the status's start and after a
             * switch-in (onSwitchIn). */
            uint8_t *stage = &b->tail.sides[e->flat / 2u].toxic_stage[dfi_pos(b, e->flat)->occupant];
            if (*stage < DFI_TAIL_TOXIC_STAGE_MAX) {
                *stage = (uint8_t)((uint32_t)*stage + 1u); /* wide-operands-reviewed: < 15 */
            }
            damage = (uint32_t)m->hp_max / 16u;
            damage = (damage == 0u ? 1u : damage) * (uint32_t)*stage; /* wide-operands-reviewed: <= 15 * hp_max */
        }
        st = dfi_deal(r, e->flat, damage, poison ? DUOFORGE_CAUSE_POISON : DUOFORGE_CAUSE_BURN, 0u,
                      DUOFORGE_NO_POSITION, DFI_DMG_STATUS);
        if (st != DUOFORGE_OK) {
            return st;
        }
        dfi_process_faints(r);
        if (r->ended) {
            return dfi_residual_stop(stop);
        }
    }
    return DUOFORGE_OK;
}

/* Phase 4: the counts that go down silently, then the duration handlers of the side conditions, Trick Room, Gravity
 * and the terrain. */
static DFI_ALWAYS_INLINE duoforge_status dfi_residual_durations(dfi_run *r, struct duoforge_battle *b,
                                                               const uint32_t first[DFI_SIDE_KINDS], bool *stop)
{
    duoforge_status st = DUOFORGE_OK;
    /* Throat Chop's count (order 22) goes down here: its end is silent, so nothing shows where it comes. Heal Block, Yawn
     * and Taunt end in the sorted list above, at their own orders. */
    {
        for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
            dfi_tail_pos *tail = &b->tail.sides[flat / 2u].positions[flat % 2u];
            if (tail->throat_chop_turns != 0u) {
                tail->throat_chop_turns = (uint8_t)((uint32_t)tail->throat_chop_turns - 1u); /* wide-operands-reviewed */
            }
        }
        /* Wide Guard's side condition has duration 1 and no end line: it is gone after this residual. Quick Guard (step G54)
         * has duration 1 as well, and no end line. */
        for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
            b->tail.sides[s].wide_guard = 0u;
            b->tail.sides[s].quick_guard = 0u;
        }
    }
    /* The duration handlers in their order: the side conditions (26), Trick
     * Room (27, sub-order 1), the terrain (27, 7); each that runs out shows
     * its end line (and the terrain's end runs TerrainChange). Protect,
     * flinch and the stall counter end without a line. */
    static const uint8_t side_kind[DFI_SIDE_KINDS] = {DUOFORGE_SIDE_REFLECT, DUOFORGE_SIDE_LIGHT_SCREEN,
                                                      DUOFORGE_SIDE_TAILWIND, DUOFORGE_SIDE_AURORA_VEIL};
    for (uint32_t k = 0u; k < DFI_SIDE_KINDS; ++k) {
        {
            /* The same kind on both sides, one of them ending now and the other not, with a faint still queued: the
             * faints are shown after the one that does not end, so before or after the other's end line by the tie's
             * shuffle, a draw that the conversion drops (the two only count down). Not modelled: refused. */
            const uint8_t t0 = *dfi_side_turns(b, 0u, k);
            const uint8_t t1 = *dfi_side_turns(b, 1u, k);
            if (r->faint_count != 0u && t0 != 0u && t1 != 0u && (t0 == 1u) != (t1 == 1u)) {
                return DUOFORGE_E_UNSUPPORTED;
            }
        }
        for (uint32_t j = 0u; j < DUOFORGE_SIDE_COUNT; ++j) {
            const uint32_t s = j ^ first[k];
            uint8_t *turns = dfi_side_turns(b, s, k);
            if (*turns == 0u) {
                continue;
            }
            *turns = (uint8_t)((uint32_t)*turns - 1u); /* wide-operands-reviewed: >= 1 */
            if (*turns == 0u) {
                duoforge_event e = dfi_event_make(DUOFORGE_EVENT_SIDE_END, DUOFORGE_NO_POSITION);
                e.detail = (uint8_t)s;
                e.amount = side_kind[k];
                dfi_emit(r, &e); /* [-sideend] */
            } else {
                dfi_residual_faints(r);
                if (r->ended) {
                    /* The battle ended at this handler, so the other side's handler of the same kind did not run: which
                     * of the two ran first is the shuffle of the tie, a draw that the conversion drops when both only
                     * count down, and the remaining turns of an ended battle show it. Not modelled: refused. */
                    if (j == 0u && *dfi_side_turns(b, s ^ 1u, k) != 0u) {
                        return DUOFORGE_E_UNSUPPORTED;
                    }
                    return dfi_residual_stop(stop);
                }
            }
        }
    }
    if (b->trick_room_turns != 0u) {
        b->trick_room_turns = (uint8_t)((uint32_t)b->trick_room_turns - 1u); /* wide-operands-reviewed: >= 1 */
        if (b->trick_room_turns == 0u) {
            duoforge_event e = dfi_event_make(DUOFORGE_EVENT_FIELD_END, DUOFORGE_NO_POSITION);
            e.detail = (uint8_t)DUOFORGE_FIELD_TRICK_ROOM;
            dfi_emit(r, &e); /* [-fieldend] */
        } else {
            dfi_residual_faints(r);
            if (r->ended) {
                return dfi_residual_stop(stop);
            }
        }
    }
    /* Step K4 (#475, data/moves.ts:7832-7833, Gravity's onFieldResidualOrder 27 and SubOrder 2): after Trick Room (27.1), before
     * the terrains (27.7). Its end is `-fieldend|move: Gravity` with no [of] (:7834-7836). */
    if (b->tail.gravity_turns != 0u) {
        b->tail.gravity_turns = (uint8_t)((uint32_t)b->tail.gravity_turns - 1u); /* wide-operands-reviewed: >= 1 */
        if (b->tail.gravity_turns == 0u) {
            duoforge_event e = dfi_event_make(DUOFORGE_EVENT_FIELD_END, DUOFORGE_NO_POSITION);
            e.detail = (uint8_t)DUOFORGE_FIELD_GRAVITY;
            dfi_emit(r, &e); /* [-fieldend] */
        } else {
            dfi_residual_faints(r);
            if (r->ended) {
                return dfi_residual_stop(stop);
            }
        }
    }
    if (b->terrain != DFI_TERRAIN_NONE) {
        b->terrain_turns = (uint8_t)((uint32_t)b->terrain_turns - 1u); /* wide-operands-reviewed: >= 1 */
        if (b->terrain_turns == 0u) {
            const uint32_t ended = b->terrain;
            b->terrain = (uint8_t)DFI_TERRAIN_NONE;
            duoforge_event e = dfi_event_make(DUOFORGE_EVENT_FIELD_END, DUOFORGE_NO_POSITION);
            e.detail = (uint8_t)dfi_terrain_field_detail(ended);
            dfi_emit(r, &e); /* [-fieldend] */
            st = dfi_terrain_change(r);
            if (st != DUOFORGE_OK) {
                return st;
            }
        } else {
            dfi_residual_faints(r);
            if (r->ended) {
                return dfi_residual_stop(stop);
            }
        }
    }
    return DUOFORGE_OK;
}

/* Phase 5: Speed Boost and Moody (order 28), then White Herb (29). */
static DFI_ALWAYS_INLINE duoforge_status dfi_residual_late(dfi_run *r, struct duoforge_battle *b, const dfi_residual_entry *list,
                                                          uint32_t herbs_from, uint32_t sorted, bool *stop)
{
    /* White Herb's onResidual (order 29), each holder's check. The engine
     * keeps the side conditions without their kinds, so the start order of
     * the shuffle above can differ from the reference's: two holders due in
     * one group of equal speed are E_UNSUPPORTED. Moody (order 28, step G73)
     * runs before the herbs and may lower a stat, so the due check is made
     * when the first herb is reached: every order-28 handler has run by then
     * (the sort puts 28 before 29). */
    bool herb_checked = false;
    for (uint32_t i = herbs_from; i < sorted; ++i) {
        if (list[i].kind == DFI_RES_WHITE_HERB && !herb_checked) {
            herb_checked = true;
            for (uint32_t a = i; a < sorted; ++a) {
                if (list[a].kind != DFI_RES_WHITE_HERB || !dfi_herb_due(b, list[a].flat)) {
                    continue;
                }
                for (uint32_t j = a + 1u; j < sorted; ++j) {
                    if (list[j].kind == DFI_RES_WHITE_HERB && list[j].speed == list[a].speed && dfi_herb_due(b, list[j].flat)) {
                        return DUOFORGE_E_UNSUPPORTED;
                    }
                }
            }
        }
        if ((list[i].kind == DFI_RES_SPEED_BOOST || list[i].kind == DFI_RES_MOODY || list[i].kind == DFI_RES_WHITE_HERB) &&
            dfi_residual_holder_stands(r, list[i].flat)) {
            if (list[i].kind == DFI_RES_SPEED_BOOST) {
                dfi_speed_boost(r, list[i].flat);
            } else if (list[i].kind == DFI_RES_MOODY) {
                const duoforge_status mst = dfi_moody(r, list[i].flat);
                if (mst != DUOFORGE_OK) {
                    return mst;
                }
            } else {
                dfi_white_herb(r, list[i].flat, dfi_use_item);
            }
            dfi_residual_faints(r); /* a callback: faintMessages follows it */
            if (r->ended) {
                return dfi_residual_stop(stop);
            }
        }
    }
    return DUOFORGE_OK;
}

/* Phase 6, the last: the duration handlers of the volatiles that have no order, in Speed order. The handlers of one
 * position, everything except its lockedmove: Protect, flinch, Helping Hand and Follow Me (duration 1) end at once, the
 * stall counter and a charge (2) end on their second residual, mustrecharge (2) lasts through the one of the turn that set
 * it, Ally Switch's volatile counts down. `keeps`: one of them does not end (a faint point follows it); `also_ends`: one
 * ends. With `pair_here` Protect's volatile is left for dfi_residual_pair_draws. */
static DFI_ALWAYS_INLINE void dfi_noorder_counters(struct duoforge_battle *b, uint32_t flat, bool pair_here, bool *keeps_out,
                                                   bool *also_ends_out)
{
    const uint32_t ended_flags = DFI_VOL_PROTECT | DFI_VOL_FLINCH | DFI_VOL_HELPING_HAND | DFI_VOL_FOLLOW_ME;
    dfi_active_slot *pos = dfi_pos(b, flat);
    *keeps_out = (pos->stall_level != 0u && pos->stall_turns > 1u) || pos->charge_turns > 1u ||
                 b->tail.sides[flat / 2u].positions[flat % 2u].must_recharge != 0u;
    *also_ends_out = ((uint32_t)pos->flags & ended_flags) != 0u || pos->charge_turns == 1u || pos->stall_turns == 1u;
    if (!pair_here) {
        pos->flags = (uint8_t)((uint32_t)pos->flags & ~ended_flags); /* wide-operands-reviewed */
    }
    /* The variant ends with the volatile. protect and spikyshield have `duration: 1` and no onResidual, onEnd or order
     * (data/moves.ts:13961-14005, :17532-17584), so each is one of the position's duration handlers of the sorted
     * Residual list above (sim/battle.ts:1097-1112 adds a volatile with a duration, :516-517 counts it down and
     * removes it, silently without an onEnd): the count `ends` has it through DFI_VOL_PROTECT whichever variant it is.
     * Nothing between its place in the sort and this sweep can read it (no hit is made in a residual), so clearing
     * it with the flag is the same outcome. */
    if (!pair_here) {
        b->tail.sides[flat / 2u].positions[flat % 2u].protect_kind = (uint8_t)DFI_PROTECT_PLAIN;
    }
    if (pos->charge_turns > 0u) {
        pos->charge_turns = (uint8_t)((uint32_t)pos->charge_turns - 1u); /* wide-operands-reviewed */
        if (pos->charge_turns == 0u) {
            pos->locked_target = 0u;
            if (((uint32_t)pos->flags & DFI_VOL_CHOICE_LOCK) == 0u) {
                pos->locked_move = 0u; /* a choice lock outlives the charge */
            }
        }
    }
    if (pos->stall_turns > 0u) {
        pos->stall_turns = (uint8_t)((uint32_t)pos->stall_turns - 1u); /* wide-operands-reviewed */
        if (pos->stall_turns == 0u) {
            pos->stall_level = 0u;
        }
    }
    /* Ally Switch's volatile (step G80, decision 0044): its duration counts down here, silently; at 0 it is gone and the
     * counter with it. The turns are the low two bits of ally_switch. */
    dfi_tail_pos *atp = &b->tail.sides[flat / 2u].positions[flat % 2u];
    if (atp->ally_switch != 0u) {
        if (((uint32_t)atp->ally_switch & 3u) == 1u) {
            atp->ally_switch = 0u;
        } else {
            atp->ally_switch = (uint8_t)((uint32_t)atp->ally_switch - 1u); /* wide-operands-reviewed: turns 2 -> 1 */
        }
    }
}

/* The lockedmove of a position (step G56): an order-less callback. A marked lock ends in its duration phase (no faint point:
 * sim/battle.ts:515-522 `continue`s); any other lock's onResidual runs and the faintMessages after it is a faint point
 * (sim/battle.ts:565-566), as a counter that keeps (issue 606, decision 0015 5dv). `*lock_here`: the position has a lock that
 * ran; `*lock_point`: a faint point follows it. A holder whose faint is queued and not yet shown (a Perish Song end of this
 * residual) still has its handler: fieldEvent skips only a fainted holder (sim/battle.ts:514-517), so its lock's faint point
 * is there too; its end confuses nobody (addVolatile refuses a Pokemon at 0 HP, sim/pokemon.ts:1975) and the faint clears
 * the lock, so only the faint point is run for it (issue 633; the fuzz run 6631 found it as a divergence of the faint lines
 * against the upkeep on main). */
static DFI_ALWAYS_INLINE duoforge_status dfi_noorder_lock(dfi_run *r, struct duoforge_battle *b, uint32_t flat, bool *lock_here,
                                                          bool *lock_point)
{
    const dfi_tail_pos *ltp = &b->tail.sides[flat / 2u].positions[flat % 2u];
    *lock_here = dfi_residual_holder_stands(r, flat) && ltp->lock_turns != 0u;
    *lock_point = *lock_here && ((uint32_t)ltp->single_turn & DFI_SINGLE_TURN_LOCK_UNUSED) == 0u;
    return *lock_here && dfi_alive(b, flat) ? dfi_residual_lock(r, flat) : DUOFORGE_OK;
}

/* A drawn no-order group (issues 630 and 633): the entries list[at, end) of one Speed, two callbacks or more, in the order
 * that the third sort pass of phase 2 left (the reference's for the draws of the tape, dfi_residual_order_ambiguous having
 * cleared the order of each Pokemon's volatiles). Each lockedmove runs at its own entry; a position's other no-order
 * handlers run at its first entry among them (the engine does not tell its counters apart: they print nothing, and where
 * they stand shows only through a faint point, refused below where it would). A faint point that ends the battle leaves
 * the entries after it unrun, as fieldEvent does (sim/battle.ts:565-566); the outcome is then the reference's only when
 * every Pokemon that still stands has either run all of its counters or none of them, and has not both a lock and counters
 * (their pre-sort order, which the state does not hold, would decide which of them ran): anything else is refused. */
static DFI_ALWAYS_INLINE duoforge_status dfi_noorder_drawn(dfi_run *r, struct duoforge_battle *b, const dfi_residual_entry *list,
                                                           uint32_t at, uint32_t end, bool *stop)
{
    uint32_t counters[DFI_POSITIONS] = {0u, 0u, 0u, 0u}; /* the position's counter entries in the group */
    uint32_t ran[DFI_POSITIONS] = {0u, 0u, 0u, 0u};      /* ... of which those up to the current entry (the pin's) */
    bool locks[DFI_POSITIONS] = {false, false, false, false};
    for (uint32_t i = at; i < end; ++i) {
        if (list[i].kind == DFI_RES_LOCK) {
            locks[list[i].flat] = true;
        } else {
            counters[list[i].flat] += 1u;
        }
    }
    for (uint32_t i = at; i < end; ++i) {
        const uint32_t flat = list[i].flat;
        bool point = false;
        if (list[i].kind == DFI_RES_LOCK) {
            bool lock_here = false;
            const duoforge_status st = dfi_noorder_lock(r, b, flat, &lock_here, &point);
            if (st != DUOFORGE_OK) {
                return st;
            }
        } else {
            ran[flat] += 1u;
            if (ran[flat] != 1u) {
                continue; /* run with the position's first counter entry */
            }
            bool also_ends = false;
            dfi_noorder_counters(b, flat, false, &point, &also_ends);
            if (point && counters[flat] > 1u && r->faint_count != 0u) {
                return DUOFORGE_E_UNSUPPORTED; /* which of its counters keeps, and so where its faint point is, is not known */
            }
        }
        if (point && r->faint_count != 0u) {
            dfi_residual_faints(r);
            if (r->ended) {
                for (uint32_t p = 0u; p < DFI_POSITIONS; ++p) {
                    if (counters[p] != 0u && dfi_alive(b, p) && (locks[p] || (ran[p] != 0u && ran[p] != counters[p]))) {
                        return DUOFORGE_E_UNSUPPORTED;
                    }
                }
                return dfi_residual_stop(stop);
            }
        }
    }
    return DUOFORGE_OK;
}

static DFI_ALWAYS_INLINE duoforge_status dfi_residual_noorder(dfi_run *r, struct duoforge_battle *b, const dfi_residual_entry *list,
                                                             uint32_t from, uint32_t n, dfi_noorder_snapshot *ps)
{
    /* The duration handlers of the volatiles that have no order come last, in Speed order (comparePriority puts no order
     * after every order). Any that does not end is followed by faintMessages, and a battle that ends there leaves the
     * handlers after it unrun: the ones before it ended, the ones after it keep their counters. A group of one Speed with
     * two callbacks or more was drawn in phase 2 and runs in its drawn order (dfi_noorder_drawn). In any other group the
     * order of its handlers is a shuffle that the conversion drops; it shows only in the counters of a Pokemon that stands
     * when the battle ends at a faint point of the group (a fainted one has lost its volatiles), and that case is refused,
     * except the lone Protect / stall pair (dfi_residual_pair_draws). */
    const uint32_t ended_flags = DFI_VOL_PROTECT | DFI_VOL_FLINCH | DFI_VOL_HELPING_HAND | DFI_VOL_FOLLOW_ME;
    while (from < n && list[from].order != DFI_RES_NO_ORDER) {
        from += 1u;
    }
    uint32_t seq[DFI_POSITIONS];
    bool had[DFI_POSITIONS] = {false}; /* by position: a handler of this kind exists now (before any of them runs) */
    uint32_t seq_n = 0u;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        const dfi_active_slot *pos = dfi_pos(b, flat);
        if (pos->occupant != DFI_OCCUPANT_NONE) {
            seq[seq_n] = flat;
            seq_n += 1u;
            /* A lockedmove (issue 606, decision 0015 5dv) is one of these handlers too: its end (a marked lock: the fatigue line
             * and its draw), its onResidual (a sleeping holder's delete) and the faint point after that onResidual all depend on
             * whether it ran before a battle-ending faint point of an equal-Speed Pokemon. */
            had[flat] = ((uint32_t)pos->flags & ended_flags) != 0u || pos->charge_turns != 0u || pos->stall_turns != 0u ||
                        b->tail.sides[flat / 2u].positions[flat % 2u].must_recharge != 0u ||
                        b->tail.sides[flat / 2u].positions[flat % 2u].lock_turns != 0u;
        }
    }
    for (uint32_t i = 1u; i < seq_n; ++i) {
        for (uint32_t j = i; j > 0u && r->speed_seen[seq[j]] > r->speed_seen[seq[j - 1u]]; --j) {
            const uint32_t swap = seq[j];
            seq[j] = seq[j - 1u];
            seq[j - 1u] = swap;
        }
    }
    bool done[DFI_POSITIONS] = {false}; /* run as a member of a drawn group */
    for (uint32_t i = 0u; i < seq_n; ++i) {
        const uint32_t flat = seq[i];
        if (done[flat]) {
            continue;
        }
        /* The drawn group of this position's no-order entries, if they are one: list[at, end), two callbacks or more. */
        uint32_t at = from;
        while (at < n && list[at].flat != flat) {
            at += 1u;
        }
        if (at < n) {
            uint32_t start = at;
            while (start > from && dfi_residual_compare(&list[start - 1u], &list[at]) == 1u) {
                start -= 1u;
            }
            uint32_t end = at;
            while (end < n && dfi_residual_compare(&list[end], &list[at]) == 1u) {
                end += 1u;
            }
            uint32_t calls = 0u;
            for (uint32_t k = start; k < end; ++k) {
                calls += list[k].callback ? 1u : 0u;
            }
            if (calls >= 2u) {
                for (uint32_t k = start; k < end; ++k) {
                    done[list[k].flat] = true;
                }
                bool stop = false;
                const duoforge_status st = dfi_noorder_drawn(r, b, list, start, end, &stop);
                if (st != DUOFORGE_OK || stop) {
                    return st;
                }
                continue;
            }
        }
        const bool pair_here = ps->pair[flat]; /* Protect's volatile and the stall counter, nothing else: see below */
        bool keeps = false;
        bool also_ends = false;
        dfi_noorder_counters(b, flat, pair_here, &keeps, &also_ends);
        /* lockedmove (step G56): an order-less callback in this Speed order, after the counters it shares a sub-order with. */
        bool lock_here = false;
        bool lock_point = false;
        const duoforge_status st = dfi_noorder_lock(r, b, flat, &lock_here, &lock_point);
        if (st != DUOFORGE_OK) {
            return st;
        }
        if ((keeps || lock_point) && r->faint_count != 0u) {
            dfi_residual_faints(r);
            if (r->ended) {
                if (also_ends && !pair_here && dfi_alive(b, flat)) {
                    return DUOFORGE_E_UNSUPPORTED; /* its own other handler: before or after the faint point */
                }
                if (lock_here && keeps && dfi_alive(b, flat)) {
                    return DUOFORGE_E_UNSUPPORTED; /* its lock's handler and a counter that keeps: which faint point came first */
                }
                for (uint32_t j = 0u; j < seq_n; ++j) {
                    if (j != i && had[seq[j]] && dfi_alive(b, seq[j]) && r->speed_seen[seq[j]] == r->speed_seen[flat]) {
                        return DUOFORGE_E_UNSUPPORTED; /* equal Speed, an undrawn group: the shuffle decides who ran */
                    }
                }
                if (pair_here) {
                    ps->ended_at = flat; /* Protect's volatile is still there: dfi_residual_pair_draws decides */
                }
                return DUOFORGE_OK;
            }
        }
        if (pair_here) {
            dfi_pos(b, flat)->flags = (uint8_t)((uint32_t)dfi_pos(b, flat)->flags & ~ended_flags); /* wide-operands-reviewed */
            b->tail.sides[flat / 2u].positions[flat % 2u].protect_kind = (uint8_t)DFI_PROTECT_PLAIN;
        }
    }
    return DUOFORGE_OK;
}

static duoforge_status dfi_residual_events_run(dfi_run *r, dfi_noorder_snapshot *ps)
{
    struct duoforge_battle *b = r->b;
    duoforge_status st = dfi_update_speeds(r);
    if (st != DUOFORGE_OK) {
        return st;
    }
    {
        const uint32_t protect_and_friends = DFI_VOL_PROTECT | DFI_VOL_FLINCH | DFI_VOL_HELPING_HAND | DFI_VOL_FOLLOW_ME;
        ps->ended_at = DFI_POSITIONS;
        ps->drawn_slowest = UINT32_MAX;
        for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
            const dfi_active_slot *pos = dfi_pos(b, flat);
            const bool recharge = b->tail.sides[flat / 2u].positions[flat % 2u].must_recharge != 0u;
            ps->key[flat] = r->speed_seen[flat];
            ps->had[flat] = pos->occupant != DFI_OCCUPANT_NONE &&
                            (((uint32_t)pos->flags & protect_and_friends) != 0u || pos->charge_turns != 0u ||
                             pos->stall_turns != 0u || recharge ||
                             b->tail.sides[flat / 2u].positions[flat % 2u].lock_turns != 0u);
            ps->pair[flat] = pos->occupant != DFI_OCCUPANT_NONE && dfi_alive(b, flat) &&
                             ((uint32_t)pos->flags & protect_and_friends) == DFI_VOL_PROTECT && pos->stall_level != 0u &&
                             pos->stall_turns != 0u && pos->charge_turns == 0u && !recharge;
        }
    }
    dfi_residual_entry list[DFI_RES_MAX];
    uint32_t n = 0u;
    st = dfi_residual_collect(r, b, list, &n);
    if (st != DUOFORGE_OK) {
        return st;
    }
    uint32_t first[DFI_SIDE_KINDS] = {0u, 0u, 0u, 0u};
    uint32_t early = 0u;
    uint32_t sorted = 0u;
    uint32_t herbs_from = 0u;
    st = dfi_residual_order(r, b, list, n, first, &early, &sorted, &herbs_from);
    if (st != DUOFORGE_OK) {
        return st;
    }
    /* The slowest drawn no-order group: a lone Protect / stall pair of a faster Pokemon draws before it in the reference. */
    for (uint32_t i = sorted; i < n; ++i) {
        if (list[i].order != DFI_RES_NO_ORDER || !list[i].callback) {
            continue;
        }
        uint32_t calls = 0u;
        for (uint32_t j = sorted; j < n; ++j) {
            calls += (dfi_residual_compare(&list[i], &list[j]) == 1u && list[j].callback) ? 1u : 0u;
        }
        if (calls >= 2u && list[i].speed < ps->drawn_slowest) {
            ps->drawn_slowest = list[i].speed;
        }
    }
    ps->draws_after_order = r->draws->log_len;
    bool stop = false;
    st = dfi_residual_early(r, b, list, early, &stop);
    if (st != DUOFORGE_OK || stop) {
        return st;
    }
    st = dfi_residual_durations(r, b, first, &stop);
    if (st != DUOFORGE_OK || stop) {
        return st;
    }
    st = dfi_residual_late(r, b, list, herbs_from, sorted, &stop);
    if (st != DUOFORGE_OK || stop) {
        return st;
    }
    return dfi_residual_noorder(r, b, list, sorted, n, ps);
}

/* The residual's tie between the two no-order handlers of one Pokemon, Protect's volatile and its stall counter (equal
 * keys: order none, one sub-order, one holder's Speed). The reference shuffles every tied group while it sorts
 * (Battle.speedSort, sim/battle.ts:429-460), one draw random(start, start + 2) for a pair, so every Protect turn draws.
 * The order shows in one case only: the battle ends at the faint point that follows the stall counter (it does not
 * end), and then a Pokemon that still stands has kept Protect's volatile when the stall counter ran first (the loop
 * above stops there) and lost it when Protect's own duration handler did. The conversion keeps exactly that draw
 * (tools/reference/trace_to_c.py no_order_end_tie: the battle ends in the step and a lone pair of a standing holder is
 * the group) and drops the others, so the engine draws exactly then: a battle that ended in this residual and a standing
 * Pokemon whose handlers are that pair, in Speed order. The pre-shuffle order of the group is the reference's list order,
 * which the state does not hold; the conversion states the outcome instead (0: the stall counter ran first, 1: Protect's
 * volatile did), and a uniform shuffle makes the engine's own draw the same distribution. The outcome matters only when
 * the end was at that Pokemon's own faint point; an earlier end (a Perish count's, a side condition's) left every no-order
 * handler unrun and the draw is spent unseen. A group of more than the pair (an equal-Speed neighbour, Helping Hand) is
 * refused, as before: its permutation is not modelled. */
static duoforge_status dfi_residual_pair_draws(dfi_run *r, const dfi_noorder_snapshot *ps)
{
    struct duoforge_battle *b = r->b;
    uint32_t order[DFI_POSITIONS];
    uint32_t n = 0u;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        if (ps->pair[flat] && dfi_alive(b, flat)) {
            order[n] = flat;
            n += 1u;
        }
    }
    for (uint32_t i = 1u; i < n; ++i) {
        for (uint32_t j = i; j > 0u && ps->key[order[j]] > ps->key[order[j - 1u]]; --j) {
            const uint32_t swap = order[j];
            order[j] = order[j - 1u];
            order[j - 1u] = swap;
        }
    }
    for (uint32_t i = 0u; i < n; ++i) {
        const uint32_t flat = order[i];
        for (uint32_t j = 0u; j < DFI_POSITIONS; ++j) {
            if (j != flat && ps->had[j] && ps->key[j] == ps->key[flat]) {
                return DUOFORGE_E_UNSUPPORTED; /* a bigger group: its shuffle is not modelled */
            }
        }
        if (ps->key[flat] > ps->drawn_slowest) {
            return DUOFORGE_E_UNSUPPORTED; /* the reference draws this pair before a slower group that phase 2 drew: the tape's order */
        }
        if (i == 0u && r->draws->log_len != ps->draws_after_order) {
            /* The reference draws the pair in its sort, before every handler of the residual; a handler of this residual
             * drew already (a fatigue's confusion, a sleep's turns), so the engine's draw would come after it: the tape's
             * order (issue 633). */
            return DUOFORGE_E_UNSUPPORTED;
        }
        uint32_t v = 0u;
        const duoforge_status st = dfi_draw(r->draws, DFI_SITE_SPEED_TIE, 0u, 2u, &v);
        if (st != DUOFORGE_OK) {
            return st;
        }
        if (ps->ended_at == flat && v == 1u) {
            dfi_active_slot *pos = dfi_pos(b, flat);
            pos->flags = (uint8_t)((uint32_t)pos->flags & ~(uint32_t)DFI_VOL_PROTECT); /* wide-operands-reviewed */
            b->tail.sides[flat / 2u].positions[flat % 2u].protect_kind = (uint8_t)DFI_PROTECT_PLAIN;
        }
    }
    return DUOFORGE_OK;
}

static duoforge_status dfi_residual_events(dfi_run *r)
{
    dfi_noorder_snapshot ps = {{false}, {false}, {0u}, DFI_POSITIONS, UINT32_MAX, 0u};
    const duoforge_status st = dfi_residual_events_run(r, &ps);
    if (st != DUOFORGE_OK || !r->ended) {
        return st;
    }
    return dfi_residual_pair_draws(r, &ps);
}

#include "combat/flow/turn.h"
