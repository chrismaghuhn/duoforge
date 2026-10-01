#include "state/request.h"

#include <string.h>

#include "combat/turn.h"
#include "core/arith.h"
#include "core/bytes.h"
#include "state/context_internal.h"
#include "state/invariants.h"
#include "state/transition.h"

/* 24 MOVE (4 slots x 3 targets x 2 Mega) + 5 SWITCH + PASS/NONE < 32. */
#define DFI_SLOT_LIST_CAP 32u
#define DFI_POSITION_COUNT (DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE)

typedef struct dfi_slot_list {
    duoforge_slot_command cmds[DFI_SLOT_LIST_CAP];
    uint32_t n;
} dfi_slot_list;

static bool dfi_list_push(dfi_slot_list *l, uint32_t kind, uint32_t move_slot, uint32_t target, uint32_t mega,
                          uint32_t reserve)
{
    if (l->n >= DFI_SLOT_LIST_CAP) {
        return false;
    }
    duoforge_slot_command *c = &l->cmds[l->n];
    memset(c, 0, sizeof *c);
    if (!dfi_u32_to_u8(kind, &c->kind) || !dfi_u32_to_u8(move_slot, &c->move_slot) ||
        !dfi_u32_to_u8(target, &c->target) || !dfi_u32_to_u8(mega, &c->mega) ||
        !dfi_u32_to_u8(reserve, &c->reserve)) {
        return false;
    }
    l->n += 1u;
    return true;
}

/* Selectable targets of a class for the actor at (side, slot), ascending
 * flat positions (decision 0005 section 4). Returns the count, 1..3. */
static uint32_t dfi_targets(uint32_t cls, uint32_t side, uint32_t slot, uint8_t out[3])
{
    const uint32_t me = side * DUOFORGE_ACTIVE_PER_SIDE + slot;
    const uint32_t ally = side * DUOFORGE_ACTIVE_PER_SIDE + (1u - slot);
    const uint32_t foe0 = (1u - side) * DUOFORGE_ACTIVE_PER_SIDE;
    uint32_t n = 0u;
    switch (cls) {
    case DUOFORGE_TARGET_CLASS_NORMAL:
    case DUOFORGE_TARGET_CLASS_ANY:
        for (uint32_t f = 0u; f < DFI_POSITION_COUNT; ++f) {
            if (f != me) {
                out[n] = (uint8_t)f;
                ++n;
            }
        }
        return n;
    case DUOFORGE_TARGET_CLASS_ADJACENT_ALLY:
        out[0] = (uint8_t)ally;
        return 1u;
    case DUOFORGE_TARGET_CLASS_ADJACENT_ALLY_OR_SELF: {
        const uint32_t lo = me < ally ? me : ally;
        const uint32_t hi = me < ally ? ally : me;
        out[0] = (uint8_t)lo;
        out[1] = (uint8_t)hi;
        return 2u;
    }
    case DUOFORGE_TARGET_CLASS_ADJACENT_FOE: {
        const uint32_t foe1 = foe0 + 1u;
        out[0] = (uint8_t)foe0;
        out[1] = (uint8_t)foe1;
        return 2u;
    }
    default:
        out[0] = (uint8_t)DUOFORGE_TARGET_NONE;
        return 1u;
    }
}

/* Reserves of a side: brought, not in a position, alive; ascending. The
 * state passed the invariant checker, so member_count <= 6. */
static uint32_t dfi_reserves(const dfi_side *side, uint8_t out[DUOFORGE_MAX_ROSTER])
{
    uint32_t n = 0u;
    for (uint32_t r = 0u; r < DUOFORGE_MAX_ROSTER && r < side->member_count; ++r) {
        if ((((uint32_t)side->brought_mask >> r) & 1u) == 0u) {
            continue;
        }
        if (side->positions[0].occupant == r || side->positions[1].occupant == r) {
            continue;
        }
        if (side->members[r].hp == 0u) {
            continue;
        }
        out[n] = (uint8_t)r;
        ++n;
    }
    return n;
}

/* Candidates of one requested slot in documented order. An alive occupant
 * without a move with PP left gets Struggle instead of its moves (target
 * NONE, with the Mega declarations its moves would have). */
