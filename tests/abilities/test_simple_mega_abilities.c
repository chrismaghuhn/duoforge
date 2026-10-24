/*
 * duoforge.abilities.simple_mega_abilities (white-box): step G63 of the content expansion (decision 0015 entry 5bj), the simple
 * Mega abilities as one batch: Sand Force (BasePower 5325/4096 for a Rock, Ground or Steel move in Sandstorm, and the Sandstorm
 * immunity), Shell Armor (onCriticalHit false, the crit roll is still taken), Filter (the Solid Rock damage step) and Stalwart
 * are marked engine rows (handler NONE), and the base abilities of their Megas' formes that stay unmarked (Slowbro's Own Tempo,
 * Aggron's Heavy Metal, Heracross's Guts) are UNMODELLED, the Megas reachable through the marked base abilities. The behaviour
 * is covered by the recorded battles g63_*, including the control battle of the Shell Armor rule.
 *
 * Split by subject from the test of step G63 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stddef.h>
#include <stdint.h>

#include <duoforge/duoforge.h>

#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "state/closure_member.h"
#include "support/check.h"

/* The four engine rows of step G63 are marked and their handler is NONE (read by id in src/combat/turn.c). */
static void test_mega_abilities_are_engine_rows(df_test *t)
{
    static const uint32_t rows[] = {DFI_ABILITY_SANDFORCE, DFI_ABILITY_SHELLARMOR, DFI_ABILITY_FILTER, DFI_ABILITY_STALWART};
    for (size_t i = 0u; i < sizeof rows / sizeof rows[0]; ++i) {
        DF_CHECK(t, dfi_support.abilities[rows[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[rows[i]], DFI_HANDLER_NONE);
    }
}

/* The base abilities that stay unmarked: Megas stay reachable through their marked base abilities (decision 0015 5bj).
 * Steelix's Sheer Force is no longer one of them: step G61 (decision 0015 5bi) made it an engine row (tests/abilities/test_sheer_force.c);
 * nor is Poison Point (Dragalge's): A2a (decision 0015 entry 5dy) made it one. */
static void test_unmarked_base_abilities_stay_unmodelled(df_test *t)
{
    static const uint32_t bases[] = {DFI_ABILITY_OWNTEMPO, DFI_ABILITY_HEAVYMETAL, DFI_ABILITY_GUTS};
    for (size_t i = 0u; i < sizeof bases / sizeof bases[0]; ++i) {
        DF_CHECK_EQ_U64(t, dfi_support.abilities[bases[i]], 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[bases[i]], DFI_HANDLER_UNMODELED);
    }
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_POISONPOINT] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_POISONPOINT], DFI_HANDLER_NONE);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.simple_mega_abilities");
    test_mega_abilities_are_engine_rows(&t);
    test_unmarked_base_abilities_stay_unmodelled(&t);
    return df_test_end(&t);
}
