/*
 * duoforge.interactions.cheap_set_rows (white-box): step G75 of the content expansion (decision 0015, item 5bp, the cheap set),
 * POOL build, its three rows as one batch, each read by id in combat/turn.c: Pure Power (onModifyAtk x2 for a physical move of
 * its holder, data/abilities.ts:3608-3617, as Huge Power), Battle Armor (onCriticalHit false: the critical hit is cancelled
 * after its draw, data/abilities.ts:355-361, as Shell Armor) and Scope Lens (onModifyCritRatio +1, data/items.ts:5554-5565).
 * Their marks and handler columns (engine rows, handler NONE), and the base formes Falinks and Perrserker that carry Battle
 * Armor. The recorded battles g75_* are replayed by duoforge.reference.conformance_pool_data, which compares every event, HP
 * and draw with the reference, the critical draws included. The batch's two Mega Stones are checked in
 * tests/forms/test_mega_stones.c.
 *
 * Split by subject from the test of step G75 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>

#include <duoforge/duoforge.h>

#include "data/formulas.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* ---- the marks and the handler columns of the three rows */
static void check_rows(df_test *t)
{
    static const uint32_t abilities[] = {DFI_ABILITY_PUREPOWER, DFI_ABILITY_BATTLEARMOR};
    for (size_t i = 0u; i < sizeof abilities / sizeof abilities[0]; ++i) {
        DF_CHECK(t, dfi_support.abilities[abilities[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[abilities[i]], DFI_HANDLER_NONE); /* an engine row: read by id */
        DF_CHECK_EQ_U64(t, dfi_pool_ability_family[abilities[i]].family, DFI_ABILITY_FAMILY_NONE);
    }
    DF_CHECK(t, dfi_support.items[DFI_ITEM_SCOPELENS] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_SCOPELENS], DFI_HANDLER_NONE);
}

/* ---- the legal base abilities of a forme */
static bool base_ability_legal(uint32_t base, uint32_t ability)
{
    const dfi_forme_legal *l = &dfi_pool_forme_legal[base];
    for (uint32_t k = 0u; k < l->ability_count; ++k) {
        if (l->abilities[k] == ability) {
            return true;
        }
    }
    return false;
}

/* ---- Falinks (the holder of the battle) and Perrserker carry Battle Armor as a base ability */
static void check_battle_armor_bases(df_test *t)
{
    DF_CHECK(t, base_ability_legal(DFI_FORME_FALINKS, DFI_ABILITY_BATTLEARMOR));
    DF_CHECK(t, base_ability_legal(DFI_FORME_PERRSERKER, DFI_ABILITY_BATTLEARMOR));
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.interactions.cheap_set_rows");
    check_rows(&t);
    check_battle_armor_bases(&t);
    return df_test_end(&t);
}
