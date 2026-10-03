#ifndef DFI_COMBAT_RESIDUAL_ORDER_H
#define DFI_COMBAT_RESIDUAL_ORDER_H

/*
 * The residual handler list (the sort of fieldEvent('Residual'), sim/battle.ts:484-523) and when the engine can
 * build it exactly.
 *
 * The reference lists every handler of the event, sorts the list once with a selection sort (speedSort,
 * sim/battle.ts:429-460) and shuffles each group of equal handlers. A shuffle is a draw, and the group that is
 * shuffled holds its members in the order that the selection sort's swaps left them: the list's initial order and the
 * entries that never act (duration handlers, a callback that has nothing to do) decide which of two tied Pokemon comes
 * first for a given draw. So the engine's list must be the reference's list: the field's handlers, then per active
 * Pokemon in slot order its status, its volatiles in the order they were added, its ability, its item (the Pokemon's
 * handlers, sim/battle.ts:1097-1130), and Grassy Terrain's heal after them (the field's handler for that Pokemon,
 * sim/battle.ts:501-503).
 *
 * The order in which a Pokemon's volatiles were added is not stored. The engine builds them in one fixed order (the
 * duration counters, Heal Block, Disable, Throat Chop, Encore). That is the reference's order, or it changes nothing, in these
 * cases (proved by tests/test_residual_order.c against its own model of the reference's selection sort):
 *   - the Pokemon has volatile handlers of one sort key only (the duration counters have one: no order, sub-order 2),
 *     so their order is the order of equal entries and shows nowhere;
 *   - no group of equal callbacks (a group that draws: Leftovers, Grassy Terrain, burn, poison, Encore, White Herb)
 *     has an order at or after the earliest order among the Pokemon's volatile handlers (the cheap test below: every
 *     selection round for a group of earlier order looks at the group's members, whose positions are those of the
 *     initial list, and the entries that those rounds move out of their way are the ones at the front, whose new
 *     places are the holes of the group's members: where a volatile handler of a later order lands changes no member
 *     of a group of earlier order and no draw);
 *   - or the sort, run over every order of the volatiles of the Pokemon that have two sort keys or more and over every
 *     value of every draw, comes out with the same callbacks in the same order every round (the exact test below; it
 *     runs only for the lists that the cheap test cannot clear, and gives up, as ambiguous, past a bound on the number
 *     of orders and of draws that it tries). The sizes of the groups, and so the draws, do not depend on the order.
 * Anything else is dfi_residual_order_ambiguous: the engine refuses it (E_UNSUPPORTED) rather than guess.
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define DFI_RES_WEATHER 1u
#define DFI_RES_TERRAIN_END 2u
#define DFI_RES_BURN 3u
#define DFI_RES_DURATION 4u /* a volatile's duration handler of a position: the counters, Heal Block, Throat Chop */
#define DFI_RES_GRASSY 5u
#define DFI_RES_FIELD_END 6u /* Trick Room, a side condition: duration only */
#define DFI_RES_LEFTOVERS 7u
#define DFI_RES_POISON 8u
#define DFI_RES_WHITE_HERB 9u
#define DFI_RES_ENCORE 10u /* Encore: order 16, a callback with a duration (step G9) */
/* The duration handlers whose end shows a line (step G27 for Disable, and Heal Block, which was a pass): each is an entry
 * of the sorted list at its own order, and a callback (a tie of two draws) exactly when it ends in this residual. */
#define DFI_RES_HEAL_BLOCK 12u /* Heal Block: order 20, -end|X|move: Heal Block */
#define DFI_RES_DISABLE 14u    /* Disable: order 17, -end|X|Disable */
#define DFI_RES_NO_ORDER 0xFFFFFFFFu

/* The exact test's bounds: the lists of the engine have at most 3 + 3 * 2 + 14 * 4 entries, a few draws and a few
 * orders (3 + 4 * 2 + 15 * 4 with Disable). */
#define DFI_RES_MODEL_MAX 80u
#define DFI_RES_DRAW_CAP 4096u
#define DFI_RES_ARRANGEMENT_CAP 1024u
#define DFI_RES_REGION_MAX 4u

typedef struct dfi_residual_entry {
    uint32_t kind;
    uint32_t flat;
    uint32_t order;
    uint32_t speed;
    uint32_t sub_order;
    bool callback; /* the engine draws a tie of such entries (a shuffle that shows) */
} dfi_residual_entry;

/* comparePriority for residual handlers: 0 a first, 1 tie, 2 b first. */
static inline uint32_t dfi_residual_compare(const dfi_residual_entry *a, const dfi_residual_entry *b)
{
    if (a->order != b->order) {
        return a->order < b->order ? 0u : 2u;
    }
    if (a->speed != b->speed) {
        return a->speed > b->speed ? 0u : 2u;
    }
    if (a->sub_order != b->sub_order) {
        return a->sub_order < b->sub_order ? 0u : 2u;
    }
    return 1u;
}