static duoforge_status dfi_slot_candidates(const duoforge_context *ctx, const struct duoforge_battle *b,
                                           uint32_t s, uint32_t slot, dfi_slot_list *out)
{
    const dfi_side *side = &b->sides[s];
    const uint32_t occupant = side->positions[slot].occupant;
    uint8_t reserves[DUOFORGE_MAX_ROSTER] = {0};
    out->n = 0u;
    if (b->boundary_kind == DUOFORGE_BOUNDARY_TURN) {
        if (occupant == DFI_OCCUPANT_NONE || occupant >= DUOFORGE_MAX_ROSTER || side->members[occupant].hp == 0u) {
            return dfi_list_push(out, DUOFORGE_SLOT_PASS, 0u, 0u, 0u, 0u) ? DUOFORGE_OK : DUOFORGE_E_INVARIANT;
        }
        const dfi_member *mem = &side->members[occupant];
        const uint32_t megas = (mem->mega_capable != 0u && side->mega_used == 0u) ? 2u : 1u;
        uint32_t moves = 0u;
        for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS && k < mem->move_count; ++k) {
            const dfi_move_slot *mv = &mem->moves[k];
            if (mv->pp == 0u) {
                continue;
            }
            if (mv->move_id >= ctx->move_count) {
                return DUOFORGE_E_INVARIANT;
            }
            uint8_t targets[3] = {0, 0, 0};
            const uint32_t nt = dfi_targets(ctx->move_target_classes[mv->move_id], s, slot, targets);
            for (uint32_t ti = 0u; ti < nt; ++ti) {
                for (uint32_t mg = 0u; mg < megas; ++mg) {
                    if (!dfi_list_push(out, DUOFORGE_SLOT_MOVE, k, targets[ti], mg, 0u)) {
                        return DUOFORGE_E_INVARIANT;
                    }
                }
            }
            ++moves;
        }
        if (moves == 0u) {
            for (uint32_t mg = 0u; mg < megas; ++mg) {
                if (!dfi_list_push(out, DUOFORGE_SLOT_MOVE, DUOFORGE_MOVE_SLOT_STRUGGLE, DUOFORGE_TARGET_NONE, mg,
                                   0u)) {
                    return DUOFORGE_E_INVARIANT;
                }
            }
        }
    }
    const uint32_t nr = dfi_reserves(side, reserves);
    for (uint32_t i = 0u; i < nr; ++i) {
        if (!dfi_list_push(out, DUOFORGE_SLOT_SWITCH, 0u, 0u, 0u, reserves[i])) {
            return DUOFORGE_E_INVARIANT;
        }
    }
    if (b->boundary_kind != DUOFORGE_BOUNDARY_TURN) {
        if (!dfi_list_push(out, DUOFORGE_SLOT_PASS, 0u, 0u, 0u, 0u)) {
            return DUOFORGE_E_INVARIANT;
        }
    }
    return DUOFORGE_OK;
}

/* Enumeration sink: counts, optionally writes into a caller buffer, and
 * optionally looks for a byte-identical needle. */
typedef struct dfi_sink {
    duoforge_side_choice *buffer; /* nullable */
    uint32_t capacity;
    uint32_t count;
    const duoforge_side_choice *needle; /* nullable */
    uint32_t match; /* UINT32_MAX = none */
} dfi_sink;

static void dfi_sink_emit(dfi_sink *k, const duoforge_side_choice *c)
{
    if (k->buffer != NULL && k->count < k->capacity) {
        k->buffer[k->count] = *c;
    }
    if (k->needle != NULL && k->match == UINT32_MAX &&
        dfi_bytes_equal((const uint8_t *)k->needle, (const uint8_t *)c, sizeof *c)) {
        k->match = k->count;
    }
    k->count += 1u;
}

/* All ordered tuples of `m` distinct indices below `n`, lexicographic:
 * an odometer over n^m tuples that skips repeats. n <= 6, m <= n. */
static void dfi_enumerate_team(const struct duoforge_battle *b, uint32_t s, uint32_t n, uint32_t m, dfi_sink *k)
{
    uint32_t idx[DUOFORGE_MAX_ROSTER] = {0, 0, 0, 0, 0, 0};
    duoforge_side_choice c;
    for (;;) {
        uint32_t used = 0u;
        bool distinct = true;
        for (uint32_t i = 0u; i < m; ++i) {
            if (((used >> idx[i]) & 1u) != 0u) {
                distinct = false;
                break;
            }
            used |= 1u << idx[i];
        }
        if (distinct) {
            memset(&c, 0, sizeof c);
            c.epoch = b->request_epoch;
            c.side = (uint8_t)s;
            c.kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
            c.pick_count = (uint8_t)m;
            for (uint32_t i = 0u; i < m; ++i) {
                c.picks[i] = (uint8_t)idx[i];
            }
            dfi_sink_emit(k, &c);
        }
        /* Advance the odometer from the last position. */
        uint32_t j = m;
        for (;;) {
            if (j == 0u) {
                return;
            }
            --j;
            idx[j] += 1u;
            if (idx[j] < n) {
                break;
            }
            idx[j] = 0u;
        }
    }
}

