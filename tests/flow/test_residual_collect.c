/*
 * duoforge.flow.residual_collect (white-box, issue 664): the unsorted handler list of the residual
 * (dfi_residual_collect, src/combat/flow/residual_collect.h), checked entry by entry with no battle step. PR 661 put Gravity,
 * Wide Guard and Quick Guard into the list and gave each side condition its own sub-order; no reference battle shows those
 * entries mattering, so two mutants survived it (docs/mechanics/flow/5ga-residual-noorder-tie.md). This test kills both.
 *
 * The pin's list (sim/battle.ts fieldEvent :484-510): findFieldEventHandlers (:1133-1145) first, the field's
 * pseudo-weathers in the order they were added, then the weather, then the terrain; then for each side
 * findSideEventHandlers (:1149-1163), the side's conditions before that side's Pokemon. resolvePriority (:954-980) gives
 * each its key: Trick Room order 27 sub-order 1, Gravity 27 / 2 (data/moves.ts:19970-19971, 7832-7833); Reflect 26 / 1,
 * Light Screen 26 / 2, Tailwind 26 / 5, Aurora Veil 26 / 10 (:14872-14873, 10345-10346, 18904-18905, 867-868); Wide Guard
 * and Quick Guard have no onResidual and no order, and a side condition's default sub-order is 4 with Speed 0. The engine's keys: kind DFI_RES_FIELD_END, flat
 * DFI_RESIDUAL_FIELD_FLAT (the field) or DFI_RESIDUAL_SIDE_FLAT + side, Speed 0, not a callback; the weather is
 * DFI_RES_WEATHER (order 1, sub-order 5, a callback) and the terrain DFI_RES_TERRAIN_END (27 / 7).
 *
 *   1. everything: Trick Room, Gravity, rain, Electric Terrain (Grassy would add a handler per Pokemon), all six side
 *      conditions on both sides, a burn on positions 0 and 3: the whole list, in order.
 *   2. each field and side entry alone: one entry with its key.
 * Mutants killed (issue 664): the Gravity entry removed (1 and 2), and the side conditions' own sub-orders lumped into one
 * key again (1 and 2). The base (no field or side entry, every Pokemon cured) is checked empty first.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/flow/residual_collect.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"

#define POSITIONS 4u

/* Distinct Speed keys, so that a Pokemon's entry shows whose it is. */
static const uint32_t k_speed[POSITIONS] = {111u, 82u, 93u, 74u};

enum {
    COND_REFLECT,
    COND_LIGHT_SCREEN,
    COND_TAILWIND,
    COND_AURORA_VEIL,
    COND_WIDE_GUARD,
    COND_QUICK_GUARD,
    COND_COUNT
};

static const char *const k_cond_name[COND_COUNT] = {"Reflect", "Light Screen", "Tailwind", "Aurora Veil", "Wide Guard",
                                                    "Quick Guard"};

/* The pin's key of each side condition: order (DFI_RES_NO_ORDER for none) and sub-order. */
static const uint32_t k_cond_order[COND_COUNT] = {26u, 26u, 26u, 26u, DFI_RES_NO_ORDER, DFI_RES_NO_ORDER};
static const uint32_t k_cond_sub[COND_COUNT] = {1u, 2u, 5u, 10u, 4u, 4u};

static void set_cond(struct duoforge_battle *b, uint32_t side, uint32_t c)
{
    dfi_side *sd = &b->sides[side];
    dfi_tail_side *tsd = &b->tail.sides[side];
    switch (c) {
    case COND_REFLECT:
        sd->reflect_turns = 5u;
        break;
    case COND_LIGHT_SCREEN:
        sd->light_screen_turns = 5u;
        break;
    case COND_TAILWIND:
        sd->tailwind_turns = 4u;
        break;
    case COND_AURORA_VEIL:
        tsd->aurora_veil_turns = 5u;
        break;
    case COND_WIDE_GUARD:
        tsd->wide_guard = 1u;
        break;
    default:
        tsd->quick_guard = 1u;
        break;
    }
}

/* The base battle: F1 (after team selection) with every active Pokemon cured, so that the Pokemon add no handler of their own. */
static struct duoforge_battle *make_base(df_test *t, const duoforge_context *ctx)
{
    struct duoforge_battle *b = df_make_f1(ctx);
    for (uint32_t flat = 0u; flat < POSITIONS; ++flat) {
        dfi_member *m = dfi_at(b, flat);
        if (DF_CHECK(t, m != NULL)) {
            m->status = 0u;
        }
    }
    return b;
}

static bool collect(df_test *t, struct duoforge_battle *b, dfi_residual_entry *list, uint32_t *n)
{
    dfi_run r;
    memset(&r, 0, sizeof r);
    r.b = b;
    memcpy(r.speed_seen, k_speed, sizeof k_speed);
    *n = UINT32_MAX;
    return DF_CHECK(t, dfi_residual_collect(&r, b, list, n) == DUOFORGE_OK) && DF_CHECK(t, *n <= DFI_RES_MAX);
}

static dfi_residual_entry entry(uint32_t kind, uint32_t flat, uint32_t order, uint32_t speed, uint32_t sub, bool callback)
{
    return (dfi_residual_entry){kind, flat, order, speed, sub, callback};
}

static dfi_residual_entry cond_entry(uint32_t side, uint32_t c)
{
    return entry(DFI_RES_FIELD_END, DFI_RESIDUAL_SIDE_FLAT + side, k_cond_order[c], 0u, k_cond_sub[c], false);
}

