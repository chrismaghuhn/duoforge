/*
 * duoforge.state.pool_g44 (white-box): step G44 of the content expansion (decision 0015 item 5an), the simple moves.
 *
 * Four handlers, each a rule that the generic columns cannot hold: Thunder (never misses in rain, 50 under sun), Power Trip
 * (20 plus 20 per positive stage of the user), Ice Fang (a freeze roll, then a flinch roll) and Tri Attack (a 20 percent roll,
 * then a pick of burn, paralysis or freeze). Seven data rows: Breaking Swipe, Vacuum Wave, Stone Edge, Aqua Cutter, Hammer
 * Arm, Trop Kick and Meteor Mash. The recorded battles (g44_* under "data": "pool") are replayed by
 * duoforge.reference.conformance_pool_data, which compares every draw, message and HP that the reference shows. Here are the
 * facts that the battles do not show by themselves:
 *
 *   - the marks, the handler numbers and the pinned numbers of each row (the pin's power, accuracy, priority, critical hit
 *     ratio and stage changes, with the Champions override of Trop Kick's power);
 *   - what stays unmarked: Scale Shot (its hit count is a draw of its own, a new draw site, so it is left out of this step),
 *     and Fly, which Thunder would hit through (not marked, so no battle can have a Thunder that meets a Fly);
 *   - the guard: Ice Fang and Tri Attack bypass the generic secondaries path, so they skip the pin's ModifySecondaries
 *     (sim/battle-actions.ts:1340-1341), which Shield Dust, Covert Cloak and Serene Grace change. None of the three is marked
 *     or a row of the pool today; marking any of them later fails here until these paths honour it;
 *   - Power Trip's positive-stage sum at every stat, white-box (combat/power_trip.h): the battles of this step carry two stages
 *     of attack and defense only, so an accuracy or evasion stage is checked here.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/power_trip.h"
#include "combat/secondary_rolls.h"
#include "data/closure_tables.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "support/check.h"
#include "support/pool.h"

static void check_marks(df_test *t)
{
    static const uint32_t moves[] = {
        DFI_MOVE_THUNDER, DFI_MOVE_POWERTRIP, DFI_MOVE_ICEFANG, DFI_MOVE_TRIATTACK,
        DFI_MOVE_BREAKINGSWIPE, DFI_MOVE_VACUUMWAVE, DFI_MOVE_STONEEDGE, DFI_MOVE_AQUACUTTER,
        DFI_MOVE_HAMMERARM, DFI_MOVE_TROPKICK, DFI_MOVE_METEORMASH,
    };
    for (size_t i = 0u; i < sizeof moves / sizeof moves[0]; ++i) {
        DF_CHECK(t, dfi_support.moves[moves[i]] != 0u);
    }
    /* the data rows have no handler; the four handlers are the ids after Yawn, in this order */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_BREAKINGSWIPE].special, DFI_SPECIAL_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_VACUUMWAVE].special, DFI_SPECIAL_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_STONEEDGE].special, DFI_SPECIAL_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_AQUACUTTER].special, DFI_SPECIAL_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_HAMMERARM].special, DFI_SPECIAL_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_TROPKICK].special, DFI_SPECIAL_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_METEORMASH].special, DFI_SPECIAL_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_THUNDER].special, DFI_SPECIAL_THUNDER);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_POWERTRIP].special, DFI_SPECIAL_POWER_TRIP);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_ICEFANG].special, DFI_SPECIAL_ICE_FANG);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_TRIATTACK].special, DFI_SPECIAL_TRI_ATTACK);
    /* after the handlers of step G48 (Rage Fist, Stone Axe, Ceaseless Edge, Population Bomb) */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_POWER_TRIP, DFI_SPECIAL_MULTI_HIT_10 + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_THUNDER, DFI_SPECIAL_POWER_TRIP + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_ICE_FANG, DFI_SPECIAL_THUNDER + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_TRI_ATTACK, DFI_SPECIAL_ICE_FANG + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_ROOST, DFI_SPECIAL_TRI_ATTACK + 1u); /* step G42 */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_STOMPING_TANTRUM, DFI_SPECIAL_ROOST + 1u); /* step G42 */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_STOMPING_TANTRUM + 1u);
}

