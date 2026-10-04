/*
 * Views and worlds (decision 0023): a player's public state of a battle, the
 * world built from a public state and a hypothesis, and the privileged
 * hypothesis of a battle. All three work on the canonical encoding
 * (src/codec/state_codec.h): the public state is the encoding with the
 * hidden values replaced, and a world is decoded strictly, so it passes the
 * full state check. The mapping of the hypothesis's words is integer
 * arithmetic only.
 */
#include <duoforge/duoforge_view.h>

#include <string.h>

#include "codec/state_codec.h"
#include "data/closure_tables.h"
#include "rng/pcg32.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "state/context_internal.h"
#include "state/invariants.h"
#include "state/knowledge.h"

/* The weights of a running hidden counter's value v = 1, 2, ... (a draw seen at a random point of its run). */
static const uint32_t dfi_sleep_weights[3] = {3u, 3u, 2u};           /* sample([2, 3, 3]) */
static const uint32_t dfi_confusion_weights[5] = {4u, 4u, 3u, 2u, 1u}; /* random(2, 6): 2..5 */

/* ---- integer uniforms ---- */

/* floor(u * n / 2^64) for n < 2^32, exactly. */
static uint32_t dfi_pick(uint64_t u, uint32_t n)
{
    const uint64_t lo = (u & 0xFFFFFFFFu) * (uint64_t)n;
    const uint64_t hi = (u >> 32) * (uint64_t)n;
    return (uint32_t)((hi + (lo >> 32)) >> 32); /* wide-operands-reviewed: < n < 2^32, no overflow (hi < 2^64 - 2^33) */
}

/* The middle word of those that pick index i of n: floor((2i + 1) * 2^63 / n), exactly (n < 2^16). */
static uint64_t dfi_word_of(uint32_t i, uint32_t n)
{
    const uint64_t half = (uint64_t)1u << 63;
    const uint64_t k = 2u * (uint64_t)i + 1u;
    return k * (half / n) + (k * (half % n)) / n;
}

/* The index of the value picked by u under integer weights w[0..n). */
static uint32_t dfi_pick_weighted(uint64_t u, const uint32_t *w, uint32_t n)
{
    uint32_t total = 0u;
    for (uint32_t i = 0u; i < n; ++i) {
        total += w[i];
    }
    uint32_t t = dfi_pick(u, total);
    for (uint32_t i = 0u; i < n; ++i) {
        if (t < w[i]) {
            return i;
        }
        t -= w[i];
    }
    return n - 1u;
}

static uint64_t dfi_word_of_weighted(uint32_t index, const uint32_t *w, uint32_t n)
{
    uint32_t start = 0u;
    uint32_t total = 0u;
    for (uint32_t i = 0u; i < n; ++i) {
        if (i < index) {
            start += w[i];
        }
        total += w[i];
    }
    return dfi_word_of(start + w[index] / 2u, total);
}

/* ---- bytes ---- */

static uint32_t rd16(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8);
}

static void wr16(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v & 0xFFu);        /* wide-operands-reviewed: masked */
    p[1] = (uint8_t)((v >> 8) & 0xFFu); /* wide-operands-reviewed: masked */
}

static void wr64(uint8_t *p, uint64_t v)
{
    for (uint32_t i = 0u; i < 8u; ++i) {
        p[i] = (uint8_t)((v >> (8u * i)) & 0xFFu); /* wide-operands-reviewed: masked */
    }
}

static uint8_t *side_at(uint8_t *s, uint32_t side)
{
    return s + DFI_ENC_SIDE_OFF + side * DFI_ENC_SIDE_SIZE;
}

static uint8_t *member_at(uint8_t *s, uint32_t side, uint32_t m)
{
    return side_at(s, side) + DFI_ENC_SIDE_MEMBERS_OFF + m * DFI_ENC_MEMBER_SIZE;
}

static uint8_t *position_at(uint8_t *s, uint32_t side, uint32_t p)
{
    return side_at(s, side) + DFI_ENC_SIDE_POS_OFF + p * DFI_ENC_POS_SIZE;
}

