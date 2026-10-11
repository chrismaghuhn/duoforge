/*
 * duoforge.state.pool_g9 (white-box): step G9 of the content expansion, Encore, in the POOL state tail (last_move,
 * encore_slot and encore_turns of a position, decision 0015 section 7), in the queue (Champions' replacement of the
 * target's queued action), in the request (every slot but the Encored one is disabled), in the residual (order 16, the
 * -end line) and in the view extension (decision 0018: encore_slot, supported bit 7).
 *
 * The recorded battles (g09_encore_* under "data": "pool") are replayed through the step with the reference's draws,
 * as in duoforge.reference.conformance_pool_data, which compares everything the reference shows: every HP, PP, stage,
 * event and request, and the tape, which is consumed exactly: the RANDOM_TARGET draw that decides who the replaced
 * action hits is one of its entries (the harness labels it resolve:insert, tools/reference/ps_trace.js). Here the state
 * that the reference does not show is read after every step: the tail's three fields of every position, and both
 * viewers' extension.
 *
 *   g09_encore_lock      Milotic uses Ice Beam; Raichu (faster) Encores it while Coil is queued: the action becomes Ice
 *                        Beam with a random target (-start Encore), the next requests offer only Ice Beam, the Encore
 *                        ends in the residual of the third turn.
 *   g09_encore_fail      Encore fails before the target has used a move (-fail, [still]); it lands on a Milotic that
 *                        queued the very move it used last (nothing is replaced); a second Encore on it is -fail.
 *   g09_encore_late      Encore after the target moved this turn: duration 4.
 *   g09_encore_switch    The Encore ends silently when the target switches out; the Milotic that returns is free.
 *   g09_encore_struggle  Encore onto Fake Out: the replaced Fake Out fails (first turn only), then Champions' rule
 *                        disables it and Encore the rest: the request offers Struggle until the Encore ends.
 *   g09_encore_tie_a/_b  Equal Speed (Ceruledge and Rillaboom): the replaced action ties Rillaboom's queued move, so
 *                        its place in the queue is a draw (INSERT_TIE, one tape entry; the two seeds give its two
 *                        values). The re-sort after Encore's action shuffles the tie again with the PRNG, whose outcome
 *                        depends on the order the insertion made, which is why the tape needs the entry.
 *
 *   g09_encore_encore   Encore on a target whose last move is Encore (the failencore flag): -fail; and the Encore of Politoed
 *                        on a Milotic that has moved (duration 4, the lock ends after the fourth residual).
 *
 * Also: the failencore predicate against the pinned flag (the list below is the pin's; tools/datagen/
 * pool_families.js reads it from this file and compares it with the pinned data), Encore's end when the Encored
 * move has no PP left (a state poke: no battle of the reference runs a move down to its last PP), and the request of
 * an Encored slot under Throat Chop and Heal Block.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

static void build_setup(const df_conf_battle *cb, duoforge_battle_setup *s)
{
    memset(s, 0, sizeof *s);
    s->rng_initstate = 1u;
    s->rng_initseq = 2u;
    for (uint32_t side = 0; side < 2u; ++side) {
        s->sides[side].member_count = cb->member_count;
        for (uint32_t m = 0; m < cb->member_count; ++m) {
            const df_conf_member *src = &cb->members[side][m];
            duoforge_member_setup *dst = &s->sides[side].members[m];
            dst->species_id = src->species;
            dst->gender = src->gender;
            dst->nature = src->nature;
            for (uint32_t i = 0; i < 6u; ++i) {
                dst->stat_points[i] = src->sp[i];
            }
            dst->ability = src->ability;
            dst->item = src->item;
            dst->move_count = src->move_count;
            for (uint32_t k = 0; k < src->move_count; ++k) {
                dst->moves[k].move_id = src->moves[k];
            }
        }
    }
}

static void bundle_of(const df_conf_step *st, const duoforge_battle *b, duoforge_decision_bundle *bd)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u)); /* wide-operands-reviewed */
    for (uint32_t s = 0; s < 2u; ++s) {
        if ((s == 0u && !st->answered0) || (s == 1u && !st->answered1)) {
            continue;
        }
        duoforge_side_choice *r = &bd->responses[s];
        r->epoch = b->request_epoch;
        r->side = (uint8_t)s;
        if (st->team) {
            r->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
            r->pick_count = 4u;
            for (uint32_t i = 0; i < 4u; ++i) {
                r->picks[i] = st->picks[s][i];
            }
        } else {
            r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
            for (uint32_t k = 0; k < 2u; ++k) {
                const df_conf_cmd *c = &st->cmds[s][k];
                r->slots[k] = (duoforge_slot_command){c->kind, c->move_slot, c->target, c->mega, c->reserve, {0u, 0u, 0u}};
            }
        }
    }
}

