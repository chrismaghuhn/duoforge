#ifndef DUOFORGE_COMBAT_FLOW_QUEUE_H
#define DUOFORGE_COMBAT_FLOW_QUEUE_H

/* Private flow implementation (restructure step 4, flow): the action queue: priority, Speed keys, sorting and the next
 * action. Split from src/combat/turn.c@c02189e7; included by turn.c where the code stood, so its dependencies and the
 * turn order are unchanged. */
#include "combat/run_internal.h"

/* ---------------------------------------------------------------- queue */

/* ModifyPriority: Prankster gives status moves +1, Grassy Glide gets +1
 * in Grassy Terrain for a grounded user. Biased like the move table.
 *
 * A fainted holder's queued action is priced again after every action (sim/battle.ts:2919-2926 re-sorts the queue,
 * and Battle.getActionSpeed, :2619-2662, runs ModifyPriority at :2645-2646). The action stays queued and is skipped
 * when it comes up (:2705-2707), so only its sort key matters, and that decides which actions tie and so how many
 * values the shuffle draws. faintMessages (:2566) sets isActive false after clearVolatile, and then no ability or
 * item of the holder speaks: runEvent drops an ability handler whose holder ignoringAbility() (:879-883;
 * sim/pokemon.ts:858-859, true for !isActive) and an item handler whose holder ignoringItem() (:874-878;
 * sim/pokemon.ts:879-881, the same), so a fainted Prankster's status action has the move's own priority. The move's
 * own onModifyPriority (Grassy Glide) is a singleEvent on the move and still runs; its grounded test reads the types
 * alone (no Levitate or Air Balloon in the pool). No other ability or item of the pool changes a priority:
 * tools/datagen/pool_families.js pins that every modelled ability or item with a priority or Speed callback is
 * Prankster, Unburden, Choice Scarf or (step G22) one of the four weather Speed abilities, so a new one cannot enter
 * without this function and dfi_speed_key being looked at. Quick Claw's onFractionalPriority (decision 0015 entry 5eh) is
 * the one fractional callback: drawn once when the action is resolved, kept in its record, read by dfi_key_of. */
static uint32_t dfi_move_priority(const struct duoforge_battle *b, const dfi_member *m, const dfi_move_data *md)
{
    uint32_t priority = md->priority;
    const bool standing = m->hp != 0u; /* isActive: the holder's ability and item count */
    if (standing && dfi_ability(b, m, DFI_ABILITY_PRANKSTER) && md->category == DFI_CATEGORY_STATUS) {
        priority += 1u;
    }
    if (md->special == DFI_SPECIAL_GRASSY_GLIDE && b->terrain == DFI_TERRAIN_GRASSY && dfi_grounded(b, m)) {
        priority += 1u;
    }
    /* Gale Wings' onModifyPriority (step G34, data/abilities.ts:1588-1596): +1 for a Flying move of a holder at full HP; the
     * move's type is the one it has before ModifyType (an -ate ability's change comes later). */
    if (standing && md->type == DFI_TYPE_FLYING && md->special != DFI_SPECIAL_STRUGGLE && m->hp == m->hp_max &&
        dfi_ability(b, m, DFI_ABILITY_GALEWINGS)) {
        priority += 1u;
    }
    return priority;
}

/* Expanding Force (data/moves.ts:4943-4965, step G15): its onModifyMove makes the target allAdjacentFoes while the user
 * isGrounded in Psychic Terrain; useMoveInner runs it after BeforeMove and the PP (sim/battle-actions.ts:431), so
 * getTarget (runMove) and the choice's target still see "normal", and the request offers a target. Wide Guard, the
 * spread modifier and the protect check read the active move's target, so they see the class that this returns; the
 * redirection of getMoveTargets' default branch (Follow Me, Lightning Rod) is not run for a spread class. The user's
 * grounding is its type alone (no Levitate, Air Balloon, Ingrain, Magnet Rise, Telekinesis, Smack Down or Roost is
 * modelled, and Gravity (step K4) is not consulted for it; no pool forme that learns the move is a Flying type:
 * tools/datagen/test_pool_rows.py). The
 * terrain and the user stay the same through the move, so base power and target class agree. */
