/*
 * duoforge.state.pool_g20 (white-box): step G20 of the content expansion, Aurora Veil, in the POOL state tail
 * (decision 0015 section 7, aurora_veil_turns of each side) and in the POOL view extension (decision 0018).
 *
 * The recorded battles (g20_aurora_veil_* under "data": "pool") are replayed through the step with the reference's draws,
 * as in duoforge.reference.conformance_pool_data, which compares everything that the reference shows (the failed Aurora
 * Veil outside snow and while it is up, the -sidestart and -sideend lines, the damage of every hit under the screen, the
 * order of the two end lines of two screens that end together). Here is what the reference does not show, after every
 * step:
 *
 *   - the tail's aurora_veil_turns of each side is what the protocol lines say alone (the -sidestart line of Aurora Veil
 *     sets 5, or 8 when the user holds Light Clay: the sheet; each |upkeep| line counts it down; the -sideend line ends
 *     it: tools/reference/test_trace_to_c.py derives the rows of the table below from the committed traces and requires
 *     the table to be exactly that);
 *   - the POOL view extension of both viewers, byte for byte: revision, viewer, epoch, the supported bits of the build
 *     and aurora_veil_turns of each side equal to the row, nothing else (the count is public, it is the same for both
 *     viewers);
 *   - the bit of the feature is set in the build's mask (decision 0018: a feature's step sets its bit with its recorded
 *     battles).
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

/* The turns left of Aurora Veil on each side after each step of the recorded battles. */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t turns[2];
} veil_rows[] = {
    {"g20_aurora_veil_a", 0u, {0u, 0u}},
    {"g20_aurora_veil_a", 1u, {0u, 0u}},
    {"g20_aurora_veil_a", 2u, {4u, 0u}},
    {"g20_aurora_veil_a", 3u, {3u, 0u}},
    {"g20_aurora_veil_a", 4u, {2u, 0u}},
    {"g20_aurora_veil_a", 5u, {1u, 0u}},
    {"g20_aurora_veil_a", 6u, {1u, 0u}},
    {"g20_aurora_veil_a", 7u, {0u, 0u}},
    {"g20_aurora_veil_clay", 0u, {0u, 0u}},
    {"g20_aurora_veil_clay", 1u, {7u, 0u}},
    {"g20_aurora_veil_clay", 2u, {6u, 0u}},
    {"g20_aurora_veil_clay", 3u, {5u, 0u}},
    {"g20_aurora_veil_clay", 4u, {4u, 0u}},
    {"g20_aurora_veil_clay", 5u, {3u, 0u}},
    {"g20_aurora_veil_clay", 6u, {2u, 0u}},
    {"g20_aurora_veil_clay", 7u, {2u, 0u}},
    {"g20_aurora_veil_clay", 8u, {1u, 0u}},
    {"g20_aurora_veil_clay", 9u, {0u, 0u}},
    {"g20_aurora_veil_fail", 0u, {0u, 0u}},
    {"g20_aurora_veil_fail", 1u, {0u, 0u}},
    {"g20_aurora_veil_fail", 2u, {0u, 0u}},
    {"g20_aurora_veil_fail", 3u, {4u, 0u}},
    {"g20_aurora_veil_fail", 4u, {3u, 0u}},
    {"g20_aurora_veil_fail", 5u, {2u, 0u}},
    {"g20_aurora_veil_screens", 0u, {0u, 0u}},
    {"g20_aurora_veil_screens", 1u, {0u, 0u}},
    {"g20_aurora_veil_screens", 2u, {4u, 0u}},
    {"g20_aurora_veil_screens", 3u, {3u, 0u}},
    {"g20_aurora_veil_screens", 4u, {2u, 0u}},
    {"g20_aurora_veil_screens", 5u, {1u, 0u}},
    {"g20_aurora_veil_screens", 6u, {0u, 0u}},
    {"g20_aurora_veil_pair_a", 0u, {0u, 0u}},
    {"g20_aurora_veil_pair_a", 1u, {4u, 4u}},
    {"g20_aurora_veil_pair_a", 2u, {3u, 3u}},
    {"g20_aurora_veil_pair_a", 3u, {2u, 2u}},
    {"g20_aurora_veil_pair_a", 4u, {1u, 1u}},
    {"g20_aurora_veil_pair_a", 5u, {0u, 0u}},
    {"g20_aurora_veil_pair_a", 6u, {0u, 0u}},
    {"g20_aurora_veil_pair_a", 7u, {0u, 0u}},
    {"g20_aurora_veil_pair_b", 0u, {0u, 0u}},
    {"g20_aurora_veil_pair_b", 1u, {4u, 4u}},
    {"g20_aurora_veil_pair_b", 2u, {3u, 3u}},
    {"g20_aurora_veil_pair_b", 3u, {2u, 2u}},
    {"g20_aurora_veil_pair_b", 4u, {1u, 1u}},
    {"g20_aurora_veil_pair_b", 5u, {0u, 0u}},
    {"g20_aurora_veil_pair_b", 6u, {0u, 0u}},
    {"g20_aurora_veil_pair_b", 7u, {0u, 0u}},
};

