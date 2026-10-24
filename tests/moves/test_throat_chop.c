/*
 * duoforge.moves.throat_chop (white-box): step G8 of the content expansion, Throat Chop in the POOL state tail (decision 0015
 * section 7) and in the request. g8_throat_chop is replayed with the reference's draws to the turns that matter: the counter is
 * 2 when set and the residual of the turn counts it down, so the next request has the sound moves barred (a holder of a sound
 * move alone gets Struggle) and the one after has them back; a Throat Chop into Protect adds nothing, a faint clears the
 * position, and the other side's slots are not touched. The reference's own lines are compared by
 * duoforge.reference.conformance_pool_data.
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
    df_test_begin(&t, "duoforge.moves.throat_chop");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    /* Throat Chop (g8_throat_chop, steps: 0 team preview, 1 turn 1, 2 turn 2, ...). Turn 1: Sneasler's Throat Chop
     * hits Salamence, Kingambit's hits Archaludon (a Choice Scarf holder with Snarl alone). The counter is 2 when set
     * and the residual of the turn counts it down, so the next request has the sound moves barred and the one after
     * has them back. */
    {
        duoforge_battle *b = df_conf_replay_checked(&t, kp, "g8_throat_chop", 1u);
        if (b != NULL) {
            expect_tail(&t, b, 1u, 0u, 0u, 0u, "before turn 1: Salamence");
            duoforge_battle_destroy(b);
        }
        b = df_conf_replay_checked(&t, kp, "g8_throat_chop", 2u);
        if (b != NULL) {
            expect_tail(&t, b, 1u, 0u, 1u, 0u, "after turn 1: Salamence");
            expect_tail(&t, b, 1u, 1u, 1u, 0u, "after turn 1: Archaludon");
            expect_tail(&t, b, 0u, 0u, 0u, 0u, "after turn 1: Sneasler");
            expect_tail(&t, b, 0u, 1u, 0u, 0u, "after turn 1: Kingambit");
            /* Salamence: Hyper Voice (slot 0) is a sound move, Protect (1) and Tailwind (2) are not. Archaludon has
             * Snarl alone: Struggle, and its switches. */
            offered a = offered_for(&t, kp, b, 1u, 0u, 0u);
            DF_CHECK_EQ_U64(&t, a.of_move_slot, 0u);
            DF_CHECK(&t, offered_for(&t, kp, b, 1u, 0u, 1u).of_move_slot != 0u);
            DF_CHECK(&t, offered_for(&t, kp, b, 1u, 0u, 2u).of_move_slot != 0u);
            offered s = offered_for(&t, kp, b, 1u, 1u, 0u);
            DF_CHECK_EQ_U64(&t, s.of_move_slot, 0u);
            DF_CHECK(&t, s.struggle != 0u);
            /* The other side's slots are not touched: Sneasler still has all of its moves. */
            DF_CHECK(&t, offered_for(&t, kp, b, 0u, 0u, 0u).of_move_slot != 0u);
            duoforge_battle_destroy(b);
        }
        b = df_conf_replay_checked(&t, kp, "g8_throat_chop", 3u);
        if (b != NULL) {
            expect_tail(&t, b, 1u, 0u, 0u, 0u, "after turn 2: Salamence");
            expect_tail(&t, b, 1u, 1u, 0u, 0u, "after turn 2: Archaludon");
            DF_CHECK(&t, offered_for(&t, kp, b, 1u, 0u, 0u).of_move_slot != 0u);
            DF_CHECK(&t, offered_for(&t, kp, b, 1u, 1u, 0u).of_move_slot != 0u);
            DF_CHECK_EQ_U64(&t, offered_for(&t, kp, b, 1u, 1u, 0u).struggle, 0u);
            duoforge_battle_destroy(b);
        }
        /* Turn 4: Sneasler's Throat Chop into Protect adds nothing, Kingambit's knocks Archaludon out. */
        b = df_conf_replay_checked(&t, kp, "g8_throat_chop", 5u);
        if (b != NULL) {
            expect_tail(&t, b, 1u, 0u, 0u, 0u, "after turn 4: Salamence");
            expect_tail(&t, b, 1u, 1u, 0u, 0u, "after turn 4: the fainted position");
            duoforge_battle_destroy(b);
        }
    }
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
