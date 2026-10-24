/*
 * duoforge.abilities.life_dew_water_absorb (white-box): batch A2a of the Champions-100 track (decision 0015 entry 5dy), Life
 * Dew (a Water heal move of the user and its ally) at an ally with Water Absorb (g32_life_dew step 3 with Kingambit's ability
 * changed). A2a refused it (the heal path did not run the TryHit abilities); since decision 0015 entry 5ed (issue 641) the heal
 * path runs them, so the step plays and the ally's line is Water Absorb's (a heal with [of] the user, or -immune at full HP;
 * the recorded battle is life_dew_water_absorb, the white-box test duoforge.abilities.life_dew_try_hit). The user's own Water
 * Absorb is not asked (target === source) and the control plays.
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
    for (uint32_t variant = 0u; variant < 3u; ++variant) {
        duoforge_battle *x = NULL;
        if (!DF_CHECK(t, duoforge_battle_clone(ctx, b, &x) == DUOFORGE_OK)) {
            continue;
        }
        if (variant == 1u) {
            x->tail.sides[0].ability_now[ally] = (uint16_t)AB(WATERABSORB); /* the ally: its TryHit runs (5ed) */
        } else if (variant == 2u) {
            x->tail.sides[0].ability_now[milotic] = (uint16_t)AB(WATERABSORB); /* the user itself: not asked */
        }
        DF_CHECK(t, duoforge_battle_check(ctx, x) == DUOFORGE_OK);
        static df_conf_run run;
        df_conf_run_step(ctx, x, st, &run);
        DF_CHECK(t, run.status == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, run.used, st->tape_len);
        /* The ally's line from Water Absorb: one in the ally variant (5ed: no longer refused), none otherwise. */
        uint32_t absorbed = 0u;
        for (uint32_t i = 0u; i < run.count; ++i) {
            const duoforge_event *e = &run.events[i];
            absorbed += (e->kind == DUOFORGE_EVENT_HEAL || e->kind == DUOFORGE_EVENT_IMMUNE) && e->position == 1u &&
                                e->cause == DUOFORGE_CAUSE_ABILITY && e->id2 == AB(WATERABSORB)
                            ? 1u
                            : 0u;
        }
        DF_CHECK_EQ_U64(t, absorbed, variant == 1u ? 1u : 0u);
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
