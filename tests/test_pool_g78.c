/*
 * duoforge.state.pool_g78 (white-box): step G78 of the content expansion (decision 0015 5ch, decision 0043), Dragon Darts.
 *
 * The branches are replayed by duoforge.reference.conformance_pool_data against the recorded battles g78_* (under "data": "pool"):
 * the split (both foes hit, -anim before the second hit), the chosen target stopped by Protect (silent, the partner takes both
 * hits and the move line is retargeted), the partner stopped by Protect (silent), the Fairy partner (silent immunity), a Fairy
 * target stopped after the first failure (the immunity line prints), a first target that falls on hit 1 (the partner still takes
 * hit 2), Pressure on both foes (two extra PP), a partner that has fallen (one target, two hits), the random retarget of a fallen
 * target, a user's ally as the target, and Emergency Exit (checked on the partner, never on the first target of a split).
 *
 * This file checks the state after the steps that the battle replay does not show by itself: the marks and the handler ids,
 * the hit points after a branch, the PP of the move, the move result (FALSE after a blocked split), and the refusals (E_UNSUPPORTED)
 * of R1 (Protect stops both targets), R2 (a Substitute on a target of a split) and R5 (Red Card held by a target of a split).
 * The refusals are set up from the setup of g78_split, with the change of one member named in its test. Flat positions: side 0
 * slots 0 and 1 (flat 0, 1), side 1 slots 0 and 1 (flat 2, 3).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/invariants.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* One slot's command of a turn: a move (move slot and target flat position) or a switch (the reserve's roster index). */
typedef struct g78_cmd {
    uint8_t kind;      /* DUOFORGE_SLOT_MOVE or DUOFORGE_SLOT_SWITCH */
    uint8_t move_slot; /* 0-based */
    uint8_t target;    /* flat position, DUOFORGE_TARGET_NONE for none */
    uint8_t reserve;   /* roster index, for a switch */
} g78_cmd;

#define MV(slot, target) {DUOFORGE_SLOT_MOVE, (slot), (target), 0u}
#define NO DUOFORGE_TARGET_NONE

/* Flat positions and roster indices of the teams of the recorded battles: side 0 Dragapult (0) and Milotic (1); side 1 the
 * lead foes in the order of the spec (p2a, p2b). */
#define FLAT_P2A 2u
#define FLAT_P2B 3u
#define FLAT_P1B 1u

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
static void turn_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b, const g78_cmd cmd[2][2])
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

/* Creates the battle from `s` (after any change of the setup) and runs its team preview. */
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

static bool full(const duoforge_battle *b, uint32_t side, uint32_t member)
{
    return b->sides[side].members[member].hp == b->sides[side].members[member].hp_max;
}

/* The row: the marks, the handler id and the id after it (UNMODELED follows Dragon Darts). */
static void test_row(df_test *t)
{
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_DRAGON_DARTS, DFI_SPECIAL_DRAGON_CHEER + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_DRAGON_DARTS + 1u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_DRAGONDARTS].special, DFI_SPECIAL_DRAGON_DARTS);
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_DRAGONDARTS], 1u);
    DF_CHECK(t, dfi_pool_move_unmodeled[DFI_MOVE_DRAGONDARTS] == NULL);
}

