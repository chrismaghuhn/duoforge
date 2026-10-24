/*
 * duoforge.moves.power_move_rows (white-box): step G86 of the content expansion (decision 0015 5cn), the power moves as one
 * batch: the handlers Heavy Slam, Hard Press, Ice Spinner and Belly Drum and the data rows Body Slam, Razor Shell and Tickle
 * are marked, with the generated handler ids; Minimize stays unmarked (the minimize flag of Body Slam and Heavy Slam is inert).
 * The recorded battles g86_* are replayed by duoforge.reference.conformance_pool_data.
 *
 * Split by subject from the test of step G86 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/moves/families.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "support/check.h"

static void test_marks(df_test *t)
{
    /* The seven moves of the batch are marked (the data rows and the handlers alike). */
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_BODYSLAM] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_RAZORSHELL] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_TICKLE] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_HEAVYSLAM] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_HARDPRESS] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_ICESPINNER] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_BELLYDRUM] != 0u);
    /* Minimize stays unmarked: the minimize flag of Body Slam and Heavy Slam is inert (no volatile can exist). */
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_MINIMIZE] == 0u);
    /* The handler ids are the generated ones (gen_closure.py SPECIAL_IDS_P: after Dragon Darts, before UNMODELED). */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_HEAVY_SLAM, 104u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_HARD_PRESS, 105u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_ICE_SPINNER, 106u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_BELLY_DRUM, 107u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, 122u); /* K3 Speed Swap (decision 0015 5de) before UNMODELED: UNMODELED 122 */ /* batch 8: UNMODELED after Ally Switch (0x77) */
    DF_CHECK(t, dfi_pool_moves[DFI_MOVE_HEAVYSLAM].special == DFI_SPECIAL_HEAVY_SLAM);
    DF_CHECK(t, dfi_pool_moves[DFI_MOVE_HARDPRESS].special == DFI_SPECIAL_HARD_PRESS);
    DF_CHECK(t, dfi_pool_moves[DFI_MOVE_ICESPINNER].special == DFI_SPECIAL_ICE_SPINNER);
    DF_CHECK(t, dfi_pool_moves[DFI_MOVE_BELLYDRUM].special == DFI_SPECIAL_BELLY_DRUM);
    /* The data rows have no handler (the generic columns carry them). */
    DF_CHECK(t, dfi_pool_moves[DFI_MOVE_BODYSLAM].special == DFI_SPECIAL_NONE);
    DF_CHECK(t, dfi_pool_moves[DFI_MOVE_RAZORSHELL].special == DFI_SPECIAL_NONE);
    DF_CHECK(t, dfi_pool_moves[DFI_MOVE_TICKLE].special == DFI_SPECIAL_NONE);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.moves.power_move_rows");
    test_marks(&t);
    return df_test_end(&t);
}
