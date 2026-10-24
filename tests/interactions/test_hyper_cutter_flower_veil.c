/*
 * duoforge.interactions.hyper_cutter_flower_veil (white-box): step G39 of the content expansion, the TryBoost order that the
 * engine does not compute: Hyper Cutter shares the event with Flower Veil's handler, so no Pokemon of the pool that can have
 * Hyper Cutter is a Grass type (a Flower Veil holder protects the Grass types of its side).
 *
 * Split by subject from the test of step G39 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "rng/draw.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* A Hyper Cutter holder that is a Grass type would meet Flower Veil's TryBoost handler of a partner in an order that the engine
 * does not compute. */
static void check_hyper_cutter_not_grass(df_test *t)
{
    uint32_t holders = 0u;
    for (uint32_t forme = 0u; forme < DFI_POOL_FORME_COUNT; ++forme) {
        const dfi_forme_legal *l = &dfi_pool_forme_legal[forme];
        bool has = false;
        for (uint32_t k = 0u; k < l->ability_count; ++k) {
            has = has || l->abilities[k] == DFI_ABILITY_HYPERCUTTER;
        }
        if (!has) {
            continue;
        }
        holders += 1u;
        DF_CHECK(t, dfi_pool_formes[forme].types[0] != DFI_TYPE_GRASS && dfi_pool_formes[forme].types[1] != DFI_TYPE_GRASS);
    }
    DF_CHECK(t, holders >= 4u); /* Pinsir, Mawile, Gliscor, Crabominable and their Megas */
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.interactions.hyper_cutter_flower_veil");
    check_hyper_cutter_not_grass(&t);
    return df_test_end(&t);
}
