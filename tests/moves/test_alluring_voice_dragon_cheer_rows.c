/*
 * duoforge.moves.alluring_voice_dragon_cheer_rows (white-box): step G72b of the content expansion (decision 0015 5ce), the rows
 * of Alluring Voice and Dragon Cheer: the support marks, the handler ids in their merged order, the view bit and position bit
 * of the Dragon Cheer stage (the manifest and the view agree), the volatile number and the public cause
 * DUOFORGE_PUBLIC_CAUSE_RAISED_THIS_TURN.
 *
 * Split by subject from the test of step G72b (restructure step 6e; tests/renames.tsv maps the old name).
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

/* The row: the support marks, the handler ids, and the view bit of Dragon Cheer (the manifest and the view agree). */
static void test_row(df_test *t)
{
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_ALLURING_VOICE, DFI_SPECIAL_KINGS_SHIELD + 1u); /* merged order: after King's Shield (G66) */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_DRAGON_CHEER, DFI_SPECIAL_ALLURING_VOICE + 1u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_ALLURINGVOICE].special, DFI_SPECIAL_ALLURING_VOICE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_DRAGONCHEER].special, DFI_SPECIAL_DRAGON_CHEER);
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_ALLURINGVOICE], 1u);
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_DRAGONCHEER], 1u);
    DF_CHECK(t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_DRAGON_CHEER)) != 0u);
    DF_CHECK_EQ_U64(t, DUOFORGE_POSITION_EXT_DRAGON_CHEER, 0x40u);
    DF_CHECK_EQ_U64(t, DUOFORGE_VOLATILE_DRAGONCHEER, 10u);
    DF_CHECK_EQ_U64(t, DUOFORGE_PUBLIC_CAUSE_RAISED_THIS_TURN, 32u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.moves.alluring_voice_dragon_cheer_rows");
    test_row(&t);
    return df_test_end(&t);
}
