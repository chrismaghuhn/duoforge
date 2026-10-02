/*
 * duoforge_battle_tiebreak: the result of Battle.tiebreak() of the pinned
 * reference (sim/battle.ts:1467-1508) on the battle as it stands, which is
 * not modified. Training cuts off lengthy battles; a truncation is scored by
 * this winner instead of counting as a tie.
 *
 * The reference's steps, in its order, on the two sides:
 *  1. notFainted = side.pokemon.filter(!fainted).length (1472-1474); the
 *     side with the most wins (1478-1482);
 *  2. among the tied sides, the HP percentage: the sum of hp / maxhp over
 *     side.pokemon, times 100, divided by 6 (1484-1486), compared with ===;
 *     the largest wins (1490-1494);
 *  3. among those still tied, the total HP, the sum of pokemon.hp over
 *     side.pokemon (1496-1498); the largest wins (1502-1506);
 *  4. else a tie (1507).
 *
 * What side.pokemon holds after a team of 4 is brought from 6. The format
 * has "Picked Team Size = Auto", which is 4 for doubles
 * (sim/dex-formats.ts:336-342); chooseTeam makes one 'team' action per
 * brought Pokemon (sim/side.ts:1027-1029 and 1031-1095, one action for each
 * of pickedTeamSize positions), and the first of them replaces side.pokemon
 * by an empty array that the brought Pokemon are then pushed into, in the
 * order of the choice (sim/battle.ts:2750-2757). So after the picks
 * side.pokemon holds ONLY the brought four, not the other two: the count
 * and the sums run over four Pokemon, and the divisor 6 stays (an HP
 * percentage of a full team of four is 66.67). Before the picks are made
 * (the TEAM_SELECTION boundary: the 'team' actions run only when both sides
 * have chosen, sim/battle.ts:1977-2004 asks, 2750 executes) side.pokemon
 * still is the whole roster in the order of the team (sim/side.ts:241-245):
 * the count is the roster size, the sums run over all of it.
 *
 * The order of side.pokemon, which decides the sum. The array is [the
 * Pokemon of the active slots 0 and 1, the bench in some order]: the leads
 * are switched in at positions 0 and 1 (sim/battle.ts:2697, "switchIn(
 * side.pokemon[i], i)"), and every later switch-in (a voluntary switch, a
 * replacement after a faint, Parting Shot, Flip Turn, Emergency Exit) goes
 * through switchIn (sim/battle-actions.ts:62-161), which SWAPS the array
 * positions of the Pokemon that comes in and of the one that goes out
 * (battle-actions.ts:125-133): the bench Pokemon takes the slot, and the
 * Pokemon that left, fainted or not, takes the bench position the other came
 * from. So the active slots are always side.pokemon[0] and [1], and the
 * order of the bench is the history of the swaps. The engine keeps no such
 * history: brought_order is the order of the picks, is not updated by a
 * switch, and is part of the observation. Two things follow.
 *  - The two active terms cannot matter: IEEE addition is commutative, and
 *    the sum starts with them (the reference's reduce starts with the first
 *    element; 0 + x is exactly x).
 *  - The bench terms can: floating-point addition is not associative, and a
 *    search over random legal HP values found a different HP percentage in
 *    the last bit, when two bench Pokemon swap places, for about one choice
 *    of four fractions in five (tests/test_tiebreak_cases.c has such a
 *    set). That changes the winner only when the other side's percentage
 *    equals one of the values the orders give, or lies between them (equal
 *    fractions that are not exact in binary, as in a mirrored HP state).
 *    The engine does not guess then: it evaluates the reference's arithmetic
 *    for EVERY order the bench can have, and when the winner is the same
 *    under all of them (every state of the committed reference battles, and
 *    every state where the sides differ by more than a rounding error) that
 *    is the answer; when it is not, duoforge_battle_tiebreak returns
 *    DUOFORGE_E_UNSUPPORTED rather than a guess. The remedy is state that
 *    tracks side.pokemon (a state schema change, not made here).
 *
 * The arithmetic is the reference's IEEE-754 binary64: each hp / maxhp one
 * division, summed left to right in the order of side.pokemon, then * 100,
 * then / 6, and compared with ==. The file is the only one with floating
 * point (the source lint allows float and double here and nowhere else).
 * Nothing may contract, reorder or widen it: FP_CONTRACT is off here (and
 * -ffp-contract=off in CMakeLists.txt for GCC, whose pragma support does not
 * cover it), no -ffast-math anywhere, and a compiler with excess precision
 * (x87, FLT_EVAL_METHOD != 0) is refused at compile time. MSVC /fp:precise
 * is its default and x86 builds use SSE2.
 */
#include <float.h>
#include <stdbool.h>
#include <string.h>

