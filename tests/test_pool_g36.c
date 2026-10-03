/*
 * duoforge.state.pool_g36 (white-box): step G36 of the content expansion, Toxic and the badly poisoned status, in the POOL
 * state tail (decision 0015 section 7: toxic_stage of a roster member, rev 2 as it is), the member's status
 * DUOFORGE_AILMENT_TOX and the POOL view (decision 0018: the ailment value in the member views, supported bit 10).
 *
 * The recorded battles (g36_* under "data": "pool") are replayed through the step with the reference's draws, as in
 * duoforge.reference.conformance_pool_data, which compares everything that the reference shows (the status lines, the
 * residual damage with its status field, the failures and the immunities). Here is what the reference does not show, after
 * every step:
 *
 *   - the tail's toxic_stage of the occupant of each position is the number of tox damage lines that the protocol shows for it
 *     since its status started or since it last switched in (zero then; capped at 15), and the occupant has the status tox
 *     exactly where the protocol says it has (tools/reference/test_trace_to_c.py derives the rows below from the committed
 *     traces and requires the table to be exactly that);
 *   - the observation of both viewers shows the ailment Tox of that member (the old observation's status field), and the
 *     feature bit of the POOL extension is set in the build's mask;
 *   - the state passes the invariants (a stage needs the status tox and a member on the field).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
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

/* Bit 8: the occupant is badly poisoned; the low byte: its toxic stage; of each position (side * 2 + slot) after each step. */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t bits[4];
} rows[] = {
    {"g36_poison_fang_a", 0u, {0u, 0u, 0u, 0u}},
    {"g36_poison_fang_a", 1u, {0u, 0u, 0u, 0u}},
    {"g36_poison_fang_a", 2u, {0u, 0u, 257u, 257u}},
    {"g36_poison_fang_a", 3u, {0u, 0u, 258u, 258u}},
    {"g36_poison_fang_a", 4u, {0u, 0u, 259u, 259u}},
    {"g36_poison_fang_a", 5u, {0u, 0u, 260u, 260u}},
    {"g36_poison_fang_a", 6u, {0u, 0u, 0u, 261u}},
    {"g36_poison_fang_b", 0u, {0u, 0u, 0u, 0u}},
    {"g36_poison_fang_b", 1u, {0u, 0u, 0u, 0u}},
    {"g36_poison_fang_b", 2u, {0u, 0u, 257u, 257u}},
    {"g36_poison_fang_b", 3u, {0u, 0u, 258u, 258u}},
    {"g36_poison_fang_b", 4u, {0u, 0u, 259u, 259u}},
    {"g36_poison_fang_b", 5u, {0u, 0u, 260u, 260u}},
    {"g36_poison_fang_b", 6u, {0u, 0u, 0u, 261u}},
    {"g36_toxic_a", 0u, {0u, 0u, 0u, 0u}},
    {"g36_toxic_a", 1u, {0u, 0u, 257u, 257u}},
    {"g36_toxic_a", 2u, {0u, 0u, 258u, 258u}},
    {"g36_toxic_a", 3u, {0u, 0u, 257u, 259u}},
    {"g36_toxic_a", 4u, {0u, 0u, 257u, 260u}},
    {"g36_toxic_a", 5u, {0u, 0u, 258u, 261u}},
    {"g36_toxic_a", 6u, {0u, 0u, 259u, 262u}},
    {"g36_toxic_a", 7u, {0u, 0u, 260u, 0u}},
    {"g36_toxic_fail", 0u, {0u, 0u, 0u, 0u}},
    {"g36_toxic_fail", 1u, {0u, 0u, 0u, 0u}},
    {"g36_toxic_fail", 2u, {0u, 0u, 0u, 0u}},
    {"g36_toxic_fail", 3u, {0u, 0u, 0u, 0u}},
    {"g36_toxic_fail", 4u, {0u, 0u, 0u, 0u}},
    {"g36_toxic_fail", 5u, {0u, 0u, 0u, 0u}},
    {"g36_toxic_mirror_a", 0u, {0u, 0u, 0u, 0u}},
    {"g36_toxic_mirror_a", 1u, {257u, 0u, 257u, 0u}},
    {"g36_toxic_mirror_a", 2u, {258u, 0u, 258u, 0u}},
    {"g36_toxic_mirror_a", 3u, {259u, 0u, 259u, 0u}},
    {"g36_toxic_mirror_a", 4u, {260u, 0u, 260u, 0u}},
    {"g36_toxic_mirror_a", 5u, {261u, 0u, 261u, 0u}},
    {"g36_toxic_mirror_b", 0u, {0u, 0u, 0u, 0u}},
    {"g36_toxic_mirror_b", 1u, {257u, 0u, 257u, 0u}},
    {"g36_toxic_mirror_b", 2u, {258u, 0u, 258u, 0u}},
    {"g36_toxic_mirror_b", 3u, {259u, 0u, 259u, 0u}},
    {"g36_toxic_mirror_b", 4u, {260u, 0u, 260u, 0u}},
    {"g36_toxic_mirror_b", 5u, {261u, 0u, 261u, 0u}},
};

