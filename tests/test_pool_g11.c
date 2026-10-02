/*
 * duoforge.state.pool_g11 (white-box): step G11 of the content expansion, Soak, in the POOL state tail (the soak type
 * of the occupant, decision 0015 section 7), in what reads the types, in the event and in the view extension
 * (decision 0018: type_now and TYPE_CHANGED, bit 9).
 *
 * The recorded battles g11_soak, g11_soak_mega, g11_soak_stab and g11_soak_electro (under "data": "pool") are replayed
 * through the step with the reference's draws, as in duoforge.reference.conformance_pool_data, which compares every
 * HP, stage, request and event the reference shows (the damage lines carry what reads the types: the -supereffective,
 * -resisted and -immune lines, the STAB through the HP that is left, the Grassy Terrain heal of a Pokemon that is
 * grounded since Soak). Here the state that the reference does not show is read after every step: the tail's soak
 * type of every roster member, and both viewers' whole extension.
 *
 * What the battles show (the pin: data/moves.ts:17186-17208 soak, sim/pokemon.ts:1392 setSpecies, :1508-1560
 * clearVolatile):
 *   g11_soak          Soak makes Pelipper Water (the type is shown, Thunderbolt is two times over instead of four,
 *                     a second Soak is -fail with the target as its argument, Grassy Terrain heals it: it is grounded
 *                     now); Soak on Rillaboom; Pelipper switches out and comes back as Water/Flying (Thunderbolt is
 *                     four times over again); a Soak that a Protect stops; a Soak on Ceruledge.
 *   g11_soak_mega     Soak on Salamence (Ice Beam is resisted), its Mega Evolution ends the type (Ice Beam is four
 *                     times over: setSpecies), a Soak after the Mega Evolution takes (resisted again), and the faint
 *                     of the Soaked Mega Salamence.
 *   g11_soak_stab     Soak on Milotic, a pure Water Pokemon, is -fail and sets nothing; Ceruledge (Fire/Ghost) is
 *                     immune to Double-Edge until Soak makes it Water; Soak on the ally Basculegion (Water/Ghost,
 *                     Adaptability): its Shadow Ball loses the STAB, Wave Crash keeps it.
 *   g11_soak_electro  Electro Shot in rain: the shot hits Soaked Pelipper two times over (it would be four), and the
 *                     faint ends the type.
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

/* The positions (bit = side * 2 + slot) whose occupant is Soaked after each step of each battle: what the protocol
 * lines say alone (`|-start|X|typechange|Water` sets it; a `|switch|`, `|drag|`, `|replace|`, `|faint|` or `|-mega|` of
 * the position clears it: decision 0018 section 6.1). tools/reference/test_trace_to_c.py derives the rows from the
 * committed traces and requires this table to be exactly that. */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t soaked;
} rows[] = {
    {"g11_soak", 0u, 0x0u},
    {"g11_soak", 1u, 0x4u},
    {"g11_soak", 2u, 0x4u},
    {"g11_soak", 3u, 0x8u},
    {"g11_soak", 4u, 0x8u},
    {"g11_soak", 5u, 0x8u},
    {"g11_soak", 6u, 0x8u},
    {"g11_soak", 7u, 0x8u},
    {"g11_soak", 8u, 0xcu},
    {"g11_soak_mega", 0u, 0x0u},
    {"g11_soak_mega", 1u, 0x4u},
    {"g11_soak_mega", 2u, 0x0u},
    {"g11_soak_mega", 3u, 0x4u},
    {"g11_soak_mega", 4u, 0x0u},
    {"g11_soak_mega", 5u, 0x0u},
    {"g11_soak_stab", 0u, 0x0u},
    {"g11_soak_stab", 1u, 0x0u},
    {"g11_soak_stab", 2u, 0x4u},
    {"g11_soak_stab", 3u, 0x5u},
    {"g11_soak_stab", 4u, 0x5u},
    {"g11_soak_stab", 5u, 0x5u},
    {"g11_soak_electro", 0u, 0x0u},
    {"g11_soak_electro", 1u, 0x0u},
    {"g11_soak_electro", 2u, 0x0u},
    {"g11_soak_electro", 3u, 0x0u},
    {"g11_soak_electro", 4u, 0x0u},
};

#define WATER_PLUS_1 ((uint8_t)(DUOFORGE_TYPE_WATER + 1u))

/* After every step of the four battles: the tail's soak types are exactly the occupants of the rows' positions (and no
 * other roster member has one), and both viewers' extension equals the expected one byte for byte: revision, viewer,
 * epoch, the supported bits, TYPE_CHANGED with type_now = {Water, none} at those positions and nothing else; Soak is
 * public, so the foe sees what the owner sees, and the two sections are the same. */
