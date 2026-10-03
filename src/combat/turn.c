#include "combat/turn.h"

#include "combat/ability_family.h"
#include "combat/residual_order.h"
#include "combat/events.h"
#include "combat/item_family.h"
#include "combat/move_rules.h"

#include "core/arith.h"
#include "core/modifier.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "state/closure_member.h"
#include "state/context_internal.h"
#include "state/identity.h"
#include "state/knowledge.h"

/* Action orders (sim/battle-queue.ts:174-195). */
#define DFI_ORDER_SWITCH_IN 3u    /* instaswitch: a replacement */
#define DFI_ORDER_RUN_SWITCH 101u /* the entry of a Pokemon that came in */
#define DFI_ORDER_SWITCH 103u     /* a voluntary switch */
#define DFI_ORDER_MEGA 104u       /* megaEvo */
#define DFI_ORDER_MOVE 200u
#define DFI_ORDER_RESIDUAL 300u
#define DFI_SPEED_BIAS 10000u   /* speed key: 10000 + speed, or 10000 - speed under Trick Room */
#define DFI_SPEED_CAP 10000u    /* getStat caps Speed at 10000 (sim/pokemon.ts:636) */
#define DFI_LEVEL 50u
#define DFI_POSITIONS 4u
#define DFI_STALL_DURATION 2u /* data/conditions.ts: stall */

typedef struct dfi_run {
    const struct duoforge_context *ctx;
    struct duoforge_battle *b;
    dfi_draws *draws;
    /* Pokemon whose HP reached 0 during the current action, in that order
     * (the reference's faintQueue). */
    uint32_t faint_queue[DFI_POSITIONS];
    uint32_t faint_count;
    uint32_t faint_announced; /* how many of them a faintMessages already showed */
    uint32_t last_fainted; /* flat position of the last processed faint */
    bool ended;
    /* The result a hit loop's faintMessages already showed (DFI_RESULT_*),
     * DFI_RESULT_NONE when the end of the action shows it. */
    uint32_t early_result;
    /* pokemon.speed: the speed key of each position at the reference's last
     * updateSpeed while its Pokemon stood (a fainted Pokemon keeps it). */
    uint32_t speed_seen[DFI_POSITIONS];
    /* residualPokemon: each position's HP before the residual events. */
    uint32_t residual_hp[DFI_POSITIONS];
    /* The step's events (docs/decisions/0007 section 6), NULL for none, and
     * the index of the current action's move event, which later protocol
     * lines amend (attrLastMove, retargetLastMove), or UINT32_MAX. */
    dfi_events *events;
    uint32_t last_move;
    /* The current move action got past BeforeMove and used its move
     * (useMove ran): the AfterMove event follows. */
    bool move_used;
    /* runMove's target, which AfterMove gets (DFI_MOVE_TARGET_*). */
    uint32_t move_target;
} dfi_run;

#define DFI_MOVE_TARGET_NONE DFI_POSITIONS          /* no target Pokemon */
#define DFI_MOVE_TARGET_SPREAD (DFI_POSITIONS + 1u) /* a spread move's random foe, not drawn */

typedef struct dfi_key {
    uint32_t order;
    uint32_t priority; /* biased like the move table */
    uint32_t speed;    /* DFI_SPEED_BIAS +/- speed */
} dfi_key;

/* ---------------------------------------------------------------- access */

static dfi_active_slot *dfi_pos(struct duoforge_battle *b, uint32_t flat)
{
    return &b->sides[flat / 2u].positions[flat % 2u];
}

/* The member at a flat position, or NULL when it is empty. */
static dfi_member *dfi_at(struct duoforge_battle *b, uint32_t flat)
{
    const uint32_t occupant = dfi_pos(b, flat)->occupant;
    if (occupant >= DUOFORGE_MAX_ROSTER) {
        return NULL;
    }
    return &b->sides[flat / 2u].members[occupant];
}

/* The brought members of a side at 0 HP: side.totalFainted, since the
 * data has no revival and faints are processed before the next action
 * (decision 0009 section 4.1; Last Respects). */
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

static const dfi_pool_forme_data *dfi_forme_of(const dfi_member *m)
{
    const dfi_pool_forme_data *base = &dfi_pool_formes[m->species_id];
    return m->is_mega != 0u ? &dfi_pool_formes[base->mega_forme] : base;
}

/* The member's types now (Pokemon.getTypes): its forme's, or the one type that Soak set (setType, sim/pokemon.ts:2109;
 * the POOL tail's soak_type of the member, zero under every other kind), which lasts until the Pokemon leaves the field,
 * faints or Mega Evolves (setSpecies resets the types, sim/pokemon.ts:1392). `m` is a member of `b`. */
static void dfi_types_of(const struct duoforge_battle *b, const dfi_member *m, uint32_t types[2])
{
    const dfi_pool_forme_data *f = dfi_forme_of(m);
    types[0] = f->types[0];
    types[1] = f->types[1];
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const dfi_member *first = &b->sides[s].members[0];
        if (m >= first && m < first + DUOFORGE_MAX_ROSTER) {
            const uint32_t soak = b->tail.sides[s].soak_type[m - first];
            if (soak != 0u) {
                types[0] = soak - 1u; /* a single type */
                types[1] = DFI_CLOSURE_NONE;
            }
            return;
        }
    }
}

static bool dfi_has_type(const struct duoforge_battle *b, const dfi_member *m, uint32_t type)
{
    uint32_t t[2];
    dfi_types_of(b, m, t);
    return t[0] == type || t[1] == type;
}

/* isGrounded with the data: not Flying (no Levitate, Air Balloon or Gravity). */
static bool dfi_grounded(const struct duoforge_battle *b, const dfi_member *m)
{
    return !dfi_has_type(b, m, DFI_TYPE_FLYING);
}

/* The item a member holds now, stored as 1 + id (0 = none): the one the member's sheet says unless it has been used
 * up, or the one that the POOL tail's item_now holds for it (zero under every other kind, and zero unless something
 * took or changed the item: DFI_TAIL_ITEM_NONE after a Knock Off, an item id + 1 after a Trick, which nothing does
 * yet). Every rule of the turn code reads the item through this, never through dfi_member.item, which is the sheet's
 * (and what the Mega Evolution reads: a Mega Stone is never taken from its own species). `m` is a member of `b`; no
 * heap, one tail read for a member that is found on a side. */
static uint32_t dfi_item_code(const struct duoforge_battle *b, const dfi_member *m)
{
    if (m == NULL || m->item_consumed != 0u) {
        return 0u; /* used up, whichever item it was */
    }
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const dfi_member *first = &b->sides[s].members[0];
        if (m >= first && m < first + DUOFORGE_MAX_ROSTER) {
            const uint32_t now = b->tail.sides[s].item_now[m - first];
            if (now == DFI_TAIL_ITEM_NONE) {
                return 0u;
            }
            if (now != 0u) {
                return now;
            }
            break;
        }
    }
    return m->item;
}

/* The member holds item `id` and has not used it up or lost it (items are stored as 1 + id). */
static bool dfi_holds(const struct duoforge_battle *b, const dfi_member *m, uint32_t id)
{
    return m != NULL && dfi_item_code(b, m) == 1u + id;
}

/* singleEvent TakeItem of the item (data/items.ts, the onTakeItem of the Mega Stones: they refuse their own species,
 * Floettite's variant at :2194 gives the same result; the Champions mod changes none): a Pokemon that holds an item
 * that can be taken from it. The only items of the pool with an onTakeItem are the Mega Stones, and takeItem() asks
 * with the Pokemon itself as the source, so a Mega Stone on another species, and every other item, is taken.
 * dfi_member.mega_capable is exactly "holds the stone of its own base forme" (the member invariant) and stays after
 * the Mega Evolution, as the Pokemon's baseSpecies does. */
static bool dfi_item_takeable(const struct duoforge_battle *b, const dfi_member *m)
{
    const uint32_t item = dfi_item_code(b, m);
    return item != 0u && !(m->mega_capable != 0u && item == m->item);
}

/* The member's ability now, stored as 1 + id (0 = none): the one the member's sheet says, or the one that the POOL tail's
 * ability_now holds for it (Trace and the other effects that change an ability; zero under every other kind, and zero
 * unless something changed it). Every rule of the turn code reads the ability through this, never through
 * dfi_member.ability, which is the sheet's (and the Mega forme's) ability. `m` is a member of `b`; no heap, one tail
 * read for a member that is found on a side. */
static uint32_t dfi_ability_code(const struct duoforge_battle *b, const dfi_member *m)
{
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const dfi_member *first = &b->sides[s].members[0];
        if (m >= first && m < first + DUOFORGE_MAX_ROSTER) {
            const uint32_t now = b->tail.sides[s].ability_now[m - first];
            return now != 0u ? now : m->ability;
        }
    }
    return m->ability;
}

/* The family row of the member's ability now (src/combat/ability_family.h). */
static dfi_ability_family dfi_ability_family_now(const struct duoforge_battle *b, const dfi_member *m)
{
    return dfi_ability_family_for(m == NULL ? 0u : dfi_ability_code(b, m));
}

/* The member's ability is `id` (abilities are stored as 1 + id). */
static bool dfi_ability(const struct duoforge_battle *b, const dfi_member *m, uint32_t id)
{
    return m != NULL && dfi_ability_code(b, m) == 1u + id;
}

/* ---------------------------------------------------------------- events */

static void dfi_emit(dfi_run *r, const duoforge_event *e)
{
    if (r->events != NULL) {
        dfi_events_push(r->events, e);
    }
}

/* An event about `position` with a cause ([from], [of]). */
static duoforge_event dfi_ev(uint32_t kind, uint32_t position, uint32_t cause, uint32_t id2, uint32_t other)
{
    duoforge_event e = dfi_event_make(kind, position);
    e.cause = (uint8_t)cause; /* <= DUOFORGE_CAUSE_POISON */
    e.id2 = (uint16_t)id2;    /* < 2^16 */
    e.other = (uint8_t)other; /* < 4 or DUOFORGE_NO_POSITION */
    return e;
}

#define DFI_FAIRY_AURA_MODIFIER 5448u /* chainModify([5448, 4096]) */

/* Fairy Aura (data/abilities.ts:1266-1282, onAnyBasePower, priority 20): a Pokemon on the field with the ability (the
 * Mega Floette's only one; a fainted Pokemon is no longer on the field). It boosts the Fairy moves of every Pokemon on
 * the field once each (move.auraBooster: a second holder changes nothing), the foes' included. Aura Break (3072/4096
 * instead) is in no pool forme's legal abilities (checked by tests/test_pool_tables.c). */
static bool dfi_fairy_aura_on_field(struct duoforge_battle *b)
{
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        const dfi_member *m = dfi_at(b, flat);
        if (m != NULL && m->hp != 0u && dfi_ability(b, m, DFI_ABILITY_FAIRYAURA)) {
            return true;
        }
    }
    return false;
}

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