#include "core/arith.h"
#include "state/context_internal.h"
#include "state/invariants.h"
#include "state/tiebreak.h"

#if defined(FLT_EVAL_METHOD) && FLT_EVAL_METHOD != 0
#error "tiebreak.c needs binary64 arithmetic without excess precision (FLT_EVAL_METHOD 0, SSE2 on x86)"
#endif
#if defined(__clang__)
#pragma STDC FP_CONTRACT OFF
#elif defined(_MSC_VER)
#pragma fp_contract(off)
#endif

_Static_assert(sizeof(double) == sizeof(uint64_t), "the tiebreak needs IEEE-754 binary64");
_Static_assert(DFI_TIEBREAK_BENCH_MAX == DUOFORGE_MAX_ROSTER - 2u, "the bench is the roster less two leads");
_Static_assert(DFI_RESULT_SIDE0 == DUOFORGE_RESULT_SIDE_0 && DFI_RESULT_SIDE1 == DUOFORGE_RESULT_SIDE_1 &&
                   DFI_RESULT_TIE == DUOFORGE_RESULT_TIE,
               "the public results are the internal ones");

/* The terms of one side's side.pokemon: the part whose order is known (the
 * active Pokemon in slot order, or the whole roster before the picks) and
 * the bench, whose order is not. Members are roster indices. */
typedef struct dfi_tb_order {
    uint8_t head[DUOFORGE_MAX_ROSTER];
    uint32_t head_count;
    uint8_t bench[DFI_TIEBREAK_BENCH_MAX];
    uint32_t bench_count;
} dfi_tb_order;

static uint32_t dfi_tb_factorial(uint32_t n)
{
    uint32_t f = 1u;
    for (uint32_t i = 2u; i <= n; ++i) {
        f *= i;
    }
    return f;
}

/* False when the positions do not hold what a started battle holds. */
static bool dfi_tb_side_order(const struct duoforge_battle *b, uint32_t s, dfi_tb_order *o)
{
    const dfi_side *side = &b->sides[s];
    memset(o, 0, sizeof *o);
    if (b->boundary_kind == DUOFORGE_BOUNDARY_TEAM_SELECTION) {
        /* The whole roster, in the order of the team. */
        for (uint32_t m = 0u; m < side->member_count && m < DUOFORGE_MAX_ROSTER; ++m) {
            o->head[o->head_count++] = (uint8_t)m;
        }
        return o->head_count != 0u;
    }
    uint32_t occupied = 0u; /* roster indices in a position */
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        const uint32_t occupant = side->positions[p].occupant;
        if (occupant == DFI_OCCUPANT_NONE) {
            continue;
        }
        if (occupant >= DUOFORGE_MAX_ROSTER) {
            return false;
        }
        o->head[o->head_count++] = (uint8_t)occupant;
        occupied |= 1u << occupant;
    }
    /* A started battle has its leads in their slots; a position that is empty
     * (a synthetic state: the identity primitives can vacate one) leaves its
     * Pokemon among the bench, which the reference has no state for. */
    const uint32_t brought = dfi_popcount8(side->brought_mask);
    for (uint32_t i = 0u; i < brought && i < DUOFORGE_MAX_ROSTER; ++i) {
        const uint32_t m = side->brought_order[i];
        if (m < DUOFORGE_MAX_ROSTER && ((occupied >> m) & 1u) == 0u) {
            if (o->bench_count >= DFI_TIEBREAK_BENCH_MAX) {
                return false;
            }
            o->bench[o->bench_count++] = (uint8_t)m;
        }
    }
    return o->head_count + o->bench_count == brought;
}

/* hp / maxhp of a member. */
static double dfi_tb_fraction(const dfi_side *side, uint32_t m)
{
    return (double)side->members[m].hp / (double)side->members[m].hp_max;
}

/* The HP percentage of side.pokemon in the order head, then the bench in the
 * order of permutation number `code` (0: the order of o->bench): the sum of
 * hp / maxhp from the left (0 + x is exactly x, so the first term needs no
 * special case), times 100, divided by 6. */
static double dfi_tb_percentage(const dfi_side *side, const dfi_tb_order *o, uint32_t code)
{
    double sum = 0.0;
    for (uint32_t i = 0u; i < o->head_count; ++i) {
        sum = sum + dfi_tb_fraction(side, o->head[i]);
    }
    uint8_t avail[DFI_TIEBREAK_BENCH_MAX];
    for (uint32_t i = 0u; i < o->bench_count; ++i) {
        avail[i] = o->bench[i];
    }
    uint32_t left = o->bench_count;
    uint32_t rest = code;
    for (uint32_t i = 0u; i < o->bench_count; ++i) {
        const uint32_t f = dfi_tb_factorial(left - 1u);
        const uint32_t pick = rest / f; /* < left */
        rest %= f;
        sum = sum + dfi_tb_fraction(side, avail[pick]);
        for (uint32_t j = pick; j + 1u < left; ++j) {
            avail[j] = avail[j + 1u];
        }
        left -= 1u;
    }
    return sum * 100.0 / 6.0;
}

