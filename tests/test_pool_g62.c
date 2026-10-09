/*
 * duoforge.state.pool_g62 (white-box): step G62 of the content expansion (decision 0015 entry 5az, decision 0031), in the POOL
 * build: Haze. Its hit prints `-clearallboost` (the public event DUOFORGE_EVENT_CLEAR_ALL_BOOSTS, 47) and clears the seven
 * boosts of every standing active Pokemon (getAllActive(), so a fainted one is skipped), and nothing else: the volatiles stay.
 * The recorded battles (g62_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data, which compares
 * every event, draw, stage and HP of the reference. Here are the facts that the battles do not state by themselves:
 *
 *   - the mark, the handler number and the pinned row of Haze (accuracy true: 0, the field target, no protect flag);
 *   - the public value 47 and the event order (after DRAG, 45; 46 is not used here);
 *   - the neutral stage value that the boosts go to, and the number of boosts that clearBoosts zeroes (seven).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/closure_tables.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/pool.h"

static void check_mark(df_test *t)
{
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_HAZE] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_HAZE].special, DFI_SPECIAL_HAZE);
    /* the handler id comes after the G54 ones, and Unmodelled moves after it */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_HAZE, DFI_SPECIAL_STRENGTH_SAP + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_HAZE + 1u);
}

/* data/moves.ts:8156-8172: accuracy true (0: never misses), Status, the field target, no protect flag, priority 0, Ice. */
static void check_pins(df_test *t)
{
    const dfi_move_data *haze = &dfi_pool_moves[DFI_MOVE_HAZE];
    DF_CHECK_EQ_U64(t, haze->accuracy, 0u);
    DF_CHECK_EQ_U64(t, haze->category, DFI_CATEGORY_STATUS);
    DF_CHECK_EQ_U64(t, haze->target_class, DUOFORGE_TARGET_CLASS_ALL);
    DF_CHECK(t, (haze->flags & DFI_MOVE_FLAG_PROTECT) == 0u);
    DF_CHECK_EQ_U64(t, haze->priority, DFI_PRIORITY_BIAS);
    DF_CHECK_EQ_U64(t, haze->type, DFI_TYPE_ICE);
    DF_CHECK_EQ_U64(t, haze->sec_chance, 0u);
}

/* The public value and the neutral stage: the event is the one the reference's `-clearallboost` line maps to (trace_to_c.py),
 * and the boosts go to DFI_STAGE_NEUTRAL (the biased zero). Seven boosts exist (atk, def, spa, spd, spe, accuracy, evasion). */
static void check_values(df_test *t)
{
    DF_CHECK_EQ_U64(t, DUOFORGE_EVENT_CLEAR_ALL_BOOSTS, 47u);
    DF_CHECK_EQ_U64(t, DUOFORGE_EVENT_CLEAR_ALL_BOOSTS, DUOFORGE_EVENT_DRAG + 2u); /* 46 is not used by this step */
    DF_CHECK_EQ_U64(t, DFI_STAGE_NEUTRAL, 6u);
    DF_CHECK_EQ_U64(t, DFI_STAT_STAGE_COUNT, 7u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g62");
    check_mark(&t);
    check_pins(&t);
    check_values(&t);
    return df_test_end(&t);
}
