/*
 * duoforge.state.pool_terrain (white-box): the step of Electric Terrain and Misty Terrain (Electric Surge, the two terrain
 * moves, Electric Seed and Misty Seed, Rising Voltage, Terrain Pulse, step G25) and the terrain values Electric and Misty of
 * the POOL kinds in the player view (decision 0018, supported bits 5 and 32).
 *
 * The six recorded battles of the step (g25_* under "data": "pool") are replayed through the step with the reference's
 * draws, as duoforge.reference.conformance_pool_data does, which compares everything the reference shows. Here the view is
 * checked against the protocol: after every step both players' observation has the terrain and the turns left that the
 * `-fieldstart` and `-fieldend` lines and the `|upkeep` lines alone give (terrain_rows, which
 * tools/reference/test_trace_to_c.py derives from the committed traces and requires to be exactly that), and the view
 * extension is the header of the build's supported mask with every field zero (these battles have no other effect of
 * the extension). Also: the sources of the terrains' effects that the engine does not model are not marked (Surge Surfer,
 * Terrain Extender, Mimicry, Seed Sower, Grass Pelt, Steel Roller, Ice Spinner, Misty Explosion), the terrain values are
 * valid in a POOL state and in no other kind's, and the numbers that the damage rules use are the pinned ones.
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

/* The terrain after each step of the terrain battles, from the lines alone: a `-fieldstart` line that names a terrain sets
 * it for 5 turns (the replaced terrain ends without a line), each `|upkeep` line with a terrain up is one turn gone, a
 * `-fieldend` line ends it. The values are the engine's (DFI_TERRAIN_*: 3 Electric, 4 Misty, 2 Psychic). */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t terrain;
    uint32_t turns;
} terrain_rows[] = {
    {"g25_electric_surge_voltage", 0u, 3u, 5u},
    {"g25_electric_surge_voltage", 1u, 3u, 4u},
    {"g25_electric_surge_voltage", 2u, 3u, 3u},
    {"g25_electric_surge_voltage", 3u, 3u, 2u},
    {"g25_electric_surge_voltage", 4u, 3u, 1u},
    {"g25_electric_surge_voltage", 5u, 0u, 0u},
    {"g25_electric_seed", 0u, 0u, 0u},
    {"g25_electric_seed", 1u, 3u, 4u},
    {"g25_electric_seed", 2u, 3u, 3u},
    {"g25_electric_seed", 3u, 3u, 2u},
    {"g25_electric_seed", 4u, 3u, 1u},
    {"g25_electric_seed", 5u, 0u, 0u},
    {"g25_misty_terrain", 0u, 0u, 0u},
    {"g25_misty_terrain", 1u, 4u, 4u},
    {"g25_misty_terrain", 2u, 4u, 3u},
    {"g25_misty_terrain", 3u, 4u, 2u},
    {"g25_misty_terrain", 4u, 4u, 1u},
    {"g25_misty_terrain", 5u, 0u, 0u},
    {"g25_terrain_pulse_psychic_misty", 0u, 2u, 5u},
    {"g25_terrain_pulse_psychic_misty", 1u, 4u, 4u},
    {"g25_terrain_pulse_psychic_misty", 2u, 4u, 3u},
    {"g25_terrain_pulse_psychic_misty", 3u, 4u, 2u},
    {"g25_terrain_pulse_psychic_misty", 4u, 4u, 1u},
    {"g25_terrain_pulse_psychic_misty", 5u, 0u, 0u},
    {"g25_terrain_pulse_electric", 0u, 3u, 5u},
    {"g25_terrain_pulse_electric", 1u, 3u, 4u},
    {"g25_terrain_pulse_electric", 2u, 3u, 3u},
    {"g25_terrain_pulse_electric", 3u, 3u, 2u},
    {"g25_terrain_pulse_electric", 4u, 3u, 1u},
    {"g25_terrain_pulse_electric", 5u, 0u, 0u},
    {"g25_weather_ball_refrigerate", 0u, 0u, 0u},
    {"g25_weather_ball_refrigerate", 1u, 0u, 0u},
    {"g25_weather_ball_refrigerate", 2u, 0u, 0u},
    {"g25_weather_ball_refrigerate", 3u, 0u, 0u},
    {"g25_weather_ball_refrigerate", 4u, 0u, 0u},
    {"g25_weather_ball_refrigerate", 5u, 0u, 0u},
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
    static const char *const names[] = {"g25_electric_surge_voltage", "g25_electric_seed", "g25_misty_terrain",
                                        "g25_terrain_pulse_psychic_misty", "g25_terrain_pulse_electric",
                                        "g25_weather_ball_refrigerate"};
    uint32_t compared = 0u;
    uint32_t electric_steps = 0u;
    uint32_t misty_steps = 0u;
    uint32_t psychic_steps = 0u;
    const uint64_t terrain_bits = ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_TERRAIN_ELECTRIC) |
                                  ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_TERRAIN_MISTY);
    DF_CHECK(t, (dfi_support.view_ext_features & terrain_bits) == terrain_bits);
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
            uint32_t terrain = 0xFFu;
            uint32_t turns = 0xFFu;
            for (size_t r = 0u; r < sizeof terrain_rows / sizeof terrain_rows[0]; ++r) {
                if (strcmp(terrain_rows[r].battle, names[n]) == 0 && terrain_rows[r].step == si) {
                    terrain = terrain_rows[r].terrain;
                    turns = terrain_rows[r].turns;
                }
            }
            if (!DF_CHECK(t, terrain != 0xFFu)) {
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
                continue;
            }
            electric_steps += terrain == DUOFORGE_TERRAIN_ELECTRIC ? 1u : 0u;
            misty_steps += terrain == DUOFORGE_TERRAIN_MISTY ? 1u : 0u;
            psychic_steps += terrain == DUOFORGE_TERRAIN_PSYCHIC ? 1u : 0u;
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation ob;
                duoforge_observation_ext ext;
                memset(&ob, 0, sizeof ob);
                memset(&ext, 0xA5, sizeof ext);
                if (!DF_CHECK(t, duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK &&
                                     duoforge_battle_observe_ext(ctx, b, viewer, &ext) == DUOFORGE_OK)) {
                    continue;
                }
                if (!DF_CHECK(t, ob.terrain == terrain && ob.terrain_turns == turns)) {
                    fprintf(stderr,
                            "  %s step %u viewer %u: the view shows terrain %u for %u turns, the lines say %u for %u\n",
                            names[n], si, viewer, ob.terrain, ob.terrain_turns, terrain, turns);
                }
                duoforge_observation_ext want;
                memset(&want, 0, sizeof want);
                want.revision = (uint8_t)DUOFORGE_OBSERVATION_EXT_REVISION;
                want.player = (uint8_t)viewer;
                want.epoch = ob.epoch;
                want.supported = dfi_support.view_ext_features;
                DF_CHECK(t, memcmp(&ext, &want, sizeof want) == 0);
                compared += 1u;
            }
        }
        duoforge_battle_destroy(b);
    }
    DF_CHECK_EQ_U64(t, compared, 2u * (uint32_t)(sizeof terrain_rows / sizeof terrain_rows[0]));
    /* The battles show every terrain the step adds for several steps (the check above is not vacuous). */
    DF_CHECK_EQ_U64(t, electric_steps, 14u);
    DF_CHECK_EQ_U64(t, misty_steps, 8u);
    DF_CHECK_EQ_U64(t, psychic_steps, 1u);
}

