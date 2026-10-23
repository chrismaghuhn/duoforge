/*
 * duoforge.moves.quick_guard_view (white-box): step G54 of the content expansion (decision 0015, the moves batch; decision
 * 0029), Quick Guard's side flag reaches the view: the tail's quick_guard of one side sets that side's
 * DUOFORGE_SIDE_GUARD_QUICK_GUARD bit in guard_flags of the view extension, and no other side's.
 *
 * Split by subject from the test of step G54 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/moves/multihit.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/conformance_replay.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* Quick Guard's side flag reaches the view: the tail's quick_guard of one side sets its guard bit and no other side's. */
static void check_guard_flag(df_test *t, duoforge_context *ctx)
{
    const df_conf_battle *cb = df_conf_find("g54_quick_guard_a");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    duoforge_battle_setup setup;
    df_conf_build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return;
    }
    duoforge_observation_ext ext;
    DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, 0u, &ext) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, ext.sides[0].guard_flags & DUOFORGE_SIDE_GUARD_QUICK_GUARD, 0u);
    b->tail.sides[0].quick_guard = 1u;
    DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, 0u, &ext) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, ext.sides[0].guard_flags, DUOFORGE_SIDE_GUARD_QUICK_GUARD);
    DF_CHECK_EQ_U64(t, ext.sides[1].guard_flags, 0u);
    b->tail.sides[0].quick_guard = 0u;
    b->tail.sides[1].quick_guard = 1u;
    DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, 1u, &ext) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, ext.sides[0].guard_flags, 0u);
    DF_CHECK_EQ_U64(t, ext.sides[1].guard_flags, DUOFORGE_SIDE_GUARD_QUICK_GUARD);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.moves.quick_guard_view");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_guard_flag(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
