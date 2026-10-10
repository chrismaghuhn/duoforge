/*
 * duoforge.state.pool_g55 (white-box): step G55 of the content expansion, the rock items Damp Rock, Heat Rock, Smooth Rock and
 * Icy Rock and Terrain Extender (decision 0015, item 5bf). A weather or a terrain that its setter starts lasts 8 turns while the
 * setter holds the item that lengthens it, else 5 (data/conditions.ts durationCallback: source?.hasItem; data/moves.ts terrains).
 * The setter is the Pokemon that uses the move, or the holder of the ability (Field.setWeather and setTerrain pass it as the
 * source, sim/field.ts:41-42 and :78-81, :147-149). The rule change: DFI_FIELD_TURNS_EXTENDED_MAX (8) bounds the weather and the
 * terrain of the state; Trick Room keeps DFI_FIELD_TURNS_MAX (5).
 *
 *   - the marks and the handler columns of the five items (ENGINE_ROWS: no handler, no family, not UNMODELED);
 *   - the constants and the bounds of the state (8 is valid, 9 is refused for weather and terrain; Trick Room stays at 5);
 *   - the recorded battles (g55_*, under "data": "pool") step by step: the weather or the terrain turns that the engine
 *     holds after every step, pinned from the reference's own values (the trace's weather and terrain durations).
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

static void check_facts(df_test *t)
{
    static const uint32_t rocks[] = {DFI_ITEM_DAMPROCK, DFI_ITEM_HEATROCK, DFI_ITEM_SMOOTHROCK, DFI_ITEM_ICYROCK,
                                     DFI_ITEM_TERRAINEXTENDER};
    for (size_t i = 0u; i < sizeof rocks / sizeof rocks[0]; ++i) {
        DF_CHECK(t, dfi_support.items[rocks[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_item_handler[rocks[i]], DFI_HANDLER_NONE);
        DF_CHECK_EQ_U64(t, dfi_pool_item_family[rocks[i]].family, DFI_ITEM_FAMILY_NONE);
    }
}

static void check_constants(df_test *t)
{
    DF_CHECK_EQ_U64(t, DFI_FIELD_TURNS_MAX, 5u);
    DF_CHECK_EQ_U64(t, DFI_FIELD_TURNS_EXTENDED_MAX, 8u);
}

/* The bounds of the state in a POOL battle: weather and terrain up to 8 turns, Trick Room still up to 5. */
static void check_bounds(df_test *t)
{
    duoforge_context *pool = df_make_context(&df_config_pool);
    duoforge_battle_setup s;
    df_setup_teams(&s);
    duoforge_battle *b = df_make_battle(pool, &s);
    duoforge_battle *x = NULL;
    DF_CHECK(t, duoforge_battle_clone(pool, b, &x) == DUOFORGE_OK && x != NULL);
    x->weather = (uint8_t)DUOFORGE_WEATHER_RAIN;
    x->weather_turns = 8u;
    DF_CHECK(t, duoforge_battle_check(pool, x) == DUOFORGE_OK);
    x->weather_turns = 9u;
    DF_CHECK(t, duoforge_battle_check(pool, x) == DUOFORGE_E_INVARIANT);
    x->weather = (uint8_t)DUOFORGE_WEATHER_NONE;
    x->weather_turns = 0u;
    x->terrain = (uint8_t)DUOFORGE_TERRAIN_ELECTRIC;
    x->terrain_turns = 8u;
    DF_CHECK(t, duoforge_battle_check(pool, x) == DUOFORGE_OK);
    x->terrain = (uint8_t)DUOFORGE_TERRAIN_NONE;
    x->terrain_turns = 0u;
    x->trick_room_turns = 6u; /* Trick Room is not a setter with a rock: 5 is its bound */
    DF_CHECK(t, duoforge_battle_check(pool, x) == DUOFORGE_E_INVARIANT);
    x->trick_room_turns = 5u;
    DF_CHECK(t, duoforge_battle_check(pool, x) == DUOFORGE_OK);
    duoforge_battle_destroy(x);
    duoforge_battle_destroy(b);
    duoforge_context_destroy(pool);
}

/* ---- the recorded battles, step by step (the conformance pattern of test_pool_g49.c) ---- */

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

static void bundle_of(const df_conf_step *st, const duoforge_battle *b, duoforge_decision_bundle *bd)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u)); /* wide-operands-reviewed */
    for (uint32_t s = 0; s < 2u; ++s) {
        if ((s == 0u && !st->answered0) || (s == 1u && !st->answered1)) {
            continue;
        }
        duoforge_side_choice *r = &bd->responses[s];
        r->epoch = b->request_epoch;
        r->side = (uint8_t)s;
        if (st->team) {
            r->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
            r->pick_count = 4u;
            for (uint32_t i = 0; i < 4u; ++i) {
                r->picks[i] = st->picks[s][i];
            }
        } else {
            r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
            for (uint32_t k = 0; k < 2u; ++k) {
                const df_conf_cmd *c = &st->cmds[s][k];
                r->slots[k] = (duoforge_slot_command){c->kind, c->move_slot, c->target, c->mega, c->reserve, {0u, 0u, 0u}};
            }
        }
    }
}

