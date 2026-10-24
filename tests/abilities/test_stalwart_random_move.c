/*
 * duoforge.abilities.stalwart_random_move (white-box): step G80 of the content expansion (decision 0044; issue 541), Stalwart
 * with a randomNormal move: the original target is the one resolveAction drew when the move was queued
 * (sim/battle-queue.ts:268-273), a draw the engine does not model, so the move is refused (E_UNSUPPORTED) rather than aimed by
 * a draw of its own. No recorded battle reaches it, so Stalwart is set through the tail's ability_now of the Outrage user of
 * fz519_volt_switch_sub.
 *
 * Split by subject from the test of step G80 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include <stdlib.h>

#include <duoforge/duoforge.h>

#include "data/formats/reg-mc/closure_tables.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "codec/state_codec.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"
#define MV(slot, target) {DUOFORGE_SLOT_MOVE, (slot), (target), 0u}
#define NO DUOFORGE_TARGET_NONE

/* One slot's command of a turn: move slot and target flat position. */
typedef struct g80_cmd {
    uint8_t kind;
    uint8_t move_slot;
    uint8_t target;
    uint8_t reserve;
} g80_cmd;

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

static void turn_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b, const g80_cmd cmd[2][2])
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

/* Starts the recorded battle `name` (its context, its battle, the team preview). */
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

/* Stalwart with a randomNormal move (issue 541): the original target is the one resolveAction drew when the move was queued
 * (sim/battle-queue.ts:268-273), a draw the engine does not model, so the move is refused (E_UNSUPPORTED) rather than aimed by a
 * draw of its own. No recorded battle reaches it (its battle would stop there), so Stalwart is set through the tail's ability_now
 * of the Outrage user of fz519_volt_switch_sub (Bastiodon, our slot 1). */
static void test_stalwart_random_refusal(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "fz519_volt_switch_sub", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    const uint32_t member = b->sides[0].positions[1].occupant;
    DF_CHECK(t, member < DUOFORGE_MAX_ROSTER);
    if (member >= DUOFORGE_MAX_ROSTER) {
        finish(ctx, b);
        return;
    }
    b->tail.sides[0].ability_now[member] = (uint16_t)(DFI_ABILITY_STALWART + 1u);
    /* Altaria Protects (move 1), Bastiodon uses Outrage (move 2, randomNormal: no target); the foe's Rotom-Heat aims Eerie
     * Impulse and Garganacl Heavy Slam at our slot 0 (flat 0) */
    static const g80_cmd turn1[2][2] = {{MV(1, NO), MV(2, NO)}, {MV(1, 0u), MV(1, 0u)}};
    turn_bundle(&bd, b, turn1);
    const duoforge_status st = duoforge_battle_step(ctx, b, &bd, &res);
    DF_CHECK_EQ_U64(t, st, DUOFORGE_E_UNSUPPORTED);
    finish(ctx, b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.stalwart_random_move");
    test_stalwart_random_refusal(&t);
    return df_test_end(&t);
}
