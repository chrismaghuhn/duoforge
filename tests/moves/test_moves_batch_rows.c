/*
 * duoforge.moves.moves_batch_rows (white-box): step G54 of the content expansion (decision 0015, the moves batch), in the POOL
 * build, as one batch: six handlers (Icicle Spear and Scale Shot, a hit count of 2 to 5 drawn from the Champions sample; Quick
 * Guard, the side guard of decision 0029; Upper Hand; Heal Pulse; Strength Sap) and the data row Sing. Their marks, handler
 * numbers and pinned numbers; what stays unmarked and why (Skill Link and Loaded Dice, whose hit-count rules are not modelled;
 * Steel Beam, Final Gambit and Mega Launcher, dropped here, are marked by later steps); and the constants the rows depend on
 * (the draw site of the hit count, the BLOCKED detail of Quick Guard, its side guard bit and the view's feature bit). The
 * recorded battles g54_* are replayed by duoforge.reference.conformance_pool_data.
 *
 * Split by subject from the test of step G54 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/moves/multihit.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

static void check_marks(df_test *t)
{
    static const uint32_t moves[] = {
        DFI_MOVE_ICICLESPEAR, DFI_MOVE_SCALESHOT, DFI_MOVE_QUICKGUARD, DFI_MOVE_UPPERHAND,
        DFI_MOVE_HEALPULSE,   DFI_MOVE_STRENGTHSAP, DFI_MOVE_SING,
    };
    for (size_t i = 0u; i < sizeof moves / sizeof moves[0]; ++i) {
        DF_CHECK(t, dfi_support.moves[moves[i]] != 0u);
    }
    /* the handlers are the ids after the step G44 ones (Tri Attack is 70), in this order; Sing is a data row */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_ICICLESPEAR].special, DFI_SPECIAL_MULTI_HIT_2_5);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SCALESHOT].special, DFI_SPECIAL_SCALE_SHOT);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_QUICKGUARD].special, DFI_SPECIAL_QUICK_GUARD);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_UPPERHAND].special, DFI_SPECIAL_UPPER_HAND);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_HEALPULSE].special, DFI_SPECIAL_HEAL_PULSE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_STRENGTHSAP].special, DFI_SPECIAL_STRENGTH_SAP);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SING].special, DFI_SPECIAL_NONE);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_MULTI_HIT_2_5, DFI_SPECIAL_REVIVAL_BLESSING + 1u); /* after Revival Blessing (G52) */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_SCALE_SHOT, DFI_SPECIAL_MULTI_HIT_2_5 + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_QUICK_GUARD, DFI_SPECIAL_SCALE_SHOT + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UPPER_HAND, DFI_SPECIAL_QUICK_GUARD + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_HEAL_PULSE, DFI_SPECIAL_UPPER_HAND + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_STRENGTH_SAP, DFI_SPECIAL_HEAL_PULSE + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_HAZE, DFI_SPECIAL_SHEER_COLD + 1u); /* step G62 (decision 0031), after the four of G64 */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_SPEED_SWAP + 1u /* G72b: after Alluring Voice and Dragon Cheer */); /* step G60 (decision 0032) comes after Quash */ /* G62 added Haze, After You and Quash after it */
}