/* The move failed: -fail for the user, then [still] on its move line. */
static void dfi_fail_still(dfi_run *r, uint32_t user)
{
    dfi_emit_plain(r, DUOFORGE_EVENT_FAIL, user);
    dfi_still(r);
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
static duoforge_status dfi_speed_key(const struct duoforge_battle *b, uint32_t side, const dfi_member *m,
                                     const dfi_active_slot *pos, uint32_t *out)
{
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
    /* Unburden's volatile (Team C): chainModify(2) while its holder holds no item (data/abilities.ts:5247-5251): the
     * volatile is set when the item is used or taken, and also when a Mega Stone on its own species refuses Knock Off
     * (dfi_knock_off), so the item is asked for. */
    if (active && ((uint32_t)pos->flags & DFI_VOL_UNBURDEN) != 0u && dfi_item_code(b, m) == 0u &&
        !dfi_chain_modify(chain, 8192u, &chain)) {
        return DUOFORGE_E_INVARIANT;
    }
    if (chain != 4096u) {
        spe = dfi_modify(spe, chain); /* spe <= 4 * 65535, chain <= 6 * 4096 */
    }
    if (active && m->status == DFI_STATUS_PAR) {
        spe = spe * 50u / 100u; /* spe <= 24 * 65535: stage x4, chain x6 */
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
 * Prankster, Unburden or Choice Scarf, so a new one cannot enter without this function and dfi_speed_key being
 * looked at. */
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
    return priority;
}

/* Expanding Force (data/moves.ts:4943-4965, step G15): its onModifyMove makes the target allAdjacentFoes while the user
 * isGrounded in Psychic Terrain; useMoveInner runs it after BeforeMove and the PP (sim/battle-actions.ts:431), so
 * getTarget (runMove) and the choice's target still see "normal", and the request offers a target. Wide Guard, the
 * spread modifier and the protect check read the active move's target, so they see the class that this returns; the
 * redirection of getMoveTargets' default branch (Follow Me, Lightning Rod) is not run for a spread class. The user's
 * grounding is its type alone (no Levitate, Air Balloon, Ingrain, Gravity, Magnet Rise, Telekinesis, Smack Down or
 * Roost is modelled; no pool forme that learns the move is a Flying type: tools/datagen/test_pool_rows.py). The
 * terrain and the user stay the same through the move, so base power and target class agree. */
static uint32_t dfi_effective_target_class(const struct duoforge_battle *b, const dfi_member *m, const dfi_move_data *md)
{
    if (md->special == DFI_SPECIAL_EXPANDING_FORCE && b->terrain == DFI_TERRAIN_PSYCHIC && dfi_grounded(b, m)) {
        return DUOFORGE_TARGET_CLASS_ALL_ADJACENT_FOES;
    }
    return md->target_class;
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
        pos->flags = (uint8_t)((uint32_t)pos->flags & ~(uint32_t)DFI_VOL_PROTECT);
        broke = true;
    }
    if (b->tail.sides[flat / 2u].wide_guard != 0u) {
        b->tail.sides[flat / 2u].wide_guard = 0u;
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
        *out = (dfi_key){DFI_ORDER_RESIDUAL, DFI_PRIORITY_BIAS, 0u};
        return DUOFORGE_OK;
    }
    uint32_t order = 0u;
    if (q->kind == DFI_Q_MOVE) {
        order = DFI_ORDER_MOVE;
    } else if (q->kind == DFI_Q_SWITCH) {
        order = DFI_ORDER_SWITCH;
    } else if (q->kind == DFI_Q_SWITCH_IN) {
        order = DFI_ORDER_SWITCH_IN;
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
    const duoforge_status st = dfi_speed_key(r->b, flat / 2u, m, dfi_pos(r->b, flat), &speed);
    if (st != DUOFORGE_OK) {
        return st;
    }
    out->order = order;
    out->priority = DFI_PRIORITY_BIAS;
    if (q->kind == DFI_Q_MOVE && !dfi_move_slot_ok(m, q->move_slot)) {
        return DUOFORGE_E_INVARIANT;
    }
    if (q->kind == DFI_Q_MOVE) {
        out->priority = dfi_move_priority(r->b, m, &dfi_pool_moves[dfi_move_of(m, q->move_slot)]);
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

/* Battle.updateSpeed: every standing active Pokemon's speed is taken again;
 * a fainted one keeps the value it had (getAllActive skips it). */
static duoforge_status dfi_update_position_speed(dfi_run *r, uint32_t flat)
{
    const dfi_member *m = dfi_at(r->b, flat);
    if (m == NULL || m->hp == 0u) {
        return DUOFORGE_OK;
    }
    return dfi_speed_key(r->b, flat / 2u, m, dfi_pos(r->b, flat), &r->speed_seen[flat]);
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
        if (k == DFI_Q_MOVE || k == DFI_Q_SWITCH || k == DFI_Q_SWITCH_IN) {
            return true;
        }
    }
    return false;
}

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
} dfi_boost_effect;

static dfi_boost_effect dfi_effect(uint32_t cause, uint32_t id2, uint32_t mode)
{
    const dfi_boost_effect e = {cause, id2, mode, false};
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
    /* TryBoost (after Contrary and the cap): Flower Veil deletes every drop that another Pokemon causes on a Grass
     * type of its side (sim/battle.ts:2030-2033, data/abilities.ts:1419-1437); the line shows unless the effect is a
     * move's secondary (effect.secondaries): Intimidate's does, Snarl's does not. */
    bool veil[DFI_STAT_STAGE_COUNT] = {false, false, false, false, false, false, false};
    uint32_t holder = 0u;
    if (source != flat && source != DFI_POSITIONS && dfi_flower_veil_holder(b, flat, &holder)) {
        bool any = false;
        for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
            veil[i] = boosts[i] != DFI_BIAS6 && capped[i] < DFI_BIAS6;
            any = any || veil[i];
        }
        if (any && !(effect.cause == DUOFORGE_CAUSE_MOVE && effect.mode == DFI_BOOST_SECONDARY)) {
            dfi_flower_veil_block(r, flat, holder);
        }
    }
    bool announced = effect.mode == DFI_BOOST_SECONDARY;
    /* The stats of a boost are changed in the order of the move's table in the data (Battle.boost loops over the keys of
     * the object): the stat order, except Shell Smash, whose pinned entry lists Defense and Special Defense first (data/moves.ts
     * 16255-16275); `negatives_first` is that order, two passes by the sign that the entry gives (Contrary reverses the
     * change, not the order). */
    for (uint32_t k = 0u; k < 2u * DFI_STAT_STAGE_COUNT; ++k) {
        const uint32_t i = k % DFI_STAT_STAGE_COUNT;
        const uint32_t pass = k / DFI_STAT_STAGE_COUNT;
        if (effect.negatives_first ? ((boosts[i] < DFI_BIAS6) != (pass == 0u)) : pass != 0u) {
            continue;
        }
        if (boosts[i] == DFI_BIAS6 || veil[i]) {
            continue; /* not part of this boost, or blocked */
        }
        const uint32_t before = pos->stages[i];
        uint8_t one[DFI_STAT_STAGE_COUNT] = {6u, 6u, 6u, 6u, 6u, 6u, 6u};
        one[i] = capped[i];
        dfi_apply_boosts(pos, one);
        const uint32_t after = pos->stages[i];
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


static bool dfi_alive(struct duoforge_battle *b, uint32_t flat)
{
    const dfi_member *m = dfi_at(b, flat);
    return m != NULL && m->hp != 0u;
}

/* side.randomFoe: sample over the active foes that have not fainted
 * (RANDOM_TARGET). *out = DFI_POSITIONS when there is none. */
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
                                        uint32_t targets[DFI_POSITIONS], uint32_t *count)
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
        if (chosen / 2u == side) {
            /* The ally: hit while it stands; a fainted ally is not
             * retargeted (the move fails); an empty slot falls through to a
             * random foe (sim/battle.ts:2461-2486). */
            const dfi_member *ally = dfi_at(r->b, chosen);
            if (ally != NULL) {
                if (ally->hp != 0u) {
                    targets[0] = chosen;
                    *count = 1u;
                }
                return DUOFORGE_OK;
            }
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
 * defending type. */
static uint32_t dfi_type_mod(const struct duoforge_battle *b, const dfi_member *target, uint32_t move_type)
{
    uint32_t mod = DFI_BIAS6;
    if (move_type >= DFI_TYPE_COUNT) {
        return mod;
    }
    uint32_t types[2];
    dfi_types_of(b, target, types);
    for (uint32_t i = 0u; i < 2u; ++i) {
        const uint32_t t = types[i];
        if (t >= DFI_TYPE_COUNT) {
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

/* getDamage and the Champions modifyDamage (sim/battle-actions.ts:1585-1720,
 * data/mods/champions/scripts.ts:196-312) for a turn-core move: CRIT and
 * DAMAGE_ROLL draws in that order. */
static duoforge_status dfi_get_damage(dfi_run *r, uint32_t user, uint32_t target, const dfi_move_data *md,
                                      uint32_t move_type, bool spread, uint32_t *out)
{
    static const uint32_t crit_mult[5] = {0u, 24u, 8u, 2u, 1u};
    const dfi_member *a = dfi_at(r->b, user);
    const dfi_member *d = dfi_at(r->b, target);
    const dfi_active_slot *ap = dfi_pos(r->b, user);
    const dfi_active_slot *dp = dfi_pos(r->b, target);
    bool crit = false;
    uint32_t ratio = md->crit_ratio;
    if (ratio > 4u) {
        ratio = 4u;
    }
    if (ratio > 0u) {
        const duoforge_status st = dfi_draw_chance(r->draws, DFI_SITE_CRIT, 1u, crit_mult[ratio], &crit);
        if (st != DUOFORGE_OK) {
            return st;
        }
    }
    const bool physical = md->category == DFI_CATEGORY_PHYSICAL;
    const uint32_t atk_index = physical ? DFI_STAGE_ATK : DFI_STAGE_SPA;
    const uint32_t def_index = physical ? DFI_STAGE_DEF : DFI_STAGE_SPD;
    uint32_t atk_stage = ap->stages[atk_index];
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
    uint32_t attack = 0u;
    uint32_t defense = 0u;
    uint32_t damage = 0u;
    if (!dfi_stage_stat(a->stats[atk_index], atk_stage, &attack) ||
        !dfi_stage_stat(d->stats[def_index], def_stage, &defense)) {
        return DUOFORGE_E_INVARIANT;
    }
    /* ModifyDef and ModifySpD (sim/battle-actions.ts:1707-1709) of the weather conditions, priority 10, so the first
     * handler: Sandstorm's onModifySpD gives a Rock type 1.5x its Special Defense, Snowscape's onModifyDef an Ice
     * type 1.5x its Defense (data/conditions.ts:640-645 and 706-711; this.modify(x, 1.5) is 6144/4096). */
    if (r->b->weather == DFI_WEATHER_SAND && def_index == DFI_STAGE_SPD && dfi_has_type(r->b, d, DFI_TYPE_ROCK)) {
        defense = dfi_modify(defense, 6144u);
    } else if (r->b->weather == DFI_WEATHER_SNOW && def_index == DFI_STAGE_DEF && dfi_has_type(r->b, d, DFI_TYPE_ICE)) {
        defense = dfi_modify(defense, 6144u);
    }
    /* BasePower (after the critical hit roll), one chained modifier: Mystic
     * Water (Water) and Miracle Seed (Grass) 4915/4096, Grassy Terrain
     * 5325/4096 for a grounded user's Grass move. */
    /* Weather Ball doubles in rain or sun (onModifyMove); Grass Knot's and
     * Low Kick's power follow the target's weight (basePowerCallback). */
    uint32_t power = md->base_power;
    if (md->special == DFI_SPECIAL_WEATHER_BALL && r->b->weather != DFI_WEATHER_NONE) {
        power *= 2u;
    } else if (md->special == DFI_SPECIAL_ACROBATICS) {
        /* Acrobatics' basePowerCallback (step G28, data/moves.ts:117-141): doubled while the user holds no item (the item it
         * holds now: one that was eaten, knocked off or used up is gone). */
        if (dfi_item_code(r->b, a) == 0u) {
            power *= 2u;
        }
    } else if (dfi_move_power_by_weight(md)) {
        power = dfi_weight_power(dfi_forme_of(d)->weight_hg);
    } else if (md->special == DFI_SPECIAL_LAST_RESPECTS) {
        /* Last Respects (Team C): 50 + 50 per fainted member of the user's
         * side (basePowerCallback, data/moves.ts:10091-10105). side.totalFainted
         * is derived: no revival in the data, and every faint is processed
         * before the next action starts (decision 0009 section 4.1). */
        power = 50u + 50u * dfi_fainted_members(r->b, user / 2u);
    }
    uint32_t bp_chain = 4096u;
    bool ok = true;
    /* An -ate ability (the ATE family: Aerilate, Pixilate and Refrigerate,
     * decision 0015): a Normal move it turned into its type gets 4915/4096
     * (data/abilities.ts, onBasePowerPriority 23: first). */
    if (dfi_ate_boosts_fam(dfi_ability_family_now(r->b, a), md->type, move_type)) {
        ok = dfi_chain_modify(bp_chain, DFI_ATE_MODIFIER, &bp_chain);
    }
    if (dfi_ability(r->b, a, DFI_ABILITY_TOUGHCLAWS) && (md->flags & DFI_MOVE_FLAG_CONTACT) != 0u) {
        ok = dfi_chain_modify(bp_chain, 5325u, &bp_chain); /* onBasePowerPriority 21: first */
    }
    /* Fairy Aura (the Mega Floette's ability, onAnyBasePower priority 20: after Tough Claws, before the items): a
     * Fairy move of anyone on the field, unless it targets its own user, 5448/4096 once. */
    if (move_type == DFI_TYPE_FAIRY && user != target && dfi_fairy_aura_on_field(r->b)) {
        ok = ok && dfi_chain_modify(bp_chain, DFI_FAIRY_AURA_MODIFIER, &bp_chain);
    }
    /* A type booster (the TYPE_BOOSTER family: Mystic Water, Miracle Seed
     * and the sixteen others, decision 0015): 4915/4096 for a move of its
     * type (onBasePowerPriority 15). */
    if (dfi_type_booster_applies(dfi_item_code(r->b, a), move_type)) {
        ok = ok && dfi_chain_modify(bp_chain, DFI_TYPE_BOOSTER_MODIFIER, &bp_chain);
    }
    /* Helping Hand's volatile (Team C): chainModify(1.5) at
     * onBasePowerPriority 10, after the items (15) and before Grassy Terrain
     * (6) (data/moves.ts:8590-8597). */
    if (((uint32_t)dfi_pos(r->b, user)->flags & DFI_VOL_HELPING_HAND) != 0u) {
        ok = ok && dfi_chain_modify(bp_chain, 6144u, &bp_chain);
    }
    if (move_type == DFI_TYPE_GRASS && r->b->terrain == DFI_TERRAIN_GRASSY && dfi_grounded(r->b, a)) {
        ok = ok && dfi_chain_modify(bp_chain, 5325u, &bp_chain);
    }
    /* Psychic Terrain (Team C): 5325/4096 for a grounded user's Psychic move
     * (onBasePowerPriority 6, like Grassy Terrain's, which cannot be up at
     * the same time). */
    if (move_type == DFI_TYPE_PSYCHIC && r->b->terrain == DFI_TERRAIN_PSYCHIC && dfi_grounded(r->b, a)) {
        ok = ok && dfi_chain_modify(bp_chain, 5325u, &bp_chain);
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
    const uint32_t base_power = bp_chain == 4096u ? power : dfi_modify(power, bp_chain);
    /* ModifyAtk / ModifySpA, one chained modifier: a pinch ability (the
     * PINCH family: Blaze, Overgrow, Torrent and Swarm, decision 0015) for a
     * move of its type at a third of the HP or less, Flash Fire's boost for
     * Fire moves once it took one; 1.5 each. */
    uint32_t atk_chain = 4096u;
    if (dfi_pinch_applies_fam(dfi_ability_family_now(r->b, a), a, move_type)) {
        ok = ok && dfi_chain_modify(atk_chain, DFI_PINCH_MODIFIER, &atk_chain);
    }
    if (move_type == DFI_TYPE_FIRE && dfi_ability(r->b, a, DFI_ABILITY_FLASHFIRE) &&
        ((uint32_t)ap->flags & DFI_VOL_FLASH_FIRE) != 0u) {
        ok = ok && dfi_chain_modify(atk_chain, 6144u, &atk_chain);
    }
    if (!ok) {
        return DUOFORGE_E_INVARIANT;
    }
    if (atk_chain != 4096u) {
        attack = dfi_modify(attack, atk_chain);
    }
    if (!dfi_base_damage(DFI_LEVEL, base_power, attack, defense, &damage)) {
        return DUOFORGE_E_INVARIANT;
    }
    damage += 2u;
    if (spread) {
        damage = dfi_modify(damage, 3072u); /* 0.75 */
    }
    /* WeatherModifyDamage: rain and sun boost their type by half and halve
     * the other (data/conditions.ts raindance, sunnyday). */
    const uint32_t weather = r->b->weather;
    if ((weather == DFI_WEATHER_RAIN && move_type == DFI_TYPE_WATER) ||
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
        mod = dfi_type_mod(r->b, d, move_type);
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
    /* A burned attacker's physical moves, Struggle included, do half
     * (modifyDamage, sim/battle-actions.ts:1816-1820). */
    if (physical && a->status == DFI_STATUS_BRN) {
        damage = dfi_modify(damage, 2048u);
    }
    /* ModifyDamage, one chained modifier: the attacker's Life Orb 5324/4096;
     * the target's Chople Berry (Team C, data/items.ts:1030-1053), which it
     * eats inside the calculation of a super-effective Fighting hit
     * ([-enditem] [eat], then [weaken]) for 2048/4096; then Reflect
     * (physical) or Light Screen (special) on the target's side, not against
     * a critical hit and not on the user itself, 2732/4096 in doubles.
     * The reference orders the handlers by speed: the held items by their
     * holders' speed, a screen as a side condition at 0 (comparePriority), so
     * last, or first under Trick Room, where speeds are negative. Every order
     * of these modifiers chains to the same value (checked below), so the
     * order and a speed tie between the holders decide nothing (its shuffle
     * draw is dropped, decision 0009 section 10.5). */
    const dfi_side *ds = &r->b->sides[target / 2u];
    uint32_t chain = 4096u;
    uint32_t mods = 0u; /* the ModifyDamage modifiers in the chain */
    if (dfi_holds(r->b, a, DFI_ITEM_LIFEORB)) {
        ok = dfi_chain_modify(chain, 5324u, &chain);
        mods += 1u;
    }
    /* Expert Belt's onModifyDamage (step G28, data/items.ts:1901-1914): 4915/4096 when the hit is super effective
     * (typeMod > 0: the combined type effectiveness above the neutral one). */
    if (dfi_holds(r->b, a, DFI_ITEM_EXPERTBELT) && mod > DFI_BIAS6) {
        ok = ok && dfi_chain_modify(chain, 4915u, &chain);
        mods += 1u;
    }
    /* A resist berry (the RESIST_BERRY family: Chople Berry and the sixteen
     * others, decision 0015; combat/item_family.h) is eaten by a super
     * effective hit of its type, the Normal berry by any Normal hit. */
    const uint32_t berry_item = dfi_item_code(r->b, d);
    if (dfi_resist_berry_applies(berry_item, move_type, mod)) {
        dfi_use_item(r, target); /* [-enditem] [eat] */
        duoforge_event weaken =
            dfi_ev(DUOFORGE_EVENT_ITEM_END, target, DUOFORGE_CAUSE_NONE, berry_item, DUOFORGE_NO_POSITION);
        weaken.detail = 1u;
        dfi_emit(r, &weaken); /* [-enditem] [weaken] */
        ok = ok && dfi_chain_modify(chain, DFI_RESIST_BERRY_MODIFIER, &chain);
        mods += 1u;
    }
    /* Aurora Veil (step G20, data/moves.ts:846-860) weakens both categories by the same 2732/4096 and returns without an
     * effect when the target's side has the screen of the move's category (so the two never multiply): the test is one
     * 2732 for a screen of the category or Aurora Veil. A critical hit and `infiltrates` (no Infiltrator or move that
     * has it is marked) skip all three. */
    if (!crit && target != user &&
        ((physical && ds->reflect_turns != 0u) ||
         (md->category == DFI_CATEGORY_SPECIAL && ds->light_screen_turns != 0u) ||
         r->b->tail.sides[target / 2u].aurora_veil_turns != 0u)) {
        ok = ok && dfi_chain_modify(chain, 2732u, &chain);
        mods += 1u;
    }
    /* Glaive Rush's onSourceModifyDamage on the target (data/moves.ts:6647-6678): chainModify(2). With a Life Orb attacker,
     * a resist berry and a screen all in the chain the four modifiers do not commute (3552 or 3551 by their order, the
     * handlers' speeds and a tie draw), a case that this build does not model. */
    if (r->b->tail.sides[target / 2u].positions[target % 2u].glaive_rush != 0u) {
        if (mods >= 3u) {
            return DUOFORGE_E_UNSUPPORTED; /* three modifiers already: the order of the fourth is not modelled */
        }
        ok = ok && dfi_chain_modify(chain, 8192u, &chain);
    }
    if (!ok) {
        return DUOFORGE_E_INVARIANT;
    }
    if (chain != 4096u) {
        damage = dfi_modify(damage, chain);
    }
    *out = dfi_final_damage(damage);
    return DUOFORGE_OK;
}

/* Pokemon.damage: HP never below 0; reaching 0 queues the faint. */
static duoforge_status dfi_deal(dfi_run *r, uint32_t flat, uint32_t amount, uint32_t cause, uint32_t id2,
                                uint32_t other)
{
    dfi_member *m = dfi_at(r->b, flat);
    const uint32_t hp = m->hp;
    if (hp == 0u) {
        return DUOFORGE_OK;
    }
    m->hp = (uint16_t)(hp > amount ? hp - amount : 0u); /* wide-operands-reviewed: <= hp */
    if (amount != 0u) {
        dfi_emit_hp(r, dfi_ev(DUOFORGE_EVENT_DAMAGE, flat, cause, id2, other)); /* [-damage] */
    }
    if (m->hp == 0u) {
        if (dfi_support.switching == 0u) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        if (r->faint_count < DFI_POSITIONS) {
            r->faint_queue[r->faint_count] = flat;
            r->faint_count += 1u;
        }
    }
    return DUOFORGE_OK;
}

/* runStatusImmunity('psn') (Team C): a type whose chart entry carries the
 * psn key, Poison and Steel (data/typechart.ts). */
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
static duoforge_status dfi_try_status(dfi_run *r, uint32_t flat, uint32_t status, uint32_t user, uint32_t move_id,
                                      bool primary, uint32_t from_ability)
{
    static const uint8_t sleep_turns[3] = {2u, 3u, 3u};
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
    if ((status == DFI_STATUS_BRN && dfi_has_type(r->b, m, DFI_TYPE_FIRE)) ||
        (status == DFI_STATUS_PAR && dfi_has_type(r->b, m, DFI_TYPE_ELECTRIC)) ||
        (status == DFI_STATUS_FRZ && (dfi_has_type(r->b, m, DFI_TYPE_ICE) || r->b->weather == DFI_WEATHER_SUN)) ||
        (status == DFI_STATUS_PSN && dfi_poison_immune(r->b, m))) {
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
    if (user != flat && dfi_flower_veil_holder(r->b, flat, &holder)) {
        if (primary) {
            dfi_flower_veil_block(r, flat, holder);
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
        counter = 3u;
    }
    m->status = (uint8_t)status;          /* <= DFI_STATUS_PSN */
    m->status_counter = (uint8_t)counter; /* <= 3 */
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
        pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_FLINCH); /* wide-operands-reviewed */
        return DUOFORGE_OK;
    }
    if (which != DFI_VOLATILE_CONFUSION) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    if (pos->confusion_turns != 0u) {
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

/* Emergency Exit (onEmergencyExit, data/mods/champions/abilities.ts): a
 * standing holder that fell from above half HP to half or less, with a
 * reserve and no switch flag yet, leaves. Unlike the base game, the
 * Champions handler leaves every other switch flag in place. */
static bool dfi_exits(struct duoforge_battle *b, uint32_t flat, uint32_t hp_before)
{
    const dfi_member *m = dfi_at(b, flat);
    return m != NULL && m->hp != 0u && dfi_ability_code(b, m) == 1u + DFI_ABILITY_EMERGENCYEXIT &&
           (uint32_t)m->hp * 2u <= m->hp_max && hp_before * 2u > m->hp_max && dfi_can_switch(b, flat / 2u) &&
           dfi_pos(b, flat)->switch_flag == 0u;
}

static void dfi_emergency_exit(dfi_run *r, uint32_t flat, uint32_t hp_before)
{
    if (dfi_exits(r->b, flat, hp_before)) {
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
    struct duoforge_battle *b = r->b;
    const uint32_t side = flat / 2u;
    const uint32_t occupant = dfi_pos(b, flat)->occupant;
    const uint32_t item = dfi_item_code(b, &b->sides[side].members[occupant]); /* before it is used up */
    b->sides[side].members[occupant].item_consumed = 1u;
    duoforge_event e = dfi_ev(DUOFORGE_EVENT_ITEM_END, flat, DUOFORGE_CAUSE_NONE, item, DUOFORGE_NO_POSITION);
    const bool berry = item == 1u + DFI_ITEM_SITRUSBERRY ||
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
    if (((uint32_t)pos->flags & DFI_VOL_CHOICE_LOCK) != 0u) {
        pos->flags = (uint8_t)((uint32_t)pos->flags & ~(uint32_t)DFI_VOL_CHOICE_LOCK); /* wide-operands-reviewed */
        if (pos->charge_turns == 0u) {
            pos->locked_move = 0u;
        }
    }
}

/* White Herb's check (onStart, data/items.ts): its standing holder has a
 * lowered stat. */
static bool dfi_herb_due(struct duoforge_battle *b, uint32_t flat)
{
    const dfi_member *m = dfi_at(b, flat);
    if (m == NULL || m->hp == 0u || !dfi_holds(b, m, DFI_ITEM_WHITEHERB)) {
        return false;
    }
    const dfi_active_slot *pos = dfi_pos(b, flat);
    bool lowered = false;
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        lowered = lowered || pos->stages[i] < DFI_STAGE_NEUTRAL;
    }
    return lowered;
}

/* White Herb (Team C, data/items.ts): when it is due, its holder uses it:
 * [-enditem], then the lowered stages go back to 0 ([-clearnegativeboost]
 * is [silent]), then AfterUseItem (Unburden). */
static void dfi_white_herb(dfi_run *r, uint32_t flat)
{
    if (!dfi_herb_due(r->b, flat)) {
        return;
    }
    dfi_use_item(r, flat);
    dfi_active_slot *pos = dfi_pos(r->b, flat);
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        if (pos->stages[i] < DFI_STAGE_NEUTRAL) {
            pos->stages[i] = (uint8_t)DFI_STAGE_NEUTRAL;
        }
    }
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

/* A standing Pokemon whose White Herb is unused: it has the herb's
 * handlers (side.allies() keeps only Pokemon with HP). */
static bool dfi_herb_holder(struct duoforge_battle *b, uint32_t flat)
{
    const dfi_member *m = dfi_at(b, flat);
    return m != NULL && m->hp != 0u && dfi_holds(b, m, DFI_ITEM_WHITEHERB);
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
        dfi_white_herb(r, list[i]);
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

/* Psychic Noise's Heal Block lasts 2 turns (durationCallback, data/moves.ts:8286-8289); Throat Chop's condition has
 * duration 2 (data/moves.ts:19391-19393, DFI_TAIL_THROAT_CHOP_MAX). */
#define DFI_HEAL_BLOCK_PSYCHIC_NOISE_TURNS 2u

/* Encore's condition has duration 3 (data/moves.ts:4724-4783); onStart adds one when the target has no move queued. */
#define DFI_ENCORE_TURNS 3u

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
static duoforge_status dfi_update(dfi_run *r)
{
    uint32_t bearers = 0u;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        bearers |= dfi_holds(r->b, dfi_at(r->b, flat), DFI_ITEM_SITRUSBERRY) ? 1u << flat : 0u;
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
        const dfi_member *m = dfi_at(r->b, flat);
        if (m->hp != 0u && dfi_holds(r->b, m, DFI_ITEM_SITRUSBERRY) && (uint32_t)m->hp * 2u <= m->hp_max &&
            !dfi_heal_blocked(r->b, flat)) {
            dfi_use_item(r, flat);
            dfi_heal(r, flat, (uint32_t)m->hp_max / 4u, DUOFORGE_CAUSE_ITEM, 1u + DFI_ITEM_SITRUSBERRY,
                     DUOFORGE_NO_POSITION);
        }
    }
    return DUOFORGE_OK;
}

/* runStatusImmunity('sandstorm'): a type whose chart entry carries the sandstorm key, Rock, Ground and Steel
 * (data/typechart.ts), judged by the types now (dfi_types_of: a Soaked Pokemon is a Water type alone, step G11). An
 * ability or item that gives the immunity (Overcoat, Sand Force, Sand Rush, Sand Veil,
 * Safety Goggles) or stops indirect damage (Magic Guard) is not marked in the support manifest, so no battle
 * holds one (tests/test_pool_weather.c checks that); marking one needs its immunity here. */
static bool dfi_sand_immune(const struct duoforge_battle *b, const dfi_member *m)
{
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
        if (m != NULL && m->hp != 0u && !dfi_sand_immune(r->b, m)) {
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
                      DUOFORGE_NO_POSITION);
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

/* checkWin (sim/battle.ts:404-415): a side with no Pokemon left loses; when
 * every side is out, the side whose Pokemon fainted last wins (generation 5
 * and later). */
static uint32_t dfi_win_result(const struct duoforge_battle *b, uint32_t last_fainted)
{
    const uint32_t left0 = dfi_left(b, 0u);
    const uint32_t left1 = dfi_left(b, 1u);
    if (left0 == 0u && left1 == 0u) {
        return last_fainted / 2u == 0u ? DFI_RESULT_SIDE0 : DFI_RESULT_SIDE1;
    }
    if (left1 == 0u) {
        return DFI_RESULT_SIDE0;
    }
    return left0 == 0u ? DFI_RESULT_SIDE1 : DFI_RESULT_NONE;
}

/* faintMessages and checkWin (sim/battle.ts:2535-2590, 404-415): the faints
 * of the action in order, then the win rule. */
static void dfi_process_faints(dfi_run *r)
{
    struct duoforge_battle *b = r->b;
    for (uint32_t i = 0u; i < r->faint_count; ++i) {
        const uint32_t flat = r->faint_queue[i];
        if (i >= r->faint_announced) {
            dfi_emit_plain(r, DUOFORGE_EVENT_FAINT, flat); /* [faint] */
        }
        dfi_tail_clear_occupant(b, flat); /* the POOL tail ends with the volatiles (decision 0015 section 7) */
        dfi_clear_volatile(dfi_pos(b, flat));
        /* clearVolatile ends with setSpecies, which sets pokemon.speed to the
         * raw Speed stat (sim/pokemon.ts:1418); a fainted Pokemon is not
         * updated again. */
        r->speed_seen[flat] = dfi_raw_speed_key(dfi_at(b, flat));
        r->last_fainted = flat;
    }
    const bool any = r->faint_count != 0u;
    r->faint_count = 0u;
    r->faint_announced = 0u;
    if (!any) {
        return;
    }
    const uint32_t result = dfi_win_result(b, r->last_fainted);
    if (result != DFI_RESULT_NONE) {
        b->result = (uint8_t)result;
        r->ended = true;
    }
}

/* The faintMessages after the hit loop (data/mods/champions/scripts.ts:546)
 * shows the faints so far; their processing stays at the end of the action
 * (dfi_process_faints), where the engine runs it for the whole action. With
 * the attacker at 0 HP (a Rocky Helmet) that faintMessages also checks the
 * win (sim/battle.ts:2593-2598): the result is shown here, before the rest
 * of the action, which the reference still runs and shows (a target's
 * Emergency Exit, :578-590). */
static void dfi_announce_faints(dfi_run *r, bool check_win)
{
    for (uint32_t i = r->faint_announced; i < r->faint_count; ++i) {
        dfi_emit_plain(r, DUOFORGE_EVENT_FAINT, r->faint_queue[i]); /* [faint] */
    }
    r->faint_announced = r->faint_count;
    if (check_win && r->faint_count != 0u) {
        const uint32_t result = dfi_win_result(r->b, r->faint_queue[r->faint_count - 1u]);
        if (result != DFI_RESULT_NONE) {
            duoforge_event e = dfi_event_make(DUOFORGE_EVENT_RESULT, DUOFORGE_NO_POSITION);
            e.detail = (uint8_t)result; /* wide-operands-reviewed: <= 3 */
            dfi_emit(r, &e); /* [win] */
            r->early_result = result;
        }
    }
}

/* Whether a faintMessages inside the current action already showed the
 * faint at `flat`; the reference processed it there, so from then on that
 * Pokemon is not active (sim/battle.ts:2566). */
static bool dfi_faint_shown(const dfi_run *r, uint32_t flat)
{
    for (uint32_t i = 0u; i < r->faint_announced; ++i) {
        if (r->faint_queue[i] == flat) {
            return true;
        }
    }
    return false;
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
    }
    if (((uint32_t)pos->flags & DFI_VOL_FLINCH) != 0u) {
        const duoforge_event e = dfi_ev(DUOFORGE_EVENT_CANT, user, DUOFORGE_CAUSE_FLINCH, 0u, DUOFORGE_NO_POSITION);
        dfi_emit(r, &e); /* [cant] flinch */
        return DUOFORGE_OK;
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
                if (dfi_focus_sash_saves(dfi_item_code(r->b, m), m, damage)) {
                    dfi_use_item(r, user);
                    damage = (uint32_t)m->hp - 1u;
                }
                return dfi_deal(r, user, damage, DUOFORGE_CAUSE_CONFUSION, 0u, DUOFORGE_NO_POSITION);
            }
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

/* Soak's onHit (data/moves.ts:17186-17208): a target that is already pure Water, or whose type cannot be set, gives
 * -fail|target (the move still animates) and null; otherwise target.setType('Water') and -start|target|typechange|Water.
 * setType refuses (without `enforce`) Arceus and Silvally (species numbers 493 and 773, sim/pokemon.ts:2113-2118; no
 * pool forme is one) and a Terastallized Pokemon (the format has no Terastallization). The type stays until the
 * occupant leaves, faints or Mega Evolves (dfi_tail_clear_occupant, dfi_run_mega). True when the type was set. */
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
    duoforge_event e = dfi_ev(DUOFORGE_EVENT_TYPE_CHANGE, flat, DUOFORGE_CAUSE_MOVE, move_id, DUOFORGE_NO_POSITION);
    e.detail = (uint8_t)DFI_TYPE_WATER; /* -start|target|typechange|Water */
    dfi_emit(r, &e);
    return true;
}

/* A status move that did something to a target ends the Champions hit
 * loop like a hit: its Update (data/mods/champions/scripts.ts:537), the
 * faint lines, then the Update after it (:574). A side or field move does
 * not reach the hit loop. */
static duoforge_status dfi_status_hit_end(dfi_run *r)
{
    const duoforge_status st = dfi_update(r);
    if (st != DUOFORGE_OK) {
        return st;
    }
    dfi_announce_faints(r, false); /* no status move in the data costs its user HP */
    return dfi_update(r);
}

/* Protect (data/moves.ts protect, data/conditions.ts stall): fails without a
 * draw when nobody acts after the user; with a stall counter it succeeds on
 * random(counter) == 0 (STALL) and otherwise loses the counter. */
static duoforge_status dfi_run_protect(dfi_run *r, uint32_t user)
{
    dfi_active_slot *pos = dfi_pos(r->b, user);
    if (!dfi_will_act(r->b)) {
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
            dfi_fail_still(r, user);
            return DUOFORGE_OK;
        }
    }
    pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_PROTECT); /* wide-operands-reviewed: < 256 */
    pos->stall_level = (uint8_t)(level < DFI_STALL_LEVEL_MAX ? level + 1u : level); /* wide-operands-reviewed */
    pos->stall_turns = (uint8_t)DFI_STALL_DURATION;
    dfi_emit_plain(r, DUOFORGE_EVENT_PROTECT, user); /* [-singleturn] Protect */
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
    return dfi_try_status(r, target, DFI_STATUS_PSN, user, DFI_NO_SOURCE_MOVE, false, 1u + DFI_ABILITY_POISONTOUCH);
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
    return DUOFORGE_OK;
}

/* Aurora Veil (POOL data, data/moves.ts:830-877; the side's turns are in the state tail). Its onTry (:840) fails the
 * move unless the weather is snow (Field.isWeather, sim/field.ts:118; nothing here suppresses a weather: Cloud Nine and
 * Air Lock are not marked): -fail with [still], as every failed side move. addSideCondition does not restart an active
 * condition, so a second one fails the same way. The duration is 5, or 8 when the user holds Light Clay
 * (durationCallback, :842-847); the line is -sidestart|side|move: Aurora Veil (:861-863). A side move does not reach the
 * Champions hit loop (no Update), as Wide Guard's does not. */
static duoforge_status dfi_run_aurora_veil(dfi_run *r, uint32_t user)
{
    struct duoforge_battle *b = r->b;
    const uint32_t side = user / 2u;
    uint8_t *turns = &b->tail.sides[side].aurora_veil_turns;
    if (b->weather != DFI_WEATHER_SNOW || *turns != 0u) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    const uint32_t duration = dfi_holds(b, dfi_at(b, user), DFI_ITEM_LIGHTCLAY) ? DFI_SCREEN_TURNS_MAX : 5u;
    *turns = (uint8_t)duration; /* <= 8 */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_SIDE_START, DUOFORGE_NO_POSITION);
    e.detail = (uint8_t)side;
    e.amount = (uint8_t)DUOFORGE_SIDE_AURORA_VEIL;
    dfi_emit(r, &e);
    return DUOFORGE_OK;
}

/* Nothing to hit: [notarget] on the last move line, then -fail. */
static duoforge_status dfi_no_target(dfi_run *r, uint32_t user)
{
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
 * marked member can have (duoforge.state.pool_g9 checks the predicate over every pool move against the pinned flag). */
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
    const uint32_t cls = dfi_pool_moves[tm->moves[slot].move_id].target_class;
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
 * it replaced by the Encored one (dfi_encore_replace), unless it holds a Mental Herb (the item is not in any set the
 * gate accepts: E_UNSUPPORTED). *did tells whether the lock started. */
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
    if (replace && dfi_holds(b, tm, DFI_ITEM_MENTALHERB)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    tail->encore_slot = (uint8_t)last;
    tail->encore_turns = queued == NULL ? DFI_ENCORE_TURNS + 1u : DFI_ENCORE_TURNS; /* 4 or 3: fits the byte */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_VOLATILE_START, flat);
    e.detail = (uint8_t)DUOFORGE_VOLATILE_ENCORE;
    dfi_emit(r, &e);
    *did = true;
    if (replace) {
        return dfi_encore_replace(r, flat, slot);
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
    if (dfi_ability(r->b, dfi_at(r->b, ally), DFI_ABILITY_GOODASGOLD)) {
        dfi_immune(r, ally, 1u + DFI_ABILITY_GOODASGOLD); /* the move steps stop: no Update */
        return DUOFORGE_OK;
    }
    if (dfi_boost(r, ally, md->boosts, user, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_PRIMARY))) {
        return dfi_status_hit_end(r);
    }
    return DUOFORGE_OK; /* nothing changed: the hit loop stops */
}

/* Follow Me (Team C, data/moves.ts:6039-6074). Its onTry needs two active
 * Pokemon per side (activePerHalf > 1), which doubles always has; its target
 * is the user, so Psychic Terrain and Protect never stop it. The volatile
 * lasts this turn: [-singleturn] user|move: Follow Me. The user cannot hold
 * it already: one action per turn, and the residual ends it. */
static duoforge_status dfi_run_follow_me(dfi_run *r, uint32_t user)
{
    dfi_active_slot *pos = dfi_pos(r->b, user);
    if (((uint32_t)pos->flags & DFI_VOL_FOLLOW_ME) != 0u) {
        return DUOFORGE_E_INVARIANT;
    }
    pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_FOLLOW_ME); /* wide-operands-reviewed: < 256 */
    duoforge_event e = dfi_ev(DUOFORGE_EVENT_SINGLE_TURN, user, DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION);
    e.id = (uint16_t)DFI_MOVE_FOLLOWME;
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
static duoforge_status dfi_run_heal_move(dfi_run *r, uint32_t user, uint32_t move_id)
{
    dfi_member *m = dfi_at(r->b, user);
    if (m->hp >= m->hp_max) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    const uint32_t num = dfi_pool_move_heal[move_id][0];
    const uint32_t den = dfi_pool_move_heal[move_id][1];
    uint32_t amount = ((uint32_t)m->hp_max * num * 2u + den) / (2u * den); /* Math.round(hp_max * num / den) */
    amount = amount < 1u ? 1u : amount;
    dfi_heal(r, user, amount, DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION);
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
    /* getTarget('recharge', no location) has no target class and takes getRandomTarget: a random foe (one draw with two
     * foes standing), before OverrideAction and BeforeMove; it decides nothing. */
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
    return st != DUOFORGE_OK ? st : (can ? DUOFORGE_E_INVARIANT : DUOFORGE_OK);
}

/* runMove and useMove for one move action (sim/battle-actions.ts:210-548,
 * the hit steps at 550-620 and the Champions hit loop). */
static duoforge_status dfi_run_move(dfi_run *r, const dfi_queue_record *q, bool *ran)
{
    struct duoforge_battle *b = r->b;
    const uint32_t side = q->side;
    const uint32_t user = side * 2u + (uint32_t)q->slot;
    dfi_active_slot *pos = dfi_pos(b, user);
    dfi_member *m = dfi_at(b, user);
    *ran = false;
    /* runAction: an inactive or fainted actor does nothing (no epilogue). */
    if (m == NULL || m->hp == 0u || pos->activation_id != q->activation_id) {
        return DUOFORGE_OK;
    }
    if (!dfi_move_slot_ok(m, q->move_slot)) {
        return DUOFORGE_E_INVARIANT;
    }
    /* A choice-locked actor queues only its locked move or Struggle (the
     * request offers nothing else), so choicelock's onBeforeMove, which
     * would fail another move (data/conditions.ts), never runs; a decoded
     * state that queues another move fails loudly (Team C). */
    if (((uint32_t)pos->flags & DFI_VOL_CHOICE_LOCK) != 0u && q->move_slot != DUOFORGE_MOVE_SLOT_STRUGGLE &&
        q->move_slot != DUOFORGE_MOVE_SLOT_RECHARGE && q->move_slot + 1u != pos->locked_move) {
        return DUOFORGE_E_INVARIANT;
    }
    *ran = true;
    r->move_used = false;
    if (pos->move_actions < UINT8_MAX) {
        pos->move_actions = (uint8_t)((uint32_t)pos->move_actions + 1u); /* wide-operands-reviewed */
    }
    if (q->move_slot == DUOFORGE_MOVE_SLOT_RECHARGE) {
        return dfi_run_recharge(r, user);
    }
    const uint32_t move_id = dfi_move_of(m, q->move_slot);
    const dfi_move_data *md = &dfi_pool_moves[move_id];
    if (move_id != DFI_MOVE_STRUGGLE && dfi_support.moves[move_id] == 0u) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    /* getTarget and getMoveTargets (the spread classes need no draw): the
     * reference picks a random target in runMove, before BeforeMove, so the
     * draw happens even when the Pokemon then cannot move. */
    uint32_t targets[DFI_POSITIONS] = {0};
    uint32_t count = 0u;
    duoforge_status st = dfi_move_targets(r, user, md->target_class, q->target, targets, &count);
    if (st != DUOFORGE_OK) {
        return st;
    }
    /* runMove's target, which AfterMove gets: getTarget's result, before
     * any redirection; a spread move's is a random foe that only labels
     * its line, which the engine does not draw. */
    r->move_target = md->target_class == DUOFORGE_TARGET_CLASS_ALL_ADJACENT_FOES ? DFI_MOVE_TARGET_SPREAD
                     : count != 0u                                              ? targets[0]
                                                                                : DFI_MOVE_TARGET_NONE;
    /* BeforeMove: a Pokemon that cannot move uses no PP and shows nothing;
     * on the locked turn of a two-turn move its charge ends (twoturnmove's
     * onMoveAborted). */
    const bool locked = pos->charge_turns != 0u;
    bool can = false;
    st = dfi_before_move(r, user, move_id, md, &can);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (!can) {
        if (locked) {
            pos->charge_turns = 0u;
            pos->locked_target = 0u;
            if (((uint32_t)pos->flags & DFI_VOL_CHOICE_LOCK) == 0u) {
                pos->locked_move = 0u; /* a choice lock outlives the charge */
            }
        }
        return DUOFORGE_OK;
    }
    /* deductPP; a locked move uses none. The opponent counts the use from
     * the move line (dfi_events_fold_knowledge). */
    if (q->move_slot < DUOFORGE_MAX_MOVE_SLOTS && !locked) {
        dfi_move_slot *slot = &m->moves[q->move_slot];
        if (slot->pp == 0u) {
            return DUOFORGE_OK; /* "cant nopp"; the domain never offers it */
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
    /* ModifyMove's change of the target class (Expanding Force in Psychic Terrain): useMoveInner takes the target again
     * with the new class (getRandomTarget, whose draw only labels the move line, as for any spread move), and
     * getMoveTargets then collects the foes. runMove's own target (r->move_target, AfterMove's) stays the old one. */
    const uint32_t target_class = dfi_effective_target_class(b, m, md);
    if (target_class != md->target_class) {
        st = dfi_move_targets(r, user, target_class, q->target, targets, &count);
        if (st != DUOFORGE_OK) {
            return st;
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
        const uint32_t chosen = q->target;
        aimed = (chosen < DFI_POSITIONS && chosen / 2u == side && dfi_at(b, chosen) != NULL) ? chosen : (1u - side) * 2u;
        aimed = dfi_at(b, aimed) != NULL ? aimed : DUOFORGE_NO_POSITION;
    }
    /* The move line; a locked turn says [from] lockedmove. Later lines
     * amend it. */
    {
        duoforge_event e = dfi_event_make(DUOFORGE_EVENT_MOVE, user);
        e.id = (uint16_t)move_id;
        /* A fainted Pokemon is printed without its slot ("p1: Name"): with
         * nothing to hit, the line names no position. */
        e.other = (uint8_t)(count == 1u ? aimed : DUOFORGE_NO_POSITION); /* wide-operands-reviewed: < 256 */
        const uint32_t spread_flag = count > 1u ? DUOFORGE_EVENT_FLAG_SPREAD : 0u;
        const uint32_t locked_flag = locked ? DUOFORGE_EVENT_FLAG_LOCKED : 0u;
        e.flags = (uint8_t)(spread_flag | locked_flag); /* wide-operands-reviewed: flags < 256 */
        r->last_move = r->events != NULL ? r->events->count : UINT32_MAX;
        dfi_emit(r, &e);
    }
    if (aimed == DUOFORGE_NO_POSITION && count == 0u) {
        return dfi_no_target(r, user); /* no target at all: before getMoveTargets */
    }
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
    const bool single = count <= 1u && (target_class == DUOFORGE_TARGET_CLASS_NORMAL ||
                                        target_class == DUOFORGE_TARGET_CLASS_ANY ||
                                        target_class == DUOFORGE_TARGET_CLASS_ADJACENT_FOE ||
                                        target_class == DFI_TARGET_CLASS_RANDOM_NORMAL);
    uint32_t follow = DFI_POSITIONS;
    for (uint32_t slot = 0u; single && slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
        const uint32_t flat = (1u - side) * 2u + slot;
        if (dfi_alive(b, flat) && ((uint32_t)dfi_pos(b, flat)->flags & DFI_VOL_FOLLOW_ME) != 0u) {
            if (follow != DFI_POSITIONS) {
                return DUOFORGE_E_UNSUPPORTED;
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
    if (follow == DFI_POSITIONS && md->type == DFI_TYPE_ELECTRIC && single) {
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
    /* Electro Shot's onTryMove (a singleEvent before the TryMove event):
     * on the charge turn Special Attack +1, then in rain the attack goes on,
     * otherwise twoturnmove locks the move and the chosen target for the
     * next turn (duration 2). On the locked turn the attack goes on. */
    if (md->special == DFI_SPECIAL_ELECTRO_SHOT && !locked) {
        static const uint8_t spa_up[DFI_STAT_STAGE_COUNT] = {6u, 6u, 7u, 6u, 6u, 6u, 6u};
        duoforge_event *mv = dfi_last_move(r);
        if (mv != NULL) {
            mv->flags = (uint8_t)((uint32_t)mv->flags | DUOFORGE_EVENT_FLAG_STILL); /* wide-operands-reviewed: flags < 256 */
            mv->other = (uint8_t)DUOFORGE_NO_POSITION; /* "the target should never be known" */
        }
        duoforge_event prep = dfi_event_make(DUOFORGE_EVENT_PREPARE, user);
        prep.id = (uint16_t)move_id;
        dfi_emit(r, &prep);
        dfi_boost(r, user, spa_up, DFI_POSITIONS, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_PRIMARY));
        if (b->weather == DFI_WEATHER_RAIN) {
            /* addMove('-anim'): from now on the last move line, which later
             * attributes ([miss], [notarget]) amend. */
            duoforge_event anim = dfi_event_make(DUOFORGE_EVENT_ANIMATION, user);
            anim.id = (uint16_t)move_id;
            anim.other = (uint8_t)(count == 1u ? aimed : DUOFORGE_NO_POSITION); /* wide-operands-reviewed: < 256 */
            r->last_move = r->events != NULL ? r->events->count : UINT32_MAX;
            dfi_emit(r, &anim);
        }
        if (b->weather != DFI_WEATHER_RAIN) {
            pos->charge_turns = (uint8_t)DFI_CHARGE_TURNS_MAX;
            pos->locked_move = (uint8_t)((uint32_t)q->move_slot + 1u); /* wide-operands-reviewed: <= 4 */
            pos->locked_target = q->target;
            return DUOFORGE_OK;
        }
    }
    /* TryMove: Armor Tail on a standing foe stops a move with positive
     * priority aimed at the holder's side (with nothing to hit, the aimed
     * Pokemon is fainted: no standing holder is its ally). */
    if (count != 0u) {
        const uint32_t priority = dfi_move_priority(b, m, md);
        aimed = targets[count - 1u];
        if (priority > DFI_PRIORITY_BIAS && aimed / 2u != side && md->target_class != DUOFORGE_TARGET_CLASS_SELF &&
            md->target_class != DUOFORGE_TARGET_CLASS_ALLY_SIDE && md->target_class != DUOFORGE_TARGET_CLASS_ALL) {
            for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
                const dfi_member *holder = dfi_at(b, (1u - side) * 2u + slot);
                if (holder != NULL && holder->hp != 0u && dfi_ability(r->b, holder, DFI_ABILITY_ARMORTAIL)) {
                    /* [still], then cant|holder|ability: Armor Tail|move|[of] user */
                    dfi_still(r);
                    duoforge_event e = dfi_ev(DUOFORGE_EVENT_CANT, (1u - side) * 2u + slot, DUOFORGE_CAUSE_ABILITY,
                                              1u + DFI_ABILITY_ARMORTAIL, user);
                    e.id = (uint16_t)move_id;
                    dfi_emit(r, &e);
                    return DUOFORGE_OK;
                }
            }
        }
    }
    if (count == 0u) {
        return dfi_no_target(r, user); /* after TryMove (sim/battle-actions.ts:509-513) */
    }
    if (md->special == DFI_SPECIAL_HELPING_HAND) {
        return dfi_run_helping_hand(r, user, targets[0]);
    }
    if (md->special == DFI_SPECIAL_PROTECT) {
        return dfi_run_protect(r, user);
    }
    if (md->special == DFI_SPECIAL_WIDE_GUARD) {
        return dfi_run_wide_guard(r, user);
    }
    if (md->special == DFI_SPECIAL_AURORA_VEIL) {
        return dfi_run_aurora_veil(r, user);
    }
    if (md->special == DFI_SPECIAL_FOLLOW_ME) {
        return dfi_run_follow_me(r, user);
    }
    const bool status_move = md->category == DFI_CATEGORY_STATUS;
    if (status_move && md->boost_role == DFI_BOOST_ROLE_PRIMARY_ALLY) {
        return dfi_run_coaching(r, user, targets[0], md);
    }
    if (status_move && md->side_condition != 0u) {
        /* addSideCondition: an active condition is not restarted (the move
         * fails); Tailwind lasts 4 turns, the screens 5, or 8 with Light Clay. */
        dfi_side *us = &b->sides[side];
        uint8_t *turns = md->side_condition == DFI_SIDE_CONDITION_TAILWIND  ? &us->tailwind_turns
                         : md->side_condition == DFI_SIDE_CONDITION_REFLECT ? &us->reflect_turns
                                                                            : &us->light_screen_turns;
        if (md->side_condition > DFI_SIDE_CONDITION_LIGHT_SCREEN) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        if (*turns != 0u) {
            dfi_fail_still(r, user);
            return DUOFORGE_OK;
        }
        const uint32_t screen = dfi_holds(r->b, m, DFI_ITEM_LIGHTCLAY) ? DFI_SCREEN_TURNS_MAX : 5u;
        const uint32_t duration = md->side_condition == DFI_SIDE_CONDITION_TAILWIND ? DFI_TAILWIND_TURNS_MAX : screen;
        *turns = (uint8_t)duration; /* <= 8 */
        duoforge_event e = dfi_event_make(DUOFORGE_EVENT_SIDE_START, DUOFORGE_NO_POSITION);
        e.detail = (uint8_t)side;
        e.amount = (uint8_t)md->side_condition; /* DUOFORGE_SIDE_* */
        dfi_emit(r, &e);
        return DUOFORGE_OK;
    }
    if (status_move && (md->special == DFI_SPECIAL_SANDSTORM || md->special == DFI_SPECIAL_SNOWSCAPE)) {
        /* Sandstorm and Snowscape (moveHit, sim/battle-actions.ts:1248-1251): Field.setWeather (sim/field.ts:39-82)
         * fails when the same weather is up (the move fails), and otherwise replaces the weather for 5 turns
         * (the rock items that make it 8 are not marked) with -weather|X, no [from]. */
        const uint32_t w = md->special == DFI_SPECIAL_SANDSTORM ? DFI_WEATHER_SAND : DFI_WEATHER_SNOW;
        if (b->weather == w) {
            dfi_fail_still(r, user);
            return DUOFORGE_OK;
        }
        b->weather = (uint8_t)w;
        b->weather_turns = (uint8_t)DFI_FIELD_TURNS_MAX;
        duoforge_event e = dfi_event_make(DUOFORGE_EVENT_WEATHER, DUOFORGE_NO_POSITION);
        e.detail = (uint8_t)w; /* DUOFORGE_WEATHER_* */
        dfi_emit(r, &e);
        return DUOFORGE_OK;
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
        return DUOFORGE_OK;
    }
    if (status_move && md->primary_status == DFI_STATUS_NONE && md->special != DFI_SPECIAL_PARTING_SHOT &&
        md->special != DFI_SPECIAL_SOAK && md->special != DFI_SPECIAL_ENCORE) {
        if (dfi_pool_move_heal[move_id][1] != 0u) {
            return dfi_run_heal_move(r, user, move_id);
        }
        if (md->boost_role != DFI_BOOST_ROLE_PRIMARY_SELF || md->target_class != DUOFORGE_TARGET_CLASS_SELF) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        dfi_boost_effect own = dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_PRIMARY);
        own.negatives_first = md->special == DFI_SPECIAL_SHELL_SMASH;
        if (dfi_boost(r, user, md->boosts, DFI_POSITIONS, own)) {
            return dfi_status_hit_end(r);
        }
        return DUOFORGE_OK; /* nothing changed: the hit loop stops */
    }
    /* A handler this build does not have fails explicitly; the Team C
     * specials of later steps are also kept out by the support manifest. */
    if (md->special > DFI_SPECIAL_STRUGGLE && md->special != DFI_SPECIAL_DARKEST_LARIAT &&
        md->special != DFI_SPECIAL_LAST_RESPECTS && md->special != DFI_SPECIAL_SUCKER_PUNCH &&
        md->special != DFI_SPECIAL_FIRST_IMPRESSION && md->special != DFI_SPECIAL_LOW_KICK &&
        md->special != DFI_SPECIAL_SOAK && md->special != DFI_SPECIAL_ENCORE &&
        md->special != DFI_SPECIAL_KNOCK_OFF && md->special != DFI_SPECIAL_EXPANDING_FORCE &&
        md->special != DFI_SPECIAL_GLAIVE_RUSH && md->special != DFI_SPECIAL_ACROBATICS &&
        md->special != DFI_SPECIAL_BLIZZARD && md->special != DFI_SPECIAL_FEINT) {
        return DUOFORGE_E_INVARIANT;
    }
    /* Fake Out's and First Impression's onTry (in trySpreadMoveHit, after
     * TryMove): only on the first move action since it entered. */
    if (dfi_move_first_turn_only(md) && pos->move_actions > 1u) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
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
            return DUOFORGE_OK;
        }
    }
    /* Hurricane never misses in rain and has 50 accuracy under sun. */
    uint32_t base_accuracy = md->accuracy;
    if (md->special == DFI_SPECIAL_HURRICANE) {
        if (b->weather == DFI_WEATHER_RAIN) {
            base_accuracy = 0u;
        } else if (b->weather == DFI_WEATHER_SUN) {
            base_accuracy = 50u;
        }
    }
    /* Blizzard's onModifyMove (step G28, data/moves.ts:1491-1510): in snow it never misses. */
    if (md->special == DFI_SPECIAL_BLIZZARD && b->weather == DFI_WEATHER_SNOW) {
        base_accuracy = 0u;
    }
    /* Struggle is typeless; Weather Ball turns Water in rain, Fire under sun
     * (its onModifyType, before the hit steps). */
    uint32_t move_type = md->special == DFI_SPECIAL_STRUGGLE ? DFI_CLOSURE_NONE : md->type;
    /* An -ate ability (the ATE family, decision 0015): onModifyType
     * (priority -1) turns a Normal move into its type before immunity and
     * STAB; Weather Ball is in its noModifyType list and Struggle is
     * typeless by then (data/abilities.ts). */
    move_type = dfi_ate_type_fam(dfi_ability_family_now(r->b, m), md, move_type);
    if (md->special == DFI_SPECIAL_WEATHER_BALL && b->weather == DFI_WEATHER_RAIN) {
        move_type = DFI_TYPE_WATER;
    } else if (md->special == DFI_SPECIAL_WEATHER_BALL && b->weather == DFI_WEATHER_SUN) {
        move_type = DFI_TYPE_FIRE;
    } else if (md->special == DFI_SPECIAL_WEATHER_BALL && b->weather == DFI_WEATHER_SAND) {
        move_type = DFI_TYPE_ROCK; /* data/moves.ts:20711-20713 */
    } else if (md->special == DFI_SPECIAL_WEATHER_BALL && b->weather == DFI_WEATHER_SNOW) {
        move_type = DFI_TYPE_ICE; /* data/moves.ts:20714-20717 (snowscape) */
    }
    const bool spread = count > 1u;
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
        return DUOFORGE_E_UNSUPPORTED;
    }
    bool hit[DFI_POSITIONS] = {false, false, false, false};
    /* Wide Guard's onTryHit (priority 4, data/moves.ts:20828-20844) runs for every target before Protect's (3): it
     * stops a move whose target class is allAdjacentFoes (or allAdjacent, which the tables do not have yet) and that
     * has the protect flag (checkMoveBypassesProtect, sim/battle.ts:1300-1309), whatever its category and however many
     * targets are left, one -activate line per guarded target. A guarded target that also protects gets this line
     * only (its Protect handler is skipped). */
    bool guarded[DFI_POSITIONS] = {false, false, false, false};
    if (target_class == DUOFORGE_TARGET_CLASS_ALL_ADJACENT_FOES && (md->flags & DFI_MOVE_FLAG_PROTECT) != 0u) {
        for (uint32_t i = 0u; i < count; ++i) {
            const uint32_t t = targets[i];
            if (b->tail.sides[t / 2u].wide_guard != 0u) {
                guarded[i] = true;
                duoforge_event e = dfi_event_make(DUOFORGE_EVENT_BLOCKED, t);
                e.detail = (uint8_t)DUOFORGE_BLOCK_WIDE_GUARD; /* [-activate] move: Wide Guard */
                dfi_emit(r, &e);
            }
        }
    }
    for (uint32_t i = 0u; i < count; ++i) {
        const uint32_t t = targets[i];
        const dfi_active_slot *tp = dfi_pos(b, t);
        if (guarded[i]) {
            continue;
        }
        if (psychic_block && t / 2u != side && dfi_grounded(b, dfi_at(b, t))) {
            duoforge_event e = dfi_event_make(DUOFORGE_EVENT_BLOCKED, t);
            e.detail = (uint8_t)DUOFORGE_FIELD_PSYCHIC_TERRAIN; /* [-activate] move: Psychic Terrain */
            dfi_emit(r, &e);
            continue;
        }
        hit[i] = !((((uint32_t)tp->flags & DFI_VOL_PROTECT) != 0u) && ((md->flags & DFI_MOVE_FLAG_PROTECT) != 0u));
        if (!hit[i]) {
            dfi_emit_plain(r, DUOFORGE_EVENT_BLOCKED, t); /* [-activate] move: Protect */
        }
    }
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
        }
    }
    for (uint32_t i = 0u; i < count && !status_move; ++i) {
        if (hit[i] && dfi_type_immune(b, dfi_at(b, targets[i]), move_type)) {
            hit[i] = false; /* a status move ignores type immunity */
            dfi_immune(r, targets[i], 0u);
        }
    }
    /* hitStepTryImmunity: a Prankster-boosted status move fails on a Dark
     * foe. */
    for (uint32_t i = 0u; i < count && status_move && dfi_ability(r->b, m, DFI_ABILITY_PRANKSTER); ++i) {
        if (hit[i] && targets[i] / 2u != side && dfi_has_type(b, dfi_at(b, targets[i]), DFI_TYPE_DARK)) {
            hit[i] = false;
            dfi_immune(r, targets[i], 0u);
        }
    }
    if (base_accuracy != 0u) {
        for (uint32_t i = 0u; i < count; ++i) {
            if (!hit[i]) {
                continue;
            }
            /* No Guard on the user or the target: the move cannot miss. */
            if (dfi_ability(r->b, m, DFI_ABILITY_NOGUARD) || dfi_ability(r->b, dfi_at(b, targets[i]), DFI_ABILITY_NOGUARD)) {
                continue;
            }
            /* Glaive Rush's onAccuracy on the target (data/moves.ts:6647-6678): the move cannot miss, no draw
             * (sim/battle-actions.ts:736-738). */
            if (b->tail.sides[targets[i] / 2u].positions[targets[i] % 2u].glaive_rush != 0u) {
                continue;
            }
            /* The user's accuracy stage minus the target's evasion, clamped. */
            const uint32_t acc = pos->stages[DFI_STAGE_ACCURACY];
            /* Darkest Lariat (Team C): ignoreEvasion (sim/battle-actions.ts:719). */
            const uint32_t eva = md->special == DFI_SPECIAL_DARKEST_LARIAT
                                     ? DFI_BIAS6
                                     : (uint32_t)dfi_pos(b, targets[i])->stages[DFI_STAGE_EVASION];
            uint32_t combined = acc + 12u - eva; /* 12 means 0 */
            combined = combined < 6u ? 6u : (combined > 18u ? 18u : combined);
            uint32_t accuracy = 0u;
            if (!dfi_stage_accuracy(base_accuracy, combined - 6u, &accuracy)) {
                return DUOFORGE_E_INVARIANT;
            }
            st = dfi_draw_chance(r->draws, DFI_SITE_ACCURACY, accuracy, 100u, &hit[i]);
            if (st != DUOFORGE_OK) {
                return st;
            }
            if (!hit[i]) {
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
    /* hitStepBreakProtect, after the accuracy check (sim/battle-actions.ts:568-571): Feint removes the protections of every
     * target that is still hit. */
    if (md->special == DFI_SPECIAL_FEINT) {
        for (uint32_t i = 0u; i < count; ++i) {
            if (hit[i]) {
                dfi_break_protect(r, targets[i], move_id);
            }
        }
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
                if (dfi_boost(r, targets[i], drop, user, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_PRIMARY)) &&
                    m->hp != 0u && dfi_can_switch(b, side)) {
                    pos->switch_flag = (uint8_t)DFI_SWITCH_MOVE;
                }
                did = true;
                continue;
            }
            if (md->special == DFI_SPECIAL_SOAK) {
                did = dfi_soak(r, targets[i], move_id) || did;
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
            const uint32_t before = dfi_at(b, targets[i])->status;
            st = dfi_try_status(r, targets[i], md->primary_status, user, move_id, true, 0u);
            if (st != DUOFORGE_OK) {
                return st;
            }
            did = did || dfi_at(b, targets[i])->status != before;
        }
        return did ? dfi_status_hit_end(r) : DUOFORGE_OK;
    }
    /* getSpreadDamage: every target's damage (crit, roll), then spreadDamage. */
    uint32_t damage[DFI_POSITIONS] = {0u, 0u, 0u, 0u};
    for (uint32_t i = 0u; i < count; ++i) {
        if (hit[i]) {
            st = dfi_get_damage(r, user, targets[i], md, move_type, spread, &damage[i]);
            if (st != DUOFORGE_OK) {
                return st;
            }
        }
    }
    /* spreadDamage, per target: the damage, then a drain heals the user by
     * round(dealt * drain) (sim/battle.ts:2170-2173). The HP actually lost
     * adds up to the move's total damage. */
    uint32_t total = 0u;
    uint32_t hp_before[DFI_POSITIONS] = {0u, 0u, 0u, 0u};
    for (uint32_t i = 0u; i < count; ++i) {
        if (hit[i]) {
            const uint32_t before = dfi_at(b, targets[i])->hp;
            hp_before[i] = before;
            /* Focus Sash (combat/item_family.h): a move hit that would take
             * all of a full-HP holder's HP uses the item up ([-enditem],
             * before the [-damage] line) and leaves 1 HP. Each target decides
             * for itself. Only the damage of a Move comes here (and the
             * confusion hit, below): recoil, Life Orb, Rocky Helmet, weather
             * and status damage are not Move effects and go through dfi_deal
             * on their own. */
            const dfi_member *tm = dfi_at(b, targets[i]);
            if (dfi_focus_sash_saves(dfi_item_code(b, tm), tm, damage[i])) {
                dfi_use_item(r, targets[i]);
                damage[i] = (uint32_t)tm->hp - 1u;
            }
            st = dfi_deal(r, targets[i], damage[i], DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION);
            if (st != DUOFORGE_OK) {
                return st;
            }
            const uint32_t dealt = before - (uint32_t)dfi_at(b, targets[i])->hp;
            total += dealt;
            if (md->drain[1] != 0u && dealt != 0u) {
                const uint32_t num = dealt * md->drain[0] * 2u + md->drain[1];
                dfi_heal(r, user, num / (2u * md->drain[1]), DUOFORGE_CAUSE_DRAIN, 0u, targets[i]); /* round */
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
            return DUOFORGE_E_UNSUPPORTED;
        }
        bool hit_any = false;
        for (uint32_t i = 0u; i < count; ++i) {
            hit_any = hit_any || hit[i];
        }
        if (hit_any && m->hp != 0u && dfi_can_switch(b, side)) {
            pos->switch_flag = pivot->flag;
        }
    }
    /* selfDrops: once, after the first target that was hit, a roll of
     * random(100) that always passes (no chance), then the user's own stat
     * changes (Close Combat, Make It Rain). */
    if (md->boost_role == DFI_BOOST_ROLE_SELF_AFTER_HIT) {
        bool hit_any = false;
        for (uint32_t i = 0u; i < count; ++i) {
            hit_any = hit_any || hit[i];
        }
        if (hit_any) {
            uint32_t roll = 0u;
            st = dfi_draw(r->draws, DFI_SITE_SECONDARY, 0u, 100u, &roll);
            if (st != DUOFORGE_OK) {
                return st;
            }
            dfi_boost(r, user, md->boosts, DFI_POSITIONS, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_SELF));
        }
    }
    /* A recharge move (flags.recharge, self: {volatileStatus: 'mustrecharge'}; step G17): selfDrops (sim/battle-actions.ts:
     * 1096, 1317-1335) puts the volatile on the user for every target that was not ruled out (a miss, a Protect or an
     * immunity make it `false`; a knocked-out target is still a hit), once: a second addVolatile changes nothing.
     * -mustrecharge|user (data/conditions.ts:374-376, onStart). */
    if ((dfi_pool_move_flags2[move_id] & DFI_MOVE_FLAG2_RECHARGE) != 0u && move_id != DFI_MOVE_STRUGGLE) {
        bool hit_any = false;
        for (uint32_t i = 0u; i < count; ++i) {
            hit_any = hit_any || hit[i];
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
     * (data/moves.ts:6647-6678; the public view infers it from the move line, decision 0018 section 6.1). */
    if (md->special == DFI_SPECIAL_GLAIVE_RUSH) {
        bool hit_any = false;
        for (uint32_t i = 0u; i < count; ++i) {
            hit_any = hit_any || hit[i];
        }
        if (hit_any) {
            b->tail.sides[side].positions[q->slot].glaive_rush = 1u;
        }
    }
    /* secondaries: one SECONDARY draw per hit target, even at 100; a status
     * or volatile reaches only a standing target. */
    if (md->sec_chance != 0u) {
        for (uint32_t i = 0u; i < count; ++i) {
            if (!hit[i]) {
                continue;
            }
            uint32_t roll = 0u;
            st = dfi_draw(r->draws, DFI_SITE_SECONDARY, 0u, 100u, &roll);
            if (st != DUOFORGE_OK) {
                return st;
            }
            if (roll >= md->sec_chance) {
                continue;
            }
            if (md->sec_kind == DFI_SECONDARY_BOOST) {
                dfi_boost(r, targets[i], md->boosts, user, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_SECONDARY));
            } else if (md->sec_kind == DFI_SECONDARY_STATUS) {
                st = dfi_try_status(r, targets[i], md->sec_param, user, move_id, false, 0u);
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
                    st = dfi_try_status(r, targets[i], pick[v], user, DFI_NO_SOURCE_MOVE, false, 0u);
                }
            } else {
                st = DUOFORGE_E_UNSUPPORTED;
            }
            if (st != DUOFORGE_OK) {
                return st;
            }
        }
        if (md->boost_role == DFI_BOOST_ROLE_SELF_AFTER_HIT) {
            return DUOFORGE_E_UNSUPPORTED; /* no closure move has both */
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
                          targets[i]);
            if (st != DUOFORGE_OK) {
                return st;
            }
        }
    }
    for (uint32_t i = 0u; i < count; ++i) {
        if (hit[i] && (md->flags & DFI_MOVE_FLAG_CONTACT) != 0u &&
            dfi_holds(r->b, dfi_at(b, targets[i]), DFI_ITEM_ROCKYHELMET)) {
            const uint32_t helmet = (uint32_t)m->hp_max / 6u;
            st = dfi_deal(r, user, helmet == 0u ? 1u : helmet, DUOFORGE_CAUSE_ITEM, 1u + DFI_ITEM_ROCKYHELMET,
                          targets[i]);
            if (st != DUOFORGE_OK) {
                return st;
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
            /* The unordered handlers of a target that is down do nothing, except the attacker's Poison Touch: it
             * draws its roll (the handler runs, trySetStatus then fails). */
            st = dfi_poison_touch(r, user, targets[i], md);
            if (st != DUOFORGE_OK) {
                return st;
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
        }
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
        /* The attacker's Poison Touch comes after the target's own handlers (its onSourceDamagingHit is appended
         * after them, sim/battle.ts:1035-1063, and the sort is stable). */
        st = dfi_poison_touch(r, user, targets[i], md);
        if (st != DUOFORGE_OK) {
            return st;
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
    /* The attacker's own Emergency Exit when DamagingHit (Rocky Helmet) took
     * it to half (data/mods/champions/scripts.ts:406, 419-420). */
    dfi_emergency_exit(r, user, user_before_hit);
    bool any = false;
    for (uint32_t i = 0u; i < count; ++i) {
        any = any || hit[i];
    }
    /* The hit loop's Update (sim/battle-actions.ts:967), then its
     * faintMessages. */
    if (any) {
        st = dfi_update(r);
        if (st != DUOFORGE_OK) {
            return st;
        }
        dfi_announce_faints(r, m->hp == 0u);
    }
    /* applyRecoilDamage after the hit loop: Struggle round(maxHP / 4), a
     * recoil move round(total * a / b), at least 1; then Update again
     * (:1003). */
    if (any) {
        uint32_t recoil = 0u;
        if ((md->flags & DFI_MOVE_FLAG_STRUGGLE_RECOIL) != 0u) {
            recoil = ((uint32_t)m->hp_max + 2u) / 4u; /* Math.round(hp_max / 4) */
            recoil = recoil < 1u ? 1u : recoil;
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
            st = dfi_deal(r, user, recoil, DUOFORGE_CAUSE_RECOIL, 0u, DUOFORGE_NO_POSITION);
            if (st != DUOFORGE_OK) {
                return st;
            }
            dfi_emergency_exit(r, user, user_before); /* inside applyRecoilDamage */
        }
        st = dfi_update(r);
        if (st != DUOFORGE_OK) {
            return st;
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
                }
            }
        }
        /* After the secondaries of the hit loop: a target that fell to half
         * HP (sim/battle-actions.ts:1005-1017). */
        for (uint32_t i = 0u; i < count; ++i) {
            if (hit[i]) {
                dfi_emergency_exit(r, targets[i], hp_before[i]);
            }
        }
    }
    /* AfterMoveSecondarySelf: Life Orb takes a tenth of the holder's HP
     * (at least 1) after a damaging move that hit something. */
    if (any && dfi_holds(r->b, m, DFI_ITEM_LIFEORB)) {
        const uint32_t recoil = (uint32_t)m->hp_max / 10u;
        const uint32_t user_before = m->hp;
        st = dfi_deal(r, user, recoil == 0u ? 1u : recoil, DUOFORGE_CAUSE_ITEM, 1u + DFI_ITEM_LIFEORB,
                      DUOFORGE_NO_POSITION);
        if (st != DUOFORGE_OK) {
            return st;
        }
        dfi_emergency_exit(r, user, user_before); /* after AfterMoveSecondarySelf */
    }
    return DUOFORGE_OK;
}

/* ---------------------------------------------------------------- switches */

/* insertChoice (sim/battle-queue.ts:369-401) of the entry action of the
 * Pokemon that came in: before the first action it sorts ahead of or ties
 * with. Among tied entries the reference draws a position; the engine does
 * not, because entries queued together run as one batch, ordered by Speed
 * in dfi_run_entries (decision 0006 section 5.1, converter rule INSERT_TIE). */
static duoforge_status dfi_insert_run_switch(dfi_run *r, uint32_t side, uint32_t slot, uint32_t activation)
{
    struct duoforge_battle *b = r->b;
    if (b->queue_len >= DFI_QUEUE_CAPACITY) {
        return DUOFORGE_E_INVARIANT;
    }
    const dfi_queue_record rec = {activation, (uint8_t)DFI_Q_RUN_SWITCH, (uint8_t)side, (uint8_t)slot, 0u, 0u, 0u};
    dfi_key key;
    duoforge_status st = dfi_update_position_speed(r, side * 2u + slot);
    if (st != DUOFORGE_OK) {
        return st;
    }
    st = dfi_key_of(r, &rec, &key);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const uint32_t n = b->queue_len;
    uint32_t index = n;
    for (uint32_t i = 0u; i < n; ++i) {
        dfi_key other;
        st = dfi_key_of(r, &b->queue[i], &other);
        if (st != DUOFORGE_OK) {
            return st;
        }
        if (dfi_compare(&key, &other) != 2u) {
            index = i; /* the first action it sorts ahead of or ties with */
            break;
        }
    }
    for (uint32_t i = n; i > index; --i) {
        b->queue[i] = b->queue[i - 1u];
    }
    b->queue[index] = rec;
    b->queue_len = (uint8_t)(n + 1u); /* wide-operands-reviewed: <= 12 */
    return DUOFORGE_OK;
}

/* cancelAction (sim/battle-queue.ts:334-343): the queued actions of one
 * activation are removed; the rest keeps its order. */
static void dfi_cancel_actions(struct duoforge_battle *b, uint32_t activation_id)
{
    const uint32_t len = b->queue_len;
    uint32_t n = 0u;
    for (uint32_t i = 0u; i < len && i < DFI_QUEUE_CAPACITY; ++i) {
        if (activation_id == 0u || b->queue[i].activation_id != activation_id) {
            b->queue[n] = b->queue[i];
            n += 1u;
        }
    }
    for (uint32_t i = n; i < len && i < DFI_QUEUE_CAPACITY; ++i) {
        b->queue[i] = (dfi_queue_record){0u, 0u, 0u, 0u, 0u, 0u, 0u};
    }
    b->queue_len = (uint8_t)n; /* <= len */
}

/* switchIn (sim/battle-actions.ts:57-149): the Pokemon in the slot leaves
 * (its position is cleared; a fainted one simply makes room), the reserve
 * comes in with a fresh activation and is seen by the opponent, and its
 * entry is queued. */
static duoforge_status dfi_run_switch(dfi_run *r, const dfi_queue_record *q)
{
    struct duoforge_battle *b = r->b;
    const uint32_t side = q->side;
    const uint32_t slot = q->slot;
    const dfi_position_id where = {(uint8_t)side, (uint8_t)slot};
    const dfi_side *sd = &b->sides[side];
    const uint32_t reserve = q->reserve;
    if (reserve >= sd->member_count || sd->members[reserve].hp == 0u ||
        ((uint32_t)sd->brought_mask >> reserve & 1u) == 0u || sd->positions[0].occupant == reserve ||
        sd->positions[1].occupant == reserve) {
        return DUOFORGE_E_INVARIANT; /* the domain offers only standing reserves */
    }
    const uint32_t ability = sd->members[reserve].ability;
    const uint32_t item = sd->members[reserve].item;
    if ((ability != 0u && (ability > DFI_POOL_ABILITY_COUNT || dfi_support.abilities[ability - 1u] == 0u)) ||
        (item != 0u && (item > DFI_POOL_ITEM_COUNT || dfi_support.items[item - 1u] == 0u))) {
        return DUOFORGE_E_UNSUPPORTED; /* not marked in the support manifest */
    }
    const dfi_member *leaving = dfi_at(b, side * 2u + slot);
    const uint32_t flag = sd->positions[slot].switch_flag;
    const bool parting_shot = leaving != NULL && leaving->hp != 0u && flag == DFI_SWITCH_MOVE;
    /* A damaging pivot move's flag names the move that pivots. */
    const dfi_pivot_move *pivot = leaving != NULL && leaving->hp != 0u ? dfi_pivot_of_flag(flag) : NULL;
    if (leaving != NULL && leaving->hp != 0u && sd->positions[slot].switch_flag == 0u) {
        const duoforge_status us = dfi_update(r); /* BeforeSwitchOut, then Update (sim/battle-actions.ts:80-84) */
        if (us != DUOFORGE_OK) {
            return us;
        }
    }
    if (leaving != NULL && leaving->hp != 0u) {
        /* cancelAction (sim/battle-actions.ts:107): a Pokemon that leaves
         * standing loses its queued actions. */
        dfi_cancel_actions(b, sd->positions[slot].activation_id);
    }
    if (sd->positions[slot].occupant != DFI_OCCUPANT_NONE) {
        const duoforge_status vs = dfi_vacate(b, where);
        if (vs != DUOFORGE_OK) {
            return vs;
        }
    }
    dfi_binding binding = {{0u, 0u}, 0u};
    const duoforge_status ps = dfi_place(b, where, (uint8_t)reserve, &binding);
    if (ps != DUOFORGE_OK) {
        return ps;
    }
    /* newlySwitched until the end of the turn (Team C: only Helping Hand
     * reads it). */
    dfi_active_slot *entered = dfi_pos(b, side * 2u + slot);
    const uint32_t newly = dfi_kind_limits_of(r->ctx->data_kind).vol_flags_mask & DFI_VOL_NEWLY_SWITCHED;
    entered->flags = (uint8_t)((uint32_t)entered->flags | newly); /* wide-operands-reviewed: < 256 */
    /* [switch], with [from] and the move (Parting Shot, Flip Turn, U-turn) when the move made it */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_SWITCH, side * 2u + slot);
    e.id = (uint16_t)reserve;
    if (parting_shot || pivot != NULL) {
        e.cause = (uint8_t)DUOFORGE_CAUSE_MOVE;
        e.id2 = (uint16_t)(parting_shot ? DFI_MOVE_PARTINGSHOT : pivot->move); /* wide-operands-reviewed: a move id of the pool tables, a u16 */
    }
    dfi_emit_hp(r, e);
    return dfi_insert_run_switch(r, side, slot, binding.activation_id);
}

/* The entry abilities of the closure: an ability's onStart runs as a
 * SwitchIn handler (Battle.getCallback). */
static bool dfi_has_entry(const struct duoforge_battle *b, const dfi_member *m);

/* The terrain seeds (data/items.ts:2595-2614 Grassy Seed, :4903-4922 Psychic Seed; the generator checks that the second
 * is the first for its terrain and its stat): onSwitchInPriority -1, onStart (not ignoringItem, the terrain is up)
 * and onTerrainChange (the terrain is up) both call useItem, and the item's boosts raise one stat by one stage. The
 * terrain a seed waits for, or DFI_TERRAIN_NONE for a member that holds none. The Electric and Misty Seeds are
 * UNMODELED rows (no Electric or Misty Terrain in the pool tables' setters). */
static uint32_t dfi_seed_terrain(const struct duoforge_battle *b, const dfi_member *m)
{
    if (dfi_holds(b, m, DFI_ITEM_GRASSYSEED)) {
        return DFI_TERRAIN_GRASSY;
    }
    if (dfi_holds(b, m, DFI_ITEM_PSYCHICSEED)) {
        return DFI_TERRAIN_PSYCHIC;
    }
    return DFI_TERRAIN_NONE;
}

/* A terrain seed (useItem): its stat +1 once, when its terrain is up: Grassy Seed's Defense, Psychic Seed's Special
 * Defense. A holder that fainted does nothing. */
static void dfi_terrain_seed(dfi_run *r, uint32_t flat)
{
    static const uint8_t def_up[DFI_STAT_STAGE_COUNT] = {6u, 7u, 6u, 6u, 6u, 6u, 6u};
    static const uint8_t spd_up[DFI_STAT_STAGE_COUNT] = {6u, 6u, 6u, 7u, 6u, 6u, 6u};
    const dfi_member *m = dfi_at(r->b, flat);
    if (m == NULL || m->hp == 0u) {
        return;
    }
    const uint32_t terrain = dfi_seed_terrain(r->b, m);
    if (terrain == DFI_TERRAIN_NONE || r->b->terrain != terrain) {
        return;
    }
    const bool grassy = terrain == DFI_TERRAIN_GRASSY;
    const uint32_t item = grassy ? DFI_ITEM_GRASSYSEED : DFI_ITEM_PSYCHICSEED;
    dfi_use_item(r, flat);
    dfi_boost(r, flat, grassy ? def_up : spd_up, DFI_POSITIONS,
              dfi_effect(DUOFORGE_CAUSE_ITEM, 1u + item, DFI_BOOST_PRIMARY));
}

/* eachEvent('TerrainChange'): every terrain seed on the field in
 * eachEvent's order; a seed acts only while its terrain is up. */
static duoforge_status dfi_terrain_change(dfi_run *r)
{
    uint32_t bearers = 0u;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        bearers |= dfi_seed_terrain(r->b, dfi_at(r->b, flat)) != DFI_TERRAIN_NONE ? 1u << flat : 0u;
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
        dfi_terrain_seed(r, list[i]);
    }
    return DUOFORGE_OK;
}

/* A SwitchIn handler: an entry ability (priority 0) or a terrain seed's
 * onStart (onSwitchInPriority -1). */
static bool dfi_has_switch_in(const struct duoforge_battle *b, const dfi_member *m)
{
    return dfi_has_entry(b, m) || dfi_seed_terrain(b, m) != DFI_TERRAIN_NONE;
}

/* An entry ability: a weather or a terrain setter (the families of
 * decision 0015: Drizzle, Drought, Grassy Surge, Psychic Surge), Intimidate,
 * Fairy Aura (whose onStart only shows the ability) or Trace. */
static bool dfi_has_entry(const struct duoforge_battle *b, const dfi_member *m)
{
    const dfi_ability_family fam = dfi_ability_family_now(b, m);
    const uint32_t now = dfi_ability_code(b, m);
    return dfi_weather_set_by_fam(fam) != DFI_WEATHER_NONE || dfi_terrain_set_by_fam(fam) != DFI_TERRAIN_NONE ||
           now == 1u + DFI_ABILITY_INTIMIDATE || now == 1u + DFI_ABILITY_FAIRYAURA || now == 1u + DFI_ABILITY_TRACE;
}

/* Trace (data/abilities.ts:5118-5148, onStart then its Update): the holder copies the ability of one of the foes that
 * are standing and whose ability can be copied. `adjacentFoes()` is every foe in doubles (sim/pokemon.ts:732-735),
 * a foe is a candidate unless its ability is none or has the notrace flag: of the abilities that a battle can hold
 * (the marked ones) only Trace itself has it (tests/test_pool_tables.c; the pin's nine notrace abilities are
 * checked by tools/datagen/pool_families.js), so a foe that is still Trace, or whose Trace has not run yet, is not
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
            if (code != 0u && code != 1u + DFI_ABILITY_TRACE) {
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
    b->tail.sides[flat / 2u].ability_now[dfi_pos(b, flat)->occupant] = (uint16_t)copied; /* <= the ability count */
    const duoforge_event e = dfi_ev(DUOFORGE_EVENT_ABILITY, flat, DUOFORGE_CAUSE_ABILITY, copied, source);
    dfi_emit(r, &e);
    if (dfi_has_entry(b, dfi_at(b, flat))) {
        return dfi_entry_ability(r, flat); /* setAbility's Start event */
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
            b->weather_turns = (uint8_t)DFI_FIELD_TURNS_MAX;
            /* -weather|...|[from] ability: X|[of] holder */
            duoforge_event e = dfi_ev(DUOFORGE_EVENT_WEATHER, DUOFORGE_NO_POSITION, DUOFORGE_CAUSE_ABILITY, a, flat);
            e.detail = (uint8_t)w; /* DUOFORGE_WEATHER_* */
            dfi_emit(r, &e);
        }
    } else if (terrain != DFI_TERRAIN_NONE) {
        const bool grassy = terrain == DFI_TERRAIN_GRASSY;
        if (b->terrain != terrain) {
            b->terrain = (uint8_t)terrain;
            b->terrain_turns = (uint8_t)DFI_FIELD_TURNS_MAX;
            /* -fieldstart|move: X Terrain|[from] ability: X|[of] holder */
            duoforge_event e =
                dfi_ev(DUOFORGE_EVENT_FIELD_START, DUOFORGE_NO_POSITION, DUOFORGE_CAUSE_ABILITY, a, flat);
            e.detail = (uint8_t)(grassy ? DUOFORGE_FIELD_GRASSY_TERRAIN : DUOFORGE_FIELD_PSYCHIC_TERRAIN); /* wide-operands-reviewed: < 4 */
            dfi_emit(r, &e);
            return dfi_terrain_change(r);
        }
    } else if (a == 1u + DFI_ABILITY_TRACE) {
        return dfi_trace(r, flat);
    } else if (a == 1u + DFI_ABILITY_FAIRYAURA) {
        /* onStart: -ability|holder|Fairy Aura (the aura itself is onAnyBasePower) */
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
                dfi_boost(r, foe * 2u + slot, drop, flat,
                          dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_INTIMIDATE, DFI_BOOST_SECONDARY));
            }
        }
    }
    return DUOFORGE_OK;
}

/* runSwitch (sim/battle-actions.ts:177-192): every active Pokemon, a
 * fainted one included, is sorted by its last speed (Battle.speedSort, ties
 * shuffled); the SwitchIn handlers then run in that order. A tie decides
 * something only between two entering Pokemon with an entry ability, or
 * between two standing White Herb holders, whose onAnySwitchIn runs for
 * every holder on the field (Team C): only such a group draws (decision
 * 0006 section 5.1). */
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
            bearers += (((entering >> flat) & 1u) != 0u && m->hp != 0u && dfi_has_switch_in(b, m)) ? 1u : 0u;
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
    /* The abilities (priority 0) in that order, then the terrain seeds
     * (Grassy and Psychic Seed, priority -1), then White Herb's onAnySwitchIn of every holder on the
     * field (priority -2, Team C), in the same order: the handlers'
     * fractional speeds follow it (sim/battle.ts:1008-1013). */
    for (uint32_t pass = 0u; pass < 2u; ++pass) {
        for (uint32_t i = 0u; i < n; ++i) {
            const uint32_t flat = list[i];
            const dfi_member *m = dfi_at(b, flat);
            if (((entering >> flat) & 1u) == 0u || m->hp == 0u) {
                continue;
            }
            if (pass == 0u && dfi_has_entry(b, m)) {
                const duoforge_status st = dfi_entry_ability(r, flat);
                if (st != DUOFORGE_OK) {
                    return st;
                }
            } else if (pass == 1u && dfi_seed_terrain(r->b, m) != DFI_TERRAIN_NONE) {
                dfi_terrain_seed(r, flat);
            } else {
                continue;
            }
            dfi_process_faints(r);
            if (r->ended) {
                return DUOFORGE_OK;
            }
        }
    }
    for (uint32_t i = 0u; i < n; ++i) {
        dfi_white_herb(r, list[i]);
    }
    return DUOFORGE_OK;
}

