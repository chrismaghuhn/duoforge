/*
 * duoforge.items.air_balloon_pop_order (white-box): issue 639, decision 0015 entry 5eb
 * (docs/mechanics/items/5eb-air-balloon-pops-after-the-holder.md). A standing Air Balloon holder hit by a damaging move: its
 * own DamagingHit ability handler comes before its item's pop. The pin gathers each target's ability handler before its item
 * (findPokemonEventHandlers, sim/battle.ts:1117-1130) and sorts the DamagingHit handlers stably by order, priority and the
 * target's index (compareLeftToRightOrder, :421-426); none of these handlers has an order. So every line of the holder's
 * ability prints before `-enditem|holder|Air Balloon`, and the ally's Symbiosis pass that the pop triggers (AfterUseItem,
 * data/items.ts:197-202) comes right after it.
 *
 * The three recorded battles f639_balloon_* (tests/reference/specs) are replayed with the reference's tape through the team
 * step, and their step 1 (the hits) is run once more with the events of both viewers. In each viewer's events of that step
 * the named ability events of the holder stand, in this order, directly before the holder's ITEM_END of Air Balloon, and the
 * Symbiosis ACTIVATE of the ally, where there is one, directly after it:
 *
 *   - f639_balloon_toxic_debris: Glimmora (p2a, Toxic Debris) hit by Quick Attack: ACTIVATE Toxic Debris, SIDE_START Toxic
 *     Spikes on p1's side, ITEM_END, then Floette-Eternal's Symbiosis.
 *   - f639_balloon_weak_armor_justified: Armarouge (p1b, Weak Armor) hit by Bullet Punch: ABILITY Weak Armor, UNBOOST def,
 *     BOOST spe, ITEM_END (no Symbiosis on p1's side); then Lucario (p2a, Justified) hit by Night Slash: ABILITY Justified,
 *     BOOST atk, ITEM_END, then Floette-Eternal's Symbiosis.
 *   - f639_balloon_cursed_body: Gengar (p2a, Cursed Body) hit by Bullet Punch: its roll (drawn before the pop) succeeds, the
 *     VOLATILE_START of Disable on Lucario (p1a) from Cursed Body, ITEM_END, then Floette-Eternal's Symbiosis.
 *
 * The engine fix is decision 0015 entry 5fa (c) (issue 546, PR #628); this test and the three battles are the evidence of 5eb for
 * the other holders of issue 639. The old order (the pop before the holder's other abilities, main before 5fa) puts ITEM_END and
 * the Symbiosis pass in front of the ability events and fails every case; the conformance replay of the same battles fails on
 * it too.
 */
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/formats/reg-mc/pool_tables.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/conformance_replay.h"
#include "support/fixtures.h"
#include "support/pool.h"

#define ANY 0xFFFFu

/* One expected event: kind, then position, cause, id2 and detail, each one not compared when ANY. An ABILITY event (the
 * `-ability|X|Ability|boost` line) carries the ability in id2 and no cause. */
typedef struct pop_ev {
    uint16_t kind, position, cause, id2, detail;
} pop_ev;

/* One holder's run of events: `before` (count `nb`) directly before the holder's ITEM_END of Air Balloon at `holder`, and
 * the Symbiosis ACTIVATE of `ally` directly after it when `ally` is not ANY. */
typedef struct pop_case {
    const char *battle;
    uint16_t holder, ally;
    pop_ev before[3];
    uint32_t nb;
} pop_case;

static bool matches(const duoforge_event *e, const pop_ev *w)
{
    return e->kind == w->kind && (w->position == ANY || e->position == w->position) &&
           (w->cause == ANY || e->cause == w->cause) &&
           (w->id2 == ANY || e->id2 == w->id2) && (w->detail == ANY || e->detail == w->detail);
}

/* Index of the holder's ITEM_END of Air Balloon in `buf` (exactly one), or -1. */
static int balloon_end(df_test *t, const duoforge_event_buffer *buf, uint16_t holder)
{
    int at = -1;
    uint32_t n = 0u;
    for (uint32_t i = 0u; i < buf->count; ++i) {
        const duoforge_event *e = &buf->events[i];
        if (e->kind == DUOFORGE_EVENT_ITEM_END && e->position == holder && e->id2 == 1u + DFI_ITEM_AIRBALLOON) {
            at = (int)i;
            n += 1u;
        }
    }
    DF_CHECK_EQ_U64(t, n, 1u);
    return n == 1u ? at : -1;
}

