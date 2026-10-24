/*
 * duoforge.moves.heal_block (white-box): step G8 of the content expansion, Psychic Noise's Heal Block in the POOL state tail
 * (decision 0015 section 7) and in the request. g8_heal_block: the block is 2 turns (1 left after the turn it was set in, gone
 * after the next residual) and bars the heal moves of the request while it holds; a faint clears it. g8_heal_block_pair: two
 * blocks set in one turn end in one residual. Two Heal Blocks that end in one residual at equal Speed are ordered by a
 * SPEED_TIE draw (the reference shuffles them and the two -end lines show the outcome): under 24 seeds of the engine's own
 * generator the turn is accepted with both lines and both orders occur; the recorded tie_a and tie_b battles are the two orders
 * against the reference's draws.
 *
 * Split by subject from the test of step G8 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/identity.h"
#include "state/request.h"
#include "support/check.h"
#include "support/conformance_replay.h"
#include "support/fixtures.h"
#include "support/pool.h"

static const dfi_tail_pos *tail_at(const duoforge_battle *b, uint32_t side, uint32_t slot)
{
    return &b->tail.sides[side].positions[slot];
}

static void expect_tail(df_test *t, const duoforge_battle *b, uint32_t side, uint32_t slot, uint32_t throat_chop,
                        uint32_t heal_block, const char *what)
{
    const dfi_tail_pos *p = tail_at(b, side, slot);
    /* last_move is written by every move used (step G9), so it is no part of what these battles pin down; no Encore. */
    if (!DF_CHECK(t, p->throat_chop_turns == throat_chop && p->heal_block_turns == heal_block &&
                         p->encore_slot == 0u && p->encore_turns == 0u)) {
        fprintf(stderr, "  %s: throat chop %u (want %u), heal block %u (want %u)\n", what, p->throat_chop_turns,
                throat_chop, p->heal_block_turns, heal_block);
    }
}

/* What the engine offers a slot of `player`: how many candidates use the move slot `move_slot` for the slot `slot`,
 * and how many use Struggle. */
typedef struct offered {
    uint32_t count;
    uint32_t of_move_slot;
    uint32_t struggle;
} offered;

