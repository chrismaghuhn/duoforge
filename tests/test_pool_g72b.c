/*
 * duoforge.state.pool_g72b (white-box): step G72b of the content expansion (decision 0015 5ce), Alluring Voice and Dragon Cheer,
 * with the position flags of tail rev 5 (the stats-raised bit, the Dragon Cheer stage) and the PIVOT refusal of the public record.
 *
 * The behaviour is replayed by duoforge.reference.conformance_pool_data: nine recorded battles (g72b_* under "data": "pool") cover
 * Alluring Voice on the turn of a raise (Defiant at the start, Intimidate), after the turn ends, after a switch, against an
 * unraised target, and at a mid-turn PIVOT; Dragon Cheer on a Dragon ally (stage 2) and a non-Dragon ally (stage 1), the crit
 * of each (-crit on the crit draws), a second cheer (-fail), and the clear on switch-out. This file checks the state after the
 * steps that matter, the view bit of the Dragon Cheer stage, the focus-energy guard, and the refusal of the public record at
 * the PIVOT with DUOFORGE_PUBLIC_CAUSE_RAISED_THIS_TURN. Flat positions: side 0 slots 0 and 1 (flat 0, 1), side 1 (flat 2, 3).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "data/closure_tables.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/invariants.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* One slot's command of a turn: a move (move slot and target flat position) or a switch (the reserve's roster index). */
typedef struct g72b_cmd {
    uint8_t kind;      /* DUOFORGE_SLOT_MOVE or DUOFORGE_SLOT_SWITCH */
    uint8_t move_slot; /* 0-based */
    uint8_t target;    /* flat position, DUOFORGE_TARGET_NONE for none */
    uint8_t reserve;   /* roster index, for a switch */
} g72b_cmd;

#define MV(slot, target) {DUOFORGE_SLOT_MOVE, (slot), (target), 0u}
#define SW(reserve) {DUOFORGE_SLOT_SWITCH, 0u, 0u, (reserve)} /* a switch: move slot and target zero (the records check it) */
#define NO DUOFORGE_TARGET_NONE

/* The position flags of tail rev 5 (battle_internal.h) of a flat position. */
static uint32_t flags_of(const duoforge_battle *b, uint32_t flat)
{
    return (uint32_t)b->tail.sides[flat / 2u].positions[flat % 2u].position_flags;
}

static uint32_t stage_of(const duoforge_battle *b, uint32_t flat)
{
    return (flags_of(b, flat) & DFI_POSFLAG_DRAGON_CHEER_MASK) >> DFI_POSFLAG_DRAGON_CHEER_SHIFT;
}

static bool raised_of(const duoforge_battle *b, uint32_t flat)
{
    return (flags_of(b, flat) & DFI_POSFLAG_STATS_RAISED) != 0u;
}

static uint32_t confusion_of(const duoforge_battle *b, uint32_t flat)
{
    return b->sides[flat / 2u].positions[flat % 2u].confusion_turns;
}

static uint32_t occupant_of(const duoforge_battle *b, uint32_t flat)
{
    return b->sides[flat / 2u].positions[flat % 2u].occupant;
}

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

/* The team preview: the first four of each paste (the leads are the first two), as the recorded battles pick them. */
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
static void turn_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b, const g72b_cmd cmd[2][2])
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

/* Starts the recorded battle `name`: the context, the battle and the team preview. Returns false when it cannot. */
static bool start(df_test *t, const char *name, duoforge_context **ctx, duoforge_battle **b, duoforge_decision_bundle *bd,
                  duoforge_step_result *res)
{
    *ctx = df_make_context(&df_config_pool);
    DF_CHECK(t, *ctx != NULL);
    const df_conf_battle *cb = find_conf(name);
    DF_CHECK(t, cb != NULL);
    if (*ctx == NULL || cb == NULL) {
        return false;
    }
    duoforge_battle_setup s;
    setup_from(cb, &s);
    *b = df_make_battle(*ctx, &s);
    DF_CHECK(t, *b != NULL);
    if (*b == NULL) {
        return false;
    }
    team_bundle(bd, *b);
    return duoforge_battle_step(*ctx, *b, bd, res) == DUOFORGE_OK;
}

