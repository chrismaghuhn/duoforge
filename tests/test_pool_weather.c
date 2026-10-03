/*
 * duoforge.state.pool_weather (white-box): the step of Sandstorm and Snowscape (Sand Stream, Snow Warning, the two
 * weather moves) and the weather values of the POOL kinds in the player view (decision 0018, supported bits 0 and 1).
 *
 * The ten recorded battles of the step (w1_sand_stream to w8_sand_soak under "data": "pool") are replayed
 * through the step with the reference's draws, as duoforge.reference.conformance_pool_data does, which compares
 * everything the reference shows. Here the view is checked against the protocol: after every step both players'
 * observation has the weather and the turns left that the `-weather` lines alone give (weather_rows, which
 * tools/reference/test_trace_to_c.py derives from the committed traces and requires to be exactly that), and the view
 * extension is the header of the build's supported mask with every field zero (these battles have no other effect
 * of the extension). Also: the sources of immunity to Sandstorm damage and of indirect-damage protection that the
 * engine does not model are not marked, so no battle holds one (marking one needs its immunity in
 * dfi_sand_immune), and the weather values are valid in a POOL state and in no other kind's.
 */
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
#include "support/team_c.h"

/* The weather after each step of the weather battles, from the -weather lines alone: a line that names a weather sets
 * it for 5 turns, each `[upkeep]` line is one turn gone, `-weather|none` ends it. */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t weather;
    uint32_t turns;
} weather_rows[] = {
    {"w1_sand_stream", 0u, 3u, 5u},
    {"w1_sand_stream", 1u, 3u, 4u},
    {"w1_sand_stream", 2u, 3u, 3u},
    {"w1_sand_stream", 3u, 3u, 2u},
    {"w1_sand_stream", 4u, 3u, 1u},
    {"w1_sand_stream", 5u, 0u, 0u},
    {"w1_sand_stream", 6u, 0u, 0u},
    {"w1_sand_stream", 7u, 0u, 0u},
    {"w1_sand_stream", 8u, 0u, 0u},
    {"w2_sandstorm_move", 0u, 1u, 5u},
    {"w2_sandstorm_move", 1u, 3u, 4u},
    {"w2_sandstorm_move", 2u, 3u, 3u},
    {"w2_sandstorm_move", 3u, 3u, 2u},
    {"w2_sandstorm_move", 4u, 3u, 1u},
    {"w2_sandstorm_move", 5u, 0u, 0u},
    {"w2_sandstorm_move", 6u, 3u, 4u},
    {"w2_sandstorm_move", 7u, 3u, 3u},
    {"w2_sandstorm_move", 8u, 3u, 2u},
    {"w2_sandstorm_move", 9u, 3u, 2u},
    {"w2_sandstorm_move", 10u, 3u, 1u},
    {"w3_snow_warning", 0u, 4u, 5u},
    {"w3_snow_warning", 1u, 4u, 4u},
    {"w3_snow_warning", 2u, 4u, 3u},
    {"w3_snow_warning", 3u, 4u, 3u},
    {"w3_snow_warning", 4u, 4u, 2u},
    {"w3_snow_warning", 5u, 4u, 1u},
    {"w3_snow_warning", 6u, 0u, 0u},
    {"w3_snow_warning", 7u, 0u, 0u},
    {"w3_snow_warning", 8u, 0u, 0u},
    {"w3_snow_warning", 9u, 0u, 0u},
    {"w4_snowscape_move", 0u, 3u, 5u},
    {"w4_snowscape_move", 1u, 3u, 4u},
    {"w4_snowscape_move", 2u, 3u, 4u},
    {"w4_snowscape_move", 3u, 3u, 3u},
    {"w4_snowscape_move", 4u, 3u, 2u},
    {"w4_snowscape_move", 5u, 4u, 4u},
    {"w4_snowscape_move", 6u, 4u, 4u},
    {"w4_snowscape_move", 7u, 3u, 4u},
    {"w4_snowscape_move", 8u, 4u, 4u},
    {"w4_snowscape_move", 9u, 3u, 4u},
    {"w5_sand_tie_four", 0u, 3u, 5u},
    {"w5_sand_tie_four", 1u, 3u, 4u},
    {"w5_sand_tie_four", 2u, 3u, 3u},
    {"w5_sand_tie_four", 3u, 3u, 2u},
    {"w5_sand_tie_four", 4u, 3u, 1u},
    {"w5_sand_tie_four", 5u, 0u, 0u},
    {"w5_sand_tie_four", 6u, 0u, 0u},
    {"w5_sand_tie_pairs", 0u, 3u, 5u},
    {"w5_sand_tie_pairs", 1u, 3u, 4u},
    {"w5_sand_tie_pairs", 2u, 3u, 3u},
    {"w5_sand_tie_pairs", 3u, 3u, 2u},
    {"w5_sand_tie_pairs", 4u, 3u, 1u},
    {"w5_sand_tie_pairs", 5u, 0u, 0u},
    {"w5_sand_tie_pairs", 6u, 0u, 0u},
    {"w5_sand_tie_mixed", 0u, 3u, 5u},
    {"w5_sand_tie_mixed", 1u, 3u, 4u},
    {"w5_sand_tie_mixed", 2u, 3u, 3u},
    {"w5_sand_tie_mixed", 3u, 3u, 2u},
    {"w5_sand_tie_mixed", 4u, 3u, 1u},
    {"w5_sand_tie_mixed", 5u, 0u, 0u},
    {"w5_sand_tie_mixed", 6u, 0u, 0u},
    {"w6_sand_residual_order", 0u, 3u, 5u},
    {"w6_sand_residual_order", 1u, 3u, 4u},
    {"w6_sand_residual_order", 2u, 3u, 3u},
    {"w6_sand_residual_order", 3u, 3u, 2u},
    {"w6_sand_residual_order", 4u, 3u, 1u},
    {"w6_sand_residual_order", 5u, 3u, 1u},
    {"w6_sand_residual_order", 6u, 0u, 0u},
    {"w6_sand_residual_order", 7u, 0u, 0u},
    {"w7_sand_ko_sitrus", 0u, 3u, 5u},
    {"w7_sand_ko_sitrus", 1u, 3u, 4u},
    {"w7_sand_ko_sitrus", 2u, 3u, 3u},
    {"w7_sand_ko_sitrus", 3u, 3u, 3u},
    {"w7_sand_ko_sitrus", 4u, 3u, 2u},
    {"w7_sand_ko_sitrus", 5u, 3u, 1u},
    {"w7_sand_ko_sitrus", 6u, 3u, 1u},
    {"w7_sand_ko_sitrus", 7u, 0u, 0u},
    {"w8_sand_soak", 0u, 3u, 5u},
    {"w8_sand_soak", 1u, 3u, 4u},
    {"w8_sand_soak", 2u, 3u, 3u},
    {"w8_sand_soak", 3u, 3u, 2u},
    {"w8_sand_soak", 4u, 3u, 1u},
    {"w8_sand_soak", 5u, 0u, 0u},
    {"w8_sand_soak", 6u, 0u, 0u},
};

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

