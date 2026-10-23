/*
 * duoforge.abilities.keen_eye (white-box): step G51 of the content expansion (Mega batch 4, decision 0015 entry 5bc), Keen Eye,
 * an engine row (dfi_accuracy_check) that the recorded battle g51_keen_eye exercises:
 *
 *   - no forme of the pool with Keen Eye or Big Pecks as a legal ability is a Grass type (Flower Veil, a Grass type's
 *     TryBoost, would race them by Speed, and dfi_boost assumes none exists);
 *   - the Keen Eye holder's ignoreEvasion: in g51_keen_eye the Pidgeot (Keen Eye, no stone) uses Hurricane (accuracy 70) on the
 *     foe Milotic in step 2 and the reference's accuracy draw is 31; with the foe's evasion stage raised by six by hand (the chance
 *     would fall to 23.3 and the draw would miss) the hit stands only if the Keen Eye user ignores the evasion, and the tape of
 *     the step still fits.
 *
 * Split by subject from the test of step G51 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/formulas.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "state/request.h"
#include "support/check.h"
#include "support/conformance_replay.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* Flower Veil (a Grass type's TryBoost) would race Keen Eye and Big Pecks by Speed on a Grass forme with either ability, and
 * dfi_boost assumes none exists: no forme of the pool with Keen Eye or Big Pecks as a legal ability is a Grass type. */
static void check_no_grass_holder(df_test *t)
{
    uint32_t holders = 0u;
    for (uint32_t f = 0u; f < DFI_POOL_FORME_COUNT; ++f) {
        const dfi_forme_legal *l = &dfi_pool_forme_legal[f];
        bool holds = false;
        for (uint32_t k = 0u; k < l->ability_count; ++k) {
            holds = holds || l->abilities[k] == DFI_ABILITY_KEENEYE || l->abilities[k] == DFI_ABILITY_BIGPECKS;
        }
        if (holds) {
            holders += 1u;
            DF_CHECK(t, dfi_pool_formes[f].types[0] != DFI_TYPE_GRASS && dfi_pool_formes[f].types[1] != DFI_TYPE_GRASS);
        }
    }
    DF_CHECK(t, holders >= 1u); /* Pidgeot is one of them */
}

/* 2. The ignoreEvasion of Keen Eye (dfi_accuracy_check). In g51_keen_eye the Pidgeot (Keen Eye, no stone) uses Hurricane (accuracy
 * 70) on the foe Milotic in step 2, and the reference's accuracy draw is 31: a hit with evasion stage 0. The test raises that foe's
 * evasion stage by six by hand (a stage of +6 would cut the chance to 70 x 3 / 9 = 23.3 and the draw 31 would miss), so the hit
 * stands only if the Keen Eye user ignores the evasion. The tape of the step then still fits: the same hit and the same draws. */
static void check_keen_eye_evasion(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = df_conf_find("g51_keen_eye");
    if (!DF_CHECK(t, cb != NULL) || !DF_CHECK(t, cb->step_count > 2u)) {
        return;
    }
    duoforge_battle *b = df_conf_replay_quiet(t, ctx, cb, 2u);
    if (b == NULL) {
        return;
    }
    b->sides[1].positions[0].stages[DFI_STAGE_EVASION] = (uint8_t)DFI_STAGE_MAX; /* +6, biased by 12 */
    static duoforge_event events[DUOFORGE_MAX_EVENTS];
    uint32_t n = 0u;
    if (DF_CHECK(t, df_conf_step_events(ctx, b, &cb->steps[2], events, &n) == DUOFORGE_OK)) {
        uint32_t hits = 0u;
        uint32_t misses = 0u;
        for (uint32_t i = 0u; i < n; ++i) {
            if (events[i].kind == DUOFORGE_EVENT_DAMAGE && events[i].position == 2u) {
                hits += 1u; /* the foe Milotic (p2a) takes the Hurricane */
            }
            misses += events[i].kind == DUOFORGE_EVENT_MISS ? 1u : 0u;
        }
        DF_CHECK(t, hits >= 1u);
        DF_CHECK_EQ_U64(t, misses, 0u);
    }
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.keen_eye");
    check_no_grass_holder(&t);
    duoforge_context *ctx = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, ctx != NULL)) {
        check_keen_eye_evasion(&t, ctx);
        duoforge_context_destroy(ctx);
    }
    return df_test_end(&t);
}
