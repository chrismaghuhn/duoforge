/*
 * duoforge.moves.heavy_slam (white-box): step G86 of the content expansion (decision 0015 5cn), Heavy Slam's base power by the
 * ratio of the user's weight to the target's, in hectograms, at the boundaries of each multiple (the pin's tests, >= on each).
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

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.moves.heavy_slam");
    test_heavy_slam_power(&t);
    return df_test_end(&t);
}
