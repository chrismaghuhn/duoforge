/*
 * duoforge.interactions.crit_package_rows (white-box): step G77 of the content expansion (decision 0015, item 5bq, the crit
 * package), POOL build, as one batch: Magma Armor, Anger Point, Sniper and Leek are marked engine rows (family NONE, handler
 * NONE), read by id in combat/turn.c; Mold Breaker, which would ignore the breakable flag of Magma Armor, is not marked and
 * stays UNMODELLED. The recorded battles g77_* are replayed by duoforge.reference.conformance_pool_data.
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

/* ---- the marks, the handler columns and the rows that stay out */
static void check_facts(df_test *t)
{
    static const uint32_t abilities[] = {DFI_ABILITY_MAGMAARMOR, DFI_ABILITY_ANGERPOINT, DFI_ABILITY_SNIPER};
    for (size_t i = 0u; i < sizeof abilities / sizeof abilities[0]; ++i) {
        DF_CHECK(t, dfi_support.abilities[abilities[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[abilities[i]], DFI_HANDLER_NONE); /* an engine row: read by id */
        DF_CHECK_EQ_U64(t, dfi_pool_ability_family[abilities[i]].family, DFI_ABILITY_FAMILY_NONE);
    }
    DF_CHECK(t, dfi_support.items[DFI_ITEM_LEEK] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_LEEK], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_item_family[DFI_ITEM_LEEK].family, DFI_ITEM_FAMILY_NONE);
    /* Mold Breaker would ignore the breakable flag of Magma Armor: it is not marked, and its row is UNMODELLED */
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_MOLDBREAKER], 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_MOLDBREAKER], DFI_HANDLER_UNMODELED);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.interactions.crit_package_rows");
    check_facts(&t);
    return df_test_end(&t);
}