static void check_pins(df_test *t)
{
    /* Thunder (data/moves.ts:19438-19466): accuracy 70, 110 power, Special, a 30 percent paralysis */
    const dfi_move_data *th = &dfi_pool_moves[DFI_MOVE_THUNDER];
    DF_CHECK_EQ_U64(t, th->accuracy, 70u);
    DF_CHECK_EQ_U64(t, th->base_power, 110u);
    DF_CHECK_EQ_U64(t, th->category, DFI_CATEGORY_SPECIAL);
    DF_CHECK_EQ_U64(t, th->sec_chance, 30u);
    DF_CHECK_EQ_U64(t, th->sec_kind, DFI_SECONDARY_STATUS);
    /* Power Trip (data/moves.ts:13851-13870): base power 20, accuracy 100, Physical; the rest is the callback */
    const dfi_move_data *pt = &dfi_pool_moves[DFI_MOVE_POWERTRIP];
    DF_CHECK_EQ_U64(t, pt->accuracy, 100u);
    DF_CHECK_EQ_U64(t, pt->base_power, 20u);
    DF_CHECK_EQ_U64(t, pt->category, DFI_CATEGORY_PHYSICAL);
    DF_CHECK_EQ_U64(t, pt->sec_chance, 0u);
    /* Ice Fang (data/moves.ts:9347-9368): accuracy 95, 65 power, Physical; the two secondaries belong to the handler */
    const dfi_move_data *fang = &dfi_pool_moves[DFI_MOVE_ICEFANG];
    DF_CHECK_EQ_U64(t, fang->accuracy, 95u);
    DF_CHECK_EQ_U64(t, fang->base_power, 65u);
    DF_CHECK_EQ_U64(t, fang->sec_chance, 0u);
    /* Tri Attack (data/moves.ts:19845-19864): accuracy 100, 80 power, Special; the chance 20 belongs to the handler */
    const dfi_move_data *tri = &dfi_pool_moves[DFI_MOVE_TRIATTACK];
    DF_CHECK_EQ_U64(t, tri->accuracy, 100u);
    DF_CHECK_EQ_U64(t, tri->base_power, 80u);
    DF_CHECK_EQ_U64(t, tri->category, DFI_CATEGORY_SPECIAL);
    DF_CHECK_EQ_U64(t, tri->sec_chance, 0u);
    /* the data rows: Breaking Swipe (allAdjacentFoes, a 100 percent Attack drop of each foe) */
    const dfi_move_data *bs = &dfi_pool_moves[DFI_MOVE_BREAKINGSWIPE];
    DF_CHECK_EQ_U64(t, bs->base_power, 60u);
    DF_CHECK_EQ_U64(t, bs->sec_chance, 100u);
    DF_CHECK_EQ_U64(t, bs->sec_kind, DFI_SECONDARY_BOOST);
    DF_CHECK_EQ_U64(t, bs->boosts[DFI_STAGE_ATK], DFI_STAGE_BIAS - 1u);
    /* Vacuum Wave (data/moves.ts:20282-20294): 40 power, accuracy 100, Special, priority +1 */
    const dfi_move_data *vw = &dfi_pool_moves[DFI_MOVE_VACUUMWAVE];
    DF_CHECK_EQ_U64(t, vw->base_power, 40u);
    DF_CHECK_EQ_U64(t, vw->accuracy, 100u);
    DF_CHECK_EQ_U64(t, vw->category, DFI_CATEGORY_SPECIAL);
    DF_CHECK_EQ_U64(t, vw->priority, DFI_PRIORITY_BIAS + 1u);
    /* Stone Edge (data/moves.ts:18096-18109): 100 power, accuracy 80, critical hit ratio 2 */
    const dfi_move_data *se = &dfi_pool_moves[DFI_MOVE_STONEEDGE];
    DF_CHECK_EQ_U64(t, se->base_power, 100u);
    DF_CHECK_EQ_U64(t, se->accuracy, 80u);
    DF_CHECK_EQ_U64(t, se->crit_ratio, 2u);
    /* Aqua Cutter (data/moves.ts:439-452): 70 power, accuracy 100, critical hit ratio 2, the slicing flag */
    const dfi_move_data *ac = &dfi_pool_moves[DFI_MOVE_AQUACUTTER];
    DF_CHECK_EQ_U64(t, ac->base_power, 70u);
    DF_CHECK_EQ_U64(t, ac->crit_ratio, 2u);
    DF_CHECK(t, (dfi_pool_move_flags2[DFI_MOVE_AQUACUTTER] & DFI_MOVE_FLAG2_SLICING) != 0u);
    /* Hammer Arm (data/moves.ts:8085-8102): 100 power, accuracy 90, the user loses one Speed stage */
    const dfi_move_data *ha = &dfi_pool_moves[DFI_MOVE_HAMMERARM];
    DF_CHECK_EQ_U64(t, ha->base_power, 100u);
    DF_CHECK_EQ_U64(t, ha->accuracy, 90u);
    DF_CHECK_EQ_U64(t, ha->boosts[DFI_STAGE_SPE], DFI_STAGE_BIAS - 1u);
    /* Trop Kick (data/moves.ts:20057-20075; the Champions mod sets the power to 85, data/mods/champions/moves.ts:1084-1087) */
    const dfi_move_data *tk = &dfi_pool_moves[DFI_MOVE_TROPKICK];
    DF_CHECK_EQ_U64(t, tk->base_power, 85u);
    DF_CHECK_EQ_U64(t, tk->sec_chance, 100u);
    DF_CHECK_EQ_U64(t, tk->boosts[DFI_STAGE_ATK], DFI_STAGE_BIAS - 1u);
    /* Meteor Mash (data/moves.ts:11763-11783): 90 power, accuracy 90, a 20 percent roll for the user's Attack +1 */
    const dfi_move_data *mm = &dfi_pool_moves[DFI_MOVE_METEORMASH];
    DF_CHECK_EQ_U64(t, mm->base_power, 90u);
    DF_CHECK_EQ_U64(t, mm->accuracy, 90u);
    DF_CHECK_EQ_U64(t, mm->sec_chance, 20u);
    DF_CHECK_EQ_U64(t, mm->sec_kind, DFI_SECONDARY_SELF_BOOST);
    DF_CHECK_EQ_U64(t, mm->boosts[DFI_STAGE_ATK], DFI_STAGE_BIAS + 1u);
}