static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

/* The battle `name` after its first `steps` steps (the reference's draws as the tape); NULL when it fails. */
static duoforge_battle *replay(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps)
{
    const df_conf_battle *cb = find(name);
    if (!DF_CHECK(t, cb != NULL && steps <= cb->step_count)) {
        return NULL;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return NULL;
    }
    for (uint32_t si = 0u; si < steps; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0xFFFFFFFFu;
        const duoforge_status status =
            dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (!DF_CHECK(t, status == DUOFORGE_OK && used == st->tape_len)) {
            fprintf(stderr, "  %s step %u: %s\n", name, si, duoforge_status_name(status));
            duoforge_battle_destroy(b);
            return NULL;
        }
    }
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    return b;
}

/* The slot (slot + 1) that each position (side * 2 + slot) is Encored to after each step of each battle: what the protocol
 * lines say alone (`|-start|X|Encore` sets it, to the slot of the occupant's last `|move|` line on its open sheet; the
 * matching `|-end|X|Encore`, or a `|switch|`, `|drag|`, `|replace|` or `|faint|` of the position clears it: decision
 * 0018 section 6.1). tools/reference/test_trace_to_c.py derives the rows from the committed traces and specs and
 * requires this table to be exactly that. */
static const struct {
    const char *battle;
    uint32_t step;
    uint8_t slot[4];
} rows[] = {
    {"g09_encore_lock", 0u, {0u, 0u, 0u, 0u}},
    {"g09_encore_lock", 1u, {0u, 0u, 0u, 0u}},
    {"g09_encore_lock", 2u, {0u, 0u, 1u, 0u}},
    {"g09_encore_lock", 3u, {0u, 0u, 1u, 0u}},
    {"g09_encore_lock", 4u, {0u, 0u, 1u, 0u}},
    {"g09_encore_lock", 5u, {0u, 0u, 0u, 0u}},
    {"g09_encore_lock", 6u, {0u, 0u, 0u, 0u}},
    {"g09_encore_fail", 0u, {0u, 0u, 0u, 0u}},
    {"g09_encore_fail", 1u, {0u, 0u, 0u, 0u}},
    {"g09_encore_fail", 2u, {0u, 0u, 2u, 0u}},
    {"g09_encore_fail", 3u, {0u, 0u, 2u, 0u}},
    {"g09_encore_fail", 4u, {0u, 0u, 0u, 0u}},
    {"g09_encore_late", 0u, {0u, 0u, 0u, 0u}},
    {"g09_encore_late", 1u, {0u, 0u, 0u, 0u}},
    {"g09_encore_late", 2u, {0u, 0u, 2u, 0u}},
    {"g09_encore_late", 3u, {0u, 0u, 2u, 0u}},
    {"g09_encore_late", 4u, {0u, 0u, 2u, 0u}},
    {"g09_encore_late", 5u, {0u, 0u, 2u, 0u}},
    {"g09_encore_late", 6u, {0u, 0u, 0u, 0u}},
    {"g09_encore_switch", 0u, {0u, 0u, 0u, 0u}},
    {"g09_encore_switch", 1u, {0u, 0u, 0u, 0u}},
    {"g09_encore_switch", 2u, {0u, 0u, 1u, 0u}},
    {"g09_encore_switch", 3u, {0u, 0u, 1u, 0u}},
    {"g09_encore_switch", 4u, {0u, 0u, 0u, 0u}},
    {"g09_encore_switch", 5u, {0u, 0u, 0u, 0u}},
    {"g09_encore_struggle", 0u, {0u, 0u, 0u, 0u}},
    {"g09_encore_struggle", 1u, {0u, 0u, 0u, 0u}},
    {"g09_encore_struggle", 2u, {0u, 0u, 1u, 0u}},
    {"g09_encore_struggle", 3u, {0u, 0u, 1u, 0u}},
    {"g09_encore_struggle", 4u, {0u, 0u, 1u, 0u}},
    {"g09_encore_struggle", 5u, {0u, 0u, 0u, 0u}},
    {"g09_encore_struggle", 6u, {0u, 0u, 0u, 0u}},
    {"g09_encore_tie_a", 0u, {0u, 0u, 0u, 0u}},
    {"g09_encore_tie_a", 1u, {0u, 0u, 0u, 0u}},
    {"g09_encore_tie_a", 2u, {0u, 0u, 1u, 0u}},
    {"g09_encore_tie_a", 3u, {0u, 0u, 1u, 0u}},
    {"g09_encore_tie_b", 0u, {0u, 0u, 0u, 0u}},
    {"g09_encore_tie_b", 1u, {0u, 0u, 0u, 0u}},
    {"g09_encore_tie_b", 2u, {0u, 0u, 1u, 0u}},
    {"g09_encore_tie_b", 3u, {0u, 0u, 1u, 0u}},
    {"g09_encore_encore", 0u, {0u, 0u, 0u, 0u}},
    {"g09_encore_encore", 1u, {0u, 0u, 0u, 2u}},
    {"g09_encore_encore", 2u, {0u, 0u, 0u, 2u}},
    {"g09_encore_encore", 3u, {0u, 0u, 0u, 2u}},
    {"g09_encore_encore", 4u, {0u, 0u, 0u, 0u}},
};

