/*
 * duoforge.interactions.rage_powder_batch_rows (white-box): step G30 of the content expansion, Rage Powder with the powder
 * immunity, Psychic Fangs, Solar Beam, Flame Body, Clear Body, Hospitality and Overcoat, and the data rows that only waited for
 * a recorded battle (the status powders, Matcha Gotcha, Giga Drain, Energy Ball, Play Rough), as one batch: the draw sites, the
 * marks, the special numbers, the powder flag of exactly six moves; what stays unmarked and why (Cotton Spore, Magic Powder,
 * Utility Umbrella and Power Herb, which Solar Beam's weather and charge would meet, and Safety Goggles), and the later marks
 * the step's guards rely on (Stomping Tantrum by G42, Mega Sol by G59, whose refusals off sun keep the Utility Umbrella and
 * Power Herb claims); and no Grass-type forme can have Clear Body or Trace (Flower Veil's order with Clear Body). The recorded
 * battles g30_* are replayed by duoforge.reference.conformance_pool_data.
 *
 * Split by subject from the test of step G30 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

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
    /* the numbers */
    DF_CHECK_EQ_U64(t, DFI_SITE_FLAME_BODY, 18u);
    DF_CHECK_EQ_U64(t, DFI_SITE_STATIC, 19u); /* step G39: Static's draw; the count was 19 until then */
    DF_CHECK_EQ_U64(t, DFI_SITE_COUNT, 34u); /* step G46 adds the drag (site 20), step G54 the multi-hit count (site 22), step G73 Moody (site 23), step G80 Ally Switch (site 33) */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_RAGE_POWDER, 33u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_PSYCHIC_FANGS, 34u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_SOLAR_BEAM, 35u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_STEEL_ROLLER, DFI_SPECIAL_CLANGING_SCALES + 1u); /* 36 before step G32 put its eight handlers after Solar Beam, and step G34 its three after them */
    DF_CHECK_EQ_U64(t, DUOFORGE_VIEWEXT_FEATURE_RAGE_POWDER, 39u);
    DF_CHECK(t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_RAGE_POWDER)) != 0u);
    /* the marks */
    static const uint32_t marked_moves[] = {DFI_MOVE_RAGEPOWDER, DFI_MOVE_SLEEPPOWDER, DFI_MOVE_STUNSPORE,
                                            DFI_MOVE_POISONPOWDER, DFI_MOVE_PSYCHICFANGS, DFI_MOVE_SOLARBEAM,
                                            DFI_MOVE_MATCHAGOTCHA, DFI_MOVE_GIGADRAIN, DFI_MOVE_ENERGYBALL,
                                            DFI_MOVE_PLAYROUGH};
    for (size_t i = 0u; i < sizeof marked_moves / sizeof marked_moves[0]; ++i) {
        DF_CHECK(t, dfi_support.moves[marked_moves[i]] != 0u);
    }
    static const uint32_t marked_abilities[] = {DFI_ABILITY_FLAMEBODY, DFI_ABILITY_CLEARBODY, DFI_ABILITY_HOSPITALITY,
                                                DFI_ABILITY_OVERCOAT};
    for (size_t i = 0u; i < sizeof marked_abilities / sizeof marked_abilities[0]; ++i) {
        DF_CHECK(t, dfi_support.abilities[marked_abilities[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[marked_abilities[i]], DFI_HANDLER_NONE);
    }
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_RAGEPOWDER].special, DFI_SPECIAL_RAGE_POWDER);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_PSYCHICFANGS].special, DFI_SPECIAL_PSYCHIC_FANGS);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SOLARBEAM].special, DFI_SPECIAL_SOLAR_BEAM);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_RAGEPOWDER].priority, 8u + 2u);
    /* the powder flag: exactly the six moves of the pin, whatever their category */
    uint32_t powder = 0u;
    for (uint32_t m = 0u; m < DFI_POOL_MOVE_COUNT; ++m) {
        const bool flag = (dfi_pool_move_flags2[m] & DFI_MOVE_FLAG2_POWDER) != 0u;
        const bool want = m == DFI_MOVE_COTTONSPORE || m == DFI_MOVE_MAGICPOWDER || m == DFI_MOVE_POISONPOWDER ||
                          m == DFI_MOVE_RAGEPOWDER || m == DFI_MOVE_SLEEPPOWDER || m == DFI_MOVE_STUNSPORE;
        DF_CHECK_EQ_U64(t, flag ? 1u : 0u, want ? 1u : 0u);
        powder += flag ? 1u : 0u;
        /* the public static flag has the same set (decision 0020) */
        DF_CHECK_EQ_U64(t, (dfi_pool_move_static_flags[m] & DUOFORGE_MOVE_STATIC_FLAG_POWDER) != 0u ? 1u : 0u, want ? 1u : 0u);
    }
    DF_CHECK_EQ_U64(t, powder, 6u);
    /* what stays unmarked, and why */
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_COTTONSPORE], 0u);    /* boosts to the foes: no primary boosts on a non-self target */
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_MAGICPOWDER], 0u);    /* a type change */
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_STOMPINGTANTRUM] != 0u); /* step G42 marks it: the last move result of the tail (rev 4) */
    /* effectiveWeather: sun for the Solar Beam of its user. Step G59 marks Mega Sol: its holder's Solar Beam and Weather Ball are
     * refused off sun (dfi_mega_sol_refused, tests/abilities/test_mega_sol.c), so the Utility Umbrella and Power Herb claims above stand. */
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_MEGASOL] != 0u);
    for (uint32_t i = 0u; i < DFI_POOL_ITEM_COUNT; ++i) {
        const char *name = dfi_pool_item_names[i];
        if (strcmp(name, "utilityumbrella") == 0 || strcmp(name, "powerherb") == 0 || strcmp(name, "safetygoggles") == 0) {
            DF_CHECK_EQ_U64(t, dfi_support.items[i], 0u); /* Solar Beam's weather, its ChargeMove event, powder immunity */
        }
    }
    /* Clear Body, Trace and Grass: Flower Veil's TryBoost handler would need an order with Clear Body's */
    for (uint32_t f = 0u; f < DFI_POOL_FORME_COUNT; ++f) {
        const bool grass = dfi_pool_formes[f].types[0] == DFI_TYPE_GRASS || dfi_pool_formes[f].types[1] == DFI_TYPE_GRASS;
        for (uint32_t a = 0u; a < dfi_pool_forme_legal[f].ability_count; ++a) {
            const uint32_t id = dfi_pool_forme_legal[f].abilities[a];
            DF_CHECK(t, !(grass && (id == DFI_ABILITY_CLEARBODY || id == DFI_ABILITY_TRACE)));
        }
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.interactions.rage_powder_batch_rows");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_facts(&t);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
