/*
 * duoforge.state.pool_g39 (white-box): step G39 of the content expansion, thirteen abilities (Hyper Cutter, Scrappy, Infiltrator,
 * Queenly Majesty, Damp, Sturdy, Snow Cloak, Sand Veil, Static, Justified, Limber, Solar Power, Regenerator) and four moves
 * (Charm, Fake Tears, Sacred Sword, Super Fang).
 *
 * The recorded battles (g39_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data with the reference's
 * draws. Here are the facts that they do not show:
 *
 *   - the marks and the table rows: the abilities are engine rows (no handler), Sacred Sword has Darkest Lariat's handler, Super
 *     Fang its own (SUPER_FANG), Charm and Fake Tears are data with the boost role PRIMARY_TARGET;
 *   - what keeps two of the abilities inert: Damp's callbacks only stop Explosion, Self-Destruct, Misty Explosion and Mind Blown
 *     and nullify Aftermath, and Sturdy's second callback makes it immune to the moves with the pin's `ohko` field; no such move
 *     and no Aftermath is marked, so no battle can reach what the engine does not model (marking one needs its rule first);
 *   - the TryBoost orders that the engine does not compute: Hyper Cutter shares the event with Flower Veil's handler, so no
 *     Pokemon of the pool that can have Hyper Cutter is a Grass type (a Flower Veil holder protects Grass types of its side);
 *   - Limber's onUpdate, which cures a paralysis that its holder has: the abilities that give or copy it are Limber itself and
 *     Trace (dfi_trace refuses a paralysed holder that copies it), and no other marked ability or item sets paralysis on a
 *     holder of Limber except a move, whose status Limber refuses.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "rng/draw.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

static uint32_t move_named(const char *name)
{
    for (uint32_t m = 0u; m < DFI_POOL_MOVE_COUNT; ++m) {
        if (strcmp(dfi_pool_move_names[m], name) == 0) {
            return m;
        }
    }
    return UINT32_MAX;
}

static void check_marks(df_test *t)
{
    static const uint32_t abilities[] = {DFI_ABILITY_HYPERCUTTER, DFI_ABILITY_SCRAPPY,      DFI_ABILITY_INFILTRATOR,
                                         DFI_ABILITY_QUEENLYMAJESTY, DFI_ABILITY_DAMP,       DFI_ABILITY_STURDY,
                                         DFI_ABILITY_SNOWCLOAK,   DFI_ABILITY_SANDVEIL,     DFI_ABILITY_STATIC,
                                         DFI_ABILITY_JUSTIFIED,   DFI_ABILITY_LIMBER,       DFI_ABILITY_SOLARPOWER,
                                         DFI_ABILITY_REGENERATOR};
    for (size_t i = 0u; i < sizeof abilities / sizeof abilities[0]; ++i) {
        DF_CHECK(t, dfi_support.abilities[abilities[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[abilities[i]], DFI_HANDLER_NONE);
    }
    static const uint32_t moves[] = {DFI_MOVE_CHARM, DFI_MOVE_FAKETEARS, DFI_MOVE_SACREDSWORD, DFI_MOVE_SUPERFANG};
    for (size_t i = 0u; i < sizeof moves / sizeof moves[0]; ++i) {
        DF_CHECK(t, dfi_support.moves[moves[i]] != 0u);
    }
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SACREDSWORD].special, DFI_SPECIAL_DARKEST_LARIAT);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SUPERFANG].special, DFI_SPECIAL_SUPER_FANG);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_DRAGON_CHEER + 1u /* G72b: after Alluring Voice and Dragon Cheer */) /* G62: After You and Quash (decision 0015 entry 5az) come after Strength Sap */; /* Taunt and Yawn (G31), the four of G48, the four of G44, Double Shock (G50) and Roost and Stomping Tantrum (G42) follow */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SUPERFANG].base_power, 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SUPERFANG].accuracy, 90u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_CHARM].boost_role, DFI_BOOST_ROLE_PRIMARY_TARGET);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_FAKETEARS].boost_role, DFI_BOOST_ROLE_PRIMARY_TARGET);
    DF_CHECK_EQ_U64(t, DFI_BOOST_ROLE_PRIMARY_TARGET, DFI_BOOST_ROLE_SECONDARY_SELF + 1u);
    /* Charm: Attack -2, Fake Tears: Special Defense -2, both at 100 accuracy at one target */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_CHARM].boosts[0], 4u); /* the stat order atk, def, spa, spd, spe; biased by 6 */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_FAKETEARS].boosts[3], 4u);
    /* Static's draw is the site 19 (Flame Body has 18, 17 is Cursed Body's) */
    DF_CHECK_EQ_U64(t, DFI_SITE_STATIC, 19u);
    DF_CHECK_EQ_U64(t, DFI_SITE_COUNT, 24u); /* step G46 adds the drag (site 20), step G54 the multi-hit count (site 22), step G73 Moody (site 23) */
}

/* Damp and Sturdy are inert only while what they would act on is unmarked. */
static void check_inert(df_test *t)
{
    static const char *const explosive[] = {"explosion", "selfdestruct", "mistyexplosion", "mindblown"};
    /* Sheer Cold is no longer in this list: step G64 marks it (ohko 'Ice', decision 0015 item 5ca); the others stay unmodelled. */
    static const char *const ohko[] = {"fissure", "guillotine", "horndrill"};
    for (size_t i = 0u; i < sizeof explosive / sizeof explosive[0]; ++i) {
        const uint32_t m = move_named(explosive[i]);
        if (m != UINT32_MAX) {
            DF_CHECK_EQ_U64(t, dfi_support.moves[m], 0u);
        }
    }
    for (size_t i = 0u; i < sizeof ohko / sizeof ohko[0]; ++i) {
        const uint32_t m = move_named(ohko[i]);
        if (m != UINT32_MAX) {
            DF_CHECK_EQ_U64(t, dfi_support.moves[m], 0u);
            DF_CHECK_EQ_U64(t, dfi_pool_moves[m].special, DFI_SPECIAL_UNMODELED); /* the generator refuses the field */
        }
    }
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_AFTERMATH], 0u);
    /* Mold Breaker, which Hyper Cutter, Sturdy, Damp, Snow Cloak, Sand Veil, Limber and Queenly Majesty are breakable against,
     * is unmarked */
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_MOLDBREAKER], 0u);
}

/* A Hyper Cutter holder that is a Grass type would meet Flower Veil's TryBoost handler of a partner in an order that the engine
 * does not compute. */
static void check_hyper_cutter_not_grass(df_test *t)
{
    uint32_t holders = 0u;
    for (uint32_t forme = 0u; forme < DFI_POOL_FORME_COUNT; ++forme) {
        const dfi_forme_legal *l = &dfi_pool_forme_legal[forme];
        bool has = false;
        for (uint32_t k = 0u; k < l->ability_count; ++k) {
            has = has || l->abilities[k] == DFI_ABILITY_HYPERCUTTER;
        }
        if (!has) {
            continue;
        }
        holders += 1u;
        DF_CHECK(t, dfi_pool_formes[forme].types[0] != DFI_TYPE_GRASS && dfi_pool_formes[forme].types[1] != DFI_TYPE_GRASS);
    }
    DF_CHECK(t, holders >= 4u); /* Pinsir, Mawile, Gliscor, Crabominable and their Megas */
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g39");
    check_marks(&t);
    check_inert(&t);
    check_hyper_cutter_not_grass(&t);
    return df_test_end(&t);
}