static uint8_t *knowledge_at(uint8_t *s, uint32_t side, uint32_t m)
{
    return side_at(s, side) + DFI_ENC_SIDE_KNOWLEDGE_OFF + m * DFI_ENC_KNOWLEDGE_SIZE;
}

/* ---- the candidates of a hidden value ---- */

/* The exact HP values whose display is (percent, flag) under hp_max, in ascending order: their count, and the
 * index-th of them in *out_hp (when index < count). */
static uint32_t dfi_hp_candidates(uint32_t percent, uint32_t flag, uint32_t hp_max, uint32_t index, uint32_t *out_hp)
{
    if (percent == 0u) {
        *out_hp = 0u;
        return 1u;
    }
    uint32_t n = 0u;
    for (uint32_t hp = 1u; hp <= hp_max; ++hp) {
        uint8_t pc = 0u;
        uint8_t fl = 0u;
        dfi_hp_display(hp, hp_max, &pc, &fl);
        if (pc == percent && fl == flag) {
            if (n == index) {
                *out_hp = hp;
            }
            ++n;
        }
    }
    return n;
}

/* The targets a move of the given target class could have chosen from flat position `user`, in ascending order. */
static uint32_t dfi_target_candidates(uint32_t target_class, uint32_t user, uint8_t *out)
{
    uint32_t n = 0u;
    const uint32_t ally = user ^ 1u;
    for (uint32_t f = 0u; f < DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE; ++f) {
        const bool foe = f / 2u != user / 2u;
        bool ok = false;
        switch (target_class) {
        case DUOFORGE_TARGET_CLASS_NORMAL:
        case DUOFORGE_TARGET_CLASS_ANY:
            ok = f != user;
            break;
        case DUOFORGE_TARGET_CLASS_ADJACENT_FOE:
            ok = foe;
            break;
        case DUOFORGE_TARGET_CLASS_ADJACENT_ALLY:
            ok = f == ally;
            break;
        case DUOFORGE_TARGET_CLASS_ADJACENT_ALLY_OR_SELF:
            ok = f == ally || f == user;
            break;
        default:
            break;
        }
        if (ok) {
            out[n++] = (uint8_t)f;
        }
    }
    if (n == 0u) {
        out[n++] = (uint8_t)DUOFORGE_TARGET_NONE;
    }
    return n;
}

/* ---- the public state ---- */

