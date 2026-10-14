/*
 * duoforge.state.pool_k1 (white-box): step K1 (#476, decision 0015 entry 5dc), Temper Flare. Its basePowerCallback is the
 * one of Stomping Tantrum (the special DFI_SPECIAL_STOMPING_TANTRUM): base power x2 when the user's last move result is
 * FALSE, strictly (null is no failure). The four recorded battles (k1_temper_flare_* under "data": "pool") are replayed
 * through the step with the reference's draws; duoforge.reference.conformance_pool compares the damage of each hit (the
 * doubling included). Here is what the reference does not show, after every step of each battle, for the Charizard
 * position (flat 0, the user):
 *
 *   - the move result of the position: `this` (bits 0-1) and `last` (bits 2-3), against the table below. The classes are
 *     those of tests/moves/test_pool_g42.c; at the end of a turn `this` is 0 and `last` holds the turn's result.
 *   - a Temper Flare that hits: TRUE; a Roost at full HP (`-fail heal`): FALSE; a Temper Flare that Protect takes:
 *     NULL (no failure); a position that switched in: 0 in both (its result was cleared on the switch).
 *   - the unclassified bits (4, 5) and bits 6-7 are zero; the Roost volatile is not set (the Roost failed).
 *   - an unclassified last result (bit 5) makes Temper Flare refuse with E_UNSUPPORTED.
 *   - the manifest marks Temper Flare: the setup is accepted and the move has the special of Stomping Tantrum.
 *
 * Hand-checked damage of the four battles (Charizard atk 149 = floor((84 + 32 + 20) x 110 / 100), Dragonite def 115, level
 * 50; base damage = floor(floor(22 x BP x 149 / 115) / 50) + 2 = 44 at BP 75, 87 at BP 150; then the roll (100 - draw),
 * STAB x 1.5, and the half of a Fire move on Dragon): plain turn 1 roll 93 -> 30, turn 2 roll 95 -> 30 (last result TRUE,
 * BP 75); doubled turn 2 roll 87 at BP 150 -> 56; null turn 2 roll 88 at BP 75 -> 28; switch turn 4 roll 99 at BP 75 -> 32.
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

/* The boundary after each step of each battle: the Charizard position's move result (this, last). The unclassified bits and
 * the Roost bit are zero in all of them. Derived from the committed traces as described in the header. */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t this_result;
    uint32_t last_result;
} rows[] = {
    {"k1_temper_flare_plain", 0u, 0u, 0u},
    {"k1_temper_flare_plain", 1u, 0u, 1u},
    {"k1_temper_flare_plain", 2u, 0u, 1u},
    {"k1_temper_flare_doubled", 0u, 0u, 0u},
    {"k1_temper_flare_doubled", 1u, 0u, 2u},
    {"k1_temper_flare_doubled", 2u, 0u, 1u},
    {"k1_temper_flare_null", 0u, 0u, 0u},
    {"k1_temper_flare_null", 1u, 0u, 3u},
    {"k1_temper_flare_null", 2u, 0u, 1u},
    {"k1_temper_flare_switch", 0u, 0u, 0u},
    {"k1_temper_flare_switch", 1u, 0u, 2u},
    {"k1_temper_flare_switch", 2u, 0u, 0u},
    {"k1_temper_flare_switch", 3u, 0u, 0u},
    {"k1_temper_flare_switch", 4u, 0u, 1u},
};