static uint32_t dfi_effective_target_class(const struct duoforge_battle *b, const dfi_member *m, const dfi_move_data *md)
{
    if (md->special == DFI_SPECIAL_EXPANDING_FORCE && b->terrain == DFI_TERRAIN_PSYCHIC && dfi_grounded(b, m)) {
        return DUOFORGE_TARGET_CLASS_ALL_ADJACENT_FOES;
    }
    return md->target_class;
}

/* The target class of a move for a user of the given types (step G84; the Curse override of
 * data/mods/champions/moves.ts:165-196, Showdown's getMoves, sim/pokemon.ts: a user that is not a Ghost gets the move's
 * nonGhostTarget): a Curse of a user without the Ghost type targets the user (onModifyMove sets 'self'), so the request
 * offers no target and the choice has none. The pool row says normal; a Ghost user keeps it (dfi_run_curse and dfi_curse_targets
 * model its Ghost variant, decision 0063). Every other move keeps the class of its row. The one rule behind the
 * request (dfi_user_target_class) and the public query duoforge_data_request_target_class, which the Python replay calls.
 * types are the user's current types; DFI_CLOSURE_NONE marks no type. */
uint32_t dfi_target_class_for_types(uint32_t special, uint32_t table_class, const uint32_t types[2])
{
    if (special != DFI_SPECIAL_CURSE) {
        return table_class;
    }
    return types[0] == DFI_TYPE_GHOST || types[1] == DFI_TYPE_GHOST ? table_class : DUOFORGE_TARGET_CLASS_SELF;
}

/* The target class of a move for its user (step G84): the class of the user's current types (dfi_types_of: a Soak, a Double
 * Shock and a Mega forme count) through dfi_target_class_for_types. */
uint32_t dfi_user_target_class(const struct duoforge_battle *b, uint32_t user, uint32_t special, uint32_t table_class)
{
    if (special != DFI_SPECIAL_CURSE) {
        return table_class;
    }
    const uint32_t occupant = b->sides[user / DUOFORGE_ACTIVE_PER_SIDE].positions[user % DUOFORGE_ACTIVE_PER_SIDE].occupant;
    if (occupant >= DUOFORGE_MAX_ROSTER) {
        return table_class;
    }
    uint32_t types[2];
    dfi_types_of(b, &b->sides[user / DUOFORGE_ACTIVE_PER_SIDE].members[occupant], types);
    return dfi_target_class_for_types(special, table_class, types);
}

/* The type a move has when it is used (useMoveInner, sim/battle-actions.ts:430-438: the move's own onModifyType first, then
 * the abilities'): Struggle is typeless; an -ate ability (the ATE family, decision 0015: onModifyType at priority -1)
 * turns a Normal move into its type before immunity and STAB, except the moves of its noModifyType list; Weather Ball
 * turns Water in rain, Fire under sun, Rock in sand, Ice in snow (data/moves.ts:20711-20717); Terrain Pulse (step G25,
 * data/moves.ts:19273-19291) takes the type of the terrain for a grounded user. The redirection of Lightning Rod reads the
 * type of this call (getMoveTargets runs after ModifyType, sim/pokemon.ts:829-831), so a Terrain Pulse in Electric Terrain is
 * drawn to it, which the move's table type (Normal) would not say. */
