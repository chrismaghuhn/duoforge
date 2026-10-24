/*
 * duoforge.moves.psych_up_howl_ally_switch_rows (white-box): step G80 of the content expansion (decision 0044), the rows of
 * Psych Up, Howl and Ally Switch: the special ids and their order, Howl's boost role and target class, the unmodelled lists,
 * the support marks, the event numbers, Ally Switch's draw site and the place of its byte in the tail's reserve. The recorded
 * battles g80_* are replayed by duoforge.reference.conformance_pool_data.
 *
 * Split by subject from the test of step G80 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include <stdlib.h>

#include <duoforge/duoforge.h>

#include "data/formats/reg-mc/closure_tables.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "codec/state_codec.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* The rows: the special ids and their order, the boost role and the target class, the unmodelled lists, the support marks, the
 * event numbers, the draw site and the Ally Switch byte's place in the reserve. */
static void test_rows(df_test *t)
{
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_PSYCH_UP, 0x76u); /* generator order: after Endeavor (C5, 0x75), before Ally Switch (batch 8 merge order) */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_ALLY_SWITCH, DFI_SPECIAL_PSYCH_UP + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_SPEED_SWAP + 1u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_PSYCHUP].special, DFI_SPECIAL_PSYCH_UP);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_ALLYSWITCH].special, DFI_SPECIAL_ALLY_SWITCH);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_HOWL].boost_role, DFI_BOOST_ROLE_PRIMARY_TARGET);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_HOWL].target_class, DFI_TARGET_CLASS_ALLIES);
    DF_CHECK(t, dfi_pool_move_unmodeled[DFI_MOVE_PSYCHUP] == NULL);
    DF_CHECK(t, dfi_pool_move_unmodeled[DFI_MOVE_HOWL] == NULL);
    DF_CHECK(t, dfi_pool_move_unmodeled[DFI_MOVE_ALLYSWITCH] == NULL);
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_PSYCHUP], 1u);
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_HOWL], 1u);
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_ALLYSWITCH], 1u);
    DF_CHECK_EQ_U64(t, DUOFORGE_EVENT_SWAP, 49u);
    DF_CHECK_EQ_U64(t, DUOFORGE_EVENT_COPY_BOOST, 50u);
    DF_CHECK_EQ_U64(t, DFI_SITE_ALLY_SWITCH, 33u);
    DF_CHECK_EQ_U64(t, DFI_SITE_COUNT, 34u); /* G80 Ally Switch (site 33) */
    DF_CHECK_EQ_U64(t, DFI_ALLY_SWITCH_MAX, 26u); /* level 6, two turns: (6 << 2) | 2 */
    DF_CHECK_EQ_U64(t, DFI_ENC_TAIL5_ALLY_SWITCH_OFF, 4u);
    DF_CHECK_EQ_U64(t, DFI_ENC_TAIL5_ALLY_SWITCH_COUNT, 4u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.moves.psych_up_howl_ally_switch_rows");
    test_rows(&t);
    return df_test_end(&t);
}
