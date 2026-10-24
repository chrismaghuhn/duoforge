/*
 * duoforge.interactions.rain_dish_friend_guard_rows (white-box): step G35 of the content expansion, ten data rows (Thunder
 * Punch, X-Scissor, Lumina Crash, Overdrive, Scorching Sands, Leaf Blade, Boomburst, Sludge Wave, Volt Tackle, Discharge) and
 * two small rules (Rain Dish and Friend Guard): the marks, that the two abilities are engine rows, the flags of the data rows
 * that other rules read (punch, slicing, sound), and Gigaton Hammer, left out of the step, unmarked because no learner of it
 * has a marked ability (the day one has, this test fails). The recorded battles g35_* are replayed by
 * duoforge.reference.conformance_pool_data.
 *
 * Split by subject from the test of step G35 (restructure step 6e; tests/renames.tsv maps the old name).
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
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

static void check_facts(df_test *t)
{
    static const uint32_t moves[] = {DFI_MOVE_THUNDERPUNCH, DFI_MOVE_XSCISSOR,   DFI_MOVE_LUMINACRASH, DFI_MOVE_OVERDRIVE,
                                     DFI_MOVE_SCORCHINGSANDS, DFI_MOVE_LEAFBLADE, DFI_MOVE_BOOMBURST,   DFI_MOVE_SLUDGEWAVE,
                                     DFI_MOVE_VOLTTACKLE,   DFI_MOVE_DISCHARGE};
    for (size_t i = 0u; i < sizeof moves / sizeof moves[0]; ++i) {
        DF_CHECK(t, dfi_support.moves[moves[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_moves[moves[i]].special, DFI_SPECIAL_NONE); /* data rows, no handler */
    }
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_RAINDISH] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_FRIENDGUARD] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_RAINDISH], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_FRIENDGUARD], DFI_HANDLER_NONE);
    /* the flags that other rules read: Iron Fist (punch), Sharpness (slicing), Soundproof and Throat Chop (sound) */
    DF_CHECK(t, (dfi_pool_move_flags2[DFI_MOVE_THUNDERPUNCH] & DFI_MOVE_FLAG2_PUNCH) != 0u);
    DF_CHECK(t, (dfi_pool_move_flags2[DFI_MOVE_XSCISSOR] & DFI_MOVE_FLAG2_SLICING) != 0u);
    DF_CHECK(t, (dfi_pool_move_flags2[DFI_MOVE_LEAFBLADE] & DFI_MOVE_FLAG2_SLICING) != 0u);
    DF_CHECK(t, (dfi_pool_move_flags2[DFI_MOVE_OVERDRIVE] & DFI_MOVE_FLAG2_SOUND) != 0u);
    DF_CHECK(t, (dfi_pool_move_flags2[DFI_MOVE_BOOMBURST] & DFI_MOVE_FLAG2_SOUND) != 0u);
    DF_CHECK(t, (dfi_pool_move_flags2[DFI_MOVE_VOLTTACKLE] & (DFI_MOVE_FLAG2_PUNCH | DFI_MOVE_FLAG2_SLICING)) == 0u);
    /* Gigaton Hammer (cantusetwice) is not part of the step: it is unmarked, and so is every ability of every forme that learns it */
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_GIGATONHAMMER] == 0u);
    uint32_t learners = 0u;
    for (uint32_t forme = 0u; forme < DFI_POOL_FORME_COUNT; ++forme) {
        const dfi_forme_legal *l = &dfi_pool_forme_legal[forme];
        if ((((uint32_t)l->learnable[DFI_MOVE_GIGATONHAMMER / 8u] >> (DFI_MOVE_GIGATONHAMMER % 8u)) & 1u) == 0u) {
            continue;
        }
        learners += 1u;
        DF_CHECK_EQ_U64(t, forme, DFI_FORME_TINKATON);
        for (uint32_t k = 0u; k < l->ability_count; ++k) {
            DF_CHECK(t, dfi_support.abilities[l->abilities[k]] == 0u);
        }
    }
    DF_CHECK_EQ_U64(t, learners, 1u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.interactions.rain_dish_friend_guard_rows");
    check_facts(&t);
    return df_test_end(&t);
}