/* The turns of the field after each of the nine steps, as the reference recorded them (the weather or terrain turns of the
 * trace's steps): a weather set by an ability at the start is 8 after step 0; one set by a move in turn 1 is 8 at its step and
 * 7 after that step's residual (the first upkeep), so both end after step 8; the Knock Off battle's rain lasts 5 (ends after
 * step 5). */
struct g55_expect {
    const char *name;
    uint32_t weather, terrain;
    uint32_t weather_turns[9];
    uint32_t terrain_turns[9];
};

static const struct g55_expect g55_expected[] = {
    {"g55_damp_rock_drizzle", DFI_WEATHER_RAIN, 0u, {8, 7, 6, 5, 4, 3, 2, 1, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {"g55_damp_rock_rain_dance", DFI_WEATHER_RAIN, 0u, {0, 7, 6, 5, 4, 3, 2, 1, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {"g55_damp_rock_knock_off", DFI_WEATHER_RAIN, 0u, {0, 4, 3, 2, 1, 0, 0, 0, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {"g55_heat_rock_drought", DFI_WEATHER_SUN, 0u, {8, 7, 6, 5, 4, 3, 2, 1, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {"g55_heat_rock_sunny_day", DFI_WEATHER_SUN, 0u, {0, 7, 6, 5, 4, 3, 2, 1, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {"g55_smooth_rock_sand_stream", DFI_WEATHER_SAND, 0u, {8, 7, 6, 5, 4, 3, 2, 1, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {"g55_smooth_rock_sandstorm", DFI_WEATHER_SAND, 0u, {0, 7, 6, 5, 4, 3, 2, 1, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {"g55_icy_rock_snow_warning", DFI_WEATHER_SNOW, 0u, {8, 7, 6, 5, 4, 3, 2, 1, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {"g55_icy_rock_snowscape", DFI_WEATHER_SNOW, 0u, {0, 7, 6, 5, 4, 3, 2, 1, 0}, {0, 0, 0, 0, 0, 0, 0, 0, 0}},
    {"g55_terrain_extender_electric_surge", 0u, DFI_TERRAIN_ELECTRIC, {0, 0, 0, 0, 0, 0, 0, 0, 0}, {8, 7, 6, 5, 4, 3, 2, 1, 0}},
    {"g55_terrain_extender_electric_terrain", 0u, DFI_TERRAIN_ELECTRIC, {0, 0, 0, 0, 0, 0, 0, 0, 0}, {0, 7, 6, 5, 4, 3, 2, 1, 0}},
    {"g55_terrain_extender_grassy_surge", 0u, DFI_TERRAIN_GRASSY, {0, 0, 0, 0, 0, 0, 0, 0, 0}, {8, 7, 6, 5, 4, 3, 2, 1, 0}},
    {"g55_terrain_extender_misty_terrain", 0u, DFI_TERRAIN_MISTY, {0, 0, 0, 0, 0, 0, 0, 0, 0}, {0, 7, 6, 5, 4, 3, 2, 1, 0}},
    {"g55_terrain_extender_psychic_surge", 0u, DFI_TERRAIN_PSYCHIC, {0, 0, 0, 0, 0, 0, 0, 0, 0}, {8, 7, 6, 5, 4, 3, 2, 1, 0}},
};

static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

static void check_recorded(df_test *t, duoforge_context *ctx, const struct g55_expect *e)
{
    const df_conf_battle *cb = find(e->name);
    if (!DF_CHECK(t, cb != NULL && cb->step_count == 9u)) {
        return;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return;
    }
    for (uint32_t si = 0; si < cb->step_count; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        const duoforge_status status = dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (!DF_CHECK(t, status == DUOFORGE_OK)) {
            break;
        }
        DF_CHECK_EQ_U64(t, b->weather_turns, e->weather_turns[si]);
        DF_CHECK_EQ_U64(t, b->terrain_turns, e->terrain_turns[si]);
        if (e->weather_turns[si] != 0u) {
            DF_CHECK_EQ_U64(t, b->weather, e->weather);
        }
        if (e->terrain_turns[si] != 0u) {
            DF_CHECK_EQ_U64(t, b->terrain, e->terrain);
        }
    }
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g55");
    check_facts(&t);
    check_constants(&t);
    check_bounds(&t);
    duoforge_context *pool = df_make_context(&df_config_pool);
    for (size_t i = 0u; i < sizeof g55_expected / sizeof g55_expected[0]; ++i) {
        check_recorded(&t, pool, &g55_expected[i]);
    }
    duoforge_context_destroy(pool);
    return df_test_end(&t);
}