static uint32_t dfi_move_type_now(const dfi_run *r, const dfi_member *m, const dfi_move_data *md)
{
    const struct duoforge_battle *b = r->b;
    uint32_t move_type = md->special == DFI_SPECIAL_STRUGGLE ? DFI_CLOSURE_NONE : md->type;
    move_type = dfi_ate_type_fam(dfi_ability_family_now(b, m), md, move_type);
    /* Liquid Voice (step G22, POOL data, data/abilities.ts:2416-2427): onModifyType (priority -1) makes a move with the
     * sound flag Water, unless its user is Dynamaxed (never in this format). Weather Ball has no sound flag and Struggle none
     * either, so the order against their types does not matter; the whole pool's sound moves are the flags2 SOUND bit (the
     * pinned flag, tools/datagen/pool_families.js checkG22). The change reaches the immunity, the STAB, the weather and the
     * resist berries: they read the type of this call. */
    if (dfi_ability(b, m, DFI_ABILITY_LIQUIDVOICE) && md->special != DFI_SPECIAL_STRUGGLE &&
        (dfi_pool_move_flags2[(uint32_t)(md - dfi_pool_moves)] & DFI_MOVE_FLAG2_SOUND) != 0u) { /* wide-operands-reviewed: a pointer into the move table */
        move_type = DFI_TYPE_WATER;
    }
    /* Weather Ball reads pokemon.effectiveWeather of its user (dfi_move_weather: Mega Sol's sun, else the field). */
    const uint32_t weather = md->special == DFI_SPECIAL_WEATHER_BALL ? dfi_move_weather(r, m, true) : DFI_WEATHER_NONE;
    if (weather == DFI_WEATHER_RAIN) {
        move_type = DFI_TYPE_WATER;
    } else if (weather == DFI_WEATHER_SUN) {
        move_type = DFI_TYPE_FIRE;
    } else if (weather == DFI_WEATHER_SAND) {
        move_type = DFI_TYPE_ROCK;
    } else if (weather == DFI_WEATHER_SNOW) {
        move_type = DFI_TYPE_ICE;
    }
    if (md->special == DFI_SPECIAL_TERRAIN_PULSE && dfi_grounded(b, m)) {
        move_type = b->terrain == DFI_TERRAIN_ELECTRIC  ? DFI_TYPE_ELECTRIC
                    : b->terrain == DFI_TERRAIN_GRASSY  ? DFI_TYPE_GRASS
                    : b->terrain == DFI_TERRAIN_MISTY   ? DFI_TYPE_FAIRY
                    : b->terrain == DFI_TERRAIN_PSYCHIC ? DFI_TYPE_PSYCHIC
                                                        : move_type;
    }
    return move_type;
}

/* Step G58, Phantom Force's semi-invulnerability (the volatile phantomforce of data/moves.ts:13327-13330: duration 2,
 * onInvulnerability false; the charge is twoturnmove, sim/battle-actions.ts:621-643 is the Invulnerability step). A position
 * is semi-invulnerable while its two-turn lock is Phantom Force's: on the charge turn, from the charge to the end of the turn;
 * on the locked turn, until its own action, whose onTryMove removes the volatile. No field of its own is needed: the charge
 * (charge_turns is 2 on the charge turn and 1 after its residual) and the locked move say which turn it is, and the user's
 * MOVE record is queued exactly until the locked action has run. A fainted user has no charge (the charge ends with it). */
/* Step G58 (generalised by the semi-invulnerable exemptions of the terrains): the engine's form of Pokemon.isSemiInvulnerable
 * (sim/pokemon.ts:2162-2165: the volatiles fly, bounce, dive, dig, phantomforce, shadowforce, and skydrop). Today only the
 * charge of Phantom Force makes a position semi-invulnerable (the only such source the pool marks). Fly, Bounce, Dive, Dig,
 * Shadow Force and Sky Drop must extend this predicate when their rows are marked (none is). Every reader of the pin's
 * isSemiInvulnerable() in the marked data calls this predicate: the Invulnerability step (dfi_invulnerable_to), the
 * terrains' status, confusion, Earthquake and Dragon weakening, the Grassy residual heal, the terrains' attacker boosts and
 * Psychic Terrain's TryHit (data/moves.ts:4517, 4525, 4533, 7695, 7714, 12171, 12178, 12186, 14119, 14132). */
static bool dfi_semi_invulnerable(dfi_run *r, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    const dfi_active_slot *pos = dfi_pos(b, flat);
    const dfi_member *m = dfi_at(b, flat);
    if (pos->charge_turns == 0u || pos->locked_move == 0u || m == NULL || m->hp == 0u ||
        dfi_move_of(m, (uint32_t)pos->locked_move - 1u) != DFI_MOVE_PHANTOMFORCE) {
        return false;
    }
    if (pos->charge_turns >= DFI_CHARGE_TURNS_MAX) {
        return true;
    }
    for (uint32_t i = 0u; i < b->queue_len; ++i) {
        if (b->queue[i].kind == DFI_Q_MOVE && (uint32_t)b->queue[i].side * 2u + (uint32_t)b->queue[i].slot == flat) {
            return true;
        }
    }
    return false;
}

