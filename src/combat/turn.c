#include "combat/turn.h"

#include "core/arith.h"
#include "core/modifier.h"
#include "data/closure_tables.h"
#include "data/support_manifest.h"
#include "state/closure_member.h"
#include "state/context_internal.h"
#include "state/identity.h"
#include "state/knowledge.h"

/* Action orders (sim/battle-queue.ts:174-195). */
#define DFI_ORDER_SWITCH_IN 3u    /* instaswitch: a replacement */
#define DFI_ORDER_RUN_SWITCH 101u /* the entry of a Pokemon that came in */
#define DFI_ORDER_SWITCH 103u     /* a voluntary switch */
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
    uint32_t last_fainted; /* flat position of the last processed faint */
    bool ended;
} dfi_run;

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

static const dfi_forme_data *dfi_forme_of(const dfi_member *m)
{
    const dfi_forme_data *base = &dfi_closure_formes[m->species_id];
    return m->is_mega != 0u ? &dfi_closure_formes[base->mega_forme] : base;
}

static bool dfi_has_type(const dfi_member *m, uint32_t type)
{
    const dfi_forme_data *f = dfi_forme_of(m);
    return f->types[0] == type || f->types[1] == type;
}

/* A stat (0 atk .. 4 spe) after its stage (getStat without modifiers). */
static duoforge_status dfi_staged_stat(const dfi_member *m, const dfi_active_slot *pos, uint32_t index,
                                       uint32_t *out)
{
    return dfi_stage_stat(m->stats[index], pos->stages[index], out) ? DUOFORGE_OK : DUOFORGE_E_INVARIANT;
}

/* getActionSpeed of the Champions mod (data/mods/champions/scripts.ts:46-55):
 * the staged Speed, capped, negated under Trick Room. */
static duoforge_status dfi_speed_key(const struct duoforge_battle *b, const dfi_member *m,
                                     const dfi_active_slot *pos, uint32_t *out)
{
    uint32_t spe = 0u;
    const duoforge_status st = dfi_staged_stat(m, pos, DFI_STAT_SPE - 1u, &spe);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (spe > DFI_SPEED_CAP) {
        spe = DFI_SPEED_CAP;
    }
    *out = b->trick_room_turns != 0u ? DFI_SPEED_BIAS - spe : DFI_SPEED_BIAS + spe;
    return DUOFORGE_OK;
}

static uint32_t dfi_move_of(const dfi_member *m, uint32_t move_slot)
{
    return move_slot == DUOFORGE_MOVE_SLOT_STRUGGLE ? DFI_MOVE_STRUGGLE : m->moves[move_slot].move_id;
}

/* ---------------------------------------------------------------- queue */

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
    } else {
        return DUOFORGE_E_UNSUPPORTED; /* Mega Evolution comes later */
    }
    const uint32_t flat = (uint32_t)q->side * 2u + (uint32_t)q->slot;
    const dfi_member *m = dfi_at(r->b, flat);
    if (m == NULL) {
        return DUOFORGE_E_INVARIANT;
    }
    uint32_t speed = 0u;
    const duoforge_status st = dfi_speed_key(r->b, m, dfi_pos(r->b, flat), &speed);
    if (st != DUOFORGE_OK) {
        return st;
    }
    out->order = order;
    out->priority = q->kind == DFI_Q_MOVE ? dfi_closure_moves[dfi_move_of(m, q->move_slot)].priority
                                          : DFI_PRIORITY_BIAS;
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

static void dfi_swap(struct duoforge_battle *b, dfi_key *keys, uint32_t i, uint32_t j)
{
    const dfi_queue_record q = b->queue[i];
    b->queue[i] = b->queue[j];
    b->queue[j] = q;
    const dfi_key k = keys[i];
    keys[i] = keys[j];
    keys[j] = k;
}

/* Battle.speedSort over the whole queue: a selection sort that gathers the
 * next tied group in list order and shuffles it (PRNG.shuffle,
 * sim/prng.ts:150-157), each draw random(i, n) relative to the group. */