static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

static void check_view(df_test *t, const duoforge_context *ctx)
{
    static const char *const names[] = {"w1_sand_stream",    "w2_sandstorm_move",   "w3_snow_warning",
                                        "w4_snowscape_move", "w5_sand_tie_four",    "w5_sand_tie_pairs",
                                        "w5_sand_tie_mixed", "w6_sand_residual_order", "w7_sand_ko_sitrus", "w8_sand_soak"};
    uint32_t compared = 0u;
    uint32_t sand_steps = 0u;
    uint32_t snow_steps = 0u;
    const uint64_t weather_bits = ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_WEATHER_SAND) |
                                  ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_WEATHER_SNOW);
    DF_CHECK(t, (dfi_support.view_ext_features & weather_bits) == weather_bits);
    for (size_t n = 0u; n < sizeof names / sizeof names[0]; ++n) {
        const df_conf_battle *cb = find(names[n]);
        if (!DF_CHECK(t, cb != NULL)) {
            continue;
        }
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        duoforge_battle *b = NULL;
        if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
            continue;
        }
        for (uint32_t si = 0u; si < cb->step_count; ++si) {
            const df_conf_step *st = &cb->steps[si];
            duoforge_decision_bundle bd;
            bundle_of(st, b, &bd);
            duoforge_step_result res;
            uint32_t used = 0u;
            if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                                 DUOFORGE_OK)) {
                break;
            }
            uint32_t weather = 0xFFu;
            uint32_t turns = 0xFFu;
            for (size_t r = 0u; r < sizeof weather_rows / sizeof weather_rows[0]; ++r) {
                if (strcmp(weather_rows[r].battle, names[n]) == 0 && weather_rows[r].step == si) {
                    weather = weather_rows[r].weather;
                    turns = weather_rows[r].turns;
                }
            }
            if (!DF_CHECK(t, weather != 0xFFu)) {
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
                continue;
            }
            sand_steps += weather == DUOFORGE_WEATHER_SAND ? 1u : 0u;
            snow_steps += weather == DUOFORGE_WEATHER_SNOW ? 1u : 0u;
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation ob;
                duoforge_observation_ext ext;
                memset(&ob, 0, sizeof ob);
                memset(&ext, 0xA5, sizeof ext);
                if (!DF_CHECK(t, duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK &&
                                     duoforge_battle_observe_ext(ctx, b, viewer, &ext) == DUOFORGE_OK)) {
                    continue;
                }
                if (!DF_CHECK(t, ob.weather == weather && ob.weather_turns == turns)) {
                    fprintf(stderr,
                            "  %s step %u viewer %u: the view shows weather %u for %u turns, the lines say %u for %u\n",
                            names[n], si, viewer, ob.weather, ob.weather_turns, weather, turns);
                }
                duoforge_observation_ext want;
                memset(&want, 0, sizeof want);
                want.revision = (uint8_t)DUOFORGE_OBSERVATION_EXT_REVISION;
                want.player = (uint8_t)viewer;
                want.epoch = ob.epoch;
                want.supported = dfi_support.view_ext_features;
                /* w8_sand_soak has Soaked positions (TYPE_CHANGED, type_now: step G11's fields, checked against the
                 * protocol by duoforge.state.pool_g11 for its own battles); the weather needs no other field. */
                if (strcmp(names[n], "w8_sand_soak") != 0) {
                    DF_CHECK(t, memcmp(&ext, &want, sizeof want) == 0);
                } else {
                    DF_CHECK(t, ext.supported == want.supported && ext.epoch == want.epoch);
                }
                compared += 1u;
            }
        }
        duoforge_battle_destroy(b);
    }
    DF_CHECK_EQ_U64(t, compared, 2u * (uint32_t)(sizeof weather_rows / sizeof weather_rows[0]));
    /* The battles show both new weathers for several steps each (the check above is not vacuous). */
    DF_CHECK_EQ_U64(t, sand_steps, 54u);
    DF_CHECK_EQ_U64(t, snow_steps, 9u);
}

