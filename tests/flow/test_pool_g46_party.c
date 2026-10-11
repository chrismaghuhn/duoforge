/*
 * Step G46, party_order (docs/decisions/0015 section 7): the engine's order of the brought members, after every step of recorded
 * POOL battles with several switches, equals the side.pokemon order of the pinned Showdown.
 *
 * The expectations are tests/reference/party_order_g46.h, generated from the traces by tools/reference/party_expect.py: the
 * state.sides[s].pokemon list of each step, mapped to the roster index through the start log. Each replayed step runs the
 * recorded tape of the conformance battle (the same records as test_pool_g41.c), and the engine's entries (roster index + 1,
 * 3 bits, tail.party_order) must be the expected row: the four brought members in order, the rest empty.
 *
 * A row also checks the count (every expected battle has as many rows as conformance steps), so a battle cannot pass with
 * fewer steps replayed.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "reference/conformance_pool.h"
#include "reference/party_order_g46.h"
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

static const df_conf_battle *find_conf(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

/* The engine's party order of one side equals the expected row: entries 0..3 are roster index + 1, entries 4..5 empty. */
static bool party_matches(const duoforge_battle *b, uint32_t side, const uint8_t want[4])
{
    for (uint32_t k = 0u; k < 4u; ++k) {
        if (dfi_party_entry(&b->tail, side, k) != (uint32_t)want[k] + 1u) {
            return false;
        }
    }
    return dfi_party_entry(&b->tail, side, 4u) == 0u && dfi_party_entry(&b->tail, side, 5u) == 0u;
}

static void check_battle(df_test *t, const duoforge_context *ctx, const df_party_battle *pb)
{
    const df_conf_battle *cb = find_conf(pb->name);
    if (!DF_CHECK(t, cb != NULL && cb->step_count == pb->row_count)) {
        fprintf(stderr, "  %s: %u expected rows, the conformance record has %u steps\n", pb->name, (unsigned)pb->row_count,
                cb != NULL ? (unsigned)cb->step_count : 0u);
        return;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return;
    }
    uint32_t switches = 0u;
    for (uint32_t si = 0u; si < cb->step_count; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0xFFFFFFFFu;
        const duoforge_status status = dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (!DF_CHECK(t, status == DUOFORGE_OK && used == st->tape_len)) {
            fprintf(stderr, "  %s step %u: %s\n", pb->name, (unsigned)si, duoforge_status_name(status));
            break;
        }
        const df_party_row *row = &pb->rows[si];
        if (!DF_CHECK(t, row->step == si)) {
            break;
        }
        for (uint32_t s = 0u; s < 2u; ++s) {
            if (!DF_CHECK(t, party_matches(b, s, row->order[s]))) {
                fprintf(stderr, "  %s step %u side %u: party order differs from Showdown\n", pb->name, (unsigned)si,
                        (unsigned)s);
            }
        }
        if (si > 0u && memcmp(row->order, pb->rows[si - 1].order, sizeof row->order) != 0) {
            ++switches;
        }
    }
    /* The battle has the switches it was chosen for (a row that changed the lead order, on either side). */
    DF_CHECK(t, switches >= 1u);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g46_party");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    for (size_t i = 0; i < sizeof party_battles / sizeof party_battles[0]; ++i) {
        check_battle(&t, ctx, &party_battles[i]);
    }
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