static duoforge_status dfi_view_encode(const duoforge_context *ctx, const duoforge_battle *b, uint32_t player,
                                       uint8_t *s, size_t *out_size)
{
    if (ctx == NULL || b == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (!dfi_context_fingerprint_matches(ctx, b->context_fingerprint)) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    if (player >= DUOFORGE_SIDE_COUNT) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    if (dfi_state_check(ctx, b, NULL) != DUOFORGE_OK) {
        return DUOFORGE_E_INVARIANT;
    }
    const uint32_t foe = player ^ 1u;
    /* the refusals, each decided by public facts */
    if (b->sides[foe].sealed != 0u) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    for (uint32_t q = 0u; q < b->queue_len && q < DFI_QUEUE_CAPACITY; ++q) {
        const dfi_queue_record *r = &b->queue[q];
        if (r->side == foe && (r->kind == DFI_Q_MOVE || r->kind == DFI_Q_SWITCH || r->kind == DFI_Q_MEGA)) {
            return DUOFORGE_E_UNSUPPORTED;
        }
    }
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const dfi_tail_pos *tp = &b->tail.sides[side].positions[p];
            if (tp->trap_turns != 0u || tp->lock_turns != 0u || (side == foe && tp->substitute_hp != 0u)) {
                return DUOFORGE_E_UNSUPPORTED;
            }
        }
    }
    const size_t n = dfi_encode_unchecked(ctx, b, s);
    memset(s + DFI_ENC_RNG_STATE_OFF, 0, 24u);
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            uint8_t *mb = member_at(s, side, m);
            if (mb[DFI_ENC_MEMBER_STATUS_OFF] == DFI_STATUS_SLP && mb[DFI_ENC_MEMBER_STATUS_COUNTER_OFF] != 0u) {
                mb[DFI_ENC_MEMBER_STATUS_COUNTER_OFF] = (uint8_t)DUOFORGE_VIEW_HIDDEN;
            }
        }
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            uint8_t *pb = position_at(s, side, p);
            if (pb[DFI_ENC_POS_CONFUSION_OFF] != 0u) {
                pb[DFI_ENC_POS_CONFUSION_OFF] = (uint8_t)DUOFORGE_VIEW_HIDDEN;
            }
            if (side == foe && pb[DFI_ENC_POS_CHARGE_OFF] != 0u) {
                pb[DFI_ENC_POS_LOCKED_TARGET_OFF] = (uint8_t)DUOFORGE_VIEW_HIDDEN_TARGET;
            }
        }
    }
    uint8_t *fs = side_at(s, foe);
    fs[DFI_ENC_SIDE_BROUGHT_OFF] = 0u;
    for (uint32_t k = 2u; k < DUOFORGE_MAX_ROSTER; ++k) {
        fs[DFI_ENC_SIDE_ORDER_OFF + k] = (uint8_t)DUOFORGE_VIEW_PICK_NONE;
    }
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        uint8_t *mb = member_at(s, foe, m);
        memset(mb + DFI_ENC_MEMBER_HP_OFF, 0, 2u + 2u + 2u * DFI_MEMBER_STAT_COUNT);
        memset(mb + DFI_ENC_MEMBER_STAT_POINTS_OFF, 0, DFI_STAT_POINT_COUNT);
        for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
            mb[DFI_ENC_MOVE_OFF + k * DFI_ENC_MOVE_SIZE + 2u] = 0u; /* pp */
        }
    }
    *out_size = n;
    return DUOFORGE_OK;
}

