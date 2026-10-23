/*
 * duoforge.moves.tri_attack (white-box): step G44 of the content expansion (decision 0015 item 5an), Tri Attack's chance (20 of
 * random(100), combat/moves/tri_attack.h): the roll 19 passes and 20 fails, at both edges and at the ends. No recorded battle
 * has a roll of 19 on that draw.
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

/* The Tri Attack chance (20 of random(100)): the roll 19 passes, 20 fails, at both edges and at the ends. No recorded battle has
 * a roll of 19 on that draw, so the edges are checked here (combat/moves/tri_attack.h). */
static void check_tri_attack_edges(df_test *t)
{
    DF_CHECK(t, dfi_tri_attack_chance_hit(0u));
    DF_CHECK(t, dfi_tri_attack_chance_hit(19u));
    DF_CHECK(t, !dfi_tri_attack_chance_hit(20u));
    DF_CHECK(t, !dfi_tri_attack_chance_hit(99u));
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.moves.tri_attack");
    check_tri_attack_edges(&t);
    return df_test_end(&t);
}