/* runMegaEvo (sim/battle-actions.ts): the Mega forme with its stats and
 * ability, once per side; the opponent sees it; the new ability starts
 * (setAbility's Start event: Drought). */
static duoforge_status dfi_run_mega(dfi_run *r, const dfi_queue_record *q)
{
    struct duoforge_battle *b = r->b;
    const uint32_t flat = (uint32_t)q->side * 2u + (uint32_t)q->slot;
    dfi_member *m = dfi_at(b, flat);
    dfi_side *sd = &b->sides[q->side];
    if (m == NULL || m->hp == 0u || dfi_pos(b, flat)->activation_id != q->activation_id || sd->mega_used != 0u) {
        return DUOFORGE_OK;
    }
    if (!dfi_closure_member_mega_evolve(m)) {
        return DUOFORGE_E_INVARIANT; /* the domain offers Mega only to a holder of its stone */
    }
    sd->mega_used = 1u;
    /* formeChange -> setSpecies -> setType(species.types, true): a type that Soak set ends (sim/pokemon.ts:1392,
     * 1427-1434), without a line. */
    b->tail.sides[q->side].soak_type[dfi_pos(b, flat)->occupant] = 0u;
    /* The Mega forme's ability replaces one that Trace copied (formeChange -> setAbility, sim/pokemon.ts:1487). */
    b->tail.sides[q->side].ability_now[dfi_pos(b, flat)->occupant] = 0u;
    /* setAbility ends the old ability first (sim/pokemon.ts:1923): Unburden's onEnd removes its volatile
     * (data/abilities.ts:5243-5245), which a holder of its own Mega Stone may have since a Knock Off (dfi_knock_off); no
     * ability of a Mega forme in the pool is Unburden. */
    {
        dfi_active_slot *mega_pos = dfi_pos(b, flat);
        mega_pos->flags = (uint8_t)((uint32_t)mega_pos->flags & ~(uint32_t)DFI_VOL_UNBURDEN); /* wide-operands-reviewed */
    }
    duoforge_event forme = dfi_event_make(DUOFORGE_EVENT_FORME, flat);
    forme.id = dfi_pool_formes[m->species_id].mega_forme; /* [detailschange] */
    dfi_emit(r, &forme);
    duoforge_event mega = dfi_event_make(DUOFORGE_EVENT_MEGA, flat);
    mega.id2 = m->item; /* [-mega] the stone, item + 1 */
    dfi_emit(r, &mega);
    if (dfi_has_entry(b, m)) {
        const duoforge_status st = dfi_entry_ability(r, flat);
        if (st != DUOFORGE_OK) {
            return st;
        }
    }
    /* AfterMega: White Herb's onAnyAfterMega (Team C;
     * sim/battle-actions.ts:1914). */
    return dfi_herb_event(r, flat);
}

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
/* The side conditions that count down in the residual, by sub-order: Reflect, Light Screen, Tailwind, Aurora Veil. */
#define DFI_SIDE_KINDS 4u
static uint8_t *dfi_side_turns(struct duoforge_battle *b, uint32_t s, uint32_t k)
{
    dfi_side *sd = &b->sides[s];
    return k == 0u ? &sd->reflect_turns
           : k == 1u ? &sd->light_screen_turns
           : k == 2u ? &sd->tailwind_turns
                     : &b->tail.sides[s].aurora_veil_turns; /* the tail is zero under every kind but POOL */
}
/* Trick Room, weather and terrain; four conditions per side (step G20 added Aurora Veil); per position
 * (DFI_RES_PER_POSITION) a status (burn or poison), the volatiles' handlers (seven duration ends: Protect, the stall
 * counter, flinch, a charge, Helping Hand, Follow Me and mustrecharge; Heal Block, Throat Chop and Encore), an item
 * (Leftovers or White Herb) and Grassy Terrain. */
