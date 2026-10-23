/*
 * duoforge.moves.hard_press (white-box): step G86 of the content expansion (decision 0015 5cn), Hard Press's base power: the
 * pin's integer form of its formula, checked against the values of the pin's own double arithmetic (33 of 100 HP gives 32, not
 * 33; the full HP 100; the minimum 1).
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
    df_test_begin(&t, "duoforge.moves.hard_press");
    test_hard_press_power(&t);
    return df_test_end(&t);
}
