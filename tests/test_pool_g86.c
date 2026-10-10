/*
 * duoforge.state.pool_g86 (white-box): step G86 of the content expansion (decision 0015 5cn), the power moves: Heavy Slam,
 * Hard Press, Ice Spinner and Belly Drum (the handlers), and Body Slam, Razor Shell and Tickle (data rows, marked only).
 *
 * The recorded battles g86_* (under "data": "pool") are replayed by duoforge.reference.conformance_pool_data, which compares
 * every HP, stage, request and event with the reference. This file checks what the replay does not show by itself: the marks
 * and the handler ids of the rows, the two base power formulas at their boundaries (the pin's integer forms, checked against
 * the values that the pin's own double arithmetic gives: Hard Press at 33 percent is 32, not 33), and the names of the rows.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/move_rules.h"
#include "data/pool_tables.h"
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
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_HEAVY_SLAM, 101u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_HARD_PRESS, 102u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_ICE_SPINNER, 103u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_BELLY_DRUM, 104u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, 105u);
    DF_CHECK(t, dfi_pool_moves[DFI_MOVE_HEAVYSLAM].special == DFI_SPECIAL_HEAVY_SLAM);
    DF_CHECK(t, dfi_pool_moves[DFI_MOVE_HARDPRESS].special == DFI_SPECIAL_HARD_PRESS);
    DF_CHECK(t, dfi_pool_moves[DFI_MOVE_ICESPINNER].special == DFI_SPECIAL_ICE_SPINNER);
    DF_CHECK(t, dfi_pool_moves[DFI_MOVE_BELLYDRUM].special == DFI_SPECIAL_BELLY_DRUM);
    /* The data rows have no handler (the generic columns carry them). */
    DF_CHECK(t, dfi_pool_moves[DFI_MOVE_BODYSLAM].special == DFI_SPECIAL_NONE);
    DF_CHECK(t, dfi_pool_moves[DFI_MOVE_RAZORSHELL].special == DFI_SPECIAL_NONE);
    DF_CHECK(t, dfi_pool_moves[DFI_MOVE_TICKLE].special == DFI_SPECIAL_NONE);
}

/* Heavy Slam: the ratio of the user's weight to the target's, in hectograms; the tests are the pin's, >= on each multiple. */
static void test_heavy_slam_power(df_test *t)
{
    DF_CHECK_EQ_U64(t, dfi_heavy_slam_power(1000u, 200u), 120u); /* exactly five times */
    DF_CHECK_EQ_U64(t, dfi_heavy_slam_power(999u, 200u), 100u);
    DF_CHECK_EQ_U64(t, dfi_heavy_slam_power(800u, 200u), 100u);  /* exactly four times */
    DF_CHECK_EQ_U64(t, dfi_heavy_slam_power(799u, 200u), 80u);
    DF_CHECK_EQ_U64(t, dfi_heavy_slam_power(600u, 200u), 80u);   /* exactly three times */
    DF_CHECK_EQ_U64(t, dfi_heavy_slam_power(599u, 200u), 60u);
    DF_CHECK_EQ_U64(t, dfi_heavy_slam_power(400u, 200u), 60u);   /* exactly twice */
    DF_CHECK_EQ_U64(t, dfi_heavy_slam_power(399u, 200u), 40u);   /* the smallest ratio of the table */
    DF_CHECK_EQ_U64(t, dfi_heavy_slam_power(4600u, 4600u), 40u); /* Snorlax against Snorlax */
    DF_CHECK_EQ_U64(t, dfi_heavy_slam_power(0u, 200u), 40u);     /* a weight of 0 counts as 1 (getWeight's max) */
    DF_CHECK_EQ_U64(t, dfi_heavy_slam_power(5u, 0u), 120u);      /* the target's 0 counts as 1 */
}

/* Hard Press: the pin's formula floor(floor((100 * (100 * floor(hp * 4096 / maxhp)) + 2047) / 4096) / 100) || 1. The expected
 * values are the pin's double arithmetic, run once: 33 of 100 HP gives 32, 267 of 267 gives 100, 1 of 267 gives 1 (the minimum). */
static void test_hard_press_power(df_test *t)
{
    DF_CHECK_EQ_U64(t, dfi_hard_press_power(1u, 267u), 1u);
    DF_CHECK_EQ_U64(t, dfi_hard_press_power(134u, 267u), 50u);
    DF_CHECK_EQ_U64(t, dfi_hard_press_power(50u, 100u), 50u);
    DF_CHECK_EQ_U64(t, dfi_hard_press_power(99u, 100u), 99u);
    DF_CHECK_EQ_U64(t, dfi_hard_press_power(100u, 100u), 100u);
    DF_CHECK_EQ_U64(t, dfi_hard_press_power(1u, 100u), 1u);
    DF_CHECK_EQ_U64(t, dfi_hard_press_power(33u, 100u), 32u);
    DF_CHECK_EQ_U64(t, dfi_hard_press_power(267u, 267u), 100u);
    DF_CHECK_EQ_U64(t, dfi_hard_press_power(200u, 267u), 74u);
    DF_CHECK_EQ_U64(t, dfi_hard_press_power(1u, 1u), 100u);
    DF_CHECK_EQ_U64(t, dfi_hard_press_power(7u, 10u), 70u);
    DF_CHECK_EQ_U64(t, dfi_hard_press_power(3u, 7u), 42u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g86");
    test_marks(&t);
    test_heavy_slam_power(&t);
    test_hard_press_power(&t);
    return df_test_end(&t);
}