static const char *const names[] = {"g20_aurora_veil_a", "g20_aurora_veil_clay", "g20_aurora_veil_fail", "g20_aurora_veil_screens", "g20_aurora_veil_pair_a", "g20_aurora_veil_pair_b"};

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g20");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    uint32_t compared = 0u;
    uint32_t live = 0u;
    uint32_t clay = 0u;
    uint32_t both = 0u;
    (void)conf_events;
    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_AURORA_VEIL, 3u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_SIDE_AURORA_VEIL, 4u);
    DF_CHECK(&t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_AURORA_VEIL)) != 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_AURORAVEIL] != 0u);
    DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_AURORAVEIL].special, DFI_SPECIAL_AURORA_VEIL);
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
            uint32_t turns[2] = {0xFFu, 0xFFu};
            for (size_t r = 0u; r < sizeof veil_rows / sizeof veil_rows[0]; ++r) {
                if (strcmp(veil_rows[r].battle, names[n]) == 0 && veil_rows[r].step == si) {
                    turns[0] = veil_rows[r].turns[0];
                    turns[1] = veil_rows[r].turns[1];
                }
            }
            if (!DF_CHECK(&t, turns[0] != 0xFFu)) {
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
                continue;
            }
            DF_CHECK_EQ_U64(&t, b->tail.sides[0].aurora_veil_turns, turns[0]);
            DF_CHECK_EQ_U64(&t, b->tail.sides[1].aurora_veil_turns, turns[1]);
            live += (turns[0] != 0u || turns[1] != 0u) ? 1u : 0u;
            clay += (turns[0] > 5u || turns[1] > 5u) ? 1u : 0u;
            both += (turns[0] != 0u && turns[1] != 0u) ? 1u : 0u;
            duoforge_observation_ext ext[2];
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation ob;
                memset(&ob, 0, sizeof ob);
                DF_CHECK(&t, duoforge_battle_observe_ext(ctx, b, viewer, &ext[viewer]) == DUOFORGE_OK &&
                                 duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK);
                duoforge_observation_ext want;
                memset(&want, 0, sizeof want);
                want.revision = (uint8_t)DUOFORGE_OBSERVATION_EXT_REVISION;
                want.player = (uint8_t)viewer;
                want.epoch = ob.epoch;
                /* The mask is the build's (later steps add their bits); this step's bit is checked above. */
                want.supported = dfi_support.view_ext_features;
                for (uint32_t s = 0u; s < 2u; ++s) {
                    want.sides[s].aurora_veil_turns = (uint8_t)turns[s];
                }
                if (!DF_CHECK(&t, memcmp(&ext[viewer], &want, sizeof want) == 0)) {
                    fprintf(stderr, "  %s step %u viewer %u: the extension differs from the protocol's (want %u and %u)\n",
                            names[n], si, viewer, turns[0], turns[1]);
                }
                compared += 1u;
            }
            DF_CHECK(&t, memcmp(ext[0].sides, ext[1].sides, sizeof ext[0].sides) == 0);
        }
        duoforge_battle_destroy(b);
    }
    DF_CHECK_EQ_U64(&t, compared, 2u * (uint32_t)(sizeof veil_rows / sizeof veil_rows[0]));
    /* The battles show the screen up, with Light Clay's eight turns, and on both sides at once. */
    DF_CHECK(&t, live != 0u && clay != 0u && both != 0u);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
