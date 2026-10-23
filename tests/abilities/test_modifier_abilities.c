/*
 * duoforge.abilities.modifier_abilities (white-box): step G65 of the content expansion (decision 0015 entry 5bk), the simple
 * modifier abilities as one batch, POOL build: Unaware (onAnyModifyBoost), Marvel Scale (onModifyDef x1.5 with a status), Water
 * Bubble (Fire at the holder x0.5, its Water moves x2, the burn refused), Reckless (x4915/4096 for a recoil move) and Super
 * Luck (crit ratio +1) are marked engine rows (family NONE, handler NONE, read by id in combat/turn.c), and Mold Breaker, which
 * would ignore the breakable ones, is not marked and stays UNMODELLED. The recorded battles g65_* are replayed by
 * duoforge.reference.conformance_pool_data.
 *
 * Split by subject from the test of step G65 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"


/* ---- the marks, the handler columns and the rows that stay out */
static void check_facts(df_test *t)
{
    static const uint32_t abilities[] = {DFI_ABILITY_UNAWARE, DFI_ABILITY_MARVELSCALE, DFI_ABILITY_WATERBUBBLE,
                                         DFI_ABILITY_RECKLESS, DFI_ABILITY_SUPERLUCK};
    for (size_t i = 0u; i < sizeof abilities / sizeof abilities[0]; ++i) {
        DF_CHECK(t, dfi_support.abilities[abilities[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[abilities[i]], DFI_HANDLER_NONE); /* an engine row: read by id */
        DF_CHECK_EQ_U64(t, dfi_pool_ability_family[abilities[i]].family, DFI_ABILITY_FAMILY_NONE);
    }
    /* Mold Breaker (and so Teravolt and Turboblaze, which are not in the pool) would ignore the breakable flag of Unaware, Marvel
     * Scale and Water Bubble: it is not marked, and its row is UNMODELLED, so no team with it is played. */
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_MOLDBREAKER], 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_MOLDBREAKER], DFI_HANDLER_UNMODELED);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.modifier_abilities");
    check_facts(&t);
    return df_test_end(&t);
}
