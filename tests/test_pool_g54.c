/*
 * duoforge.state.pool_g54 (white-box): step G54 of the content expansion (decision 0015, the moves batch), in the POOL build.
 *
 * Six handlers: Icicle Spear and Scale Shot (a hit count of 2 to 5 drawn from the Champions sample of 20 values, one draw of
 * DFI_SITE_MULTIHIT_COUNT; Scale Shot's self boost after the last hit), Quick Guard (the side guard, decision 0029 for the
 * public value DUOFORGE_BLOCK_QUICK_GUARD), Upper Hand (the target's queued priority move, read from the queue), Heal Pulse
 * (half of the target's maximum HP) and Strength Sap (heals by the target's Attack and lowers it). Sing is a data row. The
 * recorded battles (g54_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data, which compares
 * every draw, message and HP that the reference shows. Here are the facts the battles do not show by themselves:
 *
 *   - the marks, the handler numbers and the pinned numbers of the rows (Sing's data row included);
 *   - what stays unmarked and why (Haze was added by step G62, decision 0031): Steel Beam and Final Gambit (the public values or the state they need are not in
 *     this build), Loaded Dice and Skill Link (the hit count is their own rule and is not modelled), and Mega Launcher (the
 *     pulse guard of Heal Pulse is not modelled), so no battle can reach them;
 *   - the constants that the rows depend on: the draw site of the hit count (20 values), the BLOCKED detail of Quick Guard
 *     and the side guard bit that the view reports;
 *   - Quick Guard's side flag reaches the view: the tail's quick_guard of a side sets its guard bit in guard_flags, and no
 *     other side's, and the feature bit of the view extension is among the supported bits of the build.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/multihit_count.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

static void build_setup(const df_conf_battle *cb, duoforge_battle_setup *s)
{
    memset(s, 0, sizeof *s);
    s->rng_initstate = 1u;
    s->rng_initseq = 2u;
    for (uint32_t side = 0; side < 2u; ++side) {
        s->sides[side].member_count = cb->member_count;
        for (uint32_t m = 0; m < cb->member_count; ++m) {
            const df_conf_member *src = &cb->members[side][m];
            duoforge_member_setup *dst = &s->sides[side].members[m];
            dst->species_id = src->species;
            dst->gender = src->gender;
            dst->nature = src->nature;
            for (uint32_t i = 0; i < 6u; ++i) {
                dst->stat_points[i] = src->sp[i];
            }
            dst->ability = src->ability;
            dst->item = src->item;
            dst->move_count = src->move_count;
            for (uint32_t k = 0; k < src->move_count; ++k) {
                dst->moves[k].move_id = src->moves[k];
            }
        }
    }
}

static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

static void check_marks(df_test *t)
{
    static const uint32_t moves[] = {
        DFI_MOVE_ICICLESPEAR, DFI_MOVE_SCALESHOT, DFI_MOVE_QUICKGUARD, DFI_MOVE_UPPERHAND,
        DFI_MOVE_HEALPULSE,   DFI_MOVE_STRENGTHSAP, DFI_MOVE_SING,
    };
    for (size_t i = 0u; i < sizeof moves / sizeof moves[0]; ++i) {
        DF_CHECK(t, dfi_support.moves[moves[i]] != 0u);
    }
    /* the handlers are the ids after the step G44 ones (Tri Attack is 70), in this order; Sing is a data row */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_ICICLESPEAR].special, DFI_SPECIAL_MULTI_HIT_2_5);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SCALESHOT].special, DFI_SPECIAL_SCALE_SHOT);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_QUICKGUARD].special, DFI_SPECIAL_QUICK_GUARD);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_UPPERHAND].special, DFI_SPECIAL_UPPER_HAND);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_HEALPULSE].special, DFI_SPECIAL_HEAL_PULSE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_STRENGTHSAP].special, DFI_SPECIAL_STRENGTH_SAP);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SING].special, DFI_SPECIAL_NONE);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_MULTI_HIT_2_5, DFI_SPECIAL_REVIVAL_BLESSING + 1u); /* after Revival Blessing (G52) */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_SCALE_SHOT, DFI_SPECIAL_MULTI_HIT_2_5 + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_QUICK_GUARD, DFI_SPECIAL_SCALE_SHOT + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UPPER_HAND, DFI_SPECIAL_QUICK_GUARD + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_HEAL_PULSE, DFI_SPECIAL_UPPER_HAND + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_STRENGTH_SAP, DFI_SPECIAL_HEAL_PULSE + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_HAZE, DFI_SPECIAL_SHEER_COLD + 1u); /* step G62 (decision 0031), after the four of G64 */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_THUNDER_WAVE + 1u); /* step G60 (decision 0032) comes after Quash */ /* G62 added Haze, After You and Quash after it */
}

