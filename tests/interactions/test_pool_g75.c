/*
 * duoforge.state.pool_g75 (white-box): step G75 of the content expansion (decision 0015, item 5bp, the cheap set), POOL build.
 *
 * Four rows, each read by id in combat/turn.c, and two Mega pairs:
 *   Pure Power     onModifyAtk x2 for a physical move of its holder (data/abilities.ts:3608-3617, as Huge Power at :1886-1896)
 *   Battle Armor   onCriticalHit false: the critical hit is cancelled after its draw (data/abilities.ts:355-361, as Shell Armor)
 *   Scope Lens     onModifyCritRatio +1: one more term of the critical ratio sum, before the clamp to 0..4 (data/items.ts:5554-5565)
 *   Medichamite    Medicham-Mega (Pure Power); Medicham keeps Pure Power and Telepathy
 *   Clefablite     Clefable-Mega (Magic Bounce); Clefable's hidden ability Unaware (marked by G65) makes the pair reachable
 *
 * The recorded battles (g75_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data, which compares every
 * event, HP and draw with the reference, the critical draws (site CRIT, with their denominators) included. Here are the facts that
 * they do not show by themselves:
 *   - the marks and the handler columns: the four rows and the three stones are marked (support manifest), with the handler NONE
 *     (engine rows read by id, the stones mark only);
 *   - the stones that stay out, with their reason: Starminite (Starmie's abilities Illuminate, Natural Cure and Analytic are
 *     unmarked), Altarianite (Altaria's Natural Cure and Cloud Nine are unmarked), Sharpedonite (Strong Jaw is UNMODELLED: its bite
 *     flag has no pool column yet, deferred);
 *   - the Mega of each pair (dfi_mega_of) and the support of the pair (dfi_manifest_mega_of), and the legal base abilities of the
 *     two base formes that the battles use (Pure Power on Medicham, Unaware on Clefable, as hidden ability).
 */
#include <stdio.h>

#include <duoforge/duoforge.h>

#include "data/formulas.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* ---- the marks, the handler columns and the rows that stay out */
static void check_marks(df_test *t)
{
    static const uint32_t abilities[] = {DFI_ABILITY_PUREPOWER, DFI_ABILITY_BATTLEARMOR};
    for (size_t i = 0u; i < sizeof abilities / sizeof abilities[0]; ++i) {
        DF_CHECK(t, dfi_support.abilities[abilities[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[abilities[i]], DFI_HANDLER_NONE); /* an engine row: read by id */
        DF_CHECK_EQ_U64(t, dfi_pool_ability_family[abilities[i]].family, DFI_ABILITY_FAMILY_NONE);
    }
    static const uint32_t items[] = {DFI_ITEM_SCOPELENS, DFI_ITEM_MEDICHAMITE, DFI_ITEM_CLEFABLITE};
    for (size_t i = 0u; i < sizeof items / sizeof items[0]; ++i) {
        DF_CHECK(t, dfi_support.items[items[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_item_handler[items[i]], DFI_HANDLER_NONE);
    }
    /* the stones that stay out, and Strong Jaw, whose bite flag would need a pool column (deferred, not in this batch) */
    DF_CHECK_EQ_U64(t, dfi_support.items[DFI_ITEM_STARMINITE], 0u);
    DF_CHECK_EQ_U64(t, dfi_support.items[DFI_ITEM_ALTARIANITE], 0u);
    DF_CHECK_EQ_U64(t, dfi_support.items[DFI_ITEM_SHARPEDONITE], 0u);
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_STRONGJAW], 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_STRONGJAW], DFI_HANDLER_UNMODELED);
}

/* ---- the Mega pairs of the two stones, and the legal base abilities of their base formes */
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

static void check_pairs(df_test *t)
{
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_MEDICHAM, 1u + DFI_ITEM_MEDICHAMITE), DFI_FORME_MEDICHAMMEGA);
    DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_MEDICHAM, 1u + DFI_ITEM_MEDICHAMITE));
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_CLEFABLE, 1u + DFI_ITEM_CLEFABLITE), DFI_FORME_CLEFABLEMEGA);
    DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_CLEFABLE, 1u + DFI_ITEM_CLEFABLITE));
    /* the base formes of the battles hold the ability of each pair */
    DF_CHECK(t, base_ability_legal(DFI_FORME_MEDICHAM, DFI_ABILITY_PUREPOWER));
    DF_CHECK(t, base_ability_legal(DFI_FORME_CLEFABLE, DFI_ABILITY_UNAWARE));
    /* Falinks (the holder of the battle) and Perrserker carry Battle Armor as a base ability */
    DF_CHECK(t, base_ability_legal(DFI_FORME_FALINKS, DFI_ABILITY_BATTLEARMOR));
    DF_CHECK(t, base_ability_legal(DFI_FORME_PERRSERKER, DFI_ABILITY_BATTLEARMOR));
    /* a stone of another forme gives nothing: Medichamite on Clefable, Clefablite on Medicham */
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_CLEFABLE, 1u + DFI_ITEM_MEDICHAMITE), DFI_FORME_NONE);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_MEDICHAM, 1u + DFI_ITEM_CLEFABLITE), DFI_FORME_NONE);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g75");
    check_marks(&t);
    check_pairs(&t);
    return df_test_end(&t);
}