/* The abilities and the item that the pinned data gives immunity to Sandstorm damage (onImmunity 'sandstorm': Sand Force,
 * Sand Rush, Sand Veil; the item that does so, Safety Goggles, is not in the pool) or protection from
 * indirect damage (Magic Guard): the engine has an immunity for Sand Rush (step G22), Overcoat (step G30) and Sand Veil (step G39) in
 * dfi_sand_immune, so the others stay unmarked. The abilities that suppress or override the weather that the Speed abilities of step G22 read
 * (Cloud Nine; Mega Sol makes Pokemon#effectiveWeather sunny for its holder's moves; Air Lock and Utility Umbrella are
 * not in the pool at all) stay unmarked too, and so do the ones that break an ability (Inner Focus is breakable): no
 * battle holds any of them. The pinned-data side of this list is checked by tools/datagen/pool_families.js. */
static void check_unmodelled_sources(df_test *t)
{
    static const uint32_t abilities[] = {DFI_ABILITY_SANDFORCE,
                                         DFI_ABILITY_MAGICGUARD, DFI_ABILITY_CLOUDNINE, DFI_ABILITY_MEGASOL,
                                         DFI_ABILITY_MOLDBREAKER};
    for (size_t i = 0u; i < sizeof abilities / sizeof abilities[0]; ++i) {
        DF_CHECK_EQ_U64(t, dfi_support.abilities[abilities[i]], 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[abilities[i]], DFI_HANDLER_UNMODELED);
    }
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_SANDRUSH], 1u); /* step G22: its immunity is dfi_sand_immune */
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_SANDVEIL], 1u); /* step G39: so is Sand Veil's */
    DF_CHECK_EQ_U64(t, dfi_support.items[DFI_ITEM_SMOOTHROCK], 0u); /* Sandstorm for 8 turns */
    DF_CHECK_EQ_U64(t, dfi_support.items[DFI_ITEM_ICYROCK], 0u);    /* Snowscape for 8 turns */
    /* Sand Stream and Snow Warning, the two moves, and the immunity bit of exactly three types. */
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_SANDSTREAM] != 0u && dfi_support.abilities[DFI_ABILITY_SNOWWARNING] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_SANDSTORM] != 0u && dfi_support.moves[DFI_MOVE_SNOWSCAPE] != 0u);
    uint32_t immune = 0u;
    for (uint32_t type = 0u; type < DFI_TYPE_COUNT; ++type) {
        const bool want = type == DFI_TYPE_GROUND || type == DFI_TYPE_ROCK || type == DFI_TYPE_STEEL;
        DF_CHECK_EQ_U64(t, (dfi_pool_type_immunity[type] & DFI_IMMUNE_SAND) != 0u ? 1u : 0u, want ? 1u : 0u);
        immune += (dfi_pool_type_immunity[type] & DFI_IMMUNE_SAND) != 0u ? 1u : 0u;
    }
    DF_CHECK_EQ_U64(t, immune, 3u);
}