/* What the step marks and what it leaves out: the sources of the terrains' effects that the engine does not model are
 * unmarked rows, so no battle holds one. Surge Surfer (Speed x2 in Electric Terrain), Mimicry (the type of the terrain),
 * Seed Sower and Grass Pelt (Grassy Terrain), Terrain Extender (eight turns), Steel Roller and Ice Spinner (they clear the
 * terrain) and Misty Explosion (x1.5 in Misty Terrain) read the terrain by a callback of their own. */
static void check_marks(df_test *t)
{
    static const uint32_t abilities[] = {DFI_ABILITY_SURGESURFER, DFI_ABILITY_MIMICRY, DFI_ABILITY_SEEDSOWER, DFI_ABILITY_GRASSPELT};
    for (size_t i = 0u; i < sizeof abilities / sizeof abilities[0]; ++i) {
        DF_CHECK_EQ_U64(t, dfi_support.abilities[abilities[i]], 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[abilities[i]], DFI_HANDLER_UNMODELED);
    }
    DF_CHECK_EQ_U64(t, dfi_support.items[DFI_ITEM_TERRAINEXTENDER], 0u);
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_STEELROLLER], 0u);
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_ICESPINNER], 0u);
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_MISTYEXPLOSION], 0u);
    /* The step's rows: both terrain moves, Rising Voltage and Terrain Pulse with their handlers, Electric Surge (a terrain
     * setter of the family column, Electric: code 3), Electric Seed and Misty Seed (engine rows). Misty Surge is not in the
     * pool. */
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_ELECTRICTERRAIN] != 0u && dfi_support.moves[DFI_MOVE_MISTYTERRAIN] != 0u &&
                    dfi_support.moves[DFI_MOVE_RISINGVOLTAGE] != 0u && dfi_support.moves[DFI_MOVE_TERRAINPULSE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_ELECTRICSURGE] != 0u && dfi_support.items[DFI_ITEM_ELECTRICSEED] != 0u &&
                    dfi_support.items[DFI_ITEM_MISTYSEED] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_family[DFI_ABILITY_ELECTRICSURGE].family, DFI_ABILITY_FAMILY_TERRAIN_SETTER);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_family[DFI_ABILITY_ELECTRICSURGE].param, DFI_FAMILY_TERRAIN_ELECTRIC);
    DF_CHECK_EQ_U64(t, DFI_FAMILY_TERRAIN_ELECTRIC, DFI_TERRAIN_ELECTRIC); /* the codes of the column are the state values */
    DF_CHECK_EQ_U64(t, DFI_FAMILY_TERRAIN_MISTY, DFI_TERRAIN_MISTY);
    DF_CHECK_EQ_U64(t, DFI_FAMILY_TERRAIN_GRASSY, DFI_TERRAIN_GRASSY);
    DF_CHECK_EQ_U64(t, DFI_FAMILY_TERRAIN_PSYCHIC, DFI_TERRAIN_PSYCHIC);
    /* The public values and the internal ones agree (step G25's two new public values are the field details 4 and 5). */
    DF_CHECK_EQ_U64(t, DUOFORGE_FIELD_ELECTRIC_TERRAIN, 4u);
    DF_CHECK_EQ_U64(t, DUOFORGE_FIELD_MISTY_TERRAIN, 5u);
    DF_CHECK_EQ_U64(t, DUOFORGE_TERRAIN_ELECTRIC, DFI_TERRAIN_ELECTRIC);
    DF_CHECK_EQ_U64(t, DUOFORGE_TERRAIN_MISTY, DFI_TERRAIN_MISTY);
    DF_CHECK_EQ_U64(t, DUOFORGE_VIEWEXT_FEATURE_TERRAIN_ELECTRIC, 5u);
    DF_CHECK_EQ_U64(t, DUOFORGE_VIEWEXT_FEATURE_TERRAIN_MISTY, 32u);
    /* Rising Voltage is a plain Electric move of 70 and Terrain Pulse a plain Normal move of 50: the engine adds the
     * terrain rules, the table does not (nothing in the columns). */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_RISINGVOLTAGE].type, DFI_TYPE_ELECTRIC);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_RISINGVOLTAGE].base_power, 70u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_TERRAINPULSE].type, DFI_TYPE_NORMAL);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_TERRAINPULSE].base_power, 50u);
}

