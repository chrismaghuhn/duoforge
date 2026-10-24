/*
 * duoforge.interactions.multi_hit_mirror_armor_rows (white-box): step G33 of the content expansion, the multi-hit moves Dual
 * Wingbeat, Twin Beam and Triple Axel and the ability Mirror Armor: the marks and the handler numbers (the hit counts are in
 * the handler ids; the static hit columns have no reader in the engine, duoforge.data.static_unread checks that), and Triple
 * Axel's accuracy 90. The recorded battles g33_* are replayed by duoforge.reference.conformance_pool_data.
 *
 * Split by subject from the test of step G33 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/moves/multiaccuracy.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

static void check_facts(df_test *t)
{
    static const uint32_t moves[] = {DFI_MOVE_DUALWINGBEAT, DFI_MOVE_TRIPLEAXEL, DFI_MOVE_TWINBEAM};
    for (size_t i = 0u; i < sizeof moves / sizeof moves[0]; ++i) {
        DF_CHECK(t, dfi_support.moves[moves[i]] != 0u);
    }
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_MIRRORARMOR] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_MIRRORARMOR], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_DUALWINGBEAT].special, DFI_SPECIAL_MULTI_HIT_2);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_TWINBEAM].special, DFI_SPECIAL_MULTI_HIT_2);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_TRIPLEAXEL].special, DFI_SPECIAL_TRIPLE_AXEL);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_TRIPLE_AXEL, DFI_SPECIAL_MULTI_HIT_2 + 1u);
    /* Population Bomb is not one of this step's rows: step G48 marks it (MULTI_HIT_10, tests/moves/test_hits_taken_hazard_moves.c) */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_TRIPLEAXEL].accuracy, 90u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.interactions.multi_hit_mirror_armor_rows");
    check_facts(&t);
    return df_test_end(&t);
}
