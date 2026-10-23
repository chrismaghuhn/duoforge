/*
 * duoforge.moves.destiny_bond_final_gambit_rows (white-box): step G76 of the content expansion (decision 0015 5cg), the rows of
 * Destiny Bond and Final Gambit: the handler ids, the support marks, the view bit and feature of Destiny Bond, its bit in
 * position_flags, the event that carries -singlemove, and the volatile numbers. Healing Wish is not in this step (5cg says
 * why).
 *
 * Split by subject from the test of step G76 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "data/formats/reg-mc/closure_tables.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/invariants.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* The row: the handler ids, the support marks, the view bit and feature of Destiny Bond, the event and the position bit. */
static void test_row(df_test *t)
{
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_DESTINY_BOND, DFI_SPECIAL_BATON_PASS + 1u); /* batch5: after G74 Baton Pass (97) */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_FINAL_GAMBIT, DFI_SPECIAL_DESTINY_BOND + 1u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_DESTINYBOND].special, DFI_SPECIAL_DESTINY_BOND);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_FINALGAMBIT].special, DFI_SPECIAL_FINAL_GAMBIT);
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_DESTINYBOND], 1u);
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_FINALGAMBIT], 1u);
    DF_CHECK(t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_DESTINY_BOND)) != 0u);
    DF_CHECK_EQ_U64(t, DUOFORGE_POSITION_EXT_DESTINY_BOND, 0x00000400u);
    DF_CHECK_EQ_U64(t, DUOFORGE_VIEWEXT_FEATURE_DESTINY_BOND, 35u);
    DF_CHECK_EQ_U64(t, DFI_POSFLAG_DESTINY_BOND, 0x10u); /* the lead's approved bit 4 of position_flags */
    DF_CHECK_EQ_U64(t, DFI_POSFLAG_VALID_MASK, 0xFFu); /* G84b (decision 0063) adds bit 7 CURSED; G88 bits 5 and 6: all eight bits */
    DF_CHECK_EQ_U64(t, DUOFORGE_EVENT_SINGLE_TURN, 38u); /* event 38 carries -singlemove with id = the move (no new value) */
    DF_CHECK_EQ_U64(t, DUOFORGE_VOLATILE_DRAGONCHEER, 10u); /* volatile 12 stays unused */
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.moves.destiny_bond_final_gambit_rows");
    test_row(&t);
    return df_test_end(&t);
}
