/*
 * duoforge.state.pool_g58 (white-box): step G58 of the content expansion (decision 0015 item 5ax), Phantom Force.
 *
 * The behaviour is replayed by duoforge.reference.conformance_pool_data: nineteen recorded battles (g58_* under "data": "pool")
 * cover the charge turn, the locked turn, the miss of a second charging user, No Guard on the target and the user, a Poison-type
 * and a non-Poison Toxic, the breaks of Protect, Quick Guard, Wide Guard and Spiky Shield (and Feint's own break of a Spiky
 * Shield), Coaching, Earthquake, Choice Scarf's lock, flinches, the faint of a charging user, the drag of a charging user, the
 * retarget after a faint, and the first result after an invulnerable miss (Stomping Tantrum).
 *
 * This file checks what the tables and the support gate say about the move (the row, its handler id, its flags, and that Protect
 * does not stop it), and the reset of the protect variant on the break (decision 0015 5ax, mutant M14): the residual clears the
 * variant at the end of a turn, so the reset is visible only at a boundary inside the turn. The battle is the recorded
 * g58_phantom_spiky_break: Glimmora's Eject Button switches it out after the Phantom Force hit, so the step stops at a
 * mid-turn switch boundary, and there the Spiky Shield variant must already be zero and the state must pass the invariants.
 * Power Herb has no row in the pool tables (its ChargeMove skip, data/items.ts:4776-4783, is not modelled), so no team can hold it.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/closure_tables.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/invariants.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

static void test_row(df_test *t)
{
    const dfi_move_data *m = &dfi_pool_moves[DFI_MOVE_PHANTOMFORCE];
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_PHANTOM_FORCE, DFI_SPECIAL_SUBSTITUTE + 1u); /* after Substitute (G60, 89) in the batch merge */
    DF_CHECK_EQ_U64(t, m->special, DFI_SPECIAL_PHANTOM_FORCE);
    DF_CHECK_EQ_U64(t, m->base_power, 90u);
    DF_CHECK_EQ_U64(t, m->accuracy, 100u);
    DF_CHECK_EQ_U64(t, m->type, DFI_TYPE_GHOST);
    DF_CHECK_EQ_U64(t, m->category, DFI_CATEGORY_PHYSICAL);
    DF_CHECK_EQ_U64(t, m->priority, DFI_PRIORITY_BIAS);
    /* contact and charge (the two-turn flag); no protect flag, so Protect does not stop the move (checkMoveBypassesProtect) */
    DF_CHECK(t, (m->flags & DFI_MOVE_FLAG_CONTACT) != 0u);
    DF_CHECK(t, (m->flags & DFI_MOVE_FLAG_CHARGE) != 0u);
    DF_CHECK(t, (m->flags & DFI_MOVE_FLAG_PROTECT) == 0u);
    /* the handler is marked, and the unmodelled handler id is the one after Phantom Force */
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_PHANTOMFORCE], 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_DRAGON_CHEER + 1u); /* after Alluring Voice and Dragon Cheer (G72b) */
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

/* One turn's slots: plan[side][slot] = {move slot, target flat position}. */
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

/* The recorded battle g58_phantom_spiky_break, step for step. Turn 1: Annihilape charges Glimmora (flat 2) and Glimmora
 * Toxics Annihilape (flat 0); Protect for the partners. Turn 2: Glimmora's Spiky Shield goes up before the locked hit, which
 * breaks it, and the Eject Button sends Glimmora out mid-turn. */
static void test_spiky_break_reset_at_mid_turn(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    DF_CHECK(t, ctx != NULL);
    const df_conf_battle *cb = find_conf("g58_phantom_spiky_break");
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
    /* [side][slot] = {move slot, target flat}: side 0 Annihilape (slot 0), Golurk (slot 1); side 1 Glimmora (slot 0), Gengar */
    static const uint8_t turn1[2][2][2] = {{{0u, 2u}, {1u, DUOFORGE_TARGET_NONE}}, {{2u, 0u}, {1u, DUOFORGE_TARGET_NONE}}};
    static const uint8_t turn2[2][2][2] = {{{0u, 2u}, {1u, DUOFORGE_TARGET_NONE}}, {{0u, DUOFORGE_TARGET_NONE}, {1u, DUOFORGE_TARGET_NONE}}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    turn_bundle(&bd, b, turn2);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    /* the Eject Button's switch is pending: the step stopped inside the turn, before the residual cleared the variant */
    DF_CHECK(t, b->boundary_kind != DUOFORGE_BOUNDARY_TURN);
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    /* the break reset the protect variant of Glimmora's position (flat 2: side 1, position 0) with its volatile */
    DF_CHECK_EQ_U64(t, b->tail.sides[1].positions[0].protect_kind, 0u);
    DF_CHECK(t, ((uint32_t)b->sides[1].positions[0].flags & DFI_VOL_PROTECT) == 0u);
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g58");
    test_row(&t);
    test_spiky_break_reset_at_mid_turn(&t);
    return df_test_end(&t);
}
