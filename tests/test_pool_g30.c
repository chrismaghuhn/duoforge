/*
 * duoforge.state.pool_g30 (white-box): step G30 of the content expansion: Rage Powder with the powder immunity (a Grass
 * type, Overcoat), Psychic Fangs, Solar Beam, Flame Body, Clear Body, Hospitality and Overcoat, and the data rows that
 * only waited for a recorded battle (the status powders, Matcha Gotcha, Giga Drain, Energy Ball, Play Rough).
 *
 * The recorded battles (g30_* under "data": "pool") are replayed through the step with the reference's draws, as in
 * duoforge.reference.conformance_pool_data, which compares everything that the reference shows: every HP and status,
 * every line (the redirected move lines, the -immune lines of the powders and of Overcoat, the -sideend lines of Psychic
 * Fangs, the -prepare / [still] / -anim lines of Solar Beam, the -fail ... unboost lines of Clear Body, Hospitality's
 * -heal), and the tape (Flame Body's draw is the site FLAME_BODY, 18).
 *
 * What the reference does not show is read here. Rage Powder shares the position's Follow Me bit with Follow Me and the
 * last move of the occupant tells them apart (dfi_last_move_id), so after every step:
 *   - the extension of both viewers has the position bit RAGE_POWDER (decision 0018, supported bit 39, public) exactly
 *     where the protocol says Rage Powder stands: at the PIVOT boundary inside the turn of g30_rage_powder_pivot, between
 *     Talonflame's U-turn and the end of the turn; and at no turn boundary, in any battle (the residual ends it);
 *   - no position shows Follow Me's flag in the player view (the volatile of a Rage Powder user is not Follow Me's);
 *   - no other volatile bit of the extension is set (these battles have none).
 * Also the facts that the engine relies on: the marks, the special numbers, the powder flag of exactly six moves, the
 * sources of weather and charge changes that the engine does not model stay unmarked (Utility Umbrella and Mega Sol
 * change effectiveWeather, Power Herb is the ChargeMove event, Stomping Tantrum needs a last-move-failed flag), and no
 * Grass-type forme can have Clear Body or Trace (Flower Veil's order with Clear Body).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/request.h"
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

static const char *const names[] = {
    "g30_rage_powder_a",     "g30_overcoat_rage",      "g30_rage_powder_pivot", "g30_overcoat_powder", "g30_powder_a",
    "g30_powder_b",          "g30_psychic_fangs",      "g30_solar_beam_sun_rain", "g30_solar_beam_sand_snow",
    "g30_flame_body",        "g30_flame_body_ko",      "g30_clear_body",        "g30_hospitality",      "g30_hospitality_trace",
    "g30_matcha_drain_rows"};

/* The one boundary of the battles where Rage Powder stands: after step 1 of g30_rage_powder_pivot (the request for the
 * U-turn's switch, inside the turn), on side 0 position 0 (Sinistcha). */
static uint32_t rage_powder_at(const char *battle, uint32_t step, uint32_t side, uint32_t pos)
{
    return strcmp(battle, "g30_rage_powder_pivot") == 0 && step == 1u && side == 0u && pos == 0u
               ? DUOFORGE_POSITION_EXT_RAGE_POWDER
               : 0u;
}

static void check_facts(df_test *t)
{
    /* the numbers */
    DF_CHECK_EQ_U64(t, DFI_SITE_FLAME_BODY, 18u);
    DF_CHECK_EQ_U64(t, DFI_SITE_STATIC, 19u); /* step G39: Static's draw; the count was 19 until then */
    DF_CHECK_EQ_U64(t, DFI_SITE_COUNT, 21u); /* step G46: DFI_SITE_DRAG */
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
     * refused off sun (dfi_mega_sol_refused, tests/test_pool_g59.c), so the Utility Umbrella and Power Herb claims above stand. */
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
    df_test_begin(&t, "duoforge.state.pool_g30");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    uint32_t compared = 0u;
    uint32_t rage_seen = 0u;
    (void)conf_events;
    check_facts(&t);
    for (size_t n = 0u; n < sizeof names / sizeof names[0]; ++n) {
        const df_conf_battle *cb = find(names[n]);
        if (!DF_CHECK(&t, cb != NULL)) {
            fprintf(stderr, "  %s: not in the conformance data\n", names[n]);
            continue;
        }
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        duoforge_battle *b = NULL;
        const duoforge_status created = duoforge_battle_create(ctx, &setup, &b);
        if (!DF_CHECK(&t, created == DUOFORGE_OK && b != NULL)) {
            fprintf(stderr, "  %s: the setup is rejected: %s\n", names[n], duoforge_status_name(created));
            continue;
        }
        for (uint32_t si = 0u; si < cb->step_count; ++si) {
            const df_conf_step *st = &cb->steps[si];
            duoforge_decision_bundle bd;
            bundle_of(st, b, &bd);
            duoforge_step_result res;
            uint32_t used = 0u;
            if (!DF_CHECK(&t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                                  DUOFORGE_OK)) {
                fprintf(stderr, "  %s step %u: the step fails\n", names[n], si);
                break;
            }
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation ob;
                duoforge_observation_ext ext;
                memset(&ob, 0, sizeof ob);
                memset(&ext, 0, sizeof ext);
                if (!DF_CHECK(&t, duoforge_battle_observe_ext(ctx, b, viewer, &ext) == DUOFORGE_OK &&
                                      duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK)) {
                    continue;
                }
                for (uint32_t s = 0u; s < 2u; ++s) {
                    for (uint32_t p = 0u; p < 2u; ++p) {
                        const uint32_t want = rage_powder_at(names[n], si, s, p);
                        if (!DF_CHECK_EQ_U64(&t, ext.sides[s].positions[p].volatiles, want)) {
                            fprintf(stderr, "  %s step %u viewer %u side %u position %u: volatiles %08x, want %08x\n",
                                    names[n], si, viewer, s, p, (unsigned)ext.sides[s].positions[p].volatiles,
                                    (unsigned)want);
                        }
                        rage_seen += (ext.sides[s].positions[p].volatiles & DUOFORGE_POSITION_EXT_RAGE_POWDER) != 0u ? 1u : 0u;
                        DF_CHECK_EQ_U64(&t, ob.sides[s].positions[p].reserved & DUOFORGE_POSITION_FLAG_FOLLOW_ME, 0u);
                    }
                }
                compared += 1u;
            }
        }
        duoforge_battle_destroy(b);
    }
    /* The bit was seen at the one boundary of each viewer, and every comparison ran. */
    DF_CHECK_EQ_U64(&t, rage_seen, 2u);
    DF_CHECK(&t, compared != 0u);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
