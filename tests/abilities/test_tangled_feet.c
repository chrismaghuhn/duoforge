/*
 * duoforge.abilities.tangled_feet (white-box): batch A2a of the Champions-100 track (decision 0015 entry 5dy), Tangled Feet:
 *
 *   - a multi-accuracy move's later hit at a confused Tangled Feet holder (a2a_cover_c with Gardevoir's Will-O-Wisp slot holding
 *     Triple Axel, which it learns) is refused (E_UNSUPPORTED, the later-hit refusal), the battle unchanged; the control plays;
 *   - Tangled Feet's 2048 and Compound Eyes' 5325 (both priority -1) give the same chain in both orders, from 4096 and from
 *     Gravity's 6840 (the accuracy chain applies them in one fixed order).
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

/* Tangled Feet's later-hit refusal: a2a_cover_c step 4 (Gardevoir's Will-O-Wisp at Pidgeot) with Triple Axel in that slot,
 * Gardevoir at +6 accuracy (its first hit lands: 90 x 0.5 x 3 > 100) and burned instead of paralysed (no full paralysis draw; its
 * traced Quick Feet keeps it first), and Pidgeot confused (3 turns; at 88 of 190 HP it stands after the 20-power first hit). With
 * Tangled Feet the second hit's ModifyAccuracy is refused (E_UNSUPPORTED, the battle unchanged); with Keen Eye in its place the step plays. The
 * step runs on the battle's own generator. */
static void check_tangled_feet_later_hit(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = df_conf_find("a2a_cover_c");
    if (!DF_CHECK(t, cb != NULL && cb->step_count > 4u)) {
        return;
    }
    duoforge_battle *b = df_conf_replay_battle(t, ctx, cb, 4u);
    if (b == NULL) {
        return;
    }
    const uint32_t gard = df_conf_member_of(b, 1u, DFI_FORME_GARDEVOIR);
    const uint32_t pidgeot = df_conf_member_of(b, 0u, DFI_FORME_PIDGEOT);
    uint32_t gard_slot = 2u;
    uint32_t pidgeot_slot = 2u;
    for (uint32_t p = 0u; p < 2u; ++p) {
        gard_slot = b->sides[1].positions[p].occupant == gard ? p : gard_slot;
        pidgeot_slot = b->sides[0].positions[p].occupant == pidgeot ? p : pidgeot_slot;
    }
    if (!DF_CHECK(t, gard < DUOFORGE_MAX_ROSTER && pidgeot < DUOFORGE_MAX_ROSTER && gard_slot < 2u && pidgeot_slot < 2u)) {
        duoforge_battle_destroy(b);
        return;
    }
    duoforge_decision_bundle bd;
    df_conf_bundle_of(&cb->steps[4], b, &bd);
    for (uint32_t variant = 0u; variant < 2u; ++variant) {
        duoforge_battle *x = NULL;
        if (!DF_CHECK(t, duoforge_battle_clone(ctx, b, &x) == DUOFORGE_OK)) {
            continue;
        }
        dfi_member *gm = &x->sides[1].members[gard];
        uint32_t pp_max = 0u; /* Triple Axel has Psychic's 10 PP: the slot takes Psychic's maximum */
        for (uint32_t k = 0u; k < gm->move_count; ++k) {
            pp_max = gm->moves[k].move_id == DFI_MOVE_PSYCHIC ? gm->moves[k].pp_max : pp_max;
        }
        DF_CHECK(t, pp_max != 0u);
        for (uint32_t k = 0u; k < gm->move_count; ++k) {
            if (gm->moves[k].move_id == DFI_MOVE_WILLOWISP) {
                gm->moves[k].move_id = (uint16_t)DFI_MOVE_TRIPLEAXEL;
                gm->moves[k].pp_max = (uint8_t)pp_max;
                gm->moves[k].pp = (uint8_t)pp_max;
            }
        }
        gm->status = (uint8_t)DFI_STATUS_BRN;
        gm->status_counter = 0u;
        x->sides[1].positions[gard_slot].stages[DFI_STAGE_ACCURACY] = (uint8_t)DFI_BIAS6_MAX;
        x->sides[0].positions[pidgeot_slot].confusion_turns = 3u;
        if (variant == 0u) {
            x->tail.sides[0].ability_now[pidgeot] = (uint16_t)AB(KEENEYE);
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

/* 4. The priority -1 accuracy group: Tangled Feet's 2048 and Compound Eyes' 5325 in both orders. */
static void check_dyadic_order(df_test *t)
{
    static const uint32_t starts[] = {4096u, 6840u};
    for (size_t i = 0; i < sizeof starts / sizeof starts[0]; ++i) {
        uint32_t a = 0u;
        uint32_t b = 0u;
        DF_CHECK(t, dfi_chain_modify(starts[i], 5325u, &a) && dfi_chain_modify(a, 2048u, &a));
        DF_CHECK(t, dfi_chain_modify(starts[i], 2048u, &b) && dfi_chain_modify(b, 5325u, &b));
        DF_CHECK_EQ_U64(t, a, b);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.tangled_feet");
    check_dyadic_order(&t);
    duoforge_context *kp = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, kp != NULL)) {
        check_tangled_feet_later_hit(&t, kp);
        duoforge_context_destroy(kp);
    }
    return df_test_end(&t);
}
