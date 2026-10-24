/*
 * duoforge.interactions.modify_damage_bound (white-box): step G77 of the content expansion (decision 0015, item 5bq), the bound
 * of the ModifyDamage list: it holds at most DFI_MODIFY_DAMAGE_MAX (six) modifiers, and dfi_mods_push refuses a seventh
 * (E_UNSUPPORTED) without writing past the list. The maximum for one hit is six (combat/damage_chain.h): Sniper is a crit-only
 * modifier and a screen is not applied to a crit, so the two never meet.
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

/* ---- the ModifyDamage list: the bound, and the refusal of a write past it */
static void check_chain_bound(df_test *t)
{
    DF_CHECK_EQ_U64(t, DFI_MODIFY_DAMAGE_MAX, 6u); /* the bound is six (damage_chain.h): no hit has a seventh modifier */
    uint32_t list[DFI_MODIFY_DAMAGE_MAX] = {0u};
    uint32_t mods = 0u;
    for (uint32_t i = 0u; i < DFI_MODIFY_DAMAGE_MAX; ++i) {
        DF_CHECK(t, dfi_mods_push(list, &mods, 2048u + i));
    }
    DF_CHECK_EQ_U64(t, mods, DFI_MODIFY_DAMAGE_MAX);
    /* the ninth is refused: the count and the list are unchanged, nothing is written past the end */
    DF_CHECK(t, !dfi_mods_push(list, &mods, 4096u));
    DF_CHECK_EQ_U64(t, mods, DFI_MODIFY_DAMAGE_MAX);
    DF_CHECK_EQ_U64(t, list[DFI_MODIFY_DAMAGE_MAX - 1u], 2048u + DFI_MODIFY_DAMAGE_MAX - 1u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.interactions.modify_damage_bound");
    check_chain_bound(&t);
    return df_test_end(&t);
}
