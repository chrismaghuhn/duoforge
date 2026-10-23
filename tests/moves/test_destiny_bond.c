/*
 * duoforge.moves.destiny_bond (white-box): step G76 of the content expansion (decision 0015 5cg), Destiny Bond's flag bit after
 * the steps that matter of the recorded g76_db_* battles: the holder's next move ends it (the attempt, not the turn); a second
 * use in a row fails and ends the volatile, a third starts it; a holder knocked out by a foe's move takes the attacker with it,
 * and the holder's flag ends with its faint. The behaviour is compared with the reference by
 * duoforge.reference.conformance_pool_data. Flat positions: side 0 slots 0 and 1 (flat 0, 1), side 1 (flat 2, 3); roster
 * members of side 1: Golurk 0, Kingambit 1, Pincurchin 2.
 *
 * Split by subject from the test of step G76 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "data/formats/reg-mc/closure_tables.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/invariants.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"
#define MV(slot, target) {DUOFORGE_SLOT_MOVE, (slot), (target), 0u}
#define NO DUOFORGE_TARGET_NONE

/* One slot's command of a turn: a move (move slot and target flat position) or a switch (the reserve's roster index). */
typedef struct g76_cmd {
    uint8_t kind;      /* DUOFORGE_SLOT_MOVE or DUOFORGE_SLOT_SWITCH */
    uint8_t move_slot; /* 0-based */
    uint8_t target;    /* flat position, DUOFORGE_TARGET_NONE for none */
    uint8_t reserve;   /* roster index, for a switch */
} g76_cmd;

/* The position flags of tail rev 5 (battle_internal.h) of a flat position. */
static uint32_t flags_of(const duoforge_battle *b, uint32_t flat)
{
    return (uint32_t)b->tail.sides[flat / 2u].positions[flat % 2u].position_flags;
}

static bool destiny_bond_of(const duoforge_battle *b, uint32_t flat)
{
    return (flags_of(b, flat) & DFI_POSFLAG_DESTINY_BOND) != 0u;
}

static uint32_t hp_of(const duoforge_battle *b, uint32_t side, uint32_t roster)
{
    return (uint32_t)b->sides[side].members[roster].hp;
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
static void turn_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b, const g76_cmd cmd[2][2])
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

/* db_clear: Destiny Bond is up after turn 1; Gardevoir's Shadow Ball on turn 2 ends it (the attempt, not the turn). */
static void test_db_clear(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g76_db_clear", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    DF_CHECK(t, !destiny_bond_of(b, 0u));
    static const g76_cmd turn1[2][2] = {{MV(0, NO), MV(0, 2u)}, {MV(1, NO), MV(1, NO)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, destiny_bond_of(b, 0u));
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    static const g76_cmd turn2[2][2] = {{MV(1, 2u), MV(0, 2u)}, {MV(1, NO), MV(1, NO)}};
    turn_bundle(&bd, b, turn2);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, !destiny_bond_of(b, 0u));
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

/* db_consecutive: the second use fails and ends the volatile (removeVolatile in onPrepareHit), the third use starts it. */
static void test_db_consecutive(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g76_db_consecutive", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g76_cmd turn1[2][2] = {{MV(0, NO), MV(1, NO)}, {MV(1, NO), MV(1, NO)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, destiny_bond_of(b, 0u));
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, !destiny_bond_of(b, 0u));
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, destiny_bond_of(b, 0u));
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

/* db_ko: Gardevoir's Destiny Bond is up when Golurk's Earthquake and then Kingambit's Iron Head KO it; Kingambit faints with it
 * (-activate move: Destiny Bond, then its faint), and the holder's flag ends with its faint. */
static void test_db_ko(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g76_db_ko", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g76_cmd turn1[2][2] = {{MV(0, NO), MV(1, NO)}, {MV(2, NO), MV(3, 0u)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, hp_of(b, 0u, 0u), 0u); /* Gardevoir fainted */
    DF_CHECK_EQ_U64(t, hp_of(b, 1u, 1u), 0u); /* Kingambit fainted with it */
    DF_CHECK(t, !destiny_bond_of(b, 0u));
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.moves.destiny_bond");
    test_db_clear(&t);
    test_db_consecutive(&t);
    test_db_ko(&t);
    return df_test_end(&t);
}