/* Step G58, the Invulnerability step of a move against one target (hitStepInvulnerabilityEvent, sim/battle-actions.ts:621-643):
 * a semi-invulnerable target is a miss unless No Guard is on the user or on the target (onAnyInvulnerability returns 0, not
 * false: data/abilities.ts:2970-2974) or the move is a Toxic of a Poison-type user (sim/battle-actions.ts:627-628). Helping
 * Hand never reaches it (its own function). Lock-On (onSourceInvulnerability) is unmarked, so it cannot be in a battle. */
static bool dfi_invulnerable_to(dfi_run *r, uint32_t user, uint32_t target, uint32_t move_id)
{
    struct duoforge_battle *b = r->b;
    if (!dfi_semi_invulnerable(r, target)) {
        return false;
    }
    if (dfi_ability(b, dfi_at(b, user), DFI_ABILITY_NOGUARD) || dfi_ability(b, dfi_at(b, target), DFI_ABILITY_NOGUARD)) {
        return false;
    }
    return !(move_id == DFI_MOVE_TOXIC && dfi_has_type(b, dfi_at(b, user), DFI_TYPE_POISON));
}

/* Feint's breaksProtect (hitStepBreakProtect, sim/battle-actions.ts:755-777, the step after the accuracy check, for every target
 * that is still hit): the target's Protect volatile and the Wide Guard of its side are removed (Quick Guard, Crafty Shield,
 * Mat Block and the other protections are not modelled: UNMODELED rows), and if any was there the line is
 * `-activate|target|move: Feint` and the target's stall counter is deleted, so that its next Protect succeeds again.
 * (Feint has no protect flag, so Protect never stops it: only the breaking is its effect.) */
static void dfi_break_protect(dfi_run *r, uint32_t flat, uint32_t move_id)
{
    struct duoforge_battle *b = r->b;
    dfi_active_slot *pos = dfi_pos(b, flat);
    bool broke = false;
    if (((uint32_t)pos->flags & DFI_VOL_PROTECT) != 0u) {
        pos->flags = (uint8_t)((uint32_t)pos->flags & ~(uint32_t)DFI_VOL_PROTECT); /* wide-operands-reviewed */
        /* The variant belongs to the volatile (invariants.c): a Spiky Shield that breaks is a plain one from now on. */
        b->tail.sides[flat / 2u].positions[flat % 2u].protect_kind = DFI_PROTECT_PLAIN;
        broke = true;
    }
    if (b->tail.sides[flat / 2u].wide_guard != 0u) {
        b->tail.sides[flat / 2u].wide_guard = 0u;
        broke = true;
    }
    /* hitStepBreakProtect also removes Quick Guard from the target's side (sim/battle-actions.ts:756-770, gen 9). */
    if (b->tail.sides[flat / 2u].quick_guard != 0u) {
        b->tail.sides[flat / 2u].quick_guard = 0u;
        broke = true;
    }
    if (broke) {
        const duoforge_event e = dfi_ev(DUOFORGE_EVENT_ACTIVATE, flat, DUOFORGE_CAUSE_MOVE, move_id, DUOFORGE_NO_POSITION);
        dfi_emit(r, &e);
        pos->stall_level = 0u;
        pos->stall_turns = 0u;
    }
}

/* The sort key of an action (getActionSpeed): the order of its kind, the
 * move's priority (switches have none), and the action speed of the
 * Pokemon in the slot: the one leaving for a switch, the fainted one for a
 * replacement, the one that came in for its entry. */
