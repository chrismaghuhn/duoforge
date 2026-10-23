/*
 * duoforge.abilities.reckless (white-box): step G65 of the content expansion (decision 0015 entry 5bk), the rows that
 * Reckless's recoil clause relies on: Struggle has no recoil (its struggleRecoil is a flag), the recoil moves carry their
 * fraction, and the crash moves (Axe Kick, High Jump Kick, Supercell Slam) are UNMODELLED, so no Reckless boost is reachable
 * through them. Also the four unmodified reads of the pin (getStat(..., true), which runs no ModifyBoost): Shell Side Arm is
 * the only one in the pool and it is an UNMODELLED row, so no read of it reaches Unaware.
 *
 * Split by subject from the test of step G65 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"
/* ---- the moves that Reckless's recoil clause reads, and the ones it must not reach */
static void check_recoil_rows(df_test *t)
{
    /* the recoil fraction of the move data: numerator and denominator (sim/battle-actions.ts applyRecoilDamage) */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_BRAVEBIRD].recoil[0], 33u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_BRAVEBIRD].recoil[1], 100u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_HEADSMASH].recoil[1], 2u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_WILDCHARGE].recoil[1], 4u);
    /* Struggle has no move.recoil (struggleRecoil is a flag, moves.ts:18228): Reckless does not boost it */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_STRUGGLE].recoil[1], 0u);
    /* the crash moves (hasCrashDamage) are UNMODELLED: no Reckless boost reaches them, and the generator refuses a modelled one
     * while Reckless has no crash clause (pool_families.js checkG65) */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_AXEKICK].special, DFI_SPECIAL_UNMODELED);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_HIGHJUMPKICK].special, DFI_SPECIAL_UNMODELED);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SUPERCELLSLAM].special, DFI_SPECIAL_UNMODELED);
    /* Shell Side Arm reads the unmodified Attack and Special Attack (sim/battle-actions.ts getStat(..., true), moves.ts:16230):
     * the row is UNMODELLED, so no Unaware stage is zeroed in that read. Once it is modelled, its read is to be exempt. */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SHELLSIDEARM].special, DFI_SPECIAL_UNMODELED);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.reckless");
    check_recoil_rows(&t);
    return df_test_end(&t);
}