static const char *const names[] = {"k1_temper_flare_plain", "k1_temper_flare_doubled", "k1_temper_flare_null",
                                    "k1_temper_flare_switch"};

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_k1");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    uint32_t steps_run = 0u;
    uint32_t false_last = 0u;

    DF_CHECK_EQ_U64(&t, DFI_MOVE_RESULT_NULL, 3u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_TEMPERFLARE] != 0u); /* the manifest mark: the setup with it is accepted */
    DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_TEMPERFLARE].special, DFI_SPECIAL_STOMPING_TANTRUM);

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
            steps_run += 1u;
            DF_CHECK(&t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
            uint32_t want_this = 0u;
            uint32_t want_last = 0u;
            uint32_t found = 0u;
            for (size_t r = 0u; r < sizeof rows / sizeof rows[0]; ++r) {
                if (strcmp(rows[r].battle, names[n]) == 0 && rows[r].step == si) {
                    want_this = rows[r].this_result;
                    want_last = rows[r].last_result;
                    found += 1u;
                }
            }
            if (!DF_CHECK(&t, found == 1u)) {
                fprintf(stderr, "  %s step %u: %u rows\n", names[n], si, found);
                continue;
            }
            const dfi_tail_pos *tp = &b->tail.sides[0].positions[0];
            const uint32_t mr = (uint32_t)tp->move_result;
            const bool ok = (mr & 3u) == want_this && ((mr >> DFI_MOVE_RESULT_LAST_SHIFT) & 3u) == want_last &&
                            (mr & 0xF0u) == 0u && (tp->single_turn & DFI_SINGLE_TURN_ROOST) == 0u &&
                            (tp->single_turn & ~DFI_TAIL_SINGLE_TURN_MASK) == 0u;
            if (!DF_CHECK(&t, ok)) {
                fprintf(stderr, "  %s step %u: move_result %#x (this %u last %u), want this %u last %u\n", names[n], si, mr,
                        mr & 3u, (mr >> DFI_MOVE_RESULT_LAST_SHIFT) & 3u, want_this, want_last);
            }
            false_last += want_last == 2u ? 1u : 0u;
        }
        duoforge_battle_destroy(b);
    }

    /* A Temper Flare whose user's last result carries the unclassified bit refuses with E_UNSUPPORTED: the plain battle after
     * step 1 (Charizard's Temper Flare hit, TRUE) with that bit set, then its step 2 (a Temper Flare). */
    {
        const df_conf_battle *cb = find("k1_temper_flare_plain");
        if (DF_CHECK(&t, cb != NULL && cb->step_count == 3u)) {
            duoforge_battle_setup setup;
            build_setup(cb, &setup);
            duoforge_battle *b = NULL;
            if (DF_CHECK(&t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
                duoforge_status st = DUOFORGE_OK;
                for (uint32_t si = 0u; si < 2u && st == DUOFORGE_OK; ++si) {
                    duoforge_decision_bundle bd;
                    bundle_of(&cb->steps[si], b, &bd);
                    duoforge_step_result res;
                    uint32_t used = 0u;
                    st = dfi_battle_step_tape(ctx, b, &bd, &conf_tape[cb->steps[si].tape_off], cb->steps[si].tape_len, &used,
                                              &res);
                }
                DF_CHECK_EQ_U64(&t, st, DUOFORGE_OK);
                dfi_tail_pos *charizard = &b->tail.sides[0].positions[0];
                /* the unclassified last result alone: an unclassified bit is only valid with the result bits of its slot zero */
                charizard->move_result = (uint8_t)DFI_MOVE_RESULT_UNCLASSIFIED_LAST;
                DF_CHECK(&t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
                duoforge_decision_bundle bd;
                bundle_of(&cb->steps[2], b, &bd);
                duoforge_step_result res;
                uint32_t used = 0u;
                DF_CHECK_EQ_U64(&t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[cb->steps[2].tape_off], cb->steps[2].tape_len,
                                                         &used, &res),
                                DUOFORGE_E_UNSUPPORTED);
                duoforge_battle_destroy(b);
            }
        }
    }

    fprintf(stderr, "  %u steps in %zu battles; %u Charizard boundaries with a FALSE last result\n", steps_run,
            sizeof names / sizeof names[0], false_last);
    DF_CHECK_EQ_U64(&t, sizeof rows / sizeof rows[0], 14u);
    DF_CHECK_EQ_U64(&t, steps_run, 14u);
    DF_CHECK_EQ_U64(&t, false_last, 2u);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