static void check_unmarked(df_test *t)
{
    /* Scale Shot: a hit count of 2 to 5 is a draw of its own (the Champions sample of 20 values), and no draw site of the
     * reference has it: the row stays UNMODELED */
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_SCALESHOT] == 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SCALESHOT].special, DFI_SPECIAL_UNMODELED);
    /* Thunder can hit through Fly (a semi-invulnerable target): Fly is not marked, so no battle has that case */
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_FLY] == 0u);
}

/* The Tri Attack chance (20 of random(100)): the roll 19 passes, 20 fails, at both edges and at the ends. No recorded battle has
 * a roll of 19 on that draw, so the edges are checked here (combat/secondary_rolls.h). */
static void check_tri_attack_edges(df_test *t)
{
    DF_CHECK(t, dfi_tri_attack_chance_hit(0u));
    DF_CHECK(t, dfi_tri_attack_chance_hit(19u));
    DF_CHECK(t, !dfi_tri_attack_chance_hit(20u));
    DF_CHECK(t, !dfi_tri_attack_chance_hit(99u));
}

/* Power Trip's positive-stage sum: every stat counts, accuracy and evasion too (Coil raises accuracy, and the five-stat
 * mutant of the decision is caught here), a negative stage adds nothing. Stored stages are biased by DFI_STAGE_NEUTRAL. */
