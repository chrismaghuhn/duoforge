/*
 * duoforge.interactions.sniper_chain_order (white-box): step G77 of the content expansion (decision 0015, item 5bq), the
 * ModifyDamage chain with Sniper: the chain of a critical hit with Life Orb, a resist berry, Solid Rock and Sniper does not
 * commute, so the engine refuses that hit (E_UNSUPPORTED; the reference orders those four by speed, a tie), and the sets that
 * commute are chained.
 *
 * Split by subject from the test of step G77 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/damage_chain.h"
#include "combat/turn.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* ---- the commutation of the chain with Sniper: the sets the engine refuses, and the ones it chains */
static void check_commute(df_test *t)
{
    /* Life Orb 5324, a resist berry 2048, Solid Rock 3072 and Sniper 6144 on one critical super-effective hit: the chain takes
     * 2995 or 2996 by the order of its four factors, so the engine refuses the hit */
    const uint32_t refused[4] = {5324u, 2048u, 3072u, 6144u};
    DF_CHECK(t, !dfi_mods_commute(refused, 4u));
    /* Life Orb with Sniper and a resist berry (no Solid Rock, Friend Guard or Glaive Rush): every order gives 3993 */
    const uint32_t chains[3] = {5324u, 6144u, 2048u};
    DF_CHECK(t, dfi_mods_commute(chains, 3u));
    /* a resist berry, Glaive Rush and Sniper: every order gives 6144 */
    const uint32_t berry_glaive[3] = {6144u, 2048u, 8192u};
    DF_CHECK(t, dfi_mods_commute(berry_glaive, 3u));
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.interactions.sniper_chain_order");
    check_commute(&t);
    return df_test_end(&t);
}
