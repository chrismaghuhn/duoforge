/*
 * duoforge.state.pool_g90 (white-box): step G90 of the content expansion (decision 0015 5cs, decision 0060), the partial trap of
 * Bind, Wrap, Fire Spin, Sand Tomb, Snap Trap and Infestation.
 *
 * The battles are replayed by duoforge.reference.conformance_pool_data against the recorded battles g90_* (under "data": "pool"):
 * the start line and its draw (g90_wrap_band), the re-hit with no line and no draw (the same battle), the residual at 1/6 with
 * Binding Band, the trapped request (g90_infest_switch), the silent end when the source left (g90_fire_source_leaves).
 *
 * This file checks what the replay does not show by itself: the marks and the ids, the four fields of the trap after each step
 * (the turns of 5 or 6 drawn once and counted down by the residual, the source, the move and the band), the trapped flag of the
 * turn boundary, and the public view: two states that differ only in the drawn turns give byte-equal views for both players, and
 * a different source does not (the source is public, the turns are not: decision 0060, section 6).
 * Flat positions: side 0 slots 0 and 1 (flat 0, 1), side 1 slots 0 and 1 (flat 2, 3).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "combat/residual_order.h"
#include "combat/turn.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/invariants.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* One slot's command of a turn: a move (move slot and target flat position) or a switch (the reserve's roster index). */
typedef struct g90_cmd {
    uint8_t kind;      /* DUOFORGE_SLOT_MOVE or DUOFORGE_SLOT_SWITCH */
    uint8_t move_slot; /* 0-based */
    uint8_t target;    /* flat position, DUOFORGE_TARGET_NONE for none */
    uint8_t reserve;   /* roster index, for a switch */
} g90_cmd;

#define MV(slot, target) {DUOFORGE_SLOT_MOVE, (slot), (target), 0u}
#define SW(reserve) {DUOFORGE_SLOT_SWITCH, 0u, DUOFORGE_TARGET_NONE, (reserve)}
#define NO DUOFORGE_TARGET_NONE

#define FLAT_P1A 0u
#define FLAT_P1B 1u
#define FLAT_P2A 2u

/* The recorded battle `name` (conformance_pool.h): its setup, as the conformance test builds it. */
static const df_conf_battle *find_conf(const char *name)
{
    for (size_t i = 0u; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

static void setup_from(const df_conf_battle *cb, duoforge_battle_setup *s)
{
    memset(s, 0, sizeof *s);
    s->rng_initstate = 1u;
    s->rng_initseq = 2u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        s->sides[side].member_count = cb->member_count;
        for (uint32_t m = 0u; m < cb->member_count; ++m) {
            const df_conf_member *src = &cb->members[side][m];
            duoforge_member_setup *dst = &s->sides[side].members[m];
            dst->species_id = src->species;
            dst->gender = src->gender;
            dst->nature = src->nature;
            for (uint32_t i = 0u; i < 6u; ++i) {
                dst->stat_points[i] = src->sp[i];
            }
            dst->ability = src->ability;
            dst->item = src->item;
            dst->move_count = src->move_count;
            for (uint32_t k = 0u; k < src->move_count; ++k) {
                dst->moves[k].move_id = src->moves[k];
            }
        }
    }
}

/* The team preview: the first four of each paste (the leads are the first two). */
static void team_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        duoforge_side_choice *c = &bd->responses[side];
        c->epoch = b->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
        c->pick_count = 4u;
        for (uint32_t i = 0u; i < 4u; ++i) {
            c->picks[i] = (uint8_t)i;
        }
    }
}

/* One turn: cmd[side][slot]. */
static void turn_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b, const g90_cmd cmd[2][2])
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        duoforge_side_choice *c = &bd->responses[side];
        c->epoch = b->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
        for (uint32_t slot = 0u; slot < 2u; ++slot) {
            c->slots[slot].kind = cmd[side][slot].kind;
            c->slots[slot].move_slot = cmd[side][slot].move_slot;
            c->slots[slot].target = cmd[side][slot].target;
            c->slots[slot].reserve = cmd[side][slot].reserve;
        }
    }
}