/* The pinned numbers that the rows of this step depend on (data/moves.ts; the Champions mod changes none of them). */
static void check_pins(df_test *t)
{
    const dfi_move_data *ice = &dfi_pool_moves[DFI_MOVE_ICICLESPEAR];
    DF_CHECK_EQ_U64(t, ice->accuracy, 100u);
    DF_CHECK_EQ_U64(t, ice->base_power, 25u);
    DF_CHECK_EQ_U64(t, ice->category, DFI_CATEGORY_PHYSICAL);
    const dfi_move_data *sc = &dfi_pool_moves[DFI_MOVE_SCALESHOT];
    DF_CHECK_EQ_U64(t, sc->accuracy, 90u);
    DF_CHECK_EQ_U64(t, sc->base_power, 25u);
    const dfi_move_data *qg = &dfi_pool_moves[DFI_MOVE_QUICKGUARD];
    DF_CHECK_EQ_U64(t, qg->priority, DFI_PRIORITY_BIAS + 3u);
    DF_CHECK_EQ_U64(t, qg->category, DFI_CATEGORY_STATUS);
    const dfi_move_data *uh = &dfi_pool_moves[DFI_MOVE_UPPERHAND];
    DF_CHECK_EQ_U64(t, uh->base_power, 65u);
    DF_CHECK_EQ_U64(t, uh->priority, DFI_PRIORITY_BIAS + 3u);
    DF_CHECK_EQ_U64(t, uh->sec_chance, 100u);
    DF_CHECK_EQ_U64(t, uh->sec_kind, DFI_SECONDARY_VOLATILE);
    const dfi_move_data *hp = &dfi_pool_moves[DFI_MOVE_HEALPULSE];
    DF_CHECK_EQ_U64(t, hp->category, DFI_CATEGORY_STATUS);
    const dfi_move_data *ss = &dfi_pool_moves[DFI_MOVE_STRENGTHSAP];
    DF_CHECK_EQ_U64(t, ss->accuracy, 100u);
    DF_CHECK_EQ_U64(t, ss->category, DFI_CATEGORY_STATUS);
}

/* The rows that stay out of this build (the step's drops and the guards): no mark, and no battle can reach them. */
static void check_unmarked(df_test *t)
{
    /* Haze was unmarked here until step G62 (decision 0031) marked it; its check is in duoforge.state.pool_g62 */
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_STEELBEAM] != 0u); /* marked by step G68 (decision 0015 item 5cc): the drop of G54 is no longer dropped */
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_FINALGAMBIT] == 0u);
    /* the abilities whose rule would change a hit count (Skill Link: the maximum) or a pulse (Mega Launcher) stay unmarked */
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_SKILLLINK], 0u);
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_MEGALAUNCHER], 0u);
    /* Loaded Dice raises the hit count in the same draw: an item of the pool would be marked only with that rule */
    static const char *const items[] = {"loadeddice"};
    for (uint32_t i = 0u; i < DFI_POOL_ITEM_COUNT; ++i) {
        const char *n = dfi_pool_item_names[i];
        for (size_t k = 0u; n != NULL && k < sizeof items / sizeof items[0]; ++k) {
            if (strcmp(n, items[k]) == 0) {
                DF_CHECK_EQ_U64(t, dfi_support.items[i], 0u);
            }
        }
    }
}

/* The hit count of each draw of DFI_SITE_MULTIHIT_COUNT (random(20)): the Champions sample, index by index, and its shares
 * (seven 2s, seven 3s, three 4s, three 5s). The pin is scripts.ts:440, the same list as battle-actions.ts:870. */
static void check_multihit_weights(df_test *t)
{
    static const uint32_t want[20] = {2u, 2u, 2u, 2u, 2u, 2u, 2u, 3u, 3u, 3u, 3u, 3u, 3u, 3u, 4u, 4u, 4u, 5u, 5u, 5u};
    uint32_t share[6] = {0u, 0u, 0u, 0u, 0u, 0u};
    for (uint32_t i = 0u; i < 20u; ++i) {
        DF_CHECK_EQ_U64(t, dfi_multihit_count(i), want[i]);
        share[dfi_multihit_count(i)] += 1u;
    }
    DF_CHECK_EQ_U64(t, share[2], 7u);
    DF_CHECK_EQ_U64(t, share[3], 7u);
    DF_CHECK_EQ_U64(t, share[4], 3u);
    DF_CHECK_EQ_U64(t, share[5], 3u);
    DF_CHECK_EQ_U64(t, DFI_SITE_MULTIHIT_COUNT, 22u /* site 20 is the G46 drag, 21 the G56 lock */);
}

/* The constants that the rows and their draws depend on. */
static void check_constants(df_test *t)
{
    DF_CHECK_EQ_U64(t, DFI_SITE_MULTIHIT_COUNT, 22u /* site 20 is the G46 drag, 21 the G56 lock */);
    DF_CHECK_EQ_U64(t, DFI_SITE_COUNT, 23u);
    DF_CHECK_EQ_U64(t, DUOFORGE_BLOCK_QUICK_GUARD, 6u); /* decision 0029 */
    DF_CHECK_EQ_U64(t, DUOFORGE_SIDE_GUARD_QUICK_GUARD, 2u);
    DF_CHECK_EQ_U64(t, DUOFORGE_VIEWEXT_FEATURE_QUICK_GUARD, 38u);
    DF_CHECK(t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_QUICK_GUARD)) != 0u);
}

/* Quick Guard's side flag reaches the view: the tail's quick_guard of one side sets its guard bit and no other side's. */
static void check_guard_flag(df_test *t, duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g54_quick_guard_a");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return;
    }
    duoforge_observation_ext ext;
    DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, 0u, &ext) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, ext.sides[0].guard_flags & DUOFORGE_SIDE_GUARD_QUICK_GUARD, 0u);
    b->tail.sides[0].quick_guard = 1u;
    DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, 0u, &ext) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, ext.sides[0].guard_flags, DUOFORGE_SIDE_GUARD_QUICK_GUARD);
    DF_CHECK_EQ_U64(t, ext.sides[1].guard_flags, 0u);
    b->tail.sides[0].quick_guard = 0u;
    b->tail.sides[1].quick_guard = 1u;
    DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, 1u, &ext) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, ext.sides[0].guard_flags, 0u);
    DF_CHECK_EQ_U64(t, ext.sides[1].guard_flags, DUOFORGE_SIDE_GUARD_QUICK_GUARD);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g54");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_marks(&t);
    check_pins(&t);
    check_unmarked(&t);
    check_constants(&t);
    check_multihit_weights(&t);
    check_guard_flag(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
