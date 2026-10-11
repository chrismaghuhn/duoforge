/*
 * duoforge.state.pool_g92 (white-box): step G92 of the content expansion (decision 0015 5cu, decision 0062).
 *
 * The branches are replayed by duoforge.reference.conformance_pool_data against the recorded battles g92_* (under "data": "pool"):
 * Confuse Ray into a foe (-start) and again on the confused foe (silent), Misty Terrain's -activate for a primary confusion,
 * Swagger's boost before its confusion, Teeter Dance on the adjacent Pokemon with Flatter's confusion and boost, the OHKO
 * moves (Sturdy's -immune, the miss, the KO with its -ohko line), Memento's two unboosts then the user's faint, Night Shade's
 * fixed damage, and Magic Bounce reflecting Confuse Ray (g92_cr_bounce).
 *
 * This file checks what the replay does not show by itself: the marks, the handler ids the rows carry, and that Gigaton Hammer
 * (dropped, decision 0062) is neither marked nor handled. The numbers of the handler ids come from the generator, so the test
 * compares the macros with the row of each move, never with a literal.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "support/check.h"

static void test_marks(df_test *t)
{
    /* The ten moves of the G92 handlers are marked. */
    static const uint32_t marked[] = {
        DFI_MOVE_CONFUSERAY, DFI_MOVE_SWAGGER, DFI_MOVE_FLATTER, DFI_MOVE_TEETERDANCE, DFI_MOVE_FISSURE,
        DFI_MOVE_GUILLOTINE, DFI_MOVE_HORNDRILL, DFI_MOVE_MEMENTO, DFI_MOVE_NIGHTSHADE,
    };
    for (size_t i = 0u; i < sizeof marked / sizeof marked[0]; ++i) {
        DF_CHECK_EQ_U64(t, dfi_support.moves[marked[i]], 1u);
    }
    /* Gigaton Hammer (decision 0062, dropped): cantusetwice is unmodelled, the row is UNMODELED and unmarked. */
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_GIGATONHAMMER], 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_GIGATONHAMMER].special, DFI_SPECIAL_UNMODELED);
}

static void test_handler_ids(df_test *t)
{
    /* Each handler id of the G92 rows is the one the generator gave it, and UNMODELED stays the last id. */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_CONFUSERAY].special, DFI_SPECIAL_CONFUSE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SWAGGER].special, DFI_SPECIAL_CONFUSE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_FLATTER].special, DFI_SPECIAL_CONFUSE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_TEETERDANCE].special, DFI_SPECIAL_CONFUSE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_FISSURE].special, DFI_SPECIAL_OHKO);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_GUILLOTINE].special, DFI_SPECIAL_OHKO);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_HORNDRILL].special, DFI_SPECIAL_OHKO);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_MEMENTO].special, DFI_SPECIAL_MEMENTO);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_NIGHTSHADE].special, DFI_SPECIAL_LEVEL_DAMAGE);
    /* Sheer Cold keeps its own id (step G64): the OHKO set is two ids, the Ice rule belongs to Sheer Cold only. */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SHEERCOLD].special, DFI_SPECIAL_SHEER_COLD);
    DF_CHECK(t, DFI_SPECIAL_CONFUSE < DFI_SPECIAL_UNMODELED);
    DF_CHECK(t, DFI_SPECIAL_OHKO < DFI_SPECIAL_UNMODELED);
    DF_CHECK(t, DFI_SPECIAL_MEMENTO < DFI_SPECIAL_UNMODELED);
    DF_CHECK(t, DFI_SPECIAL_LEVEL_DAMAGE < DFI_SPECIAL_UNMODELED);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g92");
    test_marks(&t);
    test_handler_ids(&t);
    return df_test_end(&t);
}
