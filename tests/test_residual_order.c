/*
 * duoforge.combat.residual_order (white-box): the argument of src/combat/residual_order.h, checked by brute force.
 *
 * The engine does not store the order in which a Pokemon's volatiles were added, and builds their residual handlers in
 * one fixed order. dfi_residual_order_ambiguous says when a different order could change the outcome; the header's
 * claim is that for every list it does not flag, any order of any Pokemon's volatile handlers gives the same result.
 * The result that matters is the order in which the callbacks (the handlers that act, and the groups that draw) come
 * out of Battle.speedSort, and the draws that the sort takes: the group sizes of a selection sort do not depend on the
 * list's order, so the draws are the same sequence, and the test feeds every arrangement the same values.
 *
 * The model below is the reference's speedSort (sim/battle.ts:429-460) over entries with the engine's sort keys: a
 * selection sort that gathers the next group of equal entries in list order, swaps them to the front (the swaps
 * displace the entries in the way, which is why the list's order matters at all) and shuffles the group with one draw
 * per step (PRNG.shuffle: step i takes a value in [i, count)).
 *  - random lists (the shapes the engine builds: per Pokemon a status, volatile handlers, an item, Grassy Terrain),
 *    with speeds chosen for ties: not flagged => every order of the volatiles gives the same callback sequence;
 *  - flagged lists are not vacuous: the brute force finds a list that is flagged and whose outcome does change;
 *  - fixed examples: Encore and Throat Chop on one Pokemon with Leftovers tied (an order before the volatiles: fine),
 *    Encore tied between two Pokemon that each hold two volatiles of different keys (flagged), one key only (fine).
 */
#include <stdio.h>
#include <string.h>

#include "combat/residual_order.h"
#include "support/check.h"

#define MAX_LIST 64u
#define MAX_MONS 4u
#define MAX_VOL 4u

typedef struct rng {
    uint64_t s;
} rng;

static uint32_t rng_next(rng *g)
{
    g->s = g->s * 6364136223846793005ull + 1442695040888963407ull;
    return (uint32_t)(g->s >> 33);
}

/* The reference's selection sort with shuffles. The draws are taken from `values` in order. */
static uint32_t g_ranges[MAX_LIST];
static uint32_t g_draws;

static void model_sort(dfi_residual_entry *list, uint32_t n, const uint32_t *values)
{
    uint32_t sorted = 0u;
    uint32_t used = 0u;
    g_draws = 0u;
    while (sorted + 1u < n) {
        uint32_t next[MAX_LIST] = {0};
        uint32_t count = 1u;
        next[0] = sorted;
        for (uint32_t i = sorted + 1u; i < n; ++i) {
            const uint32_t c = dfi_residual_compare(&list[next[0]], &list[i]);
            if (c == 2u) {
                next[0] = i;
                count = 1u;
            } else if (c == 1u) {
                next[count] = i;
                count += 1u;
            }
        }
        for (uint32_t i = 0u; i < count; ++i) {
            if (next[i] != sorted + i) {
                const dfi_residual_entry e = list[sorted + i];
                list[sorted + i] = list[next[i]];
                list[next[i]] = e;
            }
        }
        if (list[sorted].callback) {
            for (uint32_t start = sorted; start + 1u < sorted + count; ++start) {
                const uint32_t lo = start - sorted;
                g_ranges[used] = count - lo;
                const uint32_t v = lo + values[used++] % (count - lo);
                g_draws = used;
                if (sorted + v != start) {
                    const dfi_residual_entry e = list[start];
                    list[start] = list[sorted + v];
                    list[sorted + v] = e;
                }
            }
        }
        sorted += count;
    }
}

/* The callbacks of a sorted list in order, as 32-bit codes (kind, position, sort key). */
static uint32_t outcome(const dfi_residual_entry *list, uint32_t n, uint32_t *out)
{
    uint32_t k = 0u;
    for (uint32_t i = 0u; i < n; ++i) {
        if (list[i].callback) {
            out[k++] = list[i].kind * 1000u + list[i].flat * 100u + list[i].order % 100u;
        }
    }
    return k;
}

