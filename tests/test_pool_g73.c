/*
 * duoforge.state.pool_g73 (white-box): step G73 of the content expansion (decision 0015, item 5bo), Moody, POOL build.
 *
 * Moody (data/abilities.ts:2701-2734) is an engine row read by id in combat/turn.c (dfi_moody):
 *   - the residual entry of order 28, sub-order 2, the key of Speed Boost (DFI_RES_MOODY, a callback), so a tie of two Moody
 *     holders is a shuffle as Speed Boost's is;
 *   - two samples in the same DFI_SITE_MOODY (23): the stats below +6 (accuracy and evasion left out), then the stats above -6
 *     and not the raised one; an empty list draws nothing, a list of one draws (random(1), one rng.next() at the pin);
 *   - one boost {raised: +2, lowered: -1} with the raised key first (positives_first), the ability's own line.
 *
 * The recorded battles (g73_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data, which compares
 * every event, HP and draw with the reference. Here are the facts they do not show by themselves:
 *   - the marks and the handler columns: Moody is a marked engine row (family NONE, handler NONE), not breakable;
 *   - Opportunist (a foe's onFoeAfterBoost copies a rise, which Moody's rise reaches) stays unmarked and UNMODELLED, so no team
 *     with it is played, and Mirror Herb and Simple are not pool rows;
 *   - the draw site: DFI_SITE_MOODY is 23 and DFI_SITE_COUNT 24 (the site list is the one of draw.h; G71 takes 24 and 25 later).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/residual_order.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* ---- the marks, the handler columns and the rows that stay out */
static void check_facts(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_MOODY] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_MOODY], DFI_HANDLER_NONE); /* an engine row: read by id */
    DF_CHECK_EQ_U64(t, dfi_pool_ability_family[DFI_ABILITY_MOODY].family, DFI_ABILITY_FAMILY_NONE);
    /* Opportunist copies a foe's rise (onFoeAfterBoost, data/abilities.ts:3042): not marked, UNMODELLED, so it is refused */
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_OPPORTUNIST], 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_OPPORTUNIST], DFI_HANDLER_UNMODELED);
    /* the draw site of Moody's samples, and the count of the sites after it */
    DF_CHECK_EQ_U64(t, DFI_SITE_MOODY, 23u);
    DF_CHECK_EQ_U64(t, DFI_SITE_COUNT, 24u);
    /* the residual kind of the entry: after the kinds of residual_order.h before it (Speed Boost 11, the duration kinds up to 17) */
    DF_CHECK_EQ_U64(t, DFI_RES_MOODY, 18u);
}

/* ---- the recorded battles of this step are in the conformance table (their names are the spec names) */
static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0u; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

static void check_battles_present(df_test *t)
{
    static const char *const names[] = {"g73_moody_turns", "g73_moody_white_herb", "g73_moody_speed_tie"};
    for (size_t i = 0u; i < sizeof names / sizeof names[0]; ++i) {
        DF_CHECK(t, find(names[i]) != NULL);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g73");
    check_facts(&t);
    check_battles_present(&t);
    return df_test_end(&t);
}