static duoforge_status dfi_sort_queue(dfi_run *r)
{
    struct duoforge_battle *b = r->b;
    const uint32_t n = b->queue_len;
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
    if (cls == DUOFORGE_TARGET_CLASS_SELF) {
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
    return DUOFORGE_E_UNSUPPORTED; /* ally, side and field classes come later */
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
    uint32_t attack = 0u;
    uint32_t defense = 0u;
    uint32_t damage = 0u;
    if (!dfi_stage_stat(a->stats[atk_index], atk_stage, &attack) ||
        !dfi_stage_stat(d->stats[def_index], def_stage, &defense) ||
        !dfi_base_damage(DFI_LEVEL, md->base_power, attack, defense, &damage)) {
        return DUOFORGE_E_INVARIANT;
    }
    damage += 2u;
    if (spread) {
        damage = dfi_modify(damage, 3072u); /* 0.75 */
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
    if (move_type < DFI_TYPE_COUNT) {
        damage = dfi_modify(damage, dfi_has_type(a, move_type) ? 6144u : 4096u); /* STAB 1.5 */
        if (!dfi_type_damage(damage, dfi_type_mod(d, move_type), &damage)) {
            return DUOFORGE_E_INVARIANT;
        }
    }
    *out = dfi_final_damage(damage);
    return DUOFORGE_OK;
}

/* Pokemon.damage: HP never below 0; reaching 0 queues the faint. */
static duoforge_status dfi_deal(dfi_run *r, uint32_t flat, uint32_t amount)
{
    dfi_member *m = dfi_at(r->b, flat);
    const uint32_t hp = m->hp;
    if (hp == 0u) {
        return DUOFORGE_OK;
    }
    m->hp = (uint16_t)(hp > amount ? hp - amount : 0u); /* wide-operands-reviewed: <= hp */
    dfi_knowledge_refresh_active(r->b);
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

/* faintMessages and checkWin (sim/battle.ts:2535-2590, 404-415): the faints
 * of the action in order, then the win rule. When every side is out, the
 * side whose Pokemon fainted last wins (generation 5 and later). */
static void dfi_process_faints(dfi_run *r)
{
    struct duoforge_battle *b = r->b;
    for (uint32_t i = 0u; i < r->faint_count; ++i) {
        const uint32_t flat = r->faint_queue[i];
        dfi_clear_volatile(dfi_pos(b, flat));
        r->last_fainted = flat;
    }
    const bool any = r->faint_count != 0u;
    r->faint_count = 0u;
    if (!any) {
        return;
    }
    const uint32_t left0 = dfi_left(b, 0u);
    const uint32_t left1 = dfi_left(b, 1u);
    uint32_t result = DFI_RESULT_NONE;
    if (left0 == 0u && left1 == 0u) {
        result = r->last_fainted / 2u == 0u ? DFI_RESULT_SIDE0 : DFI_RESULT_SIDE1;
    } else if (left1 == 0u) {
        result = DFI_RESULT_SIDE0;
    } else if (left0 == 0u) {
        result = DFI_RESULT_SIDE1;
    }
    if (result != DFI_RESULT_NONE) {
        b->result = (uint8_t)result;
        r->ended = true;
    }
}

/* ---------------------------------------------------------------- moves */

/* Protect (data/moves.ts protect, data/conditions.ts stall): fails without a
 * draw when nobody acts after the user; with a stall counter it succeeds on
 * random(counter) == 0 (STALL) and otherwise loses the counter. */
static duoforge_status dfi_run_protect(dfi_run *r, uint32_t user)
{
    dfi_active_slot *pos = dfi_pos(r->b, user);
    if (!dfi_will_act(r->b)) {
        return DUOFORGE_OK; /* fails; the stall counter stays */
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
            return DUOFORGE_OK;
        }
    }
    pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_PROTECT); /* wide-operands-reviewed: <= 7 */
    pos->stall_level = (uint8_t)(level < DFI_STALL_LEVEL_MAX ? level + 1u : level); /* wide-operands-reviewed */
    pos->stall_turns = (uint8_t)DFI_STALL_DURATION;
    return DUOFORGE_OK;
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
    *ran = true;
    if (pos->move_actions < UINT8_MAX) {
        pos->move_actions = (uint8_t)((uint32_t)pos->move_actions + 1u); /* wide-operands-reviewed */
    }
    const uint32_t move_id = dfi_move_of(m, q->move_slot);
    const dfi_move_data *md = &dfi_closure_moves[move_id];
    if (move_id != DFI_MOVE_STRUGGLE && dfi_support.moves[move_id] == 0u) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    /* getTarget and getMoveTargets (the spread classes need no draw). */
    uint32_t targets[DFI_POSITIONS] = {0};
    uint32_t count = 0u;
    duoforge_status st = dfi_move_targets(r, user, md->target_class, q->target, targets, &count);
    if (st != DUOFORGE_OK) {
        return st;
    }
    /* deductPP and what the opponent sees. */
    if (q->move_slot < DUOFORGE_MAX_MOVE_SLOTS) {
        dfi_move_slot *slot = &m->moves[q->move_slot];
        if (slot->pp == 0u) {
            return DUOFORGE_OK; /* "cant nopp"; the domain never offers it */
        }
        slot->pp = (uint8_t)((uint32_t)slot->pp - 1u); /* wide-operands-reviewed: pp > 0 */
        dfi_knowledge *k = &b->sides[1u - side].knowledge[pos->occupant];
        if (k->moves_used[q->move_slot] < UINT8_MAX) {
            k->moves_used[q->move_slot] = (uint8_t)((uint32_t)k->moves_used[q->move_slot] + 1u); /* wide-operands-reviewed */
        }
    }
    if (count == 0u) {
        return DUOFORGE_OK; /* no target: the move fails */
    }
    if (md->special == DFI_SPECIAL_PROTECT) {
        return dfi_run_protect(r, user);
    }
    if (md->category == DFI_CATEGORY_STATUS) {
        if (md->boost_role != DFI_BOOST_ROLE_PRIMARY_SELF || md->target_class != DUOFORGE_TARGET_CLASS_SELF) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        dfi_apply_boosts(pos, md->boosts);
        return DUOFORGE_OK;
    }
    if (md->special != DFI_SPECIAL_NONE && md->special != DFI_SPECIAL_STRUGGLE) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    /* Struggle is typeless (its onModifyMove). */
    const uint32_t move_type = md->special == DFI_SPECIAL_STRUGGLE ? DFI_CLOSURE_NONE : md->type;
    const bool spread = count > 1u;
    /* Hit steps: Protect (TryHit), type immunity, accuracy per target. */
    bool hit[DFI_POSITIONS] = {false, false, false, false};
    for (uint32_t i = 0u; i < count; ++i) {
        const uint32_t t = targets[i];
        const dfi_active_slot *tp = dfi_pos(b, t);
        hit[i] = !((((uint32_t)tp->flags & DFI_VOL_PROTECT) != 0u) && ((md->flags & DFI_MOVE_FLAG_PROTECT) != 0u));
    }
    for (uint32_t i = 0u; i < count; ++i) {
        if (hit[i] && dfi_type_immune(dfi_at(b, targets[i]), move_type)) {
            hit[i] = false;
        }
    }
    if (md->accuracy != 0u) {
        for (uint32_t i = 0u; i < count; ++i) {
            if (!hit[i]) {
                continue;
            }
            /* The user's accuracy stage minus the target's evasion, clamped. */
            const uint32_t acc = pos->stages[DFI_STAGE_ACCURACY];
            const uint32_t eva = dfi_pos(b, targets[i])->stages[DFI_STAGE_EVASION];
            uint32_t combined = acc + 12u - eva; /* 12 means 0 */
            combined = combined < 6u ? 6u : (combined > 18u ? 18u : combined);
            uint32_t accuracy = 0u;
            if (!dfi_stage_accuracy(md->accuracy, combined - 6u, &accuracy)) {
                return DUOFORGE_E_INVARIANT;
            }
            st = dfi_draw_chance(r->draws, DFI_SITE_ACCURACY, accuracy, 100u, &hit[i]);
            if (st != DUOFORGE_OK) {
                return st;
            }
        }
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
    for (uint32_t i = 0u; i < count; ++i) {
        if (hit[i]) {
            st = dfi_deal(r, targets[i], damage[i]);
            if (st != DUOFORGE_OK) {
                return st;
            }
        }
    }
    /* secondaries: one SECONDARY draw per hit target, even at 100. */
    if (md->sec_chance != 0u) {
        if (md->sec_kind != DFI_SECONDARY_BOOST) {
            return DUOFORGE_E_UNSUPPORTED; /* statuses and flinch: step 4 */
        }
        for (uint32_t i = 0u; i < count; ++i) {
            if (!hit[i]) {
                continue;
            }
            uint32_t roll = 0u;
            st = dfi_draw(r->draws, DFI_SITE_SECONDARY, 0u, 100u, &roll);
            if (st != DUOFORGE_OK) {
                return st;
            }
            if (roll < md->sec_chance) {
                dfi_apply_boosts(dfi_pos(b, targets[i]), md->boosts);
            }
        }
    } else if (md->boost_role != DFI_BOOST_ROLE_NONE || md->recoil[1] != 0u || md->drain[1] != 0u) {
        return DUOFORGE_E_UNSUPPORTED; /* self-drops, recoil and drain: step 9 */
    }
    /* Struggle's recoil: round(maxHP / 4), at least 1 (applyRecoilDamage). */
    if ((md->flags & DFI_MOVE_FLAG_STRUGGLE_RECOIL) != 0u) {
        bool any = false;
        for (uint32_t i = 0u; i < count; ++i) {
            any = any || hit[i];
        }
        if (any) {
            const uint32_t hp_max = m->hp_max;
            uint32_t recoil = (hp_max + 2u) / 4u; /* Math.round(hp_max / 4) */
            if (recoil < 1u) {
                recoil = 1u;
            }
            st = dfi_deal(r, user, recoil);
            if (st != DUOFORGE_OK) {
                return st;
            }
        }
    }
    return DUOFORGE_OK;
}

/* ---------------------------------------------------------------- switches */

/* insertChoice (sim/battle-queue.ts:369-401) of the entry action of the
 * Pokemon that came in: before the first action it sorts ahead of. Among
 * tied entries the reference draws a position; that changes nothing while
 * no Pokemon has an entry effect, and entry effects are not implemented
 * (abilities and items stay behind the manifest). */
static duoforge_status dfi_insert_run_switch(dfi_run *r, uint32_t side, uint32_t slot, uint32_t activation)
{
    struct duoforge_battle *b = r->b;
    if (b->queue_len >= DFI_QUEUE_CAPACITY) {
        return DUOFORGE_E_INVARIANT;
    }
    const dfi_queue_record rec = {activation, (uint8_t)DFI_Q_RUN_SWITCH, (uint8_t)side, (uint8_t)slot, 0u, 0u, 0u};
    dfi_key key;
    duoforge_status st = dfi_key_of(r, &rec, &key);
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
    if (sd->members[reserve].ability != 0u || sd->members[reserve].item != 0u) {
        return DUOFORGE_E_UNSUPPORTED; /* entry effects: steps 5 and 8 */
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
    return dfi_insert_run_switch(r, side, slot, binding.activation_id);
}

/* ---------------------------------------------------------------- turn */

/* fieldEvent('Residual') for the turn core: Protect ends, the stall counter
 * counts down its duration. */
static void dfi_residual(struct duoforge_battle *b)
{
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        dfi_active_slot *pos = dfi_pos(b, flat);
        if (pos->occupant == DFI_OCCUPANT_NONE) {
            continue;
        }
        pos->flags = (uint8_t)((uint32_t)pos->flags & ~DFI_VOL_PROTECT); /* wide-operands-reviewed */
        if (pos->stall_turns > 0u) {
            pos->stall_turns = (uint8_t)((uint32_t)pos->stall_turns - 1u); /* wide-operands-reviewed */
            if (pos->stall_turns == 0u) {
                pos->stall_level = 0u;
            }
        }
    }
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

/* The battle is over: TERMINAL with its result, nobody requested. */
static duoforge_status dfi_terminal(struct duoforge_battle *b)
{
    const duoforge_status st = dfi_next_epoch(b);
    if (st != DUOFORGE_OK) {
        return st;
    }
    dfi_clear_requests(b);
    b->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_TERMINAL;
    b->request_mask = 0u;
    dfi_knowledge_refresh_active(b);
    return DUOFORGE_OK;
}

static duoforge_status dfi_end_turn(struct duoforge_battle *b)
{
    uint32_t turn = 0u;
    uint32_t epoch = 0u;
    if (!dfi_add_u32(b->turn, 1u, &turn) || turn > UINT16_MAX || !dfi_add_u32(b->request_epoch, 1u, &epoch) ||
        epoch == UINT32_MAX) {
        return DUOFORGE_E_EXHAUSTED;
    }
    b->turn = (uint16_t)turn;
    b->request_epoch = epoch;
    b->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_TURN;
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
    dfi_knowledge_refresh_active(b);
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

/* The queue is empty after the residual action: checkFainted and the
 * switch request (sim/battle.ts:2524-2530, 2876-2915). A side with a
 * fainted Pokemon on the field and a reserve is asked to replace it;
 * otherwise the next turn starts. */
static duoforge_status dfi_finish_turn(struct duoforge_battle *b)
{
    uint32_t mask = 0u;
    uint32_t fainted[DUOFORGE_SIDE_COUNT] = {0u, 0u};
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const uint32_t occupant = b->sides[s].positions[p].occupant;
            if (occupant < DUOFORGE_MAX_ROSTER && b->sides[s].members[occupant].hp == 0u) {
                fainted[s] |= 1u << p;
            }
        }
        if (fainted[s] != 0u && dfi_has_reserve(b, s)) {
            mask |= 1u << s;
        }
    }
    if (mask == 0u) {
        return dfi_end_turn(b);
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
    dfi_knowledge_refresh_active(b);
    return DUOFORGE_OK;
}

duoforge_status dfi_turn_run(const duoforge_context *ctx, struct duoforge_battle *b,
                             const duoforge_side_choice responses[DUOFORGE_SIDE_COUNT], dfi_draws *draws)
{
    const bool replacement = b->boundary_kind == DUOFORGE_BOUNDARY_REPLACEMENT;
    if (!dfi_context_is_closure(ctx) || (b->boundary_kind != DUOFORGE_BOUNDARY_TURN && !replacement)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    if (!dfi_closure_battle_supported(&dfi_support, b) || (replacement && dfi_support.switching == 0u)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    dfi_run r = {ctx, b, draws, {0u, 0u, 0u, 0u}, 0u, 0u, false};
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
            if (c.kind == DFI_SLOT_NONE || c.kind == DFI_SLOT_PASS) {
                continue;
            }
            uint32_t kind = DFI_Q_MOVE;
            if (c.kind == DFI_SLOT_SWITCH) {
                if (dfi_support.switching == 0u) {
                    return DUOFORGE_E_UNSUPPORTED;
                }
                kind = replacement ? DFI_Q_SWITCH_IN : DFI_Q_SWITCH;
            } else if (c.kind != DFI_SLOT_MOVE || c.mega != 0u || replacement) {
                return DUOFORGE_E_UNSUPPORTED; /* Mega Evolution comes later */
            }
            const bool move = kind == DFI_Q_MOVE;
            b->queue[b->queue_len] = (dfi_queue_record){
                kind == DFI_Q_SWITCH_IN ? 0u : b->sides[s].positions[slot].activation_id, (uint8_t)kind, (uint8_t)s,
                (uint8_t)slot, move ? c.move_slot : 0u, move ? c.target : 0u, move ? 0u : c.reserve};
            b->queue_len = (uint8_t)((uint32_t)b->queue_len + 1u); /* wide-operands-reviewed: <= 4 */
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
        st = dfi_sort_queue(&r);
    }
    if (st == DUOFORGE_OK && !replacement && b->queue[0].kind == DFI_Q_MOVE) {
        st = dfi_sort_queue(&r);
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
        } else if (q.kind == DFI_Q_SWITCH || q.kind == DFI_Q_SWITCH_IN) {
            st = dfi_run_switch(&r, &q);
            if (st != DUOFORGE_OK) {
                return st;
            }
        } else if (q.kind == DFI_Q_RUN_SWITCH) {
            /* runSwitch takes every entry queued right behind it; no entry
             * effect exists yet. */
            while (b->queue_len > 0u && b->queue[0].kind == DFI_Q_RUN_SWITCH) {
                dfi_queue_pop(b, &q);
            }
        } else if (q.kind == DFI_Q_RESIDUAL) {
            dfi_residual(b);
        } else {
            return DUOFORGE_E_UNSUPPORTED;
        }
        /* The epilogue: faints and the win rule; before a further
         * replacement nothing else; before a move action, speeds and
         * priorities are recomputed and the rest of the queue is sorted. */
        dfi_process_faints(&r);
        if (r.ended) {
            return dfi_terminal(b);
        }
        if (b->queue_len > 0u && b->queue[0].kind == DFI_Q_SWITCH_IN) {
            continue;
        }
        if (b->queue_len > 0u && b->queue[0].kind == DFI_Q_MOVE) {
            st = dfi_sort_queue(&r);
            if (st != DUOFORGE_OK) {
                return st;
            }
        }
    }
    return replacement ? dfi_end_turn(b) : dfi_finish_turn(b);
}