typedef struct shape {
    dfi_residual_entry list[MAX_LIST];
    uint32_t n;
    uint32_t vol_start[MAX_MONS]; /* the volatile region of each Pokemon: [start, start + len) */
    uint32_t vol_len[MAX_MONS];
    uint32_t mons;
} shape;

static void push(shape *s, uint32_t kind, uint32_t flat, uint32_t order, uint32_t speed, uint32_t sub, bool cb)
{
    s->list[s->n++] = (dfi_residual_entry){kind, flat, order, speed, sub, cb};
}

/* A list the way dfi_residual_events builds it. */
static void random_shape(rng *g, shape *s, bool grassy, bool weather)
{
    memset(s, 0, sizeof *s);
    if (weather) {
        push(s, DFI_RES_WEATHER, 0u, 1u, 0u, 5u, true);
    }
    s->mons = 1u + rng_next(g) % MAX_MONS;
    static const uint32_t speeds[3] = {80u, 120u, 120u}; /* ties are common */
    for (uint32_t flat = 0u; flat < s->mons; ++flat) {
        const uint32_t speed = speeds[rng_next(g) % 3u];
        const uint32_t status = rng_next(g) % 4u;
        if (status == 1u) {
            push(s, DFI_RES_BURN, flat, 10u, speed, 0u, true);
        } else if (status == 2u) {
            push(s, DFI_RES_POISON, flat, 9u, speed, 0u, true);
        }
        s->vol_start[flat] = s->n;
        const uint32_t counters = rng_next(g) % 3u;
        for (uint32_t k = 0u; k < counters; ++k) {
            push(s, DFI_RES_DURATION, flat, DFI_RES_NO_ORDER, speed, 2u, false);
        }
        if (rng_next(g) % 3u == 0u) {
            push(s, DFI_RES_DURATION, flat, 20u, speed, 2u, false);
        }
        if (rng_next(g) % 3u == 0u) {
            push(s, DFI_RES_DURATION, flat, 22u, speed, 2u, false);
        }
        if (rng_next(g) % 3u == 0u) {
            push(s, DFI_RES_ENCORE, flat, 16u, speed, 2u, true);
        }
        if (rng_next(g) % 4u == 0u) {
            push(s, DFI_RES_PERISH, flat, 24u, speed, 2u, true); /* step G26 */
        }
        s->vol_len[flat] = s->n - s->vol_start[flat];
        const uint32_t item = rng_next(g) % 3u;
        if (item == 1u) {
            push(s, DFI_RES_LEFTOVERS, flat, 5u, speed, 4u, true);
        } else if (item == 2u) {
            push(s, DFI_RES_WHITE_HERB, flat, 29u, speed, 8u, true);
        }
        if (grassy) {
            push(s, DFI_RES_GRASSY, flat, 5u, speed, 2u, true);
        }
    }
}

/* Reorders every Pokemon's volatile region randomly (Fisher-Yates over the region). */
static void scramble(rng *g, shape *s)
{
    for (uint32_t m = 0u; m < s->mons; ++m) {
        dfi_residual_entry *v = &s->list[s->vol_start[m]];
        for (uint32_t i = s->vol_len[m]; i > 1u; --i) {
            const uint32_t j = rng_next(g) % i;
            const dfi_residual_entry e = v[i - 1u];
            v[i - 1u] = v[j];
            v[j] = e;
        }
    }
}

static bool same_outcome(const shape *a, const shape *b, const uint32_t *values)
{
    dfi_residual_entry la[MAX_LIST];
    dfi_residual_entry lb[MAX_LIST];
    memcpy(la, a->list, sizeof(dfi_residual_entry) * a->n);
    memcpy(lb, b->list, sizeof(dfi_residual_entry) * b->n);
    model_sort(la, a->n, values);
    model_sort(lb, b->n, values);
    uint32_t oa[MAX_LIST];
    uint32_t ob[MAX_LIST];
    const uint32_t na = outcome(la, a->n, oa);
    const uint32_t nb = outcome(lb, b->n, ob);
    return na == nb && memcmp(oa, ob, sizeof(uint32_t) * na) == 0;
}