static duoforge_status dfi_key_of(dfi_run *r, const dfi_queue_record *q, dfi_key *out)
{
    if (q->kind == DFI_Q_RESIDUAL) {
        *out = (dfi_key){DFI_ORDER_RESIDUAL, DFI_PRIORITY_BIAS, 0u, 0u};
        return DUOFORGE_OK;
    }
    uint32_t order = 0u;
    if (q->kind == DFI_Q_MOVE) {
        /* After You and Quash give a queued move its order (DFI_QRES_*, step G62); a plain move is class 200. */
        const uint32_t cls = (uint32_t)q->reserve & DFI_QRES_ORDER_MASK;
        order = cls == DFI_QRES_PRIORITIZED   ? DFI_ORDER_PRIORITIZED
                : cls == DFI_QRES_QUASHED     ? DFI_ORDER_QUASHED
                                              : DFI_ORDER_MOVE;
    } else if (q->kind == DFI_Q_SWITCH) {
        order = DFI_ORDER_SWITCH;
    } else if (q->kind == DFI_Q_SWITCH_IN) {
        order = DFI_ORDER_SWITCH_IN;
    } else if (q->kind == DFI_Q_INSTASWITCH) {
        order = DFI_ORDER_SWITCH_IN;
    } else if (q->kind == DFI_Q_REVIVE) {
        order = DFI_ORDER_REVIVE;
    } else if (q->kind == DFI_Q_RUN_SWITCH) {
        order = DFI_ORDER_RUN_SWITCH;
    } else if (q->kind == DFI_Q_MEGA) {
        order = DFI_ORDER_MEGA;
    } else {
        return DUOFORGE_E_INVARIANT;
    }
    const uint32_t flat = (uint32_t)q->side * 2u + (uint32_t)q->slot;
    const dfi_member *m = dfi_at(r->b, flat);
    if (m == NULL) {
        return DUOFORGE_E_INVARIANT;
    }
    uint32_t speed = 0u;
    const duoforge_status st = dfi_speed_key(r, flat / 2u, m, dfi_pos(r->b, flat), &speed);
    if (st != DUOFORGE_OK) {
        return st;
    }
    out->order = order;
    out->priority = DFI_PRIORITY_BIAS;
    out->frac = 0u;
    if (q->kind == DFI_Q_MOVE && !dfi_move_slot_ok(m, q->move_slot)) {
        return DUOFORGE_E_INVARIANT;
    }
    if (q->kind == DFI_Q_MOVE) {
        out->priority = dfi_move_priority(r->b, m, &dfi_pool_moves[dfi_move_of(m, q->move_slot)]);
        /* action.priority = priority + action.fractionalPriority (sim/battle.ts:2647): the fractional part that resolveAction
         * drew for the action (Quick Claw's 0.1, decision 0015 entry 5eh) stays with it for the turn, whatever the holder does
         * later, so it is a bit of the record (DFI_QRES_QUICK_CLAW), not a fact read from the holder now. */
        out->frac = ((uint32_t)q->reserve & DFI_QRES_QUICK_CLAW) != 0u ? 1u : 0u;
    }
    out->speed = speed;
    return DUOFORGE_OK;
}

/* comparePriority (sim/battle.ts:404-411): 0 a first, 1 tie, 2 b first. */
static uint32_t dfi_compare(const dfi_key *a, const dfi_key *b)
{
    if (a->order != b->order) {
        return a->order < b->order ? 0u : 2u;
    }
    if (a->priority != b->priority) {
        return a->priority > b->priority ? 0u : 2u;
    }
    /* The fraction of action.priority (decision 0015 entry 5eh): every integer priority step is larger than Quick Claw's 0.1, so
     * it decides only between equal integer priorities. */
    if (a->frac != b->frac) {
        return a->frac > b->frac ? 0u : 2u;
    }
    if (a->speed != b->speed) {
        return a->speed > b->speed ? 0u : 2u;
    }
    return 1u;
}

/* The speed key of the raw Speed stat: a fainted Pokemon's pokemon.speed
 * (setSpecies at its clearVolatile), positive even under Trick Room. */
static uint32_t dfi_raw_speed_key(const dfi_member *m)
{
    return DFI_SPEED_BIAS + (uint32_t)m->stats[DFI_STAT_SPE - 1u];
}

#include "combat/field/trick_room.h"

/* Battle.updateSpeed: every standing active Pokemon's speed is taken again;
 * a fainted one keeps the value it had (getAllActive skips it). */
static duoforge_status dfi_update_position_speed(dfi_run *r, uint32_t flat)
{
    const dfi_member *m = dfi_at(r->b, flat);
    if (m == NULL || m->hp == 0u) {
        return DUOFORGE_OK;
    }
    return dfi_speed_key(r, flat / 2u, m, dfi_pos(r->b, flat), &r->speed_seen[flat]);
}

/* At the start of a step a fainted Pokemon still on the field has its raw
 * speed; the others are taken by the first update. */
