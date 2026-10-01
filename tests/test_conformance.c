/*
 * duoforge.reference.conformance (white-box): battles recorded from the
 * pinned Showdown (tests/reference/traces, converted by
 * tools/reference/trace_to_c.py into tests/reference/conformance.h) replayed
 * in DuoForge. The teams are created through the public API (CLOSURE_DEV,
 * the support gate must let them pass); every turn runs through the step
 * with the reference's kept draws as a test-only tape, which must be
 * consumed exactly; afterwards HP, PP, stat stages and the stall counter of
 * every member equal the reference, and so does the turn number.
 */
#include <stdio.h>
#include <string.h>

#include "reference/conformance.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"

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

static unsigned compare_state(const duoforge_battle *b, const df_conf_step *st, const char *name, uint32_t step)
{
    unsigned bad = 0;
    if (b->turn != st->turn) {
        fprintf(stderr, "  %s step %u: turn %u, reference %u\n", name, step, b->turn, st->turn);
        ++bad;
    }
    if (b->boundary_kind != st->boundary || b->result != st->result) {
        fprintf(stderr, "  %s step %u: boundary %u result %u, reference %u %u\n", name, step, b->boundary_kind,
                b->result, st->boundary, st->result);
        ++bad;
    }
    /* Entries in the reference's order have rising activation ids. */
    uint32_t last_activation = 0u;
    for (uint32_t i = 0; i < 4u && st->entries[i] != 0xFFu; ++i) {
        const uint32_t activation = b->sides[st->entries[i] / 2u].positions[st->entries[i] % 2u].activation_id;
        if (i > 0u && activation <= last_activation) {
            fprintf(stderr, "  %s step %u: entry %u (position %u) is out of the reference's order\n", name, step, i,
                    st->entries[i]);
            ++bad;
        }
        last_activation = activation;
    }
    for (uint32_t s = 0; s < 2u; ++s) {
        for (uint32_t p = 0; p < 2u; ++p) {
            if (b->sides[s].positions[p].occupant != st->occupants[s][p]) {
                fprintf(stderr, "  %s step %u: side %u position %u holds %u, reference %u\n", name, step, s, p,
                        b->sides[s].positions[p].occupant, st->occupants[s][p]);
                ++bad;
            }
        }
    }
    for (uint32_t s = 0; s < 2u; ++s) {
        for (uint32_t m = 0; m < 6u; ++m) {
            const df_conf_mon *e = &st->mons[s][m];
            if (!e->present) {
                continue;
            }
            const dfi_member *mem = &b->sides[s].members[m];
            if (mem->hp != e->hp) {
                fprintf(stderr, "  %s step %u: side %u member %u hp %u, reference %u\n", name, step, s, m, mem->hp,
                        e->hp);
                ++bad;
            }
            for (uint32_t k = 0; k < mem->move_count; ++k) {
                if (mem->moves[k].pp != e->pp[k]) {
                    fprintf(stderr, "  %s step %u: side %u member %u move %u pp %u, reference %u\n", name, step, s,
                            m, k, mem->moves[k].pp, e->pp[k]);
                    ++bad;
                }
            }
            /* Stages and the stall counter live in the position. */
            const dfi_active_slot *pos = NULL;
            for (uint32_t p = 0; p < 2u; ++p) {
                if (b->sides[s].positions[p].occupant == m) {
                    pos = &b->sides[s].positions[p];
                }
            }
            for (uint32_t i = 0; i < 7u; ++i) {
                const uint32_t have = pos != NULL ? pos->stages[i] : 6u;
                if (have != e->stages[i]) {
                    fprintf(stderr, "  %s step %u: side %u member %u stage %u = %u, reference %u\n", name, step, s,
                            m, i, have, e->stages[i]);
                    ++bad;
                }
            }
            const uint32_t stall = (pos != NULL && pos->stall_level != 0u) ? 1u : 0u;
            if (stall != e->stall) {
                fprintf(stderr, "  %s step %u: side %u member %u stall %u, reference %u\n", name, step, s, m, stall,
                        e->stall);
                ++bad;
            }
        }
    }
    return bad;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.reference.conformance");
    duoforge_context *k2 = df_make_context(&df_config_k2);
    for (size_t bi = 0; bi < sizeof conf_battles / sizeof conf_battles[0]; ++bi) {
        const df_conf_battle *cb = &conf_battles[bi];
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        duoforge_battle *b = NULL;
        if (!DF_CHECK(&t, duoforge_battle_create(k2, &setup, &b) == DUOFORGE_OK && b != NULL)) {
            fprintf(stderr, "  %s: the support gate rejects the development teams\n", cb->name);
            continue;
        }
        unsigned bad = 0;
        for (uint32_t si = 0; si < cb->step_count && bad == 0u; ++si) {
            const df_conf_step *st = &cb->steps[si];
            duoforge_decision_bundle bd;
            memset(&bd, 0, sizeof bd);
            bd.epoch = b->request_epoch;
            bd.response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u)); /* wide-operands-reviewed */
            for (uint32_t s = 0; s < 2u; ++s) {
                if ((s == 0u && !st->answered0) || (s == 1u && !st->answered1)) {
                    continue;
                }
                duoforge_side_choice *r = &bd.responses[s];
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
                        r->slots[k] = (duoforge_slot_command){c->kind, c->move_slot, c->target, c->mega, c->reserve,
                                                              {0u, 0u, 0u}};
                    }
                }
            }
            duoforge_step_result res;
            uint32_t used = 0xFFFFFFFFu;
            const duoforge_status status = dfi_battle_step_tape(k2, b, &bd, &conf_tape[st->tape_off], st->tape_len,
                                                                &used, &res);
            const bool consumed = st->team ? true : used == st->tape_len;
            if (!DF_CHECK(&t, status == DUOFORGE_OK && consumed)) {
                fprintf(stderr, "  %s step %u: %s, tape %u of %u\n", cb->name, si, duoforge_status_name(status),
                        used, st->tape_len);
                ++bad;
                break;
            }
            bad += compare_state(b, st, cb->name, si);
            DF_CHECK(&t, duoforge_battle_check(k2, b) == DUOFORGE_OK);
        }
        DF_CHECK_EQ_U64(&t, bad, 0u);
        duoforge_battle_destroy(b);
    }
    DF_CHECK_EQ_U64(&t, sizeof conf_battles / sizeof conf_battles[0], 12u);
    duoforge_context_destroy(k2);
    return df_test_end(&t);
}