#define DFI_RES_PER_POSITION 14u
#define DFI_RES_MAX (3u + 4u * DUOFORGE_SIDE_COUNT + DFI_RES_PER_POSITION * DFI_POSITIONS)
_Static_assert(DFI_RES_MAX <= DFI_RES_MODEL_MAX, "the exact test of residual_order.h must hold the whole list");

/* Battle.speedSort over the residual handlers, continued from *sorted
 * until `want` callbacks are placed (*placed counts them). A group of tied
 * callbacks is shuffled, one draw per step; a tie among duration handlers
 * changes nothing and is not drawn. Callbacks and duration handlers never
 * share an order, so no group mixes them. */
static duoforge_status dfi_residual_sort(dfi_run *r, dfi_residual_entry *list, uint32_t n, uint32_t *sorted,
                                         uint32_t *placed, uint32_t want)
{
    while (*placed < want && *sorted < n) {
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
        const bool callbacks = list[at].callback;
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
        *placed += callbacks ? count : 0u;
        *sorted = at + count;
    }
    return DUOFORGE_OK;
}

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

static duoforge_status dfi_residual_events(dfi_run *r)
{
    struct duoforge_battle *b = r->b;
    duoforge_status st = dfi_update_speeds(r);
    if (st != DUOFORGE_OK) {
        return st;
    }
    dfi_residual_entry list[DFI_RES_MAX];
    uint32_t n = 0u;
    if (b->trick_room_turns != 0u) {
        list[n] = (dfi_residual_entry){DFI_RES_FIELD_END, 0u, 27u, 0u, 1u, false};
        n += 1u;
    }
    if (b->weather != DFI_WEATHER_NONE) {
        list[n] = (dfi_residual_entry){DFI_RES_WEATHER, 0u, 1u, 0u, 5u, true};
        n += 1u;
    }
    if (b->terrain != DFI_TERRAIN_NONE) {
        list[n] = (dfi_residual_entry){DFI_RES_TERRAIN_END, 0u, 27u, 0u, 7u, false};
        n += 1u;
    }
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        if (flat % 2u == 0u) {
            /* The side's conditions come before its Pokemon (order 26). */
            const dfi_side *sd = &b->sides[flat / 2u];
            const uint32_t conditions = (sd->reflect_turns != 0u ? 1u : 0u) + (sd->light_screen_turns != 0u ? 1u : 0u) +
                                        (sd->tailwind_turns != 0u ? 1u : 0u) +
                                        (b->tail.sides[flat / 2u].aurora_veil_turns != 0u ? 1u : 0u);
            for (uint32_t k = 0u; k < conditions; ++k) {
                list[n] = (dfi_residual_entry){DFI_RES_FIELD_END, 0u, 26u, 0u, 1u, false};
                n += 1u;
            }
        }
        const dfi_active_slot *pos = dfi_pos(b, flat);
        const dfi_member *m = dfi_at(b, flat);
        if (m == NULL) {
            continue;
        }
        if (n + DFI_RES_PER_POSITION > DFI_RES_MAX) {
            return DUOFORGE_E_INVARIANT; /* the bound above is exact: never */
        }
        const uint32_t speed = r->speed_seen[flat];
        if (m->status == DFI_STATUS_BRN) {
            list[n] = (dfi_residual_entry){DFI_RES_BURN, flat, 10u, speed, 0u, true};
            n += 1u;
        } else if (m->status == DFI_STATUS_PSN) {
            list[n] = (dfi_residual_entry){DFI_RES_POISON, flat, 9u, speed, 0u, true};
            n += 1u;
        }
        const uint32_t ends = ((((uint32_t)pos->flags & DFI_VOL_PROTECT) != 0u) ? 1u : 0u) +
                              (pos->stall_level != 0u ? 1u : 0u) +
                              ((((uint32_t)pos->flags & DFI_VOL_FLINCH) != 0u) ? 1u : 0u) +
                              (pos->charge_turns != 0u ? 1u : 0u) +
                              ((((uint32_t)pos->flags & DFI_VOL_HELPING_HAND) != 0u) ? 1u : 0u) +
                              ((((uint32_t)pos->flags & DFI_VOL_FOLLOW_ME) != 0u) ? 1u : 0u) +
                              /* mustrecharge has a duration (2) and no callback: an end handler of the residual's sort,
                               * like the stall counter (data/conditions.ts:364-378; step G17). */
                              (b->tail.sides[flat / 2u].positions[flat % 2u].must_recharge != 0u ? 1u : 0u);
        for (uint32_t k = 0u; k < ends; ++k) {
            list[n] = (dfi_residual_entry){DFI_RES_DURATION, flat, DFI_RES_NO_ORDER, speed, 2u, false};
            n += 1u;
        }
        /* Heal Block (order 20, data/moves.ts:8273-8320) and Throat Chop (order 22, :19389-19423) are duration handlers
         * of a position's volatile too: they sort in the list like the others, and take their turn after the
         * callbacks (the count and the end lines are below, their tie is the outcome draw of the Heal Blocks that
         * end). Encore (order 16) is a volatile as well: its handler comes before the item's, not after Grassy
         * Terrain's (sim/battle.ts:1107-1130). */
        if (b->tail.sides[flat / 2u].positions[flat % 2u].heal_block_turns != 0u) {
            list[n] = (dfi_residual_entry){DFI_RES_DURATION, flat, 20u, speed, 2u, false};
            n += 1u;
        }
        if (b->tail.sides[flat / 2u].positions[flat % 2u].throat_chop_turns != 0u) {
            list[n] = (dfi_residual_entry){DFI_RES_DURATION, flat, 22u, speed, 2u, false};
            n += 1u;
        }
        if (b->tail.sides[flat / 2u].positions[flat % 2u].encore_slot != 0u) {
            list[n] = (dfi_residual_entry){DFI_RES_ENCORE, flat, 16u, speed, 2u, true};
            n += 1u;
        }
        if (dfi_holds(r->b, m, DFI_ITEM_LEFTOVERS)) {
            list[n] = (dfi_residual_entry){DFI_RES_LEFTOVERS, flat, 5u, speed, 4u, true};
            n += 1u;
        }
        /* White Herb's onResidual (order 29, an item: sub-order 8; Team C). */
        if (dfi_holds(r->b, m, DFI_ITEM_WHITEHERB)) {
            list[n] = (dfi_residual_entry){DFI_RES_WHITE_HERB, flat, 29u, speed, 8u, true};
            n += 1u;
        }
        if (b->terrain == DFI_TERRAIN_GRASSY) {
            list[n] = (dfi_residual_entry){DFI_RES_GRASSY, flat, 5u, speed, 2u, true};
            n += 1u;
        }
    }
    /* The order in which a Pokemon's volatiles were added is not stored: the engine lists them in one fixed order, which
     * is the reference's or changes nothing except in the cases of dfi_residual_order_ambiguous (combat/
     * residual_order.h); those it refuses. */
    if (dfi_residual_order_ambiguous(list, n)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    uint32_t early = 0u; /* the callbacks of orders 1 to 10 */
    uint32_t herbs = 0u; /* White Herb's, order 29 */
    for (uint32_t i = 0u; i < n; ++i) {
        if (list[i].kind == DFI_RES_WHITE_HERB) {
            herbs += 1u;
        } else if (list[i].callback) {
            early += 1u;
        }
    }
    /* The sort's draws in the reference's order: the early callbacks, the
     * side conditions (26), then White Herb (29). */
    uint32_t sorted = 0u;
    uint32_t placed = 0u;
    st = dfi_residual_sort(r, list, n, &sorted, &placed, early);
    if (st != DUOFORGE_OK) {
        return st;
    }
    /* The side conditions end in the group of order 26, sub-order by kind
     * (Reflect 1, Light Screen 2, Tailwind 5, Aurora Veil 10: data/moves.ts:864-865). The same kind on both sides
     * ties; the shuffle decides the order of the two end lines when both
     * run out now: only then a draw (decision 0007 section 6). `first`: the
     * side whose line comes first, per kind. */
    uint32_t first[DFI_SIDE_KINDS] = {0u, 0u, 0u, 0u};
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
    st = dfi_residual_sort(r, list, n, &sorted, &placed, early + herbs);
    if (st != DUOFORGE_OK) {
        return st;
    }
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
                if (b->weather == DFI_WEATHER_SAND) {
                    st = dfi_sand_damage(r); /* eachEvent('Weather'): Sandstorm's onWeather */
                    if (st != DUOFORGE_OK) {
                        return st;
                    }
                }
                st = dfi_update(r); /* the upkeep: eachEvent('Weather') ends with 'Update' */
                if (st != DUOFORGE_OK) {
                    return st;
                }
                dfi_process_faints(r); /* fieldEvent: faintMessages after each handler (sim/battle.ts:569-570) */
                if (r->ended) {
                    return DUOFORGE_OK;
                }
            }
            continue;
        }
        dfi_member *m = dfi_at(b, e->flat);
        if (m->hp == 0u) {
            continue; /* the holder fainted */
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
        if (e->kind == DFI_RES_LEFTOVERS) {
            dfi_heal(r, e->flat, (uint32_t)m->hp_max / 16u, DUOFORGE_CAUSE_ITEM, 1u + DFI_ITEM_LEFTOVERS,
                     DUOFORGE_NO_POSITION); /* heal(baseMaxhp / 16) */
            continue;
        }
        if (e->kind == DFI_RES_GRASSY) {
            /* heal(baseMaxhp / 16): at least 1, not above the maximum, not
             * for a Pokemon that is not grounded or at full HP. */
            if (dfi_grounded(b, m) && m->hp < m->hp_max && !dfi_heal_blocked(b, e->flat)) {
                uint32_t heal = (uint32_t)m->hp_max / 16u;
                heal = heal == 0u ? 1u : heal;
                const uint32_t hp = (uint32_t)m->hp + heal;
                m->hp = (uint16_t)(hp > m->hp_max ? m->hp_max : hp); /* wide-operands-reviewed: <= hp_max */
                dfi_emit_hp(r, dfi_ev(DUOFORGE_EVENT_HEAL, e->flat, DUOFORGE_CAUSE_TERRAIN, 0u, DUOFORGE_NO_POSITION));
            }
            continue;
        }
        /* burn: baseMaxhp / 16; poison: baseMaxhp / 8 (data/conditions.ts:
         * 123-137); at least 1. Any other callback here is a missing case. */
        if (e->kind != DFI_RES_BURN && e->kind != DFI_RES_POISON) {
            return DUOFORGE_E_INVARIANT;
        }
        const bool poison = e->kind == DFI_RES_POISON;
        const uint32_t damage = (uint32_t)m->hp_max / (poison ? 8u : 16u);
        st = dfi_deal(r, e->flat, damage == 0u ? 1u : damage, poison ? DUOFORGE_CAUSE_POISON : DUOFORGE_CAUSE_BURN, 0u,
                      DUOFORGE_NO_POSITION);
        if (st != DUOFORGE_OK) {
            return st;
        }
        dfi_process_faints(r);
        if (r->ended) {
            return DUOFORGE_OK;
        }
    }
    /* Heal Block (order 20) and Throat Chop (order 22), duration handlers of a position's volatile (POOL tail): the
     * count goes down; at 0 Heal Block shows its end line (-end|X|move: Heal Block) and Throat Chop's is [silent].
     * Two Heal Blocks that end now come in the speed order of their holders; at equal speed the reference shuffles
     * and draws, and the order shows in the two -end lines, so the converter keeps that tie (heal_block_end_tie)
     * and the engine draws it (below). */
    {
        uint32_t ending[DFI_POSITIONS] = {0u, 0u, 0u, 0u};
        uint32_t ne = 0u;
        for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
            dfi_tail_pos *tail = &b->tail.sides[flat / 2u].positions[flat % 2u];
            if (tail->heal_block_turns != 0u) {
                tail->heal_block_turns = (uint8_t)((uint32_t)tail->heal_block_turns - 1u); /* wide-operands-reviewed */
                if (tail->heal_block_turns == 0u) {
                    ending[ne] = flat;
                    ne += 1u;
                }
            }
        }
        for (uint32_t i = 1u; i < ne; ++i) {
            for (uint32_t j = i; j > 0u && r->speed_seen[ending[j]] > r->speed_seen[ending[j - 1u]]; --j) {
                const uint32_t swap = ending[j];
                ending[j] = ending[j - 1u];
                ending[j - 1u] = swap;
            }
        }
        /* Holders of equal Speed: the reference's speedSort shuffles each such run (PRNG.shuffle, one draw
         * random(start, start + 2) for a pair), and the two -end lines show the outcome, so the engine draws the
         * SPEED_TIE in the same place (after the callbacks of the sort, before the side conditions) and orders the
         * pair by it: 0 keeps the lower position first, 1 swaps. A run of three or four needs the longer shuffle,
         * which no battle has needed: E_UNSUPPORTED, as before. */
        for (uint32_t i = 0u; i < ne;) {
            uint32_t j = i + 1u;
            while (j < ne && r->speed_seen[ending[j]] == r->speed_seen[ending[i]]) {
                ++j;
            }
            if (j - i > 2u) {
                return DUOFORGE_E_UNSUPPORTED;
            }
            if (j - i == 2u) {
                uint32_t v = 0u;
                st = dfi_draw(r->draws, DFI_SITE_SPEED_TIE, 0u, 2u, &v);
                if (st != DUOFORGE_OK) {
                    return st;
                }
                if (v == 1u) {
                    const uint32_t swap = ending[i];
                    ending[i] = ending[i + 1u];
                    ending[i + 1u] = swap;
                }
            }
            i = j;
        }
        for (uint32_t i = 0u; i < ne; ++i) {
            duoforge_event e = dfi_event_make(DUOFORGE_EVENT_VOLATILE_END, ending[i]);
            e.detail = (uint8_t)DUOFORGE_VOLATILE_HEAL_BLOCK;
            dfi_emit(r, &e);
        }
        for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
            dfi_tail_pos *tail = &b->tail.sides[flat / 2u].positions[flat % 2u];
            if (tail->throat_chop_turns != 0u) {
                tail->throat_chop_turns = (uint8_t)((uint32_t)tail->throat_chop_turns - 1u); /* wide-operands-reviewed */
            }
        }
        /* Wide Guard's side condition has duration 1 and no end line: it is gone after this residual. */
        for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
            b->tail.sides[s].wide_guard = 0u;
        }
    }
    /* The duration handlers in their order: the side conditions (26), Trick
     * Room (27, sub-order 1), the terrain (27, 7); each that runs out shows
     * its end line (and the terrain's end runs TerrainChange). Protect,
     * flinch and the stall counter end without a line. */
    static const uint8_t side_kind[DFI_SIDE_KINDS] = {DUOFORGE_SIDE_REFLECT, DUOFORGE_SIDE_LIGHT_SCREEN,
                                                      DUOFORGE_SIDE_TAILWIND, DUOFORGE_SIDE_AURORA_VEIL};
    for (uint32_t k = 0u; k < DFI_SIDE_KINDS; ++k) {
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
            }
        }
    }
    if (b->trick_room_turns != 0u) {
        b->trick_room_turns = (uint8_t)((uint32_t)b->trick_room_turns - 1u); /* wide-operands-reviewed: >= 1 */
        if (b->trick_room_turns == 0u) {
            duoforge_event e = dfi_event_make(DUOFORGE_EVENT_FIELD_END, DUOFORGE_NO_POSITION);
            e.detail = (uint8_t)DUOFORGE_FIELD_TRICK_ROOM;
            dfi_emit(r, &e); /* [-fieldend] */
        }
    }
    if (b->terrain != DFI_TERRAIN_NONE) {
        b->terrain_turns = (uint8_t)((uint32_t)b->terrain_turns - 1u); /* wide-operands-reviewed: >= 1 */
        if (b->terrain_turns == 0u) {
            const bool grassy = b->terrain == DFI_TERRAIN_GRASSY;
            b->terrain = (uint8_t)DFI_TERRAIN_NONE;
            duoforge_event e = dfi_event_make(DUOFORGE_EVENT_FIELD_END, DUOFORGE_NO_POSITION);
            e.detail = (uint8_t)(grassy ? DUOFORGE_FIELD_GRASSY_TERRAIN : DUOFORGE_FIELD_PSYCHIC_TERRAIN); /* wide-operands-reviewed: < 4 */
            dfi_emit(r, &e); /* [-fieldend] */
            st = dfi_terrain_change(r);
            if (st != DUOFORGE_OK) {
                return st;
            }
        }
    }
    /* White Herb's onResidual (order 29), each holder's check. The engine
     * keeps the side conditions without their kinds, so the start order of
     * the shuffle above can differ from the reference's: two holders due in
     * one group of equal speed are E_UNSUPPORTED. With the data no herb is
     * due here (every lowered stat meets an earlier check). */
    for (uint32_t i = herbs_from; i < sorted; ++i) {
        if (list[i].kind != DFI_RES_WHITE_HERB || !dfi_herb_due(b, list[i].flat)) {
            continue;
        }
        for (uint32_t j = i + 1u; j < sorted; ++j) {
            if (list[j].kind == DFI_RES_WHITE_HERB && list[j].speed == list[i].speed && dfi_herb_due(b, list[j].flat)) {
                return DUOFORGE_E_UNSUPPORTED;
            }
        }
    }
    for (uint32_t i = herbs_from; i < sorted; ++i) {
        if (list[i].kind == DFI_RES_WHITE_HERB) {
            dfi_white_herb(r, list[i].flat);
        }
    }
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        dfi_active_slot *pos = dfi_pos(b, flat);
        if (pos->occupant == DFI_OCCUPANT_NONE) {
            continue;
        }
        const uint32_t ended = DFI_VOL_PROTECT | DFI_VOL_FLINCH | DFI_VOL_HELPING_HAND | DFI_VOL_FOLLOW_ME;
        pos->flags = (uint8_t)((uint32_t)pos->flags & ~ended); /* wide-operands-reviewed */
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
    }
    return DUOFORGE_OK;
}

