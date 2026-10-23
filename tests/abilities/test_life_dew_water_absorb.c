/*
 * duoforge.abilities.life_dew_water_absorb (white-box): batch A2a of the Champions-100 track (decision 0015 entry 5dy), Life
 * Dew (a Water heal move of the user and its ally) at an ally with Water Absorb: the heal path does not run the TryHit
 * abilities, so it is refused before anything changes (g32_life_dew step 3 with Kingambit's ability changed); the user's own
 * Water Absorb is not asked (target === source) and the control plays.
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

/* 5. Life Dew at an ally with Water Absorb (g32_life_dew step 3: Milotic's Life Dew heals Milotic and Kingambit). */
static void check_life_dew(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = df_conf_find("g32_life_dew");
    if (!DF_CHECK(t, cb != NULL && cb->step_count > 3u)) {
        return;
    }
    duoforge_battle *b = df_conf_replay_battle(t, ctx, cb, 3u);
    if (b == NULL) {
        return;
    }
    const uint32_t milotic = df_conf_member_of(b, 0u, DFI_FORME_MILOTIC);
    const uint32_t ally = df_conf_member_of(b, 0u, DFI_FORME_KINGAMBIT);
    if (!DF_CHECK(t, milotic < DUOFORGE_MAX_ROSTER && ally < DUOFORGE_MAX_ROSTER)) {
        duoforge_battle_destroy(b);
        return;
    }
    const df_conf_step *st = &cb->steps[3];
    duoforge_decision_bundle bd;
    df_conf_bundle_of(st, b, &bd);
    for (uint32_t variant = 0u; variant < 3u; ++variant) {
        duoforge_battle *x = NULL;
        if (!DF_CHECK(t, duoforge_battle_clone(ctx, b, &x) == DUOFORGE_OK)) {
            continue;
        }
        if (variant == 1u) {
            x->tail.sides[0].ability_now[ally] = (uint16_t)AB(WATERABSORB); /* the ally: refused */
        } else if (variant == 2u) {
            x->tail.sides[0].ability_now[milotic] = (uint16_t)AB(WATERABSORB); /* the user itself: not asked */
        }
        DF_CHECK(t, duoforge_battle_check(ctx, x) == DUOFORGE_OK);
        duoforge_battle *before = NULL;
        DF_CHECK(t, duoforge_battle_clone(ctx, x, &before) == DUOFORGE_OK);
        duoforge_step_result res;
        uint32_t used = 0u;
        const duoforge_status s = dfi_battle_step_tape(ctx, x, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (variant == 1u) {
            DF_CHECK(t, s == DUOFORGE_E_UNSUPPORTED);
            bool equal = false;
            DF_CHECK(t, before != NULL && duoforge_battle_equal(ctx, x, before, &equal) == DUOFORGE_OK && equal);
        } else {
            DF_CHECK(t, s == DUOFORGE_OK);
            DF_CHECK_EQ_U64(t, used, st->tape_len);
        }
        duoforge_battle_destroy(before);
        duoforge_battle_destroy(x);
    }
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.life_dew_water_absorb");
    duoforge_context *kp = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, kp != NULL)) {
        check_life_dew(&t, kp);
        duoforge_context_destroy(kp);
    }
    return df_test_end(&t);
}
