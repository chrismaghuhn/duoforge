/*
 * duoforge.state.pool_g72 (white-box): step G72 of the content expansion (decision 0015 item 5ce), the open evidence gap of
 * the Yawn rules (G31's clause (3), G58's semi-invulnerable exemptions).
 *
 * The behaviour is replayed by duoforge.reference.conformance_pool_data: two recorded battles (g72_* under "data": "pool")
 * cover the two halves of the question. In g72_yawn_charger_electric, Golurk (No Guard, grounded) charges Phantom Force
 * under Electric Terrain and Sylveon yawns it on the locked turn before the hit: the Yawn volatile starts, with no
 * -activate line, because the Electric Terrain refusal is skipped for a semi-invulnerable target (data/moves.ts:4525). On
 * the next turn Golurk charges again, and the Yawn's sleep (the residual of that turn) is not refused either (data/moves.ts:4517),
 * so Golurk falls asleep while it is still semi-invulnerable. In g72_yawn_charger_miss, Annihilape (no No Guard) charges and
 * the yawn of the locked turn is a miss (the Invulnerability step, before any Yawn or terrain rule).
 *
 * This file checks the state after the steps that matter: the volatile after the yawn, the sleep after the residual, and
 * the miss (no volatile, no status). The mutants of decision 0015 5ce (the `!dfi_semi_invulnerable` of dfi_yawn and of the
 * Electric sleep refusal) are caught by the first battle here and by duoforge.reference.conformance_pool_data.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/closure_tables.h"
#include "data/pool_tables.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/invariants.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

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

/* One turn's slots: plan[side][slot] = {move slot (0-based), target flat position}. */
static void turn_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b, const uint8_t plan[2][2][2])
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
            c->slots[slot].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
            c->slots[slot].move_slot = plan[side][slot][0];
            c->slots[slot].target = plan[side][slot][1];
        }
    }
}

/* g72_yawn_charger_electric: the recorded battle's choices. Flat positions: side 0 Pincurchin 0, Golurk 1; side 1 Sylveon 2,
 * Salamence 3. Golurk's Phantom Force (move slot 0) targets Salamence (flat 3); Sylveon's Yawn (move slot 0) targets Golurk
 * (flat 1); Protect is move slot 1 for Pincurchin, Sylveon and Salamence. Turn 1: Golurk charges (Protect for the rest).
 * Turn 2: Sylveon, faster than the charging Golurk, yawns it before the locked hit. Turn 3: Golurk charges again. */
static void test_yawn_on_charger_under_electric(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    DF_CHECK(t, ctx != NULL);
    const df_conf_battle *cb = find_conf("g72_yawn_charger_electric");
    DF_CHECK(t, cb != NULL);
    if (ctx == NULL || cb == NULL) {
        duoforge_context_destroy(ctx);
        return;
    }
    duoforge_battle_setup s;
    setup_from(cb, &s);
    duoforge_battle *b = df_make_battle(ctx, &s);
    DF_CHECK(t, b != NULL);
    if (b == NULL) {
        duoforge_context_destroy(ctx);
        return;
    }
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    team_bundle(&bd, b);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);

    static const uint8_t turn1[2][2][2] = {{{1u, DUOFORGE_TARGET_NONE}, {0u, 3u}}, {{1u, DUOFORGE_TARGET_NONE}, {1u, DUOFORGE_TARGET_NONE}}};
    static const uint8_t turn2[2][2][2] = {{{1u, DUOFORGE_TARGET_NONE}, {0u, 3u}}, {{0u, 1u}, {0u, 0u}}};
    static const uint8_t turn3[2][2][2] = {{{1u, DUOFORGE_TARGET_NONE}, {0u, 3u}}, {{1u, DUOFORGE_TARGET_NONE}, {1u, DUOFORGE_TARGET_NONE}}};

    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    /* Golurk (side 0, roster 1) is charging: the volatile of the charge is up and no Yawn is on it yet */
    DF_CHECK_EQ_U64(t, b->tail.sides[0].positions[1].yawn_turns, 0u);
    DF_CHECK_EQ_U64(t, b->sides[0].members[1].status, DFI_STATUS_NONE);

    turn_bundle(&bd, b, turn2);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    /* the Yawn of the locked turn hit the charging No Guard Golurk: no Electric refusal, the volatile starts (duration 2,
     * the residual of turn 2 leaves 1) */
    DF_CHECK_EQ_U64(t, b->tail.sides[0].positions[1].yawn_turns, 1u);
    DF_CHECK_EQ_U64(t, b->sides[0].members[1].status, DFI_STATUS_NONE);
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);

    turn_bundle(&bd, b, turn3);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    /* the residual of turn 3 ends the Yawn: the sleep is not refused, although Golurk charges again (still semi-invulnerable,
     * the residual sees the charge up) */
    DF_CHECK_EQ_U64(t, b->tail.sides[0].positions[1].yawn_turns, 0u);
    DF_CHECK_EQ_U64(t, b->sides[0].members[1].status, DFI_STATUS_SLP);
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

/* g72_yawn_charger_miss: Annihilape (no No Guard) charges on turn 1 and is still charging when Sylveon, faster, yawns it on
 * turn 2: the Invulnerability step misses the status move (no volatile, no status, no Electric line). */
static void test_yawn_missed_charger(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    DF_CHECK(t, ctx != NULL);
    const df_conf_battle *cb = find_conf("g72_yawn_charger_miss");
    DF_CHECK(t, cb != NULL);
    if (ctx == NULL || cb == NULL) {
        duoforge_context_destroy(ctx);
        return;
    }
    duoforge_battle_setup s;
    setup_from(cb, &s);
    duoforge_battle *b = df_make_battle(ctx, &s);
    DF_CHECK(t, b != NULL);
    if (b == NULL) {
        duoforge_context_destroy(ctx);
        return;
    }
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    team_bundle(&bd, b);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);

    static const uint8_t turn1[2][2][2] = {{{1u, DUOFORGE_TARGET_NONE}, {0u, 3u}}, {{1u, DUOFORGE_TARGET_NONE}, {1u, DUOFORGE_TARGET_NONE}}};
    static const uint8_t turn2[2][2][2] = {{{1u, DUOFORGE_TARGET_NONE}, {0u, 3u}}, {{0u, 1u}, {1u, DUOFORGE_TARGET_NONE}}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    turn_bundle(&bd, b, turn2);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    /* the miss: Annihilape (side 0, roster 1) takes no volatile and no status; the Phantom Force of the locked turn ran */
    DF_CHECK_EQ_U64(t, b->tail.sides[0].positions[1].yawn_turns, 0u);
    DF_CHECK_EQ_U64(t, b->sides[0].members[1].status, DFI_STATUS_NONE);
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g72");
    test_yawn_on_charger_under_electric(&t);
    test_yawn_missed_charger(&t);
    return df_test_end(&t);
}