static void check_power_trip_stages(df_test *t)
{
    uint8_t s[DFI_STAT_STAGE_COUNT];
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        s[i] = DFI_STAGE_NEUTRAL;
    }
    DF_CHECK_EQ_U64(t, dfi_power_trip_positive_stages(s), 0u);
    for (uint32_t k = 0u; k < DFI_STAT_STAGE_COUNT; ++k) {
        s[k] = (uint8_t)(DFI_STAGE_NEUTRAL + 1u);
        DF_CHECK_EQ_U64(t, dfi_power_trip_positive_stages(s), 1u);
        s[k] = DFI_STAGE_NEUTRAL;
    }
    s[DFI_STAGE_ACCURACY] = (uint8_t)(DFI_STAGE_NEUTRAL + 2u);
    s[DFI_STAGE_EVASION] = (uint8_t)(DFI_STAGE_NEUTRAL + 1u);
    DF_CHECK_EQ_U64(t, dfi_power_trip_positive_stages(s), 3u);
    s[DFI_STAGE_ATK] = (uint8_t)(DFI_STAGE_NEUTRAL + 2u);
    s[DFI_STAGE_DEF] = 0u; /* -6 */
    DF_CHECK_EQ_U64(t, dfi_power_trip_positive_stages(s), 5u);
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        s[i] = (uint8_t)(DFI_STAGE_NEUTRAL + DFI_STAGE_NEUTRAL); /* +6 */
    }
    DF_CHECK_EQ_U64(t, dfi_power_trip_positive_stages(s), 42u);
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        s[i] = 0u; /* -6 */
    }
    DF_CHECK_EQ_U64(t, dfi_power_trip_positive_stages(s), 0u);
}

/* The guard (decision 0015 item 5an): the rows that the generic secondaries path would have to honour (Shield Dust blocks a
 * move's secondary, Serene Grace doubles its chance, Covert Cloak blocks the effect of an item's source), and the secondaries
 * that Ice Fang and Tri Attack bypass (ModifySecondaries, sim/battle-actions.ts:1340-1341). None is marked, and none is a
 * row of the pool today (Serene Grace and Covert Cloak have no name in the tables). A row of any of these names that a later
 * step adds must stay unmarked until these paths honour it. */
static void check_guard_unmarked(df_test *t)
{
    DF_CHECK(t, dfi_pool_ability_names[DFI_ABILITY_SHIELDDUST] != NULL &&
                    strcmp(dfi_pool_ability_names[DFI_ABILITY_SHIELDDUST], "shielddust") == 0);
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_SHIELDDUST], 0u);
    static const char *const abilities[] = {"shielddust", "serenegrace"};
    for (uint32_t i = 0u; i < DFI_POOL_ABILITY_COUNT; ++i) {
        const char *n = dfi_pool_ability_names[i];
        for (size_t k = 0u; n != NULL && k < sizeof abilities / sizeof abilities[0]; ++k) {
            if (strcmp(n, abilities[k]) == 0) {
                DF_CHECK_EQ_U64(t, dfi_support.abilities[i], 0u);
            }
        }
    }
    static const char *const items[] = {"covertcloak"};
    for (uint32_t i = 0u; i < DFI_POOL_ITEM_COUNT; ++i) {
        const char *n = dfi_pool_item_names[i];
        for (size_t k = 0u; n != NULL && k < sizeof items / sizeof items[0]; ++k) {
            if (strcmp(n, items[k]) == 0) {
                DF_CHECK_EQ_U64(t, dfi_support.items[i], 0u);
            }
        }
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g44");
    check_marks(&t);
    check_pins(&t);
    check_unmarked(&t);
    check_power_trip_stages(&t);
    check_tri_attack_edges(&t);
    check_guard_unmarked(&t);
    return df_test_end(&t);
}