static const char *const names[] = {"g36_poison_fang_a", "g36_poison_fang_b", "g36_toxic_a", "g36_toxic_fail", "g36_toxic_mirror_a", "g36_toxic_mirror_b"};

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g36");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    uint32_t compared = 0u;
    uint32_t staged = 0u;
    (void)conf_events;
    DF_CHECK_EQ_U64(&t, DUOFORGE_AILMENT_TOX, 6u);
    DF_CHECK_EQ_U64(&t, DFI_STATUS_TOX, DUOFORGE_AILMENT_TOX);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_AILMENT_TOX, 10u);
    DF_CHECK(&t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_AILMENT_TOX)) != 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_TOXIC] != 0u && dfi_support.moves[DFI_MOVE_POISONFANG] != 0u);
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
            uint32_t want[4] = {0xFFFFu, 0xFFFFu, 0xFFFFu, 0xFFFFu};
            for (size_t r = 0u; r < sizeof rows / sizeof rows[0]; ++r) {
                if (strcmp(rows[r].battle, names[n]) == 0 && rows[r].step == si) {
                    for (uint32_t k = 0u; k < 4u; ++k) {
                        want[k] = rows[r].bits[k];
                    }
                }
            }
            if (!DF_CHECK(&t, want[0] != 0xFFFFu)) {
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
                continue;
            }
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation ob;
                memset(&ob, 0, sizeof ob);
                DF_CHECK(&t, duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK);
                for (uint32_t flat = 0u; flat < 4u; ++flat) {
                    const uint32_t s = flat / 2u;
                    const uint32_t occ = b->sides[s].positions[flat % 2u].occupant;
                    if (occ >= DUOFORGE_MAX_ROSTER || b->sides[s].members[occ].hp == 0u) {
                        continue;
                    }
                    DF_CHECK_EQ_U64(&t, b->sides[s].members[occ].status == DFI_STATUS_TOX ? 1u : 0u, (want[flat] >> 8u) & 1u);
                    DF_CHECK_EQ_U64(&t, b->tail.sides[s].toxic_stage[occ], want[flat] & 0xFFu);
                    if (viewer == 0u) {
                        staged += b->tail.sides[s].toxic_stage[occ] != 0u ? 1u : 0u;
                    }
                    const uint32_t shown = ob.sides[s].members[occ].status;
                    if ((want[flat] & 0x100u) != 0u && s == viewer) {
                        DF_CHECK_EQ_U64(&t, shown, DUOFORGE_AILMENT_TOX);
                    }
                }
                compared += 1u;
            }
            DF_CHECK(&t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
        }
        duoforge_battle_destroy(b);
    }
    DF_CHECK(&t, compared != 0u && staged != 0u);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
