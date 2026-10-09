/*
 * duoforge.state.pool_g64 (white-box): step G64 of the content expansion (decision 0015, item 5ca, moves batch 2), POOL build.
 *
 * Four handlers: Beat Up (BEAT_UP), Bug Bite (BUG_BITE), Poltergeist (POLTERGEIST) and Sheer Cold (SHEER_COLD). The recorded
 * battles (g64_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data. Here are the facts the battles
 * do not show by themselves: the handler numbers, the marks of the support manifest, and the pinned numbers of the rows.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "support/check.h"

/* The handler numbers follow the step G54 ones (Strength Sap is 81), in this order, and UNMODELED moves to the last. */
static void check_handlers(df_test *t)
{
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_BEATUP].special, DFI_SPECIAL_BEAT_UP);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_BUGBITE].special, DFI_SPECIAL_BUG_BITE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_POLTERGEIST].special, DFI_SPECIAL_POLTERGEIST);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SHEERCOLD].special, DFI_SPECIAL_SHEER_COLD);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_BEAT_UP, DFI_SPECIAL_STRENGTH_SAP + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_BUG_BITE, DFI_SPECIAL_BEAT_UP + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_POLTERGEIST, DFI_SPECIAL_BUG_BITE + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_SHEER_COLD, DFI_SPECIAL_POLTERGEIST + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_HAZE, DFI_SPECIAL_SHEER_COLD + 1u); /* step G62 (merged after G64): Haze, After You, Quash */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_PHANTOM_FORCE + 1u); /* step G60 (decision 0032) comes after Quash */
}

/* The marks of the support manifest: Poltergeist is the one row of the step that the turn code plays at this point. */
static void check_marks(df_test *t)
{
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_POLTERGEIST] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_BEATUP] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_BUGBITE] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_SHEERCOLD] != 0u);
}

/* The pinned numbers of the Poltergeist row (data/moves.ts:13595-13608): accuracy 90, base power 110, Ghost, Physical. */
static void check_pins(df_test *t)
{
    const dfi_move_data *p = &dfi_pool_moves[DFI_MOVE_POLTERGEIST];
    DF_CHECK_EQ_U64(t, p->accuracy, 90u);
    DF_CHECK_EQ_U64(t, p->base_power, 110u);
    DF_CHECK_EQ_U64(t, p->type, DFI_TYPE_GHOST);
    DF_CHECK_EQ_U64(t, p->category, DFI_CATEGORY_PHYSICAL);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g64");
    check_handlers(&t);
    check_marks(&t);
    check_pins(&t);
    return df_test_end(&t);
}
