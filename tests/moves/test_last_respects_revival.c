/*
 * duoforge.state.last_respects_revival (white-box): Last Respects after Revival Blessing (decision 0083 section 7).
 *
 * Last Respects counts side.totalFainted, which the state derives from the brought members at 0 HP (decision 0009 section 4.1).
 * A revived member fainted once more than the roster shows (sim/battle.ts:2554 counts every faint) and the state does not count
 * revivals, so a Last Respects of a side whose Revival Blessing has spent PP is refused (E_UNSUPPORTED), never played with the
 * roster count.
 *
 * The recorded battle o2_last_respects_revival (duoforge.reference.conformance_pool_data replays it): Raichu, p1b, faints at
 * step 1, Basculegion comes in at step 2, Pawmot, p1a, uses Revival Blessing at step 3 and revives Raichu at step 4. This file
 * continues it: after step 4 a Last Respects of Basculegion is refused and the battle is unchanged; after step 2 (Raichu at
 * 0 HP, Revival Blessing not used) the same turn runs.
 * Flat positions: side 0 slots 0 and 1 (flat 0, 1), side 1 slots 0 and 1 (flat 2, 3).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/turn.h"
#include "data/extended_tables.h"
#include "data/pool_tables.h"
#include "reference/conformance_pool.h"
#include "state/request.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

#define BATTLE "o2_last_respects_revival"

static const df_conf_battle *find_conf(const char *name)
{
    for (size_t i = 0u; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

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

/* The team preview: the first four of each paste ("team 1234" in the spec). */
static void team_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        duoforge_side_choice *c = &bd->responses[side];
        c->epoch = b->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
        c->pick_count = 4u;
        for (uint32_t i = 0u; i < 4u; ++i) {
            c->picks[i] = (uint8_t)i;
        }
    }
}

static void conf_bundle(const df_conf_step *st, const duoforge_battle *b, duoforge_decision_bundle *bd)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u));
    for (uint32_t s = 0u; s < 2u; ++s) {
        if ((s == 0u && !st->answered0) || (s == 1u && !st->answered1)) {
            continue;
        }
        duoforge_side_choice *r = &bd->responses[s];
        r->epoch = b->request_epoch;
        r->side = (uint8_t)s;
        r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
        for (uint32_t k = 0u; k < 2u; ++k) {
            const df_conf_cmd *c = &st->cmds[s][k];
            r->slots[k] = (duoforge_slot_command){c->kind, c->move_slot, c->target, c->mega, c->reserve, {0u, 0u, 0u}};
        }
    }
}

/* The turn after the recorded steps: Pawmot (flat 0) Protect, Basculegion (flat 1) Last Respects into Garchomp (flat 2); both
 * foes Protect. */
static void last_respects_bundle(const duoforge_battle *b, duoforge_decision_bundle *bd)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    for (uint32_t s = 0u; s < 2u; ++s) {
        duoforge_side_choice *r = &bd->responses[s];
        r->epoch = b->request_epoch;
        r->side = (uint8_t)s;
        r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
    }
    bd->responses[0].slots[0] = (duoforge_slot_command){DUOFORGE_SLOT_MOVE, 3u, DUOFORGE_TARGET_NONE, 0u, 0u, {0u, 0u, 0u}};
    bd->responses[0].slots[1] = (duoforge_slot_command){DUOFORGE_SLOT_MOVE, 0u, 2u, 0u, 0u, {0u, 0u, 0u}};
    bd->responses[1].slots[0] = (duoforge_slot_command){DUOFORGE_SLOT_MOVE, 2u, DUOFORGE_TARGET_NONE, 0u, 0u, {0u, 0u, 0u}};
    bd->responses[1].slots[1] = (duoforge_slot_command){DUOFORGE_SLOT_MOVE, 2u, DUOFORGE_TARGET_NONE, 0u, 0u, {0u, 0u, 0u}};
}

