/*
 * duoforge.combat.move_rules (white-box): the rules that several moves share
 * (src/combat/move_rules.h, step G10) against literal values written from
 * the pinned handlers.
 *
 * Fake Out and First Impression are the moves of the first-turn rule, no
 * other move of the pool is; Grass Knot and Low Kick take their power from
 * the target's weight with the table of data/moves.ts:10446-10464, here at
 * every threshold and one hectogram on each side of it; the flags2 and heal
 * columns say which moves thaw their target (data/moves.ts:15770) and which
 * heal (:14806-14820).
 */
#include <stdio.h>

#include <duoforge/duoforge.h>

#include "combat/move_rules.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "support/check.h"

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.combat.move_rules");

    /* The first-turn rule: exactly Fake Out and First Impression. */
    for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
        const bool want = id == DFI_MOVE_FAKEOUT || id == DFI_MOVE_FIRSTIMPRESSION;
        if (!DF_CHECK(&t, dfi_move_first_turn_only(&dfi_pool_moves[id]) == want)) {
            fprintf(stderr, "  first turn only: move %u expected %d\n", (unsigned)id, (int)want);
        }
    }

    /* Power by weight: exactly Grass Knot and Low Kick. */
    for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
        const bool want = id == DFI_MOVE_GRASSKNOT || id == DFI_MOVE_LOWKICK;
        if (!DF_CHECK(&t, dfi_move_power_by_weight(&dfi_pool_moves[id]) == want)) {
            fprintf(stderr, "  power by weight: move %u expected %d\n", (unsigned)id, (int)want);
        }
    }

    /* The weight table (hectograms): each threshold and its neighbours. */
    static const struct {
        uint32_t weight, power;
    } cases[] = {
        {0u, 20u},    {99u, 20u},   {100u, 40u},  {101u, 40u},  {249u, 40u},   {250u, 60u},   {251u, 60u},
        {499u, 60u},  {500u, 80u},  {501u, 80u},  {999u, 80u},  {1000u, 100u}, {1001u, 100u}, {1999u, 100u},
        {2000u, 120u}, {2001u, 120u}, {9999u, 120u},
    };
    for (size_t i = 0u; i < sizeof cases / sizeof cases[0]; ++i) {
        if (!DF_CHECK(&t, dfi_weight_power(cases[i].weight) == cases[i].power)) {
            fprintf(stderr, "  weight %u: %u, expected %u\n", (unsigned)cases[i].weight,
                    (unsigned)dfi_weight_power(cases[i].weight), (unsigned)cases[i].power);
        }
    }

    /* The weights of real members that the recorded battles use: Staraptor 24.9 kg and its Mega 50 kg, Rillaboom
     * 90 kg, Milotic 162 kg, Sneasler 43 kg, Gholdengo 30 kg. */
    DF_CHECK_EQ_U64(&t, dfi_weight_power(dfi_pool_formes[DFI_FORME_STARAPTOR].weight_hg), 40u);
    DF_CHECK_EQ_U64(&t, dfi_weight_power(dfi_pool_formes[DFI_FORME_STARAPTORMEGA].weight_hg), 80u);
    DF_CHECK_EQ_U64(&t, dfi_weight_power(dfi_pool_formes[DFI_FORME_RILLABOOM].weight_hg), 80u);
    DF_CHECK_EQ_U64(&t, dfi_weight_power(dfi_pool_formes[DFI_FORME_MILOTIC].weight_hg), 100u);
    DF_CHECK_EQ_U64(&t, dfi_weight_power(dfi_pool_formes[DFI_FORME_SNEASLER].weight_hg), 60u);
    DF_CHECK_EQ_U64(&t, dfi_weight_power(dfi_pool_formes[DFI_FORME_GHOLDENGO].weight_hg), 60u);

    /* The columns of step G10: Scald thaws its target (flags2 bit 4), Recover heals 1/2 and has the heal flag (bit 2,
     * which Heal Block reads); a move with a heal fraction has the heal flag, and the first-turn moves, the weight
     * moves and the four moves of the step have no handler id that the turn code lacks. */
    DF_CHECK(&t, (dfi_pool_move_flags2[DFI_MOVE_SCALD] & DFI_MOVE_FLAG2_THAWS_TARGET) != 0u);
    DF_CHECK(&t, (dfi_pool_move_flags2[DFI_MOVE_RECOVER] & DFI_MOVE_FLAG2_THAWS_TARGET) == 0u);
    DF_CHECK(&t, (dfi_pool_move_flags2[DFI_MOVE_RECOVER] & DFI_MOVE_FLAG2_HEAL) != 0u);
    DF_CHECK_EQ_U64(&t, dfi_pool_move_heal[DFI_MOVE_RECOVER][0], 1u);
    DF_CHECK_EQ_U64(&t, dfi_pool_move_heal[DFI_MOVE_RECOVER][1], 2u);
    DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_SCALD].special, DFI_SPECIAL_NONE); /* data, no handler */
    DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_RECOVER].special, DFI_SPECIAL_NONE);
    DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_FIRSTIMPRESSION].special, DFI_SPECIAL_FIRST_IMPRESSION);
    DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_LOWKICK].special, DFI_SPECIAL_LOW_KICK);
    for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
        const bool heals = dfi_pool_move_heal[id][1] != 0u;
        if (heals) {
            DF_CHECK(&t, dfi_pool_move_heal[id][0] != 0u && dfi_pool_move_heal[id][0] <= dfi_pool_move_heal[id][1]);
            DF_CHECK(&t, (dfi_pool_move_flags2[id] & DFI_MOVE_FLAG2_HEAL) != 0u);
        } else {
            DF_CHECK_EQ_U64(&t, dfi_pool_move_heal[id][0], 0u);
        }
        /* The four moves are modelled: not the UNMODELED handler. */
        if (id == DFI_MOVE_SCALD || id == DFI_MOVE_RECOVER || id == DFI_MOVE_FIRSTIMPRESSION ||
            id == DFI_MOVE_LOWKICK) {
            DF_CHECK(&t, dfi_pool_moves[id].special != DFI_SPECIAL_UNMODELED);
            DF_CHECK(&t, dfi_pool_move_unmodeled[id] == NULL);
        }
    }

    /* The gate: the four moves of step G10 are marked. */
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_FIRSTIMPRESSION] != 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_SCALD] != 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_RECOVER] != 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_LOWKICK] != 0u);
    return df_test_end(&t);
}