static void finish(duoforge_context *ctx, duoforge_battle *b)
{
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

/* The row: the support marks, the handler ids, and the view bit of Dragon Cheer (the manifest and the view agree). */
static void test_row(df_test *t)
{
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_ALLURING_VOICE, DFI_SPECIAL_PHANTOM_FORCE + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_DRAGON_CHEER, DFI_SPECIAL_ALLURING_VOICE + 1u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_ALLURINGVOICE].special, DFI_SPECIAL_ALLURING_VOICE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_DRAGONCHEER].special, DFI_SPECIAL_DRAGON_CHEER);
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_ALLURINGVOICE], 1u);
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_DRAGONCHEER], 1u);
    DF_CHECK(t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_DRAGON_CHEER)) != 0u);
    DF_CHECK_EQ_U64(t, DUOFORGE_POSITION_EXT_DRAGON_CHEER, 0x40u);
    DF_CHECK_EQ_U64(t, DUOFORGE_VOLATILE_DRAGONCHEER, 10u);
    DF_CHECK_EQ_U64(t, DUOFORGE_PUBLIC_CAUSE_RAISED_THIS_TURN, 32u);
}

/* av_raised_turn: Kingambit's Attack was raised at the start (Defiant, Salamence's Intimidate), so it is raised on turn 1 and
 * Sylveon's Alluring Voice confuses it. */
