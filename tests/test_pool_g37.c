/*
 * duoforge.state.pool_g37 (white-box): step G37 of the content expansion, the entry hazards (Stealth Rock, Spikes, Toxic Spikes,
 * Sticky Web), in the POOL state tail (decision 0015 section 7: stealth_rock, spikes, toxic_spikes and sticky_web of each side, rev 3
 * as it is) and in the POOL view extension (decision 0018: the four fields of the side, supported bits 13, 30, 8 and 33).
 *
 * The recorded battles (g37_* under "data": "pool") are replayed through the step with the reference's draws, as in
 * duoforge.reference.conformance_pool_data, which compares everything that the reference shows (the lines of the moves that set
 * the hazards and of those that fail, the damage, the status and the stat drop of every switch-in, Toxic Spikes absorbed, Toxic
 * Debris). Here is what the reference does not show, after every step:
 *
 *   - the tail's layers of each side are the ones that the reference's own state holds (the harness records the hazards of a side,
 *     with their layers, in creation order, in every step: the rows below are derived from the committed traces by
 *     tools/reference/test_trace_to_c.py, which requires the table to be exactly that, and the engine's fixed order of the hazards of
 *     a side is the creation order in every recorded battle);
 *   - the POOL view extension of both viewers, byte for byte: revision, viewer, epoch, the supported bits of the build and the four
 *     fields of each side equal to the row, nothing else (public, the same for both viewers);
 *   - the bits of the four features are set in the build's mask, and the state passes the invariants.
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

/* The hazards of each side after each step: stealth_rock, spikes, toxic_spikes and sticky_web of side 0, then of side 1, then the creation order (hazard_order) of side 0 and of side 1. */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t layers[10];
} hazard_rows[] = {
    {"g37_hazards_a", 0u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}},
    {"g37_hazards_a", 1u, {0u, 0u, 0u, 0u, 1u, 0u, 0u, 0u, 0u, 0u}},
    {"g37_hazards_a", 2u, {0u, 0u, 0u, 0u, 1u, 1u, 0u, 0u, 0u, 4u}},
    {"g37_hazards_a", 3u, {0u, 0u, 0u, 0u, 1u, 2u, 1u, 0u, 0u, 36u}},
    {"g37_hazards_a", 4u, {0u, 0u, 0u, 0u, 1u, 3u, 2u, 0u, 0u, 36u}},
    {"g37_hazards_a", 5u, {0u, 0u, 0u, 0u, 1u, 3u, 2u, 1u, 0u, 228u}},
    {"g37_hazards_a", 6u, {0u, 0u, 0u, 0u, 1u, 3u, 2u, 1u, 0u, 228u}},
    {"g37_hazards_a", 7u, {0u, 0u, 0u, 0u, 1u, 3u, 2u, 1u, 0u, 228u}},
    {"g37_hazards_a", 8u, {0u, 0u, 0u, 0u, 1u, 3u, 2u, 1u, 0u, 228u}},
    {"g37_hazards_a", 9u, {0u, 0u, 0u, 0u, 1u, 3u, 2u, 1u, 0u, 228u}},
    {"g37_order_a", 0u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}},
    {"g37_order_a", 1u, {0u, 0u, 0u, 0u, 0u, 1u, 0u, 0u, 0u, 1u}},
    {"g37_order_a", 2u, {0u, 0u, 0u, 0u, 1u, 1u, 0u, 0u, 0u, 1u}},
    {"g37_order_a", 3u, {0u, 0u, 0u, 0u, 1u, 1u, 1u, 0u, 0u, 33u}},
    {"g37_order_a", 4u, {0u, 0u, 0u, 0u, 1u, 1u, 2u, 0u, 0u, 33u}},
    {"g37_order_a", 5u, {0u, 0u, 0u, 0u, 1u, 1u, 2u, 1u, 0u, 225u}},
    {"g37_order_a", 6u, {0u, 0u, 0u, 0u, 1u, 1u, 2u, 1u, 0u, 225u}},
    {"g37_order_a", 7u, {0u, 0u, 0u, 0u, 1u, 1u, 2u, 1u, 0u, 225u}},
    {"g37_order_a", 8u, {0u, 0u, 0u, 0u, 1u, 1u, 2u, 1u, 0u, 225u}},
    {"g37_order_b", 0u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}},
    {"g37_order_b", 1u, {0u, 0u, 0u, 0u, 0u, 0u, 2u, 0u, 0u, 2u}},
    {"g37_order_b", 2u, {0u, 0u, 0u, 0u, 1u, 0u, 2u, 0u, 0u, 2u}},
    {"g37_order_b", 3u, {0u, 0u, 0u, 0u, 1u, 1u, 2u, 0u, 0u, 18u}},
    {"g37_order_b", 4u, {0u, 0u, 0u, 0u, 1u, 1u, 2u, 0u, 0u, 18u}},
    {"g37_order_b", 5u, {0u, 0u, 0u, 0u, 1u, 1u, 0u, 0u, 0u, 4u}},
    {"g37_order_b", 6u, {0u, 0u, 0u, 0u, 1u, 1u, 1u, 0u, 0u, 36u}},
    {"g37_order_b", 7u, {0u, 0u, 0u, 0u, 1u, 1u, 1u, 0u, 0u, 36u}},
    {"g37_order_b", 8u, {0u, 0u, 0u, 0u, 1u, 1u, 1u, 0u, 0u, 36u}},
    {"g37_order_b", 9u, {0u, 0u, 0u, 0u, 1u, 1u, 1u, 0u, 0u, 36u}},
    {"g37_order_b", 10u, {0u, 0u, 0u, 0u, 1u, 1u, 1u, 1u, 0u, 228u}},
    {"g37_sticky_web", 0u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}},
    {"g37_sticky_web", 1u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 1u, 0u, 3u}},
    {"g37_sticky_web", 2u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 1u, 0u, 3u}},
    {"g37_sticky_web", 3u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 1u, 0u, 3u}},
    {"g37_sticky_web", 4u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 1u, 0u, 3u}},
    {"g37_sticky_web", 5u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 1u, 0u, 3u}},
    {"g37_sticky_web", 6u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 1u, 0u, 3u}},
    {"g37_sticky_web", 7u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 1u, 0u, 3u}},
    {"g37_toxic_debris", 0u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}},
    {"g37_toxic_debris", 1u, {1u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}},
    {"g37_toxic_debris", 2u, {1u, 0u, 1u, 0u, 0u, 0u, 0u, 0u, 8u, 0u}},
    {"g37_toxic_debris", 3u, {1u, 0u, 2u, 0u, 0u, 0u, 0u, 0u, 8u, 0u}},
    {"g37_toxic_debris", 4u, {1u, 0u, 2u, 0u, 0u, 0u, 0u, 0u, 8u, 0u}},
    {"g37_toxic_debris", 5u, {1u, 0u, 2u, 0u, 0u, 0u, 0u, 0u, 8u, 0u}},
    {"g37_toxic_debris", 6u, {1u, 0u, 2u, 0u, 0u, 0u, 0u, 0u, 8u, 0u}},
    {"g37_toxic_debris", 7u, {1u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}},
    {"g37_toxic_debris", 8u, {1u, 0u, 1u, 0u, 0u, 0u, 0u, 0u, 8u, 0u}},
    {"g37_toxic_debris", 9u, {1u, 0u, 2u, 0u, 0u, 0u, 0u, 0u, 8u, 0u}},
    {"g37_toxic_spikes", 0u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}},
    {"g37_toxic_spikes", 1u, {0u, 0u, 0u, 0u, 0u, 0u, 2u, 0u, 0u, 2u}},
    {"g37_toxic_spikes", 2u, {0u, 0u, 0u, 0u, 0u, 0u, 2u, 0u, 0u, 2u}},
    {"g37_toxic_spikes", 3u, {0u, 0u, 0u, 0u, 0u, 0u, 2u, 0u, 0u, 2u}},
    {"g37_toxic_spikes", 4u, {0u, 0u, 0u, 0u, 0u, 0u, 2u, 0u, 0u, 2u}},
    {"g37_toxic_spikes", 5u, {0u, 0u, 0u, 0u, 0u, 0u, 2u, 0u, 0u, 2u}},
    {"g37_toxic_spikes", 6u, {0u, 0u, 0u, 0u, 0u, 0u, 2u, 0u, 0u, 2u}},
    {"g37_toxic_spikes", 7u, {0u, 0u, 0u, 0u, 0u, 0u, 2u, 0u, 0u, 2u}},
    {"g37_toxic_spikes", 8u, {0u, 0u, 0u, 0u, 0u, 0u, 2u, 0u, 0u, 2u}},
    {"g37_toxic_spikes", 9u, {0u, 0u, 0u, 0u, 0u, 0u, 2u, 0u, 0u, 2u}},
};

