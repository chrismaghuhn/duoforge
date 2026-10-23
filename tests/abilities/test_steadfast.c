/*
 * duoforge.abilities.steadfast (white-box): step G45 of the content expansion (decision 0015 entry 5ba), Steadfast: replays
 * g45_steadfast to the turn where the flinch of Machamp (a Fake Out in the first turn) raises its Speed stage by 1.
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

/* Steadfast: after the team step and the first turn, Machamp (side 1, position 0) was flinched by Fake Out: Speed +1, and it did
 * not move that turn. */
static void check_steadfast(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = df_conf_replay_by_name(t, ctx, "g45_steadfast", 2u);
    if (b == NULL) {
        return;
    }
    DF_CHECK_EQ_U64(t, b->sides[1].positions[0].stages[G45_SPE], 7u);
    DF_CHECK_EQ_U64(t, b->sides[1].positions[0].stages[G45_ATK], 6u);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.steadfast");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_steadfast(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
