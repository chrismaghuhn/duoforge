/*
 * duoforge.state.pool_g63 (white-box): step G63 of the content expansion, the simple Mega abilities (decision 0015, entry 5bj).
 *
 * Four Mega abilities become engine rows: Sand Force (data/abilities.ts:3956-3973: BasePower 5325/4096 for a Rock, Ground or
 * Steel move in Sandstorm, and the Sandstorm immunity), Shell Armor (4222-4228: onCriticalHit false, the crit roll is still taken),
 * Filter (1283-1294: the Solid Rock damage step) and Stalwart (4503-4513: the holder's single-target moves are not redirected).
 * Their Mega Stones are marked: Garchompite, Steelixite, Slowbronite, Scolipite, Aggronite and Skarmorite. Heracronite (Skill Link)
 * is not: Skill Link is dropped by the lead's decision (no modelled multi-hit move is in Heracross's learnset).
 *
 * The base abilities that the pinned Megas' formes carry and that stay unmarked (Steelix's Sheer Force, Slowbro's Own Tempo,
 * Scolipede's Poison Point, Aggron's Heavy Metal) are checked here as UNMODELLED: a team with one of them is refused, the Megas
 * stay reachable through the marked base abilities.
 *
 * The behaviour is covered by the recorded battles g63_* (test_conformance, which replays them with their draws), including the
 * control battle of the Shell Armor rule (the same seed, a holder without the ability takes the critical hit). The checks here are
 * the marks, the handlers, the links of the stones to their Megas, and the one fact that Stalwart's redirection rule depends on:
 * no marked move has the scripted target class (Stalwart does not change a scripted move's target at the pin, and the engine's
 * redirection only runs for the single-target classes).
 */
#include <stddef.h>
#include <stdint.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
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
 * Steelix's Sheer Force is no longer one of them: step G61 (decision 0015 5bi) made it an engine row (tests/test_pool_g61.c). */
static void test_unmarked_base_abilities_stay_unmodelled(df_test *t)
{
    static const uint32_t bases[] = {DFI_ABILITY_OWNTEMPO, DFI_ABILITY_POISONPOINT, DFI_ABILITY_HEAVYMETAL, DFI_ABILITY_GUTS};
    for (size_t i = 0u; i < sizeof bases / sizeof bases[0]; ++i) {
        DF_CHECK_EQ_U64(t, dfi_support.abilities[bases[i]], 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[bases[i]], DFI_HANDLER_UNMODELED);
    }
}

/* The six stones are marked, Heracronite is not, and each stone takes its base forme to its Mega (the manifest and the tables). */
static void test_mega_stones_g63(df_test *t)
{
    DF_CHECK(t, dfi_support.items[DFI_ITEM_GARCHOMPITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_STEELIXITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_SLOWBRONITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_SCOLIPITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_AGGRONITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_SKARMORITE] != 0u);
    DF_CHECK_EQ_U64(t, dfi_support.items[DFI_ITEM_HERACRONITE], 0u);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_GARCHOMP, DFI_ITEM_GARCHOMPITE + 1u), DFI_FORME_GARCHOMPMEGA);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_STEELIX, DFI_ITEM_STEELIXITE + 1u), DFI_FORME_STEELIXMEGA);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_SLOWBRO, DFI_ITEM_SLOWBRONITE + 1u), DFI_FORME_SLOWBROMEGA);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_SCOLIPEDE, DFI_ITEM_SCOLIPITE + 1u), DFI_FORME_SCOLIPEDEMEGA);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_AGGRON, DFI_ITEM_AGGRONITE + 1u), DFI_FORME_AGGRONMEGA);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_SKARMORY, DFI_ITEM_SKARMORITE + 1u), DFI_FORME_SKARMORYMEGA);
    DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_GARCHOMP, DFI_ITEM_GARCHOMPITE + 1u));
    DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_SKARMORY, DFI_ITEM_SKARMORITE + 1u));
}

/* Stalwart (the redirection of the holder's moves is skipped for the single-target classes only): no marked move has the scripted
 * target class, so a scripted move never meets the rule. A marked scripted move would need its own case (E_UNSUPPORTED for a
 * Stalwart holder), so this check fails first if one is marked. */
static void test_no_marked_scripted_move(df_test *t)
{
    for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
        if (dfi_support.moves[id] == 0u) {
            continue;
        }
        DF_CHECK(t, dfi_pool_moves[id].target_class != DFI_TARGET_CLASS_SCRIPTED);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g63");
    test_mega_abilities_are_engine_rows(&t);
    test_unmarked_base_abilities_stay_unmodelled(&t);
    test_mega_stones_g63(&t);
    test_no_marked_scripted_move(&t);
    return df_test_end(&t);
}
