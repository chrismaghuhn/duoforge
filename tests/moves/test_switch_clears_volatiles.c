/*
 * duoforge.moves.switch_clears_volatiles (white-box): step G8 of the content expansion, a switch ends every volatile of the
 * POOL state tail (decision 0015 section 7): dfi_vacate, and dfi_place, which clears the same way before it overwrites an
 * occupant, clear the position's five tail fields and the leaving member's Soak type; the other position, the other members'
 * Soak types and a position of the other side are not touched.
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

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.moves.switch_clears_volatiles");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    /* A switch (dfi_vacate, then dfi_place, which clears the same way before it overwrites an occupant) ends every
     * volatile: the position's five tail fields and the leaving member's Soak type are cleared; the other position and
     * the other members' Soak types are not. */
    {
        duoforge_battle *b = df_conf_replay_checked(&t, kp, "g8_heal_block", 2u);
        if (b != NULL) {
            const uint32_t occupant = b->sides[1].positions[0].occupant;
            const uint32_t other = b->sides[1].positions[1].occupant;
            DF_CHECK(&t, occupant < DUOFORGE_MAX_ROSTER && other < DUOFORGE_MAX_ROSTER && occupant != other);
            b->tail.sides[1].positions[0] = (dfi_tail_pos){.last_move = 1u, .encore_slot = 2u, .encore_turns = 3u, .throat_chop_turns = 1u, .heal_block_turns = 1u};
            b->tail.sides[1].positions[1] = (dfi_tail_pos){.last_move = 2u, .throat_chop_turns = 2u, .heal_block_turns = 1u};
            b->tail.sides[1].soak_type[occupant] = 5u;
            b->tail.sides[1].soak_type[other] = 7u;
            b->tail.sides[0].positions[0].heal_block_turns = 1u;
            DF_CHECK(&t, dfi_vacate(b, (dfi_position_id){1u, 0u}) == DUOFORGE_OK);
            expect_tail(&t, b, 1u, 0u, 0u, 0u, "vacated position");
            DF_CHECK_EQ_U64(&t, b->tail.sides[1].soak_type[occupant], 0u);
            DF_CHECK_EQ_U64(&t, b->tail.sides[1].soak_type[other], 7u);
            DF_CHECK_EQ_U64(&t, b->tail.sides[1].positions[1].throat_chop_turns, 2u);
            DF_CHECK_EQ_U64(&t, b->tail.sides[1].positions[1].heal_block_turns, 1u);
            DF_CHECK_EQ_U64(&t, b->tail.sides[0].positions[0].heal_block_turns, 1u);
            duoforge_battle_destroy(b);
        }
    }
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
