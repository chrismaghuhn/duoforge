/*
 * duoforge.state.pool_g58 (white-box): step G58 of the content expansion (decision 0015 item 5ax), Phantom Force.
 *
 * The behaviour is replayed by duoforge.reference.conformance_pool_data: eleven recorded battles (g58_* under "data": "pool")
 * cover the charge turn (a miss on the charging user, its charge line), the locked turn (the hit), the miss of a second charging
 * user before its own action, No Guard on the target and on the user, a Poison-type Toxic, the break of Protect and Quick Guard
 * (the target's side and the ally's), Coaching and an Earthquake that miss the charging ally, Choice Scarf's lock, and a flinch
 * that cancels the charge. This file checks what the tables and the support gate say about the move: the row, its handler id,
 * its flags, and that Protect does not stop it (no protect flag). Power Herb has no row in the pool tables (its ChargeMove skip,
 * data/items.ts:4776-4783, is not modelled), so no team can hold it.
 */
#include <stdio.h>

#include <duoforge/duoforge.h>

#include "data/closure_tables.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "support/check.h"

static void test_row(df_test *t)
{
    const dfi_move_data *m = &dfi_pool_moves[DFI_MOVE_PHANTOMFORCE];
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_PHANTOM_FORCE, 82u);
    DF_CHECK_EQ_U64(t, m->special, DFI_SPECIAL_PHANTOM_FORCE);
    DF_CHECK_EQ_U64(t, m->base_power, 90u);
    DF_CHECK_EQ_U64(t, m->accuracy, 100u);
    DF_CHECK_EQ_U64(t, m->type, DFI_TYPE_GHOST);
    DF_CHECK_EQ_U64(t, m->category, DFI_CATEGORY_PHYSICAL);
    DF_CHECK_EQ_U64(t, m->priority, DFI_PRIORITY_BIAS);
    /* contact and charge (the two-turn flag); no protect flag, so Protect does not stop the move (checkMoveBypassesProtect) */
    DF_CHECK(t, (m->flags & DFI_MOVE_FLAG_CONTACT) != 0u);
    DF_CHECK(t, (m->flags & DFI_MOVE_FLAG_CHARGE) != 0u);
    DF_CHECK(t, (m->flags & DFI_MOVE_FLAG_PROTECT) == 0u);
    /* the handler is marked, and the table row's unmodelled marker is gone (it is a row of the support manifest only) */
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_PHANTOMFORCE], 1u);
    /* the unmodelled handler id is the one after Phantom Force */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, 83u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g58");
    test_row(&t);
    return df_test_end(&t);
}
