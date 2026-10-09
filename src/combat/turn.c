#include "combat/turn.h"

#include "combat/ability_family.h"
#include "combat/damage_chain.h"
#include "combat/multiaccuracy.h"
#include "combat/residual_order.h"
#include "combat/events.h"
#include "combat/item_family.h"
#include "combat/move_rules.h"
#include "combat/power_trip.h"
#include "combat/secondary_rolls.h"

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
    /* move.hit (step G33): the hit of a multi-hit move that is being made, 1 for every other move. */
    uint32_t hit_index;
    /* step G46: the positions whose switch flag (forceSwitchFlag) a forced switch set and that have not been dragged in
     * yet (bit flat). Transient: it lives in the run, never in the state, and only the phazing step after the action
     * clears it. Emergency Exit and Eject Button ignore such a holder (Champions abilities.ts:24, items.ts:270). */
    uint32_t drag_pending;
    /* step G56: the positions whose lockedmove (Outrage, Thrash, Petal Dance) duration is 2 in this step: started, or
     * restarted with a count of 2 or more (onRestart). Transient, like drag_pending; read and cleared by the AfterMove of the use (the
     * count goes down there, so no residual of a later call needs it). */
    uint32_t lock_restarted;
    /* step G42: the classification of the current move action's result (DFI_MRES_*, bits; 0 = none seen). */
    uint32_t mres;
    /* Step G45, Moxie: the cause of the last faint queued (faintData, the last of faintQueue, sim/battle.ts:2549-2601): the
     * flat position of the Pokemon that caused it, and whether it is the direct damage of a Move (effect.effectType 'Move').
     * Read only while faint_count is not 0; every queued faint sets both.
     * Run-scoped scratch, not state: they are set and read inside one step's dfi_run (between the faint announcement and
     * AfterFaint, or the process of the same action), never saved in the battle, the codec or the digest. The epilogue of
     * every action runs dfi_process_faints before the step can end (a PIVOT boundary included), which resets faint_count, so
     * the fields are dead at a step boundary. If that ever stopped being true they would be state: stop and report. */
    uint32_t last_faint_by;
    bool last_faint_move;
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
    /* The Mega forme is that of the pair (base forme, stone): the member still holds the stone (a Mega Stone is never
     * taken from its own species, dfi_item_takeable). */
    return m->is_mega != 0u ? &dfi_pool_formes[dfi_mega_of(m->species_id, m->item)] : &dfi_pool_formes[m->species_id];
}

/* The member's types now (Pokemon.getTypes): its forme's, or the one type that Soak set (setType, sim/pokemon.ts:2109;
 * the POOL tail's soak_type of the member, zero under every other kind), which lasts until the Pokemon leaves the field,
 * faints or Mega Evolves (setSpecies resets the types, sim/pokemon.ts:1392). `m` is a member of `b`. */
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

static bool dfi_has_type(const struct duoforge_battle *b, const dfi_member *m, uint32_t type)
{
    uint32_t t[2];
    dfi_types_of(b, m, t);
    return t[0] == type || t[1] == type;
}

static bool dfi_ability(const struct duoforge_battle *b, const dfi_member *m, uint32_t id);

/* isGrounded with the data (sim/pokemon.ts:2148-2160): not a Flying type and not a Levitate holder. Gravity, Ingrain,
 * Smack Down, Iron Ball, Air Balloon, Magnet Rise and Telekinesis are unmarked rows, so no battle has them; Eelevate is
 * an unmarked ability. The ability is the current one (a Mega's, or one that Trace copied). */
static bool dfi_grounded(const struct duoforge_battle *b, const dfi_member *m)
{
    return !dfi_has_type(b, m, DFI_TYPE_FLYING) && !dfi_ability(b, m, DFI_ABILITY_LEVITATE);
}

/* The FIELD_START / FIELD_END detail of a terrain (DUOFORGE_FIELD_*). */
static uint32_t dfi_terrain_field_detail(uint32_t terrain)
{
    return terrain == DFI_TERRAIN_GRASSY     ? DUOFORGE_FIELD_GRASSY_TERRAIN
           : terrain == DFI_TERRAIN_PSYCHIC  ? DUOFORGE_FIELD_PSYCHIC_TERRAIN
           : terrain == DFI_TERRAIN_ELECTRIC ? DUOFORGE_FIELD_ELECTRIC_TERRAIN
                                             : DUOFORGE_FIELD_MISTY_TERRAIN;
}

/* eachEvent('TerrainChange'), defined with the seeds below: a terrain that starts or ends runs it. */
static duoforge_status dfi_terrain_change(dfi_run *r);

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

/* Clear Body's -fail|holder|unboost|[from] ability: Clear Body|[of] holder (step G30, data/abilities.ts:523-542): the
 * FAIL event with the ability as its cause and the holder as the `other`, as Inner Focus's (step G22). */
