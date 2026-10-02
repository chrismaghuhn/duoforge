#include "state/request.h"

#include <string.h>

#include "combat/turn.h"
#include "core/arith.h"
#include "core/bytes.h"
#include "data/closure_tables.h"
#include "data/pool_tables.h"
#include "state/context_internal.h"
#include "state/invariants.h"
#include "state/transition.h"

/* 24 MOVE (4 slots x 3 targets x 2 Mega) + 5 SWITCH + PASS/NONE < 32. */
#define DFI_SLOT_LIST_CAP 32u
_Static_assert(DFI_SLOT_LIST_CAP == DUOFORGE_MAX_SLOT_OPTIONS, "a slot list fits the factored domain");
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
 * without a selectable move gets Struggle instead of its moves: target NONE
 * and no Mega declaration (the reference locks the request to Struggle,
 * which then has no canMegaEvo, sim/pokemon.ts getMoveRequestData; a typed
 * mega is dropped with it, sim/side.ts chooseMove). */
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
        /* A locked move (twoturnmove's onLockMove): that move at the stored
         * target only; no other move, no switch, no Mega (sim/pokemon.ts
         * getMoveRequestData, sim/side.ts:675-689). */
        const dfi_active_slot *own = &side->positions[slot];
        if (dfi_context_is_closure(ctx) && own->charge_turns != 0u) {
            return dfi_list_push(out, DUOFORGE_SLOT_MOVE, (uint32_t)own->locked_move - 1u, own->locked_target, 0u, 0u)
                       ? DUOFORGE_OK
                       : DUOFORGE_E_INVARIANT;
        }
        const uint32_t megas = (mem->mega_capable != 0u && side->mega_used == 0u) ? 2u : 1u;
        /* A choice lock (Team C): choicelock's onDisableMove disables every
         * other slot (data/conditions.ts); the lock does not trap, and with
         * no usable locked move the slot gets Struggle. */
        const bool choice = ((uint32_t)own->flags & DFI_VOL_CHOICE_LOCK) != 0u;
        uint32_t moves = 0u;
        for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS && k < mem->move_count; ++k) {
            const dfi_move_slot *mv = &mem->moves[k];
            if (mv->pp == 0u || (choice && k + 1u != own->locked_move)) {
                continue;
            }
            if (mv->move_id >= ctx->move_count) {
                return DUOFORGE_E_INVARIANT;
            }
            /* Throat Chop disables every move with the sound flag and Heal Block every move with the heal flag
             * (onDisableMove, data/moves.ts:19403-19409 and 8300-8306; POOL kinds, the tail is zero elsewhere); with
             * no move left the slot gets Struggle, as for any disabled move. */
            {
                const dfi_tail_pos *tail = &b->tail.sides[s].positions[slot];
                const uint32_t flags2 = dfi_pool_move_flags2[mv->move_id];
                if ((tail->throat_chop_turns != 0u && (flags2 & DFI_MOVE_FLAG2_SOUND) != 0u) ||
                    (tail->heal_block_turns != 0u && (flags2 & DFI_MOVE_FLAG2_HEAL) != 0u)) {
                    continue;
                }
            }
            /* Champions disables Fake Out once its user has taken a move
             * action since it entered (data/mods/champions/moves.ts:354-361). */
            if (dfi_context_is_closure(ctx) && mv->move_id == DFI_MOVE_FAKEOUT &&
                side->positions[slot].move_actions != 0u) {
                continue;
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
        if (moves == 0u &&
            !dfi_list_push(out, DUOFORGE_SLOT_MOVE, DUOFORGE_MOVE_SLOT_STRUGGLE, DUOFORGE_TARGET_NONE, 0u, 0u)) {
            return DUOFORGE_E_INVARIANT;
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

/* Enumeration sink. With `buffer` NULL the enumeration only counts, in
 * closed form; otherwise it writes the candidates in documented order when
 * they are known to fit: `fits` (set by the caller) or the domain's upper
 * bound within `capacity`, and then sets `written`. Nothing is written past
 * `capacity`, and nothing at all when the bound may not fit. */
typedef struct dfi_sink {
    duoforge_side_choice *buffer; /* nullable: count only */
    uint32_t capacity;
    uint32_t count;
    bool fits;    /* in: the caller knows that the domain fits */
    bool written; /* out: the candidates were written */
} dfi_sink;

/* All ordered tuples of `m` distinct indices below `n`, lexicographic
 * (decision 0005 section 3): a depth-first walk over the unused indices
 * visits exactly the n!/(n-m)! tuples, in the order of an odometer over
 * n^m tuples that skips repeats. n <= 6, 1 <= m <= n. */
static void dfi_enumerate_team(const struct duoforge_battle *b, uint32_t s, uint32_t n, uint32_t m, dfi_sink *k)
{
    uint32_t total = 1u;
    for (uint32_t i = 0u; i < m; ++i) {
        total *= n - i; /* at most 720 */
    }
    if (k->buffer == NULL || !(k->fits || total <= k->capacity)) {
        k->count = total;
        return;
    }
    duoforge_side_choice head;
    memset(&head, 0, sizeof head);
    head.epoch = b->request_epoch;
    head.side = (uint8_t)s;
    head.kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
    head.pick_count = (uint8_t)m;
    uint32_t idx[DUOFORGE_MAX_ROSTER] = {0, 0, 0, 0, 0, 0};
    uint32_t used = 0u;
    uint32_t pos = 0u;
    for (;;) {
        while (idx[pos] < n && ((used >> idx[pos]) & 1u) != 0u) {
            idx[pos] += 1u;
        }
        if (idx[pos] == n) {
            if (pos == 0u) {
                break;
            }
            pos -= 1u;
            used &= ~(1u << idx[pos]);
            idx[pos] += 1u;
        } else if (pos + 1u == m) {
            if (k->count < k->capacity) {
                duoforge_side_choice *out = &k->buffer[k->count];
                *out = head;
                for (uint32_t i = 0u; i < m; ++i) {
                    out->picks[i] = (uint8_t)idx[i];
                }
            }
            k->count += 1u;
            idx[pos] += 1u;
        } else {
            used |= 1u << idx[pos];
            pos += 1u;
            idx[pos] = 0u;
        }
    }
    k->written = true;
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

/* The number of pairs dfi_pair_allowed accepts, without listing them.
 * Unforced, every pair counts but those the rule excludes: both actors
 * switching to one reserve, both declaring Mega (disjoint cases). Forced
 * lists are small and are counted pair by pair. */
static uint32_t dfi_pair_count(const dfi_slot_list lists[DUOFORGE_ACTIVE_PER_SIDE], bool forced, uint32_t need)
{
    uint32_t to[DUOFORGE_MAX_ROSTER] = {0, 0, 0, 0, 0, 0};
    uint32_t mega = 0u;
    bool simple = !forced;
    for (uint32_t j = 0u; j < lists[1].n && simple; ++j) {
        const duoforge_slot_command *d = &lists[1].cmds[j];
        if (d->kind == DUOFORGE_SLOT_SWITCH) {
            if (d->reserve < DUOFORGE_MAX_ROSTER) {
                to[d->reserve] += 1u;
            } else {
                simple = false;
            }
        } else if (d->kind == DUOFORGE_SLOT_MOVE && d->mega != 0u) {
            mega += 1u;
        }
    }
    uint32_t count = 0u;
    if (simple) {
        uint32_t excluded = 0u;
        for (uint32_t i = 0u; i < lists[0].n && simple; ++i) {
            const duoforge_slot_command *a = &lists[0].cmds[i];
            if (a->kind == DUOFORGE_SLOT_SWITCH) {
                if (a->reserve < DUOFORGE_MAX_ROSTER) {
                    excluded += to[a->reserve];
                } else {
                    simple = false;
                }
            } else if (a->kind == DUOFORGE_SLOT_MOVE && a->mega != 0u) {
                excluded += mega;
            }
        }
        count = lists[0].n * lists[1].n - excluded; /* at most 32 x 32 */
    }
    if (!simple) {
        count = 0u;
        for (uint32_t i = 0u; i < lists[0].n; ++i) {
            for (uint32_t j = 0u; j < lists[1].n; ++j) {
                count += dfi_pair_allowed(&lists[0].cmds[i], &lists[1].cmds[j], forced, need) ? 1u : 0u;
            }
        }
    }
    return count;
}

/* The per-slot candidate lists of `s` at a SLOTS boundary and the pair
 * rule's inputs: whether exactly `need` actors must switch (`forced`).
 * Shared by the enumeration and the membership test, so both accept the
 * same set. */
static duoforge_status dfi_side_lists(const duoforge_context *ctx, const struct duoforge_battle *b, uint32_t s,
                                      dfi_slot_list lists[DUOFORGE_ACTIVE_PER_SIDE], bool *out_forced,
                                      uint32_t *out_need)
{
    const dfi_side *side = &b->sides[s];
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
    *out_forced = forced;
    *out_need = need;
    return DUOFORGE_OK;
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
    bool forced = false;
    uint32_t need = 0u;
    const duoforge_status ls = dfi_side_lists(ctx, b, s, lists, &forced, &need);
    if (ls != DUOFORGE_OK) {
        return ls;
    }
    if (k->buffer == NULL || !(k->fits || lists[0].n * lists[1].n <= k->capacity)) {
        k->count = dfi_pair_count(lists, forced, need);
        return DUOFORGE_OK;
    }
    /* Every candidate is one header (reserved bytes zero) and two slot
     * commands: the header is built once and each allowed pair is written
     * straight into the caller's buffer, in the same order. */
    duoforge_side_choice head;
    memset(&head, 0, sizeof head);
    head.epoch = b->request_epoch;
    head.side = (uint8_t)s;
    head.kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
    for (uint32_t i = 0u; i < lists[0].n; ++i) {
        const duoforge_slot_command *a = &lists[0].cmds[i];
        for (uint32_t j = 0u; j < lists[1].n; ++j) {
            const duoforge_slot_command *d = &lists[1].cmds[j];
            if (!dfi_pair_allowed(a, d, forced, need)) {
                continue;
            }
            if (k->count < k->capacity) {
                duoforge_side_choice *out = &k->buffer[k->count];
                *out = head;
                out->slots[0] = *a;
                out->slots[1] = *d;
            }
            k->count += 1u;
        }
    }
    k->written = true;
    return DUOFORGE_OK;
}

/* Whether `needle` is in the joint domain of `s` without listing it: the
 * candidate it could be is built as the enumeration builds candidates (team
 * selection: distinct picks below member_count; slots: its two commands
 * found in the shared slot lists, the pair allowed by the same rule) and
 * compared byte for byte. The accepted set is the enumerated set, in time
 * linear in the list lengths instead of their product. */
static duoforge_status dfi_side_accepts(const duoforge_context *ctx, const struct duoforge_battle *b, uint32_t s,
                                        const duoforge_side_choice *needle, bool *out)
{
    *out = false;
    duoforge_side_choice c;
    memset(&c, 0, sizeof c);
    c.epoch = b->request_epoch;
    c.side = (uint8_t)s;
    if (b->boundary_kind == DUOFORGE_BOUNDARY_TEAM_SELECTION) {
        const uint32_t n = b->sides[s].member_count;
        const uint32_t m = ctx->brought_count;
        if (m > DUOFORGE_MAX_ROSTER) {
            return DUOFORGE_E_INVARIANT;
        }
        uint32_t used = 0u;
        for (uint32_t i = 0u; i < m; ++i) {
            const uint32_t pick = needle->picks[i];
            if (pick >= n || ((used >> pick) & 1u) != 0u) {
                return DUOFORGE_OK; /* the odometer emits only distinct picks below n */
            }
            used |= 1u << pick;
            c.picks[i] = (uint8_t)pick;
        }
        c.kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
        c.pick_count = (uint8_t)m;
        *out = dfi_bytes_equal((const uint8_t *)needle, (const uint8_t *)&c, sizeof c);
        return DUOFORGE_OK;
    }
    dfi_slot_list lists[DUOFORGE_ACTIVE_PER_SIDE];
    bool forced = false;
    uint32_t need = 0u;
    const duoforge_status ls = dfi_side_lists(ctx, b, s, lists, &forced, &need);
    if (ls != DUOFORGE_OK) {
        return ls;
    }
    uint32_t found[DUOFORGE_ACTIVE_PER_SIDE] = {UINT32_MAX, UINT32_MAX};
    for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
        for (uint32_t i = 0u; i < lists[slot].n && found[slot] == UINT32_MAX; ++i) {
            if (dfi_bytes_equal((const uint8_t *)&lists[slot].cmds[i], (const uint8_t *)&needle->slots[slot],
                                sizeof needle->slots[slot])) {
                found[slot] = i;
            }
        }
        if (found[slot] == UINT32_MAX) {
            return DUOFORGE_OK;
        }
    }
    const duoforge_slot_command *a = &lists[0].cmds[found[0]];
    const duoforge_slot_command *d = &lists[1].cmds[found[1]];
    if (!dfi_pair_allowed(a, d, forced, need)) {
        return DUOFORGE_OK;
    }
    c.kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
    c.slots[0] = *a;
    c.slots[1] = *d;
    *out = dfi_bytes_equal((const uint8_t *)needle, (const uint8_t *)&c, sizeof c);
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
    if (dfi_state_check_query(ctx, b, NULL) != DUOFORGE_OK) {
        return DUOFORGE_E_INVARIANT; /* one opaque engine-side failure (decision 0011) */
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
        dfi_sink k = {NULL, 0u, 0u, false, false};
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

duoforge_status duoforge_battle_result(const duoforge_context *ctx, const duoforge_battle *battle,
                                       uint32_t *out_result)
{
    if (ctx == NULL || battle == NULL || out_result == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    const duoforge_status st = dfi_query_prologue(ctx, battle, 0u);
    if (st != DUOFORGE_OK) {
        return st;
    }
    *out_result = battle->result; /* DFI_RESULT_* equals DUOFORGE_RESULT_* */
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
    /* One pass: the candidates are written only when the domain's bound
     * fits the capacity (DUOFORGE_MAX_CANDIDATES always does); otherwise the
     * pass only counts, and a second one writes if the domain fits. */
    dfi_sink sink = {buffer, capacity, 0u, false, false};
    duoforge_status es = dfi_enumerate_side(ctx, battle, player, &sink);
    if (es != DUOFORGE_OK) {
        return es;
    }
    if (capacity < sink.count) {
        *out_count = sink.count; /* the required size; nothing else is written */
        return DUOFORGE_E_CAPACITY;
    }
    if (!sink.written) {
        dfi_sink writer = {buffer, capacity, 0u, true, false};
        es = dfi_enumerate_side(ctx, battle, player, &writer);
        if (es != DUOFORGE_OK || writer.count != sink.count) {
            return DUOFORGE_E_INVARIANT; /* unreachable: enumeration is deterministic */
        }
    }
    *out_count = sink.count;
    return DUOFORGE_OK;
}

duoforge_status duoforge_battle_factored(const duoforge_context *ctx, const duoforge_battle *battle,
                                         uint32_t player, duoforge_factored_domain *out)
{
    if (ctx == NULL || battle == NULL || out == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    const duoforge_status st = dfi_query_prologue(ctx, battle, player);
    if (st != DUOFORGE_OK) {
        return st;
    }
    duoforge_factored_domain d;
    memset(&d, 0, sizeof d);
    d.epoch = battle->request_epoch;
    if (dfi_player_requested(battle, player) && battle->boundary_kind == DUOFORGE_BOUNDARY_TEAM_SELECTION) {
        d.kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
        d.member_count = (uint8_t)battle->sides[player].member_count;
        d.pick_count = (uint8_t)ctx->brought_count;
    } else if (dfi_player_requested(battle, player)) {
        /* The slot lists and the pair rule of the enumeration, so both forms
         * hold the same domain. */
        dfi_slot_list lists[DUOFORGE_ACTIVE_PER_SIDE];
        bool forced = false;
        uint32_t need = 0u;
        const duoforge_status ls = dfi_side_lists(ctx, battle, player, lists, &forced, &need);
        if (ls != DUOFORGE_OK) {
            return ls;
        }
        d.kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
        for (uint32_t s = 0u; s < DUOFORGE_ACTIVE_PER_SIDE; ++s) {
            d.slot_count[s] = (uint8_t)lists[s].n;
            for (uint32_t i = 0u; i < lists[s].n; ++i) {
                d.slots[s][i] = lists[s].cmds[i];
            }
        }
        for (uint32_t i = 0u; i < lists[0].n; ++i) {
            uint32_t row = 0u;
            for (uint32_t j = 0u; j < lists[1].n; ++j) {
                row |= dfi_pair_allowed(&lists[0].cmds[i], &lists[1].cmds[j], forced, need) ? 1u << j : 0u;
            }
            d.allowed[i] = row;
        }
    }
    *out = d;
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
    return dfi_battle_step_events_tape(ctx, battle, bundle, NULL, 0u, NULL, out_result, NULL);
}

duoforge_status duoforge_battle_step_events(const duoforge_context *ctx, duoforge_battle *battle,
                                            const duoforge_decision_bundle *bundle,
                                            duoforge_step_result *out_result,
                                            duoforge_event_buffer buffers[DUOFORGE_SIDE_COUNT])
{
    if (buffers == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    return dfi_battle_step_events_tape(ctx, battle, bundle, NULL, 0u, NULL, out_result, buffers);
}

duoforge_status dfi_battle_step_tape(const duoforge_context *ctx, duoforge_battle *battle,
                                     const duoforge_decision_bundle *bundle, const dfi_tape_entry *tape,
                                     uint32_t tape_len, uint32_t *out_tape_used, duoforge_step_result *out_result)
{
    return dfi_battle_step_events_tape(ctx, battle, bundle, tape, tape_len, out_tape_used, out_result, NULL);
}

/* Before the commit: every player's buffer must hold the step's events.
 * Otherwise E_CAPACITY, and only the counts are written, with the required
 * number (decision 0005 section 7). */
static duoforge_status dfi_events_fit(duoforge_event_buffer *buffers, const dfi_events *staged)
{
    if (buffers == NULL) {
        return DUOFORGE_OK;
    }
    bool fit = true;
    for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT; ++p) {
        fit = fit && buffers[p].capacity >= staged->count;
    }
    if (!fit) {
        for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT; ++p) {
            buffers[p].count = staged->count;
        }
        return DUOFORGE_E_CAPACITY;
    }
    return DUOFORGE_OK;
}

/* After the commit: each player's view of every event. */
static void dfi_events_write(duoforge_event_buffer *buffers, const dfi_events *staged)
{
    if (buffers == NULL) {
        return;
    }
    for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT; ++p) {
        for (uint32_t i = 0u; i < staged->count; ++i) {
            dfi_event_project(&staged->rec[i], p, &buffers[p].events[i]);
        }
        buffers[p].count = staged->count;
    }
}

duoforge_status dfi_battle_step_events_tape(const duoforge_context *ctx, duoforge_battle *battle,
                                            const duoforge_decision_bundle *bundle, const dfi_tape_entry *tape,
                                            uint32_t tape_len, uint32_t *out_tape_used,
                                            duoforge_step_result *out_result, duoforge_event_buffer *buffers)
{
    if (ctx == NULL || battle == NULL || bundle == NULL || out_result == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    /* Every step records its events: the knowledge is folded from them
     * (decision 0007 section 6), whether or not the caller takes them. */
    dfi_events staged;
    staged.count = 0u;
    staged.overflow = false;
    dfi_events *events = &staged;
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
        bool accepted = false;
        const duoforge_status es = dfi_side_accepts(ctx, battle, s, r, &accepted);
        if (es != DUOFORGE_OK) {
            return es;
        }
        if (!accepted) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
    }
    for (uint32_t p = 0u; buffers != NULL && p < DUOFORGE_SIDE_COUNT; ++p) {
        if (buffers[p].events == NULL && buffers[p].capacity != 0u) {
            return DUOFORGE_E_INVALID_ARGUMENT; /* capacity without storage */
        }
    }
    if ((battle->boundary_kind == DUOFORGE_BOUNDARY_TURN || battle->boundary_kind == DUOFORGE_BOUNDARY_REPLACEMENT ||
         battle->boundary_kind == DUOFORGE_BOUNDARY_PIVOT) &&
        dfi_context_is_closure(ctx)) {
        /* The turn runs on a working copy; any failure commits nothing. */
        struct duoforge_battle tmp = *battle;
        dfi_draws draws = dfi_draws_from_rng(&tmp.rng);
        draws.tape = tape;
        draws.tape_len = tape_len;
        const duoforge_status ts = dfi_turn_run(ctx, &tmp, in.responses, &draws, events);
        if (out_tape_used != NULL) {
            *out_tape_used = draws.tape_pos;
        }
        if (ts != DUOFORGE_OK) {
            return ts;
        }
        if (staged.overflow) {
            return DUOFORGE_E_INVARIANT; /* past the profile bound */
        }
        if (!dfi_events_fold_knowledge(battle, &tmp, &staged, 0u) ||
            dfi_state_check_since(ctx, &tmp, battle, NULL) != DUOFORGE_OK) {
            return DUOFORGE_E_INVARIANT;
        }
        const duoforge_status fs = dfi_events_fit(buffers, &staged);
        if (fs != DUOFORGE_OK) {
            return fs;
        }
        *battle = tmp;
        dfi_events_write(buffers, &staged);
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
    /* Team selection and, for CLOSURE data, the leads' entry effects run on
     * a working copy; any failure commits nothing. */
    struct duoforge_battle tmp = *battle;
    const duoforge_status ts = dfi_apply_team_selection(ctx, &tmp, &picks);
    if (ts != DUOFORGE_OK) {
        return ts; /* E_EXHAUSTED or E_INVARIANT; the battle is unchanged */
    }
    /* [switch] of every lead, in position order, then (CLOSURE) their
     * entries, then [turn] 1. */
    for (uint32_t flat = 0u; flat < 2u * DUOFORGE_ACTIVE_PER_SIDE; ++flat) {
        if (tmp.sides[flat / 2u].positions[flat % 2u].occupant < DUOFORGE_MAX_ROSTER) {
            const duoforge_event e = dfi_event_switch(&tmp, flat);
            dfi_events_push(events, &e);
        }
    }
    /* The selected state, its leads seen, is checked before their entries run. */
    const uint32_t leads = staged.count;
    if (!dfi_events_fold_knowledge(battle, &tmp, &staged, 0u) ||
        dfi_state_check_since(ctx, &tmp, battle, NULL) != DUOFORGE_OK) {
        return DUOFORGE_E_INVARIANT;
    }
    dfi_draws draws = dfi_draws_from_rng(&tmp.rng);
    draws.tape = tape;
    draws.tape_len = tape_len;
    const duoforge_status ss = dfi_turn_start(ctx, &tmp, &draws, events);
    if (out_tape_used != NULL) {
        *out_tape_used = draws.tape_pos;
    }
    if (ss != DUOFORGE_OK) {
        return ss;
    }
    duoforge_event turn = dfi_event_make(DUOFORGE_EVENT_TURN, DUOFORGE_NO_POSITION);
    turn.id = tmp.turn; /* [turn] 1 */
    dfi_events_push(events, &turn);
    if (staged.overflow) {
        return DUOFORGE_E_INVARIANT; /* past the profile bound */
    }
    if (!dfi_events_fold_knowledge(battle, &tmp, &staged, leads) ||
        dfi_state_check_since(ctx, &tmp, battle, NULL) != DUOFORGE_OK) {
        return DUOFORGE_E_INVARIANT;
    }
    const duoforge_status fs = dfi_events_fit(buffers, &staged);
    if (fs != DUOFORGE_OK) {
        return fs;
    }
    *battle = tmp;
    dfi_events_write(buffers, &staged);
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
