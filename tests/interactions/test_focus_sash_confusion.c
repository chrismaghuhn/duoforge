/*
 * duoforge.combat.focus_sash_confusion (white-box): the confusion self-hit is
 * damage with a Move effect (data/conditions.ts:193-194), so a Focus Sash
 * holder at full HP whom it would faint uses the sash and keeps 1 HP
 * (data/items.ts:2275-2282); the item lines come in the reference order,
 * [-activate] confusion, [-enditem] Focus Sash, then [-damage] with the
 * confusion cause.
 *
 * No setup of the pool can make that self-hit lethal from full HP (the holder
 * would need an Attack of about ten times its Defense and a way to be
 * confused without being hurt first: only a damaging secondary confuses, and
 * Recover is not marked), so there is no recorded battle for it. The state is
 * poked instead: Team A's lead Rillaboom with Attack +6 and Defense -6, held
 * Focus Sash, confused, at full HP, and Speed +6 so that nobody hurts it
 * before it moves. The battle's own random stream decides whether the
 * confusion hits (33 percent); the seeds that hit are checked, and the same
 * seed without the sash is the control: the self-hit faints it.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

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

/* Every active slot uses its first move on the first foe. */
static void turn_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b)
{
    static const uint8_t plan[2][2] = {{2u, 3u}, {0u, 1u}}; /* the target of each slot */
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        duoforge_side_choice *c = &bd->responses[side];
        c->epoch = b->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
        for (uint32_t slot = 0u; slot < 2u; ++slot) {
            c->slots[slot].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
            c->slots[slot].move_slot = 0u;
            c->slots[slot].target = plan[side][slot];
        }
    }
}

typedef struct outcome {
    bool confusion_hit;     /* a [-damage] with the confusion cause for position 0 */
    bool item_end_before;   /* a [-enditem] of the sash for position 0 right before it */
    uint32_t hp_after_hit;  /* the HP that the confusion damage event shows */
    uint32_t hp;            /* the member's HP at the end of the step */
    uint32_t item_consumed; /* its item_consumed flag at the end */
} outcome;

/* One seed: the state as poked, one turn; what the confusion did. `with_sash` is the control switch. */
static outcome run(const duoforge_context *kp, uint64_t seed, bool with_sash, df_test *t)
{
    outcome o;
    memset(&o, 0, sizeof o);
    duoforge_battle_setup setup;
    df_setup_teams(&setup);
    setup.rng_initstate = seed;
    duoforge_battle *b = df_make_battle(kp, &setup);
    duoforge_decision_bundle bd;
    team_bundle(&bd, b);
    duoforge_step_result res;
    DF_CHECK(t, duoforge_battle_step(kp, b, &bd, &res) == DUOFORGE_OK);
    dfi_active_slot *pos = &b->sides[0].positions[0];
    dfi_member *m = &b->sides[0].members[pos->occupant];
    m->item = with_sash ? (uint8_t)(DFI_ITEM_FOCUSSASH + 1u) : 0u;
    m->item_consumed = 0u;
    m->hp = m->hp_max;
    pos->confusion_turns = 4u;
    pos->stages[DFI_STAGE_ATK] = (uint8_t)DFI_STAGE_MAX;
    pos->stages[DFI_STAGE_DEF] = 0u;
    pos->stages[DFI_STAGE_SPE] = (uint8_t)DFI_STAGE_MAX;
    turn_bundle(&bd, b);
    static duoforge_event ev[2][DUOFORGE_MAX_EVENTS];
    duoforge_event_buffer buffers[2] = {{ev[0], DUOFORGE_MAX_EVENTS, 0u}, {ev[1], DUOFORGE_MAX_EVENTS, 0u}};
    const duoforge_status st = duoforge_battle_step_events(kp, b, &bd, &res, buffers);
    DF_CHECK(t, st == DUOFORGE_OK);
    for (uint32_t i = 0u; i < buffers[0].count; ++i) {
        const duoforge_event *e = &ev[0][i];
        if (e->kind == DUOFORGE_EVENT_DAMAGE && e->position == 0u && e->cause == DUOFORGE_CAUSE_CONFUSION) {
            o.confusion_hit = true;
            o.hp_after_hit = e->hp;
            o.item_end_before = i > 0u && ev[0][i - 1u].kind == DUOFORGE_EVENT_ITEM_END &&
                                ev[0][i - 1u].position == 0u && ev[0][i - 1u].id2 == DFI_ITEM_FOCUSSASH + 1u;
            /* [-activate] confusion comes first: right before the damage, or before the sash line. */
            const uint32_t back = o.item_end_before ? 2u : 1u;
            DF_CHECK(t, i >= back && ev[0][i - back].kind == DUOFORGE_EVENT_CONFUSED);
        }
    }
    o.hp = m->hp;
    o.item_consumed = m->item_consumed;
    duoforge_battle_destroy(b);
    return o;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.combat.focus_sash_confusion");
    duoforge_context *kp = df_make_context(&df_config_pool);

    uint32_t hits = 0u;
    uint32_t misses = 0u;
    for (uint64_t seed = 1u; seed <= 60u; ++seed) {
        const outcome with = run(kp, seed, true, &t);
        const outcome without = run(kp, seed, false, &t);
        /* The random stream does not depend on the item: the self-hit happens in both or in neither. */
        DF_CHECK(&t, with.confusion_hit == without.confusion_hit);
        if (with.confusion_hit) {
            hits += 1u;
            /* The control: the self-hit faints the holder. */
            DF_CHECK_EQ_U64(&t, without.hp_after_hit, 0u);
            DF_CHECK_EQ_U64(&t, without.hp, 0u);
            /* With the sash: used up, shown before the damage, and 1 HP left. */
            DF_CHECK(&t, with.item_end_before);
            DF_CHECK_EQ_U64(&t, with.hp_after_hit, 1u);
            DF_CHECK_EQ_U64(&t, with.item_consumed, 1u);
            DF_CHECK(&t, with.hp <= 1u); /* nothing but a later hit of the turn could take the last HP */
        } else {
            misses += 1u;
            /* No self-hit: the sash is still there. */
            DF_CHECK_EQ_U64(&t, with.item_consumed, 0u);
        }
    }
    fprintf(stderr, "  %u seeds hit themselves, %u did not\n", (unsigned)hits, (unsigned)misses);
    DF_CHECK(&t, hits >= 5u);
    DF_CHECK(&t, misses >= 5u);

    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
