/*
 * duoforge.state.pool_g61 (white-box): step G61 of the content expansion (decision 0015 item 5bi), Sheer Force, Cameruptite and
 * Feraligite, and Dragonize as the Mega ability of Feraligatr.
 *
 * Sheer Force (data/abilities.ts:4202-4221) strips the secondaries and self effects of a move that has secondaries (and is not
 * hasSheerForceBoost), and gives it x5325/4096; Electro Shot gets the multiplier only. The predicates are in combat/sheer_force.h.
 * The battles (g61_* under "data": "pool") are compared draw by draw by duoforge.reference.conformance_pool_data; this file checks
 * what the battles do not show by themselves:
 *   - the marks: Sheer Force, Dragonize, Cameruptite and Feraligite;
 *   - the predicates on every pool move: the stripped set and the boost set are exactly the pinned ones (the generator checks the
 *     same sets against the pin for every pool move, marked or not, in tools/datagen/pool_families.js checkG61);
 *   - the named moves of each kind, so that a changed column shows here as a name, not as a count alone;
 *   - a holder without Sheer Force strips and boosts nothing.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/sheer_force.h"
#include "core/modifier.h"
#include "data/closure_tables.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "support/check.h"

/* The pinned counts of checkG61 (tools/datagen/pool_families.js): the pool moves that Sheer Force strips, and the boost-only one. */
#define G61_PINNED_STRIPPED 103u /* the 511 pool moves, marked or not (G72b's Alluring Voice adds one: its secondary is stripped too; 102 at G61) */
#define G61_PINNED_BOOST_ONLY 1u

static void check_marks(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_SHEERFORCE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_DRAGONIZE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_CAMERUPTITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_FERALIGITE] != 0u);
    /* the rows the step leaves alone: Magma Armor and Anger Point (Camerupt's other abilities), Shell Bell (the forceSwitchFlag gate
     * of G46) and Wimp Out have no mark, so no battle can carry them */
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_MAGMAARMOR] != 0u ? 1u : 0u, 0u);
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_ANGERPOINT] != 0u ? 1u : 0u, 0u);
    DF_CHECK_EQ_U64(t, dfi_support.items[DFI_ITEM_SHELLBELL] != 0u ? 1u : 0u, 0u);
}

/* The move named by its id, with the strip and boost of a Sheer Force holder. */
static void check_named(df_test *t, uint32_t move, bool strips, bool boosts)
{
    const dfi_move_data *md = &dfi_pool_moves[move];
    DF_CHECK_EQ_U64(t, dfi_sf_strips_move(true, md) ? 1u : 0u, strips ? 1u : 0u);
    DF_CHECK_EQ_U64(t, dfi_sf_boosts_move(true, md) ? 1u : 0u, boosts ? 1u : 0u);
    /* without Sheer Force nothing is stripped or boosted */
    DF_CHECK_EQ_U64(t, dfi_sf_strips_move(false, md) ? 1u : 0u, 0u);
    DF_CHECK_EQ_U64(t, dfi_sf_boosts_move(false, md) ? 1u : 0u, 0u);
}

static void check_named_moves(df_test *t)
{
    /* stripped by a chance secondary, of every kind of effect */
    check_named(t, DFI_MOVE_FLAMETHROWER, true, true);  /* status, 10 */
    check_named(t, DFI_MOVE_SHADOWBALL, true, true);    /* boosts, 20 */
    check_named(t, DFI_MOVE_AIRSLASH, true, true);      /* volatile flinch, 30 */
    check_named(t, DFI_MOVE_DIRECLAW, true, true);      /* onHit and the pick, Champions override */
    check_named(t, DFI_MOVE_THROATCHOP, true, true);    /* the lockout, chance 100 */
    check_named(t, DFI_MOVE_PSYCHICNOISE, true, true);  /* the heal block */
    check_named(t, DFI_MOVE_FAKEOUT, true, true);       /* the flinch, chance 100 */
    check_named(t, DFI_MOVE_THUNDER, true, true);       /* a status with its own accuracy rule */
    check_named(t, DFI_MOVE_BLIZZARD, true, true);      /* a status with its own rule in snow */
    /* a secondary of the move's self: Ancient Power, Fiery Dance, Meteor Mash */
    check_named(t, DFI_MOVE_ANCIENTPOWER, true, true);
    check_named(t, DFI_MOVE_FIERYDANCE, true, true);
    check_named(t, DFI_MOVE_METEORMASH, true, true);
    /* placeholders and the special handlers */
    check_named(t, DFI_MOVE_STONEAXE, true, true);
    check_named(t, DFI_MOVE_CEASELESSEDGE, true, true);
    check_named(t, DFI_MOVE_ICEFANG, true, true);
    check_named(t, DFI_MOVE_TRIATTACK, true, true);
    /* boost-only: the multiplier and nothing deleted */
    check_named(t, DFI_MOVE_ELECTROSHOT, false, true);
    /* not affected at all: self-only effects (the pin strips none of them), recoil, drain, onAfterHit without a secondary */
    check_named(t, DFI_MOVE_CLOSECOMBAT, false, false);
    check_named(t, DFI_MOVE_OVERHEAT, false, false);
    check_named(t, DFI_MOVE_HYPERBEAM, false, false);  /* the recharge is a self effect too */
    check_named(t, DFI_MOVE_HAMMERARM, false, false);
    check_named(t, DFI_MOVE_KNOCKOFF, false, false);
    check_named(t, DFI_MOVE_THIEF, false, false);
    check_named(t, DFI_MOVE_BRAVEBIRD, false, false);
    check_named(t, DFI_MOVE_WOODHAMMER, false, false);
    check_named(t, DFI_MOVE_FREEZEDRY, false, false);  /* the Champions override has no secondary */
    check_named(t, DFI_MOVE_STRUGGLE, false, false);
}

/* Every pool move, marked or not: the counts of the stripped and boost-only moves are the pinned ones. */
static void check_pool_counts(df_test *t)
{
    uint32_t stripped = 0u, boost_only = 0u;
    for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
        const dfi_move_data *md = &dfi_pool_moves[id];
        if (dfi_sf_strips_move(true, md)) {
            stripped += 1u;
        }
        if (dfi_sf_boosts_move(true, md) && !dfi_sf_strips_move(true, md)) {
            boost_only += 1u;
        }
    }
    DF_CHECK_EQ_U64(t, stripped, G61_PINNED_STRIPPED);
    DF_CHECK_EQ_U64(t, boost_only, G61_PINNED_BOOST_ONLY);
}

/* The multiplier itself (data/abilities.ts:4215, chainModify([5325, 4096])), pinned directly: the constant is 5325 over
 * 4096, a base power of 100 becomes 130 (tr((tr(100 * 5325) + 2047) / 4096)), and the chain from 4096 gives the constant. */
static void check_multiplier(df_test *t)
{
    DF_CHECK_EQ_U64(t, DFI_SHEER_FORCE_MODIFIER, 5325u);
    uint32_t chained = 0u;
    DF_CHECK(t, dfi_chain_modify(4096u, DFI_SHEER_FORCE_MODIFIER, &chained));
    DF_CHECK_EQ_U64(t, chained, 5325u);
    DF_CHECK_EQ_U64(t, dfi_modify(100u, DFI_SHEER_FORCE_MODIFIER), 130u);
    DF_CHECK_EQ_U64(t, dfi_modify(200u, DFI_SHEER_FORCE_MODIFIER), 260u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g61");
    check_marks(&t);
    check_named_moves(&t);
    check_pool_counts(&t);
    check_multiplier(&t);
    return df_test_end(&t);
}
