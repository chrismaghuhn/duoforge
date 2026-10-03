/*
 * duoforge.state.pool_g22 (white-box): step G22 of the content expansion, the weather Speed abilities, Inner Focus and
 * Liquid Voice. The recorded battles (g22_* under "data": "pool") are replayed by
 * duoforge.reference.conformance_pool_data; two things that they cannot show on their own are checked here.
 *
 *   1. The queued action of a fainted Swift Swim holder. In g22_swift_swim Kingambit knocks Basculegion out with Sucker
 *      Punch in the rain; its Liquidation stays in the queue and, with a standing holder's x2, would not tie Politoed's
 *      Weather Ball (196 against 98). The pin prices a fainted Pokemon's action again without its ability (an inactive
 *      Pokemon's ability handler is ignored, sim/battle.ts:874-883, sim/pokemon.ts:858-859), at the raw 98 that
 *      Politoed has with its 8 Speed points, so the two tie and the reference draws a shuffle. The tape without that entry
 *      fails exactly there (E_INVARIANT, every earlier entry consumed): the engine draws the tie.
 *   2. An Intimidate drop that the cap already took to nothing. Battle.boost (sim/battle.ts:2020-2088) caps the change
 *      first (getCappedBoost: Attack at -6 is a change of 0, which is no `boost.atk` for Inner Focus's onTryBoost) and
 *      the loop then shows `-unboost|atk|0` for an ability's secondary change. So an Inner Focus holder at -6 Attack
 *      gets that line from Intimidate and no `-fail` (data/abilities.ts:2157-2162); at -5 or better it gets the `-fail`
 *      and no unboost. The state is made by hand (no recorded battle reaches -6 Attack on an Inner Focus holder, because
 *      Intimidate is the usual way down and Inner Focus stops it): the Dragonite of g22_inner_focus has its Attack stage
 *      set to -6 before Staraptor's switch-in, and the control, with the stage left alone, shows the `-fail`.
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

/* The battle `name` after its first `steps` steps, the reference's draws as the tape; NULL when one fails. */
static duoforge_battle *replay(df_test *t, const duoforge_context *ctx, const df_conf_battle *cb, uint32_t steps)
{
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return NULL;
    }
    for (uint32_t si = 0u; si < steps; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
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

#define TAPE_MAX 64u

/* 1. The tie of a fainted Swift Swim holder's queued action. */
static void check_fainted_holder(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g22_swift_swim");
    if (!DF_CHECK(t, cb != NULL) || !DF_CHECK(t, cb->step_count > 4u)) {
        return;
    }
    const uint32_t decisive = 4u; /* turn 3: Sucker Punch, then the tie of Basculegion's and Politoed's actions */
    duoforge_battle *b = replay(t, ctx, cb, decisive);
    if (b == NULL) {
        return;
    }
    const df_conf_step *st = &cb->steps[decisive];
    const dfi_tape_entry *tape = &conf_tape[st->tape_off];
    uint32_t at = st->tape_len;
    for (uint32_t i = 1u; i < st->tape_len; ++i) {
        if (tape[i].site == DFI_SITE_SPEED_TIE && tape[i - 1u].site == DFI_SITE_DAMAGE_ROLL) {
            at = i;
            break;
        }
    }
    if (!DF_CHECK(t, at < st->tape_len) || !DF_CHECK(t, st->tape_len < TAPE_MAX)) {
        duoforge_battle_destroy(b);
        return;
    }
    duoforge_decision_bundle bd;
    bundle_of(st, b, &bd);
    static dfi_tape_entry variant[TAPE_MAX];
    uint32_t n = 0u;
    for (uint32_t i = 0u; i < st->tape_len; ++i) {
        if (i != at) {
            variant[n++] = tape[i];
        }
    }
    duoforge_battle *c = NULL;
    if (DF_CHECK(t, duoforge_battle_clone(ctx, b, &c) == DUOFORGE_OK)) {
        duoforge_step_result res;
        uint32_t used = 0u;
        DF_CHECK(t, dfi_battle_step_tape(ctx, c, &bd, tape, st->tape_len, &used, &res) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, used, st->tape_len);
        duoforge_battle_destroy(c);
    }
    c = NULL;
    if (DF_CHECK(t, duoforge_battle_clone(ctx, b, &c) == DUOFORGE_OK)) {
        duoforge_step_result res;
        uint32_t used = 0u;
        DF_CHECK(t, dfi_battle_step_tape(ctx, c, &bd, variant, n, &used, &res) == DUOFORGE_E_INVARIANT);
        if (!DF_CHECK_EQ_U64(t, used, at)) {
            fprintf(stderr, "  the engine asked for the tie of the fainted Swift Swim holder's action after %u entries, not %u\n",
                    used, at);
        }
        duoforge_battle_destroy(c);
    }
    duoforge_battle_destroy(b);
}

/* The events of one step of a battle with the reference's tape, player 0's view; returns the engine's status. */
static duoforge_status step_events(const duoforge_context *ctx, duoforge_battle *b, const df_conf_step *st,
                                   duoforge_event *events, uint32_t *count)
{
    duoforge_decision_bundle bd;
    bundle_of(st, b, &bd);
    duoforge_step_result res;
    uint32_t used = 0u;
    static duoforge_event other[DUOFORGE_MAX_EVENTS];
    duoforge_event_buffer buffers[2] = {{events, DUOFORGE_MAX_EVENTS, 0u}, {other, DUOFORGE_MAX_EVENTS, 0u}};
    const duoforge_status s =
        dfi_battle_step_events_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res, buffers);
    *count = buffers[0].count;
    return s;
}

