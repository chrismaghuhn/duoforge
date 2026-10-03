/*
 * duoforge.state.pool_g27 (white-box): step G27 of the content expansion, Cursed Body and Disable, in the POOL state tail
 * (decision 0015 section 7: disable_slot and disable_turns of a position, rev 3 as it is) and in the POOL view extension
 * (decision 0018: the position's disable_slot, supported bit 21).
 *
 * The recorded battles (g27_* under "data": "pool") are replayed through the step with the reference's draws, as in
 * duoforge.reference.conformance_pool_data, which compares everything that the reference shows (the Cursed Body rolls, the
 * -start and -end lines of Disable, the cant line of a barred move, the failed Disables, the requests that leave the barred
 * slot out or offer Struggle, the order of two -end lines that come together). Here is what the reference does not show,
 * after every step:
 *
 *   - the tail's disable_slot of each position is what the protocol lines say alone (the -start|X|Disable|MOVE line sets the
 *     slot of MOVE in the member's set, the -end line, a switch-out and a faint clear it: tools/reference/test_trace_to_c.py
 *     derives the rows of the table below from the committed traces and requires the table to be exactly that), and the turns
 *     left are 1 to 5 exactly when a slot is set;
 *   - the POOL view extension of both viewers, byte for byte: revision, viewer, epoch, the supported bits of the build, the
 *     disable_slot of each position equal to the row and the Encore slot that the tail holds, nothing else (the turns are
 *     never shown);
 *   - the bit of the feature is set in the build's mask (decision 0018: a feature's step sets its bit with its recorded
 *     battles).
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

/* The barred move slot (slot + 1, 0 none) of each position (side * 2 + slot) after each step of the recorded battles. */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t slot[4];
} slot_rows[] = {
    {"g27_cursed_body_a", 0u, {0u, 0u, 0u, 0u}},
    {"g27_cursed_body_a", 1u, {0u, 0u, 1u, 1u}},
    {"g27_cursed_body_a", 2u, {0u, 0u, 1u, 1u}},
    {"g27_cursed_body_a", 3u, {0u, 0u, 1u, 1u}},
    {"g27_cursed_body_a", 4u, {0u, 0u, 1u, 1u}},
    {"g27_cursed_body_a", 5u, {0u, 0u, 0u, 0u}},
    {"g27_cursed_body_a", 6u, {0u, 0u, 0u, 0u}},
    {"g27_cursed_body_a", 7u, {0u, 0u, 0u, 0u}},
    {"g27_disable_b", 0u, {0u, 0u, 0u, 0u}},
    {"g27_disable_b", 1u, {0u, 0u, 0u, 0u}},
    {"g27_disable_b", 2u, {0u, 0u, 1u, 1u}},
    {"g27_disable_b", 3u, {0u, 0u, 1u, 1u}},
    {"g27_disable_b", 4u, {0u, 0u, 1u, 1u}},
    {"g27_disable_b", 5u, {0u, 0u, 0u, 1u}},
    {"g27_disable_b", 6u, {0u, 0u, 0u, 0u}},
    {"g27_disable_b", 7u, {0u, 0u, 0u, 0u}},
    {"g27_disable_heal_block", 0u, {0u, 0u, 0u, 0u}},
    {"g27_disable_heal_block", 1u, {0u, 0u, 0u, 0u}},
    {"g27_disable_heal_block", 2u, {0u, 0u, 0u, 1u}},
    {"g27_disable_heal_block", 3u, {0u, 0u, 0u, 1u}},
    {"g27_disable_heal_block", 4u, {0u, 0u, 0u, 1u}},
    {"g27_disable_heal_block", 5u, {0u, 0u, 0u, 0u}},
    {"g27_disable_heal_block", 6u, {0u, 0u, 0u, 0u}},
    {"g27_disable_heal_block", 7u, {0u, 0u, 0u, 0u}},
    {"g27_disable_lock", 0u, {0u, 0u, 0u, 0u}},
    {"g27_disable_lock", 1u, {0u, 0u, 0u, 0u}},
    {"g27_disable_lock", 2u, {0u, 0u, 1u, 0u}},
    {"g27_disable_lock", 3u, {0u, 0u, 1u, 1u}},
    {"g27_disable_lock", 4u, {0u, 0u, 1u, 1u}},
    {"g27_disable_lock", 5u, {0u, 0u, 0u, 1u}},
    {"g27_disable_lock", 6u, {0u, 0u, 0u, 1u}},
    {"g27_disable_lock", 7u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pair_a", 0u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pair_a", 1u, {1u, 0u, 1u, 0u}},
    {"g27_disable_pair_a", 2u, {1u, 0u, 1u, 0u}},
    {"g27_disable_pair_a", 3u, {1u, 0u, 1u, 0u}},
    {"g27_disable_pair_a", 4u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pair_a", 5u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pair_a", 6u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pair_a", 7u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pair_a", 8u, {1u, 0u, 0u, 0u}},
    {"g27_disable_pair_b", 0u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pair_b", 1u, {0u, 0u, 1u, 0u}},
    {"g27_disable_pair_b", 2u, {0u, 0u, 1u, 0u}},
    {"g27_disable_pair_b", 3u, {0u, 0u, 1u, 0u}},
    {"g27_disable_pair_b", 4u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pair_b", 5u, {1u, 0u, 1u, 0u}},
    {"g27_disable_pair_b", 6u, {1u, 0u, 1u, 0u}},
    {"g27_disable_pair_b", 7u, {1u, 0u, 1u, 0u}},
    {"g27_disable_pair_b", 8u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pp", 0u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pp", 1u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pp", 2u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pp", 3u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pp", 4u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pp", 5u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pp", 6u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pp", 7u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pp", 8u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pp", 9u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pp", 10u, {0u, 0u, 0u, 0u}},
    {"g27_disable_pp", 11u, {0u, 0u, 0u, 0u}},
    {"g27_disable_switch", 0u, {0u, 0u, 0u, 0u}},
    {"g27_disable_switch", 1u, {0u, 0u, 0u, 0u}},
    {"g27_disable_switch", 2u, {0u, 0u, 1u, 0u}},
    {"g27_disable_switch", 3u, {0u, 0u, 1u, 0u}},
    {"g27_disable_switch", 4u, {0u, 0u, 0u, 0u}},
    {"g27_disable_switch", 5u, {0u, 0u, 0u, 0u}},
    {"g27_disable_switch", 6u, {0u, 0u, 0u, 0u}},
    {"g27_disable_switch", 7u, {0u, 0u, 0u, 0u}},
};

static const char *const names[] = {"g27_cursed_body_a", "g27_disable_b", "g27_disable_heal_block", "g27_disable_lock", "g27_disable_pair_a", "g27_disable_pair_b", "g27_disable_pp", "g27_disable_switch"};

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g27");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    uint32_t compared = 0u;
    uint32_t live = 0u;
    (void)conf_events;
    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_DISABLE, 21u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VOLATILE_DISABLE, 4u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_CAUSE_DISABLE, 19u);
    DF_CHECK_EQ_U64(&t, DFI_SITE_CURSED_BODY, 17u);
    DF_CHECK(&t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_DISABLE)) != 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_DISABLE] != 0u && dfi_support.abilities[DFI_ABILITY_CURSEDBODY] != 0u);
    DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_DISABLE].special, DFI_SPECIAL_DISABLE);
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
            for (size_t r = 0u; r < sizeof slot_rows / sizeof slot_rows[0]; ++r) {
                if (strcmp(slot_rows[r].battle, names[n]) == 0 && slot_rows[r].step == si) {
                    for (uint32_t k = 0u; k < 4u; ++k) {
                        want[k] = slot_rows[r].slot[k];
                    }
                }
            }
            if (!DF_CHECK(&t, want[0] != 0xFFu)) {
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
                continue;
            }
            uint32_t any = 0u;
            for (uint32_t flat = 0u; flat < 4u; ++flat) {
                const dfi_tail_pos *tp = &b->tail.sides[flat / 2u].positions[flat % 2u];
                DF_CHECK_EQ_U64(&t, tp->disable_slot, want[flat]);
                /* The turns left (4 or 5 when the bar starts, then counted down) exist exactly with the slot. */
                DF_CHECK(&t, (tp->disable_slot == 0u) == (tp->disable_turns == 0u) && tp->disable_turns <= 5u);
                any |= tp->disable_slot;
            }
            live += any != 0u ? 1u : 0u;
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
                    exp.sides[flat / 2u].positions[flat % 2u].disable_slot = (uint8_t)want[flat];
                    /* Encore's slot (step G9, checked by duoforge.state.pool_g9) is in the battle that has both. */
                    exp.sides[flat / 2u].positions[flat % 2u].encore_slot =
                        b->tail.sides[flat / 2u].positions[flat % 2u].encore_slot;
                    /* Heal Block's bit (step G8, checked by duoforge.state.pool_g8) is in the battle that has it end with a Disable. */
                    exp.sides[flat / 2u].positions[flat % 2u].volatiles =
                        b->tail.sides[flat / 2u].positions[flat % 2u].heal_block_turns != 0u
                            ? (uint32_t)DUOFORGE_POSITION_EXT_HEAL_BLOCK
                            : 0u;
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
    DF_CHECK_EQ_U64(&t, compared, 2u * (uint32_t)(sizeof slot_rows / sizeof slot_rows[0]));
    DF_CHECK(&t, live != 0u);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