static void dfi_clear_requests(struct duoforge_battle *b)
{
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        dfi_side *side = &b->sides[s];
        side->requested_slots = 0u;
        side->sealed = 0u;
        side->sealed_cmds[0] = (dfi_slot_cmd){0u, 0u, 0u, 0u, 0u};
        side->sealed_cmds[1] = (dfi_slot_cmd){0u, 0u, 0u, 0u, 0u};
    }
    b->queue_len = 0u;
    for (uint32_t i = 0u; i < DFI_QUEUE_CAPACITY; ++i) {
        b->queue[i] = (dfi_queue_record){0u, 0u, 0u, 0u, 0u, 0u, 0u};
    }
}

static duoforge_status dfi_next_epoch(struct duoforge_battle *b)
{
    uint32_t epoch = 0u;
    if (!dfi_add_u32(b->request_epoch, 1u, &epoch) || epoch == UINT32_MAX) {
        return DUOFORGE_E_EXHAUSTED;
    }
    b->request_epoch = epoch;
    return DUOFORGE_OK;
}

/* checkFainted (sim/battle.ts:2524-2530): a fainted Pokemon keeps its
 * status until the turn's actions are done (its burn handler still takes
 * part in the residual order); then the status is gone. */
static void dfi_check_fainted(struct duoforge_battle *b)
{
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        dfi_side *sd = &b->sides[s];
        for (uint32_t m = 0u; m < sd->member_count && m < DUOFORGE_MAX_ROSTER; ++m) {
            if (sd->members[m].hp == 0u) {
                sd->members[m].status = (uint8_t)DFI_STATUS_NONE;
                sd->members[m].status_counter = 0u;
            }
        }
    }
}