duoforge_status duoforge_battle_public(const duoforge_context *ctx, const duoforge_battle *battle, uint32_t player,
                                       duoforge_public_state *out)
{
    if (out == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    uint8_t s[DUOFORGE_VIEW_STATE_MAX];
    memset(s, 0, sizeof s);
    size_t n = 0u;
    const duoforge_status st = dfi_view_encode(ctx, battle, player, s, &n);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const uint32_t foe = player ^ 1u;
    memset(out, 0, sizeof *out);
    out->revision = DUOFORGE_VIEW_REVISION;
    out->player = player;
    out->state_size = (uint32_t)n;
    out->boundary = battle->boundary_kind;
    out->turn = battle->turn;
    out->request_mask = battle->request_mask;
    out->epoch = battle->request_epoch;
    out->foe_seen_mask = battle->sides[player].seen_mask;
    out->foe_leads[0] = battle->sides[foe].brought_order[0];
    out->foe_leads[1] = battle->sides[foe].brought_order[1];
    memcpy(out->state, s, n);
    return DUOFORGE_OK;
}

/* ---- the world ---- */

static bool dfi_all_zero(const uint8_t *p, size_t n)
{
    for (size_t i = 0u; i < n; ++i) {
        if (p[i] != 0u) {
            return false;
        }
    }
    return true;
}

/* A member of the encoding, as far as its stats need it. */
static void dfi_member_of(const uint8_t *mb, dfi_member *m)
{
    memset(m, 0, sizeof *m);
    m->species_id = (uint16_t)rd16(mb + DFI_ENC_MEMBER_SPECIES_OFF);
    m->is_mega = mb[DFI_ENC_MEMBER_IS_MEGA_OFF];
    m->nature = mb[DFI_ENC_MEMBER_NATURE_OFF];
    m->item = mb[DFI_ENC_MEMBER_ITEM_OFF];
    memcpy(m->stat_points, mb + DFI_ENC_MEMBER_STAT_POINTS_OFF, DFI_STAT_POINT_COUNT);
}

static duoforge_status dfi_check_picks(const duoforge_context *ctx, const duoforge_public_state *v,
                                       const duoforge_hypothesis *h, uint32_t member_count, uint8_t *out_mask)
{
    uint32_t mask = 0u;
    uint32_t count = 0u;
    for (uint32_t k = 0u; k < DUOFORGE_MAX_ROSTER; ++k) {
        const uint32_t m = h->pick_order[k];
        if (m == DUOFORGE_VIEW_PICK_NONE) {
            continue;
        }
        if (k != count || m >= member_count || ((mask >> m) & 1u) != 0u) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
        mask |= 1u << m;
        ++count;
    }
    if (v->boundary == DUOFORGE_BOUNDARY_TEAM_SELECTION) {
        if (count != 0u) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
    } else {
        if (count != ctx->brought_count || (v->foe_seen_mask & ~mask) != 0u) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
        for (uint32_t k = 0u; k < 2u; ++k) {
            if (v->foe_leads[k] != DUOFORGE_VIEW_PICK_NONE && v->foe_leads[k] != h->pick_order[k]) {
                return DUOFORGE_E_INVALID_ARGUMENT;
            }
        }
    }
    *out_mask = (uint8_t)mask;
    return DUOFORGE_OK;
}

duoforge_status duoforge_battle_from_view(const duoforge_context *ctx, const duoforge_public_state *view,
                                          const duoforge_hypothesis *hypothesis, duoforge_battle *out)
{
    if (ctx == NULL || view == NULL || hypothesis == NULL || out == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (view->revision != DUOFORGE_VIEW_REVISION || hypothesis->revision != DUOFORGE_HYPOTHESIS_REVISION) {
        return DUOFORGE_E_SCHEMA_MISMATCH;
    }
    const size_t n = dfi_state_encoded_size_of(ctx);
    if (view->player >= DUOFORGE_SIDE_COUNT || view->state_size != n || !dfi_all_zero(view->reserved, 5u) ||
        !dfi_all_zero(view->pad, 3u) || !dfi_all_zero(view->state + n, DUOFORGE_VIEW_STATE_MAX - n) ||
        hypothesis->reserved0 != 0u || !dfi_all_zero(hypothesis->reserved1, 6u)) {
        return DUOFORGE_E_MALFORMED;
    }
    if (!dfi_context_fingerprint_matches(ctx, view->state + DFI_ENC_FINGERPRINT_OFF)) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    uint8_t s[DUOFORGE_VIEW_STATE_MAX];
    memcpy(s, view->state, n);
    const uint32_t player = view->player;
    const uint32_t foe = player ^ 1u;
    uint8_t *fs = side_at(s, foe);
    const uint32_t member_count = fs[DFI_ENC_SIDE_MEMBER_COUNT_OFF];
    if (member_count > DUOFORGE_MAX_ROSTER) {
        return DUOFORGE_E_MALFORMED;
    }
    for (uint32_t m = 0u; m < member_count; ++m) {
        uint32_t sp[DFI_STAT_POINT_COUNT];
        for (uint32_t i = 0u; i < DFI_STAT_POINT_COUNT; ++i) {
            sp[i] = hypothesis->stat_points[m][i];
        }
        if (!dfi_stat_points_valid(sp)) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
    }
    uint8_t brought = 0u;
    const duoforge_status picks = dfi_check_picks(ctx, view, hypothesis, member_count, &brought);
    if (picks != DUOFORGE_OK) {
        return picks;
    }
    /* the RNG of a world: seeded with (0, 0) */
    dfi_rng rng;
    dfi_rng_seed(&rng, 0u, 0u);
    wr64(s + DFI_ENC_RNG_STATE_OFF, rng.state);
    wr64(s + DFI_ENC_RNG_INC_OFF, rng.inc);
    wr64(s + DFI_ENC_RNG_DRAWS_OFF, rng.draws);
    /* the foe's picks and members */
    fs[DFI_ENC_SIDE_BROUGHT_OFF] = brought;
    memcpy(fs + DFI_ENC_SIDE_ORDER_OFF, hypothesis->pick_order, DUOFORGE_MAX_ROSTER);
    const uint32_t seen = view->foe_seen_mask;
    for (uint32_t m = 0u; m < member_count; ++m) {
        uint8_t *mb = member_at(s, foe, m);
        dfi_member mem;
        dfi_member_of(mb, &mem);
        memcpy(mem.stat_points, hypothesis->stat_points[m], DFI_STAT_POINT_COUNT);
        if (!dfi_closure_member_derive(&mem)) {
            return DUOFORGE_E_MALFORMED;
        }
        memcpy(mb + DFI_ENC_MEMBER_STAT_POINTS_OFF, mem.stat_points, DFI_STAT_POINT_COUNT);
        wr16(mb + DFI_ENC_MEMBER_HP_MAX_OFF, mem.hp_max);
        for (uint32_t i = 0u; i < DFI_MEMBER_STAT_COUNT; ++i) {
            wr16(mb + DFI_ENC_MEMBER_STATS_OFF + 2u * i, mem.stats[i]);
        }
        const uint8_t *kb = knowledge_at(s, player, m);
        uint32_t hp = mem.hp_max;
        if (((seen >> m) & 1u) != 0u) {
            uint32_t unused = 0u;
            const uint32_t c = dfi_hp_candidates(kb[0], kb[1], mem.hp_max, UINT32_MAX, &unused);
            if (c == 0u) {
                return DUOFORGE_E_INVALID_ARGUMENT; /* no exact HP shows the display under this maximum HP */
            }
            (void)dfi_hp_candidates(kb[0], kb[1], mem.hp_max, dfi_pick(hypothesis->hp[m], c), &hp);
        }
        wr16(mb + DFI_ENC_MEMBER_HP_OFF, hp);
        const uint32_t moves = mb[DFI_ENC_MEMBER_MOVE_COUNT_OFF];
        for (uint32_t k = 0u; k < moves && k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
            uint8_t *mv = mb + DFI_ENC_MOVE_OFF + k * DFI_ENC_MOVE_SIZE;
            const uint32_t used = kb[DFI_ENC_KNOWLEDGE_USED_OFF + k];
            mv[2] = (uint8_t)(used >= mv[3] ? 0u : mv[3] - used); /* wide-operands-reviewed: <= pp_max */
        }
    }
    /* the hidden counters of both sides and the foe's charging targets */
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            uint8_t *mb = member_at(s, side, m);
            if (mb[DFI_ENC_MEMBER_STATUS_COUNTER_OFF] == DUOFORGE_VIEW_HIDDEN) {
                mb[DFI_ENC_MEMBER_STATUS_COUNTER_OFF] =
                    (uint8_t)(1u + dfi_pick_weighted(hypothesis->sleep[side][m], dfi_sleep_weights, 3u)); /* wide-operands-reviewed: 1..3 */
            }
        }
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            uint8_t *pb = position_at(s, side, p);
            if (pb[DFI_ENC_POS_CONFUSION_OFF] == DUOFORGE_VIEW_HIDDEN) {
                pb[DFI_ENC_POS_CONFUSION_OFF] =
                    (uint8_t)(1u + dfi_pick_weighted(hypothesis->confusion[side][p], dfi_confusion_weights, 5u)); /* wide-operands-reviewed: 1..5 */
            }
            if (side == foe && pb[DFI_ENC_POS_LOCKED_TARGET_OFF] == DUOFORGE_VIEW_HIDDEN_TARGET) {
                const uint32_t occupant = pb[0];
                const uint32_t slot = pb[DFI_ENC_POS_LOCKED_MOVE_OFF];
                if (occupant >= member_count || slot == 0u || slot > DUOFORGE_MAX_MOVE_SLOTS) {
                    return DUOFORGE_E_MALFORMED;
                }
                const uint32_t move = rd16(member_at(s, foe, occupant) + DFI_ENC_MOVE_OFF +
                                           (slot - 1u) * DFI_ENC_MOVE_SIZE);
                if (move >= ctx->move_count) {
                    return DUOFORGE_E_MALFORMED;
                }
                uint8_t cand[DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE];
                const uint32_t c = dfi_target_candidates(ctx->move_target_classes[move], foe * 2u + p, cand);
                pb[DFI_ENC_POS_LOCKED_TARGET_OFF] = cand[dfi_pick(hypothesis->charge_target[p], c)];
            }
        }
    }
    struct duoforge_battle world;
    const duoforge_status st = dfi_decode_state(ctx, s, n, &world, NULL);
    if (st != DUOFORGE_OK) {
        return st == DUOFORGE_E_CONTEXT_MISMATCH ? st : DUOFORGE_E_MALFORMED;
    }
    *out = world;
    return DUOFORGE_OK;
}

