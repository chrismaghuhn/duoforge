/*
 * duoforge.state.pool_g97 (white-box): step G97 (decision 0064), Metal Burst. The public record refuses with
 * DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY (64) at a PIVOT while a Metal Burst user is on the field, because the record of the
 * foe's hit is live mid-turn and not public; at a turn boundary and at the first decision it does not refuse (the record is
 * zero there). The invariant TAIL_POSITION checks the record of a standing occupant: the source is a foe (flat + 1, at most 4),
 * and the damage is zero whenever there is no source.
 *
 * The recorded battles are replayed as duoforge.reference.conformance_pool_data replays them (the kept draws, the commands).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "data/pool_tables.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/invariants.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* The recorded battle `name` (conformance_pool.h). */
static const df_conf_battle *find_conf(const char *name)
{
    for (size_t i = 0u; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

/* The setup of a recorded battle, as the conformance test builds it. */
static void setup_from(const df_conf_battle *cb, duoforge_battle_setup *s)
{
    memset(s, 0, sizeof *s);
    s->rng_initstate = 1u;
    s->rng_initseq = 2u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        s->sides[side].member_count = cb->member_count;
        for (uint32_t m = 0u; m < cb->member_count; ++m) {
            const df_conf_member *src = &cb->members[side][m];
            duoforge_member_setup *dst = &s->sides[side].members[m];
            dst->species_id = src->species;
            dst->gender = src->gender;
            dst->nature = src->nature;
            for (uint32_t i = 0u; i < 6u; ++i) {
                dst->stat_points[i] = src->sp[i];
            }
            dst->ability = src->ability;
            dst->item = src->item;
            dst->move_count = src->move_count;
            for (uint32_t k = 0u; k < src->move_count; ++k) {
                dst->moves[k].move_id = src->moves[k];
            }
        }
    }
}

static void finish(duoforge_context *ctx, duoforge_battle *b)
{
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

/* Creates the recorded battle `name` (no step yet). Returns false when it cannot. */
static bool start(df_test *t, const char *name, duoforge_context **ctx, duoforge_battle **b, const df_conf_battle **cbo)
{
    *ctx = df_make_context(&df_config_pool);
    DF_CHECK(t, *ctx != NULL);
    *cbo = find_conf(name);
    DF_CHECK(t, *cbo != NULL);
    if (*ctx == NULL || *cbo == NULL) {
        return false;
    }
    duoforge_battle_setup s;
    setup_from(*cbo, &s);
    *b = df_make_battle(*ctx, &s);
    DF_CHECK(t, *b != NULL);
    return *b != NULL;
}

/* Steps `from` up to `to` (exclusive) of the recorded battle, as the conformance replay does. */
static duoforge_status replay_steps(duoforge_context *ctx, duoforge_battle *b, const df_conf_battle *cb, uint32_t from, uint32_t to)
{
    static duoforge_event ev_buf[2][DUOFORGE_MAX_EVENTS];
    for (uint32_t si = from; si < to && si < cb->step_count; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        memset(&bd, 0, sizeof bd);
        bd.epoch = b->request_epoch;
        bd.response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u)); /* wide-operands-reviewed */
        for (uint32_t s = 0u; s < 2u; ++s) {
            if ((s == 0u && !st->answered0) || (s == 1u && !st->answered1)) {
                continue;
            }
            duoforge_side_choice *r = &bd.responses[s];
            r->epoch = b->request_epoch;
            r->side = (uint8_t)s;
            if (st->team) {
                r->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
                r->pick_count = 4u;
                for (uint32_t i = 0u; i < 4u; ++i) {
                    r->picks[i] = st->picks[s][i];
                }
            } else {
                r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
                for (uint32_t k = 0u; k < 2u; ++k) {
                    const df_conf_cmd *c = &st->cmds[s][k];
                    r->slots[k] = (duoforge_slot_command){c->kind, c->move_slot, c->target, c->mega, c->reserve, {0u, 0u, 0u}};
                }
            }
        }
        duoforge_step_result res;
        uint32_t used = 0xFFFFFFFFu;
        duoforge_event_buffer buffers[2] = {{ev_buf[0], DUOFORGE_MAX_EVENTS, 0u}, {ev_buf[1], DUOFORGE_MAX_EVENTS, 0u}};
        const duoforge_status status =
            dfi_battle_step_events_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res, buffers);
        if (status != DUOFORGE_OK) {
            return status;
        }
        if (used != st->tape_len) {
            return DUOFORGE_E_INVARIANT;
        }
    }
    return DUOFORGE_OK;
}

/* The PIVOT of g97_metal_burst_attacker_switched (the replacement request after Flip Turn, with Aggron on the field and a
 * Metal Burst user): both players are refused with cause 64. */
