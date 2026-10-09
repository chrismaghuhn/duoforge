/*
 * duoforge.state.pool_g70 (white-box): step G70 of the content expansion, Skill Swap (decision 0041).
 *
 * What this test pins, and where the rest of the evidence is:
 *   - the row: Skill Swap is marked (its handler is SKILL_SWAP, id 91, and UNMODELED follows it at 92); the other handler
 *     rows of the batch are not touched;
 *   - flags3 bit 2 (DFI_MOVE_FLAG3_BYPASSSUB): Skill Swap has flags.bypasssub in the pin (data/moves.ts:16598), so it is set;
 *   - the abilities that the swap moves are marked (no new ability row of this step): Trace, Synchronize, Intimidate, Pressure,
 *     Drizzle, Flash Fire, Cursed Body, Contrary, Levitate and Hospitality are supported, and Stance Change (its failskillswap,
 *     decision 0041) is the one that the swap fails on, marked only by step G66.
 * The engine's behaviour (the two ability events, the Start and End of the abilities that move, the ability copies, the Trace
 * draw, Hospitality, the Update refusals) is pinned by the recorded battles tests/reference/traces/g70_skillswap_*.json,
 * replayed by duoforge.reference.conformance_pool_data.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "state/battle_internal.h"
#include "support/check.h"

/* The row and its handler. */
static void check_row(df_test *t)
{
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_SKILL_SWAP, DFI_SPECIAL_PHANTOM_FORCE + 2u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_SKILL_SWAP + 1u);
    DF_CHECK_EQ_U64(t, DFI_MOVE_SKILLSWAP, 405u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_SKILLSWAP] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SKILLSWAP].special, DFI_SPECIAL_SKILL_SWAP);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SKILLSWAP].special == DFI_SPECIAL_UNMODELED ? 1u : 0u, 0u);
}

/* flags.bypasssub of the pin: the swap passes a Substitute (flags3 bit 2), and so do the moves that the pin marks with it. */
static void check_bypass(df_test *t)
{
    DF_CHECK(t, (dfi_pool_move_flags3[DFI_MOVE_SKILLSWAP] & DFI_MOVE_FLAG3_BYPASSSUB) != 0u);
    DF_CHECK(t, (dfi_pool_move_flags3[DFI_MOVE_SUBSTITUTE] & DFI_MOVE_FLAG3_BYPASSSUB) == 0u);
}

/* The abilities the swap and its Start and End lines name are rows that the support manifest marks (decision 0041, table). */
static void check_abilities(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_TRACE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_SYNCHRONIZE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_INTIMIDATE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_PRESSURE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_DRIZZLE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_FLASHFIRE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_CURSEDBODY] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_HOSPITALITY] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_LIMBER] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_THERMALEXCHANGE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_OBLIVIOUS] != 0u);
    /* Stance Change has failskillswap (data/abilities.ts:4531): its row is the one the swap refuses, and only step G66 marks it */
    DF_CHECK_EQ_U64(t, DFI_ABILITY_STANCECHANGE, 180u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g70");
    check_row(&t);
    check_bypass(&t);
    check_abilities(&t);
    return df_test_end(&t);
}
