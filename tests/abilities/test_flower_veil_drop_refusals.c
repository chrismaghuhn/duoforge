/*
 * duoforge.abilities.flower_veil_drop_refusals (white-box): batch A2a of the Champions-100 track (decision 0015 entry 5dy), the
 * refusals that no campaign battle reaches: an Illuminate or White Smoke holder that is a Grass type next to a Flower Veil
 * holder (two TryBoost handlers for one drop; g12_flower_veil_a and g31_yawn_flower_veil with the protected Rillaboom's ability
 * changed, Sylveon's Yawn slot holding Mud-Slap, which it learns) is E_UNSUPPORTED (r->deferred), the battle unchanged; the
 * controls play.
 *
 * Split by subject from the test of step A2a (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/abilities/current.h"
#include "core/modifier.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/observation_digest.h"
#include "state/request.h"
#include "support/check.h"
#include "support/conformance_replay.h"
#include "support/fixtures.h"
#include "support/pool.h"
#define AB(x) (1u + DFI_ABILITY_##x)

/* 3. The refusals. (a) White Smoke on the protected Rillaboom of g12_flower_veil_a (step 1, the reference's tape: the drops are the
 * recorded ones). */
static void check_flower_veil_refusals(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = df_conf_find("g12_flower_veil_a");
    if (!DF_CHECK(t, cb != NULL && cb->step_count > 1u)) {
        return;
    }
    duoforge_battle *b = df_conf_replay_battle(t, ctx, cb, 1u);
    if (b == NULL) {
        return;
    }
    const uint32_t rilla = df_conf_member_of(b, 0u, DFI_FORME_RILLABOOM);
    if (!DF_CHECK(t, rilla < DUOFORGE_MAX_ROSTER)) {
        duoforge_battle_destroy(b);
        return;
    }
    const df_conf_step *st = &cb->steps[1];
    duoforge_decision_bundle bd;
    df_conf_bundle_of(st, b, &bd);
    /* (a) White Smoke on the protected Rillaboom: Snarl's and Parting Shot's drops meet Flower Veil and White Smoke. */
    for (uint32_t variant = 0u; variant < 2u; ++variant) {
        duoforge_battle *x = NULL;
        if (!DF_CHECK(t, duoforge_battle_clone(ctx, b, &x) == DUOFORGE_OK)) {
            continue;
        }
        if (variant == 1u) {
            x->tail.sides[0].ability_now[rilla] = (uint16_t)AB(WHITESMOKE);
        }
        duoforge_battle *before = NULL;
        DF_CHECK(t, duoforge_battle_clone(ctx, x, &before) == DUOFORGE_OK);
        duoforge_step_result res;
        uint32_t used = 0u;
        const duoforge_status s = dfi_battle_step_tape(ctx, x, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (variant == 0u) {
            DF_CHECK(t, s == DUOFORGE_OK); /* the control: the recorded step */
        } else {
            DF_CHECK(t, s == DUOFORGE_E_UNSUPPORTED);
            bool equal = false;
            DF_CHECK(t, before != NULL && duoforge_battle_equal(ctx, x, before, &equal) == DUOFORGE_OK && equal);
        }
        duoforge_battle_destroy(before);
        duoforge_battle_destroy(x);
    }
    duoforge_battle_destroy(b);
}

/* (b) Illuminate on the protected Rillaboom of g31_yawn_flower_veil (step 1): Sylveon's Yawn slot holds Mud-Slap, whose accuracy
 * drop (a secondary of chance 100) meets Flower Veil and Illuminate. The step runs on the battle's own generator (the changed move
 * draws what it draws). The control keeps Rillaboom's own ability. */
static void check_illuminate_flower_veil(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = df_conf_find("g31_yawn_flower_veil");
    if (!DF_CHECK(t, cb != NULL && cb->step_count > 1u)) {
        return;
    }
    duoforge_battle *b = df_conf_replay_battle(t, ctx, cb, 1u);
    if (b == NULL) {
        return;
    }
    const uint32_t rilla = df_conf_member_of(b, 1u, DFI_FORME_RILLABOOM);
    const uint32_t sylveon = df_conf_member_of(b, 0u, DFI_FORME_SYLVEON);
    if (!DF_CHECK(t, rilla < DUOFORGE_MAX_ROSTER && sylveon < DUOFORGE_MAX_ROSTER)) {
        duoforge_battle_destroy(b);
        return;
    }
    duoforge_decision_bundle bd;
    df_conf_bundle_of(&cb->steps[1], b, &bd);
    for (uint32_t variant = 0u; variant < 2u; ++variant) {
        duoforge_battle *x = NULL;
        if (!DF_CHECK(t, duoforge_battle_clone(ctx, b, &x) == DUOFORGE_OK)) {
            continue;
        }
        dfi_member *sm = &x->sides[0].members[sylveon];
        for (uint32_t k = 0u; k < sm->move_count; ++k) {
            if (sm->moves[k].move_id == DFI_MOVE_YAWN) {
                sm->moves[k].move_id = (uint16_t)DFI_MOVE_MUDSLAP;
            }
        }
        if (variant == 1u) {
            x->tail.sides[1].ability_now[rilla] = (uint16_t)AB(ILLUMINATE);
        }
        DF_CHECK(t, duoforge_battle_check(ctx, x) == DUOFORGE_OK);
        duoforge_battle *before = NULL;
        DF_CHECK(t, duoforge_battle_clone(ctx, x, &before) == DUOFORGE_OK);
        duoforge_step_result res;
        const duoforge_status s = duoforge_battle_step(ctx, x, &bd, &res);
        if (variant == 0u) {
            DF_CHECK(t, s == DUOFORGE_OK);
        } else {
            DF_CHECK(t, s == DUOFORGE_E_UNSUPPORTED);
            bool equal = false;
            DF_CHECK(t, before != NULL && duoforge_battle_equal(ctx, x, before, &equal) == DUOFORGE_OK && equal);
        }
        duoforge_battle_destroy(before);
        duoforge_battle_destroy(x);
    }
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.flower_veil_drop_refusals");
    duoforge_context *kp = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, kp != NULL)) {
        check_flower_veil_refusals(&t, kp);
        check_illuminate_flower_veil(&t, kp);
        duoforge_context_destroy(kp);
    }
    return df_test_end(&t);
}
