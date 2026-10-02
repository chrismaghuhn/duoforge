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
static void model_sort(dfi_residual_entry *list, uint32_t n, const uint32_t *values)
{
    uint32_t sorted = 0u;
    uint32_t used = 0u;
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
                const uint32_t v = lo + values[used++] % (count - lo);
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

static void draw_values(rng *g, uint32_t *values)
{
    for (uint32_t i = 0u; i < MAX_LIST; ++i) {
        values[i] = rng_next(g);
    }
}

static void test_random_lists(df_test *t)
{
    rng g = {0x5EEDC0DEull};
    unsigned long flagged = 0u;
    unsigned long flagged_that_differ = 0u;
    unsigned long unflagged_multi = 0u; /* unflagged lists with a Pokemon that has volatiles of two keys */
    for (uint32_t trial = 0u; trial < 60000u; ++trial) {
        shape base;
        random_shape(&g, &base, rng_next(&g) % 4u == 0u, rng_next(&g) % 4u == 0u);
        const bool amb = dfi_residual_order_ambiguous(base.list, base.n);
        bool multi = false;
        for (uint32_t m = 0u; m < base.mons; ++m) {
            for (uint32_t i = 1u; i < base.vol_len[m]; ++i) {
                const dfi_residual_entry *a = &base.list[base.vol_start[m]];
                multi = multi || a[i].order != a[0].order || a[i].sub_order != a[0].sub_order;
            }
        }
        if (amb) {
            flagged += 1u;
        } else if (multi) {
            unflagged_multi += 1u;
        }
        bool differs = false;
        for (uint32_t rep = 0u; rep < 12u; ++rep) {
            shape other = base;
            scramble(&g, &other);
            uint32_t values[MAX_LIST];
            draw_values(&g, values);
            if (!same_outcome(&base, &other, values)) {
                differs = true;
                if (!amb) {
                    /* an unflagged list whose outcome depends on the order: the argument is wrong */
                    DF_CHECK(t, !differs);
                    return;
                }
            }
        }
        if (amb && differs) {
            flagged_that_differ += 1u;
        }
    }
    /* The brute force is not vacuous: lists that are flagged exist, some of them really change, and so do unflagged
     * lists with volatiles of two keys (which the argument says are fine). */
    DF_CHECK(t, flagged > 100u);
    DF_CHECK(t, flagged_that_differ > 10u);
    DF_CHECK(t, unflagged_multi > 100u);
}

static const dfi_residual_entry E_COUNTER0 = {DFI_RES_DURATION, 0u, DFI_RES_NO_ORDER, 100u, 2u, false};
static const dfi_residual_entry E_HEAL0 = {DFI_RES_DURATION, 0u, 20u, 100u, 2u, false};
static const dfi_residual_entry E_CHOP0 = {DFI_RES_DURATION, 0u, 22u, 100u, 2u, false};
static const dfi_residual_entry E_ENCORE0 = {DFI_RES_ENCORE, 0u, 16u, 100u, 2u, true};
static const dfi_residual_entry E_ENCORE1 = {DFI_RES_ENCORE, 1u, 16u, 100u, 2u, true};
static const dfi_residual_entry E_LEFT0 = {DFI_RES_LEFTOVERS, 0u, 5u, 100u, 4u, true};
static const dfi_residual_entry E_LEFT1 = {DFI_RES_LEFTOVERS, 1u, 5u, 100u, 4u, true};
static const dfi_residual_entry E_HERB0 = {DFI_RES_WHITE_HERB, 0u, 29u, 100u, 8u, true};
static const dfi_residual_entry E_HERB1 = {DFI_RES_WHITE_HERB, 1u, 29u, 100u, 8u, true};
static const dfi_residual_entry E_CHOP1 = {DFI_RES_DURATION, 1u, 22u, 100u, 2u, false};

static void test_examples(df_test *t)
{
    /* One Pokemon with Encore and Throat Chop (two keys) and Leftovers tied with another's: Leftovers is order 5, before
     * both volatiles, so the order of the volatiles cannot change it. */
    {
        const dfi_residual_entry l[] = {E_ENCORE0, E_CHOP0, E_LEFT0, E_LEFT1};
        DF_CHECK(t, !dfi_residual_order_ambiguous(l, 4u));
    }
    /* The same Pokemon with Encore tied with another Pokemon's Encore: a draw of order 16 on a list whose earlier part is
     * not stored. */
    {
        const dfi_residual_entry l[] = {E_ENCORE0, E_CHOP0, E_ENCORE1, E_CHOP1};
        DF_CHECK(t, dfi_residual_order_ambiguous(l, 4u));
    }
    /* A Pokemon with Throat Chop and Heal Block, a White Herb tie (order 29, after the volatiles). */
    {
        const dfi_residual_entry l[] = {E_HEAL0, E_CHOP0, E_HERB0, E_HERB1};
        DF_CHECK(t, dfi_residual_order_ambiguous(l, 4u));
    }
    /* Duration counters have one key: their order shows nowhere, so even a White Herb tie is fine. */
    {
        const dfi_residual_entry l[] = {E_COUNTER0, E_COUNTER0, E_HERB0, E_HERB1};
        DF_CHECK(t, !dfi_residual_order_ambiguous(l, 4u));
    }
    /* Two keys but no tie: nothing draws. */
    {
        const dfi_residual_entry l[] = {E_ENCORE0, E_HEAL0, E_HERB0, E_LEFT1};
        DF_CHECK(t, !dfi_residual_order_ambiguous(l, 4u));
    }
    /* Encore tied between two Pokemon that each hold one key only. */
    {
        const dfi_residual_entry l[] = {E_ENCORE0, E_ENCORE1};
        DF_CHECK(t, !dfi_residual_order_ambiguous(l, 2u));
    }
    DF_CHECK_EQ_U64(t, dfi_residual_compare(&E_ENCORE0, &E_ENCORE1), 1u);
    DF_CHECK_EQ_U64(t, dfi_residual_compare(&E_LEFT0, &E_ENCORE0), 0u);
    DF_CHECK_EQ_U64(t, dfi_residual_compare(&E_HERB0, &E_CHOP0), 2u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.combat.residual_order");
    test_examples(&t);
    test_random_lists(&t);
    return df_test_end(&t);
}
