/*
 * duoforge.abilities.guard_dog_plus6 (white-box): decision 0015 entry 5el (issue 684), Guard Dog's nested boost is isSelf.
 * Guard Dog deletes Intimidate's Attack drop and calls this.boost({atk: 1}, target, target, null, false, true)
 * (data/abilities.ts:1727-1744). At +6 the change is capped to 0, and Battle.boost (sim/battle.ts) shows an ability's isSelf
 * change of 0 as -boost|holder|atk|0, with no -ability line. The state is step 5 of guard_dog_plus6_intimidate (Gallade at p1a,
 * flat 0, holds Guard Dog by Skill Swap and stands at +6 Attack after three Swords Dances; its ally Mabosstiff at p1b, flat 1, holds
 * Steadfast; Gyarados switches in with Intimidate), with the reference's tape. The neighbour: the same step with Gallade at +5,
 * where the change is 1 and shows after the -ability line. Mabosstiff loses its Attack in both.
 */
#include <stdbool.h>
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

#define AB(x) (1u + DFI_ABILITY_##x)

/* The events of one step with the reference's tape, player 0's view; returns the engine's status. */
static duoforge_status step_events(const duoforge_context *ctx, duoforge_battle *b, const df_conf_step *st,
                                   duoforge_event *events, uint32_t *count, uint32_t *used)
{
    duoforge_decision_bundle bd;
    df_conf_bundle_of(st, b, &bd);
    duoforge_step_result res;
    static duoforge_event other[DUOFORGE_MAX_EVENTS];
    duoforge_event_buffer buffers[2] = {{events, DUOFORGE_MAX_EVENTS, 0u}, {other, DUOFORGE_MAX_EVENTS, 0u}};
    const duoforge_status s =
        dfi_battle_step_events_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, used, &res, buffers);
    *count = buffers[0].count;
    return s;
}

static void check_plus6(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = df_conf_find("guard_dog_plus6_intimidate");
    if (!DF_CHECK(t, cb != NULL) || !DF_CHECK(t, cb->step_count == 6u)) {
        return;
    }
    const uint32_t switch_step = 5u; /* Gyarados replaces Chimecho at p2a: Intimidate */
    for (uint32_t at_plus6 = 0u; at_plus6 < 2u; ++at_plus6) {
        duoforge_battle *b = df_conf_replay_battle(t, ctx, cb, switch_step);
        if (b == NULL) {
            return;
        }
        const uint32_t gallade = df_conf_member_of(b, 0u, DFI_FORME_GALLADE);
        if (!DF_CHECK(t, gallade < DUOFORGE_MAX_ROSTER)) {
            duoforge_battle_destroy(b);
            return;
        }
        /* the recorded state: Skill Swap gave Gallade Guard Dog; three Swords Dances took it to +6 (biased 12) */
        DF_CHECK_EQ_U64(t, b->sides[0].positions[0].occupant, gallade);
        DF_CHECK_EQ_U64(t, b->tail.sides[0].ability_now[gallade], AB(GUARDDOG));
        DF_CHECK_EQ_U64(t, (uint32_t)b->sides[0].positions[0].stages[DFI_STAGE_ATK], 12u);
        if (at_plus6 == 0u) {
            b->sides[0].positions[0].stages[DFI_STAGE_ATK] = 11u; /* the neighbour: +5 */
        }
        DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
        static duoforge_event events[DUOFORGE_MAX_EVENTS];
        uint32_t n = 0u;
        uint32_t used = 0u;
        const df_conf_step *st = &cb->steps[switch_step];
        DF_CHECK(t, step_events(ctx, b, st, events, &n, &used) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, used, st->tape_len);
        uint32_t guard_dog_lines = 0u;
        uint32_t zero_ups = 0u;
        uint32_t one_ups = 0u;
        uint32_t gallade_drops = 0u;
        uint32_t mab_drops = 0u;
        for (uint32_t i = 0u; i < n; ++i) {
            const duoforge_event *e = &events[i];
            if (e->kind == DUOFORGE_EVENT_ABILITY && e->position == 0u && e->id2 == AB(GUARDDOG)) {
                guard_dog_lines += 1u;
            }
            if (e->kind == DUOFORGE_EVENT_BOOST && e->position == 0u && e->detail == DFI_STAGE_ATK) {
                zero_ups += e->amount == 0u ? 1u : 0u;
                one_ups += e->amount == 1u ? 1u : 0u;
            }
            if (e->kind == DUOFORGE_EVENT_UNBOOST && e->position == 0u) {
                gallade_drops += 1u;
            }
            if (e->kind == DUOFORGE_EVENT_UNBOOST && e->position == 1u && e->detail == DFI_STAGE_ATK && e->amount == 1u) {
                mab_drops += 1u;
            }
        }
        /* +6: one -boost atk 0 and no -ability line; +5: the -ability line and -boost atk 1. */
        DF_CHECK_EQ_U64(t, guard_dog_lines, at_plus6 != 0u ? 0u : 1u);
        DF_CHECK_EQ_U64(t, zero_ups, at_plus6 != 0u ? 1u : 0u);
        DF_CHECK_EQ_U64(t, one_ups, at_plus6 != 0u ? 0u : 1u);
        DF_CHECK_EQ_U64(t, gallade_drops, 0u);
        DF_CHECK_EQ_U64(t, mab_drops, 1u);
        DF_CHECK_EQ_U64(t, (uint32_t)b->sides[0].positions[0].stages[DFI_STAGE_ATK], 12u);
        DF_CHECK_EQ_U64(t, (uint32_t)b->sides[0].positions[1].stages[DFI_STAGE_ATK], 5u);
        duoforge_battle_destroy(b);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.guard_dog_plus6");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kd = df_make_context(&df_config_pool_dev);
    if (DF_CHECK(&t, kp != NULL && kd != NULL)) {
        check_plus6(&t, kp);
        check_plus6(&t, kd);
    }
    duoforge_context_destroy(kd);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
