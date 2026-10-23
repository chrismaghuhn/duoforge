#ifndef DUOFORGE_TESTS_SUPPORT_CONFORMANCE_REPLAY_H
#define DUOFORGE_TESTS_SUPPORT_CONFORMANCE_REPLAY_H
/*
 * Replaying a recorded POOL battle of tests/reference/conformance_pool.h with the reference's tape (restructure step 6e). These
 * are the helpers that the split white-box tests share, each one character for character the copy that their source file had
 * (tools/restructure/split_test.py checks that, comments aside): the battle's setup, one step's decision bundle, a battle by
 * name, and three replays to a step, which differ in what they check on the way and at the end. Many older tests keep their own
 * copies; only the parts of a split include this header.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "reference/conformance_pool.h"
#include "state/request.h"
#include "support/check.h"

/* The setup of a recorded battle: its members, the fixed seed of the conformance runs. */
static inline void df_conf_build_setup(const df_conf_battle *cb, duoforge_battle_setup *s)
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

/* The decision bundle of one recorded step (team selection or slot commands) for the battle's current epoch. */
static inline void df_conf_bundle_of(const df_conf_step *st, const duoforge_battle *b, duoforge_decision_bundle *bd)
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

/* A recorded battle by name, or NULL. */
static inline const df_conf_battle *df_conf_find(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

/* The battle replayed through its first `steps` steps with the reference's tape: each step OK and its whole tape used,
 * the status named on a failure. NULL (and a failed check) when the battle is unknown, too short or a step fails. */
static inline duoforge_battle *df_conf_replay_by_name(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps)
{
    const df_conf_battle *cb = df_conf_find(name);
    if (!DF_CHECK(t, cb != NULL && steps <= cb->step_count)) {
        return NULL;
    }
    duoforge_battle_setup setup;
    df_conf_build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return NULL;
    }
    for (uint32_t si = 0u; si < steps; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        df_conf_bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0xFFFFFFFFu;
        const duoforge_status status =
            dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (!DF_CHECK(t, status == DUOFORGE_OK && used == st->tape_len)) {
            fprintf(stderr, "  %s step %u: %s\n", name, si, duoforge_status_name(status));
            duoforge_battle_destroy(b);
            return NULL;
        }
    }
    return b;
}

/* The same replay by name, and then the state check of the battle (DF_CHECK of duoforge_battle_check) before it returns. */
static inline duoforge_battle *df_conf_replay_checked(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps)
{
    const df_conf_battle *cb = df_conf_find(name);
    if (!DF_CHECK(t, cb != NULL && steps <= cb->step_count)) {
        return NULL;
    }
    duoforge_battle_setup setup;
    df_conf_build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return NULL;
    }
    for (uint32_t si = 0u; si < steps; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        df_conf_bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0xFFFFFFFFu;
        const duoforge_status status =
            dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (!DF_CHECK(t, status == DUOFORGE_OK && used == st->tape_len)) {
            fprintf(stderr, "  %s step %u: %s\n", name, si, duoforge_status_name(status));
            duoforge_battle_destroy(b);
            return NULL;
        }
    }
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    return b;
}

/* The same replay from the battle itself: each step's status checked and its tape used, the step named on a failure. */
static inline duoforge_battle *df_conf_replay_battle(df_test *t, const duoforge_context *ctx, const df_conf_battle *cb, uint32_t steps)
{
    duoforge_battle_setup setup;
    df_conf_build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return NULL;
    }
    for (uint32_t si = 0u; si < steps; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        df_conf_bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                             DUOFORGE_OK) ||
            !DF_CHECK_EQ_U64(t, used, st->tape_len)) {
            fprintf(stderr, "  %s step %u\n", cb->name, si);
            duoforge_battle_destroy(b);
            return NULL;
        }
    }
    return b;
}

/* The roster index of the member of `side` with forme `forme` (its first such member), or DUOFORGE_MAX_ROSTER. */
static inline uint32_t df_conf_member_of(const duoforge_battle *b, uint32_t side, uint32_t forme)
{
    for (uint32_t m = 0u; m < b->sides[side].member_count; ++m) {
        if (b->sides[side].members[m].species_id == forme) {
            return m;
        }
    }
    return DUOFORGE_MAX_ROSTER;
}

/* The step's status, tape use and player 0's events. */
typedef struct df_conf_run {
    duoforge_status status;
    uint32_t used;
    uint32_t count;
    duoforge_event events[DUOFORGE_MAX_EVENTS];
} df_conf_run;

/* One recorded step with the reference's tape, the events of both players kept (player 0's in `out`). */
static inline void df_conf_run_step(const duoforge_context *ctx, duoforge_battle *b, const df_conf_step *st, df_conf_run *out)
{
    duoforge_decision_bundle bd;
    df_conf_bundle_of(st, b, &bd);
    duoforge_step_result res;
    static duoforge_event other[DUOFORGE_MAX_EVENTS];
    memset(out->events, 0, sizeof out->events);
    duoforge_event_buffer buffers[2] = {{out->events, DUOFORGE_MAX_EVENTS, 0u}, {other, DUOFORGE_MAX_EVENTS, 0u}};
    out->used = 0u;
    out->status = dfi_battle_step_events_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &out->used, &res, buffers);
    out->count = buffers[0].count;
}

/* The replay of df_conf_replay_battle without its message: each step's status checked and its tape used. */
static inline duoforge_battle *df_conf_replay_quiet(df_test *t, const duoforge_context *ctx, const df_conf_battle *cb, uint32_t steps)
{
    duoforge_battle_setup setup;
    df_conf_build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return NULL;
    }
    for (uint32_t si = 0u; si < steps; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        df_conf_bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                             DUOFORGE_OK) ||
            !DF_CHECK_EQ_U64(t, used, st->tape_len)) {
            duoforge_battle_destroy(b);
            return NULL;
        }
    }
    return b;
}

/* The events of one recorded step with the reference's tape, player 0's view; returns the engine's status. */
static inline duoforge_status df_conf_step_events(const duoforge_context *ctx, duoforge_battle *b, const df_conf_step *st,
                                        duoforge_event *events, uint32_t *count)
{
    duoforge_decision_bundle bd;
    df_conf_bundle_of(st, b, &bd);
    duoforge_step_result res;
    uint32_t used = 0u;
    static duoforge_event other[DUOFORGE_MAX_EVENTS];
    duoforge_event_buffer buffers[2] = {{events, DUOFORGE_MAX_EVENTS, 0u}, {other, DUOFORGE_MAX_EVENTS, 0u}};
    const duoforge_status s =
        dfi_battle_step_events_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res, buffers);
    *count = buffers[0].count;
    return s;
}

#endif