/* 2. Staraptor's Intimidate against the Dragonite of g22_inner_focus (p2a, flat 2) at -6 Attack and at 0. */
static void check_cap(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g22_inner_focus");
    if (!DF_CHECK(t, cb != NULL) || !DF_CHECK(t, cb->step_count > 3u)) {
        return;
    }
    const uint32_t switch_step = 3u; /* p1 switches Staraptor in for Incineroar (Parting Shot's pivot) */
    for (uint32_t capped = 0u; capped < 2u; ++capped) {
        duoforge_battle *b = replay(t, ctx, cb, switch_step);
        if (b == NULL) {
            return;
        }
        if (capped != 0u) {
            b->sides[1].positions[0].stages[DFI_STAGE_ATK] = 0u; /* biased: -6 */
        }
        static duoforge_event events[DUOFORGE_MAX_EVENTS];
        uint32_t n = 0u;
        const df_conf_step *st = &cb->steps[switch_step];
        DF_CHECK(t, step_events(ctx, b, st, events, &n) == DUOFORGE_OK);
        uint32_t fails = 0u;
        uint32_t zero_drops = 0u;
        uint32_t raichu_drops = 0u;
        for (uint32_t i = 0u; i < n; ++i) {
            const duoforge_event *e = &events[i];
            if (e->kind == DUOFORGE_EVENT_FAIL && e->position == 2u && e->cause == DUOFORGE_CAUSE_ABILITY &&
                e->id2 == 1u + DFI_ABILITY_INNERFOCUS && e->other == 2u) {
                fails += 1u;
            }
            if (e->kind == DUOFORGE_EVENT_UNBOOST && e->position == 2u && e->detail == 0u && e->amount == 0u) {
                zero_drops += 1u;
            }
            if (e->kind == DUOFORGE_EVENT_UNBOOST && e->position == 3u && e->detail == 0u && e->amount == 1u) {
                raichu_drops += 1u;
            }
        }
        /* Raichu is lowered either way; the holder gets the -fail line at -5 or better and the empty -unboost at -6. */
        DF_CHECK_EQ_U64(t, raichu_drops, 1u);
        DF_CHECK_EQ_U64(t, fails, capped != 0u ? 0u : 1u);
        DF_CHECK_EQ_U64(t, zero_drops, capped != 0u ? 1u : 0u);
        /* the control keeps what Parting Shot of the second turn left: -1 */
        DF_CHECK_EQ_U64(t, (uint32_t)b->sides[1].positions[0].stages[DFI_STAGE_ATK], capped != 0u ? 0u : 5u);
        duoforge_battle_destroy(b);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g22");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kd = df_make_context(&df_config_pool_dev);
    for (uint32_t k = 0u; k < 2u; ++k) {
        const duoforge_context *ctx = k == 0u ? kp : kd;
        check_fainted_holder(&t, ctx);
        check_cap(&t, ctx);
    }
    duoforge_context_destroy(kd);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
