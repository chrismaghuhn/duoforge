/*
 * duoforge.state.pool_g31 (white-box): step G31 of the content expansion, Taunt and Yawn, in the POOL state tail
 * (decision 0015 section 7: taunt_turns and yawn_turns of a position, rev 2 and 3 as they are) and in the POOL view extension
 * (decision 0018: the position's volatiles bits TAUNT and YAWN, supported bits 14 and 25).
 *
 * The recorded battles (g31_* under "data": "pool") are replayed through the step with the reference's draws, as in
 * duoforge.reference.conformance_pool_data, which compares everything that the reference shows (the start, cant and end lines,
 * the requests that leave the Status moves out or offer Struggle, the sleep that Yawn brings and its draw, the order of two ends
 * that come together). Here is what the reference does not show, after every step:
 *
 *   - the tail's taunt_turns and yawn_turns of each position are zero exactly where the protocol lines say there is no such
 *     volatile (`-start|X|move: Taunt` until `-end`, `-start|X|move: Yawn` until the `-status|X|slp` it brings, a switch-out or
 *     a faint clears both: tools/reference/test_trace_to_c.py derives the rows below from the committed traces), and within
 *     their bounds (Taunt 1 to 4, Yawn 1 to 2);
 *   - the POOL view extension of both viewers, byte for byte: the revision, the viewer, the epoch, the supported bits of the
 *     build, the TAUNT and YAWN presence bits of each position, nothing else (the turns are never shown);
 *   - the bits of the feature are set in the build's mask.
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

/* Bit 0: Taunt, bit 1: Yawn, of each position (side * 2 + slot) after each step of the recorded battles. */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t bits[4];
} rows[] = {
    {"g31_taunt_a", 0u, {0u, 0u, 0u, 0u}},
    {"g31_taunt_a", 1u, {0u, 0u, 1u, 0u}},
    {"g31_taunt_a", 2u, {0u, 0u, 1u, 1u}},
    {"g31_taunt_a", 3u, {0u, 0u, 1u, 1u}},
    {"g31_taunt_a", 4u, {0u, 0u, 0u, 0u}},
    {"g31_taunt_a", 5u, {0u, 0u, 0u, 0u}},
    {"g31_taunt_a", 6u, {0u, 0u, 0u, 0u}},
    {"g31_taunt_a", 7u, {0u, 0u, 0u, 0u}},
    {"g31_taunt_switch", 0u, {0u, 0u, 0u, 0u}},
    {"g31_taunt_switch", 1u, {0u, 0u, 1u, 0u}},
    {"g31_taunt_switch", 2u, {0u, 0u, 1u, 0u}},
    {"g31_taunt_switch", 3u, {0u, 0u, 1u, 0u}},
    {"g31_taunt_switch", 4u, {0u, 0u, 1u, 0u}},
    {"g31_taunt_switch", 5u, {0u, 0u, 0u, 0u}},
    {"g31_taunt_switch", 6u, {0u, 0u, 0u, 0u}},
    {"g31_taunt_tie_a", 0u, {0u, 0u, 0u, 0u}},
    {"g31_taunt_tie_a", 1u, {0u, 0u, 1u, 1u}},
    {"g31_taunt_tie_a", 2u, {0u, 0u, 1u, 1u}},
    {"g31_taunt_tie_a", 3u, {0u, 0u, 1u, 1u}},
    {"g31_taunt_tie_a", 4u, {0u, 0u, 0u, 0u}},
    {"g31_taunt_tie_a", 5u, {0u, 0u, 0u, 0u}},
    {"g31_taunt_tie_a", 6u, {0u, 0u, 0u, 0u}},
    {"g31_taunt_tie_b", 0u, {0u, 0u, 0u, 0u}},
    {"g31_taunt_tie_b", 1u, {0u, 0u, 1u, 1u}},
    {"g31_taunt_tie_b", 2u, {0u, 0u, 1u, 1u}},
    {"g31_taunt_tie_b", 3u, {0u, 0u, 1u, 1u}},
    {"g31_taunt_tie_b", 4u, {0u, 0u, 0u, 0u}},
    {"g31_taunt_tie_b", 5u, {0u, 0u, 0u, 0u}},
    {"g31_taunt_tie_b", 6u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_a", 0u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_a", 1u, {0u, 0u, 2u, 0u}},
    {"g31_yawn_a", 2u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_a", 3u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_a", 4u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_a", 5u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_a", 6u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_flower_veil", 0u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_flower_veil", 1u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_flower_veil", 2u, {0u, 0u, 2u, 0u}},
    {"g31_yawn_flower_veil", 3u, {0u, 0u, 2u, 0u}},
    {"g31_yawn_flower_veil", 4u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_flower_veil", 5u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_switch", 0u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_switch", 1u, {0u, 0u, 2u, 0u}},
    {"g31_yawn_switch", 2u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_switch", 3u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_switch", 4u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_switch", 5u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_tie_a", 0u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_tie_a", 1u, {0u, 0u, 2u, 2u}},
    {"g31_yawn_tie_a", 2u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_tie_a", 3u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_tie_a", 4u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_tie_a", 5u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_tie_b", 0u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_tie_b", 1u, {0u, 0u, 2u, 2u}},
    {"g31_yawn_tie_b", 2u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_tie_b", 3u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_tie_b", 4u, {0u, 0u, 0u, 0u}},
    {"g31_yawn_tie_b", 5u, {0u, 0u, 0u, 0u}},
};

static const char *const names[] = {"g31_taunt_a", "g31_taunt_switch", "g31_taunt_tie_a", "g31_taunt_tie_b", "g31_yawn_a", "g31_yawn_flower_veil", "g31_yawn_switch", "g31_yawn_tie_a", "g31_yawn_tie_b"};

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g31");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    uint32_t compared = 0u;
    uint32_t taunts = 0u;
    uint32_t yawns = 0u;
    (void)conf_events;
    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_TAUNT, 14u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_YAWN, 25u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VOLATILE_TAUNT, 6u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VOLATILE_YAWN, 7u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_CAUSE_TAUNT, 20u);
    DF_CHECK(&t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_TAUNT)) != 0u);
    DF_CHECK(&t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_YAWN)) != 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_TAUNT] != 0u && dfi_support.moves[DFI_MOVE_YAWN] != 0u);
    DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_TAUNT].special, DFI_SPECIAL_TAUNT);
    DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_YAWN].special, DFI_SPECIAL_YAWN);
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
            uint32_t want[4] = {0xFFu, 0xFFu, 0xFFu, 0xFFu};
            for (size_t r = 0u; r < sizeof rows / sizeof rows[0]; ++r) {
                if (strcmp(rows[r].battle, names[n]) == 0 && rows[r].step == si) {
                    for (uint32_t k = 0u; k < 4u; ++k) {
                        want[k] = rows[r].bits[k];
                    }
                }
            }
            if (!DF_CHECK(&t, want[0] != 0xFFu)) {
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
                continue;
            }
            for (uint32_t flat = 0u; flat < 4u; ++flat) {
                const dfi_tail_pos *tp = &b->tail.sides[flat / 2u].positions[flat % 2u];
                DF_CHECK_EQ_U64(&t, tp->taunt_turns != 0u ? 1u : 0u, want[flat] & 1u);
                DF_CHECK_EQ_U64(&t, tp->yawn_turns != 0u ? 1u : 0u, (want[flat] >> 1u) & 1u);
                DF_CHECK(&t, tp->taunt_turns <= 4u && tp->yawn_turns <= 2u);
                taunts += tp->taunt_turns != 0u ? 1u : 0u;
                yawns += tp->yawn_turns != 0u ? 1u : 0u;
            }
            duoforge_observation_ext ext[2];
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation ob;
                memset(&ob, 0, sizeof ob);
                DF_CHECK(&t, duoforge_battle_observe_ext(ctx, b, viewer, &ext[viewer]) == DUOFORGE_OK &&
                                 duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK);
                duoforge_observation_ext exp;
                memset(&exp, 0, sizeof exp);
                exp.revision = (uint8_t)DUOFORGE_OBSERVATION_EXT_REVISION;
                exp.player = (uint8_t)viewer;
                exp.epoch = ob.epoch;
                exp.supported = dfi_support.view_ext_features;
                for (uint32_t flat = 0u; flat < 4u; ++flat) {
                    const dfi_tail_pos *tp = &b->tail.sides[flat / 2u].positions[flat % 2u];
                    exp.sides[flat / 2u].positions[flat % 2u].volatiles =
                        ((want[flat] & 1u) != 0u ? (uint32_t)DUOFORGE_POSITION_EXT_TAUNT : 0u) |
                        ((want[flat] & 2u) != 0u ? (uint32_t)DUOFORGE_POSITION_EXT_YAWN : 0u) |
                        (tp->heal_block_turns != 0u ? (uint32_t)DUOFORGE_POSITION_EXT_HEAL_BLOCK : 0u);
                    exp.sides[flat / 2u].positions[flat % 2u].encore_slot = tp->encore_slot;
                }
                if (!DF_CHECK(&t, memcmp(&ext[viewer], &exp, sizeof exp) == 0)) {
                    fprintf(stderr, "  %s step %u viewer %u: the extension differs from the protocol's\n", names[n], si,
                            viewer);
                }
                compared += 1u;
            }
            DF_CHECK(&t, memcmp(ext[0].sides, ext[1].sides, sizeof ext[0].sides) == 0);
        }
        duoforge_battle_destroy(b);
    }
    DF_CHECK_EQ_U64(&t, compared, 2u * (uint32_t)(sizeof rows / sizeof rows[0]));
    DF_CHECK(&t, taunts != 0u && yawns != 0u);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