static uint64_t dfi_tb_bits(double x)
{
    uint64_t bits;
    memcpy(&bits, &x, sizeof bits);
    return bits;
}

static double dfi_tb_from_bits(uint64_t bits)
{
    double x;
    memcpy(&x, &bits, sizeof x);
    return x;
}

/* The three steps of the reference on the two sides' quantities. */
static uint32_t dfi_tb_decide(const uint32_t not_fainted[DUOFORGE_SIDE_COUNT], double pct0, double pct1,
                              const uint32_t total[DUOFORGE_SIDE_COUNT])
{
    if (not_fainted[0] != not_fainted[1]) {
        return not_fainted[0] > not_fainted[1] ? DFI_RESULT_SIDE0 : DFI_RESULT_SIDE1;
    }
    if (pct0 != pct1) {
        return pct0 > pct1 ? DFI_RESULT_SIDE0 : DFI_RESULT_SIDE1;
    }
    if (total[0] != total[1]) {
        return total[0] > total[1] ? DFI_RESULT_SIDE0 : DFI_RESULT_SIDE1;
    }
    return DFI_RESULT_TIE;
}

duoforge_status dfi_battle_tiebreak_report(const duoforge_context *ctx, const struct duoforge_battle *battle,
                                           dfi_tiebreak_report *out)
{
    if (!dfi_context_fingerprint_matches(ctx, battle->context_fingerprint)) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    if (dfi_state_check_query(ctx, battle, NULL) != DUOFORGE_OK) { /* decision 0011 */
        return DUOFORGE_E_INVARIANT;
    }
    dfi_tiebreak_report r;
    memset(&r, 0, sizeof r);
    if (battle->boundary_kind == DUOFORGE_BOUNDARY_TERMINAL) {
        r.result = battle->result; /* its own, as the reference's ended battle (it returns false) */
        r.result_mask = 1u << r.result;
        *out = r;
        return DUOFORGE_OK;
    }
    dfi_tb_order order[DUOFORGE_SIDE_COUNT];
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const dfi_side *side = &battle->sides[s];
        if (!dfi_tb_side_order(battle, s, &order[s])) {
            return DUOFORGE_E_INVARIANT;
        }
        const dfi_tb_order *o = &order[s];
        for (uint32_t i = 0u; i < o->head_count + o->bench_count; ++i) {
            const uint32_t m = i < o->head_count ? o->head[i] : o->bench[i - o->head_count];
            if (side->members[m].hp != 0u) {
                r.not_fainted[s] += 1u;
            }
            r.hp_total[s] += side->members[m].hp;
        }
        r.pct_count[s] = dfi_tb_factorial(o->bench_count);
        for (uint32_t code = 0u; code < r.pct_count[s]; ++code) {
            r.pct_bits[s][code] = dfi_tb_bits(dfi_tb_percentage(side, o, code));
        }
    }
    for (uint32_t i = 0u; i < r.pct_count[0]; ++i) {
        for (uint32_t j = 0u; j < r.pct_count[1]; ++j) {
            const uint32_t result = dfi_tb_decide(r.not_fainted, dfi_tb_from_bits(r.pct_bits[0][i]),
                                                  dfi_tb_from_bits(r.pct_bits[1][j]), r.hp_total);
            r.result_mask |= 1u << result;
        }
    }
    /* A single bit set: the winner does not depend on the order. */
    if ((r.result_mask & (r.result_mask - 1u)) == 0u) {
        r.result = r.result_mask == (1u << DFI_RESULT_SIDE0)   ? DFI_RESULT_SIDE0
                   : r.result_mask == (1u << DFI_RESULT_SIDE1) ? DFI_RESULT_SIDE1
                                                                : DFI_RESULT_TIE;
    }
    *out = r;
    return DUOFORGE_OK;
}

duoforge_status duoforge_battle_tiebreak(const duoforge_context *ctx, const duoforge_battle *battle,
                                         uint32_t *out_result)
{
    if (ctx == NULL || battle == NULL || out_result == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    dfi_tiebreak_report r;
    const duoforge_status st = dfi_battle_tiebreak_report(ctx, battle, &r);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (r.result == 0u) {
        return DUOFORGE_E_UNSUPPORTED; /* the order of the bench in the reference's side.pokemon decides */
    }
    *out_result = r.result;
    return DUOFORGE_OK;
}
