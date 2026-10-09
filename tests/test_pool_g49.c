/*
 * duoforge.state.pool_g49 (white-box): step G49 of the content expansion, the item rows Muscle Band, Wise Glasses and
 * Bright Powder (decision 0015, item 5am). The duration rows (Damp Rock, Heat Rock, Smooth Rock, Icy Rock and Terrain
 * Extender) are not part of this step: the Python live tracker keeps weather and terrain turns at 5 (python/duoforge_live).
 *
 *   - Muscle Band (data/items.ts:4239-4251) and Wise Glasses (data/items.ts:7754-7766): base power x4505/4096 for a Physical
 *     and a Special move of the holder, onBasePowerPriority 16, so after Sharpness (19) and before the type boosters (15).
 *   - Bright Powder (data/items.ts:659-670): the accuracy of a move against the holder x3686/4096, onModifyAccuracyPriority -2,
 *     the same priority as Wide Lens (data/items.ts:7719-7726, the attacker's side). The two of priority -2 have no order in
 *     the pin (the holders' Speed, an exact tie draws), so the engine computes both orders and refuses a move for which they
 *     give different accuracies (E_UNSUPPORTED). The multi-hit path refuses a target with Bright Powder (the loop applies
 *     ModifyAccuracy after the stages, as it does for Wide Lens).
 *
 * The recorded battles (g49_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data, which compares
 * everything the reference shows. Here are the facts that it does not show:
 *   - the marks and the handler columns of the three rows (ENGINE_ROWS: no handler, not UNMODELED, no family);
 *   - the chain arithmetic: the modifiers, and for which base accuracies the two orders of Wide Lens and Bright Powder give
 *     different accuracies, for each prefix that Compound Eyes and Snow Cloak or Sand Veil make before them.
 */
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "core/modifier.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* The modified accuracy of a move with base accuracy `base` under the chain `chain` (dfi_modify, as the engine computes it). */
static uint32_t modified(uint32_t base, uint32_t chain)
{
    return dfi_modify(base, chain);
}

/* The two orders of Wide Lens (4505) and Bright Powder (3686) after a prefix chain (as the engine chains them): the chain
 * value of each order, and how many base accuracies (1 to 100) give a different modified accuracy in the two orders. */
static uint32_t order_chains(uint32_t prefix, uint32_t *wide_first, uint32_t *powder_first, uint32_t *differing)
{
    uint32_t a = prefix;
    uint32_t b = prefix;
    const bool ok = dfi_chain_modify(prefix, 4505u, &a) && dfi_chain_modify(a, 3686u, &a) &&
                    dfi_chain_modify(prefix, 3686u, &b) && dfi_chain_modify(b, 4505u, &b);
    *wide_first = a;
    *powder_first = b;
    *differing = 0u;
    for (uint32_t acc = 1u; acc <= 100u; ++acc) {
        *differing += modified(acc, a) != modified(acc, b) ? 1u : 0u;
    }
    return ok ? 1u : 0u;
}

static void check_facts(df_test *t)
{
    static const uint32_t items[] = {DFI_ITEM_MUSCLEBAND, DFI_ITEM_WISEGLASSES, DFI_ITEM_BRIGHTPOWDER};
    for (size_t i = 0u; i < sizeof items / sizeof items[0]; ++i) {
        DF_CHECK(t, dfi_support.items[items[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_item_handler[items[i]], DFI_HANDLER_NONE);
        DF_CHECK_EQ_U64(t, dfi_pool_item_family[items[i]].family, DFI_ITEM_FAMILY_NONE);
    }
    /* The duration rows stay unmarked: their step is not this one. */
    static const uint32_t unmarked[] = {DFI_ITEM_DAMPROCK, DFI_ITEM_HEATROCK, DFI_ITEM_SMOOTHROCK, DFI_ITEM_ICYROCK,
                                        DFI_ITEM_TERRAINEXTENDER};
    for (size_t i = 0u; i < sizeof unmarked / sizeof unmarked[0]; ++i) {
        DF_CHECK(t, dfi_support.items[unmarked[i]] == 0u);
    }
    /* The modifiers as the pin writes them: 4505/4096 is 1.1 and 3686/4096 is 0.9 of the base accuracy or power. */
    DF_CHECK_EQ_U64(t, modified(100u, 4505u), 110u);
    DF_CHECK_EQ_U64(t, modified(100u, 3686u), 90u);
    DF_CHECK_EQ_U64(t, modified(85u, 3686u), 76u);
    DF_CHECK_EQ_U64(t, modified(100u, 4096u), 100u);
}

static void check_orders(df_test *t)
{
    uint32_t wide = 0u;
    uint32_t powder = 0u;
    uint32_t differing = 0u;
    /* No prefix, or Snow Cloak's 3277 before them: a chain of two is the same in either order. */
    DF_CHECK(t, order_chains(4096u, &wide, &powder, &differing) == 1u);
    DF_CHECK_EQ_U64(t, wide, 4054u);
    DF_CHECK_EQ_U64(t, powder, 4054u);
    DF_CHECK_EQ_U64(t, differing, 0u);
    DF_CHECK(t, order_chains(3277u, &wide, &powder, &differing) == 1u);
    DF_CHECK_EQ_U64(t, wide, powder);
    DF_CHECK_EQ_U64(t, differing, 0u);
    /* Compound Eyes (5325) before them: the chains are 5271 and 5270; the orders differ for the base accuracies 68 and 75. */
    DF_CHECK(t, order_chains(5325u, &wide, &powder, &differing) == 1u);
    DF_CHECK_EQ_U64(t, wide, 5271u);
    DF_CHECK_EQ_U64(t, powder, 5270u);
    DF_CHECK_EQ_U64(t, differing, 2u);
    DF_CHECK(t, modified(68u, wide) != modified(68u, powder));
    DF_CHECK(t, modified(75u, wide) != modified(75u, powder));
    DF_CHECK(t, modified(100u, wide) == modified(100u, powder));
    DF_CHECK(t, modified(90u, wide) == modified(90u, powder));
    /* Compound Eyes and Snow Cloak together (4260 before the two): they differ for the base accuracies 17, 51 and 85. */
    DF_CHECK(t, order_chains(4260u, &wide, &powder, &differing) == 1u);
    DF_CHECK_EQ_U64(t, wide, 4216u);
    DF_CHECK_EQ_U64(t, powder, 4217u);
    DF_CHECK_EQ_U64(t, differing, 3u);
    DF_CHECK(t, modified(85u, wide) != modified(85u, powder));
    DF_CHECK(t, modified(100u, wide) == modified(100u, powder));
}

static void check_recorded(df_test *t)
{
    static const char *names[] = {"g49_wise_glasses", "g49_wise_glasses_base", "g49_muscle_band", "g49_muscle_band_base",
                                  "g49_bright_powder", "g49_bright_powder_base", "g49_category_cross"};
    for (size_t i = 0u; i < sizeof names / sizeof names[0]; ++i) {
        bool found = false;
        for (size_t k = 0u; k < sizeof conf_battles / sizeof conf_battles[0]; ++k) {
            found = found || strcmp(conf_battles[k].name, names[i]) == 0;
        }
        DF_CHECK(t, found);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g49");
    check_facts(&t);
    check_orders(&t);
    check_recorded(&t);
    return df_test_end(&t);
}
