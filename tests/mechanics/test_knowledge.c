/*
 * duoforge.state.knowledge (white-box): the Champions HP display and the
 * per-player knowledge record (docs/decisions/0006 section 6).
 *
 * Expectations come from the pinned rule (sim/pokemon.ts:2060-2073): floor
 * percent, at least 1 while alive, a colour flag only at exactly 20 and 50
 * percent. The sweep proves that the validity predicate of the invariant
 * checker accepts exactly the pairs the display can produce.
 */
#include <stdio.h>
#include <string.h>

#include "combat/events.h"
#include "state/identity.h"
#include "state/knowledge.h"
#include "support/check.h"
#include "support/fixtures.h"

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.knowledge");

    /* Hand-derived values. */
    {
        static const struct {
            uint32_t hp;
            uint32_t hp_max;
            uint32_t percent;
            uint32_t flag;
        } cases[] = {
            {0, 120, 0, DUOFORGE_HP_FLAG_NONE},     {1, 201, 1, DUOFORGE_HP_FLAG_NONE},
            {1, 65535, 1, DUOFORGE_HP_FLAG_NONE},   {2, 201, 1, DUOFORGE_HP_FLAG_NONE},
            {24, 120, 20, DUOFORGE_HP_FLAG_RED},    {25, 120, 20, DUOFORGE_HP_FLAG_YELLOW},
            {41, 201, 20, DUOFORGE_HP_FLAG_YELLOW}, {40, 201, 19, DUOFORGE_HP_FLAG_NONE},
            {65, 130, 50, DUOFORGE_HP_FLAG_YELLOW}, {66, 130, 50, DUOFORGE_HP_FLAG_GREEN},
            {101, 201, 50, DUOFORGE_HP_FLAG_GREEN}, {100, 201, 49, DUOFORGE_HP_FLAG_NONE},
            {200, 201, 99, DUOFORGE_HP_FLAG_NONE},  {201, 201, 100, DUOFORGE_HP_FLAG_NONE},
            {65535, 65535, 100, DUOFORGE_HP_FLAG_NONE},
        };
        for (unsigned i = 0; i < sizeof cases / sizeof cases[0]; ++i) {
            uint8_t percent = 0xEEu;
            uint8_t flag = 0xEEu;
            dfi_hp_display(cases[i].hp, cases[i].hp_max, &percent, &flag);
            if (!DF_CHECK(&t, percent == cases[i].percent && flag == cases[i].flag)) {
                fprintf(stderr, "  %u/%u -> %u flag %u\n", (unsigned)cases[i].hp, (unsigned)cases[i].hp_max,
                        (unsigned)percent, (unsigned)flag);
            }
        }
        /* Corrupt input stays defined: no division by zero, never above 100. */
        uint8_t percent = 0xEEu;
        uint8_t flag = 0xEEu;
        dfi_hp_display(5u, 0u, &percent, &flag);
        DF_CHECK(&t, percent == 0u && flag == DUOFORGE_HP_FLAG_NONE);
        dfi_hp_display(65535u, 1u, &percent, &flag);
        DF_CHECK(&t, percent == 100u && flag == DUOFORGE_HP_FLAG_NONE);
    }

    /* Sweep: every (hp, hp_max) with hp_max <= 1200 and a few large maxima.
     * The display is monotone in hp, 0 exactly for hp 0, and the set of
     * produced pairs equals the set the validity predicate accepts. */
    {
        uint8_t produced[256][4];
        memset(produced, 0, sizeof produced);
        unsigned violations = 0;
        static const uint32_t maxima[] = {4999u, 10000u, 32767u, 65535u};
        for (uint32_t pass = 1u; pass <= 1200u + sizeof maxima / sizeof maxima[0]; ++pass) {
            const uint32_t hp_max = pass <= 1200u ? pass : maxima[pass - 1201u];
            uint32_t previous = 0u;
            for (uint32_t hp = 0u; hp <= hp_max; ++hp) {
                uint8_t percent = 0xEEu;
                uint8_t flag = 0xEEu;
                dfi_hp_display(hp, hp_max, &percent, &flag);
                violations += (percent == 0u) != (hp == 0u) ? 1u : 0u;
                violations += percent < previous || percent > 100u || flag > 3u ? 1u : 0u;
                violations += !dfi_hp_display_valid(percent, flag) ? 1u : 0u;
                violations += (hp == hp_max) != (percent == 100u) ? 1u : 0u;
                previous = percent;
                if (percent <= 100u && flag <= 3u) {
                    produced[percent][flag] = 1u;
                }
            }
        }
        DF_CHECK_EQ_U64(&t, violations, 0u);
        unsigned accepted = 0;
        unsigned mismatches = 0;
        for (uint32_t percent = 0u; percent < 256u; ++percent) {
            for (uint32_t flag = 0u; flag < 256u; ++flag) {
                const bool valid = dfi_hp_display_valid(percent, flag);
                const bool made = flag < 4u && produced[percent][flag] != 0u;
                accepted += valid ? 1u : 0u;
                mismatches += valid != made ? 1u : 0u;
            }
        }
        DF_CHECK_EQ_U64(&t, mismatches, 0u);
        DF_CHECK_EQ_U64(&t, accepted, 103u); /* 99 plain percentages and two flags each at 20 and 50 */
    }

    /* The fold (decision 0007 section 6), the only writer of the knowledge
     * in a step: each player learns from the events about opposing
     * positions, as its own projection shows them. Damage and heal show the
     * HP display; a move is one use of its slot (saturating), not on a
     * locked turn and not for a move on no slot (Struggle); an ended item
     * and a Mega Evolution are facts; a switch makes the member seen with
     * its display, and later lines of that slot are about it; events about
     * the own side and corrupt positions change nothing. */
    {
        duoforge_context *c1 = df_make_context(&df_config_c1);
        duoforge_battle *b = df_make_f1(c1); /* s0 leads 2 and 0, s1 leads 1 and 3 */
        duoforge_battle *before = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, b, &before) == DUOFORGE_OK);
        static dfi_events ev;
        ev.count = 0u;
        ev.overflow = false;
        uint8_t pct = 0u;
        uint8_t flag = 0u;
        b->sides[0].members[2].hp = 60u; /* s0a: 50 percent of 120, yellow */
        duoforge_event e = dfi_event_make(DUOFORGE_EVENT_DAMAGE, 0u);
        dfi_event_set_hp(&e, &b->sides[0].members[2]);
        dfi_events_push(&ev, &e);
        b->sides[0].members[0].hp = 30u; /* s0b, roster 0 */
        e = dfi_event_make(DUOFORGE_EVENT_HEAL, 1u);
        dfi_event_set_hp(&e, &b->sides[0].members[0]);
        dfi_events_push(&ev, &e);
        e = dfi_event_make(DUOFORGE_EVENT_MOVE, 3u); /* s1b, roster 3: its first move */
        e.id = b->sides[1].members[3].moves[0].move_id;
        dfi_events_push(&ev, &e);
        e.flags = (uint8_t)DUOFORGE_EVENT_FLAG_LOCKED; /* the same move locked: no use */
        dfi_events_push(&ev, &e);
        e.flags = 0u;
        e.id = 0xFFFFu; /* a move on no slot (Struggle): no use */
        dfi_events_push(&ev, &e);
        b->sides[0].knowledge[3].moves_used[1] = 255u; /* saturated */
        e.id = b->sides[1].members[3].moves[1].move_id;
        dfi_events_push(&ev, &e);
        e = dfi_event_make(DUOFORGE_EVENT_ITEM_END, 2u); /* s1a, roster 1 */
        dfi_events_push(&ev, &e);
        e = dfi_event_make(DUOFORGE_EVENT_MEGA, 3u); /* s1b, roster 3 */
        dfi_events_push(&ev, &e);
        e = dfi_event_make(DUOFORGE_EVENT_DAMAGE, 7u); /* corrupt position: skipped */
        e.hp = 1u;
        e.hp_max = 1u;
        e.hp_kind = (uint8_t)DUOFORGE_HP_EXACT;
        dfi_events_push(&ev, &e);
        b->sides[0].members[1].hp = 24u; /* roster 1 enters s0b */
        b->sides[0].positions[1].occupant = 1u;
        e = dfi_event_switch(b, 1u);
        dfi_events_push(&ev, &e);
        b->sides[0].members[1].hp = 12u; /* then s0b is hit: it is roster 1 now */
        e = dfi_event_make(DUOFORGE_EVENT_DAMAGE, 1u);
        dfi_event_set_hp(&e, &b->sides[0].members[1]);
        dfi_events_push(&ev, &e);
        DF_CHECK(&t, dfi_events_fold_knowledge(before, b, &ev, 0u));
        DF_CHECK(&t, b->sides[1].knowledge[2].hp_percent == 50u &&
                         b->sides[1].knowledge[2].hp_flag == DUOFORGE_HP_FLAG_YELLOW);
        dfi_hp_display(30u, b->sides[0].members[0].hp_max, &pct, &flag);
        DF_CHECK(&t, b->sides[1].knowledge[0].hp_percent == pct && b->sides[1].knowledge[0].hp_flag == flag);
        DF_CHECK(&t, b->sides[0].knowledge[3].moves_used[0] == 1u && b->sides[0].knowledge[3].moves_used[1] == 255u &&
                         b->sides[0].knowledge[3].moves_used[2] == 0u && b->sides[0].knowledge[3].moves_used[3] == 0u);
        DF_CHECK(&t, b->sides[0].knowledge[1].revealed == DFI_REVEALED_ITEM_CONSUMED &&
                         b->sides[0].knowledge[3].revealed == DFI_REVEALED_MEGA);
        DF_CHECK_EQ_U64(&t, b->sides[1].seen_mask, 0x07u); /* roster 1 seen now */
        dfi_hp_display(12u, b->sides[0].members[1].hp_max, &pct, &flag);
        DF_CHECK(&t, pct < 100u && b->sides[1].knowledge[1].hp_percent == pct && b->sides[1].knowledge[1].hp_flag == flag);
        DF_CHECK_EQ_U64(&t, b->sides[0].seen_mask, 0x0Au); /* the own side's events teach side 0 nothing */
        DF_CHECK(&t, b->sides[0].knowledge[2].hp_percent == 0u && b->sides[1].knowledge[3].moves_used[0] == 0u);
        DF_CHECK(&t, b->sides[0].knowledge[1].hp_percent == before->sides[0].knowledge[1].hp_percent &&
                         b->sides[1].knowledge[2].revealed == 0u); /* not from own lines in the foe's slot */
        /* Lines before `first` only move the occupants. */
        duoforge_battle *again = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, before, &again) == DUOFORGE_OK);
        DF_CHECK(&t, dfi_events_fold_knowledge(before, again, &ev, ev.count - 1u));
        DF_CHECK(&t, again->sides[1].knowledge[1].hp_percent == pct && again->sides[1].seen_mask == 0x05u &&
                         again->sides[1].knowledge[2].hp_percent == before->sides[1].knowledge[2].hp_percent);
        /* A line that shows HP without a display is refused, never stored as 0. */
        ev.count = 0u;
        e = dfi_event_make(DUOFORGE_EVENT_DAMAGE, 2u); /* about s1a, seen by player 0: no HP on it */
        dfi_events_push(&ev, &e);
        DF_CHECK(&t, !dfi_events_fold_knowledge(before, again, &ev, 0u));
        duoforge_battle_destroy(again);
        duoforge_battle_destroy(before);
        duoforge_battle_destroy(b);
        duoforge_context_destroy(c1);
    }

    /* A SYNTHETIC team step through the public API: each player gets the
     * leads' [switch] lines in position order (the opponent's HP as the
     * percent display) and [turn] 1, and has seen the opposing leads. */
    {
        duoforge_context *c1 = df_make_context(&df_config_c1);
        duoforge_battle *b = df_make_g1(c1);
        static duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];
        static duoforge_event ev2[2][DUOFORGE_MAX_EVENTS];
        duoforge_decision_bundle bd;
        memset(&bd, 0, sizeof bd);
        bd.epoch = b->request_epoch;
        bd.response_mask = b->request_mask;
        for (uint32_t s = 0; s < 2u; ++s) {
            uint32_t n = 0;
            DF_CHECK(&t, duoforge_battle_candidates(c1, b, s, cands, DUOFORGE_MAX_CANDIDATES, &n) == DUOFORGE_OK &&
                             n > 0u);
            bd.responses[s] = cands[0];
        }
        duoforge_event_buffer buffers[2] = {{ev2[0], DUOFORGE_MAX_EVENTS, 0u}, {ev2[1], DUOFORGE_MAX_EVENTS, 0u}};
        duoforge_step_result res;
        DF_CHECK(&t, duoforge_battle_step_events(c1, b, &bd, &res, buffers) == DUOFORGE_OK);
        DF_CHECK(&t, buffers[0].count == 5u && buffers[1].count == 5u);
        for (uint32_t p = 0; p < 2u && buffers[p].count == 5u; ++p) {
            for (uint32_t i = 0; i < 4u; ++i) {
                const duoforge_event *x = &ev2[p][i];
                const bool own = i / 2u == p;
                DF_CHECK(&t, x->kind == DUOFORGE_EVENT_SWITCH && x->position == i &&
                                 x->id == b->sides[i / 2u].positions[i % 2u].occupant &&
                                 x->hp_kind == (own ? DUOFORGE_HP_EXACT : DUOFORGE_HP_PERCENT));
            }
            DF_CHECK(&t, ev2[p][4].kind == DUOFORGE_EVENT_TURN && ev2[p][4].id == 1u);
        }
        for (uint32_t s = 0; s < 2u; ++s) {
            const uint32_t foe = 1u - s;
            const uint32_t leads = (1u << b->sides[foe].positions[0].occupant) | (1u << b->sides[foe].positions[1].occupant);
            DF_CHECK_EQ_U64(&t, b->sides[s].seen_mask, leads);
        }
        duoforge_battle_destroy(b);
        duoforge_context_destroy(c1);
    }

    /* The fixtures' record (states built without a step): written on entry
     * and on refresh, kept on leaving, only for active members, only in the
     * opponent's knowledge. */
    {
        duoforge_context *c1 = df_make_context(&df_config_c1);
        duoforge_battle *b = df_make_f1(c1); /* s0 leads 2 and 0, s1 leads 1 and 3 */
        b->sides[0].members[2].hp = 60u;  /* active: 50 percent of 120, yellow */
        b->sides[0].members[1].hp = 11u;  /* bench */
        b->sides[1].members[3].hp = 0u;   /* active, fainted */
        df_knowledge_refresh_active(b);
        DF_CHECK(&t, b->sides[1].knowledge[2].hp_percent == 50u &&
                         b->sides[1].knowledge[2].hp_flag == DUOFORGE_HP_FLAG_YELLOW);
        DF_CHECK(&t, b->sides[1].knowledge[1].hp_percent == 0u && b->sides[1].knowledge[1].hp_flag == 0u);
        DF_CHECK(&t, b->sides[0].knowledge[3].hp_percent == 0u && b->sides[0].knowledge[1].hp_percent == 100u);
        DF_CHECK(&t, b->sides[0].knowledge[2].hp_percent == 0u); /* s1 member 2 was never seen */
        DF_CHECK(&t, duoforge_battle_check(c1, b) == DUOFORGE_OK);
        /* A corrupt occupant is skipped, not used as an index. */
        b->sides[0].positions[1].occupant = 0xFEu;
        df_knowledge_refresh_active(b);
        DF_CHECK(&t, duoforge_battle_check(c1, b) == DUOFORGE_E_INVARIANT);
        duoforge_battle_destroy(b);
        duoforge_context_destroy(c1);
    }

    return df_test_end(&t);
}
