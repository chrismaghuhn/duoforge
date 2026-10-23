/*
 * duoforge.items.power_and_accuracy_items (white-box): step G49 of the content expansion (decision 0015 entry 5ao), the item
 * rows Muscle Band, Wise Glasses and Bright Powder as one batch: the marks and the handler columns of the three rows
 * (ENGINE_ROWS: no handler, not UNMODELED, no family) and the recorded battles g49_* that conformance_pool_data replays. Muscle
 * Band and Wise Glasses (base power x4505/4096 for a Physical and a Special move of the holder, onBasePowerPriority 16, after
 * Sharpness and before the type boosters) have no check of their own here: their battles show them. The duration rows (Damp
 * Rock, Heat Rock, Smooth Rock, Icy Rock, Terrain Extender) are not part of this step.
 *
 * Split by subject from the test of step G49 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "core/modifier.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* The modified accuracy of a move with base accuracy `base` under the chain `chain` (dfi_modify, as the engine computes it). */
static uint32_t modified(uint32_t base, uint32_t chain)
{
    return dfi_modify(base, chain);
}

static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

static void check_facts(df_test *t)
{
    static const uint32_t items[] = {DFI_ITEM_MUSCLEBAND, DFI_ITEM_WISEGLASSES, DFI_ITEM_BRIGHTPOWDER};
    for (size_t i = 0u; i < sizeof items / sizeof items[0]; ++i) {
        DF_CHECK(t, dfi_support.items[items[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_item_handler[items[i]], DFI_HANDLER_NONE);
        DF_CHECK_EQ_U64(t, dfi_pool_item_family[items[i]].family, DFI_ITEM_FAMILY_NONE);
    }
    /* The duration rows (Damp, Heat, Smooth and Icy Rock, Terrain Extender) were unmarked at this step; step G55 marks them,
     * and tests/items/test_duration_items.c owns that check. */
    /* The modifiers as the pin writes them: 4505/4096 is 1.1 and 3686/4096 is 0.9 of the base accuracy or power. */
    DF_CHECK_EQ_U64(t, modified(100u, 4505u), 110u);
    DF_CHECK_EQ_U64(t, modified(100u, 3686u), 90u);
    DF_CHECK_EQ_U64(t, modified(85u, 3686u), 76u);
    DF_CHECK_EQ_U64(t, modified(100u, 4096u), 100u);
}

static void check_recorded(df_test *t)
{
    static const char *names[] = {"g49_wise_glasses", "g49_wise_glasses_base", "g49_muscle_band", "g49_muscle_band_base",
                                  "g49_bright_powder", "g49_bright_powder_base", "g49_category_cross",
                                  "g49_bright_powder_tie"};
    for (size_t i = 0u; i < sizeof names / sizeof names[0]; ++i) {
        DF_CHECK(t, find(names[i]) != NULL);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.items.power_and_accuracy_items");
    check_facts(&t);
    check_recorded(&t);
    return df_test_end(&t);
}
