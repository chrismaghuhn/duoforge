/*
 * duoforge.abilities.telepathy (white-box): step G45 of the content expansion (decision 0015 entry 5ba), Telepathy: replays
 * g45_telepathy, where the Earthquake of Garchomp does not reach Medicham (its ally, Telepathy): Medicham keeps its HP.
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
/* Telepathy: the Earthquake of Garchomp (side 0, position 0) in the second turn spreads to Medicham (side 0, position 1), which
 * Telepathy stops: its HP is unchanged (the Earthquake would take it without the ability). */
static void check_telepathy(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = df_conf_replay_by_name(t, ctx, "g45_telepathy", 3u);
    if (b == NULL) {
        return;
    }
    const dfi_member *medicham = &b->sides[0].members[b->sides[0].positions[1].occupant];
    DF_CHECK_EQ_U64(t, medicham->hp, medicham->hp_max);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.telepathy");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_telepathy(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