static const char *const names[] = {"g37_hazards_a", "g37_order_a", "g37_order_b", "g37_sticky_web", "g37_toxic_debris", "g37_toxic_spikes"};

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g37");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    uint32_t compared = 0u;
    uint32_t kinds_seen[4] = {0u, 0u, 0u, 0u};
    (void)conf_events;
    DF_CHECK_EQ_U64(&t, DUOFORGE_SIDE_STEALTH_ROCK, 5u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_SIDE_SPIKES, 6u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_SIDE_TOXIC_SPIKES, 7u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_SIDE_STICKY_WEB, 8u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_STEALTH_ROCK, 13u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_SPIKES, 30u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_TOXIC_SPIKES, 8u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_STICKY_WEB, 33u);
    DF_CHECK(&t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_STEALTH_ROCK)) != 0u &&
                       (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_SPIKES)) != 0u &&
                       (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_TOXIC_SPIKES)) != 0u &&
                       (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_STICKY_WEB)) != 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_STEALTHROCK] != 0u && dfi_support.moves[DFI_MOVE_SPIKES] != 0u &&
                     dfi_support.moves[DFI_MOVE_TOXICSPIKES] != 0u && dfi_support.moves[DFI_MOVE_STICKYWEB] != 0u &&
                     dfi_support.abilities[DFI_ABILITY_TOXICDEBRIS] != 0u);
    for (size_t n = 0u; n < sizeof names / sizeof names[0]; ++n) {
        const df_conf_battle *cb = find(names[n]);
        if (!DF_CHECK(&t, cb != NULL)) {
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
                break;
            }
            uint32_t want[10] = {0xFFu, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u};
            for (size_t r = 0u; r < sizeof hazard_rows / sizeof hazard_rows[0]; ++r) {
                if (strcmp(hazard_rows[r].battle, names[n]) == 0 && hazard_rows[r].step == si) {
                    for (uint32_t k = 0u; k < 10u; ++k) {
                        want[k] = hazard_rows[r].layers[k];
                    }
                }
            }
            if (!DF_CHECK(&t, want[0] != 0xFFu)) {
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
                continue;
            }
            for (uint32_t s = 0u; s < 2u; ++s) {
                DF_CHECK_EQ_U64(&t, b->tail.sides[s].stealth_rock, want[s * 4u + 0u]);
                DF_CHECK_EQ_U64(&t, b->tail.sides[s].spikes, want[s * 4u + 1u]);
                DF_CHECK_EQ_U64(&t, b->tail.sides[s].toxic_spikes, want[s * 4u + 2u]);
                DF_CHECK_EQ_U64(&t, b->tail.sides[s].sticky_web, want[s * 4u + 3u]);
                DF_CHECK_EQ_U64(&t, b->tail.sides[s].hazard_order, want[8u + s]); /* the reference's creation order */
                for (uint32_t k = 0u; k < 4u; ++k) {
                    kinds_seen[k] += want[s * 4u + k] != 0u ? 1u : 0u;
                }
            }
            DF_CHECK(&t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
            duoforge_observation_ext ext[2];
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation ob;
                memset(&ob, 0, sizeof ob);
                DF_CHECK(&t, duoforge_battle_observe_ext(ctx, b, viewer, &ext[viewer]) == DUOFORGE_OK &&
                                 duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK);
                duoforge_observation_ext w;
                memset(&w, 0, sizeof w);
                w.revision = (uint8_t)DUOFORGE_OBSERVATION_EXT_REVISION;
                w.player = (uint8_t)viewer;
                w.epoch = ob.epoch;
                /* The mask is the build's (later steps add their bits); this step's bits are checked above. */
                w.supported = dfi_support.view_ext_features;
                for (uint32_t s = 0u; s < 2u; ++s) {
                    w.sides[s].stealth_rock = (uint8_t)want[s * 4u + 0u];
                    w.sides[s].spikes = (uint8_t)want[s * 4u + 1u];
                    w.sides[s].toxic_spikes = (uint8_t)want[s * 4u + 2u];
                    w.sides[s].sticky_web = (uint8_t)want[s * 4u + 3u];
                }
                if (!DF_CHECK(&t, memcmp(&ext[viewer], &w, sizeof w) == 0)) {
                    fprintf(stderr, "  %s step %u viewer %u: the extension differs from the reference's state\n", names[n], si,
                            viewer);
                }
                compared += 1u;
            }
            DF_CHECK(&t, memcmp(ext[0].sides, ext[1].sides, sizeof ext[0].sides) == 0);
        }
        duoforge_battle_destroy(b);
    }
    DF_CHECK_EQ_U64(&t, compared, 2u * (uint32_t)(sizeof hazard_rows / sizeof hazard_rows[0]));
    /* Every hazard is up in some recorded step, and the rows are not all empty. */
    for (uint32_t k = 0u; k < 4u; ++k) {
        DF_CHECK(&t, kinds_seen[k] != 0u);
    }
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
