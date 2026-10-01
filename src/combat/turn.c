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
    uint32_t last_fainted; /* flat position of the last processed faint */
    bool ended;
    /* pokemon.speed: the speed key of each position at the reference's last
     * updateSpeed while its Pokemon stood (a fainted Pokemon keeps it). */
    uint32_t speed_seen[DFI_POSITIONS];
    /* residualPokemon: each position's HP before the residual events. */
    uint32_t residual_hp[DFI_POSITIONS];
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

static duoforge_status dfi_staged_stat(const dfi_member *m, const dfi_active_slot *pos, uint32_t index,
                                       uint32_t *out)
{
    return dfi_stage_stat(m->stats[index], pos->stages[index], out) ? DUOFORGE_OK : DUOFORGE_E_INVARIANT;
}

/* getActionSpeed of the Champions mod (data/mods/champions/scripts.ts:46-55):
 * the staged Speed, doubled by Tailwind (chainModify(2)), then halved by
 * paralysis (its onModifySpe runs last: finalModify, then floor of 50 of
 * 100), capped, negated under Trick Room. */
static duoforge_status dfi_speed_key(const struct duoforge_battle *b, uint32_t side, const dfi_member *m,
                                     const dfi_active_slot *pos, uint32_t *out)
{
    uint32_t spe = 0u;
    const duoforge_status st = dfi_staged_stat(m, pos, DFI_STAT_SPE - 1u, &spe);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (b->sides[side].tailwind_turns != 0u) {
        spe *= 2u; /* modify(spe, 2) is exact; spe <= 4 * 65535 */
    }
    if (m->status == DFI_STATUS_PAR) {
        spe = spe * 50u / 100u; /* spe <= 8 * 65535 */
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
/* ModifyPriority: Prankster gives status moves +1, Grassy Glide gets +1
 * in Grassy Terrain for a grounded user. Biased like the move table. */
static uint32_t dfi_move_priority(const struct duoforge_battle *b, const dfi_member *m, const dfi_move_data *md)
{
    uint32_t priority = md->priority;
    if (dfi_ability(m, DFI_ABILITY_PRANKSTER) && md->category == DFI_CATEGORY_STATUS) {
        priority += 1u;
    }
    if (md->special == DFI_SPECIAL_GRASSY_GLIDE && b->terrain == DFI_TERRAIN_GRASSY &&
        !dfi_has_type(m, DFI_TYPE_FLYING)) {
        priority += 1u;
    }
    return priority;
}

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
    if (q->kind == DFI_Q_MOVE) {
        out->priority = dfi_move_priority(r->b, m, &dfi_closure_moves[dfi_move_of(m, q->move_slot)]);
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

/* Battle.speedSort over the whole queue: a selection sort that gathers the
 * next tied group in list order and shuffles it (PRNG.shuffle,
 * sim/prng.ts:150-157), each draw random(i, n) relative to the group. */
/* speedSort of the first n queued actions (all of them, or the new
 * actions of a PIVOT answer, which commitChoices sorts before it appends
 * the stored rest of the turn). */
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

/* Battle.boost with getCappedBoost: each stage moves by the (biased) amount
 * and stops at -6 or +6. */
/* Battle.boost (sim/battle.ts): nothing for a fainted Pokemon or when its
 * foes have no Pokemon left; each stat changes by its capped amount, and a
 * stat that changed runs AfterEachBoost: Competitive raises Special Attack
 * by 2 when a foe lowered a stat. `source` is the flat position of the
 * Pokemon that caused it, or DFI_POSITIONS for the holder itself. */
static uint32_t dfi_left(const struct duoforge_battle *b, uint32_t side);
static void dfi_apply_boosts(dfi_active_slot *pos, const uint8_t *boosts);

static bool dfi_boost(dfi_run *r, uint32_t flat, const uint8_t *boosts, uint32_t source)
{
    struct duoforge_battle *b = r->b;
    const dfi_member *m = dfi_at(b, flat);
    bool changed = false;
    if (m == NULL || m->hp == 0u) {
        return false;
    }
    /* foePokemonLeft counts a Pokemon until its faint is processed. */
    uint32_t foes_left = dfi_left(b, 1u - flat / 2u);
    for (uint32_t i = 0u; i < r->faint_count; ++i) {
        foes_left += r->faint_queue[i] / 2u != flat / 2u ? 1u : 0u;
    }
    if (foes_left == 0u) {
        return false;
    }
    dfi_active_slot *pos = dfi_pos(b, flat);
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        const uint32_t before = pos->stages[i];
        uint8_t one[DFI_STAT_STAGE_COUNT] = {6u, 6u, 6u, 6u, 6u, 6u, 6u};
        /* Contrary (ChangeBoost) reverses every change. */
        const uint32_t reversed = 12u - (uint32_t)boosts[i]; /* boosts are biased by 6, 0..12 */
        one[i] = dfi_ability(m, DFI_ABILITY_CONTRARY) ? (uint8_t)reversed : boosts[i];
        dfi_apply_boosts(pos, one);
        const bool lowered = pos->stages[i] < before;
        changed = changed || pos->stages[i] != before;
        if (lowered && dfi_ability(m, DFI_ABILITY_COMPETITIVE) && source < DFI_POSITIONS && source / 2u != flat / 2u) {
            static const uint8_t raise[DFI_STAT_STAGE_COUNT] = {6u, 6u, 8u, 6u, 6u, 6u, 6u}; /* SpA +2 */
            dfi_apply_boosts(pos, raise);
        }
    }
    return changed;
}

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
    }
    uint32_t bp_chain = 4096u;
    bool ok = true;
    if (dfi_ability(a, DFI_ABILITY_TOUGHCLAWS) && (md->flags & DFI_MOVE_FLAG_CONTACT) != 0u) {
        ok = dfi_chain_modify(bp_chain, 5325u, &bp_chain); /* onBasePowerPriority 21: first */
    }
    if ((move_type == DFI_TYPE_WATER && dfi_holds(a, DFI_ITEM_MYSTICWATER)) ||
        (move_type == DFI_TYPE_GRASS && dfi_holds(a, DFI_ITEM_MIRACLESEED))) {
        ok = ok && dfi_chain_modify(bp_chain, 4915u, &bp_chain);
    }
    if (move_type == DFI_TYPE_GRASS && r->b->terrain == DFI_TERRAIN_GRASSY && !dfi_has_type(a, DFI_TYPE_FLYING)) {
        ok = ok && dfi_chain_modify(bp_chain, 5325u, &bp_chain);
    }
    const uint32_t base_power = bp_chain == 4096u ? power : dfi_modify(power, bp_chain);
    /* ModifyAtk / ModifySpA, one chained modifier: Blaze for Fire moves at a
     * third of the HP or less, Flash Fire's boost for Fire moves once it
     * took one; 1.5 each. */
    uint32_t atk_chain = 4096u;
    if (move_type == DFI_TYPE_FIRE && dfi_ability(a, DFI_ABILITY_BLAZE) && (uint32_t)a->hp * 3u <= a->hp_max) {
        ok = ok && dfi_chain_modify(atk_chain, 6144u, &atk_chain);
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
    if (move_type < DFI_TYPE_COUNT) {
        damage = dfi_modify(damage, dfi_has_type(a, move_type) ? 6144u : 4096u); /* STAB 1.5 */
        if (!dfi_type_damage(damage, dfi_type_mod(d, move_type), &damage)) {
            return DUOFORGE_E_INVARIANT;
        }
    }
    /* A burned attacker's physical moves, Struggle included, do half
     * (modifyDamage, sim/battle-actions.ts:1816-1820). */
    if (physical && a->status == DFI_STATUS_BRN) {
        damage = dfi_modify(damage, 2048u);
    }
    /* ModifyDamage: Reflect (physical) and Light Screen (special) on the
     * target's side, not against a critical hit and not on the user itself,
     * 2732/4096 in doubles. */
    const dfi_side *ds = &r->b->sides[target / 2u];
    uint32_t chain = 4096u;
    if (dfi_holds(a, DFI_ITEM_LIFEORB) && !dfi_chain_modify(chain, 5324u, &chain)) {
        return DUOFORGE_E_INVARIANT;
    }
    if (!crit && target != user && ((physical && ds->reflect_turns != 0u) ||
                                    (md->category == DFI_CATEGORY_SPECIAL && ds->light_screen_turns != 0u)) &&
        !dfi_chain_modify(chain, 2732u, &chain)) {
        return DUOFORGE_E_INVARIANT;
    }
    /* Life Orb (5324/4096) and a screen chain into one modifier; two
     * modifiers chained from 4096 give the same result in either order. */
    if (chain != 4096u) {
        damage = dfi_modify(damage, chain);
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

/* trySetStatus and setStatus (sim/pokemon.ts): only a standing Pokemon
 * without a status takes one; Fire cannot be burned, Electric cannot be
 * paralyzed, Ice and anything under sun cannot be frozen. Sleep lasts
 * sample([2, 3, 3]) attempts, freeze at most 3 (the Champions conditions,
 * data/mods/champions/conditions.ts). */
static duoforge_status dfi_try_status(dfi_run *r, uint32_t flat, uint32_t status)
{
    static const uint8_t sleep_turns[3] = {2u, 3u, 3u};
    dfi_member *m = dfi_at(r->b, flat);
    if (m == NULL || m->hp == 0u || m->status != DFI_STATUS_NONE) {
        return DUOFORGE_OK;
    }
    if ((status == DFI_STATUS_BRN && dfi_has_type(m, DFI_TYPE_FIRE)) ||
        (status == DFI_STATUS_PAR && dfi_has_type(m, DFI_TYPE_ELECTRIC)) ||
        (status == DFI_STATUS_FRZ && (dfi_has_type(m, DFI_TYPE_ICE) || r->b->weather == DFI_WEATHER_SUN))) {
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
    m->status = (uint8_t)status;          /* <= DFI_STATUS_SLP */
    m->status_counter = (uint8_t)counter; /* <= 3 */
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

static void dfi_emergency_exit(struct duoforge_battle *b, uint32_t flat, uint32_t hp_before)
{
    if (dfi_exits(b, flat, hp_before)) {
        dfi_pos(b, flat)->switch_flag = (uint8_t)DFI_SWITCH_EMERGENCY_EXIT;
    }
}

/* useItem / eatItem: the item is gone and the opponent saw it go. */
static void dfi_use_item(struct duoforge_battle *b, uint32_t flat)
{
    const uint32_t side = flat / 2u;
    const uint32_t occupant = dfi_pos(b, flat)->occupant;
    b->sides[side].members[occupant].item_consumed = 1u;
    dfi_knowledge *k = &b->sides[1u - side].knowledge[occupant];
    k->revealed = (uint8_t)((uint32_t)k->revealed | DFI_REVEALED_ITEM_CONSUMED); /* wide-operands-reviewed */
}

/* heal(): at least 1, nothing at full HP, not above the maximum. */
static void dfi_heal(struct duoforge_battle *b, uint32_t flat, uint32_t amount)
{
    dfi_member *m = dfi_at(b, flat);
    if (m == NULL || m->hp == 0u || m->hp >= m->hp_max) {
        return;
    }
    const uint32_t hp = (uint32_t)m->hp + (amount == 0u ? 1u : amount);
    m->hp = (uint16_t)(hp > m->hp_max ? m->hp_max : hp); /* wide-operands-reviewed: <= hp_max */
    dfi_knowledge_refresh_active(b);
}

/* eachEvent('Update'): Sitrus Berry eats at half HP or less and heals a
 * quarter. Each holder acts only on itself, so the order of the reference's
 * speed sort (and its tie draws) changes nothing. */
static void dfi_update(struct duoforge_battle *b)
{
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        const dfi_member *m = dfi_at(b, flat);
        if (m != NULL && m->hp != 0u && dfi_holds(m, DFI_ITEM_SITRUSBERRY) && (uint32_t)m->hp * 2u <= m->hp_max) {
            dfi_use_item(b, flat);
            dfi_heal(b, flat, (uint32_t)m->hp_max / 4u);
        }
    }
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
        /* clearVolatile ends with setSpecies, which sets pokemon.speed to the
         * raw Speed stat (sim/pokemon.ts:1418); a fainted Pokemon is not
         * updated again. */
        r->speed_seen[flat] = dfi_raw_speed_key(dfi_at(b, flat));
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

/* runEvent('BeforeMove') in handler priority order: sleep and freeze (10),
 * flinch (8), confusion (3), paralysis (1); the first that stops the move
 * ends the event (data/conditions.ts, data/mods/champions/conditions.ts). */
static duoforge_status dfi_before_move(dfi_run *r, uint32_t user, bool *can)
{
    dfi_member *m = dfi_at(r->b, user);
    dfi_active_slot *pos = dfi_pos(r->b, user);
    duoforge_status st = DUOFORGE_OK;
    *can = false;
    if (m->status == DFI_STATUS_SLP || m->status == DFI_STATUS_FRZ) {
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
            return DUOFORGE_OK;
        }
        m->status = (uint8_t)DFI_STATUS_NONE;
        m->status_counter = 0u;
    }
    if (((uint32_t)pos->flags & DFI_VOL_FLINCH) != 0u) {
        return DUOFORGE_OK;
    }
    if (pos->confusion_turns != 0u) {
        pos->confusion_turns = (uint8_t)((uint32_t)pos->confusion_turns - 1u); /* wide-operands-reviewed */
        if (pos->confusion_turns != 0u) {
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
                return dfi_deal(r, user, damage);
            }
        }
    }
    if (m->status == DFI_STATUS_PAR) {
        bool full = false;
        st = dfi_draw_chance(r->draws, DFI_SITE_FULL_PARALYSIS, 1u, 8u, &full);
        if (st != DUOFORGE_OK || full) {
            return st;
        }
    }
    *can = true;
    return DUOFORGE_OK;
}

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
    /* getTarget and getMoveTargets (the spread classes need no draw): the
     * reference picks a random target in runMove, before BeforeMove, so the
     * draw happens even when the Pokemon then cannot move. */
    uint32_t targets[DFI_POSITIONS] = {0};
    uint32_t count = 0u;
    duoforge_status st = dfi_move_targets(r, user, md->target_class, q->target, targets, &count);
    if (st != DUOFORGE_OK) {
        return st;
    }
    /* BeforeMove: a Pokemon that cannot move uses no PP and shows nothing;
     * on the locked turn of a two-turn move its charge ends (twoturnmove's
     * onMoveAborted). */
    const bool locked = pos->charge_turns != 0u;
    bool can = false;
    st = dfi_before_move(r, user, &can);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (!can) {
        if (locked) {
            pos->charge_turns = 0u;
            pos->locked_move = 0u;
            pos->locked_target = 0u;
        }
        return DUOFORGE_OK;
    }
    /* deductPP and what the opponent sees; a locked move uses none. */
    if (q->move_slot < DUOFORGE_MAX_MOVE_SLOTS && !locked) {
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
    /* getMoveTargets: an Electric single-target move goes to a standing
     * Lightning Rod holder the user may target (onAnyRedirectTarget). */
    if (md->type == DFI_TYPE_ELECTRIC && count == 1u &&
        (md->target_class == DUOFORGE_TARGET_CLASS_NORMAL || md->target_class == DUOFORGE_TARGET_CLASS_ANY ||
         md->target_class == DUOFORGE_TARGET_CLASS_ADJACENT_FOE || md->target_class == DFI_TARGET_CLASS_RANDOM_NORMAL)) {
        for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
            const dfi_member *holder = dfi_at(b, flat);
            if (flat != user && holder != NULL && holder->hp != 0u && dfi_ability(holder, DFI_ABILITY_LIGHTNINGROD)) {
                targets[0] = flat;
                break;
            }
        }
    }
    /* Electro Shot's onTryMove (a singleEvent before the TryMove event):
     * on the charge turn Special Attack +1, then in rain the attack goes on,
     * otherwise twoturnmove locks the move and the chosen target for the
     * next turn (duration 2). On the locked turn the attack goes on. */
    if (md->special == DFI_SPECIAL_ELECTRO_SHOT && !locked) {
        static const uint8_t spa_up[DFI_STAT_STAGE_COUNT] = {6u, 6u, 7u, 6u, 6u, 6u, 6u};
        dfi_boost(r, user, spa_up, DFI_POSITIONS);
        if (b->weather != DFI_WEATHER_RAIN) {
            pos->charge_turns = (uint8_t)DFI_CHARGE_TURNS_MAX;
            pos->locked_move = (uint8_t)((uint32_t)q->move_slot + 1u); /* wide-operands-reviewed: <= 4 */
            pos->locked_target = q->target;
            return DUOFORGE_OK;
        }
    }
    /* TryMove: Armor Tail on a standing foe stops a move with positive
     * priority aimed at the holder's side. */
    {
        const uint32_t priority = dfi_move_priority(b, m, md);
        const uint32_t aimed = targets[count - 1u];
        if (priority > DFI_PRIORITY_BIAS && aimed / 2u != side && md->target_class != DUOFORGE_TARGET_CLASS_SELF &&
            md->target_class != DUOFORGE_TARGET_CLASS_ALLY_SIDE && md->target_class != DUOFORGE_TARGET_CLASS_ALL) {
            for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
                const dfi_member *holder = dfi_at(b, (1u - side) * 2u + slot);
                if (holder != NULL && holder->hp != 0u && dfi_ability(holder, DFI_ABILITY_ARMORTAIL)) {
                    return DUOFORGE_OK;
                }
            }
        }
    }
    if (md->special == DFI_SPECIAL_PROTECT) {
        return dfi_run_protect(r, user);
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
        if (*turns == 0u) {
            const uint32_t screen = dfi_holds(m, DFI_ITEM_LIGHTCLAY) ? DFI_SCREEN_TURNS_MAX : 5u;
            const uint32_t duration = md->side_condition == DFI_SIDE_CONDITION_TAILWIND ? DFI_TAILWIND_TURNS_MAX : screen;
            *turns = (uint8_t)duration; /* <= 5 */
        }
        return DUOFORGE_OK;
    }
    if (status_move && md->pseudo_weather == DFI_PSEUDO_WEATHER_TRICK_ROOM) {
        /* addPseudoWeather: Trick Room again ends it (onFieldRestart). */
        const uint32_t duration = b->trick_room_turns != 0u ? 0u : DFI_FIELD_TURNS_MAX;
        b->trick_room_turns = (uint8_t)duration; /* <= 5 */
        return DUOFORGE_OK;
    }
    if (status_move && md->primary_status == DFI_STATUS_NONE && md->special != DFI_SPECIAL_PARTING_SHOT) {
        if (md->boost_role != DFI_BOOST_ROLE_PRIMARY_SELF || md->target_class != DUOFORGE_TARGET_CLASS_SELF) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        dfi_boost(r, user, md->boosts, DFI_POSITIONS);
        return DUOFORGE_OK;
    }
    if (md->special > DFI_SPECIAL_STRUGGLE) {
        return DUOFORGE_E_INVARIANT;
    }
    /* Fake Out's onTry (in trySpreadMoveHit, after TryMove): only on the
     * first move action since it entered. */
    if (md->special == DFI_SPECIAL_FAKE_OUT && pos->move_actions > 1u) {
        return DUOFORGE_OK;
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
    /* Struggle is typeless (its onModifyMove). */
    /* Struggle is typeless; Weather Ball turns Water in rain, Fire under sun
     * (its onModifyType, before the hit steps). */
    uint32_t move_type = md->special == DFI_SPECIAL_STRUGGLE ? DFI_CLOSURE_NONE : md->type;
    if (md->special == DFI_SPECIAL_WEATHER_BALL && b->weather == DFI_WEATHER_RAIN) {
        move_type = DFI_TYPE_WATER;
    } else if (md->special == DFI_SPECIAL_WEATHER_BALL && b->weather == DFI_WEATHER_SUN) {
        move_type = DFI_TYPE_FIRE;
    }
    const bool spread = count > 1u;
    /* Hit steps: Protect (TryHit), type immunity, accuracy per target. */
    bool hit[DFI_POSITIONS] = {false, false, false, false};
    for (uint32_t i = 0u; i < count; ++i) {
        const uint32_t t = targets[i];
        const dfi_active_slot *tp = dfi_pos(b, t);
        hit[i] = !((((uint32_t)tp->flags & DFI_VOL_PROTECT) != 0u) && ((md->flags & DFI_MOVE_FLAG_PROTECT) != 0u));
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
            tp->flags = (uint8_t)((uint32_t)tp->flags | DFI_VOL_FLASH_FIRE); /* wide-operands-reviewed */
            hit[i] = false;
            /* Its onTryHit sets move.accuracy = true on the shared active
             * move: the other targets of a spread move need no accuracy draw. */
            base_accuracy = 0u;
        } else if (dfi_ability(tm, DFI_ABILITY_LIGHTNINGROD) && move_type == DFI_TYPE_ELECTRIC) {
            static const uint8_t spa_up[DFI_STAT_STAGE_COUNT] = {6u, 6u, 7u, 6u, 6u, 6u, 6u};
            dfi_boost(r, t, spa_up, user);
            hit[i] = false;
        } else if (dfi_ability(tm, DFI_ABILITY_GOODASGOLD) && status_move) {
            hit[i] = false;
        }
    }
    for (uint32_t i = 0u; i < count && !status_move; ++i) {
        if (hit[i] && dfi_type_immune(dfi_at(b, targets[i]), move_type)) {
            hit[i] = false; /* a status move ignores type immunity */
        }
    }
    /* hitStepTryImmunity: a Prankster-boosted status move fails on a Dark
     * foe. */
    for (uint32_t i = 0u; i < count && status_move && dfi_ability(m, DFI_ABILITY_PRANKSTER); ++i) {
        if (hit[i] && targets[i] / 2u != side && dfi_has_type(dfi_at(b, targets[i]), DFI_TYPE_DARK)) {
            hit[i] = false;
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
            const uint32_t eva = dfi_pos(b, targets[i])->stages[DFI_STAGE_EVASION];
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
        }
    }
    /* A status move's primary status (runMoveEffects); sleep draws its turns.
     * Parting Shot lowers Attack and Special Attack and, if a stat fell and
     * a reserve stands, flags its user to switch out (selfSwitch). */
    if (status_move) {
        for (uint32_t i = 0u; i < count; ++i) {
            if (!hit[i]) {
                continue;
            }
            if (md->special == DFI_SPECIAL_PARTING_SHOT) {
                static const uint8_t drop[DFI_STAT_STAGE_COUNT] = {5u, 6u, 5u, 6u, 6u, 6u, 6u};
                if (dfi_boost(r, targets[i], drop, user) && m->hp != 0u && dfi_can_switch(b, side)) {
                    pos->switch_flag = (uint8_t)DFI_SWITCH_MOVE;
                }
                continue;
            }
            st = dfi_try_status(r, targets[i], md->primary_status);
            if (st != DUOFORGE_OK) {
                return st;
            }
        }
        return DUOFORGE_OK;
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
            st = dfi_deal(r, targets[i], damage[i]);
            if (st != DUOFORGE_OK) {
                return st;
            }
            const uint32_t dealt = before - (uint32_t)dfi_at(b, targets[i])->hp;
            total += dealt;
            if (md->drain[1] != 0u && dealt != 0u) {
                const uint32_t num = dealt * md->drain[0] * 2u + md->drain[1];
                dfi_heal(b, user, num / (2u * md->drain[1])); /* Math.round(dealt * a / b) */
            }
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
            dfi_boost(r, user, md->boosts, DFI_POSITIONS);
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
                dfi_boost(r, targets[i], md->boosts, user);
            } else if (md->sec_kind == DFI_SECONDARY_STATUS) {
                st = dfi_try_status(r, targets[i], md->sec_param);
            } else if (md->sec_kind == DFI_SECONDARY_VOLATILE) {
                st = dfi_add_volatile(r, targets[i], md->sec_param);
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
    /* DamagingHit, per damaged target: a damaging Fire move thaws a frozen
     * target (frz, status first), Stamina raises Defense by 1. */
    for (uint32_t i = 0u; i < count; ++i) {
        dfi_member *tm = dfi_at(b, targets[i]);
        if (!hit[i] || tm->hp == 0u) {
            continue;
        }
        if (move_type == DFI_TYPE_FIRE && tm->status == DFI_STATUS_FRZ) {
            tm->status = (uint8_t)DFI_STATUS_NONE;
            tm->status_counter = 0u;
        }
        if (dfi_ability(tm, DFI_ABILITY_STAMINA)) {
            static const uint8_t def_up[DFI_STAT_STAGE_COUNT] = {6u, 7u, 6u, 6u, 6u, 6u, 6u};
            dfi_boost(r, targets[i], def_up, user);
        }
    }
    bool any = false;
    for (uint32_t i = 0u; i < count; ++i) {
        any = any || hit[i];
    }
    /* The hit loop's Update (sim/battle-actions.ts:967). */
    if (any) {
        dfi_update(b);
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
        }
        if (recoil != 0u) {
            const uint32_t user_before = m->hp;
            st = dfi_deal(r, user, recoil);
            if (st != DUOFORGE_OK) {
                return st;
            }
            dfi_emergency_exit(b, user, user_before); /* inside applyRecoilDamage */
        }
        dfi_update(b);
        /* After the secondaries of the hit loop: a target that fell to half
         * HP (sim/battle-actions.ts:1005-1017). */
        for (uint32_t i = 0u; i < count; ++i) {
            if (hit[i]) {
                dfi_emergency_exit(b, targets[i], hp_before[i]);
            }
        }
    }
    /* AfterMoveSecondarySelf: Life Orb takes a tenth of the holder's HP
     * (at least 1) after a damaging move that hit something. */
    if (any && dfi_holds(m, DFI_ITEM_LIFEORB)) {
        const uint32_t recoil = (uint32_t)m->hp_max / 10u;
        const uint32_t user_before = m->hp;
        st = dfi_deal(r, user, recoil == 0u ? 1u : recoil);
        if (st != DUOFORGE_OK) {
            return st;
        }
        dfi_emergency_exit(b, user, user_before); /* after AfterMoveSecondarySelf */
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
    if ((ability != 0u && (ability > DFI_ABILITY_COUNT || dfi_support.abilities[ability - 1u] == 0u)) ||
        (item != 0u && (item > DFI_ITEM_COUNT || dfi_support.items[item - 1u] == 0u))) {
        return DUOFORGE_E_UNSUPPORTED; /* not marked in the support manifest */
    }
    const dfi_member *leaving = dfi_at(b, side * 2u + slot);
    if (leaving != NULL && leaving->hp != 0u && sd->positions[slot].switch_flag == 0u) {
        dfi_update(b); /* BeforeSwitchOut, then Update (sim/battle-actions.ts:80-84) */
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
        dfi_use_item(r->b, flat);
        dfi_boost(r, flat, def_up, DFI_POSITIONS);
    }
}

/* A SwitchIn handler: an entry ability (priority 0) or Grassy Seed's
 * onStart (onSwitchInPriority -1). */
static bool dfi_has_switch_in(const dfi_member *m)
{
    return dfi_has_entry(m) || dfi_holds(m, DFI_ITEM_GRASSYSEED);
}

static bool dfi_has_entry(const dfi_member *m)
{
    const uint32_t a = m->ability; /* 1 + id, 0 none */
    return a == 1u + DFI_ABILITY_DRIZZLE || a == 1u + DFI_ABILITY_DROUGHT || a == 1u + DFI_ABILITY_GRASSYSURGE ||
           a == 1u + DFI_ABILITY_INTIMIDATE;
}

/* Drizzle and Drought (setWeather): the same weather is not restarted;
 * otherwise the weather is replaced for 5 turns. Grassy Surge
 * (setTerrain) likewise. Intimidate lowers the Attack of every standing
 * adjacent foe by 1. */
static void dfi_entry_ability(dfi_run *r, uint32_t flat)
{
    struct duoforge_battle *b = r->b;
    const dfi_member *m = dfi_at(b, flat);
    const uint32_t a = m->ability;
    if (a == 1u + DFI_ABILITY_DRIZZLE || a == 1u + DFI_ABILITY_DROUGHT) {
        const uint32_t w = a == 1u + DFI_ABILITY_DRIZZLE ? DFI_WEATHER_RAIN : DFI_WEATHER_SUN;
        if (b->weather != w) {
            b->weather = (uint8_t)w;
            b->weather_turns = (uint8_t)DFI_FIELD_TURNS_MAX;
        }
    } else if (a == 1u + DFI_ABILITY_GRASSYSURGE) {
        if (b->terrain != DFI_TERRAIN_GRASSY) {
            b->terrain = (uint8_t)DFI_TERRAIN_GRASSY;
            b->terrain_turns = (uint8_t)DFI_FIELD_TURNS_MAX;
            /* eachEvent('TerrainChange'): every Grassy Seed on the field;
             * each acts on its holder only. */
            for (uint32_t f = 0u; f < DFI_POSITIONS; ++f) {
                dfi_grassy_seed(r, f);
            }
        }
    } else if (a == 1u + DFI_ABILITY_INTIMIDATE) {
        static const uint8_t drop[DFI_STAGE_COUNT] = {5u, 6u, 6u, 6u, 6u, 6u, 6u}; /* Attack -1 */
        const uint32_t foe = 1u - flat / 2u;
        for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
            const dfi_member *t = dfi_at(b, foe * 2u + slot);
            if (t != NULL && t->hp != 0u) {
                dfi_boost(r, foe * 2u + slot, drop, flat);
            }
        }
    }
}

/* runSwitch (sim/battle-actions.ts:177-192): every active Pokemon, a
 * fainted one included, is sorted by its last speed (Battle.speedSort, ties
 * shuffled); the SwitchIn handlers of the Pokemon that entered then run in
 * that order. A tie decides something only between two entering Pokemon
 * with an entry ability: only such a group draws (decision 0006 section
 * 5.1). */
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
        for (uint32_t i = 0u; i < count; ++i) {
            const uint32_t flat = list[next[i]];
            const dfi_member *m = dfi_at(b, flat);
            bearers += (((entering >> flat) & 1u) != 0u && m->hp != 0u && dfi_has_switch_in(m)) ? 1u : 0u;
        }
        for (uint32_t i = 0u; i < count; ++i) {
            if (next[i] != sorted + i) {
                const uint32_t e = list[sorted + i];
                list[sorted + i] = list[next[i]];
                list[next[i]] = e;
            }
        }
        for (uint32_t start = sorted; start + 1u < sorted + count && bearers >= 2u; ++start) {
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
     * (priority -1). */
    for (uint32_t pass = 0u; pass < 2u; ++pass) {
        for (uint32_t i = 0u; i < n; ++i) {
            const uint32_t flat = list[i];
            const dfi_member *m = dfi_at(b, flat);
            if (((entering >> flat) & 1u) == 0u || m->hp == 0u) {
                continue;
            }
            if (pass == 0u && dfi_has_entry(m)) {
                dfi_entry_ability(r, flat);
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
    dfi_knowledge *k = &b->sides[1u - q->side].knowledge[dfi_pos(b, flat)->occupant];
    k->revealed = (uint8_t)((uint32_t)k->revealed | DFI_REVEALED_MEGA); /* wide-operands-reviewed */
    if (dfi_has_entry(m)) {
        dfi_entry_ability(r, flat);
    }
    return DUOFORGE_OK;
}

/* ---------------------------------------------------------------- turn */

/* fieldEvent('Residual') (sim/battle.ts:484-567). The reference lists the
 * handlers of the field (weather: order 1 with its duration; Grassy
 * Terrain's duration: order 27), then per active Pokemon in slot order, a
 * fainted one included: its status handler with a callback (burn, order
 * 10), one handler per volatile with a duration (Protect, the stall
 * counter, flinch: no order), and the per-Pokemon field handler of Grassy
 * Terrain (heal, order 5, sub-order 2). Battle.speedSort orders the list by
 * order, speed (the speed each Pokemon had at its last updateSpeed; 0 for
 * the field) and sub-order; ties among callbacks draw (relative to their
 * group), ties among duration handlers change nothing and are not drawn
 * (decision 0006 section 5.1). The callbacks all sort ahead of the duration
 * handlers. After each callback faints are processed, and a finished battle
 * stops the residual phase. */
#define DFI_RES_WEATHER 1u
#define DFI_RES_TERRAIN_END 2u
#define DFI_RES_BURN 3u
#define DFI_RES_DURATION 4u
#define DFI_RES_GRASSY 5u
#define DFI_RES_FIELD_END 6u /* Trick Room, a side condition: duration only */
#define DFI_RES_LEFTOVERS 7u
#define DFI_RES_NO_ORDER 0xFFFFFFFFu
/* Trick Room, weather and terrain; three conditions per side; per position
 * a burn, four duration ends, Leftovers and Grassy Terrain. */
#define DFI_RES_MAX (3u + 3u * DUOFORGE_SIDE_COUNT + 7u * DFI_POSITIONS)

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

static bool dfi_grounded(const dfi_member *m)
{
    return !dfi_has_type(m, DFI_TYPE_FLYING);
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
    return dfi_residual_events(r);
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
        const uint32_t speed = r->speed_seen[flat];
        if (m->status == DFI_STATUS_BRN) {
            list[n] = (dfi_residual_entry){DFI_RES_BURN, flat, 10u, speed, 0u, true};
            n += 1u;
        }
        const uint32_t ends = ((((uint32_t)pos->flags & DFI_VOL_PROTECT) != 0u) ? 1u : 0u) +
                              (pos->stall_level != 0u ? 1u : 0u) +
                              ((((uint32_t)pos->flags & DFI_VOL_FLINCH) != 0u) ? 1u : 0u) +
                              (pos->charge_turns != 0u ? 1u : 0u);
        for (uint32_t k = 0u; k < ends; ++k) {
            list[n] = (dfi_residual_entry){DFI_RES_DURATION, flat, DFI_RES_NO_ORDER, speed, 2u, false};
            n += 1u;
        }
        if (dfi_holds(m, DFI_ITEM_LEFTOVERS)) {
            list[n] = (dfi_residual_entry){DFI_RES_LEFTOVERS, flat, 5u, speed, 4u, true};
            n += 1u;
        }
        if (b->terrain == DFI_TERRAIN_GRASSY) {
            list[n] = (dfi_residual_entry){DFI_RES_GRASSY, flat, 5u, speed, 2u, true};
            n += 1u;
        }
    }
    uint32_t callbacks = 0u;
    for (uint32_t i = 0u; i < n; ++i) {
        callbacks += list[i].callback ? 1u : 0u;
    }
    /* The selection sort with shuffled tie groups, until every callback is
     * placed. */
    uint32_t sorted = 0u;
    while (sorted < callbacks) {
        uint32_t next[DFI_RES_MAX] = {0};
        uint32_t count = 1u;
        next[0] = sorted;
        for (uint32_t i = sorted + 1u; i < n; ++i) {
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
            if (next[i] != sorted + i) {
                const dfi_residual_entry e = list[sorted + i];
                list[sorted + i] = list[next[i]];
                list[next[i]] = e;
            }
        }
        for (uint32_t start = sorted; start + 1u < sorted + count && list[sorted].callback; ++start) {
            uint32_t v = 0u;
            st = dfi_draw(r->draws, DFI_SITE_SPEED_TIE, start - sorted, count, &v);
            if (st != DUOFORGE_OK) {
                return st;
            }
            if (sorted + v != start) {
                const dfi_residual_entry e = list[start];
                list[start] = list[sorted + v];
                list[sorted + v] = e;
            }
        }
        sorted += count;
    }
    for (uint32_t i = 0u; i < callbacks; ++i) {
        const dfi_residual_entry *e = &list[i];
        if (e->kind == DFI_RES_WEATHER) {
            /* The duration counts down first; at 0 the weather ends. */
            b->weather_turns = (uint8_t)((uint32_t)b->weather_turns - 1u); /* wide-operands-reviewed: >= 1 */
            if (b->weather_turns == 0u) {
                b->weather = (uint8_t)DFI_WEATHER_NONE;
            } else {
                dfi_update(b); /* the upkeep: eachEvent('Weather'), then 'Update' */
            }
            continue;
        }
        dfi_member *m = dfi_at(b, e->flat);
        if (m->hp == 0u) {
            continue; /* the holder fainted */
        }
        if (e->kind == DFI_RES_LEFTOVERS) {
            dfi_heal(b, e->flat, (uint32_t)m->hp_max / 16u); /* heal(baseMaxhp / 16) */
            continue;
        }
        if (e->kind == DFI_RES_GRASSY) {
            /* heal(baseMaxhp / 16): at least 1, not above the maximum, not
             * for a Pokemon that is not grounded or at full HP. */
            if (dfi_grounded(m) && m->hp < m->hp_max) {
                uint32_t heal = (uint32_t)m->hp_max / 16u;
                heal = heal == 0u ? 1u : heal;
                const uint32_t hp = (uint32_t)m->hp + heal;
                m->hp = (uint16_t)(hp > m->hp_max ? m->hp_max : hp); /* wide-operands-reviewed: <= hp_max */
                dfi_knowledge_refresh_active(b);
            }
            continue;
        }
        const uint32_t damage = m->hp_max / 16u;
        st = dfi_deal(r, e->flat, damage == 0u ? 1u : damage);
        if (st != DUOFORGE_OK) {
            return st;
        }
        dfi_process_faints(r);
        if (r->ended) {
            return DUOFORGE_OK;
        }
    }
    /* The duration handlers: Trick Room, the side conditions and the
     * terrain count down, Protect and flinch end, the stall counter counts
     * down. */
    if (b->trick_room_turns != 0u) {
        b->trick_room_turns = (uint8_t)((uint32_t)b->trick_room_turns - 1u); /* wide-operands-reviewed: >= 1 */
    }
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        dfi_side *sd = &b->sides[s];
        uint8_t *conditions[3] = {&sd->reflect_turns, &sd->light_screen_turns, &sd->tailwind_turns};
        for (uint32_t k = 0u; k < 3u; ++k) {
            if (*conditions[k] != 0u) {
                *conditions[k] = (uint8_t)((uint32_t)*conditions[k] - 1u); /* wide-operands-reviewed: >= 1 */
            }
        }
    }
    if (b->terrain != DFI_TERRAIN_NONE) {
        b->terrain_turns = (uint8_t)((uint32_t)b->terrain_turns - 1u); /* wide-operands-reviewed: >= 1 */
        if (b->terrain_turns == 0u) {
            b->terrain = (uint8_t)DFI_TERRAIN_NONE;
        }
    }
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        dfi_active_slot *pos = dfi_pos(b, flat);
        if (pos->occupant == DFI_OCCUPANT_NONE) {
            continue;
        }
        pos->flags = (uint8_t)((uint32_t)pos->flags & ~(DFI_VOL_PROTECT | DFI_VOL_FLINCH)); /* wide-operands-reviewed */
        if (pos->charge_turns > 0u) {
            pos->charge_turns = (uint8_t)((uint32_t)pos->charge_turns - 1u); /* wide-operands-reviewed */
            if (pos->charge_turns == 0u) {
                pos->locked_move = 0u;
                pos->locked_target = 0u;
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
    dfi_knowledge_refresh_active(b);
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
            } else {
                b->sides[s].positions[slot].switch_flag = 0u;
            }
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
static duoforge_status dfi_terminal(struct duoforge_battle *b)
{
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

/* The queue is empty after the residual action or after the switches of
 * a REPLACEMENT: checkFainted and the switch request (sim/battle.ts:
 * 2524-2530, 2876-2915). A side with a fainted Pokemon on the field and a
 * reserve, or with an Emergency Exit after the residual action (`exits`,
 * by flat position), answers for those positions; otherwise the next turn
 * starts. A REPLACEMENT can follow a REPLACEMENT: when a side passed for a
 * fainted position and the Emergency Exit holder went to the bench. */
static duoforge_status dfi_finish_turn(struct duoforge_battle *b, uint32_t exits)
{
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

duoforge_status dfi_turn_start(const duoforge_context *ctx, struct duoforge_battle *b, dfi_draws *draws)
{
    if (!dfi_context_is_closure(ctx)) {
        return DUOFORGE_OK;
    }
    if (!dfi_closure_battle_supported(&dfi_support, b)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    dfi_run r = {ctx, b, draws, {0u, 0u, 0u, 0u}, 0u, 0u, false, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}};
    dfi_init_speeds(&r);
    /* The leads entered one by one (insertChoice updated each speed); their
     * entries run together. */
    duoforge_status st = dfi_update_speeds(&r);
    if (st != DUOFORGE_OK) {
        return st;
    }
    uint32_t entering = 0u;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        entering |= dfi_at(b, flat) != NULL ? 1u << flat : 0u;
    }
    st = dfi_run_entries(&r, entering);
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
    if (st == DUOFORGE_OK && !replacement && b->queue[0].kind == DFI_Q_MOVE) {
        st = dfi_sort_queue(r);
    }
    return st;
}

duoforge_status dfi_turn_run(const duoforge_context *ctx, struct duoforge_battle *b,
                             const duoforge_side_choice responses[DUOFORGE_SIDE_COUNT], dfi_draws *draws)
{
    const bool replacement = b->boundary_kind == DUOFORGE_BOUNDARY_REPLACEMENT;
    const bool pivot = b->boundary_kind == DUOFORGE_BOUNDARY_PIVOT;
    if (!dfi_context_is_closure(ctx) || (b->boundary_kind != DUOFORGE_BOUNDARY_TURN && !replacement && !pivot)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    if (!dfi_closure_battle_supported(&dfi_support, b) || ((replacement || pivot) && dfi_support.switching == 0u)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    dfi_run r = {ctx, b, draws, {0u, 0u, 0u, 0u}, 0u, 0u, false, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}};
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
            return dfi_terminal(b);
        }
        if (b->queue_len > 0u && b->queue[0].kind == DFI_Q_SWITCH_IN) {
            continue;
        }
        dfi_update(b); /* sim/battle.ts:2860-2861 */
        if (q.kind == DFI_Q_RESIDUAL) {
            /* sim/battle.ts:2862-2867: after the Update, so a Sitrus Berry
             * eaten there keeps its holder in. */
            for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
                exits |= dfi_exits(b, flat, r.residual_hp[flat]) ? 1u << flat : 0u;
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
    return dfi_finish_turn(b, exits);
}