/* A handler of one of a Pokemon's volatiles (the part of its list whose order is not stored). */
static inline bool dfi_residual_is_volatile(const dfi_residual_entry *e)
{
    return e->kind == DFI_RES_DURATION || e->kind == DFI_RES_ENCORE || e->kind == DFI_RES_HEAL_BLOCK ||
           e->kind == DFI_RES_DISABLE;
}

/* The cheap test: true when the list is one whose result could depend on the order in which a Pokemon's volatiles were
 * added: a Pokemon with volatile handlers of two or more sort keys, and a group of equal callbacks (a draw) whose order
 * is not before the earliest order of that Pokemon's volatile handlers. False means it cannot. */
static inline bool dfi_residual_order_may_matter(const dfi_residual_entry *list, uint32_t n)
{
    for (uint32_t i = 0u; i < n; ++i) {
        if (!dfi_residual_is_volatile(&list[i])) {
            continue;
        }
        uint32_t earliest = list[i].order;
        bool distinct = false;
        for (uint32_t j = 0u; j < n; ++j) {
            if (j == i || !dfi_residual_is_volatile(&list[j]) || list[j].flat != list[i].flat) {
                continue;
            }
            distinct = distinct || list[j].order != list[i].order || list[j].sub_order != list[i].sub_order;
            earliest = list[j].order < earliest ? list[j].order : earliest;
        }
        if (!distinct) {
            continue;
        }
        for (uint32_t a = 0u; a < n; ++a) {
            for (uint32_t b = a + 1u; b < n; ++b) {
                if (list[a].callback && list[b].callback && dfi_residual_compare(&list[a], &list[b]) == 1u &&
                    list[a].order >= earliest) {
                    return true;
                }
            }
        }
    }
    return false;
}

/* The reference's selection sort over a copy of the list (the engine's dfi_residual_sort does the same steps). The k-th
 * draw of a shuffle group takes digit k modulo its range; `ranges` (if not NULL) gets the range of each draw. The
 * callbacks come out in `ids` in sorted order, as a code of what they are. Returns the number of draws. */
static inline uint32_t dfi_residual_model(const dfi_residual_entry *input, uint32_t n, const uint32_t *digits,
                                          uint32_t *ranges, uint32_t *ids, uint32_t *id_count)
{
    dfi_residual_entry list[DFI_RES_MODEL_MAX];
    for (uint32_t i = 0u; i < n; ++i) {
        list[i] = input[i];
    }
    uint32_t sorted = 0u;
    uint32_t draws = 0u;
    while (sorted + 1u < n) {
        uint32_t next[DFI_RES_MODEL_MAX] = {0u};
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
        uint32_t calls = 0u;
        for (uint32_t i = sorted; i < sorted + count; ++i) {
            calls += list[i].callback ? 1u : 0u;
        }
        if (calls >= 2u) {
            for (uint32_t start = sorted; start + 1u < sorted + count; ++start) {
                const uint32_t lo = start - sorted;
                const uint32_t range = count - lo;
                if (ranges != NULL) {
                    ranges[draws] = range;
                }
                const uint32_t v = lo + digits[draws] % range;
                draws += 1u;
                if (sorted + v != start) {
                    const dfi_residual_entry e = list[start];
                    list[start] = list[sorted + v];
                    list[sorted + v] = e;
                }
            }
        }
        sorted += count;
    }
    uint32_t k = 0u;
    for (uint32_t i = 0u; i < n; ++i) {
        if (list[i].callback) {
            ids[k] = list[i].kind * 1000u + list[i].flat * 100u + list[i].order % 100u;
            k += 1u;
        }
    }
    *id_count = k;
    return draws;
}

/* Entries of one Pokemon's volatiles, ordered by their sort key (the order of the lexicographic permutations). */
static inline bool dfi_residual_key_less(const dfi_residual_entry *a, const dfi_residual_entry *b)
{
    if (a->order != b->order) {
        return a->order < b->order;
    }
    if (a->sub_order != b->sub_order) {
        return a->sub_order < b->sub_order;
    }
    return a->kind < b->kind;
}

/* The next permutation of seg[0..len) in the order of dfi_residual_key_less (equal keys are not told apart, so every
 * order of the multiset comes once). False when it was the last: the segment is then the first one again. */
static inline bool dfi_residual_next_permutation(dfi_residual_entry *seg, uint32_t len)
{
    uint32_t i = len;
    while (i >= 2u && !dfi_residual_key_less(&seg[i - 2u], &seg[i - 1u])) {
        i -= 1u;
    }
    if (i < 2u) {
        for (uint32_t a = 0u, b = len - 1u; a < b; ++a, --b) { /* back to the first order */
            const dfi_residual_entry e = seg[a];
            seg[a] = seg[b];
            seg[b] = e;
        }
        return false;
    }
    uint32_t j = len - 1u;
    while (!dfi_residual_key_less(&seg[i - 2u], &seg[j])) {
        j -= 1u;
    }
    dfi_residual_entry e = seg[i - 2u];
    seg[i - 2u] = seg[j];
    seg[j] = e;
    for (uint32_t a = i - 1u, b = len - 1u; a < b; ++a, --b) {
        e = seg[a];
        seg[a] = seg[b];
        seg[b] = e;
    }
    return true;
}