/* Every value of every draw (an odometer over the ranges that the model recorded for these values) and a number of
 * random orders of the volatiles: does the outcome ever differ from the list as it is? Returns false when there are too
 * many draws to try all values. */
/* The number of orders of the volatiles of the Pokemon with two keys or more (equal entries counted once), saturating. */
static uint32_t arrangements(const shape *s)
{
    uint32_t total = 1u;
    for (uint32_t m = 0u; m < s->mons; ++m) {
        const dfi_residual_entry *v = &s->list[s->vol_start[m]];
        const uint32_t len = s->vol_len[m];
        bool distinct = false;
        for (uint32_t i = 1u; i < len; ++i) {
            distinct = distinct || v[i].order != v[0].order || v[i].sub_order != v[0].sub_order;
        }
        if (!distinct) {
            continue;
        }
        uint32_t perms = 1u;
        for (uint32_t i = 2u; i <= len; ++i) {
            perms *= i;
        }
        for (uint32_t i = 0u; i < len; ++i) { /* divide by the factorial of each group of equal entries */
            uint32_t same = 0u;
            for (uint32_t j = 0u; j <= i; ++j) {
                same += (v[j].order == v[i].order && v[j].sub_order == v[i].sub_order) ? 1u : 0u;
            }
            perms /= same;
        }
        total *= perms;
        if (total > 100000u) {
            return 100000u;
        }
    }
    return total;
}

static bool differs_somewhere(rng *g, const shape *base, bool *tried_all)
{
    uint32_t values[MAX_LIST] = {0};
    dfi_residual_entry probe[MAX_LIST];
    memcpy(probe, base->list, sizeof(dfi_residual_entry) * base->n);
    model_sort(probe, base->n, values);
    uint32_t ranges[MAX_LIST];
    const uint32_t draws = g_draws;
    uint32_t combos = 1u;
    for (uint32_t k = 0u; k < draws; ++k) {
        ranges[k] = g_ranges[k];
        combos *= ranges[k];
        if (combos > 4096u) {
            *tried_all = false;
            return false;
        }
    }
    *tried_all = arrangements(base) <= 1024u; /* more orders than that and the engine's test gives up (refuses) */
    for (uint32_t rep = 0u; rep < 60u; ++rep) {
        shape other = *base;
        scramble(g, &other);
        memset(values, 0, sizeof values);
        for (uint32_t c = 0u; c < combos; ++c) {
            if (!same_outcome(base, &other, values)) {
                return true;
            }
            for (uint32_t k = 0u; k < draws; ++k) {
                values[k] += 1u;
                if (values[k] < ranges[k]) {
                    break;
                }
                values[k] = 0u;
            }
        }
    }
    return false;
}

static void test_random_lists(df_test *t)
{
    rng g = {0x5EEDC0DEull};
    unsigned long may_matter = 0u;
    unsigned long refused = 0u;
    unsigned long cleared_by_exact = 0u; /* the cheap test cannot clear them, the exact one does */
    unsigned long refused_but_no_difference = 0u;
    unsigned long unrefused_multi = 0u; /* unrefused lists with a Pokemon that has volatiles of two keys */
    for (uint32_t trial = 0u; trial < 40000u; ++trial) {
        shape base;
        random_shape(&g, &base, rng_next(&g) % 4u == 0u, rng_next(&g) % 4u == 0u);
        const bool may = dfi_residual_order_may_matter(base.list, base.n);
        const bool amb = dfi_residual_order_ambiguous(base.list, base.n);
        DF_CHECK(t, !amb || may); /* the exact test only narrows the cheap one */
        bool multi = false;
        for (uint32_t m = 0u; m < base.mons; ++m) {
            for (uint32_t i = 1u; i < base.vol_len[m]; ++i) {
                const dfi_residual_entry *a = &base.list[base.vol_start[m]];
                multi = multi || a[i].order != a[0].order || a[i].sub_order != a[0].sub_order;
            }
        }
        may_matter += may ? 1u : 0u;
        refused += amb ? 1u : 0u;
        cleared_by_exact += (may && !amb) ? 1u : 0u;
        unrefused_multi += (!amb && multi) ? 1u : 0u;
        bool tried_all = false;
        const bool differs = differs_somewhere(&g, &base, &tried_all);
        if (!amb && differs) {
            /* a list that is not refused and whose outcome depends on the order: the argument is wrong */
            DF_CHECK(t, !differs);
            return;
        }
        if (amb && tried_all && !differs) {
            refused_but_no_difference += 1u; /* only the random orders missed it, or the exact test is too careful */
        }
    }
    /* The brute force is not vacuous: lists that the cheap test flags exist, the exact test clears some of them and
     * refuses others, and unrefused lists with volatiles of two keys (which the argument says are fine) are many. */
    DF_CHECK(t, may_matter > 100u);
    DF_CHECK(t, refused > 10u);
    DF_CHECK(t, cleared_by_exact > 10u);
    DF_CHECK(t, unrefused_multi > 100u);
    /* what is refused really changes an outcome: found by 60 random orders of the volatiles and every draw */
    DF_CHECK(t, refused_but_no_difference * 100u <= refused);
}

