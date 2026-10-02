/*
 * duoforge.combat.move_rules (white-box): the rules that several moves share
 * (src/combat/move_rules.h, step G10) against literal values written from
 * the pinned handlers.
 *
 * Fake Out and First Impression are the moves of the first-turn rule, no
 * other move of the pool is; Grass Knot and Low Kick take their power from
 * the target's weight with the table of data/moves.ts:10446-10464, here at
 * every threshold and one hectogram on each side of it; the move extra column
 * says which moves thaw their target and which heal (data/moves.ts:15770 and
 * :14806-14820).
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

    /* The move extra column: Scald thaws its target, Recover heals 1/2, nobody else. */
    for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
        const dfi_move_extra *x = &dfi_pool_move_extra[id];
        DF_CHECK_EQ_U64(&t, x->flags, id == DFI_MOVE_SCALD ? DFI_EXTRA_THAWS_TARGET : 0u);
        DF_CHECK_EQ_U64(&t, x->heal[0], id == DFI_MOVE_RECOVER ? 1u : 0u);
        DF_CHECK_EQ_U64(&t, x->heal[1], id == DFI_MOVE_RECOVER ? 2u : 0u);
    }

    /* The gate: the four moves of step G10 are marked. */
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_FIRSTIMPRESSION] != 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_SCALD] != 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_RECOVER] != 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_LOWKICK] != 0u);
    return df_test_end(&t);
}