static void check_battles(df_test *t, const duoforge_context *ctx, uint32_t *compared)
{
    static const char *const names[] = {"g11_soak", "g11_soak_mega", "g11_soak_stab", "g11_soak_electro"};
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
            DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
            uint32_t soaked = 0xFFu;
            for (size_t r = 0u; r < sizeof rows / sizeof rows[0]; ++r) {
                if (strcmp(rows[r].battle, names[n]) == 0 && rows[r].step == si) {
                    soaked = rows[r].soaked;
                }
            }
            if (!DF_CHECK(t, soaked != 0xFFu)) {
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
                continue;
            }
            /* The tail: the soak types by roster member are those of the occupants of the soaked positions. */
            for (uint32_t s = 0u; s < 2u; ++s) {
                for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
                    uint32_t want = 0u;
                    for (uint32_t p = 0u; p < 2u; ++p) {
                        if (b->sides[s].positions[p].occupant == m && ((soaked >> (s * 2u + p)) & 1u) != 0u) {
                            want = DUOFORGE_TYPE_WATER + 1u;
                        }
                    }
                    if (!DF_CHECK_EQ_U64(t, b->tail.sides[s].soak_type[m], want)) {
                        fprintf(stderr, "  %s step %u: side %u member %u\n", names[n], si, s, m);
                    }
                }
            }
            duoforge_observation_ext ext[2];
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation ob;
                memset(&ob, 0, sizeof ob);
                DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, viewer, &ext[viewer]) == DUOFORGE_OK &&
                                duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK);
                duoforge_observation_ext want;
                memset(&want, 0, sizeof want);
                want.revision = (uint8_t)DUOFORGE_OBSERVATION_EXT_REVISION;
                want.player = (uint8_t)viewer;
                want.epoch = ob.epoch;
                /* The mask is the build's (later steps add their bits); the G8 and G11 bits are checked below. */
                want.supported = dfi_support.view_ext_features;
                DF_CHECK(t, (want.supported & (((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_THROAT_CHOP) |
                                               ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_TYPE_CHANGE) |
                                               ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_HEAL_BLOCK))) ==
                                (((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_THROAT_CHOP) |
                                 ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_TYPE_CHANGE) |
                                 ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_HEAL_BLOCK)));
                for (uint32_t flat = 0u; flat < 4u; ++flat) {
                    if (((soaked >> flat) & 1u) != 0u) {
                        want.sides[flat / 2u].positions[flat % 2u].volatiles = (uint32_t)DUOFORGE_POSITION_EXT_TYPE_CHANGED;
                        want.sides[flat / 2u].positions[flat % 2u].type_now[0] = WATER_PLUS_1;
                    }
                }
                if (!DF_CHECK(t, memcmp(&ext[viewer], &want, sizeof want) == 0)) {
                    fprintf(stderr, "  %s step %u viewer %u: the extension differs from the protocol's (Soaked 0x%x)\n",
                            names[n], si, viewer, soaked);
                }
                *compared += 1u;
            }
            DF_CHECK(t, memcmp(ext[0].sides, ext[1].sides, sizeof ext[0].sides) == 0);
        }
        duoforge_battle_destroy(b);
    }
}

/* The event of step 1 of g11_soak, as both players see it: one TYPE_CHANGE at Pelipper (position 2), the new type
 * Water in the detail, cause MOVE and the move Soak in id2 (the -start line has no [from]: the cause is the move that
 * made it). The step runs with the events of the public API's buffers. */
static void check_event(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g11_soak");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return;
    }
    for (uint32_t si = 0u; si < 2u; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        static duoforge_event ev_buf[2][DUOFORGE_MAX_EVENTS];
        duoforge_event_buffer buffers[2] = {{ev_buf[0], DUOFORGE_MAX_EVENTS, 0u}, {ev_buf[1], DUOFORGE_MAX_EVENTS, 0u}};
        if (!DF_CHECK(t, dfi_battle_step_events_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res,
                                                      buffers) == DUOFORGE_OK)) {
            break;
        }
        if (si == 1u) {
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                uint32_t found = 0u;
                for (uint32_t i = 0u; i < buffers[viewer].count; ++i) {
                    const duoforge_event *e = &buffers[viewer].events[i];
                    if (e->kind != (uint8_t)DUOFORGE_EVENT_TYPE_CHANGE) {
                        continue;
                    }
                    found += 1u;
                    DF_CHECK_EQ_U64(t, e->position, 2u);
                    DF_CHECK_EQ_U64(t, e->detail, DUOFORGE_TYPE_WATER);
                    DF_CHECK_EQ_U64(t, e->cause, DUOFORGE_CAUSE_MOVE);
                    DF_CHECK_EQ_U64(t, e->id2, DFI_MOVE_SOAK);
                }
                DF_CHECK_EQ_U64(t, found, 1u); /* the opponent sees the type change as well: it is public */
            }
        }
    }
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g11");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kd = df_make_context(&df_config_pool_dev);

    /* The new public values, as numbers (the owner's OK: DUOFORGE_EVENT_TYPE_CHANGE = 41, detail the type id). */
    DF_CHECK_EQ_U64(&t, DUOFORGE_EVENT_TYPE_CHANGE, 41u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_TYPE_WATER, 17u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_TYPE_CHANGE, 9u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_POSITION_EXT_TYPE_CHANGED, 0x00040000u);
    DF_CHECK_EQ_U64(&t, DFI_TYPE_WATER, DUOFORGE_TYPE_WATER);
    DF_CHECK_EQ_U64(&t, DFI_SPECIAL_SOAK, 20u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_SOAK] != 0u);
    DF_CHECK(&t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_TYPE_CHANGE)) != 0u);

    uint32_t compared = 0u;
    check_battles(&t, kp, &compared);
    /* Two views per step: 26 rows. */
    DF_CHECK_EQ_U64(&t, compared, 2u * (uint32_t)(sizeof rows / sizeof rows[0]));
    check_event(&t, kp);

    /* The same battles under POOL_DEV (its own fingerprint, the same tables): the same tail and view. */
    uint32_t compared_dev = 0u;
    check_battles(&t, kd, &compared_dev);
    DF_CHECK_EQ_U64(&t, compared_dev, compared);

    duoforge_context_destroy(kd);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