static void dfi_clear_body_block(dfi_run *r, uint32_t flat)
{
    const duoforge_event e = dfi_ev(DUOFORGE_EVENT_FAIL, flat, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_CLEARBODY, flat);
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

/* The move failed: -fail for the user, then [still] on its move line. */
static void dfi_fail_still(dfi_run *r, uint32_t user)
{
    dfi_emit_plain(r, DUOFORGE_EVENT_FAIL, user);
    dfi_still(r);
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

/* Whether the member has the Speed ability of the weather that is up: Swift Swim in rain, Chlorophyll in sun, Sand Rush
 * in a sandstorm, Slush Rush in snow (step G22; the callbacks are cited at dfi_speed_key). The weather is the
 * battle's: Hail is not in the format, and Primordial Sea and Desolate Land (also named by the Swift Swim and
 * Chlorophyll handlers) are not weathers of the state. */
static bool dfi_weather_speed_ability(const struct duoforge_battle *b, const dfi_member *m)
{
    return (b->weather == DFI_WEATHER_RAIN && dfi_ability(b, m, DFI_ABILITY_SWIFTSWIM)) ||
           (b->weather == DFI_WEATHER_SUN && dfi_ability(b, m, DFI_ABILITY_CHLOROPHYLL)) ||
           (b->weather == DFI_WEATHER_SAND && dfi_ability(b, m, DFI_ABILITY_SANDRUSH)) ||
           (b->weather == DFI_WEATHER_SNOW && dfi_ability(b, m, DFI_ABILITY_SLUSHRUSH));
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
    /* Sand Rush, Swift Swim, Slush Rush and Chlorophyll (step G22, POOL data): onModifySpe chainModify(2) while their
     * weather is up (data/abilities.ts:3974-3979 sandrush, 4808-4813 swiftswim, 4347-4352 slushrush, 512-517
     * chlorophyll; the Champions mod has no entry of any of them). The holder has one ability, so at most one of the
     * four counts. Field.isWeather / pokemon.effectiveWeather read the weather that is up; no Cloud Nine, Air Lock,
     * Utility Umbrella or Mega Sol is in a battle (unmarked or not in the pool: tests/test_pool_weather.c), so nothing
     * suppresses it. Like the items and Unburden, only a standing holder counts: a fainted one has its raw Speed (the
     * same isActive rule as above, the ability handler of a Pokemon that is not active is ignored). */
    if (active && dfi_weather_speed_ability(b, m)) {
        if (!dfi_chain_modify(chain, 8192u, &chain)) {
            return DUOFORGE_E_INVARIANT;
        }
    }
    if (chain != 4096u) {
        spe = dfi_modify(spe, chain); /* spe <= 4 * 65535, chain <= 12 * 4096 */
    }
    if (active && m->status == DFI_STATUS_PAR) {
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
 * without this function and dfi_speed_key being looked at. */
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

/* The type a move has when it is used (useMoveInner, sim/battle-actions.ts:430-438: the move's own onModifyType first, then
 * the abilities'): Struggle is typeless; an -ate ability (the ATE family, decision 0015: onModifyType at priority -1)
 * turns a Normal move into its type before immunity and STAB, except the moves of its noModifyType list; Weather Ball
 * turns Water in rain, Fire under sun, Rock in sand, Ice in snow (data/moves.ts:20711-20717); Terrain Pulse (step G25,
 * data/moves.ts:19273-19291) takes the type of the terrain for a grounded user. The redirection of Lightning Rod reads the
 * type of this call (getMoveTargets runs after ModifyType, sim/pokemon.ts:829-831), so a Terrain Pulse in Electric Terrain is
 * drawn to it, which the move's table type (Normal) would not say. */
static uint32_t dfi_move_type_now(const struct duoforge_battle *b, const dfi_member *m, const dfi_move_data *md)
{
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
    if (md->special == DFI_SPECIAL_WEATHER_BALL && b->weather == DFI_WEATHER_RAIN) {
        move_type = DFI_TYPE_WATER;
    } else if (md->special == DFI_SPECIAL_WEATHER_BALL && b->weather == DFI_WEATHER_SUN) {
        move_type = DFI_TYPE_FIRE;
    } else if (md->special == DFI_SPECIAL_WEATHER_BALL && b->weather == DFI_WEATHER_SAND) {
        move_type = DFI_TYPE_ROCK;
    } else if (md->special == DFI_SPECIAL_WEATHER_BALL && b->weather == DFI_WEATHER_SNOW) {
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
    /* Guard Dog (step G46, data/abilities.ts:1727-1744, onTryBoost of the holder, breakable): an Intimidate change of Attack
     * is deleted and the holder's Attack rises by 1 instead (`this.boost({ atk: 1 }, target, target, null, ...)`: a boost
     * with no effect, so its line has no [from]). Its line is the nested boost's; nothing shows for the deleted drop. */
    if (effect.cause == DUOFORGE_CAUSE_ABILITY && effect.id2 == 1u + DFI_ABILITY_INTIMIDATE &&
        boosts[DFI_STAGE_ATK] != DFI_BIAS6 && capped[DFI_STAGE_ATK] != DFI_BIAS6 && dfi_ability(r->b, m, DFI_ABILITY_GUARDDOG)) {
        veil[DFI_STAGE_ATK] = true;
        static const uint8_t guard_dog_atk_up[DFI_STAT_STAGE_COUNT] = {7u, 6u, 6u, 6u, 6u, 6u, 6u};
        /* The nested boost's effect is the running handler, Guard Dog (boost() defaults to this.effect): its line is
         * -ability|holder|Guard Dog|boost, then the -boost line (sim/battle.ts boost). */
        (void)dfi_boost(r, flat, guard_dog_atk_up, flat, dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_GUARDDOG, DFI_BOOST_PRIMARY));
    }
    /* Inner Focus (step G22, POOL data, data/abilities.ts:2157-2162): TryBoost, a change that the effect named
     * Intimidate would make to Attack (boost.atk is set: a change the cap already took to 0 is not) is deleted, and
     * -fail|holder|unboost|atk|[from] ability: Inner Focus|[of] holder shows. The Pokemon is no Grass type of a side
     * with Flower Veil, whose own TryBoost handler would race this one by Speed: no Inner Focus holder of the pool is
     * a Grass type (tools/datagen/pool_families.js checkG22). Breakable, like Flower Veil. */
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
     * (effect.secondaries). Like Clear Body it never meets a Flower Veil holder's handler: no forme of the pool with it is a
     * Grass type (tests/test_pool_g39.c). */
    if (source != flat && source != DFI_POSITIONS && boosts[DFI_STAGE_ATK] != DFI_BIAS6 && capped[DFI_STAGE_ATK] < DFI_BIAS6 &&
        dfi_ability(r->b, m, DFI_ABILITY_HYPERCUTTER)) {
        veil[DFI_STAGE_ATK] = true;
        if (!(effect.cause == DUOFORGE_CAUSE_MOVE && effect.mode == DFI_BOOST_SECONDARY)) {
            const duoforge_event e =
                dfi_ev(DUOFORGE_EVENT_FAIL, flat, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_HYPERCUTTER, flat);
            dfi_emit(r, &e); /* the Inner Focus line: it names the stat */
        }
    }
    /* Clear Body (step G30, data/abilities.ts:523-542, onTryBoost of the target itself): every drop that another Pokemon
     * causes is deleted, and the line shows unless the effect is a move's secondary (effect.secondaries) or Octolock
     * (not in the pool). Like Flower Veil it sees the drop after Contrary and the cap. A Grass type that has Clear Body
     * and stands next to a Flower Veil holder would need the two handlers' order: no forme of the pool is both
     * (tests/test_pool_g30.c checks it, and that nothing that Trace could copy it onto is Grass). */
    bool clear[DFI_STAT_STAGE_COUNT] = {false, false, false, false, false, false, false};
    if (source != flat && source != DFI_POSITIONS && dfi_ability(r->b, m, DFI_ABILITY_CLEARBODY)) {
        bool any = false;
        for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
            clear[i] = boosts[i] != DFI_BIAS6 && capped[i] < DFI_BIAS6;
            any = any || clear[i];
        }
        if (any && !(effect.cause == DUOFORGE_CAUSE_MOVE && effect.mode == DFI_BOOST_SECONDARY)) {
            dfi_clear_body_block(r, flat);
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
     * no forme of the pool is (tools/datagen/pool_families.js checkG33). */
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
        if (boosts[i] == DFI_BIAS6 || veil[i] || clear[i] || mirror[i]) {
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

/* getDamage and the Champions modifyDamage (sim/battle-actions.ts:1585-1720,
 * data/mods/champions/scripts.ts:196-312) for a turn-core move: CRIT and
 * DAMAGE_ROLL draws in that order. */
static duoforge_status dfi_get_damage(dfi_run *r, uint32_t user, uint32_t target, const dfi_move_data *md,
                                      uint32_t move_type, bool spread, uint32_t *out)
{
    static const uint32_t crit_mult[5] = {0u, 24u, 8u, 2u, 1u};
    const dfi_member *a = dfi_at(r->b, user);
    const dfi_member *d = dfi_at(r->b, target);
    /* Super Fang's damageCallback (step G39, data/moves.ts:18461-18476): getDamage returns clampIntRange(target.hp / 2, 1)
     * before the critical hit roll and the formula (sim/battle-actions.ts:1585-1600), so there is no CRIT or DAMAGE_ROLL
     * draw, no modifier of the damage chain (Multiscale, Friend Guard, the screens, the berries and the items are in
     * modifyDamage) and none of its effectiveness lines; the type immunity (Ghost) was judged before, in the hit steps. */
    if (md->special == DFI_SPECIAL_SUPER_FANG) {
        const uint32_t half = (uint32_t)d->hp / 2u;
        *out = half < 1u ? 1u : half;
        return DUOFORGE_OK;
    }
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
    } else if (md->special == DFI_SPECIAL_STOMPING_TANTRUM) {
        /* basePowerCallback (data/moves.ts:18054-18058): x2 when the user's last move result is FALSE (strictly; null is
         * not a failure). An unclassified last result is refused, never guessed (step G42). */
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
    } else if (md->special == DFI_SPECIAL_POWER_TRIP) {
        /* Power Trip's basePowerCallback (step G44, data/moves.ts:13851-13859): 20 + 20 x the user's positiveBoosts(), the sum
         * of its positive stages (Pokemon.positiveBoosts, sim/pokemon.ts:1201-1208). A stage is stored biased by 6. */
        const uint32_t positive = dfi_power_trip_positive_stages(ap->stages);
        power = (uint32_t)md->base_power + 20u * positive;
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
    const uint32_t bp_move = (uint32_t)(md - dfi_pool_moves); /* wide-operands-reviewed: a pointer into the move table, below DFI_POOL_MOVE_COUNT */
    const uint32_t bp_flags2 = bp_move != DFI_MOVE_STRUGGLE ? (uint32_t)dfi_pool_move_flags2[bp_move] : 0u;
    /* Technician (step G34, data/abilities.ts:4916-4930): onBasePower at priority 30, the first handler, so the chain is
     * still 4096 when it judges `this.modify(basePower, this.event.modifier)`: the move's own power after its callback.
     * 1.5 for 60 or less. */
    if (dfi_ability(r->b, a, DFI_ABILITY_TECHNICIAN) && power <= 60u) {
        ok = dfi_chain_modify(bp_chain, 6144u, &bp_chain);
    }
    /* An -ate ability (the ATE family: Aerilate, Pixilate and Refrigerate,
     * decision 0015): a Normal move it turned into its type gets 4915/4096
     * (data/abilities.ts, onBasePowerPriority 23: first). */
    if (!dfi_ate_excluded(md) && dfi_ate_boosts_fam(dfi_ability_family_now(r->b, a), md->type, move_type)) {
        ok = ok && dfi_chain_modify(bp_chain, DFI_ATE_MODIFIER, &bp_chain);
    }
    /* Iron Fist (step G34, data/abilities.ts:2236-2248, priority 23 like the -ate abilities, which it never meets: one
     * ability): the punch flag, 4915/4096. */
    if ((bp_flags2 & DFI_MOVE_FLAG2_PUNCH) != 0u && dfi_ability(r->b, a, DFI_ABILITY_IRONFIST)) {
        ok = ok && dfi_chain_modify(bp_chain, 4915u, &bp_chain);
    }
    if (dfi_ability(r->b, a, DFI_ABILITY_TOUGHCLAWS) && (md->flags & DFI_MOVE_FLAG_CONTACT) != 0u) {
        ok = dfi_chain_modify(bp_chain, 5325u, &bp_chain); /* onBasePowerPriority 21: first */
    }
    /* Fairy Aura (the Mega Floette's ability, onAnyBasePower priority 20: after Tough Claws, before the items): a
     * Fairy move of anyone on the field, unless it targets its own user, 5448/4096 once. */
    if (move_type == DFI_TYPE_FAIRY && user != target && dfi_fairy_aura_on_field(r->b)) {
        ok = ok && dfi_chain_modify(bp_chain, DFI_FAIRY_AURA_MODIFIER, &bp_chain);
    }
    /* Sharpness (step G34, data/abilities.ts:4174-4186, priority 19: after Fairy Aura's 20, before the items' 15): the slicing
     * flag, x1.5. */
    if ((bp_flags2 & DFI_MOVE_FLAG2_SLICING) != 0u && dfi_ability(r->b, a, DFI_ABILITY_SHARPNESS)) {
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
    if (md == &dfi_pool_moves[DFI_MOVE_EARTHQUAKE] && r->b->terrain == DFI_TERRAIN_GRASSY && dfi_grounded(r->b, d)) {
        ok = ok && dfi_chain_modify(bp_chain, 2048u, &bp_chain);
    }
    /* Psychic Terrain (Team C): 5325/4096 for a grounded user's Psychic move
     * (onBasePowerPriority 6, like Grassy Terrain's, which cannot be up at
     * the same time). */
    if (move_type == DFI_TYPE_PSYCHIC && r->b->terrain == DFI_TERRAIN_PSYCHIC && dfi_grounded(r->b, a)) {
        ok = ok && dfi_chain_modify(bp_chain, 5325u, &bp_chain);
    }
    /* Electric Terrain (step G25, data/moves.ts:4520-4527): 5325/4096 for a grounded user's Electric move, the same
     * handler slot (priority 6). Misty Terrain (:12175-12181): chainModify(0.5), 2048/4096, for a Dragon move at a grounded
     * target. */
    if (move_type == DFI_TYPE_ELECTRIC && r->b->terrain == DFI_TERRAIN_ELECTRIC && dfi_grounded(r->b, a)) {
        ok = ok && dfi_chain_modify(bp_chain, 5325u, &bp_chain);
    }
    if (move_type == DFI_TYPE_DRAGON && r->b->terrain == DFI_TERRAIN_MISTY && dfi_grounded(r->b, d)) {
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
    if (md->special == DFI_SPECIAL_SOLAR_BEAM &&
        (r->b->weather == DFI_WEATHER_RAIN || r->b->weather == DFI_WEATHER_SAND || r->b->weather == DFI_WEATHER_SNOW)) {
        ok = ok && dfi_chain_modify(bp_chain, 2048u, &bp_chain);
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
    /* Solar Power (step G39, data/abilities.ts:4396-4413, onModifySpA priority 5): x1.5 for the Special Attack stat in sun
     * (Desolate Land is not a weather of the state). It is the holder's one ability, so it never meets a pinch ability or
     * Flash Fire, the other chained ability modifiers. */
    if (atk_index == DFI_STAGE_SPA && r->b->weather == DFI_WEATHER_SUN && dfi_ability(r->b, a, DFI_ABILITY_SOLARPOWER)) {
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
    uint32_t mlist[DFI_MODIFY_DAMAGE_MAX] = {0u}; /* and their values, for the commutation test below */
    if (dfi_holds(r->b, a, DFI_ITEM_LIFEORB)) {
        ok = dfi_chain_modify(chain, 5324u, &chain);
        mlist[mods] = 5324u;
        mods += 1u;
    }
    /* Expert Belt's onModifyDamage (step G28, data/items.ts:1901-1914): 4915/4096 when the hit is super effective
     * (typeMod > 0: the combined type effectiveness above the neutral one). */
    if (dfi_holds(r->b, a, DFI_ITEM_EXPERTBELT) && mod > DFI_BIAS6) {
        ok = ok && dfi_chain_modify(chain, 4915u, &chain);
        mlist[mods] = 4915u;
        mods += 1u;
    }
    /* A resist berry (the RESIST_BERRY family: Chople Berry and the sixteen
     * others, decision 0015; combat/item_family.h) is eaten by a super
     * effective hit of its type, the Normal berry by any Normal hit. */
    const uint32_t berry_item = dfi_item_code(r->b, d);
    if (dfi_resist_berry_applies(berry_item, move_type, mod) && !dfi_unnerved(r->b, target)) {
        dfi_use_item(r, target); /* [-enditem] [eat] */
        duoforge_event weaken =
            dfi_ev(DUOFORGE_EVENT_ITEM_END, target, DUOFORGE_CAUSE_NONE, berry_item, DUOFORGE_NO_POSITION);
        weaken.detail = 1u;
        dfi_emit(r, &weaken); /* [-enditem] [weaken] */
        ok = ok && dfi_chain_modify(chain, DFI_RESIST_BERRY_MODIFIER, &chain);
        mlist[mods] = DFI_RESIST_BERRY_MODIFIER;
        mods += 1u;
    }
    /* Aurora Veil (step G20, data/moves.ts:846-860) weakens both categories by the same 2732/4096 and returns without an
     * effect when the target's side has the screen of the move's category (so the two never multiply): the test is one
     * 2732 for a screen of the category or Aurora Veil. A critical hit and `infiltrates` skip all three: the move's
     * own `infiltrates` field is not modelled (the generator refuses it), and Infiltrator (step G39, data/abilities.ts:
     * 2131-2139, onModifyMove) sets it on every move of its holder. */
    if (!crit && target != user && !dfi_ability(r->b, a, DFI_ABILITY_INFILTRATOR) &&
        ((physical && ds->reflect_turns != 0u) ||
         (md->category == DFI_CATEGORY_SPECIAL && ds->light_screen_turns != 0u) ||
         r->b->tail.sides[target / 2u].aurora_veil_turns != 0u)) {
        ok = ok && dfi_chain_modify(chain, 2732u, &chain);
        mlist[mods] = 2732u;
        mods += 1u;
    }
    /* Glaive Rush's onSourceModifyDamage on the target (data/moves.ts:6647-6678): chainModify(2). With a Life Orb attacker,
     * a resist berry and a screen all in the chain the four modifiers do not commute (3552 or 3551 by their order, the
     * handlers' speeds and a tie draw), a case that this build does not model. */
    if (r->b->tail.sides[target / 2u].positions[target % 2u].glaive_rush != 0u) {
        ok = ok && dfi_chain_modify(chain, 8192u, &chain);
        mlist[mods] = 8192u;
        mods += 1u;
    }
    /* Solid Rock and Multiscale (step G34, data/abilities.ts:4414-4425 and 2760-2771, onSourceModifyDamage of the target,
     * both breakable and Mold Breaker is not marked): x0.75 on a super effective hit (typeMod > 0), x0.5 at full HP. */
    if (dfi_ability(r->b, d, DFI_ABILITY_SOLIDROCK) && mod > DFI_BIAS6) {
        ok = ok && dfi_chain_modify(chain, 3072u, &chain);
        mlist[mods] = 3072u;
        mods += 1u;
    }
    if (dfi_ability(r->b, d, DFI_ABILITY_MULTISCALE) && d->hp >= d->hp_max) {
        ok = ok && dfi_chain_modify(chain, 2048u, &chain);
        mlist[mods] = 2048u;
        mods += 1u;
    }
    /* Aura Guard (Mega batch 2, data/abilities.ts:310-319, onSourceModifyDamage of the target, breakable and Mold Breaker is
     * not marked; the Champions mod has no entry): x0.5 (chainModify(0.5) = 2048/4096) on a move with the contact flag, like
     * the contact half of Fluffy. It is the target's one ability, so with Solid Rock and Multiscale a hit has at most one of
     * the three. */
    if (dfi_ability(r->b, d, DFI_ABILITY_AURAGUARD) && (md->flags & DFI_MOVE_FLAG_CONTACT) != 0u) {
        ok = ok && dfi_chain_modify(chain, 2048u, &chain);
        mlist[mods] = 2048u;
        mods += 1u;
    }
    /* Punk Rock's onSourceModifyDamage (step G45, data/abilities.ts:3597-3602, breakable): chainModify(0.5) on a sound move
     * against the holder. It is the target's one ability, so with Solid Rock, Multiscale and Aura Guard a hit has at most one. */
    if (dfi_ability(r->b, d, DFI_ABILITY_PUNKROCK) && md->special != DFI_SPECIAL_STRUGGLE &&
        (dfi_pool_move_flags2[(uint32_t)(md - dfi_pool_moves)] & DFI_MOVE_FLAG2_SOUND) != 0u) { /* wide-operands-reviewed: a pointer into the move table */
        ok = ok && dfi_chain_modify(chain, 2048u, &chain);
        mlist[mods] = 2048u;
        mods += 1u;
    }
    /* Friend Guard (step G35, data/abilities.ts:1533-1540, onAnyModifyDamage, breakable and Mold Breaker is not marked): the
     * target's partner, when it stands and holds the ability, weakens every hit on the target by x0.75 (3072/4096). The handler
     * is any Pokemon's, so the attacker's own partner is a holder too when it is the one hit (a spread move on an ally), and the
     * holder itself is not weakened (target !== holder). A fainted holder does not run (runEvent skips the fainted). */
    const dfi_member *partner = dfi_at(r->b, target ^ 1u);
    if (partner != NULL && partner->hp != 0u && dfi_ability(r->b, partner, DFI_ABILITY_FRIENDGUARD)) {
        ok = ok && dfi_chain_modify(chain, 3072u, &chain);
        mlist[mods] = 3072u;
        mods += 1u;
    }
    /* The handlers have no order and priority 0, so runEvent sorts them by their holders' speed, then by subOrder (a screen, a
     * side condition, has no speed and is last); this build does not compute that order (a follow-up, combat/damage_chain.h), so
     * the modifiers must chain to one value in every order. Pairs and triples of Life Orb, Expert Belt, a resist berry, a screen,
     * Solid Rock, Multiscale and Friend Guard do (checked by dfi_mods_commute at its own test, tests/test_pool_g34.c, and here for
     * every hit); the combinations that do not (Glaive Rush's x2 with three others, an Expert Belt with a berry and Glaive Rush, a
     * Solid Rock with them) are E_UNSUPPORTED. */
    if (mods >= 3u && !dfi_mods_commute(mlist, mods)) {
        return DUOFORGE_E_UNSUPPORTED;
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
            r->last_faint_by = DFI_POSITIONS; /* not a move's damage unless the caller says so (dfi_run_move's hit loop) */
            r->last_faint_move = false;
        }
    }
    return DUOFORGE_OK;
}

/* runStatusImmunity('psn') (Team C; Toxic asks for 'psn' too, sim/pokemon.ts:1713): a type whose chart entry carries the
 * psn key, Poison and Steel (data/typechart.ts). Corrosion (a Poison-type user's way past it) is not marked. */
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

static duoforge_status dfi_try_status(dfi_run *r, uint32_t flat, uint32_t status, uint32_t user, uint32_t move_id,
                                      uint32_t origin, uint32_t from_ability);
static duoforge_status dfi_after_set_status(dfi_run *r, uint32_t flat, uint32_t status, uint32_t source, uint32_t origin);

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
    if ((status == DFI_STATUS_BRN && dfi_has_type(r->b, m, DFI_TYPE_FIRE)) ||
        (status == DFI_STATUS_PAR && dfi_has_type(r->b, m, DFI_TYPE_ELECTRIC)) ||
        (status == DFI_STATUS_FRZ && (dfi_has_type(r->b, m, DFI_TYPE_ICE) || r->b->weather == DFI_WEATHER_SUN)) ||
        ((status == DFI_STATUS_PSN || status == DFI_STATUS_TOX) && dfi_poison_immune(r->b, m))) {
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
    if (user != flat && dfi_flower_veil_holder(r->b, flat, &holder)) {
        /* the block line: effect.effectType 'Move' without secondaries, or the name Synchronize, which the effect of Synchronize
         * does not have (data/abilities.ts:1438): a move's own status alone shows it */
        if (origin == DFI_ORIGIN_MOVE) {
            dfi_flower_veil_block(r, flat, holder);
        }
        return DUOFORGE_OK;
    }
    /* The terrains' onSetStatus (step G25, data/moves.ts:4497-4551 and 12151-12205). The field's handlers have no
     * speed (Battle.resolvePriority gives a speed to a Pokemon's effects only, sim/battle.ts:1001-1003), so they run after
     * every handler of an ability above (the speed of a Pokemon is positive): a refusal by Thermal Exchange or Flower
     * Veil comes first and ends the event. Electric Terrain refuses sleep for a grounded Pokemon, Misty Terrain every
     * status; both return false, and show `-activate|target|move: X Terrain` only for a move's own status (Electric:
     * `effect.effectType === 'Move' && !effect.secondaries`; Misty: `effect.status`, which a secondary's move does not
     * have), and nothing for a secondary or an ability (Poison Touch) or an item. A flying Pokemon is not grounded. */
    if ((r->b->terrain == DFI_TERRAIN_MISTY || (r->b->terrain == DFI_TERRAIN_ELECTRIC && status == DFI_STATUS_SLP)) &&
        dfi_grounded(r->b, m)) {
        if (primary) {
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
        counter = 3u;
    }
    m->status = (uint8_t)status;          /* <= DFI_STATUS_TOX */
    m->status_counter = (uint8_t)counter; /* <= 3 */
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
static duoforge_status dfi_lum_berry(dfi_run *r, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    dfi_member *m = dfi_at(b, flat);
    if (m == NULL || m->hp == 0u || !dfi_holds(b, m, DFI_ITEM_LUMBERRY) || dfi_unnerved(b, flat)) {
        return DUOFORGE_OK;
    }
    dfi_use_item(r, flat);
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
 * attract and torment are not here: no volatile of either exists in the engine (Attract is unmarked, Torment is not
 * modelled), so no state can hold them. Each removal shows its own -end line through its condition's onEnd. */
static duoforge_status dfi_mental_herb(dfi_run *r, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    const dfi_member *m = dfi_at(b, flat);
    dfi_tail_pos *tail = &b->tail.sides[flat / 2u].positions[flat % 2u];
    if (m == NULL || m->hp == 0u || !dfi_holds(b, m, DFI_ITEM_MENTALHERB)) {
        return DUOFORGE_OK;
    }
    if (tail->taunt_turns == 0u && tail->encore_slot == 0u && tail->disable_slot == 0u && tail->heal_block_turns == 0u) {
        return DUOFORGE_OK;
    }
    dfi_use_item(r, flat);
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
            st = dfi_deal(r, flat, amount, DUOFORGE_CAUSE_MOVE, DFI_MOVE_STEALTHROCK, DUOFORGE_NO_POSITION);
        } else if (kind == DUOFORGE_SIDE_SPIKES) {
            if (dfi_grounded(b, m)) {
                static const uint8_t twenty_fourths[4] = {0u, 3u, 4u, 6u}; /* 1/8, 1/6, 1/4 of the maximum HP */
                uint32_t amount = ((uint32_t)twenty_fourths[ts->spikes] * m->hp_max) / 24u;
                amount = amount == 0u ? 1u : amount;
                st = dfi_deal(r, flat, amount, DUOFORGE_CAUSE_MOVE, DFI_MOVE_SPIKES, DUOFORGE_NO_POSITION);
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
         * (tests/test_pool_weather.c), Teravolt and Turboblaze are not in the pool, and a move with ignoreAbility has a
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
    if (r->b->terrain == DFI_TERRAIN_MISTY && dfi_grounded(r->b, m)) {
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
    if (m == NULL || m->hp == 0u || dfi_ability(b, m, DFI_ABILITY_SHADOWTAG) || dfi_has_type(b, m, DFI_TYPE_GHOST)) {
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

/* useItem with a position named in the line ([of] other: Red Card names the attacker, step G46). */
static void dfi_use_item_of(dfi_run *r, uint32_t flat, uint32_t other)
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
 * less (trueDuration > 1 returns). dfi_lock_remove is the silent removal (a faint, a switch, a sleep at the countdown: the
 * pin's clearVolatile and its onResidual delete, which have no onEnd). The locked move is the choice lock's or the charge's
 * too, so it is cleared only when neither holds. */
static void dfi_lock_remove(struct duoforge_battle *b, uint32_t flat)
{
    b->tail.sides[flat / 2u].positions[flat % 2u].lock_turns = 0u;
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
        dfi_emit_item_received(r, target, mine, move_id, DUOFORGE_NO_POSITION);
    } else {
        dfi_emit_item_left(r, target, yours, move_id, DUOFORGE_NO_POSITION);
    }
    dfi_set_held(b, user, yours);
    if (yours != 0u) {
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
    if (silent_enditem) {
        dfi_emit_item_left(r, target, yours, move_id, user);
    }
    dfi_emit_item_received(r, user, yours, move_id, target);
    return DUOFORGE_OK;
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

/* Imprison itself (the status move, target self): addVolatile('imprison'); a Pokemon that has it already fails
 * (`-fail`, the move line with [still]); otherwise `-start|user|move: Imprison` (the condition's onStart). */
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
    r->mres |= DFI_MRES_TRUE;
    return DUOFORGE_OK;
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
 * the confusion hit (effectType 'Move', as for the Sash, combat/item_family.h); recoil, items, status and weather are not.
 * Its onTryHit makes the holder immune to OHKO moves: none is modelled (the generator refuses the field), which
 * tests/test_pool_g39.c pins. The ability is breakable: Mold Breaker is not marked. */
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
static duoforge_status dfi_update(dfi_run *r)
{
    uint32_t bearers = 0u;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        /* the holders with an Update handler that can act: Sitrus Berry, and step G47's Lum Berry and Mental Herb */
        const bool bears = dfi_holds(r->b, dfi_at(r->b, flat), DFI_ITEM_SITRUSBERRY) ||
                           dfi_holds(r->b, dfi_at(r->b, flat), DFI_ITEM_LUMBERRY) ||
                           dfi_holds(r->b, dfi_at(r->b, flat), DFI_ITEM_MENTALHERB);
        bearers |= bears ? 1u << flat : 0u;
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
            !dfi_heal_blocked(r->b, flat) && !dfi_unnerved(r->b, flat)) {
            dfi_use_item(r, flat);
            dfi_heal(r, flat, (uint32_t)m->hp_max / 4u, DUOFORGE_CAUSE_ITEM, 1u + DFI_ITEM_SITRUSBERRY,
                     DUOFORGE_NO_POSITION);
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
 * false; the Champions mod has no entry) and Overcoat (step G30, data/abilities.ts:3108-3111). The others that give it
 * (Sand Force, Safety Goggles) or stop indirect damage (Magic Guard) are not marked in the support manifest,
 * so no battle holds one (tests/test_pool_weather.c checks that); marking one needs its immunity here. */
static bool dfi_sand_immune(const struct duoforge_battle *b, const dfi_member *m)
{
    if (dfi_ability(b, m, DFI_ABILITY_SANDRUSH) || dfi_ability(b, m, DFI_ABILITY_OVERCOAT) ||
        dfi_ability(b, m, DFI_ABILITY_SANDVEIL)) { /* Sand Veil: step G39, data/abilities.ts:4006-4022, onImmunity 'sandstorm' */
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

/* eachEvent('Weather') under rain (step G35, the onWeather of Rain Dish, data/abilities.ts:3759-3765): every active Pokemon
 * that has not fainted and holds Rain Dish heals baseMaxhp / 16 (at least 1) as [-heal] [from] ability: Rain Dish, in
 * eachEvent's order; a full-HP holder prints nothing (Battle.heal returns early) but is still in the sort, so two holders
 * that are tied in speed draw whatever their HP (the group is shuffled as a whole; the converter keeps the draws of two
 * holders, trace_to_c.py drop_reason). Primordial Sea is not in the format. */
static duoforge_status dfi_rain_dish(dfi_run *r)
{
    uint32_t bearers = 0u;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        const dfi_member *m = dfi_at(r->b, flat);
        if (m != NULL && m->hp != 0u && dfi_ability(r->b, m, DFI_ABILITY_RAINDISH)) {
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
                     1u + DFI_ABILITY_RAINDISH, DUOFORGE_NO_POSITION);
        }
    }
    return DUOFORGE_OK;
}

/* eachEvent('Weather') under sun (step G39, the onWeather of Solar Power, data/abilities.ts:4396-4413): every active Pokemon
 * that has not fainted and holds Solar Power takes baseMaxhp / 8 (at least 1) as -damage [from] ability: Solar Power [of] the holder
 * itself (damage(..., target, target): the source is printed, the pin's line has it), in eachEvent's order; two holders at one Speed draw the order as Rain Dish's do
 * (dfi_rain_dish). Desolate Land is not a weather of the state. */
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
        st = dfi_deal(r, flat, damage == 0u ? 1u : damage, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_SOLARPOWER, flat);
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

/* The AfterFaint event of faintMessages (sim/battle.ts:2600-2602, runEvent('AfterFaint', faintData.target, faintData.source,
 * faintData.effect, length)): length is the number of faints that this call shows (the queue's length when it began, faints
 * from `from` on), and the handler that runs is the source's onSourceAfterFaint, Moxie's (data/abilities.ts:2749-2759), when
 * the last faint's effect is a Move: this.boost({atk: length}, source), the source being the holder itself, so a fainted
 * holder gets nothing (Battle.boost, :2029). The caller has checked the win (no AfterFaint after a finished battle). */
static void dfi_after_faint(dfi_run *r, uint32_t length, bool by_move, uint32_t src)
{
    if (length == 0u || !by_move || src >= DFI_POSITIONS) {
        return;
    }
    const dfi_member *holder = dfi_at(r->b, src);
    if (!dfi_ability(r->b, holder, DFI_ABILITY_MOXIE) || holder->hp == 0u) {
        return;
    }
    uint8_t atk_up[DFI_STAT_STAGE_COUNT] = {6u, 6u, 6u, 6u, 6u, 6u, 6u}; /* biased by 6 */
    atk_up[DFI_STAGE_ATK] = (uint8_t)(6u + length); /* wide-operands-reviewed: length <= DFI_POSITIONS */
    (void)dfi_boost(r, src, atk_up, src, dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_MOXIE, DFI_BOOST_PRIMARY));
}

/* faintMessages and checkWin (sim/battle.ts:2535-2590, 404-415): the faints
 * of the action in order, then the win rule. */
static void dfi_process_faints(dfi_run *r)
{
    struct duoforge_battle *b = r->b;
    const uint32_t length = r->faint_count - r->faint_announced; /* the faints this call shows (sim/battle.ts faintQueue.length) */
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
    const bool by_move = r->last_faint_move;
    const uint32_t src = r->last_faint_by;
    r->faint_count = 0u;
    r->faint_announced = 0u;
    if (!any) {
        return;
    }
    const uint32_t result = dfi_win_result(b, r->last_fainted);
    if (result != DFI_RESULT_NONE) {
        b->result = (uint8_t)result;
        r->ended = true;
        return; /* checkWin returns before AfterFaint (sim/battle.ts:2598) */
    }
    dfi_after_faint(r, length, by_move, src); /* after the queue is processed: the faints of this call are no longer queued */
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
    const uint32_t length = r->faint_count - r->faint_announced; /* the faints this call shows */
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
            return; /* faintMessages returns after checkWin: no AfterFaint (sim/battle.ts:2598) */
        }
    }
    dfi_after_faint(r, length, r->last_faint_move, r->last_faint_by);
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
static duoforge_status dfi_status_hit_end(dfi_run *r)
{
    r->mres |= DFI_MRES_TRUE; /* the effect applied: the move's hit returns true (sim/battle-actions.ts, runMoveEffects) */
    const duoforge_status st = dfi_update(r);
    if (st != DUOFORGE_OK) {
        return st;
    }
    dfi_announce_faints(r, false); /* no status move in the data costs its user HP */
    return dfi_update(r);
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

/* side.removeSideCondition for the three screens that Psychic Fangs breaks (step G30), in the order of its onTryHit:
 * Reflect, Light Screen, Aurora Veil. A condition that is not up is not removed and shows nothing; one that is shows
 * -sideend|side|its name. */
static void dfi_break_screens(dfi_run *r, uint32_t side)
{
    struct duoforge_battle *b = r->b;
    static const uint8_t kinds[3] = {DUOFORGE_SIDE_REFLECT, DUOFORGE_SIDE_LIGHT_SCREEN, DUOFORGE_SIDE_AURORA_VEIL};
    uint8_t *turns[3] = {&b->sides[side].reflect_turns, &b->sides[side].light_screen_turns,
                         &b->tail.sides[side].aurora_veil_turns};
    for (uint32_t k = 0u; k < 3u; ++k) {
        if (*turns[k] != 0u) {
            *turns[k] = 0u;
            duoforge_event e = dfi_event_make(DUOFORGE_EVENT_SIDE_END, DUOFORGE_NO_POSITION);
            e.detail = (uint8_t)side;
            e.amount = kinds[k];
            dfi_emit(r, &e); /* [-sideend] */
        }
    }
}


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
#define DFI_DISABLE_TURNS 5u
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
    const uint32_t turns = (out_a_turn && dfi_will_move(b, flat) == NULL) ? 4u : 3u;
    tail->taunt_turns = (uint8_t)turns; /* <= DFI_TAIL_TAUNT_MAX */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_VOLATILE_START, flat);
    e.detail = (uint8_t)DUOFORGE_VOLATILE_TAUNT;
    dfi_emit(r, &e);
    return true;
}

/* Yawn (data/moves.ts:21131-21162, no Champions change; accuracy true: no draw). Its own onTryHit fails the move
 * (-fail|user with [still]) for a target that has a status or is immune to sleep (no marked ability, item or type of
 * the pool is: the Immunity handlers of Insomnia, Vital Spirit, Sweet Veil and Comatose are unmarked, and the terrains
 * that stop sleep are Electric Terrain's, not in this build). addVolatile then fails for a target that is yawning
 * already. Otherwise -start|target|move: Yawn|[of] user, and the target falls asleep at the end of the next turn
 * (duration 2, the residual at order 23: the Yawn pass of dfi_residual). True when it started. */
static bool dfi_yawn(dfi_run *r, uint32_t user, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    const dfi_member *tm = dfi_at(b, flat);
    dfi_tail_pos *tail = &b->tail.sides[flat / 2u].positions[flat % 2u];
    if (tm == NULL || tm->hp == 0u) {
        return false;
    }
    if (tm->status != DFI_STATUS_NONE) {
        dfi_fail_still(r, user);
        return false;
    }
    /* addVolatile('yawn'): TryAddVolatile, Flower Veil of the target's side blocks it on a Grass type (-block, then the
     * move did nothing); a target that yawns already refuses it (no onRestart). */
    uint32_t veil = 0u;
    if (dfi_flower_veil_holder(b, flat, &veil)) {
        dfi_flower_veil_block(r, flat, veil); /* -block only: neither [still] nor -fail (recorded in g31_yawn_flower_veil) */
        return false;
    }
    if (tail->yawn_turns != 0u) {
        dfi_fail_still(r, user);
        return false;
    }
    tail->yawn_turns = 2u; /* DFI_TAIL_YAWN_MAX */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_VOLATILE_START, flat);
    e.detail = (uint8_t)DUOFORGE_VOLATILE_YAWN;
    e.other = (uint8_t)user;
    dfi_emit(r, &e);
    return true;
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
    const duoforge_status st = dfi_deal(r, user, cost, DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION);
    if (st != DUOFORGE_OK) {
        return st;
    }
    return dfi_status_hit_end(r);
}

/* Steel Roller's onHit (step G34, data/moves.ts:17893-17913): Field.clearTerrain after the damage of the hit, once for the
 * move: -fieldend|move: the terrain, then the TerrainChange event of the seeds on the field. Step G25 extends it to Electric
 * and Misty Terrain: the FIELD_END detail is the one of the terrain that ends (dfi_terrain_field_detail, as at the end of its
 * turns), and the converter reads Misty Terrain's line, which has no "move: " (data/moves.ts onFieldEnd). */
static duoforge_status dfi_clear_terrain(dfi_run *r)
{
    struct duoforge_battle *b = r->b;
    if (b->terrain == DFI_TERRAIN_NONE) {
        return DUOFORGE_OK;
    }
    const uint32_t ended = b->terrain;
    b->terrain = (uint8_t)DFI_TERRAIN_NONE;
    b->terrain_turns = 0u;
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_FIELD_END, DUOFORGE_NO_POSITION);
    e.detail = (uint8_t)dfi_terrain_field_detail(ended); /* wide-operands-reviewed: < 6 */
    dfi_emit(r, &e); /* [-fieldend] */
    return dfi_terrain_change(r);
}

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
static duoforge_status dfi_run_heal_move(dfi_run *r, uint32_t user, uint32_t move_id, const uint32_t *targets,
                                         uint32_t count)
{
    (void)user;
    bool did = false;
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
            dfi_fail_still(r, t);
            continue;
        }
        if (dfi_heal_blocked(r->b, t)) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        const uint32_t num = dfi_pool_move_heal[move_id][0];
        const uint32_t den = dfi_pool_move_heal[move_id][1];
        uint32_t amount = ((uint32_t)m->hp_max * num * 2u + den) / (2u * den); /* Math.round(hp_max * num / den) */
        amount = amount < 1u ? 1u : amount;
        dfi_heal(r, t, amount, DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION);
        did = true;
    }
    /* The `[spread]` list of the move line is the move's hitTargets after the hit steps (sim/battle-actions.ts:614-618): when
     * the heal did something for at least one target every target stays in it, a target at full HP too, and when it did
     * nothing for any the list is empty (the move line keeps its [spread] with no slot). */
    if (count > 1u) {
        duoforge_event *mv = dfi_last_move(r);
        if (mv != NULL) {
            uint32_t mask = 0u;
            for (uint32_t i = 0u; did && i < count; ++i) {
                mask |= 1u << targets[i];
            }
            mv->amount = (uint8_t)mask; /* < 16 */
        }
    }
    /* spreadMoveHit's `if (!moveDamage.some(val => val !== false)) break;` (the Champions mod's loop, data/mods/champions/scripts.ts:526 and its Update at :537, the format runs it; sim/battle-actions.ts:954 is the base's) leaves the hit loop
     * before its eachEvent('Update') when every target's heal failed (damage[i] is false for a target at full HP): no Update,
     * so no Sitrus Berry check. This is what the single-target branch did before step G32 (an early return); the spread
     * rewrite of step G32 fell through to the hit end and drew the Update's speed ties of the Sitrus holders too. */
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
    r->mres |= did ? DFI_MRES_TRUE : DFI_MRES_FALSE;
    if (!did) {
        return DUOFORGE_OK;
    }
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
    if (st == DUOFORGE_OK && !can) {
        r->mres |= DFI_MRES_NULL; /* mustrecharge's BeforeMove returns null (data/conditions.ts:367-377) */
    }
    return st != DUOFORGE_OK ? st : (can ? DUOFORGE_E_INVARIANT : DUOFORGE_OK);
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
    /* The user's accuracy stage minus the target's evasion, clamped. */
    const uint32_t acc = dfi_pos(b, user)->stages[DFI_STAGE_ACCURACY];
    /* Darkest Lariat (Team C): ignoreEvasion (sim/battle-actions.ts:719). */
    const uint32_t eva = md->special == DFI_SPECIAL_DARKEST_LARIAT ? DFI_BIAS6
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
        if ((b->weather == DFI_WEATHER_SNOW && dfi_ability(b, victim, DFI_ABILITY_SNOWCLOAK)) ||
            (b->weather == DFI_WEATHER_SAND && dfi_ability(b, victim, DFI_ABILITY_SANDVEIL))) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        /* And the target's Bright Powder (step G49): it is the same ModifyAccuracy event, after the stages. */
        if (dfi_holds(b, victim, DFI_ITEM_BRIGHTPOWDER)) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        /* The rational comparison below is proved for the accuracy 90 only (combat/multiaccuracy.h, checkG33): a new
         * multiaccuracy move extends the proof before it runs. */
        if (!dfi_multiaccuracy_proven(base_accuracy)) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        /* accuracy stage a = acc - 6: above 0 x (3 + a) / 3, otherwise x 3 / (3 - a); evasion stage e = eva - 6: above 0
         * x 3 / (3 + e), otherwise x (3 - e) / 3. */
        const uint32_t num_a = acc > DFI_BIAS6 ? 3u + (acc - DFI_BIAS6) : 3u;
        const uint32_t den_a = acc > DFI_BIAS6 ? 3u : 3u + (DFI_BIAS6 - acc);
        const uint32_t num_e = eva > DFI_BIAS6 ? 3u : 3u + (DFI_BIAS6 - eva);
        const uint32_t den_e = eva > DFI_BIAS6 ? 3u + (eva - DFI_BIAS6) : 3u;
        const uint32_t numerator = base_accuracy * num_a * num_e; /* <= 100 x 9 x 9 */
        const uint32_t denominator = den_a * den_e;               /* <= 81 */
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

/* The number of hits of a move (step G33): the pin's `multihit`, kept in the handler of the three rows that the engine runs
 * (Dual Wingbeat and Twin Beam 2, Triple Axel 3), 1 for every other move. */
static uint32_t dfi_move_hits(const dfi_move_data *md)
{
    return md->special == DFI_SPECIAL_MULTI_HIT_2 ? 2u
           : md->special == DFI_SPECIAL_TRIPLE_AXEL ? 3u
           : md->special == DFI_SPECIAL_MULTI_HIT_10 ? 10u
           : 1u;
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

static duoforge_status dfi_run_move_body(dfi_run *r, const dfi_queue_record *q, bool *ran)
{
    r->hit_index = 1u;
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
    if (st != DUOFORGE_OK) {
        return st;
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
        return DUOFORGE_OK;
    }
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
        e.other = (uint8_t)(count == 1u && target_class != DFI_TARGET_CLASS_FOE_SIDE ? aimed : DUOFORGE_NO_POSITION); /* wide-operands-reviewed: < 256 */
        const uint32_t spread_flag = count > 1u ? DUOFORGE_EVENT_FLAG_SPREAD : 0u;
        const uint32_t locked_flag = locked || lock_move ? DUOFORGE_EVENT_FLAG_LOCKED : 0u; /* a lockedmove's use: [from] lockedmove */
        e.flags = (uint8_t)(spread_flag | locked_flag); /* wide-operands-reviewed: flags < 256 */
        r->last_move = r->events != NULL ? r->events->count : UINT32_MAX;
        dfi_emit(r, &e);
    }
    if (aimed == DUOFORGE_NO_POSITION && count == 0u) {
        return dfi_no_target_or_try(r, user, md); /* no target at all: before getMoveTargets */
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
            /* Rage Powder's handler returns the holder only for an attacker that is not immune to powder (step G30);
             * for an immune one it returns nothing and the next handler (or the aimed target) stands. */
            if (dfi_last_move_id(b, flat) == DFI_MOVE_RAGEPOWDER && dfi_powder_immune(b, m)) {
                continue;
            }
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
    if (follow == DFI_POSITIONS && dfi_move_type_now(b, m, md) == DFI_TYPE_ELECTRIC && single) {
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
     * next turn (duration 2). On the locked turn the attack goes on.
     * Solar Beam's (step G30, data/moves.ts:17224-17258) is the same without the boost, with the sun in place of the
     * rain: the lines, the lock and its end are the two-turn move's, whichever move it is. The pin's
     * effectiveWeather asks Utility Umbrella (sun and rain are ignored for its holder) and Mega Sol (sun for a Mega Sol
     * user's moves): neither is marked, tests/test_pool_g30.c checks it; ChargeMove is Power Herb's event, which is not
     * in the pool either. */
    const bool charge_move = md->special == DFI_SPECIAL_ELECTRO_SHOT || md->special == DFI_SPECIAL_SOLAR_BEAM;
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
        const uint32_t skip_weather = md->special == DFI_SPECIAL_SOLAR_BEAM ? DFI_WEATHER_SUN : DFI_WEATHER_RAIN;
        if (b->weather == skip_weather) {
            /* addMove('-anim'): from now on the last move line, which later
             * attributes ([miss], [notarget]) amend. */
            duoforge_event anim = dfi_event_make(DUOFORGE_EVENT_ANIMATION, user);
            anim.id = (uint16_t)move_id;
            anim.other = (uint8_t)(count == 1u ? aimed : DUOFORGE_NO_POSITION); /* wide-operands-reviewed: < 256 */
            r->last_move = r->events != NULL ? r->events->count : UINT32_MAX;
            dfi_emit(r, &anim);
        }
        if (b->weather != skip_weather) {
            pos->charge_turns = (uint8_t)DFI_CHARGE_TURNS_MAX;
            pos->locked_move = (uint8_t)((uint32_t)q->move_slot + 1u); /* wide-operands-reviewed: <= 4 */
            pos->locked_target = q->target;
            r->mres |= DFI_MRES_NULL; /* the charge turn's onTryMove returns null (data/moves.ts) */
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
                    return DUOFORGE_OK;
                }
            }
        }
    }
    if (count == 0u) {
        return dfi_no_target_or_try(r, user, md); /* after TryMove (sim/battle-actions.ts:509-513) */
    }
    if (md->special == DFI_SPECIAL_HELPING_HAND) {
        return dfi_run_helping_hand(r, user, targets[0]);
    }
    if (md->special == DFI_SPECIAL_PROTECT) {
        return dfi_run_protect(r, user, DFI_PROTECT_PLAIN);
    }
    if (md->special == DFI_SPECIAL_SPIKY_SHIELD) {
        return dfi_run_protect(r, user, DFI_PROTECT_SPIKY_SHIELD);
    }
    if (md->special == DFI_SPECIAL_WIDE_GUARD) {
        return dfi_run_wide_guard(r, user);
    }
    if (md->special == DFI_SPECIAL_AURORA_VEIL) {
        return dfi_run_aurora_veil(r, user);
    }
    if (md->special == DFI_SPECIAL_PERISH_SONG) {
        return dfi_run_perish_song(r, user, md);
    }
    if (md->special == DFI_SPECIAL_FOLLOW_ME) {
        return dfi_run_follow_me(r, user, DFI_MOVE_FOLLOWME);
    }
    if (md->special == DFI_SPECIAL_RAGE_POWDER) {
        return dfi_run_follow_me(r, user, DFI_MOVE_RAGEPOWDER);
    }
    if (md->special == DFI_SPECIAL_CLANGOROUS_SOUL) {
        return dfi_run_clangorous_soul(r, user, md);
    }
    if (md->special == DFI_SPECIAL_IMPRISON) {
        return dfi_run_imprison(r, user);
    }
    const bool status_move = md->category == DFI_CATEGORY_STATUS;
    /* flags.powder (step G30): the second flags byte's bit; Struggle has none. */
    const bool powder_move = move_id != DFI_MOVE_STRUGGLE && (dfi_pool_move_flags2[move_id] & DFI_MOVE_FLAG2_POWDER) != 0u;
    if (status_move && md->boost_role == DFI_BOOST_ROLE_PRIMARY_ALLY) {
        return dfi_run_coaching(r, user, targets[0], md);
    }
    if (status_move && md->side_condition >= DUOFORGE_SIDE_STEALTH_ROCK) {
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
        r->mres |= DFI_MRES_TRUE; /* addSideCondition returns true */
        return DUOFORGE_OK;
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
            return DUOFORGE_OK;
        }
        b->weather = (uint8_t)w;
        b->weather_turns = (uint8_t)DFI_FIELD_TURNS_MAX;
        duoforge_event e = dfi_event_make(DUOFORGE_EVENT_WEATHER, DUOFORGE_NO_POSITION);
        e.detail = (uint8_t)w; /* DUOFORGE_WEATHER_* */
        dfi_emit(r, &e);
        r->mres |= DFI_MRES_TRUE; /* Field.setWeather returns true */
        return DUOFORGE_OK;
    }
    if (status_move && (md->special == DFI_SPECIAL_ELECTRIC_TERRAIN || md->special == DFI_SPECIAL_MISTY_TERRAIN)) {
        /* Electric Terrain and Misty Terrain (moveHit, sim/battle-actions.ts:1252-1255): Field.setTerrain
         * (sim/field.ts:130-157) fails when the same terrain is up (the move fails) and otherwise replaces the terrain
         * for 5 turns (Terrain Extender is not marked) with `-fieldstart|move: X Terrain` and no [from]; the replaced
         * terrain ends without a line, and TerrainChange runs the seeds. */
        const uint32_t terrain = md->special == DFI_SPECIAL_ELECTRIC_TERRAIN ? DFI_TERRAIN_ELECTRIC : DFI_TERRAIN_MISTY;
        if (b->terrain == terrain) {
            dfi_fail_still(r, user);
            return DUOFORGE_OK;
        }
        b->terrain = (uint8_t)terrain;
        b->terrain_turns = (uint8_t)DFI_FIELD_TURNS_MAX;
        duoforge_event e = dfi_event_make(DUOFORGE_EVENT_FIELD_START, DUOFORGE_NO_POSITION);
        e.detail = (uint8_t)dfi_terrain_field_detail(terrain);
        dfi_emit(r, &e);
        r->mres |= DFI_MRES_TRUE; /* Field.setTerrain returns true */
        return dfi_terrain_change(r);
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
        return DUOFORGE_OK;
    }
    /* A status move whose only effect is its forced switch (Roar, Whirlwind; step G46) is modelled by the forced-switch step
     * below, not refused here. */
    if (status_move && md->primary_status == DFI_STATUS_NONE && md->special != DFI_SPECIAL_PARTING_SHOT &&
        md->special != DFI_SPECIAL_SOAK && md->special != DFI_SPECIAL_ENCORE && md->special != DFI_SPECIAL_DISABLE &&
        md->special != DFI_SPECIAL_TRICK && md->special != DFI_SPECIAL_SWITCHEROO &&
        md->special != DFI_SPECIAL_TAUNT && md->special != DFI_SPECIAL_YAWN &&
        md->boost_role != DFI_BOOST_ROLE_PRIMARY_TARGET &&
        (dfi_pool_move_flags2[move_id] & DFI_MOVE_FLAG2_FORCE_SWITCH) == 0u) {
        if (dfi_pool_move_heal[move_id][1] != 0u) {
            return dfi_run_heal_move(r, user, move_id, targets, count);
        }
        if (md->boost_role != DFI_BOOST_ROLE_PRIMARY_SELF || md->target_class != DUOFORGE_TARGET_CLASS_SELF) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        dfi_boost_effect own = dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_PRIMARY);
        own.negatives_first = md->special == DFI_SPECIAL_SHELL_SMASH;
        if (dfi_boost(r, user, md->boosts, DFI_POSITIONS, own)) {
            return dfi_status_hit_end(r);
        }
        r->mres |= DFI_MRES_FALSE; /* nothing changed: the hit returns false (runMoveEffects) */
    return DUOFORGE_OK; /* the hit loop stops */
    }
    /* A handler this build does not have fails explicitly; the Team C
     * specials of later steps are also kept out by the support manifest. */
    if (md->special > DFI_SPECIAL_STRUGGLE && md->special != DFI_SPECIAL_DARKEST_LARIAT &&
        md->special != DFI_SPECIAL_LAST_RESPECTS && md->special != DFI_SPECIAL_SUCKER_PUNCH &&
        md->special != DFI_SPECIAL_FIRST_IMPRESSION && md->special != DFI_SPECIAL_LOW_KICK &&
        md->special != DFI_SPECIAL_SOAK && md->special != DFI_SPECIAL_ENCORE && md->special != DFI_SPECIAL_DISABLE &&
        md->special != DFI_SPECIAL_KNOCK_OFF && md->special != DFI_SPECIAL_EXPANDING_FORCE &&
        md->special != DFI_SPECIAL_GLAIVE_RUSH && md->special != DFI_SPECIAL_ACROBATICS &&
        md->special != DFI_SPECIAL_BLIZZARD && md->special != DFI_SPECIAL_FEINT &&
        md->special != DFI_SPECIAL_STEEL_ROLLER && md->special != DFI_SPECIAL_BRICK_BREAK &&
        md->special != DFI_SPECIAL_PSYCHIC_FANGS && md->special != DFI_SPECIAL_SOLAR_BEAM &&
        md->special != DFI_SPECIAL_HP_POWER && md->special != DFI_SPECIAL_BODY_PRESS &&
        md->special != DFI_SPECIAL_FOUL_PLAY && md->special != DFI_SPECIAL_PSYSHOCK &&
        md->special != DFI_SPECIAL_FREEZE_DRY && md->special != DFI_SPECIAL_CLANGING_SCALES &&
        md->special != DFI_SPECIAL_RISING_VOLTAGE && md->special != DFI_SPECIAL_TERRAIN_PULSE &&
        md->special != DFI_SPECIAL_MULTI_HIT_2 && md->special != DFI_SPECIAL_TRIPLE_AXEL &&
        md->special != DFI_SPECIAL_DOUBLE_SHOCK &&
        md->special != DFI_SPECIAL_RAGE_FIST && md->special != DFI_SPECIAL_STONE_AXE &&
        md->special != DFI_SPECIAL_CEASELESS_EDGE && md->special != DFI_SPECIAL_MULTI_HIT_10 &&
        md->special != DFI_SPECIAL_IMPRISON && md->special != DFI_SPECIAL_TRICK && md->special != DFI_SPECIAL_SWITCHEROO &&
        md->special != DFI_SPECIAL_THIEF && md->special != DFI_SPECIAL_COVET && md->special != DFI_SPECIAL_SUPER_FANG &&
        md->special != DFI_SPECIAL_TAUNT && md->special != DFI_SPECIAL_YAWN &&
        md->special != DFI_SPECIAL_ROOST && md->special != DFI_SPECIAL_STOMPING_TANTRUM &&
        md->special != DFI_SPECIAL_POWER_TRIP && md->special != DFI_SPECIAL_THUNDER && md->special != DFI_SPECIAL_ICE_FANG &&
        md->special != DFI_SPECIAL_TRI_ATTACK && md->special != DFI_SPECIAL_LOCKED_MOVE) {
        return DUOFORGE_E_INVARIANT;
    }
    /* Steel Roller's onTry (step G34, data/moves.ts:17893-17913): it fails without a terrain, with -fail and [still]. */
    if (md->special == DFI_SPECIAL_STEEL_ROLLER && b->terrain == DFI_TERRAIN_NONE) {
        dfi_fail_still(r, user);
        return DUOFORGE_OK;
    }
    /* Double Shock's onTryMove (decision 0025, data/moves.ts:3954-3959): without the Electric type it fails, -fail and [still].
     * A user that has the type is played only as Pawmot with its own two types (dfi_double_shock_shape); any other shape is
     * refused, never guessed. */
    if (md->special == DFI_SPECIAL_DOUBLE_SHOCK) {
        bool stopped = false;
        const duoforge_status ds = dfi_double_shock_try(r, user, &stopped);
        if (ds != DUOFORGE_OK || stopped) {
            return ds;
        }
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
    /* Hurricane never misses in rain and has 50 accuracy under sun. Thunder (step G44, data/moves.ts:19438-19458) is the same
     * onModifyMove: move.accuracy = true in rain, 50 under sun (target.effectiveWeather(), which is the field's weather). */
    uint32_t base_accuracy = md->accuracy;
    if (md->special == DFI_SPECIAL_HURRICANE || md->special == DFI_SPECIAL_THUNDER) {
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
    uint32_t move_type = dfi_move_type_now(b, m, md);
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
    if ((target_class == DUOFORGE_TARGET_CLASS_ALL_ADJACENT_FOES || target_class == DFI_TARGET_CLASS_ALL_ADJACENT) &&
        (md->flags & DFI_MOVE_FLAG_PROTECT) != 0u) {
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
    /* One TryHit event runs the handlers of every target ordered by priority, then by the holders' speed (a tie draws):
     * two holders of a punishing variant that both stop a contact move would show their lines in that order, which is not
     * modelled (E_UNSUPPORTED, never a guess). */
    if ((md->flags & DFI_MOVE_FLAG_CONTACT) != 0u && (md->flags & DFI_MOVE_FLAG_PROTECT) != 0u) {
        uint32_t punishers = 0u;
        for (uint32_t i = 0u; i < count; ++i) {
            const uint32_t t = targets[i];
            punishers += (!guarded[i] && ((uint32_t)dfi_pos(b, t)->flags & DFI_VOL_PROTECT) != 0u &&
                          b->tail.sides[t / 2u].positions[t % 2u].protect_kind != DFI_PROTECT_PLAIN)
                             ? 1u
                             : 0u;
        }
        if (punishers > 1u) {
            return DUOFORGE_E_UNSUPPORTED;
        }
    }
    for (uint32_t i = 0u; i < count; ++i) {
        const uint32_t t = targets[i];
        const dfi_active_slot *tp = dfi_pos(b, t);
        if (guarded[i]) {
            r->mres |= DFI_MRES_NULL; /* Wide Guard's TryHit returns NOT_FAIL (data/moves.ts:20838-20848) */
            continue;
        }
        if (psychic_block && t / 2u != side && dfi_grounded(b, dfi_at(b, t))) {
            duoforge_event e = dfi_event_make(DUOFORGE_EVENT_BLOCKED, t);
            e.detail = (uint8_t)DUOFORGE_FIELD_PSYCHIC_TERRAIN; /* [-activate] move: Psychic Terrain */
            dfi_emit(r, &e);
            r->mres |= DFI_MRES_FALSE; /* its TryHit returns null, which the hit steps normalise to false (battle-actions.ts:650) */
            continue;
        }
        hit[i] = !((((uint32_t)tp->flags & DFI_VOL_PROTECT) != 0u) && ((md->flags & DFI_MOVE_FLAG_PROTECT) != 0u));
        if (!hit[i]) {
            r->mres |= DFI_MRES_NULL; /* Protect's TryHit returns NOT_FAIL (data/moves.ts:13998): no failure */
            dfi_emit_plain(r, DUOFORGE_EVENT_BLOCKED, t); /* [-activate] move: Protect */
            /* Step G20: the contact punishment of Spiky Shield, in the same onTryHit after the -activate line
             * (data/moves.ts:17550-17559; checkMoveMakesContact is the contact flag: Protective Pads are not in the
             * pool). It costs the attacker floor(maxHP / 8), at least 1, with [-damage] ... [from] Spiky Shield [of] the
             * holder (CAUSE_MOVE, the move in id2, the holder in other), also when the attacker is knocked out. */
            const uint32_t kind = r->b->tail.sides[t / 2u].positions[t % 2u].protect_kind;
            if (kind != DFI_PROTECT_PLAIN && (md->flags & DFI_MOVE_FLAG_CONTACT) != 0u) {
                const uint32_t spikes = (uint32_t)m->hp_max / 8u;
                st = dfi_deal(r, user, spikes == 0u ? 1u : spikes, DUOFORGE_CAUSE_MOVE, DFI_MOVE_SPIKYSHIELD, t);
                if (st != DUOFORGE_OK) {
                    return st;
                }
            }
        }
    }
    /* Snapshot for the drops of the immunity steps below (each a literal false of the hit steps). */
    bool hit_pre_immunity[DFI_POSITIONS];
    for (uint32_t i = 0u; i < DFI_POSITIONS; ++i) {
        hit_pre_immunity[i] = hit[i];
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
    for (uint32_t i = 0u; i < count && !status_move; ++i) { /* a status move ignores type immunity */
        if (!hit[i]) {
            continue;
        }
        const dfi_member *tm = dfi_at(b, targets[i]);
        /* Scrappy (step G39, data/abilities.ts:4079-4098, onModifyMove): ignoreImmunity for the Fighting and Normal types, so
         * a Ghost type is hit by them (its other type decides the effectiveness: an immunity adds nothing, dfi_type_mod). */
        const bool scrappy = dfi_ability(b, dfi_at(b, user), DFI_ABILITY_SCRAPPY) &&
                             (move_type == DFI_TYPE_NORMAL || move_type == DFI_TYPE_FIGHTING);
        if (!scrappy && dfi_type_immune(b, tm, move_type)) {
            hit[i] = false;
            dfi_immune(r, targets[i], 0u);
        } else if (move_type == DFI_TYPE_GROUND && dfi_ability(b, tm, DFI_ABILITY_LEVITATE)) {
            /* runImmunity('Ground'): isGrounded is null for a Levitate holder (sim/pokemon.ts:2156), shown as
             * -immune|X|[from] ability: Levitate (:2257-2258); a Flying type is immune first, without the line. */
            hit[i] = false;
            dfi_immune(r, targets[i], 1u + DFI_ABILITY_LEVITATE);
        }
    }
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
    bool hit_pre_accuracy[DFI_POSITIONS];
    for (uint32_t i = 0u; i < DFI_POSITIONS; ++i) {
        hit_pre_accuracy[i] = hit[i];
    }
    if (base_accuracy != 0u) {
        for (uint32_t i = 0u; i < count; ++i) {
            if (!hit[i]) {
                continue;
            }
            uint32_t move_accuracy = base_accuracy;
            {
                uint32_t acc_chain = 4096u;
                bool acc_ok = true;
                const dfi_member *acc_target = dfi_at(b, targets[i]);
                if (acc_compound_eyes) {
                    acc_ok = dfi_chain_modify(acc_chain, 5325u, &acc_chain);
                }
                if ((b->weather == DFI_WEATHER_SNOW && dfi_ability(r->b, acc_target, DFI_ABILITY_SNOWCLOAK)) ||
                    (b->weather == DFI_WEATHER_SAND && dfi_ability(r->b, acc_target, DFI_ABILITY_SANDVEIL))) {
                    acc_ok = acc_ok && dfi_chain_modify(acc_chain, 3277u, &acc_chain);
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
    for (uint32_t i = 0u; i < count; ++i) {
        r->mres |= hit_pre_accuracy[i] && !hit[i] ? DFI_MRES_FALSE : 0u; /* a miss: the accuracy step is a literal false */
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
            if (md->special == DFI_SPECIAL_TRICK || md->special == DFI_SPECIAL_SWITCHEROO) {
                bool swapped = false;
                st = dfi_trick(r, user, targets[i], move_id, &swapped);
                if (st != DUOFORGE_OK) {
                    return st;
                }
                did = did || swapped;
                continue;
            }
            if (md->special == DFI_SPECIAL_YAWN) {
                did = dfi_yawn(r, user, targets[i]) || did;
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
                continue; /* a forced switch alone (Roar, Whirlwind; step G46): no status is set, and no [-status] line */
            }
            const uint32_t before = dfi_at(b, targets[i])->status;
            st = dfi_try_status(r, targets[i], md->primary_status, user, move_id, DFI_ORIGIN_MOVE, 0u);
            if (st != DUOFORGE_OK) {
                return st;
            }
            did = did || dfi_at(b, targets[i])->status != before;
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
    const uint32_t hits_total = dfi_move_hits(md);
    if (hits_total != 1u && (count != 1u || spread)) {
        return DUOFORGE_E_UNSUPPORTED; /* a multi-hit spread move: Dragon Darts and the like are not modelled */
    }
    const bool multi_accuracy = md->special == DFI_SPECIAL_TRIPLE_AXEL || md->special == DFI_SPECIAL_MULTI_HIT_10; /* multiaccuracy: true */
    uint32_t total = 0u;
    uint32_t hp_before[DFI_POSITIONS] = {0u, 0u, 0u, 0u};
    bool any = false;
    for (uint32_t hit_no = 1u; hit_no <= hits_total; ++hit_no) {
        if (hit_no > 1u) {
            if (!any) {
                break; /* nothing was hit (a miss, Protect, an immunity): the loop is never entered */
            }
            if (dfi_at(b, targets[0])->hp == 0u || m->status == DFI_STATUS_SLP) {
                break;
            }
            if (multi_accuracy) {
                bool ok = true;
                st = dfi_accuracy_check(r, user, targets[0], md, base_accuracy, true, &ok);
                if (st != DUOFORGE_OK) {
                    return st;
                }
                if (!ok) {
                    break;
                }
            }
        }
        r->hit_index = hit_no;
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
        /* forceSwitch of a damaging move (Dragon Tail, Circle Throw; step G46): the forceSwitch step of spreadMoveHit runs
         * after the damage is computed and before it is dealt (scripts.ts:392), so the target is still standing. */
        if (!status_move && (dfi_pool_move_flags2[move_id] & DFI_MOVE_FLAG2_FORCE_SWITCH) != 0u) {
            for (uint32_t i = 0u; i < count; ++i) {
                if (hit[i]) {
                    dfi_drag_at_hit(r, user, targets[i]);
                }
            }
        }
        /* spreadDamage, per target: the damage, then a drain heals the user by
         * round(dealt * drain) (sim/battle.ts:2170-2173). The HP actually lost
         * adds up to the move's total damage. */
        for (uint32_t i = 0u; i < count; ++i) {
            if (hit[i]) {
                const uint32_t before = dfi_at(b, targets[i])->hp;
                if (hit_no == 1u) {
                    hp_before[i] = before; /* Emergency Exit asks for the HP before the whole move */
                }
                /* Focus Sash (combat/item_family.h): a move hit that would take
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
                st = dfi_deal(r, targets[i], damage[i], DUOFORGE_CAUSE_NONE, 0u, DUOFORGE_NO_POSITION);
                if (st != DUOFORGE_OK) {
                    return st;
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
        /* Steel Roller's onHit (runMoveEffects, right after the damage of the hit): the terrain ends. */
        if (md->special == DFI_SPECIAL_STEEL_ROLLER) {
            bool any_hit = false;
            for (uint32_t i = 0u; i < count; ++i) {
                any_hit = any_hit || hit[i];
            }
            if (any_hit) {
                st = dfi_clear_terrain(r);
                if (st != DUOFORGE_OK) {
                    return st;
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
        /* Outrage, Thrash and Petal Dance (step G56; the self volatile lockedmove, data/moves.ts:13082-13097, 13291-13306,
         * 19373-19388, applied like the recharge's selfDrops once a target was not ruled out). A new lock draws its count,
         * random(2, 4) (onStart, data/conditions.ts:265); a lock already up is restarted (onRestart): its duration is 2 only
         * when the count is 2 or more. Either way the duration is 2 in this step (lock_restarted), which the countdown and the
         * end of the lock read. */
        if (md->special == DFI_SPECIAL_LOCKED_MOVE) {
            bool hit_any = false;
            for (uint32_t i = 0u; i < count; ++i) {
                hit_any = hit_any || hit[i];
            }
            if (hit_any) {
                dfi_tail_pos *ut = &b->tail.sides[side].positions[q->slot];
                if (ut->lock_turns == 0u) {
                    uint32_t count_turns = 0u;
                    st = dfi_draw(r->draws, DFI_SITE_LOCK_TURNS, 2u, 4u, &count_turns);
                    if (st != DUOFORGE_OK) {
                        return st;
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
         * with no chance always applies, after the roll), so one SECONDARY roll per hit target and nothing else. */
        if (md->special == DFI_SPECIAL_STONE_AXE || md->special == DFI_SPECIAL_CEASELESS_EDGE) {
            for (uint32_t i = 0u; i < count; ++i) {
                if (hit[i]) {
                    uint32_t roll = 0u;
                    st = dfi_draw(r->draws, DFI_SITE_SECONDARY, 0u, 100u, &roll);
                    if (st != DUOFORGE_OK) {
                        return st;
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
                    return st;
                }
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
                    return st;
                }
            }
            if (md->boost_role == DFI_BOOST_ROLE_SELF_AFTER_HIT) {
                return DUOFORGE_E_UNSUPPORTED; /* no closure move has both */
            }
        }
        /* Ice Fang (step G44, data/moves.ts:9347-9368): two secondaries in order, and for each hit target the loop of
         * secondaries() draws random(100) before each one (sim/battle-actions.ts:1336-1354): a freeze at 10 (a status of the
         * move, dfi_try_status as a status secondary does), then a flinch at 10 (a volatile of the target). Both rolls are
         * drawn for a target that fainted, as for any secondary. */
        if (md->special == DFI_SPECIAL_ICE_FANG) {
            for (uint32_t i = 0u; i < count; ++i) {
                if (!hit[i]) {
                    continue;
                }
                uint32_t roll = 0u;
                st = dfi_draw(r->draws, DFI_SITE_SECONDARY, 0u, 100u, &roll);
                if (st != DUOFORGE_OK) {
                    return st;
                }
                if (roll < 10u) {
                    st = dfi_try_status(r, targets[i], DFI_STATUS_FRZ, user, move_id, false, 0u);
                    if (st != DUOFORGE_OK) {
                        return st;
                    }
                }
                st = dfi_draw(r->draws, DFI_SITE_SECONDARY, 0u, 100u, &roll);
                if (st != DUOFORGE_OK) {
                    return st;
                }
                if (roll < 10u) {
                    st = dfi_add_volatile(r, targets[i], DFI_VOLATILE_FLINCH);
                    if (st != DUOFORGE_OK) {
                        return st;
                    }
                }
            }
        }
        /* Tri Attack (step G44, data/moves.ts:19845-19864): a secondary of chance 20, one SECONDARY roll per hit target, and
         * its onHit draws sample(['brn', 'par', 'frz']) (SITE_STATUS_PICK, random(3)) then trySetStatus without a source move,
         * as Dire Claw's pick does (the reference draws the pick after every successful roll, also for a target that fainted,
         * has a status or is immune). */
        if (md->special == DFI_SPECIAL_TRI_ATTACK) {
            static const uint8_t tri_pick[3] = {DFI_STATUS_BRN, DFI_STATUS_PAR, DFI_STATUS_FRZ};
            for (uint32_t i = 0u; i < count; ++i) {
                if (!hit[i]) {
                    continue;
                }
                uint32_t roll = 0u;
                st = dfi_draw(r->draws, DFI_SITE_SECONDARY, 0u, 100u, &roll);
                if (st != DUOFORGE_OK) {
                    return st;
                }
                if (!dfi_tri_attack_chance_hit(roll)) {
                    continue;
                }
                uint32_t v = 0u;
                st = dfi_draw(r->draws, DFI_SITE_STATUS_PICK, 0u, 3u, &v);
                if (st == DUOFORGE_OK) {
                    st = dfi_try_status(r, targets[i], tri_pick[v], user, DFI_NO_SOURCE_MOVE, false, 0u);
                }
                if (st != DUOFORGE_OK) {
                    return st;
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
                /* The unordered handlers of a target that is down do nothing, except Cursed Body (a holder that the hit knocked
                 * out still makes its attacker roll: its onDamagingHit runs before the faint is processed and `-start|...|Disable
                 * ... [from] ability: Cursed Body [of] holder` shows before the faint line, recorded in g27_cursed_body_a) and
                 * Flame Body (step G30: it draws its roll too) and the attacker's Poison Touch: it draws its roll (the handler
                 * runs, trySetStatus then fails). */
                st = dfi_toxic_debris(r, user, targets[i], md); /* step G37: the target's own handler, one ability per holder */
                if (st != DUOFORGE_OK) {
                    return st;
                }
                if (dfi_ability(r->b, tm, DFI_ABILITY_CURSEDBODY)) {
                    st = dfi_cursed_body(r, user, targets[i], move_id);
                    if (st != DUOFORGE_OK) {
                        return st;
                    }
                }
                st = dfi_flame_body(r, user, targets[i], md);
                if (st != DUOFORGE_OK) {
                    return st;
                }
                st = dfi_static(r, user, targets[i], md); /* step G39: one ability per holder, so never with Flame Body's */
                if (st != DUOFORGE_OK) {
                    return st;
                }
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
            /* Cursed Body (POOL data): the target's own onDamagingHit, after Thermal Exchange's place and before the attacker's
             * Poison Touch; the target is standing here (a holder that is down rolls too: see above). Two holders hit by one
             * spread move: DamagingHit is sorted by compareLeftToRightOrder (sim/battle.ts:789-790 and :421-426: order, then
             * priority, then the target's index in the move's target list), not by Speed, so the holders roll in target order
             * with no tie draw (the damaged targets go in as one array, sim/battle-actions.ts:1109-1121); the second holder
             * finds the attacker already disabled when the first one's roll succeeded and does not roll (data/abilities.ts:784-797). */
            st = dfi_toxic_debris(r, user, targets[i], md); /* step G37: the target's own handler, one ability per holder */
            if (st != DUOFORGE_OK) {
                return st;
            }
            if (dfi_ability(r->b, tm, DFI_ABILITY_CURSEDBODY)) {
                st = dfi_cursed_body(r, user, targets[i], move_id);
                if (st != DUOFORGE_OK) {
                    return st;
                }
            }
            /* Flame Body (step G30): the target's own handler, one ability per holder, so never with Stamina or Thermal
             * Exchange. */
            st = dfi_flame_body(r, user, targets[i], md);
            if (st != DUOFORGE_OK) {
                return st;
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
            /* Static (step G39): the target's own unordered handler, like Flame Body's. */
            st = dfi_static(r, user, targets[i], md);
            if (st != DUOFORGE_OK) {
                return st;
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
        /* Thief's and Covet's onAfterHit (step G29), at the same point (and also for a user that has fainted since: the
         * Champions mod does not ask, data/mods/champions/scripts.ts:411; setItem then refuses). */
        if (md->special == DFI_SPECIAL_THIEF || md->special == DFI_SPECIAL_COVET) {
            for (uint32_t i = 0u; i < count; ++i) {
                if (hit[i]) {
                    st = dfi_thief(r, user, targets[i], move_id, md->special == DFI_SPECIAL_THIEF);
                    if (st != DUOFORGE_OK) {
                        return st;
                    }
                }
            }
        }
        /* AfterHit of Stone Axe (Stealth Rock) and Ceaseless Edge (a Spikes layer), step G48: the foe's side of the user gets the
         * hazard after each damaged target (`source.side.foeSidesWithConditions()`, the Champions loop calls onAfterHit for every
         * damaged target without asking whether the user stands: data/mods/champions/scripts.ts:411-414; the base game's HP test is
         * at sim/battle-actions.ts:1123). addSideCondition adds a layer or does nothing (no line) when the side is full, and the
         * hazard of the same kind is not restarted: dfi_add_hazard. Sheer Force (move.hasSheerForce) is not marked, so no
         * battle has it. The foe's side is the side the hit went to (single target: the other side of the user). */
        if (md->special == DFI_SPECIAL_STONE_AXE || md->special == DFI_SPECIAL_CEASELESS_EDGE) {
            const uint32_t kind = md->special == DFI_SPECIAL_STONE_AXE ? DUOFORGE_SIDE_STEALTH_ROCK : DUOFORGE_SIDE_SPIKES;
            for (uint32_t i = 0u; i < count; ++i) {
                if (hit[i]) {
                    bool added = false;
                    st = dfi_add_hazard(r, (1u - side), kind, &added);
                    if (st != DUOFORGE_OK) {
                        return st;
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
        /* The hit loop's Update (sim/battle-actions.ts:967), after every hit. */
        if (any) {
            st = dfi_update(r);
            if (st != DUOFORGE_OK) {
                return st;
            }
        }
        if (m->hp == 0u) {
            break; /* the user fainted: that hit counts and the loop ends (:969) */
        }
    }
    r->hit_index = 1u;
    /* Then the loop's faintMessages. */
    if (any) {
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
         * HP (sim/battle-actions.ts:1005-1017). */
        for (uint32_t i = 0u; i < count; ++i) {
            if (hit[i]) {
                dfi_emergency_exit(r, targets[i], hp_before[i]);
            }
        }
    }
    /* selfBoost (step G32, sim/battle-actions.ts:520): once the hit loop is done and the move hit something, the user's
     * own stat change of the move (Clanging Scales: Defense -1), before AfterMoveSecondarySelf; moveHit with isSelf, so a
     * stat that cannot change shows nothing. */
    if (any && md->special == DFI_SPECIAL_CLANGING_SCALES && m->hp != 0u) {
        static const uint8_t def_down[DFI_STAT_STAGE_COUNT] = {6u, 5u, 6u, 6u, 6u, 6u, 6u};
        (void)dfi_boost(r, user, def_down, DFI_POSITIONS, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_SELF));
    }
    /* AfterMoveSecondarySelf: Life Orb takes a tenth of the holder's HP
     * (at least 1) after a damaging move that hit something, unless the holder
     * has a forceSwitchFlag (items.ts:3414): a Red Card drag of the user, which
     * runs before this, sets it (drag_pending, step G46). */
    if (any && dfi_holds(r->b, m, DFI_ITEM_LIFEORB) && ((r->drag_pending >> user) & 1u) == 0u) {
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
/* One move action: the body, then the result the action leaves in the user's position (step G42, tail rev 4's move_result,
 * decision 0015 section 7). Only the POOL kinds carry the tail. An action that did not run (an inactive actor) writes nothing. */
static duoforge_status dfi_run_move(dfi_run *r, const dfi_queue_record *q, bool *ran)
{
    r->mres = 0u;
    const duoforge_status st = dfi_run_move_body(r, q, ran);
    if (st != DUOFORGE_OK || !*ran || !dfi_kind_limits_of(r->ctx->data_kind).pool_rules) {
        return st;
    }
    uint32_t value = DFI_MOVE_RESULT_UNDEFINED;
    bool unclassified = true;
    if ((r->mres & DFI_MRES_UNCLASS) == 0u) {
        if ((r->mres & DFI_MRES_TRUE) != 0u) {
            value = DFI_MOVE_RESULT_TRUE;
            unclassified = false;
        } else if ((r->mres & DFI_MRES_FALSE) != 0u) {
            value = DFI_MOVE_RESULT_FALSE;
            unclassified = false;
        } else if ((r->mres & DFI_MRES_NULL) != 0u) {
            value = DFI_MOVE_RESULT_NULL;
            unclassified = false;
        }
    }
    dfi_tail_pos *tp = &r->b->tail.sides[q->side].positions[q->slot];
    /* This turn's bits (0-1) and the unclassified-now bit (4) are the action's; the last turn's bits stay. */
    const uint32_t kept = (uint32_t)tp->move_result & ~0x13u;
    tp->move_result = (uint8_t)(kept | value | (unclassified ? DFI_MOVE_RESULT_UNCLASSIFIED_NOW : 0u)); /* wide-operands-reviewed: <= 0x3F */
    return DUOFORGE_OK;
}

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

/* party_order (step G46, sim/battle-actions.ts:119-133): the incoming member takes the outgoing one's entry of side.pokemon and
 * the outgoing one takes the incoming's old entry, a fainted outgoing too. A slot with no occupant changes nothing (the pin's
 * `if (oldActive)`: only the start, where the leads come in through team selection). POOL kinds only: the tail is zero
 * under the other kinds. */
static void dfi_party_switch(dfi_run *r, uint32_t side, uint32_t slot, uint32_t incoming)
{
    struct duoforge_battle *b = r->b;
    if (!dfi_kind_limits_of(r->ctx->data_kind).pool_rules || b->sides[side].positions[slot].occupant == DFI_OCCUPANT_NONE) {
        return;
    }
    uint32_t j = DUOFORGE_MAX_ROSTER;
    for (uint32_t k = 0u; k < DUOFORGE_MAX_ROSTER; ++k) {
        if (dfi_party_entry(&b->tail, side, k) == incoming + 1u) {
            j = k;
        }
    }
    if (j >= DUOFORGE_MAX_ROSTER) {
        return; /* a brought member is always in the order (invariant TAIL_PARTY); nothing to do otherwise */
    }
    const uint32_t outgoing = dfi_party_entry(&b->tail, side, slot);
    dfi_party_put(&b->tail, side, slot, incoming + 1u);
    dfi_party_put(&b->tail, side, j, outgoing);
}

/* switchIn (sim/battle-actions.ts:57-149): the Pokemon in the slot leaves
 * (its position is cleared; a fainted one simply makes room), the reserve
 * comes in with a fresh activation and is seen by the opponent, and its
 * entry is queued. */
/* The switch of a reserve in: the outgoing Pokemon leaves and the reserve is placed (sim/battle-actions.ts switchIn). A drag
 * (step G46, `drag`) skips BeforeSwitchOut and its Update (sim/battle-actions.ts:80-85), takes no pivot or Parting Shot
 * cause, and its line is [drag] (DUOFORGE_EVENT_DRAG). The entry (runSwitch) is queued, or, for a drag, run at once by the
 * caller. `*activation` is the reserve's activation id. */
static duoforge_status dfi_switch_in(dfi_run *r, uint32_t side, uint32_t slot, uint32_t reserve, bool drag,
                                     uint32_t *activation)
{
    struct duoforge_battle *b = r->b;
    const dfi_position_id where = {(uint8_t)side, (uint8_t)slot};
    const dfi_side *sd = &b->sides[side];
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
    const bool parting_shot = leaving != NULL && leaving->hp != 0u && flag == DFI_SWITCH_MOVE && !drag;
    /* A damaging pivot move's flag names the move that pivots. */
    const dfi_pivot_move *pivot = leaving != NULL && leaving->hp != 0u && !drag ? dfi_pivot_of_flag(flag) : NULL;
    if (leaving != NULL && leaving->hp != 0u && sd->positions[slot].switch_flag == 0u && !drag) {
        const duoforge_status us = dfi_update(r); /* BeforeSwitchOut, then Update (sim/battle-actions.ts:80-84) */
        if (us != DUOFORGE_OK) {
            return us;
        }
    }
    /* The SwitchOut event of the Pokemon that leaves (sim/battle-actions.ts:90, after BeforeSwitchOut and its Update, before
     * the abilities' End events and clearVolatile): Regenerator (step G39, data/abilities.ts:3833-3841 with the Champions
     * override, data/mods/champions/abilities.ts:63-70) heals the holder by floor(baseMaxhp / 3), Pokemon.heal: no TryHeal
     * event (Heal Block does not stop it) and nothing at full HP. The Champions line is `-heal|holder|hp|[from] ability:
     * Regenerator|[silent]`: silent only in that no client shows a message, the line is in the protocol with the holder's
     * new HP, so the opponent's display of the member (the knowledge fold of the events) follows it: the HEAL event, cause
     * ABILITY Regenerator, before the SWITCH event (the converter keeps this one [silent] line, trace_to_c.py). */
    if (leaving != NULL && leaving->hp != 0u && dfi_ability(b, leaving, DFI_ABILITY_REGENERATOR)) {
        dfi_member *lm = dfi_at(b, side * 2u + slot);
        if (lm->hp < lm->hp_max) {
            const uint32_t healed = (uint32_t)lm->hp_max / 3u;
            const uint32_t hp = (uint32_t)lm->hp + (healed == 0u ? 1u : healed);
            lm->hp = (uint16_t)(hp > lm->hp_max ? lm->hp_max : hp); /* wide-operands-reviewed: <= hp_max */
            dfi_emit_hp(r, dfi_ev(DUOFORGE_EVENT_HEAL, side * 2u + slot, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_REGENERATOR,
                                  DUOFORGE_NO_POSITION));
        }
    }
    if (leaving != NULL && leaving->hp != 0u) {
        /* cancelAction (sim/battle-actions.ts:107): a Pokemon that leaves
         * standing loses its queued actions. */
        dfi_cancel_actions(b, sd->positions[slot].activation_id);
    }
    dfi_party_switch(r, side, slot, reserve); /* step G46: side.pokemon order, sim/battle-actions.ts:119-133 */
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
    duoforge_event e = dfi_event_make(drag ? DUOFORGE_EVENT_DRAG : DUOFORGE_EVENT_SWITCH, side * 2u + slot);
    e.id = (uint16_t)reserve;
    if (parting_shot || pivot != NULL) {
        e.cause = (uint8_t)DUOFORGE_CAUSE_MOVE;
        e.id2 = (uint16_t)(parting_shot ? DFI_MOVE_PARTINGSHOT : pivot->move); /* wide-operands-reviewed: a move id of the pool tables, a u16 */
    }
    dfi_emit_hp(r, e);
    *activation = binding.activation_id;
    return DUOFORGE_OK;
}

static duoforge_status dfi_run_switch(dfi_run *r, const dfi_queue_record *q)
{
    uint32_t activation = 0u;
    const duoforge_status st = dfi_switch_in(r, q->side, q->slot, q->reserve, false, &activation);
    if (st != DUOFORGE_OK) {
        return st;
    }
    return dfi_insert_run_switch(r, q->side, q->slot, activation);
}

/* The entry abilities of the closure: an ability's onStart runs as a
 * SwitchIn handler (Battle.getCallback). */
static bool dfi_has_entry(const struct duoforge_battle *b, const dfi_member *m);

/* The terrain seeds (data/items.ts:2595-2614 Grassy Seed, :4903-4922 Psychic Seed, :1799-1818 Electric Seed,
 * :4200-4219 Misty Seed; the generator checks that each is Grassy Seed for its terrain and its stat): onSwitchInPriority
 * -1, onStart (not ignoringItem, the terrain is up) and onTerrainChange (the terrain is up) both call useItem, and the
 * item's boosts raise one stage of one stat: Defense for the Grassy and Electric Seeds, Special Defense for the Psychic and
 * Misty Seeds. The terrain a seed waits for, or DFI_TERRAIN_NONE for a member that holds none. */
static uint32_t dfi_seed_terrain(const struct duoforge_battle *b, const dfi_member *m)
{
    if (dfi_holds(b, m, DFI_ITEM_GRASSYSEED)) {
        return DFI_TERRAIN_GRASSY;
    }
    if (dfi_holds(b, m, DFI_ITEM_PSYCHICSEED)) {
        return DFI_TERRAIN_PSYCHIC;
    }
    if (dfi_holds(b, m, DFI_ITEM_ELECTRICSEED)) {
        return DFI_TERRAIN_ELECTRIC;
    }
    if (dfi_holds(b, m, DFI_ITEM_MISTYSEED)) {
        return DFI_TERRAIN_MISTY;
    }
    return DFI_TERRAIN_NONE;
}

/* A terrain seed (useItem): its stat +1 once, when its terrain is up: Grassy Seed's and Electric Seed's Defense, Psychic
 * Seed's and Misty Seed's Special Defense. A holder that fainted does nothing. */
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
    const bool defense = terrain == DFI_TERRAIN_GRASSY || terrain == DFI_TERRAIN_ELECTRIC;
    const uint32_t item = terrain == DFI_TERRAIN_GRASSY     ? DFI_ITEM_GRASSYSEED
                          : terrain == DFI_TERRAIN_PSYCHIC  ? DFI_ITEM_PSYCHICSEED
                          : terrain == DFI_TERRAIN_ELECTRIC ? DFI_ITEM_ELECTRICSEED
                                                            : DFI_ITEM_MISTYSEED;
    dfi_use_item(r, flat);
    dfi_boost(r, flat, defense ? def_up : spd_up, DFI_POSITIONS,
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

/* A SwitchIn handler: an entry ability (priority 0), a terrain seed's onStart (onSwitchInPriority -1), Hospitality's onStart
 * (onSwitchInPriority -2, step G30), or the toxic status's onSwitchIn (data/conditions.ts:151, the stage back to 0; a status
 * of the entering Pokemon, which stays through a switch). Its effect is internal, but the reference runs it in the switch-in
 * order, so two entering badly poisoned Pokemon of one Speed draw the tie (the G36 Toxic row, fixed by step G47; the campaign
 * seed 9800000 battle 96 showed it). The converter's switch-order rule counts the same handler. */
static bool dfi_has_switch_in(const struct duoforge_battle *b, const dfi_member *m)
{
    return dfi_has_entry(b, m) || dfi_seed_terrain(b, m) != DFI_TERRAIN_NONE ||
           dfi_ability(b, m, DFI_ABILITY_HOSPITALITY) || m->status == DFI_STATUS_TOX;
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
           now == 1u + DFI_ABILITY_UNNERVE;
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
    /* Limber's onUpdate (step G39) cures a paralysis that its holder has: a paralysed Trace holder that copies it is not
     * modelled (E_UNSUPPORTED, never a guess; no other Update handler of the marked abilities acts on a status). */
    if (copied == 1u + DFI_ABILITY_LIMBER && dfi_at(b, flat)->status == DFI_STATUS_PAR) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    /* Oblivious's onUpdate (step G47, data/abilities.ts:3009-3016) removes a taunt of its holder with its -activate line. The
     * copy comes at the entry, where no taunt stands; a taunted holder that copies it is refused, never guessed. */
    if (copied == 1u + DFI_ABILITY_OBLIVIOUS && b->tail.sides[flat / 2u].positions[flat % 2u].taunt_turns != 0u) {
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
            b->weather_turns = (uint8_t)DFI_FIELD_TURNS_MAX;
            /* -weather|...|[from] ability: X|[of] holder */
            duoforge_event e = dfi_ev(DUOFORGE_EVENT_WEATHER, DUOFORGE_NO_POSITION, DUOFORGE_CAUSE_ABILITY, a, flat);
            e.detail = (uint8_t)w; /* DUOFORGE_WEATHER_* */
            dfi_emit(r, &e);
        }
    } else if (terrain != DFI_TERRAIN_NONE) {
        if (b->terrain != terrain) {
            b->terrain = (uint8_t)terrain;
            b->terrain_turns = (uint8_t)DFI_FIELD_TURNS_MAX;
            /* -fieldstart|move: X Terrain|[from] ability: X|[of] holder */
            duoforge_event e =
                dfi_ev(DUOFORGE_EVENT_FIELD_START, DUOFORGE_NO_POSITION, DUOFORGE_CAUSE_ABILITY, a, flat);
            e.detail = (uint8_t)dfi_terrain_field_detail(terrain);
            dfi_emit(r, &e);
            return dfi_terrain_change(r);
        }
    } else if (a == 1u + DFI_ABILITY_TRACE) {
        return dfi_trace(r, flat);
    } else if (a == 1u + DFI_ABILITY_FAIRYAURA || a == 1u + DFI_ABILITY_UNNERVE) {
        /* onStart: -ability|holder|Fairy Aura (the aura itself is onAnyBasePower); Unnerve's is the same announcement
         * (step G32; its `unnerved` flag is derived: dfi_unnerved) */
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
            bearers += (((entering >> flat) & 1u) != 0u && m->hp != 0u &&
                        (dfi_has_switch_in(b, m) || dfi_side_has_hazard(b, flat / 2u)))
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
    /* setAbility ends the old ability first (sim/pokemon.ts:1923, singleEvent End), and of the abilities that the engine
     * models three have an onEnd (data/abilities.ts; the Champions mod has none): Unburden's removes its volatile
     * (:5243-5245; a holder of its own Mega Stone may have it since a Knock Off, dfi_knock_off), Flash Fire's removes the
     * flashfire volatile (:1351-1353; a Trace holder that copied Flash Fire has it after a Fire move hit it, shown as
     * `-end|X|ability: Flash Fire|[silent]`), and Unnerve's (:5265-5267) clears the `unnerved` flag of its ability state, which the
     * engine does not keep (the foes' berries follow the ability that the holder has). Nothing else that the engine keeps
     * on a position belongs to an ability, and no ability of a Mega forme in the pool is Unburden or Flash Fire. */
    {
        dfi_active_slot *mega_pos = dfi_pos(b, flat);
        mega_pos->flags = (uint8_t)((uint32_t)mega_pos->flags & ~((uint32_t)DFI_VOL_UNBURDEN | (uint32_t)DFI_VOL_FLASH_FIRE)); /* wide-operands-reviewed */
    }
    duoforge_event forme = dfi_event_make(DUOFORGE_EVENT_FORME, flat);
    forme.id = (uint16_t)dfi_mega_of(m->species_id, m->item); /* [detailschange]: < DFI_POOL_FORME_COUNT */
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
 * counter, flinch, a charge, Helping Hand, Follow Me and mustrecharge; Heal Block, Throat Chop, Encore, Disable (step G27),
 * Perish Song (step G26), Taunt and Yawn (step G31)), an item (Leftovers or White Herb), Speed Boost (step G32) and Grassy Terrain. */
#define DFI_RES_PER_POSITION 21u /* 14 before Speed Boost (G32), Disable (G27), Perish Song (G26), Taunt and Yawn (G31), the lockedmove (G56) and Roost's volatile (G42) */
#define DFI_RES_MAX (3u + 4u * DUOFORGE_SIDE_COUNT + DFI_RES_PER_POSITION * DFI_POSITIONS)
_Static_assert(DFI_RES_MAX <= DFI_RES_MODEL_MAX, "the exact test of residual_order.h must hold the whole list");

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
 * `had`: a no-order handler of any kind, `key`: the Speed key that sorts it; `ended_at`: the position whose no-order
 * faint point ended the battle, DFI_POSITIONS when none did. */
typedef struct dfi_noorder_snapshot {
    bool pair[DFI_POSITIONS];
    bool had[DFI_POSITIONS];
    uint32_t key[DFI_POSITIONS];
    uint32_t ended_at;
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

/* lockedmove's onResidual (step G56, data/conditions.ts:253-285): its count goes down for a lock used this turn (done at
 * the use, see the AfterMove block), and a lock whose holder is asleep is deleted silently (no end, no confusion). A lock
 * not used this turn and not asleep (a flinch, a full paralysis or a freeze that stopped its move) is refused where that
 * happens (dfi_lock_skipped), so every lock that stands here was used this turn. */
static duoforge_status dfi_residual_lock(dfi_run *r, uint32_t flat)
{
    if (r->b->tail.sides[flat / 2u].positions[flat % 2u].lock_turns == 0u) {
        return DUOFORGE_OK;
    }
    const dfi_member *lm = dfi_at(r->b, flat);
    if (lm != NULL && lm->status == DFI_STATUS_SLP) {
        dfi_lock_remove(r->b, flat);
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
        for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
            const dfi_active_slot *pos = dfi_pos(b, flat);
            const bool recharge = b->tail.sides[flat / 2u].positions[flat % 2u].must_recharge != 0u;
            ps->key[flat] = r->speed_seen[flat];
            ps->had[flat] = pos->occupant != DFI_OCCUPANT_NONE &&
                            (((uint32_t)pos->flags & protect_and_friends) != 0u || pos->charge_turns != 0u ||
                             pos->stall_turns != 0u || recharge);
            ps->pair[flat] = pos->occupant != DFI_OCCUPANT_NONE && dfi_alive(b, flat) &&
                             ((uint32_t)pos->flags & protect_and_friends) == DFI_VOL_PROTECT && pos->stall_level != 0u &&
                             pos->stall_turns != 0u && pos->charge_turns == 0u && !recharge;
        }
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
        } else if (m->status == DFI_STATUS_PSN || m->status == DFI_STATUS_TOX) {
            /* psn and tox have the same handler order (9, data/conditions.ts:123-161) */
            list[n] = (dfi_residual_entry){DFI_RES_POISON, flat, 9u, speed, 0u, true};
            n += 1u;
        }
        /* The volatiles with a duration handler of their own, in the one fixed order of residual_order.h (Heal
         * Block, Throat Chop, Yawn, Taunt, Encore, then the counters of the turn): Heal Block (order 20, data/moves.ts:8273-8320), Throat Chop (22,
         * :19389-19423), Yawn (23, :21152), Taunt (15, :18992) and Encore (16). Each is an entry of the sorted list at its
         * order (the reference's fieldEvent counts every duration down and ends it when its turn comes, :517-527). The
         * ones whose end shows something (Heal Block, Yawn, Taunt) are callbacks, a tie that draws, exactly when they end
         * in this residual: a tie of handlers that end nowhere shows nothing and is not drawn (the converter drops that
         * draw from the tape). Throat Chop's end is silent: its count goes down below. */
        {
            const dfi_tail_pos *vt = &b->tail.sides[flat / 2u].positions[flat % 2u];
            if (vt->heal_block_turns != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_HEAL_BLOCK, flat, 20u, speed, 2u, vt->heal_block_turns == 1u};
                n += 1u;
            }
            if (vt->disable_slot != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_DISABLE, flat, 17u, speed, 2u, vt->disable_turns == 1u};
                n += 1u;
            }
            if (vt->throat_chop_turns != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_DURATION, flat, 22u, speed, 2u, false};
                n += 1u;
            }
            if (vt->yawn_turns != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_YAWN, flat, 23u, speed, 2u, vt->yawn_turns == 1u};
                n += 1u;
            }
            if (vt->taunt_turns != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_TAUNT, flat, 15u, speed, 2u, vt->taunt_turns == 1u};
                n += 1u;
            }
            if (vt->encore_slot != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_ENCORE, flat, 16u, speed, 2u, true};
                n += 1u;
            }
            /* Perish Song (order 24, data/moves.ts:13261-13272; step G26): a volatile with a duration and a callback every
             * turn (its count line), so a handler of the sort whose tie is a drawn shuffle, like Encore's. It sorts after
             * Heal Block's (20) and Disable's (17) end lines, which are entries of the same list. */
            if (vt->perish != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_PERISH, flat, 24u, speed, 2u, true};
                n += 1u;
            }
            /* lockedmove (step G56, data/conditions.ts:253-285): no order (the pin's onResidual has no onResidualOrder), sub-order 2
             * (a condition), and a callback with a duration: the countdown, or its end when no Outrage was used this turn. */
            if (vt->lock_turns != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_LOCK, flat, DFI_RES_NO_ORDER, speed, 2u, true};
                n += 1u;
            }
            /* Roost's volatile (duration 1, onResidualOrder 25, data/moves.ts:15444-15455): its end is silent, the bit goes at
             * that entry (step G42). */
            if ((vt->single_turn & DFI_SINGLE_TURN_ROOST) != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_DURATION, flat, 25u, speed, 2u, false};
                n += 1u;
            }
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
        /* Speed Boost's onResidual (step G32, order 28, sub-order 2): the ability's handlers come before the item's in a
         * Pokemon's list (sim/battle.ts:1097-1130). */
        if (dfi_ability(r->b, m, DFI_ABILITY_SPEEDBOOST)) {
            list[n] = (dfi_residual_entry){DFI_RES_SPEED_BOOST, flat, 28u, speed, 2u, true};
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
    uint32_t early = 0u;       /* the entries of orders 1 to 23: everything that sorts before the side conditions (26) */
    uint32_t early_calls = 0u; /* ... of which the callbacks (a tie of them draws) */
    uint32_t herbs = 0u;       /* White Herb's, order 29 */
    for (uint32_t i = 0u; i < n; ++i) {
        if (list[i].kind == DFI_RES_WHITE_HERB || list[i].kind == DFI_RES_SPEED_BOOST) {
            herbs += 1u; /* the late callbacks: Speed Boost (28) and White Herb (29) */
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
    st = dfi_residual_sort(r, list, n, &sorted, &placed, early_calls + herbs, n);
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
                } else if (b->weather == DFI_WEATHER_RAIN) {
                    st = dfi_rain_dish(r); /* eachEvent('Weather'): Rain Dish's onWeather */
                    if (st != DUOFORGE_OK) {
                        return st;
                    }
                } else if (b->weather == DFI_WEATHER_SUN) {
                    st = dfi_solar_power(r); /* eachEvent('Weather'): Solar Power's onWeather (step G39) */
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
                return DUOFORGE_OK;
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
                st = dfi_try_status(r, e->flat, DFI_STATUS_SLP, e->flat, DFI_NO_SOURCE_MOVE, DFI_ORIGIN_OTHER, 0u);
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
                      DUOFORGE_NO_POSITION);
        if (st != DUOFORGE_OK) {
            return st;
        }
        dfi_process_faints(r);
        if (r->ended) {
            return DUOFORGE_OK;
        }
    }
    /* Throat Chop's count (order 22) goes down here: its end is silent, so nothing shows where it comes. Heal Block, Yawn
     * and Taunt end in the sorted list above, at their own orders. */
    {
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
                    return DUOFORGE_OK;
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
                return DUOFORGE_OK;
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
                return DUOFORGE_OK;
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
        if ((list[i].kind == DFI_RES_SPEED_BOOST || list[i].kind == DFI_RES_WHITE_HERB) &&
            dfi_residual_holder_stands(r, list[i].flat)) {
            if (list[i].kind == DFI_RES_SPEED_BOOST) {
                dfi_speed_boost(r, list[i].flat);
            } else {
                dfi_white_herb(r, list[i].flat);
            }
            dfi_residual_faints(r); /* a callback: faintMessages follows it */
            if (r->ended) {
                return DUOFORGE_OK;
            }
        }
    }
    /* The duration handlers of the volatiles that have no order come last, in Speed order (comparePriority puts no order
     * after every order): Protect, flinch, Helping Hand and Follow Me (duration 1) end at once, the stall counter and a
     * charge (2) end on their second residual, mustrecharge (2) lasts through the one of the turn that set it. Any that
     * does not end is followed by faintMessages, and a battle that ends there leaves the handlers after it unrun: the
     * ones before it ended, the ones after it keep their counters. Which handler is first among equal Speeds, and
     * between two handlers of one Pokemon, is a shuffle that the conversion drops; it shows only in the counters of a
     * Pokemon that stands when the battle ends at that faint point (a fainted one has lost its volatiles), and that
     * case is refused. */
    const uint32_t ended_flags = DFI_VOL_PROTECT | DFI_VOL_FLINCH | DFI_VOL_HELPING_HAND | DFI_VOL_FOLLOW_ME;
    uint32_t seq[DFI_POSITIONS];
    bool had[DFI_POSITIONS] = {false}; /* by position: a handler of this kind exists now (before any of them runs) */
    uint32_t seq_n = 0u;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        const dfi_active_slot *pos = dfi_pos(b, flat);
        if (pos->occupant != DFI_OCCUPANT_NONE) {
            seq[seq_n] = flat;
            seq_n += 1u;
            had[flat] = ((uint32_t)pos->flags & ended_flags) != 0u || pos->charge_turns != 0u || pos->stall_turns != 0u ||
                        b->tail.sides[flat / 2u].positions[flat % 2u].must_recharge != 0u;
        }
    }
    for (uint32_t i = 1u; i < seq_n; ++i) {
        for (uint32_t j = i; j > 0u && r->speed_seen[seq[j]] > r->speed_seen[seq[j - 1u]]; --j) {
            const uint32_t swap = seq[j];
            seq[j] = seq[j - 1u];
            seq[j - 1u] = swap;
        }
    }
    for (uint32_t i = 0u; i < seq_n; ++i) {
        const uint32_t flat = seq[i];
        dfi_active_slot *pos = dfi_pos(b, flat);
        const bool keeps = (pos->stall_level != 0u && pos->stall_turns > 1u) || pos->charge_turns > 1u ||
                           b->tail.sides[flat / 2u].positions[flat % 2u].must_recharge != 0u;
        const bool also_ends = ((uint32_t)pos->flags & ended_flags) != 0u || pos->charge_turns == 1u || pos->stall_turns == 1u;
        const bool pair_here = ps->pair[flat]; /* Protect's volatile and the stall counter, nothing else: see below */
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
        /* lockedmove (step G56): an order-less callback in this Speed order, after the counters it shares a sub-order with. */
        if (dfi_alive(b, flat) && b->tail.sides[flat / 2u].positions[flat % 2u].lock_turns != 0u) {
            st = dfi_residual_lock(r, flat);
            if (st != DUOFORGE_OK) {
                return st;
            }
        }
        if (keeps && r->faint_count != 0u) {
            dfi_residual_faints(r);
            if (r->ended) {
                if (also_ends && !pair_here && dfi_alive(b, flat)) {
                    return DUOFORGE_E_UNSUPPORTED; /* its own other handler: before or after the faint point */
                }
                for (uint32_t j = 0u; j < seq_n; ++j) {
                    if (j != i && had[seq[j]] && dfi_alive(b, seq[j]) && r->speed_seen[seq[j]] == r->speed_seen[flat]) {
                        return DUOFORGE_E_UNSUPPORTED; /* equal Speed: the shuffle decides who ran */
                    }
                }
                if (pair_here) {
                    ps->ended_at = flat; /* Protect's volatile is still there: dfi_residual_pair_draws decides */
                }
                return DUOFORGE_OK;
            }
        }
        if (pair_here) {
            pos->flags = (uint8_t)((uint32_t)pos->flags & ~ended_flags); /* wide-operands-reviewed */
            b->tail.sides[flat / 2u].positions[flat % 2u].protect_kind = (uint8_t)DFI_PROTECT_PLAIN;
        }
    }
    return DUOFORGE_OK;
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
    dfi_noorder_snapshot ps = {{false}, {false}, {0u}, DFI_POSITIONS};
    const duoforge_status st = dfi_residual_events_run(r, &ps);
    if (st != DUOFORGE_OK || !r->ended) {
        return st;
    }
    return dfi_residual_pair_draws(r, &ps);
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
    /* endTurn: newlySwitched ends (sim/battle.ts:1673; Team C), and DisableMove runs for every active Pokemon
     * (sim/battle.ts:1691), where choicelock ends for a holder without its Choice item. */
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        dfi_choice_lock_ends(b, flat);
        dfi_active_slot *pos = dfi_pos(b, flat);
        pos->flags = (uint8_t)((uint32_t)pos->flags & ~DFI_VOL_NEWLY_SWITCHED); /* wide-operands-reviewed */
        /* moveLastTurnResult = moveThisTurnResult, then this turn's is undefined (sim/battle.ts:1674-1675). The unclassified
         * bit moves with the result (step G42). */
        dfi_tail_pos *tp = &b->tail.sides[flat / 2u].positions[flat % 2u];
        const uint32_t mr = tp->move_result;
        tp->move_result = (uint8_t)(((mr & 3u) << DFI_MOVE_RESULT_LAST_SHIFT) | /* wide-operands-reviewed: <= 0x3F */
                                    ((mr & DFI_MOVE_RESULT_UNCLASSIFIED_NOW) != 0u ? DFI_MOVE_RESULT_UNCLASSIFIED_LAST : 0u));
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
/* The drag in (step G46, sim/battle-actions.ts:162-174, dragIn). The reserve is drawn first, from the bench in side.pokemon
 * order (party_order, the non-fainted reserves; no draw when there is none: sim/battle.ts:1570-1588), and only then the
 * outgoing holder's DragOut runs: a block after the draw still consumed it (the pin's order, mirrored on purpose). The
 * switch-in is switchIn with isDrag (no BeforeSwitchOut, no Update, the [drag] line), and its entry runs at once (gen 5+,
 * battle-actions.ts:153-155), together with the entries queued right behind it. */
static duoforge_status dfi_drag_in(dfi_run *r, uint32_t side, uint32_t slot)
{
    struct duoforge_battle *b = r->b;
    const dfi_side *sd = &b->sides[side];
    uint32_t brought = 0u;
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        brought += (uint32_t)sd->brought_mask >> m & 1u;
    }
    uint32_t cand[DUOFORGE_MAX_ROSTER];
    uint32_t n = 0u;
    for (uint32_t k = DUOFORGE_ACTIVE_PER_SIDE; k < brought && k < DUOFORGE_MAX_ROSTER; ++k) {
        const uint32_t e = dfi_party_entry(&b->tail, side, k);
        if (e != 0u && e <= DUOFORGE_MAX_ROSTER && sd->members[e - 1u].hp != 0u) {
            cand[n] = e - 1u;
            n += 1u;
        }
    }
    if (n == 0u) {
        return DUOFORGE_OK; /* getRandomSwitchable returns null: no draw, no switch */
    }
    uint32_t pick = 0u;
    duoforge_status st = dfi_draw(r->draws, DFI_SITE_DRAG, 0u, n, &pick);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const uint32_t flat = side * 2u + slot;
    const dfi_member *old = dfi_at(b, flat);
    if (old == NULL || old->hp == 0u) {
        return DUOFORGE_OK; /* sim/battle-actions.ts:166-167 (the holder fainted: no drag) */
    }
    if (dfi_drag_blocked(r, flat)) {
        return DUOFORGE_OK; /* DragOut (Suction Cups, Guard Dog) returns null: the drag is not made */
    }
    uint32_t activation = 0u;
    st = dfi_switch_in(r, side, slot, cand[pick], true, &activation);
    if (st != DUOFORGE_OK) {
        return st;
    }
    uint32_t entering = 1u << flat;
    while (b->queue_len > 0u && b->queue[0].kind == DFI_Q_RUN_SWITCH) {
        dfi_queue_record q;
        dfi_queue_pop(b, &q);
        entering |= 1u << ((uint32_t)q.side * 2u + (uint32_t)q.slot);
    }
    return dfi_run_entries(r, entering);
}

/* The phazing loop after an action (sim/battle.ts:2822-2827): each position in order, sides first, whose forceSwitchFlag is set
 * is dragged in if its Pokemon still stands; the flag is cleared either way. */
static duoforge_status dfi_phaze(dfi_run *r)
{
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
            const uint32_t flat = side * 2u + slot;
            if (((r->drag_pending >> flat) & 1u) == 0u) {
                continue;
            }
            r->drag_pending &= ~(1u << flat);
            const dfi_member *m = dfi_at(r->b, flat);
            if (m != NULL && m->hp != 0u) {
                const duoforge_status st = dfi_drag_in(r, side, slot);
                if (st != DUOFORGE_OK) {
                    return st;
                }
            }
        }
    }
    return DUOFORGE_OK;
}

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
    dfi_run r = {ctx, b, draws, {0u, 0u, 0u, 0u}, 0u, 0u, 0u, false, DFI_RESULT_NONE, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}, events, UINT32_MAX, false, DFI_MOVE_TARGET_NONE, 1u, 0u, 0u, 0u, DFI_POSITIONS, false};
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
    dfi_run r = {ctx, b, draws, {0u, 0u, 0u, 0u}, 0u, 0u, 0u, false, DFI_RESULT_NONE, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}, events, UINT32_MAX, false, DFI_MOVE_TARGET_NONE, 1u, 0u, 0u, 0u, DFI_POSITIONS, false};
    dfi_init_speeds(&r);
    duoforge_status st = DUOFORGE_OK;
    uint32_t exits = 0u; /* Emergency Exit after the residual action */
    uint32_t switch_flat = DFI_POSITIONS; /* the Pokemon of the runSwitch action that ran (Emergency Exit after it) */
    uint32_t switch_hp = 0u;              /* its HP before the action (sim/battle.ts:2666) */
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
            /* lockedmove (step G56): a locked user whose move is stopped before its use (a flinch, a freeze, a full paralysis)
             * keeps the lock into the residual, where its end (fieldEvent, onEnd) would need the lock's count and the
             * order of that end, which is not modelled: refused. A sleeping holder is not refused (its lock is deleted
             * silently at the residual, as the pin does). */
            const uint32_t mover = (uint32_t)q.side * 2u + (uint32_t)q.slot;
            const bool lock_before = b->tail.sides[mover / 2u].positions[mover % 2u].lock_turns != 0u;
            st = dfi_run_move(&r, &q, &ran);
            if (st != DUOFORGE_OK) {
                return st;
            }
            if (lock_before && !r.move_used) {
                const dfi_member *mm = dfi_at(b, mover);
                if (mm != NULL && mm->hp != 0u && mm->status != DFI_STATUS_SLP) {
                    return DUOFORGE_E_UNSUPPORTED;
                }
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
                /* lockedmove's confusion (step G56) at the end of this use, after the White Herb's AnyAfterMove: when both would
                 * print (a holder whose stat is down, and a lock that ends with a count of 1 or less), their order is not modelled. */
                const bool lock_ends_here = b->tail.sides[user / 2u].positions[user % 2u].lock_turns != 0u &&
                                            ((r.lock_restarted >> user) & 1u) == 0u && b->tail.sides[user / 2u].positions[user % 2u].lock_turns <= 1u &&
                                            dfi_at(b, user) != NULL && dfi_at(b, user)->hp != 0u;
                if (lock_ends_here && dfi_herbs_matter(&r)) {
                    return DUOFORGE_E_UNSUPPORTED;
                }
                if (collected) {
                    st = dfi_herb_event(&r, user);
                    if (st != DUOFORGE_OK) {
                        return st;
                    }
                }
                /* lockedmove (step G56, data/conditions.ts:253-285). A use that restarted the lock (lock_restarted: a hit with a
                 * count of 2 or more, or the start) keeps it: its count goes down by the residual of this turn, which is done
                 * here, at the use, so that no residual of a later call (a replacement's pause) has to remember the restart.
                 * A use that did not restart it: onAfterMove removes it at duration 1 (after any result), and onEnd confuses
                 * when the count is 1 or less. A fainted user has no handler (its volatiles were cleared). */
                const dfi_member *um = dfi_at(b, user);
                const bool restarted_use = ((r.lock_restarted >> user) & 1u) != 0u;
                r.lock_restarted &= ~(1u << user); /* wide-operands-reviewed: user < 4 */
                if (b->tail.sides[user / 2u].positions[user % 2u].lock_turns != 0u && um != NULL && um->hp != 0u) {
                    if (restarted_use) {
                        dfi_tail_pos *ut = &b->tail.sides[user / 2u].positions[user % 2u];
                        ut->lock_turns = (uint8_t)((uint32_t)ut->lock_turns - 1u); /* wide-operands-reviewed: >= 1 */
                    } else {
                        if (b->tail.sides[user / 2u].positions[user % 2u].lock_turns <= 1u && dfi_herbs_matter(&r)) {
                            /* the White Herb's AnyAfterMove and this confusion would both print: the order is not modelled */
                            return DUOFORGE_E_UNSUPPORTED;
                        }
                        st = dfi_lock_end(&r, user);
                        if (st != DUOFORGE_OK) {
                            return st;
                        }
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
            switch_flat = (uint32_t)q.side * 2u + (uint32_t)q.slot;
            switch_hp = dfi_at(b, switch_flat) != NULL ? dfi_at(b, switch_flat)->hp : 0u;
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
        /* A move's own faintMessages (sim/battle-actions.ts:347, at the end of useMove, with its checkWin) comes before the
         * phazing loop of runAction (sim/battle.ts:2822-2827), so the faints of the move (an item's recoil included) and a
         * win they cause are shown first; the phazing still runs after a win (the reference drags after its [win]). The
         * other actions have no such step; the rest of the faints follow the phazing (dfi_process_faints). */
        if (q.kind == DFI_Q_MOVE) {
            const bool fresh = r.faint_announced < r.faint_count && r.early_result == DFI_RESULT_NONE;
            dfi_announce_faints(&r, fresh);
        }
        st = dfi_phaze(&r); /* the phazing loop of runAction, before the faints (sim/battle.ts:2822-2827; step G46) */
        if (st != DUOFORGE_OK) {
            return st;
        }
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
                if (dfi_exits(b, flat, r.residual_hp[flat], r.drag_pending)) {
                    exits |= 1u << flat;
                    const duoforge_event e = dfi_ev(DUOFORGE_EVENT_ACTIVATE, flat, DUOFORGE_CAUSE_ABILITY,
                                                    1u + DFI_ABILITY_EMERGENCYEXIT, DUOFORGE_NO_POSITION);
                    dfi_emit(&r, &e); /* [-activate] ability: Emergency Exit */
                }
            }
        }
        if (q.kind == DFI_Q_RUN_SWITCH && switch_flat < DFI_POSITIONS) {
            /* sim/battle.ts:2871-2874: after the Update, the Pokemon of a runSwitch action that a hazard took from above half
             * its HP to half or less runs its EmergencyExit event (only the first Pokemon of the batch: the action's own). */
            dfi_emergency_exit(&r, switch_flat, switch_hp);
            if (b->queue_len == 0u && dfi_pos(b, switch_flat)->switch_flag == DFI_SWITCH_EMERGENCY_EXIT) {
                exits |= 1u << switch_flat; /* nothing is queued: the turn ends with a request for its replacement */
            }
            switch_flat = DFI_POSITIONS;
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
