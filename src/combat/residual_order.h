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
 * duration counters, Heal Block, Throat Chop, Encore). That is the reference's order, or it changes nothing, in these
 * cases (proved by tests/test_residual_order.c against the reference's selection sort for every order of the volatiles):
 *   - the Pokemon has volatile handlers of one sort key only (the duration counters have one: no order, sub-order 2),
 *     so their order is the order of equal entries and shows nowhere;
 *   - or no group of equal callbacks (a group that draws: Leftovers, Grassy Terrain, burn, poison, Encore, White
 *     Herb) has an order at or after the earliest order among the Pokemon's volatile handlers. Every selection round
 *     for a group of earlier order looks at the group's members, whose positions are those of the initial list, and
 *     the entries that those rounds move out of their way are the ones at the front, whose new places are the holes of
 *     the group's members: where a volatile handler of a later order lands changes no member of a group of earlier
 *     order and no draw.
 * Anything else is dfi_residual_order_ambiguous: the engine refuses it (E_UNSUPPORTED) rather than guess.
 */
#include <stdbool.h>
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
#define DFI_RES_NO_ORDER 0xFFFFFFFFu

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
    return e->kind == DFI_RES_DURATION || e->kind == DFI_RES_ENCORE;
}

/* True when the list is one whose result could depend on the order in which a Pokemon's volatiles were added (the
 * module comment above): a Pokemon with volatile handlers of two or more sort keys, and a group of equal callbacks
 * (a draw) whose order is not before the earliest order of that Pokemon's volatile handlers. */
static inline bool dfi_residual_order_ambiguous(const dfi_residual_entry *list, uint32_t n)
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

#endif