static dfi_residual_entry ent(uint32_t kind, uint32_t flat, uint32_t order, uint32_t sub, bool cb)
{
    return (dfi_residual_entry){kind, flat, order, 100u, sub, cb};
}

#define COUNTER(f) ent(DFI_RES_DURATION, (f), DFI_RES_NO_ORDER, 2u, false)
#define HEAL(f) ent(DFI_RES_DURATION, (f), 20u, 2u, false)
#define CHOP(f) ent(DFI_RES_DURATION, (f), 22u, 2u, false)
#define ENCORE(f) ent(DFI_RES_ENCORE, (f), 16u, 2u, true)
#define PERISH(f) ent(DFI_RES_PERISH, (f), 24u, 2u, true)
#define LEFT(f) ent(DFI_RES_LEFTOVERS, (f), 5u, 4u, true)
#define HERB(f) ent(DFI_RES_WHITE_HERB, (f), 29u, 8u, true)

static void test_examples(df_test *t)
{
    /* Encore and Throat Chop on one Pokemon and Leftovers tied with another's: Leftovers is order 5, before both
     * volatiles: the cheap test clears it. */
    {
        const dfi_residual_entry l[] = {ENCORE(0), CHOP(0), LEFT(0), LEFT(1)};
        DF_CHECK(t, !dfi_residual_order_may_matter(l, 4u));
        DF_CHECK(t, !dfi_residual_order_ambiguous(l, 4u));
    }
    /* Duration counters have one key: their order shows nowhere, even with a White Herb tie after them. */
    {
        const dfi_residual_entry l[] = {COUNTER(0), COUNTER(0), HERB(0), HERB(1)};
        DF_CHECK(t, !dfi_residual_order_may_matter(l, 4u));
    }
    /* Two keys but no tie: nothing draws. */
    {
        const dfi_residual_entry l[] = {ENCORE(0), HEAL(0), HERB(0), LEFT(1)};
        DF_CHECK(t, !dfi_residual_order_ambiguous(l, 4u));
    }
    /* Encore tied between two Pokemon that each hold one key only. */
    {
        const dfi_residual_entry l[] = {ENCORE(0), ENCORE(1)};
        DF_CHECK(t, !dfi_residual_order_ambiguous(l, 2u));
    }
    /* Encore tied between two Pokemon, one of which also has two Protect-style counters, and Leftovers tied before them
     * (the AWS case fz_9630002_84 of 2026-10-03): the cheap test cannot clear it, the exact one does (the Leftovers
     * rounds put the first Pokemon's Encore after the second's whichever way the second's volatiles are listed). */
    {
        const dfi_residual_entry l[] = {ENCORE(1), LEFT(1), COUNTER(2), COUNTER(2), ENCORE(2), LEFT(2)};
        DF_CHECK(t, dfi_residual_order_may_matter(l, 6u));
        DF_CHECK(t, !dfi_residual_order_ambiguous(l, 6u));
    }
    /* Two White Herbs tied after a Pokemon with Throat Chop and Encore: the selection sort moves the Encore and the Chop
     * to the front past the herbs, and which herb comes first depends on the order of the two volatiles. Refused. */
    {
        const dfi_residual_entry l[] = {HERB(0), HERB(1), CHOP(2), ENCORE(2)};
        DF_CHECK(t, dfi_residual_order_may_matter(l, 4u));
        DF_CHECK(t, dfi_residual_order_ambiguous(l, 4u));
        const dfi_residual_entry other[] = {HERB(0), HERB(1), ENCORE(2), CHOP(2)};
        DF_CHECK(t, dfi_residual_order_ambiguous(other, 4u));
    }
    /* Encore tied between two Pokemon that each hold Encore and Throat Chop, one with Heal Block between: no group
     * before them moves anything, the first Pokemon's Encore stays before the second's. */
    {
        const dfi_residual_entry l[] = {ENCORE(0), CHOP(0), ENCORE(1), HEAL(1), CHOP(1)};
        DF_CHECK(t, dfi_residual_order_may_matter(l, 5u));
        DF_CHECK(t, !dfi_residual_order_ambiguous(l, 5u));
    }
    /* Perish Song (step G26, order 24) tied between two Pokemon that each hold it alone, or with Leftovers (order 5):
     * the shuffle of the tie is the only draw and no order of the volatiles changes it. */
    {
        const dfi_residual_entry l[] = {PERISH(0), PERISH(1)};
        DF_CHECK(t, !dfi_residual_order_ambiguous(l, 2u));
        const dfi_residual_entry with_items[] = {PERISH(0), LEFT(0), PERISH(1), LEFT(1)};
        DF_CHECK(t, !dfi_residual_order_ambiguous(with_items, 4u));
    }
    /* Perish Song tied between a Pokemon that holds only it and one that also holds two Protect-style counters and
     * Encore (order 16): the selection sort moves Encore to the front past the first Pokemon's Perish handler, and where
     * the group of order 24 then stands depends on how the second Pokemon's volatiles were added, which is not stored:
     * the cheap test cannot clear it, the exact one finds an order that changes the callbacks' sequence, and the engine
     * refuses it (E_UNSUPPORTED) rather than guess. */
    {
        const dfi_residual_entry l[] = {PERISH(0), COUNTER(1), COUNTER(1), ENCORE(1), PERISH(1)};
        DF_CHECK(t, dfi_residual_order_may_matter(l, 5u));
        DF_CHECK(t, dfi_residual_order_ambiguous(l, 5u));
    }
    DF_CHECK_EQ_U64(t, dfi_residual_compare(&(dfi_residual_entry){DFI_RES_PERISH, 0u, 24u, 100u, 2u, true},
                                            &(dfi_residual_entry){DFI_RES_PERISH, 1u, 24u, 100u, 2u, true}),
                    1u);
    DF_CHECK_EQ_U64(t, dfi_residual_compare(&(dfi_residual_entry){DFI_RES_ENCORE, 0u, 16u, 100u, 2u, true},
                                            &(dfi_residual_entry){DFI_RES_PERISH, 0u, 24u, 100u, 2u, true}),
                    0u);
    DF_CHECK_EQ_U64(t, dfi_residual_compare(&(dfi_residual_entry){DFI_RES_ENCORE, 0u, 16u, 100u, 2u, true},
                                            &(dfi_residual_entry){DFI_RES_ENCORE, 1u, 16u, 100u, 2u, true}),
                    1u);
    DF_CHECK_EQ_U64(t, dfi_residual_compare(&(dfi_residual_entry){DFI_RES_LEFTOVERS, 0u, 5u, 100u, 4u, true},
                                            &(dfi_residual_entry){DFI_RES_ENCORE, 0u, 16u, 100u, 2u, true}),
                    0u);
    DF_CHECK_EQ_U64(t, dfi_residual_compare(&(dfi_residual_entry){DFI_RES_WHITE_HERB, 0u, 29u, 100u, 8u, true},
                                            &(dfi_residual_entry){DFI_RES_DURATION, 0u, 22u, 100u, 2u, false}),
                    2u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.combat.residual_order");
    test_examples(&t);
    test_random_lists(&t);
    return df_test_end(&t);
}