static bool dfi_has_reserve(const struct duoforge_battle *b, uint32_t side);

/* A switch request while actions are still queued (sim/battle.ts:
 * 2876-2915): a side with flagged positions but no reserve loses its flags;
 * the other sides with flagged positions answer for exactly those positions,
 * and the rest of the queue waits. A flagged position holds a standing
 * Pokemon (Parting Shot, Emergency Exit) or, after a pass at a REPLACEMENT,
 * a fainted one (checkFainted): then the side is asked again right after the
 * switch, before the newcomer's entry. */
static bool dfi_pivot_pending(struct duoforge_battle *b)
{
    bool pending = false;
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        dfi_side *sd = &b->sides[s];
        if (sd->positions[0].switch_flag == 0u && sd->positions[1].switch_flag == 0u) {
            continue;
        }
        if (dfi_has_reserve(b, s)) {
            pending = true;
        } else {
            sd->positions[0].switch_flag = 0u;
            sd->positions[1].switch_flag = 0u;
        }
    }
    return pending;
}

static duoforge_status dfi_pivot(struct duoforge_battle *b)
{
    uint32_t epoch = 0u;
    if (!dfi_add_u32(b->request_epoch, 1u, &epoch) || epoch == UINT32_MAX) {
        return DUOFORGE_E_EXHAUSTED;
    }
    b->request_epoch = epoch;
    b->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_PIVOT;
    uint32_t mask = 0u;
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        dfi_side *sd = &b->sides[s];
        uint32_t slots = 0u;
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const dfi_member *m = dfi_at(b, s * 2u + p);
            if (sd->positions[p].switch_flag != 0u && m != NULL) {
                slots |= 1u << p;
            } else {
                sd->positions[p].switch_flag = 0u;
            }
        }
        sd->requested_slots = (uint8_t)slots; /* <= 3 */
        sd->sealed = 0u;
        sd->sealed_cmds[0] = (dfi_slot_cmd){0u, 0u, 0u, 0u, 0u};
        sd->sealed_cmds[1] = (dfi_slot_cmd){0u, 0u, 0u, 0u, 0u};
        mask |= slots != 0u ? 1u << s : 0u;
    }
    b->request_mask = (uint8_t)mask; /* <= 3 */
    return DUOFORGE_OK;
}

