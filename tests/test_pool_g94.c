/*
 * duoforge.state.pool_g94 (white-box): step G94 (decision 0015 5cv, decision 0061): Baneful Bunker (protect_kind 3) and Last
 * Resort (the used-since-entering nibbles of the tail's reserve bytes 8 and 9, the holder's view bits 0 to 3).
 *
 * The recorded battles are compared by duoforge.reference.conformance_pool_data: g94_bunker_poison, g94_bunker_noncontact,
 * g94_bunker_already_poisoned, g94_lr_basic, g94_lr_one_unused and g94_lr_switch_reset. This file checks what those do not show:
 * the nibble accessors, the manifest's guard on the moves that can copy or call a move (their refusal by setup), and the
 * recorded handler ids.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "state/battle_internal.h"
#include "support/check.h"

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g94");

    /* The handler ids: Baneful Bunker and Last Resort after Dragon Darts, UNMODELED last (decision 0015 section 4, the generator). */
    DF_CHECK_EQ_U64(&t, DFI_SPECIAL_BANEFUL_BUNKER, DFI_SPECIAL_DRAGON_DARTS + 1u);
    DF_CHECK_EQ_U64(&t, DFI_SPECIAL_LAST_RESORT, DFI_SPECIAL_BANEFUL_BUNKER + 1u);
    DF_CHECK_EQ_U64(&t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_LAST_RESORT + 1u);
    DF_CHECK_EQ_U64(&t, DFI_PROTECT_BANEFUL_BUNKER, 3u);
    DF_CHECK_EQ_U64(&t, DFI_TAIL_PROTECT_KIND_MAX, 3u);
    DF_CHECK(&t, dfi_pool_moves[DFI_MOVE_BANEFULBUNKER].special == DFI_SPECIAL_BANEFUL_BUNKER);
    DF_CHECK(&t, dfi_pool_moves[DFI_MOVE_LASTRESORT].special == DFI_SPECIAL_LAST_RESORT);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_BANEFULBUNKER] != 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_LASTRESORT] != 0u);

    /* The guard of the moves that copy or call another move: a Last Resort holder with one of them is refused by setup,
     * because the manifest does not mark them (their used flags would follow the copy or the called move, which is not
     * modelled here). Metronome, Mirror Move, Assist, Mimic and Sketch have no row in the pool (nothing can select them). */
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_TRANSFORM] == 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_COPYCAT] == 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_SLEEPTALK] == 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_SPITE] == 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_EERIESPELL] == 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_INSTRUCT] == 0u);

    /* The nibbles: position f holds bits 4 * (f % 2) .. +3 of move_used[f / 2], bit k the move slot k. Setting one position's
     * slot leaves the others, and clearing a position clears its nibble only. */
    dfi_pool_tail tail;
    memset(&tail, 0, sizeof tail);
    for (uint32_t f = 0u; f < 4u; ++f) {
        for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
            DF_CHECK_EQ_U64(&t, dfi_move_used_bits(&tail, f), 0u);
            dfi_move_used_set(&tail, f, k);
            DF_CHECK_EQ_U64(&t, dfi_move_used_bits(&tail, f), 1u << k);
            dfi_move_used_clear(&tail, f);
            DF_CHECK_EQ_U64(&t, dfi_move_used_bits(&tail, f), 0u);
        }
    }
    dfi_move_used_set(&tail, 0u, 0u);
    dfi_move_used_set(&tail, 1u, 3u);
    dfi_move_used_set(&tail, 2u, 1u);
    dfi_move_used_set(&tail, 3u, 2u);
    DF_CHECK_EQ_U64(&t, tail.move_used[0], 0x81u); /* position 0: slot 0 (bit 0), position 1: slot 3 (bit 7) */
    DF_CHECK_EQ_U64(&t, tail.move_used[1], 0x42u); /* position 2: slot 1 (bit 1), position 3: slot 2 (bit 6) */
    dfi_move_used_clear(&tail, 1u);
    DF_CHECK_EQ_U64(&t, tail.move_used[0], 0x01u);
    DF_CHECK_EQ_U64(&t, dfi_move_used_bits(&tail, 2u), 2u);

    return df_test_end(&t);
}