/* After every step: the tail's Encore slot of each position is the row's, its turns are nonzero exactly then and at most
 * 4, the other tail fields that nothing here sets are zero (the state check of the whole battle passes), and both
 * viewers' extension is byte for byte the expected one: revision, viewer, epoch, the supported bits, encore_slot at the
 * rows' positions and nothing else (the turns never show; Encore is public, so the foe sees what the owner sees). */
static void check_battles(df_test *t, const duoforge_context *ctx, uint32_t *compared)
{
    static const char *const names[] = {"g09_encore_lock", "g09_encore_fail", "g09_encore_late", "g09_encore_switch",
                                        "g09_encore_struggle", "g09_encore_tie_a", "g09_encore_tie_b", "g09_encore_encore"};
    for (size_t n = 0u; n < sizeof names / sizeof names[0]; ++n) {
        const df_conf_battle *cb = find(names[n]);
        if (!DF_CHECK(t, cb != NULL)) {
            continue;
        }
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        duoforge_battle *b = NULL;
        if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
            continue;
        }
        for (uint32_t si = 0u; si < cb->step_count; ++si) {
            const df_conf_step *st = &cb->steps[si];
            duoforge_decision_bundle bd;
            bundle_of(st, b, &bd);
            duoforge_step_result res;
            uint32_t used = 0u;
            if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                                 DUOFORGE_OK)) {
                break;
            }
            DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
            const uint8_t *want_slot = NULL;
            for (size_t r = 0u; r < sizeof rows / sizeof rows[0]; ++r) {
                if (strcmp(rows[r].battle, names[n]) == 0 && rows[r].step == si) {
                    want_slot = rows[r].slot;
                }
            }
            if (!DF_CHECK(t, want_slot != NULL)) {
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
                continue;
            }
            for (uint32_t flat = 0u; flat < 4u; ++flat) {
                const dfi_tail_pos *tp = &b->tail.sides[flat / 2u].positions[flat % 2u];
                if (!DF_CHECK(t, tp->encore_slot == want_slot[flat] && (tp->encore_slot == 0u) == (tp->encore_turns == 0u) &&
                                     tp->encore_turns <= 4u)) {
                    fprintf(stderr, "  %s step %u position %u: slot %u turns %u, want slot %u\n", names[n], si, flat,
                            tp->encore_slot, tp->encore_turns, want_slot[flat]);
                }
            }
            duoforge_observation_ext ext[2];
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation ob;
                memset(&ob, 0, sizeof ob);
                DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, viewer, &ext[viewer]) == DUOFORGE_OK &&
                                duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK);
                duoforge_observation_ext want;
                memset(&want, 0, sizeof want);
                want.revision = (uint8_t)DUOFORGE_OBSERVATION_EXT_REVISION;
                want.player = (uint8_t)viewer;
                want.epoch = ob.epoch;
                want.supported = dfi_support.view_ext_features;
                for (uint32_t flat = 0u; flat < 4u; ++flat) {
                    want.sides[flat / 2u].positions[flat % 2u].encore_slot = want_slot[flat];
                }
                for (uint32_t g42f = 0u; g42f < 4u; ++g42f) { /* step G42: move_failed is the last move result FALSE */
                    const uint32_t g42last = ((uint32_t)b->tail.sides[g42f / 2u].positions[g42f % 2u].move_result >> 2) & 3u;
                    want.sides[g42f / 2u].positions[g42f % 2u].move_failed = g42last == 2u ? 1u : 0u;
                }                if (!DF_CHECK(t, memcmp(&ext[viewer], &want, sizeof want) == 0)) {
                    fprintf(stderr, "  %s step %u viewer %u: the extension differs from the protocol's\n", names[n], si,
                            viewer);
                }
                *compared += 1u;
            }
            DF_CHECK(t, memcmp(ext[0].sides, ext[1].sides, sizeof ext[0].sides) == 0);
        }
        duoforge_battle_destroy(b);
    }
}