static bool dfi_pair_allowed(const duoforge_slot_command *a, const duoforge_slot_command *c, bool forced,
                             uint32_t need)
{
    if (a->kind == DUOFORGE_SLOT_SWITCH && c->kind == DUOFORGE_SLOT_SWITCH && a->reserve == c->reserve) {
        return false; /* two actors cannot switch to the same reserve */
    }
    if (a->kind == DUOFORGE_SLOT_MOVE && c->kind == DUOFORGE_SLOT_MOVE && a->mega != 0u && c->mega != 0u) {
        return false; /* one Mega declaration per side per choice */
    }
    if (forced) {
        uint32_t switches = 0u;
        switches += a->kind == DUOFORGE_SLOT_SWITCH ? 1u : 0u;
        switches += c->kind == DUOFORGE_SLOT_SWITCH ? 1u : 0u;
        if (switches != need) {
            return false; /* exactly min(requested, reserves) actors switch */
        }
    }
    return true;
}

/* The complete joint domain of `s` at the current boundary, in documented
 * order (decision 0005 section 3). Precondition: `s` is requested. */
static duoforge_status dfi_enumerate_side(const duoforge_context *ctx, const struct duoforge_battle *b, uint32_t s,
                                          dfi_sink *k)
{
    const dfi_side *side = &b->sides[s];
    if (b->boundary_kind == DUOFORGE_BOUNDARY_TEAM_SELECTION) {
        dfi_enumerate_team(b, s, side->member_count, ctx->brought_count, k);
        return DUOFORGE_OK;
    }
    dfi_slot_list lists[DUOFORGE_ACTIVE_PER_SIDE];
    const uint32_t rs = side->requested_slots;
    uint32_t requested = 0u;
    for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
        lists[slot].n = 0u;
        if (((rs >> slot) & 1u) != 0u) {
            const duoforge_status st = dfi_slot_candidates(ctx, b, s, slot, &lists[slot]);
            if (st != DUOFORGE_OK) {
                return st;
            }
            ++requested;
        } else if (!dfi_list_push(&lists[slot], DUOFORGE_SLOT_NONE, 0u, 0u, 0u, 0u)) {
            return DUOFORGE_E_INVARIANT;
        }
    }
    const bool forced = b->boundary_kind != DUOFORGE_BOUNDARY_TURN;
    uint32_t need = 0u;
    if (forced) {
        uint8_t reserves[DUOFORGE_MAX_ROSTER] = {0};
        const uint32_t nr = dfi_reserves(side, reserves);
        need = requested < nr ? requested : nr;
    }
    duoforge_side_choice c;
    for (uint32_t i = 0u; i < lists[0].n; ++i) {
        for (uint32_t j = 0u; j < lists[1].n; ++j) {
            const duoforge_slot_command *a = &lists[0].cmds[i];
            const duoforge_slot_command *d = &lists[1].cmds[j];
            if (!dfi_pair_allowed(a, d, forced, need)) {
                continue;
            }
            memset(&c, 0, sizeof c);
            c.epoch = b->request_epoch;
            c.side = (uint8_t)s;
            c.kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
            c.slots[0] = *a;
            c.slots[1] = *d;
            dfi_sink_emit(k, &c);
        }
    }
    return DUOFORGE_OK;
}

/* Common prologue of the model-facing queries (after the NULL checks). */
static duoforge_status dfi_query_prologue(const duoforge_context *ctx, const struct duoforge_battle *b,
                                          uint32_t player)
{
    if (!dfi_context_fingerprint_matches(ctx, b->context_fingerprint)) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    if (player >= DUOFORGE_SIDE_COUNT) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    if (dfi_state_check(ctx, b, NULL) != DUOFORGE_OK) {
        return DUOFORGE_E_INVARIANT; /* one opaque engine-side failure */
    }
    return DUOFORGE_OK;
}

static bool dfi_player_requested(const struct duoforge_battle *b, uint32_t player)
{
    return (((uint32_t)b->request_mask >> player) & 1u) != 0u;
}