/* The split with no failure: both foes are hit (the battle replay checks the lines). */
static void test_split(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g78_split", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g78_cmd turn1[2][2] = {{MV(0, FLAT_P2A), MV(1, NO)}, {MV(1, FLAT_P1B), MV(1, 1u)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, !full(b, 1u, 0u));
    DF_CHECK(t, !full(b, 1u, 1u));
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

/* The chosen target stopped by Protect: the partner takes both hits, the chosen one takes none. */
static void test_protect_t(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g78_protect_t", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g78_cmd turn1[2][2] = {{MV(0, FLAT_P2A), MV(1, NO)}, {MV(2, NO), MV(1, 1u)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, full(b, 1u, 0u));
    DF_CHECK(t, !full(b, 1u, 1u));
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

/* The partner stopped by Protect (silent): the chosen target takes both hits. */
static void test_protect_p(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g78_protect_p", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g78_cmd turn1[2][2] = {{MV(0, FLAT_P2A), MV(1, NO)}, {MV(1, FLAT_P1B), MV(0, NO)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, full(b, 1u, 1u));
    DF_CHECK(t, !full(b, 1u, 0u));
    finish(ctx, b);
}

/* A Fairy partner (immune to Dragon): its silent immunity, the chosen target takes both hits. */
static void test_fairy_p(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g78_fairy_p", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g78_cmd turn1[2][2] = {{MV(0, FLAT_P2A), MV(1, NO)}, {MV(1, FLAT_P1B), MV(0, 0u)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, full(b, 1u, 1u));
    DF_CHECK(t, !full(b, 1u, 0u));
    finish(ctx, b);
}

/* A Protect on the chosen target, then a Fairy partner: the partner's immunity is printed (the flag is already clear), no hit
 * lands, and the move's result is FALSE (a following Stomping Tantrum would double). */
static void test_protect_t_fairy_p(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g78_protect_t_fairy_p", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g78_cmd turn1[2][2] = {{MV(0, FLAT_P2A), MV(1, NO)}, {MV(2, NO), MV(0, 0u)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, full(b, 1u, 0u));
    DF_CHECK(t, full(b, 1u, 1u));
    /* the turn has ended: this turn's result is in the last-turn bits (decision 0015 section 7, tail rev 4) */
    DF_CHECK_EQ_U64(t, (uint32_t)((b->tail.sides[0].positions[0].move_result >> DFI_MOVE_RESULT_LAST_SHIFT) & 0x3u), DFI_MOVE_RESULT_FALSE);
    finish(ctx, b);
}

/* Both foes have Pressure: the move's PP drops by its own use and by one for each foe that is a target (two). */
static void test_pressure2(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g78_pressure2", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    const uint32_t before = b->sides[0].members[0].moves[0].pp;
    static const g78_cmd turn1[2][2] = {{MV(0, FLAT_P2A), MV(1, NO)}, {MV(1, FLAT_P1B), MV(1, 1u)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, b->sides[0].members[0].moves[0].pp, before - 3u);
    finish(ctx, b);
}

/* Dragon Darts on the user's ally: one target, both hits on it. */
static void test_ally_target(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g78_ally_target", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g78_cmd turn1[2][2] = {{MV(0, FLAT_P1B), MV(1, NO)}, {MV(0, 0u), MV(1, 0u)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, !full(b, 0u, 1u));
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

/* R1 (decision 0043): Protect stops both targets of a split: E_UNSUPPORTED (the order of two stoppers is not modelled). */
static void test_refuse_protect_both(df_test *t)
{
    const df_conf_battle *cb = find_conf("g78_split");
    DF_CHECK(t, cb != NULL);
    if (cb == NULL) {
        return;
    }
    duoforge_battle_setup s;
    setup_from(cb, &s);
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!begin(t, &s, &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g78_cmd turn1[2][2] = {{MV(0, FLAT_P2A), MV(1, NO)}, {MV(2, NO), MV(0, NO)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK_EQ_U64(t, duoforge_battle_step(ctx, b, &bd, &res), DUOFORGE_E_UNSUPPORTED);
    finish(ctx, b);
}

/* R2 (decision 0043): a Substitute on a target of a split: E_UNSUPPORTED. The Substitute is the Protect slot of Golisopod in
 * the setup of g78_split (move slot 3), so the setup change is the only difference; the Substitute is up after turn 1. */
static void test_refuse_substitute(df_test *t)
{
    const df_conf_battle *cb = find_conf("g78_split");
    DF_CHECK(t, cb != NULL);
    if (cb == NULL) {
        return;
    }
    duoforge_battle_setup s;
    setup_from(cb, &s);
    s.sides[1].members[0].moves[2].move_id = DFI_MOVE_SUBSTITUTE;
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!begin(t, &s, &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g78_cmd turn1[2][2] = {{MV(1, NO), MV(1, NO)}, {MV(2, NO), MV(1, 1u)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, b->tail.sides[1].positions[0].substitute_hp != 0u);
    static const g78_cmd turn2[2][2] = {{MV(0, FLAT_P2A), MV(1, NO)}, {MV(1, FLAT_P1B), MV(1, 1u)}};
    turn_bundle(&bd, b, turn2);
    DF_CHECK_EQ_U64(t, duoforge_battle_step(ctx, b, &bd, &res), DUOFORGE_E_UNSUPPORTED);
    finish(ctx, b);
}

/* R5 (decision 0043): Red Card held by the partner of a split (Kingambit's Black Glasses in the setup changes to Red Card): E_UNSUPPORTED. */
static void test_refuse_red_card(df_test *t)
{
    const df_conf_battle *cb = find_conf("g78_split");
    DF_CHECK(t, cb != NULL);
    if (cb == NULL) {
        return;
    }
    duoforge_battle_setup s;
    setup_from(cb, &s);
    s.sides[1].members[1].item = DFI_ITEM_REDCARD + 1u; /* the setup item is 1 + the item id */
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!begin(t, &s, &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g78_cmd turn1[2][2] = {{MV(0, FLAT_P2A), MV(1, NO)}, {MV(1, FLAT_P1B), MV(1, 1u)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK_EQ_U64(t, duoforge_battle_step(ctx, b, &bd, &res), DUOFORGE_E_UNSUPPORTED);
    finish(ctx, b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g78");
    test_row(&t);
    test_split(&t);
    test_protect_t(&t);
    test_protect_p(&t);
    test_fairy_p(&t);
    test_protect_t_fairy_p(&t);
    test_pressure2(&t);
    test_ally_target(&t);
    test_refuse_protect_both(&t);
    test_refuse_substitute(&t);
    test_refuse_red_card(&t);
    return df_test_end(&t);
}
