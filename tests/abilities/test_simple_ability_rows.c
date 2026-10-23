/*
 * duoforge.abilities.simple_ability_rows (white-box): step G45 of the content expansion (decision 0015 entry 5ba), six
 * abilities of the simple kind as one batch: Steadfast, Moxie, Weak Armor, Telepathy, Volt Absorb and Punk Rock are engine rows
 * (ENGINE_ROWS) that src/combat/turn.c reads by id, marked in src/data/support_manifest.c with handler NONE. Breakable:
 * Telepathy, Volt Absorb and Punk Rock are; no marked ability ignores that flag (the Mold Breaker family is unmarked, Teravolt,
 * Turboblaze and Mycelium Might are not in the pool, and a move with ignoreAbility is UNMODELED). Punk Rock has no check of its
 * own: g45_punk_rock, Hyper Voice in both directions, is checked by the conformance comparison of its damage lines (the ability
 * shows no line).
 *
 * Split by subject from the test of step G45 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/turn.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

static void check_marks(df_test *t)
{
    static const uint32_t rows[] = {DFI_ABILITY_STEADFAST, DFI_ABILITY_MOXIE, DFI_ABILITY_WEAKARMOR, DFI_ABILITY_TELEPATHY,
                                    DFI_ABILITY_VOLTABSORB, DFI_ABILITY_PUNKROCK};
    for (size_t i = 0; i < sizeof rows / sizeof rows[0]; ++i) {
        DF_CHECK(t, dfi_support.abilities[rows[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[rows[i]], DFI_HANDLER_NONE);
    }
    /* the Mold Breaker family, which would ignore the breakable flag of Telepathy, Volt Absorb and Punk Rock, is unmarked */
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_MOLDBREAKER] == 0u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.simple_ability_rows");
    check_marks(&t);
    return df_test_end(&t);
}