static void test_pivot_refusal(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    const df_conf_battle *cb = NULL;
    if (!start(t, "g97_metal_burst_attacker_switched", &ctx, &b, &cb)) {
        finish(ctx, b);
        return;
    }
    DF_CHECK_EQ_U64(t, replay_steps(ctx, b, cb, 0u, 2u), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, b->boundary_kind, DUOFORGE_BOUNDARY_PIVOT);
    for (uint32_t player = 0u; player < DUOFORGE_SIDE_COUNT; ++player) {
        uint32_t causes = 0u;
        DF_CHECK_EQ_U64(t, duoforge_battle_public_causes(ctx, b, player, &causes), DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, causes & DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY, DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY);
        duoforge_public_state pub;
        DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, b, player, &pub), DUOFORGE_E_UNSUPPORTED);
    }
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

/* g97_metal_burst_normal at the turn-2 boundary (a TURN boundary, the record of turn 1 ended): Metal Burst is known, and the
 * public record does not refuse. */
static void test_turn_boundary_not_refused(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    const df_conf_battle *cb = NULL;
    if (!start(t, "g97_metal_burst_normal", &ctx, &b, &cb)) {
        finish(ctx, b);
        return;
    }
    DF_CHECK_EQ_U64(t, replay_steps(ctx, b, cb, 0u, 2u), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, b->boundary_kind, DUOFORGE_BOUNDARY_TURN);
    for (uint32_t player = 0u; player < DUOFORGE_SIDE_COUNT; ++player) {
        uint32_t causes = 0u;
        DF_CHECK_EQ_U64(t, duoforge_battle_public_causes(ctx, b, player, &causes), DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, causes & DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY, 0u);
        duoforge_public_state pub;
        DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, b, player, &pub), DUOFORGE_OK);
    }
    finish(ctx, b);
}

/* g97_metal_burst_normal at the first decision (turn 1, after the leads): Metal Burst is known, the record is zero, and the
 * public record does not refuse. */
static void test_first_decision_not_refused(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    const df_conf_battle *cb = NULL;
    if (!start(t, "g97_metal_burst_normal", &ctx, &b, &cb)) {
        finish(ctx, b);
        return;
    }
    DF_CHECK_EQ_U64(t, replay_steps(ctx, b, cb, 0u, 1u), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, b->turn, 1u);
    for (uint32_t player = 0u; player < DUOFORGE_SIDE_COUNT; ++player) {
        uint32_t causes = 0u;
        DF_CHECK_EQ_U64(t, duoforge_battle_public_causes(ctx, b, player, &causes), DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, causes & DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY, 0u);
    }
    finish(ctx, b);
}

/* The record of a standing occupant, on the turn-2 state of g97_metal_burst_normal (Aggron at flat 0, Dragonite at flat 2 and
 * standing). A valid foe record is OK; a source that is the user's own side, a source above 4, or a damage without a source
 * is TAIL_POSITION. */
static void test_record_invariant(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    const df_conf_battle *cb = NULL;
    if (!start(t, "g97_metal_burst_normal", &ctx, &b, &cb)) {
        finish(ctx, b);
        return;
    }
    DF_CHECK_EQ_U64(t, replay_steps(ctx, b, cb, 0u, 2u), DUOFORGE_OK);
    dfi_tail_pos *p = &b->tail.sides[0].positions[0];
    DF_CHECK_EQ_U64(t, p->metal_source, 0u);
    DF_CHECK_EQ_U64(t, p->metal_damage, 0u);
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);

    dfi_invariant inv = DFI_INV_NONE;
    p->metal_source = 3u; /* flat 2, the foe Dragonite (side 1) */
    p->metal_damage = 5u;
    DF_CHECK_EQ_U64(t, dfi_state_check(ctx, b, &inv), DUOFORGE_OK);

    p->metal_source = 1u; /* flat 0, the occupant itself: its own side */
    DF_CHECK_EQ_U64(t, dfi_state_check(ctx, b, &inv), DUOFORGE_E_INVARIANT);
    DF_CHECK_EQ_U64(t, inv, DFI_INV_TAIL_POSITION);

    p->metal_source = 5u; /* above the four positions */
    inv = DFI_INV_NONE;
    DF_CHECK_EQ_U64(t, dfi_state_check(ctx, b, &inv), DUOFORGE_E_INVARIANT);
    DF_CHECK_EQ_U64(t, inv, DFI_INV_TAIL_POSITION);

    p->metal_source = 0u; /* a damage without a source */
    inv = DFI_INV_NONE;
    DF_CHECK_EQ_U64(t, dfi_state_check(ctx, b, &inv), DUOFORGE_E_INVARIANT);
    DF_CHECK_EQ_U64(t, inv, DFI_INV_TAIL_POSITION);

    p->metal_damage = 0u;
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g97");
    test_pivot_refusal(&t);
    test_turn_boundary_not_refused(&t);
    test_first_decision_not_refused(&t);
    test_record_invariant(&t);
    return df_test_end(&t);
}