static void dfi_init_speeds(dfi_run *r)
{
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        const dfi_member *m = dfi_at(r->b, flat);
        r->speed_seen[flat] = (m != NULL && m->hp == 0u) ? dfi_raw_speed_key(m) : 0u;
    }
}

static duoforge_status dfi_update_speeds(dfi_run *r)
{
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        const duoforge_status st = dfi_update_position_speed(r, flat);
        if (st != DUOFORGE_OK) {
            return st;
        }
    }
    return DUOFORGE_OK;
}

static void dfi_swap(struct duoforge_battle *b, dfi_key *keys, uint32_t i, uint32_t j)
{
    const dfi_queue_record q = b->queue[i];
    b->queue[i] = b->queue[j];
    b->queue[j] = q;
    const dfi_key k = keys[i];
    keys[i] = keys[j];
    keys[j] = k;
}

/* Battle.speedSort of the first n queued actions (all of them, or the new
 * actions of a PIVOT answer, which commitChoices sorts before it appends
 * the stored rest of the turn): a selection sort that gathers the next
 * tied group in list order and shuffles it (PRNG.shuffle,
 * sim/prng.ts:150-157), each draw random(i, n) relative to the group. */
static duoforge_status dfi_sort_front(dfi_run *r, uint32_t n)
{
    struct duoforge_battle *b = r->b;
    duoforge_status ust = dfi_update_speeds(r);
    if (ust != DUOFORGE_OK) {
        return ust;
    }
    dfi_key keys[DFI_QUEUE_CAPACITY];
    for (uint32_t i = 0u; i < n && i < DFI_QUEUE_CAPACITY; ++i) {
        const duoforge_status st = dfi_key_of(r, &b->queue[i], &keys[i]);
        if (st != DUOFORGE_OK) {
            return st;
        }
    }
    uint32_t sorted = 0u;
    while (sorted + 1u < n) {
        uint32_t next[DFI_QUEUE_CAPACITY] = {0};
        uint32_t count = 1u;
        next[0] = sorted;
        for (uint32_t i = sorted + 1u; i < n; ++i) {
            const uint32_t c = dfi_compare(&keys[next[0]], &keys[i]);
            if (c == 2u) {
                next[0] = i;
                count = 1u;
            } else if (c == 1u) {
                next[count] = i;
                count += 1u;
            }
        }
        for (uint32_t i = 0u; i < count; ++i) {
            if (next[i] != sorted + i) {
                dfi_swap(b, keys, sorted + i, next[i]);
            }
        }
        for (uint32_t start = sorted; start + 1u < sorted + count; ++start) {
            uint32_t v = 0u;
            const duoforge_status st = dfi_draw(r->draws, DFI_SITE_SPEED_TIE, start - sorted, count, &v);
            if (st != DUOFORGE_OK) {
                return st;
            }
            if (sorted + v != start) {
                dfi_swap(b, keys, start, sorted + v);
            }
        }
        sorted += count;
    }
    return DUOFORGE_OK;
}

static duoforge_status dfi_sort_queue(dfi_run *r)
{
    return dfi_sort_front(r, r->b->queue_len);
}

static void dfi_queue_pop(struct duoforge_battle *b, dfi_queue_record *out)
{
    const uint32_t n = b->queue_len; /* >= 1 */
    *out = b->queue[0];
    for (uint32_t i = 1u; i < n && i < DFI_QUEUE_CAPACITY; ++i) {
        b->queue[i - 1u] = b->queue[i];
    }
    b->queue[n - 1u] = (dfi_queue_record){0u, 0u, 0u, 0u, 0u, 0u, 0u};
    b->queue_len = (uint8_t)(n - 1u); /* wide-operands-reviewed: < 12 */
}

/* queue.willAct (sim/battle-queue.ts): another move or switch is pending. */
static bool dfi_will_act(const struct duoforge_battle *b)
{
    for (uint32_t i = 0u; i < b->queue_len && i < DFI_QUEUE_CAPACITY; ++i) {
        const uint32_t k = b->queue[i].kind;
        if (k == DFI_Q_MOVE || k == DFI_Q_SWITCH || k == DFI_Q_SWITCH_IN || k == DFI_Q_INSTASWITCH) {
            return true;
        }
    }
    return false;
}

#endif
