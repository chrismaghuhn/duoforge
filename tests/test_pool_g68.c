/*
 * duoforge.state.pool_g68 (white-box): step G68 of the content expansion (decision 0015, item 5cc, moves batch 4), POOL build.
 *
 * Two handlers: Steel Beam (STEEL_BEAM: the recoil of half the maximum HP after a hit and in MoveFail) and Thunder Wave
 * (THUNDER_WAVE: the Electric type immunity of the target, which the status moves skip). Fire Punch and Ice Hammer have no
 * handler: their rows are modelled by the existing burn secondary and self Speed drop. The recorded battles (g68_* under
 * "data": "pool") are replayed by duoforge.reference.conformance_pool_data. Here are the facts the battles do not show by
 * themselves: the handler numbers, the marks of the support manifest and the pinned numbers of the four rows.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "support/check.h"

/* The handler numbers follow the step G58 one (Phantom Force is the last before them), and UNMODELED moves to the last. */
static void check_handlers(df_test *t)
{
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_STEELBEAM].special, DFI_SPECIAL_STEEL_BEAM);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_THUNDERWAVE].special, DFI_SPECIAL_THUNDER_WAVE);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_STEEL_BEAM, DFI_SPECIAL_PHANTOM_FORCE + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_THUNDER_WAVE, DFI_SPECIAL_STEEL_BEAM + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_KINGS_SHIELD + 1u); /* G66 King's Shield (94) comes after Skill Swap */
    /* Fire Punch and Ice Hammer are data rows of the existing paths. */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_FIREPUNCH].special, DFI_SPECIAL_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_ICEHAMMER].special, DFI_SPECIAL_NONE);
}

/* The marks of the support manifest: the four rows of the step. */
static void check_marks(df_test *t)
{
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_STEELBEAM] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_THUNDERWAVE] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_FIREPUNCH] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_ICEHAMMER] != 0u);
}

/* The pinned numbers of the four rows (data/moves.ts): Steel Beam accuracy 95, base power 140, Steel, Special; Thunder Wave
 * accuracy 90, Electric, Status; Fire Punch a 10 percent secondary, Fire; Ice Hammer accuracy 90, base power 100, Ice. */
static void check_pins(df_test *t)
{
    const dfi_move_data *sb = &dfi_pool_moves[DFI_MOVE_STEELBEAM];
    const dfi_move_data *tw = &dfi_pool_moves[DFI_MOVE_THUNDERWAVE];
    const dfi_move_data *fp = &dfi_pool_moves[DFI_MOVE_FIREPUNCH];
    const dfi_move_data *ih = &dfi_pool_moves[DFI_MOVE_ICEHAMMER];
    DF_CHECK_EQ_U64(t, sb->accuracy, 95u);
    DF_CHECK_EQ_U64(t, sb->base_power, 140u);
    DF_CHECK_EQ_U64(t, sb->type, DFI_TYPE_STEEL);
    DF_CHECK_EQ_U64(t, sb->category, DFI_CATEGORY_SPECIAL);
    DF_CHECK_EQ_U64(t, tw->accuracy, 90u);
    DF_CHECK_EQ_U64(t, tw->type, DFI_TYPE_ELECTRIC);
    DF_CHECK_EQ_U64(t, tw->category, DFI_CATEGORY_STATUS);
    DF_CHECK_EQ_U64(t, fp->sec_chance, 10u);
    DF_CHECK_EQ_U64(t, fp->type, DFI_TYPE_FIRE);
    DF_CHECK_EQ_U64(t, ih->accuracy, 90u);
    DF_CHECK_EQ_U64(t, ih->base_power, 100u);
    DF_CHECK_EQ_U64(t, ih->type, DFI_TYPE_ICE);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g68");
    check_handlers(&t);
    check_marks(&t);
    check_pins(&t);
    return df_test_end(&t);
}