/* The weather values are state: valid in a POOL battle (round trip through encode and decode), refused in the state
 * of every other combat kind, and no value beyond Snow is a weather. */
static void check_state(df_test *t)
{
    duoforge_battle_setup s;
    df_setup_teams(&s);
    duoforge_context *pool = df_make_context(&df_config_pool);
    duoforge_context *team_c = df_make_context(&df_config_team_c);
    duoforge_context *closure = df_make_context(&df_config_k1);
    duoforge_battle *b = df_make_battle(pool, &s);
    duoforge_battle *x = NULL;
    DF_CHECK(t, duoforge_battle_clone(pool, b, &x) == DUOFORGE_OK);
    for (uint32_t w = DUOFORGE_WEATHER_SAND; w <= DUOFORGE_WEATHER_SNOW; ++w) {
        x->weather = (uint8_t)w;
        x->weather_turns = 3u;
        DF_CHECK(t, duoforge_battle_check(pool, x) == DUOFORGE_OK);
        uint8_t bytes[DF_STATE_ENCODED_MAX];
        const size_t size = df_encode_n(pool, x, bytes);
        duoforge_battle *y = NULL;
        DF_CHECK(t, duoforge_battle_create_decoded(pool, bytes, size, &y) == DUOFORGE_OK && y != NULL);
        bool same = false;
        DF_CHECK(t, y != NULL && duoforge_battle_equal(pool, x, y, &same) == DUOFORGE_OK && same);
        DF_CHECK(t, y != NULL && y->weather == w && y->weather_turns == 3u);
        duoforge_battle_destroy(y);
    }
    x->weather = (uint8_t)(DUOFORGE_WEATHER_SNOW + 1u);
    DF_CHECK(t, duoforge_battle_check(pool, x) == DUOFORGE_E_INVARIANT);
    x->weather = (uint8_t)DUOFORGE_WEATHER_SAND;
    x->weather_turns = 0u; /* a weather has turns */
    DF_CHECK(t, duoforge_battle_check(pool, x) == DUOFORGE_E_INVARIANT);
    x->weather_turns = 6u; /* never more than 5 (the rock items are not marked) */
    DF_CHECK(t, duoforge_battle_check(pool, x) == DUOFORGE_E_INVARIANT);
    duoforge_battle_destroy(x);
    duoforge_battle_destroy(b);
    /* Not in the kinds that have no Sandstorm: the same state under TEAM_C and CLOSURE is E_INVARIANT. */
    for (int k = 0; k < 2; ++k) {
        duoforge_context *ctx = k == 0 ? team_c : closure;
        duoforge_battle *c = df_make_battle(ctx, &s);
        DF_CHECK(t, duoforge_battle_clone(ctx, c, &x) == DUOFORGE_OK);
        for (uint32_t w = DUOFORGE_WEATHER_SUN + 1u; w <= DUOFORGE_WEATHER_SNOW; ++w) {
            x->weather = (uint8_t)w;
            x->weather_turns = 3u;
            DF_CHECK(t, duoforge_battle_check(ctx, x) == DUOFORGE_E_INVARIANT);
        }
        x->weather = (uint8_t)DUOFORGE_WEATHER_SUN;
        x->weather_turns = 3u;
        DF_CHECK(t, duoforge_battle_check(ctx, x) == DUOFORGE_OK); /* the old values stay valid */
        duoforge_battle_destroy(x);
        duoforge_battle_destroy(c);
    }
    duoforge_context_destroy(closure);
    duoforge_context_destroy(team_c);
    duoforge_context_destroy(pool);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_weather");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    check_view(&t, kp);
    check_unmodelled_sources(&t);
    check_state(&t);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