duoforge_status duoforge_battle_request(const duoforge_context *ctx, const duoforge_battle *battle,
                                        uint32_t player, duoforge_request *out_request)
{
    if (ctx == NULL || battle == NULL || out_request == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    const duoforge_status st = dfi_query_prologue(ctx, battle, player);
    if (st != DUOFORGE_OK) {
        return st;
    }
    duoforge_request r;
    memset(&r, 0, sizeof r);
    r.epoch = battle->request_epoch;
    r.boundary_kind = battle->boundary_kind;
    r.player = (uint8_t)player;
    if (dfi_player_requested(battle, player)) {
        dfi_sink k = {NULL, 0u, 0u, NULL, UINT32_MAX};
        const duoforge_status es = dfi_enumerate_side(ctx, battle, player, &k);
        if (es != DUOFORGE_OK) {
            return es;
        }
        r.requested = 1u;
        r.slot_mask = battle->sides[player].requested_slots;
        r.candidate_count = k.count;
    }
    *out_request = r;
    return DUOFORGE_OK;
}

duoforge_status duoforge_battle_candidates(const duoforge_context *ctx, const duoforge_battle *battle,
                                           uint32_t player, duoforge_side_choice *buffer, uint32_t capacity,
                                           uint32_t *out_count)
{
    if (ctx == NULL || battle == NULL || out_count == NULL || (buffer == NULL && capacity != 0u)) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    const duoforge_status st = dfi_query_prologue(ctx, battle, player);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (!dfi_player_requested(battle, player)) {
        *out_count = 0u;
        return DUOFORGE_OK;
    }
    dfi_sink count_only = {NULL, 0u, 0u, NULL, UINT32_MAX};
    duoforge_status es = dfi_enumerate_side(ctx, battle, player, &count_only);
    if (es != DUOFORGE_OK) {
        return es;
    }
    if (capacity < count_only.count) {
        *out_count = count_only.count; /* the required size; nothing else is written */
        return DUOFORGE_E_CAPACITY;
    }
    dfi_sink writer = {buffer, capacity, 0u, NULL, UINT32_MAX};
    es = dfi_enumerate_side(ctx, battle, player, &writer);
    if (es != DUOFORGE_OK || writer.count != count_only.count) {
        return DUOFORGE_E_INVARIANT; /* unreachable: enumeration is deterministic */
    }
    *out_count = writer.count;
    return DUOFORGE_OK;
}

static bool dfi_choice_is_zero(const duoforge_side_choice *c)
{
    const uint8_t *p = (const uint8_t *)c;
    for (size_t i = 0u; i < sizeof *c; ++i) {
        if (p[i] != 0u) {
            return false;
        }
    }
    return true;
}

duoforge_status duoforge_battle_step(const duoforge_context *ctx, duoforge_battle *battle,
                                     const duoforge_decision_bundle *bundle, duoforge_step_result *out_result)
{
    return dfi_battle_step_tape(ctx, battle, bundle, NULL, 0u, NULL, out_result);
}

duoforge_status dfi_battle_step_tape(const duoforge_context *ctx, duoforge_battle *battle,
                                     const duoforge_decision_bundle *bundle, const dfi_tape_entry *tape,
                                     uint32_t tape_len, uint32_t *out_tape_used, duoforge_step_result *out_result)
{
    if (ctx == NULL || battle == NULL || bundle == NULL || out_result == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (!dfi_context_fingerprint_matches(ctx, battle->context_fingerprint)) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    const duoforge_decision_bundle in = *bundle; /* read the input once */
    if (dfi_state_check(ctx, battle, NULL) != DUOFORGE_OK) {
        return DUOFORGE_E_INVARIANT;
    }
    if (battle->boundary_kind == DUOFORGE_BOUNDARY_TERMINAL) {
        return DUOFORGE_E_INVALID_ARGUMENT; /* the battle is over: no bundle is valid */
    }
    if (in.epoch != battle->request_epoch) {
        return DUOFORGE_E_STALE_EPOCH;
    }
    if (in.response_mask != battle->request_mask || in.reserved[0] != 0u || in.reserved[1] != 0u ||
        in.reserved[2] != 0u) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    const uint32_t expected_kind = battle->boundary_kind == DUOFORGE_BOUNDARY_TEAM_SELECTION
                                       ? DUOFORGE_CHOICE_TEAM_SELECTION
                                       : DUOFORGE_CHOICE_SLOTS;
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const duoforge_side_choice *r = &in.responses[s];
        if (!dfi_player_requested(battle, s)) {
            if (!dfi_choice_is_zero(r)) {
                return DUOFORGE_E_INVALID_ARGUMENT;
            }
            continue;
        }
        if (r->epoch != battle->request_epoch) {
            return DUOFORGE_E_STALE_EPOCH;
        }
        if (r->side != s || r->kind != expected_kind) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
        /* Domain membership by byte equality: the accepted set is the
         * enumerated set, computed from this side's data only. */
        dfi_sink finder = {NULL, 0u, 0u, r, UINT32_MAX};
        const duoforge_status es = dfi_enumerate_side(ctx, battle, s, &finder);
        if (es != DUOFORGE_OK) {
            return es;
        }
        if (finder.match == UINT32_MAX) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
    }
    if ((battle->boundary_kind == DUOFORGE_BOUNDARY_TURN || battle->boundary_kind == DUOFORGE_BOUNDARY_REPLACEMENT) &&
        dfi_context_is_closure(ctx)) {
        /* The turn runs on a working copy; any failure commits nothing. */
        struct duoforge_battle tmp = *battle;
        dfi_draws draws = dfi_draws_from_rng(&tmp.rng);
        draws.tape = tape;
        draws.tape_len = tape_len;
        const duoforge_status ts = dfi_turn_run(ctx, &tmp, in.responses, &draws);
        if (out_tape_used != NULL) {
            *out_tape_used = draws.tape_pos;
        }
        if (ts != DUOFORGE_OK) {
            return ts;
        }
        if (dfi_state_check(ctx, &tmp, NULL) != DUOFORGE_OK) {
            return DUOFORGE_E_INVARIANT;
        }
        *battle = tmp;
        duoforge_step_result turn_res;
        memset(&turn_res, 0, sizeof turn_res);
        turn_res.epoch = battle->request_epoch;
        turn_res.kind = (uint8_t)DUOFORGE_STEP_BOUNDARY;
        turn_res.boundary_kind = battle->boundary_kind;
        turn_res.request_mask = battle->request_mask;
        *out_result = turn_res;
        return DUOFORGE_OK;
    }
    if (battle->boundary_kind != DUOFORGE_BOUNDARY_TEAM_SELECTION) {
        return DUOFORGE_E_UNSUPPORTED; /* no combat for this boundary or data kind yet */
    }
    dfi_team_picks picks;
    memset(&picks, 0xFF, sizeof picks);
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        for (uint32_t i = 0u; i < DUOFORGE_MAX_ROSTER && i < in.responses[s].pick_count; ++i) {
            picks.picks[s][i] = in.responses[s].picks[i];
        }
    }
    const duoforge_status ts = dfi_apply_team_selection(ctx, battle, &picks);
    if (ts != DUOFORGE_OK) {
        return ts; /* E_EXHAUSTED or E_INVARIANT; the battle is unchanged */
    }
    duoforge_step_result res;
    memset(&res, 0, sizeof res);
    res.epoch = battle->request_epoch;
    res.kind = (uint8_t)DUOFORGE_STEP_BOUNDARY;
    res.boundary_kind = battle->boundary_kind;
    res.request_mask = battle->request_mask;
    *out_result = res;
    return DUOFORGE_OK;
}