static void check_case(df_test *t, const pop_case *c, const duoforge_event_buffer *buf, uint32_t viewer)
{
    const int at = balloon_end(t, buf, c->holder);
    if (!DF_CHECK(t, at >= (int)c->nb)) {
        fprintf(stderr, "  %s viewer %u: no ITEM_END of Air Balloon at %u after its ability events\n", c->battle, viewer,
                (unsigned)c->holder);
        return;
    }
    for (uint32_t k = 0u; k < c->nb; ++k) {
        const duoforge_event *e = &buf->events[(uint32_t)at - c->nb + k];
        if (!DF_CHECK(t, matches(e, &c->before[k]))) {
            fprintf(stderr, "  %s viewer %u: event %u before the pop is kind %u at %u (cause %u, id2 %u), want kind %u at %u\n",
                    c->battle, viewer, k, e->kind, e->position, e->cause, e->id2, c->before[k].kind, c->before[k].position);
        }
    }
    if (c->ally != ANY) {
        const pop_ev sym = {DUOFORGE_EVENT_ACTIVATE, c->ally, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_SYMBIOSIS, ANY};
        if (!DF_CHECK(t, (uint32_t)at + 1u < buf->count && matches(&buf->events[at + 1], &sym))) {
            fprintf(stderr, "  %s viewer %u: no Symbiosis pass of %u right after the pop\n", c->battle, viewer,
                    (unsigned)c->ally);
        }
    }
}

/* Step 1 of `battle` (after its team step) with both viewers' events, then every case of that battle on each viewer. */
static void check_battle(df_test *t, const duoforge_context *ctx, const char *battle, const pop_case *cases, size_t n)
{
    const df_conf_battle *cb = df_conf_find(battle);
    if (!DF_CHECK(t, cb != NULL && cb->step_count >= 2u)) {
        return;
    }
    duoforge_battle *b = df_conf_replay_by_name(t, ctx, battle, 1u);
    if (b == NULL) {
        return;
    }
    const df_conf_step *st = &cb->steps[1];
    duoforge_decision_bundle bd;
    df_conf_bundle_of(st, b, &bd);
    duoforge_step_result res;
    uint32_t used = 0xFFFFFFFFu;
    static duoforge_event ev_buf[2][DUOFORGE_MAX_EVENTS];
    duoforge_event_buffer buffers[2] = {{ev_buf[0], DUOFORGE_MAX_EVENTS, 0u}, {ev_buf[1], DUOFORGE_MAX_EVENTS, 0u}};
    const duoforge_status status =
        dfi_battle_step_events_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res, buffers);
    if (DF_CHECK(t, status == DUOFORGE_OK && used == st->tape_len)) {
        DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
        for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
            for (size_t i = 0u; i < n; ++i) {
                check_case(t, &cases[i], &buffers[viewer], viewer);
            }
        }
    } else {
        fprintf(stderr, "  %s step 1: %s\n", battle, duoforge_status_name(status));
    }
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.items.air_balloon_pop_order");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, ctx != NULL)) {
        static const pop_case toxic_debris[] = {
            {"f639_balloon_toxic_debris", 2u, 3u,
             {{DUOFORGE_EVENT_ACTIVATE, 2u, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_TOXICDEBRIS, ANY},
              {DUOFORGE_EVENT_SIDE_START, ANY, ANY, ANY, 0u}},
             2u},
        };
        static const pop_case weak_armor_justified[] = {
            {"f639_balloon_weak_armor_justified", 1u, ANY,
             {{DUOFORGE_EVENT_ABILITY, 1u, ANY, 1u + DFI_ABILITY_WEAKARMOR, ANY},
              {DUOFORGE_EVENT_UNBOOST, 1u, ANY, ANY, 1u},
              {DUOFORGE_EVENT_BOOST, 1u, ANY, ANY, 4u}},
             3u},
            {"f639_balloon_weak_armor_justified", 2u, 3u,
             {{DUOFORGE_EVENT_ABILITY, 2u, ANY, 1u + DFI_ABILITY_JUSTIFIED, ANY},
              {DUOFORGE_EVENT_BOOST, 2u, ANY, ANY, 0u}},
             2u},
        };
        static const pop_case cursed_body[] = {
            {"f639_balloon_cursed_body", 2u, 3u,
             {{DUOFORGE_EVENT_VOLATILE_START, 0u, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_CURSEDBODY,
               DUOFORGE_VOLATILE_DISABLE}},
             1u},
        };
        check_battle(&t, ctx, "f639_balloon_toxic_debris", toxic_debris, sizeof toxic_debris / sizeof toxic_debris[0]);
        check_battle(&t, ctx, "f639_balloon_weak_armor_justified", weak_armor_justified,
                     sizeof weak_armor_justified / sizeof weak_armor_justified[0]);
        check_battle(&t, ctx, "f639_balloon_cursed_body", cursed_body, sizeof cursed_body / sizeof cursed_body[0]);
        duoforge_context_destroy(ctx);
    }
    return df_test_end(&t);
}
