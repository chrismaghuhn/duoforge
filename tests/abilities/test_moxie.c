/*
 * duoforge.abilities.moxie (white-box): step G45 of the content expansion (decision 0015 entry 5ba), Moxie: replays
 * g45_moxie_double, where Krookodile's Earthquake knocks out two foes at once and its Attack stage rises by 2 (the number of
 * faints).
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

/* Moxie: after the first turn, Krookodile (side 0, position 0) knocked out two foes at once: Attack +2. */
static void check_moxie(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = df_conf_replay_by_name(t, ctx, "g45_moxie_double", 2u);
    if (b == NULL) {
        return;
    }
    DF_CHECK_EQ_U64(t, b->sides[0].positions[0].stages[G45_ATK], 8u);
    /* both foes of the batch are down (members 0 and 1 of side 1: Pikachu and Raichu) */
    DF_CHECK_EQ_U64(t, b->sides[1].members[0].hp, 0u);
    DF_CHECK_EQ_U64(t, b->sides[1].members[1].hp, 0u);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.moxie");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_moxie(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
