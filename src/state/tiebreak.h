#ifndef DUOFORGE_STATE_TIEBREAK_H
#define DUOFORGE_STATE_TIEBREAK_H
/*
 * The tiebreak of the pinned reference (Battle.tiebreak, sim/battle.ts:
 * 1467-1508) as a query, with its intermediate values for the tests.
 * src/state/tiebreak.c is the only file that uses floating point; no
 * floating-point type appears here, the HP percentage is passed as the 64
 * bits of its IEEE-754 binary64 value.
 */
#include <stdint.h>

#include <duoforge/duoforge.h>

#include "state/battle_internal.h"

/* The bench of a side holds at most DUOFORGE_MAX_ROSTER - 2 members (two
 * leads when more than one is brought); its orders are the permutations of
 * up to this many. */
#define DFI_TIEBREAK_BENCH_MAX 4u
#define DFI_TIEBREAK_ORDERS_MAX 24u /* 4! */

typedef struct dfi_tiebreak_report {
    uint32_t not_fainted[DUOFORGE_SIDE_COUNT]; /* Pokemon in side.pokemon that are not fainted */
    uint32_t hp_total[DUOFORGE_SIDE_COUNT];    /* the sum of their HP over side.pokemon */
    /* The HP percentage, once for each order of the bench that side.pokemon
     * can have (the engine does not keep the reference's order, see
     * tiebreak.c), as the 64 bits of the binary64 value; entry 0 is the order of
     * brought_order. Not set for a battle that has ended. */
    uint32_t pct_count[DUOFORGE_SIDE_COUNT];
    uint64_t pct_bits[DUOFORGE_SIDE_COUNT][DFI_TIEBREAK_ORDERS_MAX];
    /* Bit r: DFI_RESULT_* r is the result under some pair of bench orders. */
    uint32_t result_mask;
    /* The result when it is the same under every pair of bench orders (the
     * battle's own at TERMINAL); 0 when the order of the bench decides. */
    uint32_t result;
} dfi_tiebreak_report;

/* The prologue of the model-facing queries, then the report. */
duoforge_status dfi_battle_tiebreak_report(const duoforge_context *ctx, const struct duoforge_battle *battle,
                                           dfi_tiebreak_report *out);

#endif