/* The exact test: true when some order of the volatiles of the Pokemon with two sort keys or more, and some value of
 * every draw, makes the callbacks come out in a different order than they do for the list as it is; also true when the
 * bounds are exceeded (the result is not known then). */
static inline bool dfi_residual_order_changes_outcome(const dfi_residual_entry *list, uint32_t n)
{
    if (n > DFI_RES_MODEL_MAX) {
        return true;
    }
    /* the runs of one Pokemon's volatile entries that hold two sort keys or more */
    uint32_t start[DFI_RES_REGION_MAX] = {0u};
    uint32_t len[DFI_RES_REGION_MAX] = {0u};
    uint32_t regions = 0u;
    for (uint32_t i = 0u; i < n;) {
        if (!dfi_residual_is_volatile(&list[i])) {
            i += 1u;
            continue;
        }
        uint32_t j = i + 1u;
        bool distinct = false;
        while (j < n && dfi_residual_is_volatile(&list[j]) && list[j].flat == list[i].flat) {
            distinct = distinct || list[j].order != list[i].order || list[j].sub_order != list[i].sub_order;
            j += 1u;
        }
        for (uint32_t k = 0u; k < n; ++k) { /* a volatile of this Pokemon outside the run: not a layout the engine builds */
            if (k < i || k >= j) {
                if (dfi_residual_is_volatile(&list[k]) && list[k].flat == list[i].flat) {
                    return true;
                }
            }
        }
        if (distinct) {
            if (regions == DFI_RES_REGION_MAX) {
                return true;
            }
            start[regions] = i;
            len[regions] = j - i;
            regions += 1u;
        }
        i = j;
    }
    if (regions == 0u) {
        return false;
    }
    /* the draws: their ranges do not depend on the order of anything */
    uint32_t zero[DFI_RES_MODEL_MAX] = {0u};
    uint32_t ranges[DFI_RES_MODEL_MAX] = {0u};
    uint32_t ids[DFI_RES_MODEL_MAX];
    uint32_t id_count = 0u;
    const uint32_t draws = dfi_residual_model(list, n, zero, ranges, ids, &id_count);
    uint32_t combos = 1u;
    for (uint32_t k = 0u; k < draws; ++k) {
        combos *= ranges[k];
        if (combos > DFI_RES_DRAW_CAP) {
            return true;
        }
    }
    /* every order of the volatiles, starting from the first in sort-key order */
    dfi_residual_entry work[DFI_RES_MODEL_MAX];
    for (uint32_t i = 0u; i < n; ++i) {
        work[i] = list[i];
    }
    for (uint32_t r = 0u; r < regions; ++r) {
        dfi_residual_entry *seg = &work[start[r]];
        for (uint32_t a = 1u; a < len[r]; ++a) { /* insertion sort */
            const dfi_residual_entry e = seg[a];
            uint32_t b = a;
            while (b > 0u && dfi_residual_key_less(&e, &seg[b - 1u])) {
                seg[b] = seg[b - 1u];
                b -= 1u;
            }
            seg[b] = e;
        }
    }
    for (uint32_t arrangement = 0u;; ++arrangement) {
        if (arrangement >= DFI_RES_ARRANGEMENT_CAP) {
            return true;
        }
        uint32_t digits[DFI_RES_MODEL_MAX] = {0u};
        for (uint32_t c = 0u; c < combos; ++c) {
            uint32_t base_ids[DFI_RES_MODEL_MAX];
            uint32_t alt_ids[DFI_RES_MODEL_MAX];
            uint32_t base_count = 0u;
            uint32_t alt_count = 0u;
            (void)dfi_residual_model(list, n, digits, NULL, base_ids, &base_count);
            (void)dfi_residual_model(work, n, digits, NULL, alt_ids, &alt_count);
            if (base_count != alt_count) {
                return true;
            }
            for (uint32_t k = 0u; k < base_count; ++k) {
                if (base_ids[k] != alt_ids[k]) {
                    return true;
                }
            }
            for (uint32_t k = 0u; k < draws; ++k) { /* the next value of the draws (an odometer) */
                digits[k] += 1u;
                if (digits[k] < ranges[k]) {
                    break;
                }
                digits[k] = 0u;
            }
        }
        uint32_t r = 0u;
        while (r < regions && !dfi_residual_next_permutation(&work[start[r]], len[r])) {
            r += 1u;
        }
        if (r == regions) {
            return false;
        }
    }
}

/* True when the list is one whose result could depend on the order in which a Pokemon's volatiles were added (the
 * module comment above): what the engine refuses. */
static inline bool dfi_residual_order_ambiguous(const dfi_residual_entry *list, uint32_t n)
{
    return dfi_residual_order_may_matter(list, n) && dfi_residual_order_changes_outcome(list, n);
}

#endif
