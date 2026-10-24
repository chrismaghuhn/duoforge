/*
 * duoforge.abilities.damp_sturdy_rows (white-box): step G39 of the content expansion, what Damp and Sturdy act on: Damp's
 * callbacks only stop Explosion, Self-Destruct, Misty Explosion and Mind Blown and nullify Aftermath, none of which is marked,
 * so Damp stays inert; the OHKO moves that Sturdy's second callback is immune to are marked by later steps (Sheer Cold by G64,
 * Fissure, Guillotine and Horn Drill by G92 with the OHKO handler, Sturdy's immunity checked in its own test); and Mold
 * Breaker, which they (and five more abilities of the step) are breakable against, stays unmarked.
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

static uint32_t move_named(const char *name)
{
    for (uint32_t m = 0u; m < DFI_POOL_MOVE_COUNT; ++m) {
        if (strcmp(dfi_pool_move_names[m], name) == 0) {
            return m;
        }
    }
    return UINT32_MAX;
}

/* Damp and Sturdy are inert only while what they would act on is unmarked. */
static void check_inert(df_test *t)
{
    static const char *const explosive[] = {"explosion", "selfdestruct", "mistyexplosion", "mindblown"};
    /* Sheer Cold is no longer in this list: step G64 marks it (ohko 'Ice', decision 0015 item 5ca). Fissure, Guillotine and Horn
     * Drill are marked by step G92 (decision 0062, the OHKO handler); Sturdy is their immunity,
     * checked by duoforge.moves.confusion_moves. */
    static const char *const ohko[] = {"fissure", "guillotine", "horndrill"};
    for (size_t i = 0u; i < sizeof explosive / sizeof explosive[0]; ++i) {
        const uint32_t m = move_named(explosive[i]);
        if (m != UINT32_MAX) {
            DF_CHECK_EQ_U64(t, dfi_support.moves[m], 0u);
        }
    }
    for (size_t i = 0u; i < sizeof ohko / sizeof ohko[0]; ++i) {
        const uint32_t m = move_named(ohko[i]);
        if (m != UINT32_MAX) {
            DF_CHECK_EQ_U64(t, dfi_support.moves[m], 1u); /* step G92: marked */
            DF_CHECK_EQ_U64(t, dfi_pool_moves[m].special, DFI_SPECIAL_OHKO);
        }
    }
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_AFTERMATH], 0u);
    /* Mold Breaker, which Hyper Cutter, Sturdy, Damp, Snow Cloak, Sand Veil, Limber and Queenly Majesty are breakable against,
     * is unmarked */
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_MOLDBREAKER], 0u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.damp_sturdy_rows");
    check_inert(&t);
    return df_test_end(&t);
}