/* The recorded battle through its step `last` (team preview included), with the recorded draws. */
static bool replay(df_test *t, uint32_t last, duoforge_context **ctx, duoforge_battle **b)
{
    const df_conf_battle *cb = find_conf(BATTLE);
    DF_CHECK(t, cb != NULL);
    if (cb == NULL || last >= cb->step_count) {
        return false;
    }
    duoforge_battle_setup s;
    setup_from(cb, &s);
    *ctx = df_make_context(&df_config_pool);
    DF_CHECK(t, *ctx != NULL);
    if (*ctx == NULL) {
        return false;
    }
    *b = df_make_battle(*ctx, &s);
    DF_CHECK(t, *b != NULL);
    if (*b == NULL) {
        return false;
    }
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    team_bundle(&bd, *b);
    if (duoforge_battle_step(*ctx, *b, &bd, &res) != DUOFORGE_OK) {
        return false;
    }
    for (uint32_t si = 1u; si <= last; ++si) {
        const df_conf_step *st = &cb->steps[si];
        conf_bundle(st, *b, &bd);
        uint32_t used = 0u;
        if (dfi_battle_step_tape(*ctx, *b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) != DUOFORGE_OK) {
            return false;
        }
    }
    return true;
}

static void finish(duoforge_context *ctx, duoforge_battle *b)
{
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

/* The member on flat position `flat`. */
static const dfi_member *member_at(const duoforge_battle *b, uint32_t flat)
{
    return &b->sides[flat / 2u].members[b->sides[flat / 2u].positions[flat % 2u].occupant];
}

static void test_refused_after_revival(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    DF_CHECK(t, replay(t, 4u, &ctx, &b));
    if (b != NULL) {
        /* the setting the replay reached: Pawmot's Revival Blessing has spent PP, Raichu is back at 68 HP, nobody at 0 HP */
        const dfi_member *pawmot = member_at(b, 0u);
        DF_CHECK_EQ_U64(t, pawmot->moves[1].move_id, DFI_MOVE_REVIVALBLESSING);
        DF_CHECK(t, pawmot->moves[1].pp < pawmot->moves[1].pp_max);
        DF_CHECK_EQ_U64(t, member_at(b, 1u)->moves[0].move_id, DFI_MOVE_LASTRESPECTS);
        DF_CHECK_EQ_U64(t, b->sides[0].members[1].hp, 68u);
        static struct duoforge_battle before;
        before = *b;
        duoforge_decision_bundle bd;
        duoforge_step_result res;
        last_respects_bundle(b, &bd);
        DF_CHECK_EQ_U64(t, duoforge_battle_step(ctx, b, &bd, &res), DUOFORGE_E_UNSUPPORTED);
        DF_CHECK(t, memcmp(b, &before, sizeof before) == 0);
    }
    finish(ctx, b);
}

static void test_runs_before_revival(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    DF_CHECK(t, replay(t, 2u, &ctx, &b));
    if (b != NULL) {
        /* Raichu at 0 HP and Revival Blessing unused: the roster count is side.totalFainted, so the turn runs */
        const dfi_member *pawmot = member_at(b, 0u);
        DF_CHECK_EQ_U64(t, pawmot->moves[1].pp, pawmot->moves[1].pp_max);
        DF_CHECK_EQ_U64(t, b->sides[0].members[1].hp, 0u);
        const uint32_t pp = member_at(b, 1u)->moves[0].pp;
        duoforge_decision_bundle bd;
        duoforge_step_result res;
        last_respects_bundle(b, &bd);
        DF_CHECK_EQ_U64(t, duoforge_battle_step(ctx, b, &bd, &res), DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, member_at(b, 1u)->moves[0].pp, pp - 1u); /* Last Respects was used */
    }
    finish(ctx, b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.last_respects_revival");
    test_refused_after_revival(&t);
    test_runs_before_revival(&t);
    return df_test_end(&t);
}
