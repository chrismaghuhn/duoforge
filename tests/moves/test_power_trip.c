/*
 * duoforge.moves.power_trip (white-box): step G44 of the content expansion (decision 0015 item 5an), Power Trip's
 * positive-stage sum (combat/moves/power_trip.h), white-box: every stat counts, accuracy and evasion too, a negative stage adds
 * nothing, from 0 to 42. The recorded battles carry two stages of attack and defense only, so the other stats are checked here.
 *
 * Split by subject from the test of step G44 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/moves/power_trip.h"
#include "combat/moves/tri_attack.h"
#include "data/formats/reg-mc/closure_tables.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "support/check.h"
#include "support/pool.h"

/* Power Trip's positive-stage sum: every stat counts, accuracy and evasion too (Coil raises accuracy, and the five-stat
 * mutant of the decision is caught here), a negative stage adds nothing. Stored stages are biased by DFI_STAGE_NEUTRAL. */
static void check_power_trip_stages(df_test *t)
{
    uint8_t s[DFI_STAT_STAGE_COUNT];
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        s[i] = DFI_STAGE_NEUTRAL;
    }
    DF_CHECK_EQ_U64(t, dfi_power_trip_positive_stages(s), 0u);
    for (uint32_t k = 0u; k < DFI_STAT_STAGE_COUNT; ++k) {
        s[k] = (uint8_t)(DFI_STAGE_NEUTRAL + 1u);
        DF_CHECK_EQ_U64(t, dfi_power_trip_positive_stages(s), 1u);
        s[k] = DFI_STAGE_NEUTRAL;
    }
    s[DFI_STAGE_ACCURACY] = (uint8_t)(DFI_STAGE_NEUTRAL + 2u);
    s[DFI_STAGE_EVASION] = (uint8_t)(DFI_STAGE_NEUTRAL + 1u);
    DF_CHECK_EQ_U64(t, dfi_power_trip_positive_stages(s), 3u);
    s[DFI_STAGE_ATK] = (uint8_t)(DFI_STAGE_NEUTRAL + 2u);
    s[DFI_STAGE_DEF] = 0u; /* -6 */
    DF_CHECK_EQ_U64(t, dfi_power_trip_positive_stages(s), 5u);
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        s[i] = (uint8_t)(DFI_STAGE_NEUTRAL + DFI_STAGE_NEUTRAL); /* +6 */
    }
    DF_CHECK_EQ_U64(t, dfi_power_trip_positive_stages(s), 42u);
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        s[i] = 0u; /* -6 */
    }
    DF_CHECK_EQ_U64(t, dfi_power_trip_positive_stages(s), 0u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.moves.power_trip");
    check_power_trip_stages(&t);
    return df_test_end(&t);
}