static void finish(duoforge_context *ctx, duoforge_battle *b)
{
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

/* Creates the battle from `s` and runs its team preview. */
static bool begin(df_test *t, const duoforge_battle_setup *s, duoforge_context **ctx, duoforge_battle **b,
                  duoforge_decision_bundle *bd, duoforge_step_result *res)
{
    *ctx = df_make_context(&df_config_pool);
    DF_CHECK(t, *ctx != NULL);
    if (*ctx == NULL) {
        return false;
    }
    *b = df_make_battle(*ctx, s);
    DF_CHECK(t, *b != NULL);
    if (*b == NULL) {
        return false;
    }
    team_bundle(bd, *b);
    return duoforge_battle_step(*ctx, *b, bd, res) == DUOFORGE_OK;
}

/* The recorded battle `name`, started. */
static bool start(df_test *t, const char *name, duoforge_context **ctx, duoforge_battle **b, duoforge_decision_bundle *bd,
                  duoforge_step_result *res)
{
    const df_conf_battle *cb = find_conf(name);
    DF_CHECK(t, cb != NULL);
    if (cb == NULL) {
        return false;
    }
    duoforge_battle_setup s;
    setup_from(cb, &s);
    return begin(t, &s, ctx, b, bd, res);
}

static dfi_tail_pos *tail_of(duoforge_battle *b, uint32_t flat)
{
    return &b->tail.sides[flat / 2u].positions[flat % 2u];
}

static uint32_t hp_of(const duoforge_battle *b, uint32_t flat)
{
    const uint32_t occupant = b->sides[flat / 2u].positions[flat % 2u].occupant;
    return b->sides[flat / 2u].members[occupant].hp;
}

/* The row: the marks, the handler id, the ids after it, and the constants of decision 0060. */
static void test_row(df_test *t)
{
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_PARTIAL_TRAP, DFI_SPECIAL_DRAGON_DARTS + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_PARTIAL_TRAP + 1u);
    static const uint32_t moves[5] = {DFI_MOVE_BIND, DFI_MOVE_WRAP, DFI_MOVE_FIRESPIN, DFI_MOVE_SANDTOMB, DFI_MOVE_INFESTATION};
    for (uint32_t i = 0u; i < 5u; ++i) {
        DF_CHECK_EQ_U64(t, dfi_pool_moves[moves[i]].special, DFI_SPECIAL_PARTIAL_TRAP);
        DF_CHECK_EQ_U64(t, dfi_support.moves[moves[i]], 1u);
        DF_CHECK(t, dfi_pool_move_unmodeled[moves[i]] == NULL);
    }
    DF_CHECK_EQ_U64(t, DUOFORGE_VOLATILE_PARTIAL_TRAP, 12u);
    DF_CHECK_EQ_U64(t, DFI_SITE_PARTIAL_TRAP_TURNS, 23u);
    DF_CHECK_EQ_U64(t, DFI_RES_PARTIAL_TRAP, 18u);
}

/* The start and the residual of Wrap with Binding Band (g90_wrap_band, Milotic on flat 1 hits Golisopod on flat 2 every turn):
 * after the first step the trap holds 5 or 6 turns (a draw), the source is flat 1 + 1, the move Wrap + 1 and the band is 1; every
 * later step is a re-hit that restarts nothing (the turns go down by exactly one per residual), and the residual takes the HP
 * of the holder by 1/6. */
static void test_wrap_band(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g90_wrap_band", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g90_cmd turn1[2][2] = {{MV(1, NO), MV(0, NO)}, {MV(1, FLAT_P1B), MV(1, NO)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    const dfi_tail_pos *tp = tail_of(b, FLAT_P2A);
    DF_CHECK(t, tp->trap_turns == 4u || tp->trap_turns == 5u); /* the one draw of random(5, 7) (5 or 6), less the residual of its own turn */
    DF_CHECK(t, tp->trap_source == FLAT_P1B + 1u);
    DF_CHECK_EQ_U64(t, tp->trap_move, DFI_MOVE_WRAP + 1u);
    DF_CHECK_EQ_U64(t, tp->trap_band, 1u);
    DF_CHECK(t, dfi_switch_trapped(b, FLAT_P2A));
    /* the public presence bit (decision 0018 row 8): the foe's view of the trapped position shows it, the owner's too */
    for (uint32_t viewer = 0u; viewer < DUOFORGE_SIDE_COUNT; ++viewer) {
        duoforge_observation_ext ext;
        memset(&ext, 0, sizeof ext);
        DF_CHECK_EQ_U64(t, duoforge_battle_observe_ext(ctx, b, viewer, &ext), DUOFORGE_OK);
        DF_CHECK(t, (ext.sides[1].positions[0].volatiles & DUOFORGE_POSITION_EXT_PARTIAL_TRAP) != 0u);
        DF_CHECK(t, (ext.sides[0].positions[0].volatiles & DUOFORGE_POSITION_EXT_PARTIAL_TRAP) == 0u);
    }
    const uint32_t turns1 = tp->trap_turns;
    const uint32_t hp1 = hp_of(b, FLAT_P2A);
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    /* the second turn: the re-hit restarts nothing, the residual takes one turn off */
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, tail_of(b, FLAT_P2A)->trap_turns, turns1 - 1u);
    DF_CHECK(t, hp_of(b, FLAT_P2A) < hp1);
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

/* The source leaves (g90_fire_source_leaves: Salamence on flat 0 Fire Spins Golisopod on flat 2, then switches out): the trap is
 * ended silently at the residual of the turn the source left (no damage that turn, and no end line; the four fields are zero),
 * and the trapped flag is down at the boundary. */