/* ---- the hypothesis of a battle (privileged) ---- */

duoforge_status duoforge_battle_hypothesis(const duoforge_context *ctx, const duoforge_battle *battle,
                                           uint32_t player, duoforge_hypothesis *out)
{
    if (out == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    uint8_t s[DUOFORGE_VIEW_STATE_MAX];
    size_t n = 0u;
    const duoforge_status st = dfi_view_encode(ctx, battle, player, s, &n);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const uint32_t foe = player ^ 1u;
    const dfi_side *fs = &battle->sides[foe];
    duoforge_hypothesis h;
    memset(&h, 0, sizeof h);
    h.revision = DUOFORGE_HYPOTHESIS_REVISION;
    memset(h.pick_order, DUOFORGE_VIEW_PICK_NONE, sizeof h.pick_order);
    uint32_t brought = 0u;
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        brought += ((uint32_t)fs->brought_mask >> m) & 1u;
    }
    for (uint32_t k = 0u; k < brought && k < DUOFORGE_MAX_ROSTER; ++k) {
        h.pick_order[k] = fs->brought_order[k];
    }
    for (uint32_t m = 0u; m < fs->member_count && m < DUOFORGE_MAX_ROSTER; ++m) {
        const dfi_member *mem = &fs->members[m];
        memcpy(h.stat_points[m], mem->stat_points, DFI_STAT_POINT_COUNT);
        if ((((uint32_t)battle->sides[player].seen_mask >> m) & 1u) != 0u) {
            const dfi_knowledge *k = &battle->sides[player].knowledge[m];
            uint32_t unused = 0u;
            const uint32_t c = dfi_hp_candidates(k->hp_percent, k->hp_flag, mem->hp_max, UINT32_MAX, &unused);
            for (uint32_t i = 0u; i < c; ++i) {
                uint32_t hp = 0u;
                (void)dfi_hp_candidates(k->hp_percent, k->hp_flag, mem->hp_max, i, &hp);
                if (hp == mem->hp) {
                    h.hp[m] = dfi_word_of(i, c);
                }
            }
        }
    }
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        const dfi_side *sd = &battle->sides[side];
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            const dfi_member *mem = &sd->members[m];
            if (mem->status == DFI_STATUS_SLP && mem->status_counter >= 1u && mem->status_counter <= 3u) {
                h.sleep[side][m] = dfi_word_of_weighted(mem->status_counter - 1u, dfi_sleep_weights, 3u);
            }
        }
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const dfi_active_slot *pos = &sd->positions[p];
            if (pos->confusion_turns >= 1u && pos->confusion_turns <= 5u) {
                h.confusion[side][p] = dfi_word_of_weighted(pos->confusion_turns - 1u, dfi_confusion_weights, 5u);
            }
            if (side == foe && pos->charge_turns != 0u && pos->occupant < fs->member_count &&
                pos->locked_move >= 1u && pos->locked_move <= DUOFORGE_MAX_MOVE_SLOTS) {
                const uint32_t move = fs->members[pos->occupant].moves[pos->locked_move - 1u].move_id;
                uint8_t cand[DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE];
                const uint32_t c =
                    move < ctx->move_count ? dfi_target_candidates(ctx->move_target_classes[move], foe * 2u + p, cand)
                                           : 0u;
                for (uint32_t i = 0u; i < c; ++i) {
                    if (cand[i] == pos->locked_target) {
                        h.charge_target[p] = dfi_word_of(i, c);
                    }
                }
            }
        }
    }
    *out = h;
    return DUOFORGE_OK;
}
