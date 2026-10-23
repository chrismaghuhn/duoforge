/*
 * duoforge.abilities.weak_armor (white-box): step G45 of the content expansion (decision 0015 entry 5ba), Weak Armor: replays
 * g45_weak_armor, where one Physical hit (Garchomp's Earthquake) lowers Ceruledge's Defense stage by 1 and raises its Speed
 * stage by 2.
 *
 * Split by subject from the test of step G45 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/turn.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/conformance_replay.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* The stage indices of dfi_active_slot.stages (biased by 6): atk 0, def 1, spa 2, spd 3, spe 4. */
#define G45_ATK 0u
#define G45_DEF 1u
#define G45_SPE 4u

/* Weak Armor: after the first turn, Ceruledge (side 0, position 0) took one Physical hit: Defense -1, Speed +2. */
static void check_weak_armor(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = df_conf_replay_by_name(t, ctx, "g45_weak_armor", 2u);
    if (b == NULL) {
        return;
    }
    DF_CHECK_EQ_U64(t, b->sides[0].positions[0].stages[G45_DEF], 5u);
    DF_CHECK_EQ_U64(t, b->sides[0].positions[0].stages[G45_SPE], 8u);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.weak_armor");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_weak_armor(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