static void test_source_leaves(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g90_fire_source_leaves", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    /* step 1: Salamence (reserve 2) comes in on flat 0 */
    static const g90_cmd turn1[2][2] = {{SW(2u), MV(1, NO)}, {MV(0, NO), MV(0, NO)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    /* step 2: Fire Spin on flat 2; the trap is up and its source is flat 0 + 1 */
    static const g90_cmd turn2[2][2] = {{MV(0, FLAT_P2A), MV(1, NO)}, {MV(0, NO), MV(0, NO)}};
    turn_bundle(&bd, b, turn2);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, tail_of(b, FLAT_P2A)->trap_turns != 0u);
    DF_CHECK_EQ_U64(t, tail_of(b, FLAT_P2A)->trap_source, FLAT_P1A + 1u);
    DF_CHECK_EQ_U64(t, tail_of(b, FLAT_P2A)->trap_move, DFI_MOVE_FIRESPIN + 1u);
    const uint32_t hp2 = hp_of(b, FLAT_P2A);
    /* step 3: Salamence (slot 0) switches out to reserve 0 (Dragapult); no damage on flat 2 in this turn */
    static const g90_cmd turn3[2][2] = {{SW(0u), MV(1, NO)}, {MV(0, NO), MV(0, NO)}};
    turn_bundle(&bd, b, turn3);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, tail_of(b, FLAT_P2A)->trap_turns, 0u);
    DF_CHECK_EQ_U64(t, tail_of(b, FLAT_P2A)->trap_source, 0u);
    DF_CHECK_EQ_U64(t, tail_of(b, FLAT_P2A)->trap_move, 0u);
    DF_CHECK_EQ_U64(t, tail_of(b, FLAT_P2A)->trap_band, 0u);
    DF_CHECK_EQ_U64(t, hp_of(b, FLAT_P2A), hp2);
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

/* Creates the battle of g90_wrap_band after its first step (the same steps in every copy). */
static bool wrap_first_step(df_test *t, duoforge_context **ctx, duoforge_battle **b)
{
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g90_wrap_band", ctx, b, &bd, &res)) {
        return false;
    }
    static const g90_cmd turn1[2][2] = {{MV(1, NO), MV(0, NO)}, {MV(1, FLAT_P1B), MV(1, NO)}};
    turn_bundle(&bd, *b, turn1);
    return duoforge_battle_step(*ctx, *b, &bd, &res) == DUOFORGE_OK;
}

/* The public view (decision 0060, section 6): two states that differ only in the drawn turns of the trap give byte-equal views
 * for both players (the turns are hidden for the owner too); a state whose trap has lost its source differs (the source is
 * public). The three states are the battle of g90_wrap_band after its first step; the copies change one field each, which is
 * still a valid state (the tail invariants of invariants.c). */
static void test_view_turns_hidden(df_test *t)
{
    duoforge_context *ctx_a = NULL, *ctx_c = NULL, *ctx_d = NULL;
    duoforge_battle *a = NULL, *c = NULL, *d = NULL;
    if (!wrap_first_step(t, &ctx_a, &a) || !wrap_first_step(t, &ctx_c, &c) || !wrap_first_step(t, &ctx_d, &d)) {
        finish(ctx_a, a);
        finish(ctx_c, c);
        finish(ctx_d, d);
        return;
    }
    const uint32_t turns = tail_of(a, FLAT_P2A)->trap_turns;
    DF_CHECK(t, turns != 0u);
    tail_of(c, FLAT_P2A)->trap_turns = (uint8_t)(turns == 5u ? 6u : 5u); /* the other draw of random(5, 7) */
    tail_of(d, FLAT_P2A)->trap_source = 0u;                              /* the source left: a different public fact */
    DF_CHECK(t, dfi_state_check(ctx_c, c, NULL) == DUOFORGE_OK);
    DF_CHECK(t, dfi_state_check(ctx_d, d, NULL) == DUOFORGE_OK);
    for (uint32_t player = 0u; player < DUOFORGE_SIDE_COUNT; ++player) {
        duoforge_public_state pa;
        duoforge_public_state pc;
        duoforge_public_state pd;
        memset(&pa, 0, sizeof pa);
        memset(&pc, 0, sizeof pc);
        memset(&pd, 0, sizeof pd);
        DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx_a, a, player, &pa), DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx_c, c, player, &pc), DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx_d, d, player, &pd), DUOFORGE_OK);
        DF_CHECK(t, pa.state_size == pc.state_size && memcmp(pa.state, pc.state, pa.state_size) == 0);
        DF_CHECK(t, pa.state_size != pd.state_size || memcmp(pa.state, pd.state, pa.state_size) != 0);
    }
    finish(ctx_a, a);
    finish(ctx_c, c);
    finish(ctx_d, d);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g90");
    test_row(&t);
    test_wrap_band(&t);
    test_source_leaves(&t);
    test_view_turns_hidden(&t);
    return df_test_end(&t);
}