/* The answer to a PIVOT (commitChoices): speeds are taken again, the new
 * switches (instaswitch) go in front of the stored rest of the turn. */
static duoforge_status dfi_resume_pivot(dfi_run *r, const duoforge_side_choice responses[DUOFORGE_SIDE_COUNT])
{
    struct duoforge_battle *b = r->b;
    duoforge_status st = dfi_update_speeds(r);
    if (st != DUOFORGE_OK) {
        return st;
    }
    dfi_queue_record fresh[DFI_POSITIONS];
    uint32_t k = 0u;
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        if (((uint32_t)b->request_mask >> s & 1u) == 0u) {
            continue;
        }
        for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
            const duoforge_slot_command *sc = &responses[s].slots[slot];
            if (sc->kind == DUOFORGE_SLOT_SWITCH) {
                fresh[k] = (dfi_queue_record){0u, (uint8_t)DFI_Q_SWITCH_IN, (uint8_t)s, (uint8_t)slot, 0u, 0u,
                                              sc->reserve};
                k += 1u;
            } else if (((uint32_t)b->sides[s].requested_slots >> slot & 1u) == 0u) {
                b->sides[s].positions[slot].switch_flag = 0u;
            }
            /* A requested slot that passes keeps its flag (choosePass,
             * sim/side.ts:1330-1357): with two flagged slots and one reserve
             * (Flip Turn and Emergency Exit on one side, Team C), the side is
             * asked again after the switch, the Pokemon that left now being
             * a reserve (dfi_pivot_pending). */
        }
    }
    if ((uint32_t)b->queue_len + k > DFI_QUEUE_CAPACITY) {
        return DUOFORGE_E_INVARIANT;
    }
    for (uint32_t i = b->queue_len; i > 0u; --i) {
        b->queue[i + k - 1u] = b->queue[i - 1u];
    }
    for (uint32_t i = 0u; i < k; ++i) {
        b->queue[i] = fresh[i];
    }
    b->queue_len = (uint8_t)((uint32_t)b->queue_len + k); /* wide-operands-reviewed: <= 12 */
    /* Two Emergency Exits in one action (one on each side) switch in Speed
     * order. */
    return k > 1u ? dfi_sort_front(r, k) : DUOFORGE_OK;
}

