#include "combat/turn.h"

#include "combat/ability_family.h"
#include "combat/events.h"
#include "combat/item_family.h"

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

static const dfi_forme_data *dfi_forme_of(const dfi_member *m)
{
    const dfi_forme_data *base = &dfi_pool_formes[m->species_id];
    return m->is_mega != 0u ? &dfi_pool_formes[base->mega_forme] : base;
}

static bool dfi_has_type(const dfi_member *m, uint32_t type)
{
    const dfi_forme_data *f = dfi_forme_of(m);
    return f->types[0] == type || f->types[1] == type;
}

/* isGrounded with the data: not Flying (no Levitate, Air Balloon or Gravity). */
static bool dfi_grounded(const dfi_member *m)
{
    return !dfi_has_type(m, DFI_TYPE_FLYING);
}

/* The member holds item `id` and has not used it up (items are stored as
 * 1 + id). */
static bool dfi_holds(const dfi_member *m, uint32_t id)
{
    return m != NULL && m->item == 1u + id && m->item_consumed == 0u;
}

/* The member's ability is `id` (abilities are stored as 1 + id). */
static bool dfi_ability(const dfi_member *m, uint32_t id)
{
    return m != NULL && m->ability == 1u + id;
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
 * 50 of 100), capped, negated under Trick Room. A fainted Pokemon is not active,
 * so no ModifySpe handler runs for it (Battle.findEventHandlers,
 * sim/battle.ts): its queued action or its replacement has the raw Speed. */
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
    if (active && dfi_holds(m, DFI_ITEM_CHOICESCARF) && !dfi_chain_modify(chain, 6144u, &chain)) {
        return DUOFORGE_E_INVARIANT;
    }
    /* Unburden's volatile (Team C): chainModify(2) while its holder holds no
     * item, which is always once the volatile is set (data/abilities.ts). */
    if (active && ((uint32_t)pos->flags & DFI_VOL_UNBURDEN) != 0u && !dfi_chain_modify(chain, 8192u, &chain)) {
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

/* A queued move names a slot its actor has, or Struggle. The checker
 * accepts any slot up to Struggle (structure, not reachability), so a
 * decoded state can name an empty slot: that fails loudly instead of
 * running the empty slot. */
static bool dfi_move_slot_ok(const dfi_member *m, uint32_t move_slot)
{
    return move_slot == DUOFORGE_MOVE_SLOT_STRUGGLE || move_slot < m->move_count;
}

static uint32_t dfi_move_of(const dfi_member *m, uint32_t move_slot)
{
    return move_slot == DUOFORGE_MOVE_SLOT_STRUGGLE ? DFI_MOVE_STRUGGLE : m->moves[move_slot].move_id;
}

/* ---------------------------------------------------------------- queue */

/* ModifyPriority: Prankster gives status moves +1, Grassy Glide gets +1
 * in Grassy Terrain for a grounded user. Biased like the move table. */
static uint32_t dfi_move_priority(const struct duoforge_battle *b, const dfi_member *m, const dfi_move_data *md)
{
    uint32_t priority = md->priority;
    if (dfi_ability(m, DFI_ABILITY_PRANKSTER) && md->category == DFI_CATEGORY_STATUS) {
        priority += 1u;
    }
    if (md->special == DFI_SPECIAL_GRASSY_GLIDE && b->terrain == DFI_TERRAIN_GRASSY && dfi_grounded(m)) {
        priority += 1u;
    }
    return priority;
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
} dfi_boost_effect;

static dfi_boost_effect dfi_effect(uint32_t cause, uint32_t id2, uint32_t mode)
{
    const dfi_boost_effect e = {cause, id2, mode};
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
        const uint32_t want = dfi_ability(m, DFI_ABILITY_CONTRARY) ? 12u - (uint32_t)boosts[i] : boosts[i];
        const uint32_t sum = (uint32_t)pos->stages[i] + want; /* the target stage, biased by 12 */
        const uint32_t to = sum < 6u ? 0u : (sum - 6u > 12u ? 12u : sum - 6u);
        const uint32_t delta = to + 6u - (uint32_t)pos->stages[i];
        capped[i] = (uint8_t)delta; /* 0..12 */
    }
    bool announced = effect.mode == DFI_BOOST_SECONDARY;
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        if (boosts[i] == DFI_BIAS6) {
            continue; /* not part of this boost */
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
            if (capped[i] < DFI_BIAS6 && dfi_ability(m, DFI_ABILITY_COMPETITIVE) && source < DFI_POSITIONS &&
                source / 2u != flat / 2u) {
                static const uint8_t raise[DFI_STAT_STAGE_COUNT] = {6u, 6u, 8u, 6u, 6u, 6u, 6u}; /* SpA +2 */
                dfi_boost(r, flat, raise, flat,
                          dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_COMPETITIVE, DFI_BOOST_SELF));
            }
            /* Defiant (Team C, decision 0009): Competitive's shape with
             * Attack (data/abilities.ts:901-921). */
            if (capped[i] < DFI_BIAS6 && dfi_ability(m, DFI_ABILITY_DEFIANT) && source < DFI_POSITIONS &&
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
static bool dfi_type_immune(const dfi_member *target, uint32_t move_type)
{
    if (move_type >= DFI_TYPE_COUNT) {
        return false;
    }
    const dfi_forme_data *f = dfi_forme_of(target);
    for (uint32_t i = 0u; i < 2u; ++i) {
        const uint32_t t = f->types[i];
        if (t < DFI_TYPE_COUNT && dfi_closure_type_chart[t][move_type] == DFI_EFFECT_IMMUNE) {
            return true;
        }
    }
    return false;
}

/* runEffectiveness, biased by 6: +1 per super effective, -1 per resisted
 * defending type. */
static uint32_t dfi_type_mod(const dfi_member *target, uint32_t move_type)
{
    uint32_t mod = DFI_BIAS6;
    if (move_type >= DFI_TYPE_COUNT) {
        return mod;
    }
    const dfi_forme_data *f = dfi_forme_of(target);
    for (uint32_t i = 0u; i < 2u; ++i) {
        const uint32_t t = f->types[i];
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
    /* BasePower (after the critical hit roll), one chained modifier: Mystic
     * Water (Water) and Miracle Seed (Grass) 4915/4096, Grassy Terrain
     * 5325/4096 for a grounded user's Grass move. */
    /* Weather Ball doubles in rain or sun (onModifyMove); Grass Knot's power
     * follows the target's weight (basePowerCallback). */
    uint32_t power = md->base_power;
    if (md->special == DFI_SPECIAL_WEATHER_BALL && r->b->weather != DFI_WEATHER_NONE) {
        power *= 2u;
    } else if (md->special == DFI_SPECIAL_GRASS_KNOT) {
        const uint32_t w = dfi_forme_of(d)->weight_hg;
        power = w >= 2000u ? 120u : w >= 1000u ? 100u : w >= 500u ? 80u : w >= 250u ? 60u : w >= 100u ? 40u : 20u;
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
    if (dfi_ate_boosts(a, md->type, move_type)) {
        ok = dfi_chain_modify(bp_chain, DFI_ATE_MODIFIER, &bp_chain);
    }
    if (dfi_ability(a, DFI_ABILITY_TOUGHCLAWS) && (md->flags & DFI_MOVE_FLAG_CONTACT) != 0u) {
        ok = dfi_chain_modify(bp_chain, 5325u, &bp_chain); /* onBasePowerPriority 21: first */
    }
    /* A type booster (the TYPE_BOOSTER family: Mystic Water, Miracle Seed
     * and the sixteen others, decision 0015): 4915/4096 for a move of its
     * type (onBasePowerPriority 15). */
    if (dfi_type_booster_applies(a, move_type)) {
        ok = ok && dfi_chain_modify(bp_chain, DFI_TYPE_BOOSTER_MODIFIER, &bp_chain);
    }
    /* Helping Hand's volatile (Team C): chainModify(1.5) at
     * onBasePowerPriority 10, after the items (15) and before Grassy Terrain
     * (6) (data/moves.ts:8590-8597). */
    if (((uint32_t)dfi_pos(r->b, user)->flags & DFI_VOL_HELPING_HAND) != 0u) {
        ok = ok && dfi_chain_modify(bp_chain, 6144u, &bp_chain);
    }
    if (move_type == DFI_TYPE_GRASS && r->b->terrain == DFI_TERRAIN_GRASSY && dfi_grounded(a)) {
        ok = ok && dfi_chain_modify(bp_chain, 5325u, &bp_chain);
    }
    /* Psychic Terrain (Team C): 5325/4096 for a grounded user's Psychic move
     * (onBasePowerPriority 6, like Grassy Terrain's, which cannot be up at
     * the same time). */
    if (move_type == DFI_TYPE_PSYCHIC && r->b->terrain == DFI_TERRAIN_PSYCHIC && dfi_grounded(a)) {
        ok = ok && dfi_chain_modify(bp_chain, 5325u, &bp_chain);
    }
    const uint32_t base_power = bp_chain == 4096u ? power : dfi_modify(power, bp_chain);
    /* ModifyAtk / ModifySpA, one chained modifier: a pinch ability (the
     * PINCH family: Blaze, Overgrow, Torrent and Swarm, decision 0015) for a
     * move of its type at a third of the HP or less, Flash Fire's boost for
     * Fire moves once it took one; 1.5 each. */
    uint32_t atk_chain = 4096u;
    if (dfi_pinch_applies(a, move_type)) {
        ok = ok && dfi_chain_modify(atk_chain, DFI_PINCH_MODIFIER, &atk_chain);
    }
    if (move_type == DFI_TYPE_FIRE && dfi_ability(a, DFI_ABILITY_FLASHFIRE) &&
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
        const uint32_t stab = !dfi_has_type(a, move_type) ? 4096u
                              : dfi_ability(a, DFI_ABILITY_ADAPTABILITY) ? 8192u
                                                                         : 6144u;
        damage = dfi_modify(damage, stab);
        mod = dfi_type_mod(d, move_type);
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
    if (dfi_holds(a, DFI_ITEM_LIFEORB)) {
        ok = dfi_chain_modify(chain, 5324u, &chain);
    }
    /* A resist berry (the RESIST_BERRY family: Chople Berry and the sixteen
     * others, decision 0015; combat/item_family.h) is eaten by a super
     * effective hit of its type, the Normal berry by any Normal hit. */
    if (dfi_resist_berry_applies(d, move_type, mod)) {
        const uint32_t berry_item = d->item;
        dfi_use_item(r, target); /* [-enditem] [eat] */
        duoforge_event weaken =
            dfi_ev(DUOFORGE_EVENT_ITEM_END, target, DUOFORGE_CAUSE_NONE, berry_item, DUOFORGE_NO_POSITION);
        weaken.detail = 1u;
        dfi_emit(r, &weaken); /* [-enditem] [weaken] */
        ok = ok && dfi_chain_modify(chain, DFI_RESIST_BERRY_MODIFIER, &chain);
    }
    if (!crit && target != user &&
        ((physical && ds->reflect_turns != 0u) ||
         (md->category == DFI_CATEGORY_SPECIAL && ds->light_screen_turns != 0u))) {
        ok = ok && dfi_chain_modify(chain, 2732u, &chain);
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
static bool dfi_poison_immune(const dfi_member *m)
{
    for (uint32_t type = 0u; type < DFI_TYPE_COUNT; ++type) {
        if ((dfi_pool_type_immunity[type] & DFI_IMMUNE_PSN) != 0u && dfi_has_type(m, type)) {
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
                                      bool primary)
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
    if ((status == DFI_STATUS_BRN && dfi_has_type(m, DFI_TYPE_FIRE)) ||
        (status == DFI_STATUS_PAR && dfi_has_type(m, DFI_TYPE_ELECTRIC)) ||
        (status == DFI_STATUS_FRZ && (dfi_has_type(m, DFI_TYPE_ICE) || r->b->weather == DFI_WEATHER_SUN)) ||
        (status == DFI_STATUS_PSN && dfi_poison_immune(m))) {
        if (primary) {
            dfi_immune(r, flat, 0u);
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
    return m != NULL && m->hp != 0u && m->ability == 1u + DFI_ABILITY_EMERGENCYEXIT &&
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
    b->sides[side].members[occupant].item_consumed = 1u;
    const uint32_t item = b->sides[side].members[occupant].item;
    duoforge_event e = dfi_ev(DUOFORGE_EVENT_ITEM_END, flat, DUOFORGE_CAUSE_NONE, item, DUOFORGE_NO_POSITION);
    const bool berry = item == 1u + DFI_ITEM_SITRUSBERRY ||
                       (item != 0u && item <= DFI_POOL_ITEM_COUNT &&
                        dfi_pool_item_family[item - 1u].family == DFI_ITEM_FAMILY_RESIST_BERRY);
    e.flags = berry ? (uint8_t)DUOFORGE_EVENT_FLAG_EATEN : 0u;
    dfi_emit(r, &e);
    /* AfterUseItem: Unburden adds its volatile (Team C, data/abilities.ts). */
    if (b->sides[side].members[occupant].ability == 1u + DFI_ABILITY_UNBURDEN) {
        dfi_active_slot *pos = dfi_pos(b, flat);
        pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_UNBURDEN); /* wide-operands-reviewed: < 256 */
    }
}

/* White Herb's check (onStart, data/items.ts): its standing holder has a
 * lowered stat. */
static bool dfi_herb_due(struct duoforge_battle *b, uint32_t flat)
{
    const dfi_member *m = dfi_at(b, flat);
    if (m == NULL || m->hp == 0u || !dfi_holds(m, DFI_ITEM_WHITEHERB)) {
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
    return m != NULL && m->hp != 0u && dfi_holds(m, DFI_ITEM_WHITEHERB);
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
        bearers |= dfi_holds(dfi_at(r->b, flat), DFI_ITEM_SITRUSBERRY) ? 1u << flat : 0u;
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
        if (m->hp != 0u && dfi_holds(m, DFI_ITEM_SITRUSBERRY) && (uint32_t)m->hp * 2u <= m->hp_max &&
            !dfi_heal_blocked(r->b, flat)) {
            dfi_use_item(r, flat);
            dfi_heal(r, flat, (uint32_t)m->hp_max / 4u, DUOFORGE_CAUSE_ITEM, 1u + DFI_ITEM_SITRUSBERRY,
                     DUOFORGE_NO_POSITION);
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
                if (dfi_focus_sash_saves(m, damage)) {
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
    if (dfi_ability(dfi_at(r->b, ally), DFI_ABILITY_GOODASGOLD)) {
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
        q->move_slot + 1u != pos->locked_move) {
        return DUOFORGE_E_INVARIANT;
    }
    *ran = true;
    r->move_used = false;
    if (pos->move_actions < UINT8_MAX) {
        pos->move_actions = (uint8_t)((uint32_t)pos->move_actions + 1u); /* wide-operands-reviewed */
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
    if (dfi_holds(m, DFI_ITEM_CHOICESCARF) && q->move_slot < DUOFORGE_MAX_MOVE_SLOTS &&
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
    const bool single = count <= 1u && (md->target_class == DUOFORGE_TARGET_CLASS_NORMAL ||
                                        md->target_class == DUOFORGE_TARGET_CLASS_ANY ||
                                        md->target_class == DUOFORGE_TARGET_CLASS_ADJACENT_FOE ||
                                        md->target_class == DFI_TARGET_CLASS_RANDOM_NORMAL);
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
            if (flat == user || holder == NULL || holder->hp == 0u || !dfi_ability(holder, DFI_ABILITY_LIGHTNINGROD)) {
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
                if (holder != NULL && holder->hp != 0u && dfi_ability(holder, DFI_ABILITY_ARMORTAIL)) {
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
    if (md->special == DFI_SPECIAL_FOLLOW_ME) {
        return dfi_run_follow_me(r, user);
    }
    const bool status_move = md->category == DFI_CATEGORY_STATUS;
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
        const uint32_t screen = dfi_holds(m, DFI_ITEM_LIGHTCLAY) ? DFI_SCREEN_TURNS_MAX : 5u;
        const uint32_t duration = md->side_condition == DFI_SIDE_CONDITION_TAILWIND ? DFI_TAILWIND_TURNS_MAX : screen;
        *turns = (uint8_t)duration; /* <= 8 */
        duoforge_event e = dfi_event_make(DUOFORGE_EVENT_SIDE_START, DUOFORGE_NO_POSITION);
        e.detail = (uint8_t)side;
        e.amount = (uint8_t)md->side_condition; /* DUOFORGE_SIDE_* */
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
    if (status_move && md->primary_status == DFI_STATUS_NONE && md->special != DFI_SPECIAL_PARTING_SHOT) {
        if (md->boost_role != DFI_BOOST_ROLE_PRIMARY_SELF || md->target_class != DUOFORGE_TARGET_CLASS_SELF) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        if (dfi_boost(r, user, md->boosts, DFI_POSITIONS, dfi_effect(DUOFORGE_CAUSE_MOVE, 0u, DFI_BOOST_PRIMARY))) {
            return dfi_status_hit_end(r);
        }
        return DUOFORGE_OK; /* nothing changed: the hit loop stops */
    }
    /* A handler this build does not have fails explicitly; the Team C
     * specials of later steps are also kept out by the support manifest. */
    if (md->special > DFI_SPECIAL_STRUGGLE && md->special != DFI_SPECIAL_DARKEST_LARIAT &&
        md->special != DFI_SPECIAL_LAST_RESPECTS && md->special != DFI_SPECIAL_SUCKER_PUNCH) {
        return DUOFORGE_E_INVARIANT;
    }
    /* Fake Out's onTry (in trySpreadMoveHit, after TryMove): only on the
     * first move action since it entered. */
    if (md->special == DFI_SPECIAL_FAKE_OUT && pos->move_actions > 1u) {
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
            attacks = next->move_slot == DUOFORGE_MOVE_SLOT_STRUGGLE ||
                      dfi_pool_moves[dfi_move_of(t, next->move_slot)].category != DFI_CATEGORY_STATUS;
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
    /* Struggle is typeless; Weather Ball turns Water in rain, Fire under sun
     * (its onModifyType, before the hit steps). */
    uint32_t move_type = md->special == DFI_SPECIAL_STRUGGLE ? DFI_CLOSURE_NONE : md->type;
    /* An -ate ability (the ATE family, decision 0015): onModifyType
     * (priority -1) turns a Normal move into its type before immunity and
     * STAB; Weather Ball is in its noModifyType list and Struggle is
     * typeless by then (data/abilities.ts). */
    move_type = dfi_ate_type_of(m, md, move_type);
    if (md->special == DFI_SPECIAL_WEATHER_BALL && b->weather == DFI_WEATHER_RAIN) {
        move_type = DFI_TYPE_WATER;
    } else if (md->special == DFI_SPECIAL_WEATHER_BALL && b->weather == DFI_WEATHER_SUN) {
        move_type = DFI_TYPE_FIRE;
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
    for (uint32_t i = 0u; i < count; ++i) {
        const uint32_t t = targets[i];
        const dfi_active_slot *tp = dfi_pos(b, t);
        if (psychic_block && t / 2u != side && dfi_grounded(dfi_at(b, t))) {
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
        if (dfi_ability(tm, DFI_ABILITY_FLASHFIRE) && move_type == DFI_TYPE_FIRE) {
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
        } else if (dfi_ability(tm, DFI_ABILITY_LIGHTNINGROD) && move_type == DFI_TYPE_ELECTRIC) {
            static const uint8_t spa_up[DFI_STAT_STAGE_COUNT] = {6u, 6u, 7u, 6u, 6u, 6u, 6u};
            if (!dfi_boost(r, t, spa_up, user,
                           dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_LIGHTNINGROD, DFI_BOOST_PRIMARY))) {
                dfi_immune(r, t, 1u + DFI_ABILITY_LIGHTNINGROD);
            }
            hit[i] = false;
        } else if (dfi_ability(tm, DFI_ABILITY_GOODASGOLD) && status_move) {
            dfi_immune(r, t, 1u + DFI_ABILITY_GOODASGOLD);
            hit[i] = false;
        }
    }
    for (uint32_t i = 0u; i < count && !status_move; ++i) {
        if (hit[i] && dfi_type_immune(dfi_at(b, targets[i]), move_type)) {
            hit[i] = false; /* a status move ignores type immunity */
            dfi_immune(r, targets[i], 0u);
        }
    }
    /* hitStepTryImmunity: a Prankster-boosted status move fails on a Dark
     * foe. */
    for (uint32_t i = 0u; i < count && status_move && dfi_ability(m, DFI_ABILITY_PRANKSTER); ++i) {
        if (hit[i] && targets[i] / 2u != side && dfi_has_type(dfi_at(b, targets[i]), DFI_TYPE_DARK)) {
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
            if (dfi_ability(m, DFI_ABILITY_NOGUARD) || dfi_ability(dfi_at(b, targets[i]), DFI_ABILITY_NOGUARD)) {
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
            const uint32_t before = dfi_at(b, targets[i])->status;
            st = dfi_try_status(r, targets[i], md->primary_status, user, move_id, true);
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
            if (dfi_focus_sash_saves(tm, damage[i])) {
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
    /* selfSwitch of a damaging move (Flip Turn, Team C, the only one in the
     * data): runMoveEffects flags the user when the move hit a target and the
     * user still stands; with no reserve the request would clear it again
     * (sim/battle-actions.ts:1290-1312), so the engine sets it only when a
     * reserve can come in, as for Parting Shot. A user that a Rocky Helmet
     * then knocks out loses it again (faint(), sim/pokemon.ts:1585): here
     * with the position's other state when the faint is processed. */
    if ((md->flags & DFI_MOVE_FLAG_SELF_SWITCH) != 0u) {
        bool hit_any = false;
        for (uint32_t i = 0u; i < count; ++i) {
            hit_any = hit_any || hit[i];
        }
        if (hit_any && m->hp != 0u && dfi_can_switch(b, side)) {
            pos->switch_flag = (uint8_t)DFI_SWITCH_FLIP_TURN;
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
                st = dfi_try_status(r, targets[i], md->sec_param, user, move_id, false);
            } else if (md->sec_kind == DFI_SECONDARY_VOLATILE) {
                st = dfi_add_volatile(r, targets[i], md->sec_param);
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
                    st = dfi_try_status(r, targets[i], pick[v], user, DFI_NO_SOURCE_MOVE, false);
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
    for (uint32_t i = 0u; i < count; ++i) {
        if (hit[i] && (md->flags & DFI_MOVE_FLAG_CONTACT) != 0u &&
            dfi_holds(dfi_at(b, targets[i]), DFI_ITEM_ROCKYHELMET)) {
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
        if (!hit[i] || tm->hp == 0u) {
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
        if (dfi_ability(tm, DFI_ABILITY_STAMINA)) {
            static const uint8_t def_up[DFI_STAT_STAGE_COUNT] = {6u, 7u, 6u, 6u, 6u, 6u, 6u};
            dfi_boost(r, targets[i], def_up, user,
                      dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_STAMINA, DFI_BOOST_PRIMARY));
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
            if (dfi_ability(m, DFI_ABILITY_ROCKHEAD)) {
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
    if (any && dfi_holds(m, DFI_ITEM_LIFEORB)) {
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
    const bool flip_turn = leaving != NULL && leaving->hp != 0u && flag == DFI_SWITCH_FLIP_TURN;
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
    /* [switch], with [from] Parting Shot or Flip Turn when the move made it */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_SWITCH, side * 2u + slot);
    e.id = (uint16_t)reserve;
    if (parting_shot || flip_turn) {
        e.cause = (uint8_t)DUOFORGE_CAUSE_MOVE;
        e.id2 = (uint16_t)(parting_shot ? DFI_MOVE_PARTINGSHOT : DFI_MOVE_FLIPTURN); /* wide-operands-reviewed: < 50 */
    }
    dfi_emit_hp(r, e);
    return dfi_insert_run_switch(r, side, slot, binding.activation_id);
}

/* The entry abilities of the closure: an ability's onStart runs as a
 * SwitchIn handler (Battle.getCallback). */
static bool dfi_has_entry(const dfi_member *m);

/* Grassy Seed (useItem): Defense +1 once, when Grassy Terrain is up. */
static void dfi_grassy_seed(dfi_run *r, uint32_t flat)
{
    static const uint8_t def_up[DFI_STAT_STAGE_COUNT] = {6u, 7u, 6u, 6u, 6u, 6u, 6u};
    const dfi_member *m = dfi_at(r->b, flat);
    if (m != NULL && m->hp != 0u && dfi_holds(m, DFI_ITEM_GRASSYSEED) && r->b->terrain == DFI_TERRAIN_GRASSY) {
        dfi_use_item(r, flat);
        dfi_boost(r, flat, def_up, DFI_POSITIONS,
                  dfi_effect(DUOFORGE_CAUSE_ITEM, 1u + DFI_ITEM_GRASSYSEED, DFI_BOOST_PRIMARY));
    }
}

/* eachEvent('TerrainChange'): every Grassy Seed on the field in
 * eachEvent's order; a seed acts only while Grassy Terrain is up. */
static duoforge_status dfi_terrain_change(dfi_run *r)
{
    uint32_t bearers = 0u;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        bearers |= dfi_holds(dfi_at(r->b, flat), DFI_ITEM_GRASSYSEED) ? 1u << flat : 0u;
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
        dfi_grassy_seed(r, list[i]);
    }
    return DUOFORGE_OK;
}

/* A SwitchIn handler: an entry ability (priority 0) or Grassy Seed's
 * onStart (onSwitchInPriority -1). */
static bool dfi_has_switch_in(const dfi_member *m)
{
    return dfi_has_entry(m) || dfi_holds(m, DFI_ITEM_GRASSYSEED);
}

/* An entry ability: a weather or a terrain setter (the families of
 * decision 0015: Drizzle, Drought, Grassy Surge, Psychic Surge) or Intimidate. */
static bool dfi_has_entry(const dfi_member *m)
{
    return dfi_weather_set_by(m) != DFI_WEATHER_NONE || dfi_terrain_set_by(m) != DFI_TERRAIN_NONE ||
           m->ability == 1u + DFI_ABILITY_INTIMIDATE;
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
    const uint32_t a = m->ability;
    const uint32_t w = dfi_weather_set_by(m);
    const uint32_t terrain = dfi_terrain_set_by(m);
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
            bearers += (((entering >> flat) & 1u) != 0u && m->hp != 0u && dfi_has_switch_in(m)) ? 1u : 0u;
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
    /* The abilities (priority 0) in that order, then the Grassy Seeds
     * (priority -1), then White Herb's onAnySwitchIn of every holder on the
     * field (priority -2, Team C), in the same order: the handlers'
     * fractional speeds follow it (sim/battle.ts:1008-1013). */
    for (uint32_t pass = 0u; pass < 2u; ++pass) {
        for (uint32_t i = 0u; i < n; ++i) {
            const uint32_t flat = list[i];
            const dfi_member *m = dfi_at(b, flat);
            if (((entering >> flat) & 1u) == 0u || m->hp == 0u) {
                continue;
            }
            if (pass == 0u && dfi_has_entry(m)) {
                const duoforge_status st = dfi_entry_ability(r, flat);
                if (st != DUOFORGE_OK) {
                    return st;
                }
            } else if (pass == 1u && dfi_holds(m, DFI_ITEM_GRASSYSEED)) {
                dfi_grassy_seed(r, flat);
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
    duoforge_event forme = dfi_event_make(DUOFORGE_EVENT_FORME, flat);
    forme.id = dfi_pool_formes[m->species_id].mega_forme; /* [detailschange] */
    dfi_emit(r, &forme);
    duoforge_event mega = dfi_event_make(DUOFORGE_EVENT_MEGA, flat);
    mega.id2 = m->item; /* [-mega] the stone, item + 1 */
    dfi_emit(r, &mega);
    if (dfi_has_entry(m)) {
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
#define DFI_RES_WEATHER 1u
#define DFI_RES_TERRAIN_END 2u
#define DFI_RES_BURN 3u
#define DFI_RES_DURATION 4u
#define DFI_RES_GRASSY 5u
#define DFI_RES_FIELD_END 6u /* Trick Room, a side condition: duration only */
#define DFI_RES_LEFTOVERS 7u
#define DFI_RES_POISON 8u
#define DFI_RES_WHITE_HERB 9u
#define DFI_RES_NO_ORDER 0xFFFFFFFFu
/* Trick Room, weather and terrain; three conditions per side; per position
 * (DFI_RES_PER_POSITION) a status (burn or poison), six duration ends
 * (Protect, the stall counter, flinch, a charge, Helping Hand, Follow Me),
 * an item (Leftovers or White Herb) and Grassy Terrain. */
#define DFI_RES_PER_POSITION 9u
#define DFI_RES_MAX (3u + 3u * DUOFORGE_SIDE_COUNT + DFI_RES_PER_POSITION * DFI_POSITIONS)

typedef struct dfi_residual_entry {
    uint32_t kind;
    uint32_t flat;
    uint32_t order;
    uint32_t speed;
    uint32_t sub_order;
    bool callback;
} dfi_residual_entry;

/* comparePriority for residual handlers: 0 a first, 1 tie, 2 b first. */
static uint32_t dfi_residual_compare(const dfi_residual_entry *a, const dfi_residual_entry *b)
{
    if (a->order != b->order) {
        return a->order < b->order ? 0u : 2u;
    }
    if (a->speed != b->speed) {
        return a->speed > b->speed ? 0u : 2u;
    }
    if (a->sub_order != b->sub_order) {
        return a->sub_order < b->sub_order ? 0u : 2u;
    }
    return 1u;
}

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
                                        (sd->tailwind_turns != 0u ? 1u : 0u);
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
                              ((((uint32_t)pos->flags & DFI_VOL_FOLLOW_ME) != 0u) ? 1u : 0u);
        for (uint32_t k = 0u; k < ends; ++k) {
            list[n] = (dfi_residual_entry){DFI_RES_DURATION, flat, DFI_RES_NO_ORDER, speed, 2u, false};
            n += 1u;
        }
        if (dfi_holds(m, DFI_ITEM_LEFTOVERS)) {
            list[n] = (dfi_residual_entry){DFI_RES_LEFTOVERS, flat, 5u, speed, 4u, true};
            n += 1u;
        }
        /* White Herb's onResidual (order 29, an item: sub-order 8; Team C). */
        if (dfi_holds(m, DFI_ITEM_WHITEHERB)) {
            list[n] = (dfi_residual_entry){DFI_RES_WHITE_HERB, flat, 29u, speed, 8u, true};
            n += 1u;
        }
        if (b->terrain == DFI_TERRAIN_GRASSY) {
            list[n] = (dfi_residual_entry){DFI_RES_GRASSY, flat, 5u, speed, 2u, true};
            n += 1u;
        }
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
     * (Reflect 1, Light Screen 2, Tailwind 5). The same kind on both sides
     * ties; the shuffle decides the order of the two end lines when both
     * run out now: only then a draw (decision 0007 section 6). `first`: the
     * side whose line comes first, per kind. */
    uint32_t first[3] = {0u, 0u, 0u};
    for (uint32_t k = 0u; k < 3u; ++k) {
        const uint8_t *t0 = k == 0u ? &b->sides[0].reflect_turns
                            : k == 1u ? &b->sides[0].light_screen_turns
                                      : &b->sides[0].tailwind_turns;
        const uint8_t *t1 = k == 0u ? &b->sides[1].reflect_turns
                            : k == 1u ? &b->sides[1].light_screen_turns
                                      : &b->sides[1].tailwind_turns;
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
                st = dfi_update(r); /* the upkeep: eachEvent('Weather'), then 'Update' */
                if (st != DUOFORGE_OK) {
                    return st;
                }
            }
            continue;
        }
        dfi_member *m = dfi_at(b, e->flat);
        if (m->hp == 0u) {
            continue; /* the holder fainted */
        }
        if (e->kind == DFI_RES_LEFTOVERS) {
            dfi_heal(r, e->flat, (uint32_t)m->hp_max / 16u, DUOFORGE_CAUSE_ITEM, 1u + DFI_ITEM_LEFTOVERS,
                     DUOFORGE_NO_POSITION); /* heal(baseMaxhp / 16) */
            continue;
        }
        if (e->kind == DFI_RES_GRASSY) {
            /* heal(baseMaxhp / 16): at least 1, not above the maximum, not
             * for a Pokemon that is not grounded or at full HP. */
            if (dfi_grounded(m) && m->hp < m->hp_max && !dfi_heal_blocked(b, e->flat)) {
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
    }
    /* The duration handlers in their order: the side conditions (26), Trick
     * Room (27, sub-order 1), the terrain (27, 7); each that runs out shows
     * its end line (and the terrain's end runs TerrainChange). Protect,
     * flinch and the stall counter end without a line. */
    static const uint8_t side_kind[3] = {DUOFORGE_SIDE_REFLECT, DUOFORGE_SIDE_LIGHT_SCREEN, DUOFORGE_SIDE_TAILWIND};
    for (uint32_t k = 0u; k < 3u; ++k) {
        for (uint32_t j = 0u; j < DUOFORGE_SIDE_COUNT; ++j) {
            const uint32_t s = j ^ first[k];
            dfi_side *sd = &b->sides[s];
            uint8_t *turns = k == 0u ? &sd->reflect_turns : k == 1u ? &sd->light_screen_turns : &sd->tailwind_turns;
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