/* What the engine offers a slot of `player`: how many candidates use the move slot `move_slot` for the slot `slot`,
 * and how many use Struggle. */
typedef struct offered {
    uint32_t count;
    uint32_t of_move_slot;
    uint32_t struggle;
    uint32_t moves;
} offered;

static offered offered_for(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, uint32_t player,
                           uint32_t slot, uint32_t move_slot)
{
    static duoforge_side_choice buf[DUOFORGE_MAX_CANDIDATES];
    offered o = {0u, 0u, 0u, 0u};
    uint32_t count = 0u;
    if (!DF_CHECK(t, duoforge_battle_candidates(ctx, b, player, buf, DUOFORGE_MAX_CANDIDATES, &count) == DUOFORGE_OK)) {
        return o;
    }
    o.count = count;
    for (uint32_t i = 0u; i < count; ++i) {
        const duoforge_slot_command *c = &buf[i].slots[slot];
        if (c->kind == (uint8_t)DUOFORGE_SLOT_MOVE) {
            o.moves += 1u;
            o.of_move_slot += c->move_slot == move_slot ? 1u : 0u;
            o.struggle += c->move_slot == DUOFORGE_MOVE_SLOT_STRUGGLE ? 1u : 0u;
        }
    }
    return o;
}

/* The pinned data/moves.ts moves with flags.failencore (failencore: 1), alphabetical: the tail of the Encore condition's
 * onStart fails for them (the move.flags['failencore'] test). tools/datagen/pool_families.js compares this list with the
 * pin. */