static offered offered_for(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, uint32_t player,
                           uint32_t slot, uint32_t move_slot)
{
    static duoforge_side_choice buf[DUOFORGE_MAX_CANDIDATES];
    offered o = {0u, 0u, 0u};
    uint32_t count = 0u;
    if (!DF_CHECK(t, duoforge_battle_candidates(ctx, b, player, buf, DUOFORGE_MAX_CANDIDATES, &count) == DUOFORGE_OK)) {
        return o;
    }
    o.count = count;
    for (uint32_t i = 0u; i < count; ++i) {
        const duoforge_slot_command *c = &buf[i].slots[slot];
        if (c->kind == (uint8_t)DUOFORGE_SLOT_MOVE) {
            o.of_move_slot += c->move_slot == move_slot ? 1u : 0u;
            o.struggle += c->move_slot == DUOFORGE_MOVE_SLOT_STRUGGLE ? 1u : 0u;
        }
    }
    return o;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.moves.heal_block");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    /* Heal Block (g8_heal_block): Farigiraf's Psychic Noise hits Ceruledge on turn 1 and Milotic on turn 2. The
     * block is 2 turns: 1 left after the turn it was set in, gone after the next residual. A heal that the block
     * stops is not in the reference's events (the comparison of conformance_pool_data); here the state after
     * each turn and the domain. */
    {
        duoforge_battle *b = df_conf_replay_checked(&t, kp, "g8_heal_block", 2u);
        if (b != NULL) {
            expect_tail(&t, b, 1u, 0u, 0u, 1u, "after turn 1: Ceruledge");
            expect_tail(&t, b, 1u, 1u, 0u, 0u, "after turn 1: Milotic");
            /* Ceruledge: Bitter Blade (slot 0, a heal move) is barred; Protect and Swords Dance are not. */
            DF_CHECK_EQ_U64(&t, offered_for(&t, kp, b, 1u, 0u, 0u).of_move_slot, 0u);
            DF_CHECK(&t, offered_for(&t, kp, b, 1u, 0u, 1u).of_move_slot != 0u);
            DF_CHECK(&t, offered_for(&t, kp, b, 1u, 0u, 2u).of_move_slot != 0u);
            duoforge_battle_destroy(b);
        }
        b = df_conf_replay_checked(&t, kp, "g8_heal_block", 3u);
        if (b != NULL) {
            expect_tail(&t, b, 1u, 0u, 0u, 0u, "after turn 2: Ceruledge");
            expect_tail(&t, b, 1u, 1u, 0u, 1u, "after turn 2: Milotic");
            DF_CHECK(&t, offered_for(&t, kp, b, 1u, 0u, 0u).of_move_slot != 0u);
            duoforge_battle_destroy(b);
        }
        /* Turn 3: Ceruledge faints (its position's tail is clear, the block of Milotic ends). */
        b = df_conf_replay_checked(&t, kp, "g8_heal_block", 4u);
        if (b != NULL) {
            expect_tail(&t, b, 1u, 0u, 0u, 0u, "after turn 3: the fainted Ceruledge");
            expect_tail(&t, b, 1u, 1u, 0u, 0u, "after turn 3: Milotic");
            duoforge_battle_destroy(b);
        }
    }
    /* Two blocks that end in one residual (g8_heal_block_pair): both are set on turn 1 and counted down on turn 1
     * and turn 2, and the end lines come in the order of the holders' Speed (the comparison of
     * conformance_pool_data). */
    {
        duoforge_battle *b = df_conf_replay_checked(&t, kp, "g8_heal_block_pair", 2u);
        if (b != NULL) {
            expect_tail(&t, b, 0u, 0u, 0u, 1u, "pair, after turn 1: the fast Farigiraf");
            expect_tail(&t, b, 1u, 0u, 0u, 1u, "pair, after turn 1: the slow Farigiraf");
            duoforge_battle_destroy(b);
        }
        b = df_conf_replay_checked(&t, kp, "g8_heal_block_pair", 4u);
        if (b != NULL) {
            expect_tail(&t, b, 0u, 0u, 0u, 0u, "pair, after turn 2: the fast Farigiraf");
            expect_tail(&t, b, 1u, 0u, 0u, 0u, "pair, after turn 2: the slow Farigiraf");
            duoforge_battle_destroy(b);
        }
    }
    /* Equal Speed (g8_heal_block_tie_a: the twin Farigiraf of both sides): two Heal Blocks end in one residual, the
     * reference shuffles their order and the two -end lines show it, so the engine draws the SPEED_TIE and orders the
     * pair by it (the recorded tie_a and tie_b battles are the two orders against the reference's draws). Here: the
     * turn is accepted under every seed of the engine's own generator, always with both lines, and both orders
     * occur (0 keeps the lower position first, 1 swaps). Each side brings its Farigiraf and a Protect user. */
    {
        const df_conf_battle *cb = df_conf_find("g8_heal_block_tie_a");
        DF_CHECK(&t, cb != NULL);
        uint32_t first_p1 = 0u;
        uint32_t first_p2 = 0u;
        for (uint32_t seed = 1u; cb != NULL && seed <= 24u; ++seed) {
            duoforge_battle_setup setup;
            df_conf_build_setup(cb, &setup);
            setup.rng_initstate = seed;
            DF_CHECK(&t, setup.sides[0].members[0].species_id == setup.sides[1].members[0].species_id &&
                             setup.sides[0].members[0].nature == setup.sides[1].members[0].nature &&
                             memcmp(setup.sides[0].members[0].stat_points, setup.sides[1].members[0].stat_points, 6u) == 0);
            duoforge_battle *b = NULL;
            DF_CHECK(&t, duoforge_battle_create(kp, &setup, &b) == DUOFORGE_OK && b != NULL);
            if (b == NULL) {
                continue;
            }
            duoforge_decision_bundle bd;
            duoforge_step_result res;
            memset(&bd, 0, sizeof bd);
            bd.epoch = b->request_epoch;
            bd.response_mask = 3u;
            for (uint32_t s = 0u; s < 2u; ++s) {
                duoforge_side_choice *c = &bd.responses[s];
                c->epoch = b->request_epoch;
                c->side = (uint8_t)s;
                c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
                c->pick_count = 4u;
                c->picks[0] = 0u;
                c->picks[1] = 2u;
                c->picks[2] = 1u;
                c->picks[3] = 3u;
            }
            DF_CHECK(&t, duoforge_battle_step(kp, b, &bd, &res) == DUOFORGE_OK);
            for (uint32_t turn = 0u; turn < 2u; ++turn) {
                /* Turn 1: both Farigiraf use Psychic Noise at the foe's first position, the others Protect. Turn 2:
                 * every one Protect (move slot 1 of the Farigiraf, 0 of the others). */
                memset(&bd, 0, sizeof bd);
                bd.epoch = b->request_epoch;
                bd.response_mask = 3u;
                for (uint32_t s = 0u; s < 2u; ++s) {
                    duoforge_side_choice *c = &bd.responses[s];
                    c->epoch = b->request_epoch;
                    c->side = (uint8_t)s;
                    c->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
                    c->slots[0] = (duoforge_slot_command){
                        (uint8_t)DUOFORGE_SLOT_MOVE, (uint8_t)(turn == 0u ? 0u : 1u),
                        (uint8_t)(turn == 0u ? (s == 0u ? 2u : 0u) : DUOFORGE_TARGET_NONE), 0u, 0u, {0u, 0u, 0u}};
                    c->slots[1] = (duoforge_slot_command){(uint8_t)DUOFORGE_SLOT_MOVE, 0u, (uint8_t)DUOFORGE_TARGET_NONE,
                                                          0u, 0u, {0u, 0u, 0u}};
                }
                static duoforge_event ev_buf[2][DUOFORGE_MAX_EVENTS];
                duoforge_event_buffer buffers[2] = {{ev_buf[0], DUOFORGE_MAX_EVENTS, 0u},
                                                    {ev_buf[1], DUOFORGE_MAX_EVENTS, 0u}};
                const duoforge_status st = duoforge_battle_step_events(kp, b, &bd, &res, buffers);
                if (!DF_CHECK(&t, st == DUOFORGE_OK)) {
                    fprintf(stderr, "  equal Speed, seed %u turn %u: %s\n", seed, turn + 1u, duoforge_status_name(st));
                    break;
                }
                if (turn == 0u) {
                    expect_tail(&t, b, 0u, 0u, 0u, 1u, "equal Speed, after turn 1: p1 Farigiraf");
                    expect_tail(&t, b, 1u, 0u, 0u, 1u, "equal Speed, after turn 1: p2 Farigiraf");
                    continue;
                }
                uint32_t ends = 0u;
                uint32_t first = 0xFFu;
                for (uint32_t i = 0u; i < buffers[0].count; ++i) {
                    const duoforge_event *e = &buffers[0].events[i];
                    if (e->kind == (uint8_t)DUOFORGE_EVENT_VOLATILE_END &&
                        e->detail == (uint8_t)DUOFORGE_VOLATILE_HEAL_BLOCK) {
                        first = ends == 0u ? e->position : first;
                        ends += 1u;
                    }
                }
                DF_CHECK_EQ_U64(&t, ends, 2u);
                first_p1 += first == 0u ? 1u : 0u;
                first_p2 += first == 2u ? 1u : 0u;
                expect_tail(&t, b, 0u, 0u, 0u, 0u, "equal Speed, after turn 2: p1 Farigiraf");
                expect_tail(&t, b, 1u, 0u, 0u, 0u, "equal Speed, after turn 2: p2 Farigiraf");
            }
            duoforge_battle_destroy(b);
        }
        DF_CHECK(&t, first_p1 != 0u && first_p2 != 0u);
        DF_CHECK_EQ_U64(&t, first_p1 + first_p2, 24u);
    }
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