static void check_list(df_test *t, const char *what, const dfi_residual_entry *got, uint32_t n,
                       const dfi_residual_entry *want, uint32_t want_n)
{
    if (!DF_CHECK_EQ_U64(t, n, want_n)) {
        fprintf(stderr, "  %s: %u entries, want %u\n", what, (unsigned)n, (unsigned)want_n);
        return;
    }
    for (uint32_t i = 0u; i < n; ++i) {
        const dfi_residual_entry *g = &got[i];
        const dfi_residual_entry *w = &want[i];
        const bool same = g->kind == w->kind && g->flat == w->flat && g->order == w->order && g->speed == w->speed &&
                          g->sub_order == w->sub_order && g->callback == w->callback;
        if (!DF_CHECK(t, same)) {
            fprintf(stderr, "  %s, entry %u: kind %u flat %u order %u speed %u sub %u callback %d, want %u %u %u %u %u %d\n",
                    what, (unsigned)i, (unsigned)g->kind, (unsigned)g->flat, (unsigned)g->order, (unsigned)g->speed,
                    (unsigned)g->sub_order, (int)g->callback, (unsigned)w->kind, (unsigned)w->flat, (unsigned)w->order,
                    (unsigned)w->speed, (unsigned)w->sub_order, (int)w->callback);
        }
    }
}

static void check_empty_base(df_test *t, const duoforge_context *ctx)
{
    struct duoforge_battle *b = make_base(t, ctx);
    b->weather = (uint8_t)DFI_WEATHER_NONE;
    b->terrain = (uint8_t)DFI_TERRAIN_NONE;
    dfi_residual_entry list[DFI_RES_MAX];
    uint32_t n = 0u;
    if (collect(t, b, list, &n)) {
        check_list(t, "base", list, n, NULL, 0u);
    }
    duoforge_battle_destroy(b);
}

static void check_everything(df_test *t, const duoforge_context *ctx)
{
    struct duoforge_battle *b = make_base(t, ctx);
    b->trick_room_turns = 3u;
    b->tail.gravity_turns = 4u;
    b->weather = (uint8_t)DFI_WEATHER_RAIN;
    b->weather_turns = 5u;
    b->terrain = (uint8_t)DFI_TERRAIN_ELECTRIC;
    b->terrain_turns = 5u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        for (uint32_t c = 0u; c < COND_COUNT; ++c) {
            set_cond(b, side, c);
        }
    }
    dfi_at(b, 0u)->status = (uint8_t)DFI_STATUS_BRN;
    dfi_at(b, 3u)->status = (uint8_t)DFI_STATUS_BRN;

    dfi_residual_entry want[DFI_RES_MAX];
    uint32_t w = 0u;
    want[w++] = entry(DFI_RES_FIELD_END, DFI_RESIDUAL_FIELD_FLAT, 27u, 0u, 1u, false); /* Trick Room */
    want[w++] = entry(DFI_RES_FIELD_END, DFI_RESIDUAL_FIELD_FLAT, 27u, 0u, 2u, false); /* Gravity */
    want[w++] = entry(DFI_RES_WEATHER, 0u, 1u, 0u, 5u, true);
    want[w++] = entry(DFI_RES_TERRAIN_END, 0u, 27u, 0u, 7u, false);
    for (uint32_t c = 0u; c < COND_COUNT; ++c) {
        want[w++] = cond_entry(0u, c);
    }
    want[w++] = entry(DFI_RES_BURN, 0u, 10u, k_speed[0], 0u, true);
    for (uint32_t c = 0u; c < COND_COUNT; ++c) {
        want[w++] = cond_entry(1u, c);
    }
    want[w++] = entry(DFI_RES_BURN, 3u, 10u, k_speed[3], 0u, true);

    dfi_residual_entry list[DFI_RES_MAX];
    uint32_t n = 0u;
    if (collect(t, b, list, &n)) {
        check_list(t, "everything", list, n, want, w);
    }
    duoforge_battle_destroy(b);
}

static void check_alone(df_test *t, const duoforge_context *ctx)
{
    dfi_residual_entry list[DFI_RES_MAX];
    uint32_t n = 0u;
    for (uint32_t which = 0u; which < 2u; ++which) {
        struct duoforge_battle *b = make_base(t, ctx);
        b->weather = (uint8_t)DFI_WEATHER_NONE;
        b->terrain = (uint8_t)DFI_TERRAIN_NONE;
        if (which == 0u) {
            b->trick_room_turns = 1u;
        } else {
            b->tail.gravity_turns = 1u;
        }
        const dfi_residual_entry want =
            entry(DFI_RES_FIELD_END, DFI_RESIDUAL_FIELD_FLAT, 27u, 0u, which == 0u ? 1u : 2u, false);
        if (collect(t, b, list, &n)) {
            check_list(t, which == 0u ? "Trick Room alone" : "Gravity alone", list, n, &want, 1u);
        }
        duoforge_battle_destroy(b);
    }
    for (uint32_t side = 0u; side < 2u; ++side) {
        for (uint32_t c = 0u; c < COND_COUNT; ++c) {
            struct duoforge_battle *b = make_base(t, ctx);
            b->weather = (uint8_t)DFI_WEATHER_NONE;
            b->terrain = (uint8_t)DFI_TERRAIN_NONE;
            set_cond(b, side, c);
            const dfi_residual_entry want = cond_entry(side, c);
            char what[64];
            snprintf(what, sizeof what, "%s alone on side %u", k_cond_name[c], (unsigned)side);
            if (collect(t, b, list, &n)) {
                check_list(t, what, list, n, &want, 1u);
            }
            duoforge_battle_destroy(b);
        }
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.flow.residual_collect");
    duoforge_context *ctx = df_make_context(&df_config_c1);
    check_empty_base(&t, ctx);
    check_everything(&t, ctx);
    check_alone(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
