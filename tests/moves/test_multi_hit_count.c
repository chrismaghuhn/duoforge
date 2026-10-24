/*
 * duoforge.moves.multi_hit_count (white-box): step G54 of the content expansion (decision 0015, the moves batch), the hit count
 * of a 2-to-5 multi-hit move: each draw of DFI_SITE_MULTIHIT_COUNT (random(20)) maps to the Champions sample index by index,
 * with the shares 7, 7, 3 and 3 of two, three, four and five hits.
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
#include "support/fixtures.h"
#include "support/pool.h"

/* The hit count of each draw of DFI_SITE_MULTIHIT_COUNT (random(20)): the Champions sample, index by index, and its shares
 * (seven 2s, seven 3s, three 4s, three 5s). The pin is scripts.ts:440, the same list as battle-actions.ts:870. */
static void check_multihit_weights(df_test *t)
{
    static const uint32_t want[20] = {2u, 2u, 2u, 2u, 2u, 2u, 2u, 3u, 3u, 3u, 3u, 3u, 3u, 3u, 4u, 4u, 4u, 5u, 5u, 5u};
    uint32_t share[6] = {0u, 0u, 0u, 0u, 0u, 0u};
    for (uint32_t i = 0u; i < 20u; ++i) {
        DF_CHECK_EQ_U64(t, dfi_multihit_count(i), want[i]);
        share[dfi_multihit_count(i)] += 1u;
    }
    DF_CHECK_EQ_U64(t, share[2], 7u);
    DF_CHECK_EQ_U64(t, share[3], 7u);
    DF_CHECK_EQ_U64(t, share[4], 3u);
    DF_CHECK_EQ_U64(t, share[5], 3u);
    DF_CHECK_EQ_U64(t, DFI_SITE_MULTIHIT_COUNT, 22u /* site 20 is the G46 drag, 21 the G56 lock */);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.moves.multi_hit_count");
    check_multihit_weights(&t);
    return df_test_end(&t);
}
