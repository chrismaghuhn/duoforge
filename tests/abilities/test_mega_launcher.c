/*
 * duoforge.abilities.mega_launcher (white-box): step G59 of the content expansion (decision 0015 entry 5bh), the public static
 * flag PULSE that Mega Launcher reads (pulse moves x1.5, BasePower priority 19): the pulse moves of the pool carry it, the
 * others do not.
 *
 * Split by subject from the test of step G59 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include "combat/damage_chain.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"
/* ---- Mega Launcher reads the public static flag PULSE of the pool row (decision 0020) */
static void check_pulse(df_test *t)
{
    static const uint32_t pulse[] = {DFI_MOVE_AURASPHERE, DFI_MOVE_DARKPULSE, DFI_MOVE_WATERPULSE};
    for (size_t i = 0u; i < sizeof pulse / sizeof pulse[0]; ++i) {
        DF_CHECK(t, (dfi_pool_move_static_flags[pulse[i]] & DUOFORGE_MOVE_STATIC_FLAG_PULSE) != 0u);
    }
    DF_CHECK_EQ_U64(t, dfi_pool_move_static_flags[DFI_MOVE_SOLARBEAM] & DUOFORGE_MOVE_STATIC_FLAG_PULSE, 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_move_static_flags[DFI_MOVE_SUNNYDAY] & DUOFORGE_MOVE_STATIC_FLAG_PULSE, 0u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.mega_launcher");
    check_pulse(&t);
    return df_test_end(&t);
}
