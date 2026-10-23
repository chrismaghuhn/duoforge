/*
 * duoforge.abilities.inner_focus_intimidate_cap (white-box): step G22 of the content expansion (decision 0015 entry 5o), an
 * Intimidate drop that the cap already took to nothing, under both POOL kinds. Battle.boost (sim/battle.ts:2020-2088) caps the
 * change first (Attack at -6 is a change of 0, which is no `boost.atk` for Inner Focus's onTryBoost) and then shows
 * `-unboost|atk|0` for an ability's secondary change. So an Inner Focus holder at -6 Attack gets that line from Intimidate and
 * no `-fail` (data/abilities.ts:2157-2162); at -5 or better it gets the `-fail` and no unboost. The state is made by hand: the
 * Dragonite of g22_inner_focus has its Attack stage set to -6 before Staraptor's switch-in, and the control, with the stage
 * left alone, shows the `-fail`.
 *
 * Split by subject from the test of step G22 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/conformance_replay.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* The events of one step of a battle with the reference's tape, player 0's view; returns the engine's status. */
static duoforge_status step_events(const duoforge_context *ctx, duoforge_battle *b, const df_conf_step *st,
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

/* 2. Staraptor's Intimidate against the Dragonite of g22_inner_focus (p2a, flat 2) at -6 Attack and at 0. */
static void check_cap(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = df_conf_find("g22_inner_focus");
    if (!DF_CHECK(t, cb != NULL) || !DF_CHECK(t, cb->step_count > 3u)) {
        return;
    }
    const uint32_t switch_step = 3u; /* p1 switches Staraptor in for Incineroar (Parting Shot's pivot) */
    for (uint32_t capped = 0u; capped < 2u; ++capped) {
        duoforge_battle *b = df_conf_replay_battle(t, ctx, cb, switch_step);
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
    df_test_begin(&t, "duoforge.abilities.inner_focus_intimidate_cap");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kd = df_make_context(&df_config_pool_dev);
    for (uint32_t k = 0u; k < 2u; ++k) {
        const duoforge_context *ctx = k == 0u ? kp : kd;
        check_cap(&t, ctx);
    }
    duoforge_context_destroy(kd);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