/* failencore:begin */
static const char *const failencore_names[] = {
    "assist",         "blazingtorque", "combattorque", "copycat",     "dynamaxcannon", "encore",
    "magicaltorque",  "mefirst",       "metronome",    "mimic",       "mirrormove",    "naturepower",
    "noxioustorque",  "sketch",        "sleeptalk",    "struggle",    "transform",     "wickedtorque",
};
/* failencore:end */

static bool is_failencore_name(const char *name)
{
    for (size_t i = 0u; i < sizeof failencore_names / sizeof failencore_names[0]; ++i) {
        if (strcmp(name, failencore_names[i]) == 0) {
            return true;
        }
    }
    return false;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g9");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kd = df_make_context(&df_config_pool_dev);

    /* The new public values as numbers (owner's OK needed: the detail of the volatile events). */
    DF_CHECK_EQ_U64(&t, DUOFORGE_VOLATILE_HEAL_BLOCK, 1u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VOLATILE_ENCORE, 2u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_ENCORE, 7u);
    DF_CHECK_EQ_U64(&t, DFI_SPECIAL_ENCORE, 15u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_ENCORE] != 0u);
    DF_CHECK(&t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_ENCORE)) != 0u);

    /* The failencore flag: for every move that a gated member can use (the marked ones, and Struggle) the engine's
     * predicate is the pinned flag; the engine has the one it needs for them alone, which is why it is not a column. */
    {
        uint32_t flagged = 0u;
        for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
            if (id != DFI_MOVE_STRUGGLE && dfi_support.moves[id] == 0u) {
                continue;
            }
            const bool pin = is_failencore_name(dfi_pool_move_names[id]);
            const bool engine = id == DFI_MOVE_STRUGGLE || id == DFI_MOVE_ENCORE; /* the predicate of turn.c */
            if (!DF_CHECK(&t, pin == engine)) {
                fprintf(stderr, "  move %s: pinned failencore %d, engine %d\n", dfi_pool_move_names[id], pin, engine);
            }
            flagged += pin ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, flagged, 2u); /* Encore and Struggle */
    }

    uint32_t compared = 0u;
    check_battles(&t, kp, &compared);
    DF_CHECK_EQ_U64(&t, compared, 2u * (uint32_t)(sizeof rows / sizeof rows[0]));
    uint32_t compared_dev = 0u;
    check_battles(&t, kd, &compared_dev); /* POOL_DEV: its own fingerprint, the same tables */
    DF_CHECK_EQ_U64(&t, compared_dev, compared);

    /* last_move: after turn 1 of g09_encore_lock Milotic used Ice Beam (slot 0: 1), Gholdengo Shadow Ball (slot 0: 1) and
     * Raichu Protect (slot 2: 3). */
    {
        duoforge_battle *b = replay(&t, kp, "g09_encore_lock", 2u);
        if (b != NULL) {
            DF_CHECK_EQ_U64(&t, b->tail.sides[1].positions[0].last_move, 1u);
            DF_CHECK_EQ_U64(&t, b->tail.sides[1].positions[1].last_move, 1u);
            DF_CHECK_EQ_U64(&t, b->tail.sides[0].positions[0].last_move, 3u);
            duoforge_battle_destroy(b);
        }
    }

    /* The request under the lock (g09_encore_lock): after the Encore, Milotic (position 2) is offered only its Ice Beam
     * (slot 0) and the switches; its ally and the other side are not touched. After the end (step 5) every move is back. */
    {
        duoforge_battle *b = replay(&t, kp, "g09_encore_lock", 3u);
        if (b != NULL) {
            const offered a = offered_for(&t, kp, b, 1u, 0u, 0u);
            DF_CHECK(&t, a.of_move_slot != 0u);
            DF_CHECK_EQ_U64(&t, a.moves, a.of_move_slot);
            DF_CHECK_EQ_U64(&t, a.struggle, 0u);
            DF_CHECK(&t, offered_for(&t, kp, b, 1u, 1u, 0u).moves > offered_for(&t, kp, b, 1u, 1u, 0u).of_move_slot);
            DF_CHECK(&t, offered_for(&t, kp, b, 0u, 0u, 0u).moves > offered_for(&t, kp, b, 0u, 0u, 0u).of_move_slot);
            duoforge_battle_destroy(b);
        }
    }

    /* Fake Out and Encore (g09_encore_struggle, after turn 3's request): Champions disables Fake Out after the first
     * turn and Encore every other slot, so the slot gets Struggle and no move. */
    {
        duoforge_battle *b = replay(&t, kp, "g09_encore_struggle", 3u);
        if (b != NULL) {
            const offered a = offered_for(&t, kp, b, 1u, 0u, 0u);
            DF_CHECK(&t, a.struggle != 0u);
            DF_CHECK_EQ_U64(&t, a.moves, a.struggle);
            duoforge_battle_destroy(b);
        }
    }

    /* The Encore ends early when the Encored move has no PP left (the callback of order 16 in the residual: data/moves.ts
     * 4724-4783, onResidual): g09_encore_lock after turn 2 (steps 0 to 2) with the Ice Beam of Milotic at 1 PP. Turn 3
     * (step 3) uses the last PP, so its residual shows -end although the duration (2 -> 1) has not run out. */
    {
        duoforge_battle *b = replay(&t, kp, "g09_encore_lock", 3u);
        const df_conf_battle *cb = find("g09_encore_lock");
        if (b != NULL && cb != NULL) {
            b->sides[1].members[b->sides[1].positions[0].occupant].moves[0].pp = 1u;
            DF_CHECK(&t, duoforge_battle_check(kp, b) == DUOFORGE_OK);
            const df_conf_step *st = &cb->steps[3];
            duoforge_decision_bundle bd;
            bundle_of(st, b, &bd);
            duoforge_step_result res;
            uint32_t used = 0u;
            static duoforge_event ev_buf[2][DUOFORGE_MAX_EVENTS];
            duoforge_event_buffer buffers[2] = {{ev_buf[0], DUOFORGE_MAX_EVENTS, 0u}, {ev_buf[1], DUOFORGE_MAX_EVENTS, 0u}};
            DF_CHECK(&t, dfi_battle_step_events_tape(kp, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res,
                                                      buffers) == DUOFORGE_OK);
            DF_CHECK_EQ_U64(&t, b->tail.sides[1].positions[0].encore_slot, 0u);
            DF_CHECK_EQ_U64(&t, b->tail.sides[1].positions[0].encore_turns, 0u);
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                uint32_t ends = 0u;
                for (uint32_t i = 0u; i < buffers[viewer].count; ++i) {
                    const duoforge_event *e = &buffers[viewer].events[i];
                    if (e->kind == (uint8_t)DUOFORGE_EVENT_VOLATILE_END && e->detail == (uint8_t)DUOFORGE_VOLATILE_ENCORE) {
                        ends += 1u;
                        DF_CHECK_EQ_U64(&t, e->position, 2u);
                    }
                }
                DF_CHECK_EQ_U64(&t, ends, 1u);
            }
            duoforge_battle_destroy(b);
        }
    }

    /* Encore on a target whose last move is Struggle, the other failencore move (the Encore case is a recorded battle,
     * g09_encore_encore; Struggle needs a poke because the request offers it only when every move is disabled): the engine's
     * own predicate on g09_encore_lock after turn 1 (steps 0 and 1), before the step with Raichu's Encore on Milotic, with
     * Milotic's last move set to Struggle (5). The Encore fails (-fail, no -start, no lock) although the target has moves
     * with PP left; without the poke the same step starts the lock. */
    {
        const df_conf_battle *cb = find("g09_encore_lock");
        duoforge_battle *b = replay(&t, kp, "g09_encore_lock", 2u);
        if (b != NULL && cb != NULL) {
            dfi_tail_pos *tp = &b->tail.sides[1].positions[0];
            tp->last_move = 5u;
            const df_conf_step *st = &cb->steps[2];
            duoforge_decision_bundle bd;
            bundle_of(st, b, &bd);
            duoforge_step_result res;
            static duoforge_event ev_buf[2][DUOFORGE_MAX_EVENTS];
            duoforge_event_buffer buffers[2] = {{ev_buf[0], DUOFORGE_MAX_EVENTS, 0u}, {ev_buf[1], DUOFORGE_MAX_EVENTS, 0u}};
            /* the battle's own random source: the poke changes which draws the step needs, so the recorded tape no longer fits */
            DF_CHECK(&t, duoforge_battle_step_events(kp, b, &bd, &res, buffers) == DUOFORGE_OK);
            DF_CHECK_EQ_U64(&t, tp->encore_slot, 0u);
            DF_CHECK_EQ_U64(&t, tp->encore_turns, 0u);
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                uint32_t starts = 0u;
                uint32_t fails = 0u;
                for (uint32_t k = 0u; k < buffers[viewer].count; ++k) {
                    const duoforge_event *e = &buffers[viewer].events[k];
                    starts += e->kind == (uint8_t)DUOFORGE_EVENT_VOLATILE_START ? 1u : 0u;
                    fails += e->kind == (uint8_t)DUOFORGE_EVENT_FAIL ? 1u : 0u;
                }
                DF_CHECK_EQ_U64(&t, starts, 0u);
                DF_CHECK(&t, fails >= 1u);
            }
        }
        if (b != NULL) {
            duoforge_battle_destroy(b);
        }
    }

    /* Throat Chop and Heal Block next to the lock: an Encored sound move that Throat Chop bars is disabled twice over, so
     * the slot gets Struggle; likewise a heal move under Heal Block. State pokes on g09_encore_lock after turn 2 (steps 0 to 2): Milotic's
     * Encored slot holds Hyper Voice (a sound move: flags2 bit 1) or Recover (a heal move: bit 2) instead of Ice Beam,
     * which only the request reads (the query check does not read the move rows). */
    {
        static const struct {
            uint32_t move;
            uint32_t timer; /* 0 Throat Chop, 1 Heal Block */
        } pokes[] = {{DFI_MOVE_HYPERVOICE, 0u}, {DFI_MOVE_RECOVER, 1u}};
        for (size_t i = 0u; i < sizeof pokes / sizeof pokes[0]; ++i) {
            duoforge_battle *b = replay(&t, kp, "g09_encore_lock", 3u);
            if (b == NULL) {
                continue;
            }
            dfi_tail_pos *tp = &b->tail.sides[1].positions[0];
            const uint32_t slot = (uint32_t)tp->encore_slot - 1u;
            b->sides[1].members[b->sides[1].positions[0].occupant].moves[slot].move_id = (uint16_t)pokes[i].move;
            const uint32_t bit = pokes[i].timer == 0u ? DFI_MOVE_FLAG2_SOUND : DFI_MOVE_FLAG2_HEAL;
            DF_CHECK(&t, (dfi_pool_move_flags2[pokes[i].move] & bit) != 0u);
            const offered before = offered_for(&t, kp, b, 1u, 0u, slot);
            DF_CHECK(&t, before.of_move_slot != 0u && before.struggle == 0u);
            if (pokes[i].timer == 0u) {
                tp->throat_chop_turns = 2u;
            } else {
                tp->heal_block_turns = 2u;
            }
            const offered after = offered_for(&t, kp, b, 1u, 0u, slot);
            DF_CHECK_EQ_U64(&t, after.of_move_slot, 0u);
            DF_CHECK(&t, after.struggle != 0u);
            DF_CHECK_EQ_U64(&t, after.moves, after.struggle); /* every other slot is disabled by the lock */
            duoforge_battle_destroy(b);
        }
    }

    duoforge_context_destroy(kd);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
