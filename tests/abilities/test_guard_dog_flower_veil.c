/*
 * duoforge.abilities.guard_dog_flower_veil (white-box): decision 0015 entry 5ec (issue 640), Guard Dog's TryBoost handler
 * before Flower Veil's. Guard Dog has onTryBoostPriority 2 (data/abilities.ts:1727-1744), Flower Veil's onAllyTryBoost the
 * default 0 (data/abilities.ts:1419-1437), so runEvent('TryBoost') (sim/battle.ts:2034) runs Guard Dog first: on a Grass holder
 * next to a Flower Veil holder it deletes Intimidate's Attack drop and raises the Attack by 1, and Flower Veil then finds no
 * drop and shows no -block. The state is step 2 of guard_dog_flower_veil_skill_swap (Meowscarada at p1a, flat 0, holds Guard
 * Dog by Skill Swap; Florges at p1b, flat 1, holds Flower Veil; Gyarados switches in with Intimidate), with the reference's
 * tape. The neighbours: Meowscarada with its own Overgrow (Flower Veil alone: its -block, the drop deleted, no Guard Dog), and
 * Florges with Symbiosis (Guard Dog alone: the same lines as both). Florges, no Grass type, loses its Attack in every variant.
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

enum { BOTH = 0, VEIL_ONLY = 1, DOG_ONLY = 2, VARIANTS = 3 };

static void check_order(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = df_conf_find("guard_dog_flower_veil_skill_swap");
    if (!DF_CHECK(t, cb != NULL) || !DF_CHECK(t, cb->step_count == 3u)) {
        return;
    }
    const uint32_t switch_step = 2u; /* Gyarados replaces Mabosstiff at p2a: Intimidate */
    for (uint32_t variant = 0u; variant < VARIANTS; ++variant) {
        duoforge_battle *b = df_conf_replay_battle(t, ctx, cb, switch_step);
        if (b == NULL) {
            return;
        }
        const uint32_t meow = df_conf_member_of(b, 0u, DFI_FORME_MEOWSCARADA);
        const uint32_t florges = df_conf_member_of(b, 0u, DFI_FORME_FLORGES);
        if (!DF_CHECK(t, meow < DUOFORGE_MAX_ROSTER && florges < DUOFORGE_MAX_ROSTER)) {
            duoforge_battle_destroy(b);
            return;
        }
        /* the recorded state: Skill Swap gave Meowscarada Guard Dog */
        DF_CHECK_EQ_U64(t, b->tail.sides[0].ability_now[meow], AB(GUARDDOG));
        DF_CHECK_EQ_U64(t, b->tail.sides[0].ability_now[florges], AB(FLOWERVEIL));
        if (variant == VEIL_ONLY) {
            b->tail.sides[0].ability_now[meow] = (uint16_t)AB(OVERGROW);
        } else if (variant == DOG_ONLY) {
            b->tail.sides[0].ability_now[florges] = (uint16_t)AB(SYMBIOSIS);
        }
        DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
        static duoforge_event events[DUOFORGE_MAX_EVENTS];
        uint32_t n = 0u;
        uint32_t used = 0u;
        const df_conf_step *st = &cb->steps[switch_step];
        DF_CHECK(t, step_events(ctx, b, st, events, &n, &used) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, used, st->tape_len);
        uint32_t blocks = 0u;
        uint32_t guard_dog_lines = 0u;
        uint32_t meow_ups = 0u;
        uint32_t meow_drops = 0u;
        uint32_t florges_drops = 0u;
        for (uint32_t i = 0u; i < n; ++i) {
            const duoforge_event *e = &events[i];
            if (e->kind == DUOFORGE_EVENT_ACTIVATE && e->position == 0u && e->cause == DUOFORGE_CAUSE_ABILITY &&
                e->id2 == AB(FLOWERVEIL) && e->other == 1u) {
                blocks += 1u;
            }
            if (e->kind == DUOFORGE_EVENT_ABILITY && e->position == 0u && e->id2 == AB(GUARDDOG)) {
                guard_dog_lines += 1u;
            }
            if (e->kind == DUOFORGE_EVENT_BOOST && e->position == 0u && e->detail == DFI_STAGE_ATK && e->amount == 1u) {
                meow_ups += 1u;
            }
            if (e->kind == DUOFORGE_EVENT_UNBOOST && e->position == 0u) {
                meow_drops += 1u;
            }
            if (e->kind == DUOFORGE_EVENT_UNBOOST && e->position == 1u && e->detail == DFI_STAGE_ATK && e->amount == 1u) {
                florges_drops += 1u;
            }
        }
        /* Guard Dog runs first: no -block whenever it holds; Flower Veil's -block only without it. */
        DF_CHECK_EQ_U64(t, blocks, variant == VEIL_ONLY ? 1u : 0u);
        DF_CHECK_EQ_U64(t, guard_dog_lines, variant == VEIL_ONLY ? 0u : 1u);
        DF_CHECK_EQ_U64(t, meow_ups, variant == VEIL_ONLY ? 0u : 1u);
        DF_CHECK_EQ_U64(t, meow_drops, 0u);
        DF_CHECK_EQ_U64(t, florges_drops, 1u);
        /* Attack stages, biased by 6: Meowscarada +1 with Guard Dog, unchanged under Flower Veil alone; Florges -1. */
        DF_CHECK_EQ_U64(t, (uint32_t)b->sides[0].positions[0].stages[DFI_STAGE_ATK], variant == VEIL_ONLY ? 6u : 7u);
        DF_CHECK_EQ_U64(t, (uint32_t)b->sides[0].positions[1].stages[DFI_STAGE_ATK], 5u);
        duoforge_battle_destroy(b);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.guard_dog_flower_veil");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kd = df_make_context(&df_config_pool_dev);
    if (DF_CHECK(&t, kp != NULL && kd != NULL)) {
        check_order(&t, kp);
        check_order(&t, kd);
    }
    duoforge_context_destroy(kd);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