/* The battle is over: TERMINAL with its result, nobody requested. */
static duoforge_status dfi_terminal(dfi_run *r)
{
    struct duoforge_battle *b = r->b;
    if (r->early_result == DFI_RESULT_NONE) {
        duoforge_event e = dfi_event_make(DUOFORGE_EVENT_RESULT, DUOFORGE_NO_POSITION);
        e.detail = b->result; /* [win] or [tie]: DFI_RESULT_* are the public values */
        dfi_emit(r, &e);
    } else if (r->early_result != b->result) {
        return DUOFORGE_E_INVARIANT; /* nothing revives, so the hit loop's result stands */
    }
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        dfi_pos(b, flat)->switch_flag = 0u; /* no pivot after the end */
    }
    dfi_check_fainted(b);
    const duoforge_status st = dfi_next_epoch(b);
    if (st != DUOFORGE_OK) {
        return st;
    }
    dfi_clear_requests(b);
    b->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_TERMINAL;
    b->request_mask = 0u;
    return DUOFORGE_OK;
}

static duoforge_status dfi_end_turn(dfi_run *r)
{
    struct duoforge_battle *b = r->b;
    uint32_t turn = 0u;
    uint32_t epoch = 0u;
    if (!dfi_add_u32(b->turn, 1u, &turn) || turn > UINT16_MAX || !dfi_add_u32(b->request_epoch, 1u, &epoch) ||
        epoch == UINT32_MAX) {
        return DUOFORGE_E_EXHAUSTED;
    }
    b->turn = (uint16_t)turn;
    b->request_epoch = epoch;
    b->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_TURN;
    /* endTurn: newlySwitched ends (sim/battle.ts:1673; Team C). */
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        dfi_active_slot *pos = dfi_pos(b, flat);
        pos->flags = (uint8_t)((uint32_t)pos->flags & ~DFI_VOL_NEWLY_SWITCHED); /* wide-operands-reviewed */
    }
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_TURN, DUOFORGE_NO_POSITION);
    e.id = b->turn; /* [turn] */
    dfi_emit(r, &e);
    b->request_mask = 3u;
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        dfi_side *side = &b->sides[s];
        uint32_t occupied = 0u;
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            if (side->positions[p].occupant != DFI_OCCUPANT_NONE) {
                occupied |= 1u << p;
            }
        }
        side->requested_slots = (uint8_t)occupied; /* <= 3 */
        side->sealed = 0u;
        side->sealed_cmds[0] = (dfi_slot_cmd){0u, 0u, 0u, 0u, 0u};
        side->sealed_cmds[1] = (dfi_slot_cmd){0u, 0u, 0u, 0u, 0u};
    }
    return DUOFORGE_OK;
}

/* A standing brought member that is not on the field. */
static bool dfi_has_reserve(const struct duoforge_battle *b, uint32_t side)
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

/* The queue is empty after the residual action or after the switches of
 * a REPLACEMENT: checkFainted and the switch request (sim/battle.ts:
 * 2524-2530, 2876-2915). A side with a fainted Pokemon on the field and a
 * reserve, or with an Emergency Exit after the residual action (`exits`,
 * by flat position), answers for those positions; otherwise the next turn
 * starts. A REPLACEMENT can follow a REPLACEMENT: when a side passed for a
 * fainted position and the Emergency Exit holder went to the bench. */
static duoforge_status dfi_finish_turn(dfi_run *r, uint32_t exits)
{
    struct duoforge_battle *b = r->b;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        dfi_pos(b, flat)->switch_flag = 0u; /* the REPLACEMENT carries no flags */
    }
    dfi_check_fainted(b);
    uint32_t mask = 0u;
    uint32_t fainted[DUOFORGE_SIDE_COUNT] = {0u, 0u};
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const uint32_t occupant = b->sides[s].positions[p].occupant;
            if (occupant < DUOFORGE_MAX_ROSTER && b->sides[s].members[occupant].hp == 0u) {
                fainted[s] |= 1u << p;
            }
        }
        const uint32_t leaving = exits >> (s * 2u) & 3u;
        if ((fainted[s] != 0u && dfi_has_reserve(b, s)) || leaving != 0u) {
            fainted[s] |= leaving;
            mask |= 1u << s;
        }
    }
    if (mask == 0u) {
        return dfi_end_turn(r);
    }
    const duoforge_status st = dfi_next_epoch(b);
    if (st != DUOFORGE_OK) {
        return st;
    }
    dfi_clear_requests(b);
    b->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_REPLACEMENT;
    b->request_mask = (uint8_t)mask; /* <= 3 */
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        if ((mask >> s & 1u) != 0u) {
            b->sides[s].requested_slots = (uint8_t)fainted[s]; /* <= 3 */
        }
    }
    return DUOFORGE_OK;
}

duoforge_status dfi_turn_start(const duoforge_context *ctx, struct duoforge_battle *b, dfi_draws *draws,
                               dfi_events *events)
{
    if (!dfi_context_is_closure(ctx)) {
        return DUOFORGE_OK;
    }
    if (!dfi_closure_battle_supported(&dfi_support, b)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    dfi_run r = {ctx, b, draws, {0u, 0u, 0u, 0u}, 0u, 0u, 0u, false, DFI_RESULT_NONE, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}, events, UINT32_MAX, false, DFI_MOVE_TARGET_NONE};
    dfi_init_speeds(&r);
    /* The leads entered one by one (insertChoice updated each speed); their
     * entries run together. */
    duoforge_status st = dfi_update_speeds(&r);
    if (st != DUOFORGE_OK) {
        return st;
    }
    uint32_t entering = 0u;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        entering |= dfi_at(b, flat) != NULL ? 1u << flat : 0u; /* their [switch] lines came first */
    }
    st = dfi_run_entries(&r, entering);
    if (st != DUOFORGE_OK) {
        return st;
    }
    /* The runSwitch action's epilogue runs its Update (sim/battle.ts:2860-2861). */
    st = r.ended ? DUOFORGE_OK : dfi_update(&r);
    if (st != DUOFORGE_OK) {
        return st;
    }
    return r.ended ? DUOFORGE_E_INVARIANT : DUOFORGE_OK; /* nothing at the start can end the battle */
}

/* A TURN or REPLACEMENT bundle as queued actions, sorted like
 * commitChoices and the beforeTurn epilogue. */
static duoforge_status dfi_queue_choices(dfi_run *r, const duoforge_side_choice responses[DUOFORGE_SIDE_COUNT],
                                         bool replacement)
{
    struct duoforge_battle *b = r->b;
    /* The actions in the reference's order of addition: side 0 slot a, b,
     * then side 1 (sim/battle.ts:2998-3022); a pass adds none. */
    b->queue_len = 0u;
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const bool requested = ((uint32_t)b->request_mask >> s & 1u) != 0u;
        for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
            dfi_slot_cmd c = {0u, 0u, 0u, 0u, 0u};
            if (requested) {
                const duoforge_slot_command *sc = &responses[s].slots[slot];
                c = (dfi_slot_cmd){sc->kind, sc->move_slot, sc->target, sc->mega, sc->reserve};
            } else if (b->sides[s].sealed != 0u) {
                c = b->sides[s].sealed_cmds[slot];
            }
            if (c.kind == DFI_SLOT_PASS && replacement && requested &&
                ((uint32_t)b->sides[s].requested_slots >> slot & 1u) != 0u) {
                /* A pass adds no action (resolveAction), so a fainted
                 * position keeps checkFainted's switch flag. */
                const dfi_member *m = dfi_at(b, s * 2u + slot);
                if (m != NULL && m->hp == 0u) {
                    b->sides[s].positions[slot].switch_flag = (uint8_t)DFI_SWITCH_FAINTED;
                }
            }
            if (c.kind == DFI_SLOT_NONE || c.kind == DFI_SLOT_PASS) {
                continue;
            }
            uint32_t kind = DFI_Q_MOVE;
            if (c.kind == DFI_SLOT_SWITCH) {
                if (dfi_support.switching == 0u) {
                    return DUOFORGE_E_UNSUPPORTED;
                }
                kind = replacement ? DFI_Q_SWITCH_IN : DFI_Q_SWITCH;
            } else if (c.kind != DFI_SLOT_MOVE || replacement) {
                return DUOFORGE_E_UNSUPPORTED;
            }
            const bool move = kind == DFI_Q_MOVE;
            if (move && c.mega != 0u) {
                /* resolveAction unshifts the megaEvo action before the move. */
                if (dfi_support.mega_evolution == 0u) {
                    return DUOFORGE_E_UNSUPPORTED;
                }
                b->queue[b->queue_len] = (dfi_queue_record){b->sides[s].positions[slot].activation_id,
                                                            (uint8_t)DFI_Q_MEGA, (uint8_t)s, (uint8_t)slot, 0u, 0u,
                                                            0u};
                b->queue_len = (uint8_t)((uint32_t)b->queue_len + 1u); /* wide-operands-reviewed: <= 6 */
            }
            b->queue[b->queue_len] = (dfi_queue_record){
                kind == DFI_Q_SWITCH_IN ? 0u : b->sides[s].positions[slot].activation_id, (uint8_t)kind, (uint8_t)s,
                (uint8_t)slot, move ? c.move_slot : 0u, move ? c.target : 0u, move ? 0u : c.reserve};
            b->queue_len = (uint8_t)((uint32_t)b->queue_len + 1u); /* wide-operands-reviewed: <= 6 */
        }
    }
    duoforge_status st = DUOFORGE_OK;
    if (!replacement) {
        b->queue[b->queue_len] = (dfi_queue_record){0u, (uint8_t)DFI_Q_RESIDUAL, 0u, 0u, 0u, 0u, 0u};
        b->queue_len = (uint8_t)((uint32_t)b->queue_len + 1u); /* wide-operands-reviewed: <= 5 */
    }
    /* Sorted when the choices are committed; in a turn again after the
     * beforeTurn action, whose epilogue sorts before a first move
     * (sim/battle.ts:2940-2947, 2917-2926). A replacement has no beforeTurn. */
    if (b->queue_len > 0u) {
        st = dfi_sort_queue(r);
    }
    /* The beforeTurn action's epilogue runs its Update first
     * (sim/battle.ts:2860-2861). */
    if (st == DUOFORGE_OK && !replacement) {
        st = dfi_update(r);
    }
    if (st == DUOFORGE_OK && !replacement && b->queue[0].kind == DFI_Q_MOVE) {
        st = dfi_sort_queue(r);
    }
    return st;
}

duoforge_status dfi_turn_run(const duoforge_context *ctx, struct duoforge_battle *b,
                             const duoforge_side_choice responses[DUOFORGE_SIDE_COUNT], dfi_draws *draws,
                             dfi_events *events)
{
    const bool replacement = b->boundary_kind == DUOFORGE_BOUNDARY_REPLACEMENT;
    const bool pivot = b->boundary_kind == DUOFORGE_BOUNDARY_PIVOT;
    if (!dfi_context_is_closure(ctx) || (b->boundary_kind != DUOFORGE_BOUNDARY_TURN && !replacement && !pivot)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    if (!dfi_closure_battle_supported(&dfi_support, b) || ((replacement || pivot) && dfi_support.switching == 0u)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    dfi_run r = {ctx, b, draws, {0u, 0u, 0u, 0u}, 0u, 0u, 0u, false, DFI_RESULT_NONE, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}, events, UINT32_MAX, false, DFI_MOVE_TARGET_NONE};
    dfi_init_speeds(&r);
    duoforge_status st = DUOFORGE_OK;
    uint32_t exits = 0u; /* Emergency Exit after the residual action */
    if (pivot) {
        st = dfi_resume_pivot(&r, responses);
    } else {
        st = dfi_queue_choices(&r, responses, replacement);
    }
    if (st != DUOFORGE_OK) {
        return st;
    }
    while (b->queue_len > 0u) {
        dfi_queue_record q;
        dfi_queue_pop(b, &q);
        if (q.kind == DFI_Q_MOVE) {
            bool ran = false;
            st = dfi_run_move(&r, &q, &ran);
            if (st != DUOFORGE_OK) {
                return st;
            }
            if (!ran) {
                continue; /* runAction returned before its epilogue */
            }
            /* AfterMove after a used move: White Herb's onAnyAfterMove (Team
             * C; sim/battle-actions.ts:311-312). runEvent collects the Any
             * handlers only while the user or runMove's target is active
             * (sim/battle.ts:1053), and a Pokemon whose faint the hit loop
             * showed is not (:2566). With a spread move's undrawn target that
             * is unknown: E_UNSUPPORTED when the handlers would do anything
             * (with the data only a Rocky Helmet makes the user faint there,
             * against a single-target contact move). */
            if (r.move_used) {
                const uint32_t user = (uint32_t)q.side * 2u + (uint32_t)q.slot;
                bool collected = true;
                if (dfi_faint_shown(&r, user)) {
                    if (r.move_target == DFI_MOVE_TARGET_SPREAD && dfi_herbs_matter(&r)) {
                        return DUOFORGE_E_UNSUPPORTED;
                    }
                    collected = r.move_target < DFI_POSITIONS && !dfi_faint_shown(&r, r.move_target);
                }
                if (collected) {
                    st = dfi_herb_event(&r, user);
                    if (st != DUOFORGE_OK) {
                        return st;
                    }
                }
            }
        } else if (q.kind == DFI_Q_SWITCH || q.kind == DFI_Q_SWITCH_IN) {
            st = dfi_run_switch(&r, &q);
            if (st != DUOFORGE_OK) {
                return st;
            }
        } else if (q.kind == DFI_Q_RUN_SWITCH) {
            /* runSwitch takes every entry queued right behind it. */
            uint32_t entering = 1u << ((uint32_t)q.side * 2u + (uint32_t)q.slot);
            while (b->queue_len > 0u && b->queue[0].kind == DFI_Q_RUN_SWITCH) {
                dfi_queue_pop(b, &q);
                entering |= 1u << ((uint32_t)q.side * 2u + (uint32_t)q.slot);
            }
            st = dfi_run_entries(&r, entering);
            if (st != DUOFORGE_OK) {
                return st;
            }
        } else if (q.kind == DFI_Q_MEGA) {
            st = dfi_run_mega(&r, &q);
            if (st != DUOFORGE_OK) {
                return st;
            }
        } else if (q.kind == DFI_Q_RESIDUAL) {
            st = dfi_residual(&r);
            if (st != DUOFORGE_OK) {
                return st;
            }
        } else {
            return DUOFORGE_E_UNSUPPORTED;
        }
        /* The epilogue: faints and the win rule; before a further
         * replacement nothing else; before a move action, speeds and
         * priorities are recomputed and the rest of the queue is sorted. */
        dfi_process_faints(&r);
        if (r.ended) {
            return dfi_terminal(&r);
        }
        if (b->queue_len > 0u && b->queue[0].kind == DFI_Q_SWITCH_IN) {
            continue;
        }
        st = dfi_update(&r); /* sim/battle.ts:2860-2861 */
        if (st != DUOFORGE_OK) {
            return st;
        }
        if (q.kind == DFI_Q_RESIDUAL) {
            /* sim/battle.ts:2862-2867: after the Update, so a Sitrus Berry
             * eaten there keeps its holder in. */
            for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
                if (dfi_exits(b, flat, r.residual_hp[flat])) {
                    exits |= 1u << flat;
                    const duoforge_event e = dfi_ev(DUOFORGE_EVENT_ACTIVATE, flat, DUOFORGE_CAUSE_ABILITY,
                                                    1u + DFI_ABILITY_EMERGENCYEXIT, DUOFORGE_NO_POSITION);
                    dfi_emit(&r, &e); /* [-activate] ability: Emergency Exit */
                }
            }
        }
        if (b->queue_len > 0u && dfi_pivot_pending(b)) {
            return dfi_pivot(b);
        }
        if (b->queue_len > 0u && b->queue[0].kind == DFI_Q_MOVE) {
            st = dfi_sort_queue(&r);
            if (st != DUOFORGE_OK) {
                return st;
            }
        }
    }
    return dfi_finish_turn(&r, exits);
}