/* The pinned numbers that the rows of this step depend on (data/moves.ts; the Champions mod changes none of them). */
static void check_pins(df_test *t)
{
    const dfi_move_data *ice = &dfi_pool_moves[DFI_MOVE_ICICLESPEAR];
    DF_CHECK_EQ_U64(t, ice->accuracy, 100u);
    DF_CHECK_EQ_U64(t, ice->base_power, 25u);
    DF_CHECK_EQ_U64(t, ice->category, DFI_CATEGORY_PHYSICAL);
    const dfi_move_data *sc = &dfi_pool_moves[DFI_MOVE_SCALESHOT];
    DF_CHECK_EQ_U64(t, sc->accuracy, 90u);
    DF_CHECK_EQ_U64(t, sc->base_power, 25u);
    const dfi_move_data *qg = &dfi_pool_moves[DFI_MOVE_QUICKGUARD];
    DF_CHECK_EQ_U64(t, qg->priority, DFI_PRIORITY_BIAS + 3u);
    DF_CHECK_EQ_U64(t, qg->category, DFI_CATEGORY_STATUS);
    const dfi_move_data *uh = &dfi_pool_moves[DFI_MOVE_UPPERHAND];
    DF_CHECK_EQ_U64(t, uh->base_power, 65u);
    DF_CHECK_EQ_U64(t, uh->priority, DFI_PRIORITY_BIAS + 3u);
    DF_CHECK_EQ_U64(t, uh->sec_chance, 100u);
    DF_CHECK_EQ_U64(t, uh->sec_kind, DFI_SECONDARY_VOLATILE);
    const dfi_move_data *hp = &dfi_pool_moves[DFI_MOVE_HEALPULSE];
    DF_CHECK_EQ_U64(t, hp->category, DFI_CATEGORY_STATUS);
    const dfi_move_data *ss = &dfi_pool_moves[DFI_MOVE_STRENGTHSAP];
    DF_CHECK_EQ_U64(t, ss->accuracy, 100u);
    DF_CHECK_EQ_U64(t, ss->category, DFI_CATEGORY_STATUS);
}

/* The rows that stay out of this build (the step's drops and the guards): no mark, and no battle can reach them. */
static void check_unmarked(df_test *t)
{
    /* Haze was unmarked here until step G62 (decision 0031) marked it; its check is in duoforge.moves.haze */
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_STEELBEAM] != 0u); /* marked by step G68 (decision 0015 item 5cc): the drop of G54 is no longer dropped */
    /* Final Gambit was dropped by G54 and is marked by step G76 (decision 0015 5cg): its check is in duoforge.state.pool_g76 */
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_FINALGAMBIT] != 0u);
    /* the ability whose rule would change a hit count (Skill Link: the maximum) stays unmarked. Mega Launcher was left unmarked
     * here until step G59: its two rules now live in src/combat/turn.c (the pulse BasePower by the flags3 bit PULSE, and Heal
     * Pulse's three quarters in dfi_run_heal_fraction), pinned by tests/abilities/test_mega_launcher.c and the recorded battle g59_heal_pulse. */
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_SKILLLINK], 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_MEGALAUNCHER] != 0u);
    /* Loaded Dice raises the hit count in the same draw: an item of the pool would be marked only with that rule */
    static const char *const items[] = {"loadeddice"};
    for (uint32_t i = 0u; i < DFI_POOL_ITEM_COUNT; ++i) {
        const char *n = dfi_pool_item_names[i];
        for (size_t k = 0u; n != NULL && k < sizeof items / sizeof items[0]; ++k) {
            if (strcmp(n, items[k]) == 0) {
                DF_CHECK_EQ_U64(t, dfi_support.items[i], 0u);
            }
        }
    }
}

/* The constants that the rows and their draws depend on. */
static void check_constants(df_test *t)
{
    DF_CHECK_EQ_U64(t, DFI_SITE_MULTIHIT_COUNT, 22u /* site 20 is the G46 drag, 21 the G56 lock */);
    DF_CHECK_EQ_U64(t, DFI_SITE_COUNT, 34u); /* step G73 adds Moody's sample (site 23), step G80 Ally Switch (site 33) */
    DF_CHECK_EQ_U64(t, DUOFORGE_BLOCK_QUICK_GUARD, 6u); /* decision 0029 */
    DF_CHECK_EQ_U64(t, DUOFORGE_SIDE_GUARD_QUICK_GUARD, 2u);
    DF_CHECK_EQ_U64(t, DUOFORGE_VIEWEXT_FEATURE_QUICK_GUARD, 38u);
    DF_CHECK(t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_QUICK_GUARD)) != 0u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.moves.moves_batch_rows");
    check_marks(&t);
    check_pins(&t);
    check_unmarked(&t);
    check_constants(&t);
    return df_test_end(&t);
}
