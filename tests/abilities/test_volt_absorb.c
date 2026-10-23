/*
 * duoforge.abilities.volt_absorb (white-box): step G45 of the content expansion (decision 0015 entry 5ba), Volt Absorb: replays
 * g45_volt_absorb, where a Thunderbolt at full HP is absorbed (no heal, Jolteon stays full) and, after an Earthquake, the next
 * Thunderbolt heals Jolteon by a quarter of its maximum HP.
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
#include "support/conformance_replay.h"
#include "support/fixtures.h"
#include "support/pool.h"
/* Volt Absorb: at full HP the first Thunderbolt is absorbed (Jolteon, side 1 position 0, stays at full HP); after the Earthquake
 * of the second turn the third turn's Thunderbolt heals it by a quarter of its maximum HP (the trace: 44 -> 87 of 172). */
static void check_volt_absorb(df_test *t, const duoforge_context *ctx)
{
    /* after the first turn: Raichu's Thunderbolt at full HP is absorbed, Jolteon (side 1, position 0) stays at full HP */
    duoforge_battle *b = df_conf_replay_by_name(t, ctx, "g45_volt_absorb", 2u);
    if (b != NULL) {
        const dfi_member *jolteon = &b->sides[1].members[b->sides[1].positions[0].occupant];
        DF_CHECK_EQ_U64(t, jolteon->hp, jolteon->hp_max);
        duoforge_battle_destroy(b);
    }
    /* after the second turn (Garchomp's Earthquake) and its Leftovers: Jolteon is hurt */
    b = df_conf_replay_by_name(t, ctx, "g45_volt_absorb", 3u);
    if (b == NULL) {
        return;
    }
    const uint32_t before = b->sides[1].members[b->sides[1].positions[0].occupant].hp;
    DF_CHECK(t, before < b->sides[1].members[b->sides[1].positions[0].occupant].hp_max);
    duoforge_battle_destroy(b);
    /* the third turn: Volt Absorb heals a quarter of the maximum HP (43 of 172), then Leftovers a sixteenth (10) */
    b = df_conf_replay_by_name(t, ctx, "g45_volt_absorb", 4u);
    if (b == NULL) {
        return;
    }
    const dfi_member *jolteon = &b->sides[1].members[b->sides[1].positions[0].occupant];
    DF_CHECK_EQ_U64(t, jolteon->hp, before + jolteon->hp_max / 4u + jolteon->hp_max / 16u);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.volt_absorb");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_volt_absorb(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