/* The terrain values are state: valid in a POOL battle (round trip through encode and decode), refused in the state of
 * every other combat kind (Electric and Misty), and no value beyond Misty is a terrain. */
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
    for (uint32_t v = DUOFORGE_TERRAIN_ELECTRIC; v <= DUOFORGE_TERRAIN_MISTY; ++v) {
        x->terrain = (uint8_t)v;
        x->terrain_turns = 3u;
        DF_CHECK(t, duoforge_battle_check(pool, x) == DUOFORGE_OK);
        uint8_t bytes[DF_STATE_ENCODED_MAX];
        const size_t size = df_encode_n(pool, x, bytes);
        duoforge_battle *y = NULL;
        DF_CHECK(t, duoforge_battle_create_decoded(pool, bytes, size, &y) == DUOFORGE_OK && y != NULL);
        bool same = false;
        DF_CHECK(t, y != NULL && duoforge_battle_equal(pool, x, y, &same) == DUOFORGE_OK && same);
        DF_CHECK(t, y != NULL && y->terrain == v && y->terrain_turns == 3u);
        duoforge_battle_destroy(y);
    }
    x->terrain = (uint8_t)(DUOFORGE_TERRAIN_MISTY + 1u);
    DF_CHECK(t, duoforge_battle_check(pool, x) == DUOFORGE_E_INVARIANT);
    x->terrain = (uint8_t)DUOFORGE_TERRAIN_ELECTRIC;
    x->terrain_turns = 0u; /* a terrain has turns */
    DF_CHECK(t, duoforge_battle_check(pool, x) == DUOFORGE_E_INVARIANT);
    x->terrain_turns = 6u; /* never more than 5 (Terrain Extender is not marked) */
    DF_CHECK(t, duoforge_battle_check(pool, x) == DUOFORGE_E_INVARIANT);
    duoforge_battle_destroy(x);
    duoforge_battle_destroy(b);
    /* Not in the kinds that have neither: the same state under TEAM_C and CLOSURE is E_INVARIANT. */
    for (int k = 0; k < 2; ++k) {
        duoforge_context *ctx = k == 0 ? team_c : closure;
        duoforge_battle *c = df_make_battle(ctx, &s);
        DF_CHECK(t, duoforge_battle_clone(ctx, c, &x) == DUOFORGE_OK);
        for (uint32_t v = DUOFORGE_TERRAIN_ELECTRIC; v <= DUOFORGE_TERRAIN_MISTY; ++v) {
            x->terrain = (uint8_t)v;
            x->terrain_turns = 3u;
            DF_CHECK(t, duoforge_battle_check(ctx, x) == DUOFORGE_E_INVARIANT);
        }
        x->terrain = (uint8_t)DUOFORGE_TERRAIN_GRASSY;
        x->terrain_turns = 3u;
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
    df_test_begin(&t, "duoforge.state.pool_terrain");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    check_view(&t, kp);
    check_marks(&t);
    check_state(&t);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
