/*
 * duoforge.abilities.regenerator_pivot (white-box): step G51 of the content expansion (decision 0015 entry 5bc; the fix of the
 * G39 Regenerator row), Regenerator on a PIVOT switch-out: in g51_dragalgite Dragalge-Mega uses Flip Turn at step 2 and leaves
 * at step 3 (the answer to the PIVOT, `switch 3`); Regenerator heals it by a third before the switch, and the opponent's
 * knowledge of its HP shows the healed percent.
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

/* 3. Regenerator on a PIVOT switch-out (step G51 rework; the fix of the G39 Regenerator row, decision 0015 5bc). In g51_dragalgite
 * Dragalge-Mega uses Flip Turn at step 2 and leaves at step 3 (the answer to the PIVOT, `switch 3`): Regenerator heals it by a
 * third before the switch, and the opponent's knowledge of its HP must show the healed percent. */
static void check_regenerator_pivot(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = df_conf_find("g51_dragalgite");
    if (!DF_CHECK(t, cb != NULL) || !DF_CHECK(t, cb->step_count > 3u)) {
        return;
    }
    /* The state at the pivot request (after step 2, Flip Turn): Dragalge has not left yet, so it has not healed. The own view is
     * exact, the opponent's view is the percent display of the same HP (35 of 172 is 20 percent). */
    duoforge_battle *b = df_conf_replay_quiet(t, ctx, cb, 3u);
    if (b == NULL) {
        return;
    }
    duoforge_observation own;
    duoforge_observation foe;
    if (DF_CHECK(t, duoforge_battle_observe(ctx, b, 0u, &own) == DUOFORGE_OK) &&
        DF_CHECK(t, duoforge_battle_observe(ctx, b, 1u, &foe) == DUOFORGE_OK)) {
        DF_CHECK_EQ_U64(t, own.sides[0].members[0].hp, 35u);
        DF_CHECK_EQ_U64(t, foe.sides[0].members[0].hp_kind, DUOFORGE_HP_PERCENT);
        DF_CHECK_EQ_U64(t, foe.sides[0].members[0].hp, 20u);
    }
    /* The answer (`switch 3`): the Regenerator heal of a third (172 / 3 = 57, to 92) comes before the switch. The opponent's
     * knowledge must show the healed percent (92 of 172 is 53 percent), not the value before the heal. */
    static duoforge_event events[DUOFORGE_MAX_EVENTS];
    uint32_t n = 0u;
    if (DF_CHECK(t, df_conf_step_events(ctx, b, &cb->steps[3], events, &n) == DUOFORGE_OK)) {
        uint32_t heals = 0u;
        for (uint32_t i = 0u; i < n; ++i) {
            if (events[i].kind == DUOFORGE_EVENT_HEAL && events[i].cause == DUOFORGE_CAUSE_ABILITY &&
                events[i].id2 == 1u + DFI_ABILITY_REGENERATOR) {
                heals += 1u;
            }
        }
        DF_CHECK_EQ_U64(t, heals, 1u);
    }
    if (DF_CHECK(t, duoforge_battle_observe(ctx, b, 0u, &own) == DUOFORGE_OK) &&
        DF_CHECK(t, duoforge_battle_observe(ctx, b, 1u, &foe) == DUOFORGE_OK)) {
        DF_CHECK_EQ_U64(t, own.sides[0].members[0].hp, 92u);
        DF_CHECK_EQ_U64(t, foe.sides[0].members[0].hp_kind, DUOFORGE_HP_PERCENT);
        DF_CHECK_EQ_U64(t, foe.sides[0].members[0].hp, 53u);
    }
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.regenerator_pivot");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, ctx != NULL)) {
        check_regenerator_pivot(&t, ctx);
        duoforge_context_destroy(ctx);
    }
    return df_test_end(&t);
}
