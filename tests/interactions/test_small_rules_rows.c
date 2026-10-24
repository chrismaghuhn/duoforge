/*
 * duoforge.interactions.small_rules_rows (white-box): step G34 of the content expansion, a batch of small rules (Gale Wings,
 * Compound Eyes, Wide Lens, Technician, Iron Fist, Sharpness, Solid Rock, Multiscale, Steel Roller, Clangorous Soul, Brick
 * Break) and the data rows Fiery Dance, Psycho Cut, Iron Defense and Electroweb: the marks, the special numbers of the three
 * new handlers and the two new bits of the second flags byte (punch and slicing: internal; the engine must not read decision
 * 0020's static column, which duoforge.data.static_unread checks), carried by exactly the punch and slicing moves of the pin,
 * whatever their power. The recorded battles g34_* are replayed by duoforge.reference.conformance_pool_data.
 *
 * Split by subject from the test of step G34 (restructure step 6e; tests/renames.tsv maps the old name).
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
    DF_CHECK_EQ_U64(t, DFI_MOVE_FLAG2_PUNCH, 32u);
    DF_CHECK_EQ_U64(t, DFI_MOVE_FLAG2_SLICING, 64u);
    /* the marks */
    static const uint32_t moves[] = {DFI_MOVE_STEELROLLER, DFI_MOVE_CLANGOROUSSOUL, DFI_MOVE_BRICKBREAK, DFI_MOVE_FIERYDANCE,
                                     DFI_MOVE_PSYCHOCUT,   DFI_MOVE_IRONDEFENSE,    DFI_MOVE_ELECTROWEB};
    for (size_t i = 0u; i < sizeof moves / sizeof moves[0]; ++i) {
        DF_CHECK(t, dfi_support.moves[moves[i]] != 0u);
    }
    static const uint32_t abilities[] = {DFI_ABILITY_COMPOUNDEYES, DFI_ABILITY_IRONFIST,  DFI_ABILITY_SHARPNESS,
                                         DFI_ABILITY_SOLIDROCK,    DFI_ABILITY_TECHNICIAN, DFI_ABILITY_MULTISCALE,
                                         DFI_ABILITY_GALEWINGS};
    for (size_t i = 0u; i < sizeof abilities / sizeof abilities[0]; ++i) {
        DF_CHECK(t, dfi_support.abilities[abilities[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[abilities[i]], DFI_HANDLER_NONE);
    }
    DF_CHECK(t, dfi_support.items[DFI_ITEM_WIDELENS] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_WIDELENS], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_STEELROLLER].special, DFI_SPECIAL_STEEL_ROLLER);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_CLANGOROUSSOUL].special, DFI_SPECIAL_CLANGOROUS_SOUL);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_BRICKBREAK].special, DFI_SPECIAL_BRICK_BREAK);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_BRICK_BREAK, DFI_SPECIAL_CLANGOROUS_SOUL + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_CLANGOROUS_SOUL, DFI_SPECIAL_STEEL_ROLLER + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_DISABLE, DFI_SPECIAL_BRICK_BREAK + 1u); /* step G27, after the handlers of the other steps */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_ELECTRIC_TERRAIN, DFI_SPECIAL_DISABLE + 1u); /* step G25's four handlers follow */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_PERISH_SONG, DFI_SPECIAL_TERRAIN_PULSE + 1u); /* step G26 follows */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_MULTI_HIT_2, DFI_SPECIAL_PERISH_SONG + 1u); /* step G33's two handlers follow */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_IMPRISON, DFI_SPECIAL_TRIPLE_AXEL + 1u); /* step G38 follows */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_TRICK, DFI_SPECIAL_IMPRISON + 1u); /* step G29's four ids follow */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_SUPER_FANG, DFI_SPECIAL_COVET + 1u); /* step G39 follows */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_TAUNT, DFI_SPECIAL_SUPER_FANG + 1u); /* step G31 */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_SPEED_SWAP + 1u /* G72b: after Alluring Voice and Dragon Cheer */) /* G62: After You and Quash (decision 0015 entry 5az) come after Strength Sap */; /* step G48 adds four handlers after Yawn */
    /* Clangorous Soul: the Champions mod's accuracy true, five +1 boosts on the user, the sound flag (Throat Chop bars it) */
    const dfi_move_data *cs = &dfi_pool_moves[DFI_MOVE_CLANGOROUSSOUL];
    DF_CHECK_EQ_U64(t, cs->accuracy, 0u);
    DF_CHECK_EQ_U64(t, cs->boost_role, DFI_BOOST_ROLE_PRIMARY_SELF);
    DF_CHECK((t), (dfi_pool_move_flags2[DFI_MOVE_CLANGOROUSSOUL] & DFI_MOVE_FLAG2_SOUND) != 0u);
    /* the punch and slicing flags of the pin, on every move that has them */
    static const uint32_t punch[] = {DFI_MOVE_BULLETPUNCH, DFI_MOVE_MACHPUNCH, DFI_MOVE_DRAINPUNCH, DFI_MOVE_ICEPUNCH};
    for (size_t i = 0u; i < sizeof punch / sizeof punch[0]; ++i) {
        DF_CHECK(t, (dfi_pool_move_flags2[punch[i]] & DFI_MOVE_FLAG2_PUNCH) != 0u);
        DF_CHECK(t, (dfi_pool_move_flags2[punch[i]] & DFI_MOVE_FLAG2_SLICING) == 0u);
    }
    static const uint32_t slicing[] = {DFI_MOVE_PSYCHOCUT, DFI_MOVE_NIGHTSLASH, DFI_MOVE_SLASH};
    for (size_t i = 0u; i < sizeof slicing / sizeof slicing[0]; ++i) {
        DF_CHECK(t, (dfi_pool_move_flags2[slicing[i]] & DFI_MOVE_FLAG2_SLICING) != 0u);
        DF_CHECK(t, (dfi_pool_move_flags2[slicing[i]] & DFI_MOVE_FLAG2_PUNCH) == 0u);
    }
    /* every pool move with the punch flag in the public static column has the internal bit, and the same for slicing */
    for (uint32_t m = 0u; m < DFI_POOL_MOVE_COUNT; ++m) {
        DF_CHECK_EQ_U64(t, (dfi_pool_move_flags2[m] & DFI_MOVE_FLAG2_PUNCH) != 0u ? 1u : 0u,
                        (dfi_pool_move_static_flags[m] & DUOFORGE_MOVE_STATIC_FLAG_PUNCH) != 0u ? 1u : 0u);
        DF_CHECK_EQ_U64(t, (dfi_pool_move_flags2[m] & DFI_MOVE_FLAG2_SLICING) != 0u ? 1u : 0u,
                        (dfi_pool_move_static_flags[m] & DUOFORGE_MOVE_STATIC_FLAG_SLICING) != 0u ? 1u : 0u);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.interactions.small_rules_rows");
    check_facts(&t);
    return df_test_end(&t);
}