duoforge_status dfi_reprompt_side(const duoforge_context *ctx, struct duoforge_battle *b, uint32_t side,
                                  const duoforge_side_choice *other_accepted)
{
    if (side >= DUOFORGE_SIDE_COUNT || b->boundary_kind != DUOFORGE_BOUNDARY_TURN || b->request_mask != 3u) {
        return DUOFORGE_E_INVARIANT;
    }
    if (b->request_epoch == UINT32_MAX) {
        return DUOFORGE_E_EXHAUSTED;
    }
    struct duoforge_battle tmp = *b;
    const uint32_t other = 1u - side;
    const uint32_t mask = 1u << side; /* side < 2 */
    tmp.request_mask = (uint8_t)mask;
    tmp.sides[other].requested_slots = 0u;
    tmp.sides[other].sealed = 1u;
    for (uint32_t k = 0u; k < DUOFORGE_ACTIVE_PER_SIDE; ++k) {
        const duoforge_slot_command *c = &other_accepted->slots[k];
        tmp.sides[other].sealed_cmds[k].kind = c->kind;
        tmp.sides[other].sealed_cmds[k].move_slot = c->move_slot;
        tmp.sides[other].sealed_cmds[k].target = c->target;
        tmp.sides[other].sealed_cmds[k].mega = c->mega;
        tmp.sides[other].sealed_cmds[k].reserve = c->reserve;
    }
    uint32_t next_epoch = 0u;
    if (!dfi_add_u32(tmp.request_epoch, 1u, &next_epoch)) {
        return DUOFORGE_E_EXHAUSTED; /* unreachable after the check above */
    }
    tmp.request_epoch = next_epoch;
    if (dfi_state_check(ctx, &tmp, NULL) != DUOFORGE_OK) {
        return DUOFORGE_E_INVARIANT;
    }
    *b = tmp;
    return DUOFORGE_OK;
}