static void test_av_raised_turn(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g72b_av_raised_turn", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    DF_CHECK(t, raised_of(b, 3u));
    DF_CHECK_EQ_U64(t, confusion_of(b, 3u), 0u);
    static const g72b_cmd turn1[2][2] = {{MV(1, NO), MV(0, 3u)}, {MV(1, NO), MV(3, 0u)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, confusion_of(b, 3u) != 0u);
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

/* av_last_turn: the raise of turn 1 ends with turn 1 (endTurn clears the bit), so Alluring Voice on turn 2 does not confuse. */
static void test_av_last_turn(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g72b_av_last_turn", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g72b_cmd turn1[2][2] = {{MV(1, NO), MV(1, NO)}, {MV(1, NO), MV(3, 0u)}};
    static const g72b_cmd turn2[2][2] = {{MV(1, NO), MV(0, 3u)}, {MV(1, NO), MV(3, 0u)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, !raised_of(b, 3u));
    turn_bundle(&bd, b, turn2);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, confusion_of(b, 3u), 0u);
    finish(ctx, b);
}

/* av_switch: Kingambit switches out on turn 1 (its raise goes with it), and Gholdengo, which takes its slot, is not confused. */
static void test_av_switch(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g72b_av_switch", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    DF_CHECK(t, raised_of(b, 3u));
    static const g72b_cmd turn1[2][2] = {{MV(1, NO), MV(0, 3u)}, {MV(1, NO), SW(2)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, occupant_of(b, 3u), 2u); /* Gholdengo, the third member */
    DF_CHECK(t, !raised_of(b, 3u));
    DF_CHECK_EQ_U64(t, confusion_of(b, 3u), 0u);
    finish(ctx, b);
}

/* av_control: Golurk (not raised: Intimidate only lowers it) is hit by Alluring Voice and is not confused. */
static void test_av_control(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g72b_av_control", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g72b_cmd turn1[2][2] = {{MV(1, NO), MV(0, 2u)}, {MV(2, NO), MV(3, 0u)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, !raised_of(b, 2u));
    DF_CHECK_EQ_U64(t, confusion_of(b, 2u), 0u);
    finish(ctx, b);
}

/* dc_dragon: Milotic cheers its Dragon ally Salamence on turn 1 (stage 2, the Dragon at start); the view bit of the position is
 * set, a second cheer on turn 2 fails (the stage stays 2), and the Dragon Claw of turn 2 crits (duoforge.reference.conformance_pool_data). */
static void test_dc_dragon(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g72b_dc_dragon", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    DF_CHECK_EQ_U64(t, stage_of(b, 1u), 0u);
    static const g72b_cmd turn1[2][2] = {{MV(0, 1u), MV(1, NO)}, {MV(1, NO), MV(1, NO)}};
    static const g72b_cmd turn2[2][2] = {{MV(2, NO), MV(0, 2u)}, {MV(2, NO), MV(1, NO)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, stage_of(b, 1u), 2u);
    /* the view of both players: the Dragon Cheer bit of Salamence's position, and no other */
    for (uint32_t viewer = 0u; viewer < DUOFORGE_SIDE_COUNT; ++viewer) {
        duoforge_observation_ext ob;
        DF_CHECK_EQ_U64(t, duoforge_battle_observe_ext(ctx, b, viewer, &ob), DUOFORGE_OK);
        DF_CHECK(t, (ob.sides[0].positions[1].volatiles & DUOFORGE_POSITION_EXT_DRAGON_CHEER) != 0u);
        DF_CHECK(t, (ob.sides[0].positions[0].volatiles & DUOFORGE_POSITION_EXT_DRAGON_CHEER) == 0u);
    }
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    turn_bundle(&bd, b, turn2);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, stage_of(b, 1u), 2u);
    finish(ctx, b);
}

/* dc_nondragon: Milotic cheers Raichu, a non-Dragon ally (stage 1); Raichu's Thunderbolt crits on turn 2 (the recorded seed). */
static void test_dc_nondragon(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g72b_dc_nondragon", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g72b_cmd turn1[2][2] = {{MV(0, 1u), MV(1, NO)}, {MV(1, NO), MV(1, NO)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, stage_of(b, 1u), 1u);
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

/* dc_second: the second Dragon Cheer on the cheered Salamence fails and leaves the stage as it was. */
static void test_dc_second(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g72b_dc_second", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g72b_cmd turn1[2][2] = {{MV(0, 1u), MV(1, NO)}, {MV(1, NO), MV(1, NO)}};
    static const g72b_cmd turn2[2][2] = {{MV(0, 1u), MV(1, NO)}, {MV(2, NO), MV(1, NO)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, stage_of(b, 1u), 2u);
    turn_bundle(&bd, b, turn2);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, stage_of(b, 1u), 2u);
    finish(ctx, b);
}

/* dc_switch: the cheer ends with the switch-out: Salamence leaves on turn 2 (its stage with it), comes back on turn 3, and a new
 * cheer on turn 4 starts a stage 2 again. */
static void test_dc_switch(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g72b_dc_switch", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g72b_cmd turn1[2][2] = {{MV(0, 1u), MV(1, NO)}, {MV(1, NO), MV(1, NO)}};
    static const g72b_cmd turn2[2][2] = {{MV(2, NO), SW(2)}, {MV(2, NO), MV(1, NO)}};
    static const g72b_cmd turn3[2][2] = {{MV(2, NO), SW(1)}, {MV(2, NO), MV(1, NO)}};
    static const g72b_cmd turn4[2][2] = {{MV(0, 1u), MV(1, NO)}, {MV(2, NO), MV(1, NO)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, stage_of(b, 1u), 2u);
    turn_bundle(&bd, b, turn2);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, occupant_of(b, 1u), 2u); /* Sylveon came in */
    DF_CHECK_EQ_U64(t, stage_of(b, 1u), 0u);
    turn_bundle(&bd, b, turn3);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, occupant_of(b, 1u), 1u); /* Salamence came back */
    DF_CHECK_EQ_U64(t, stage_of(b, 1u), 0u);
    turn_bundle(&bd, b, turn4);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, stage_of(b, 1u), 2u);
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

/* The guard of Dragon Cheer (its onStart refuses a target with Focus Energy; Focus Energy is unmarked, so no battle has it): with
 * the tail's focus_energy byte set, the cheer fails and the stage stays 0. */
static void test_dc_focus_energy_guard(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g72b_dc_dragon", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    b->tail.sides[0].positions[1].focus_energy = 1u; /* Salamence holds Focus Energy (a state no recorded battle reaches) */
    static const g72b_cmd turn1[2][2] = {{MV(0, 1u), MV(1, NO)}, {MV(1, NO), MV(1, NO)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, stage_of(b, 1u), 0u);
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

/* The PIVOT (g72b_av_pivot): Milotic's Eject Button switches it out mid-turn after Alluring Voice, and Golurk's move is still
 * queued. The public record and the causes call of that state name DUOFORGE_PUBLIC_CAUSE_RAISED_THIS_TURN; the record refuses. */
static void test_pivot_refusal(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g72b_av_pivot", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g72b_cmd turn1[2][2] = {{MV(0, 2u), MV(0, 3u)}, {MV(1, NO), MV(3, 0u)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, b->boundary_kind, DUOFORGE_BOUNDARY_PIVOT);
    for (uint32_t player = 0u; player < DUOFORGE_SIDE_COUNT; ++player) {
        uint32_t causes = 0u;
        DF_CHECK_EQ_U64(t, duoforge_battle_public_causes(ctx, b, player, &causes), DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, causes & DUOFORGE_PUBLIC_CAUSE_RAISED_THIS_TURN, DUOFORGE_PUBLIC_CAUSE_RAISED_THIS_TURN);
        duoforge_public_state pub;
        DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, b, player, &pub), DUOFORGE_E_UNSUPPORTED);
    }
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g72b");
    test_row(&t);
    test_av_raised_turn(&t);
    test_av_last_turn(&t);
    test_av_switch(&t);
    test_av_control(&t);
    test_dc_dragon(&t);
    test_dc_nondragon(&t);
    test_dc_second(&t);
    test_dc_switch(&t);
    test_dc_focus_energy_guard(&t);
    test_pivot_refusal(&t);
    return df_test_end(&t);
}
