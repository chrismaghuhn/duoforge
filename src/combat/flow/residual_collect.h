#ifndef DUOFORGE_COMBAT_FLOW_RESIDUAL_COLLECT_H
#define DUOFORGE_COMBAT_FLOW_RESIDUAL_COLLECT_H

/* Private flow implementation: phase 1 of the residual runner, the unsorted handler list. Split from
 * src/combat/turn.c@8f69cc89 so that the white-box test duoforge.flow.residual_collect (issue 664) can check the list it
 * builds; included by turn.c where the list's bounds stood, so its dependencies and the turn order are unchanged.
 * Internal header: no public value, no state. */
#include <stdbool.h>
#include <stdint.h>

#include "combat/abilities/current.h"
#include "combat/items/held.h"
#include "combat/residual_order.h"
#include "combat/run_internal.h"
#include "core/inline.h"
#include "data/formats/reg-mc/closure_tables.h"
#include "data/formats/reg-mc/extended_tables.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"

/* Trick Room, weather and terrain; four conditions per side (step G20 added Aurora Veil); per position
 * (DFI_RES_PER_POSITION) a status (burn or poison), the volatiles' handlers (seven duration ends: Protect, the stall
 * counter, flinch, a charge, Helping Hand, Follow Me and mustrecharge; Heal Block, Throat Chop, Encore, Disable (step G27),
 * Perish Song (step G26), Taunt and Yawn (step G31)), an item (Leftovers or White Herb), Speed Boost (step G32) and Grassy Terrain. */
#define DFI_RES_PER_POSITION 25u /* 14 before Speed Boost (G32), Disable (G27), Perish Song (G26), Taunt and Yawn (G31), the lockedmove (G56), Roost's volatile (G42), Leech Seed's drain (G84), Curse (G84b), the partial trap (G90) and the Ally Switch duration (G80) */
#define DFI_RES_MAX (4u + 6u * DUOFORGE_SIDE_COUNT + DFI_RES_PER_POSITION * DFI_POSITIONS) /* the field: Trick Room, Gravity, weather, terrain; a side: four screens and Tailwind, two guards */
_Static_assert(DFI_RES_MAX <= DFI_RES_MODEL_MAX, "the exact test of residual_order.h must hold the whole list");

/* Phase 1: the handlers of this residual, unsorted: the field, each side's conditions, each Pokemon's. */
static DFI_ALWAYS_INLINE duoforge_status dfi_residual_collect(dfi_run *r, struct duoforge_battle *b,
                                                             dfi_residual_entry *list, uint32_t *count)
{
    uint32_t n = 0u;
    /* The field's pseudo-weathers first, in the order they were added (findFieldEventHandlers, sim/battle.ts:1133-1145): Trick
     * Room (order 27, sub-order 1) and Gravity (27, sub-order 2, data/moves.ts:7832-7833). They only count down, but each is an
     * entry of the sort whose swaps move the other entries (issue 661's review: without Gravity the pre-shuffle order of a later
     * tie can differ). The order of the two is not stored: they are a region of the arrangement test (DFI_RESIDUAL_FIELD_FLAT). */
    if (b->trick_room_turns != 0u) {
        list[n] = (dfi_residual_entry){DFI_RES_FIELD_END, DFI_RESIDUAL_FIELD_FLAT, 27u, 0u, 1u, false};
        n += 1u;
    }
    if (b->tail.gravity_turns != 0u) {
        list[n] = (dfi_residual_entry){DFI_RES_FIELD_END, DFI_RESIDUAL_FIELD_FLAT, 27u, 0u, 2u, false};
        n += 1u;
    }
    if (b->weather != DFI_WEATHER_NONE) {
        list[n] = (dfi_residual_entry){DFI_RES_WEATHER, 0u, 1u, 0u, 5u, true};
        n += 1u;
    }
    if (b->terrain != DFI_TERRAIN_NONE) {
        list[n] = (dfi_residual_entry){DFI_RES_TERRAIN_END, 0u, 27u, 0u, 7u, false};
        n += 1u;
    }
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        if (flat % 2u == 0u) {
            /* The side's conditions come before its Pokemon (findSideEventHandlers, sim/battle.ts:1149-1163), each with its
             * own key: Reflect, Light Screen, Tailwind and Aurora Veil at order 26 with sub-orders 1, 2, 5 and 10
             * (data/moves.ts:864-865 and the like), Wide Guard and Quick Guard with no order, Speed 0 and the side
             * condition's sub-order 4 (duration 1, no onResidual: sim/battle.ts:954-976). None is a callback, but each is an
             * entry of the sort (issue 661's review: a missing Wide Guard changes the pre-shuffle order of a later tie). The
             * order in which they were added is not stored: they are a region of the arrangement test (flat
             * DFI_RESIDUAL_SIDE_FLAT + side). */
            const dfi_side *sd = &b->sides[flat / 2u];
            const dfi_tail_side *tsd = &b->tail.sides[flat / 2u];
            const uint32_t side_flat = DFI_RESIDUAL_SIDE_FLAT + flat / 2u;
            if (sd->reflect_turns != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_FIELD_END, side_flat, 26u, 0u, 1u, false};
                n += 1u;
            }
            if (sd->light_screen_turns != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_FIELD_END, side_flat, 26u, 0u, 2u, false};
                n += 1u;
            }
            if (sd->tailwind_turns != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_FIELD_END, side_flat, 26u, 0u, 5u, false};
                n += 1u;
            }
            if (tsd->aurora_veil_turns != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_FIELD_END, side_flat, 26u, 0u, 10u, false};
                n += 1u;
            }
            if (tsd->wide_guard != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_FIELD_END, side_flat, DFI_RES_NO_ORDER, 0u, 4u, false};
                n += 1u;
            }
            if (tsd->quick_guard != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_FIELD_END, side_flat, DFI_RES_NO_ORDER, 0u, 4u, false};
                n += 1u;
            }
        }
        const dfi_active_slot *pos = dfi_pos(b, flat);
        const dfi_member *m = dfi_at(b, flat);
        if (m == NULL) {
            continue;
        }
        if (n + DFI_RES_PER_POSITION > DFI_RES_MAX) {
            return DUOFORGE_E_INVARIANT; /* the bound above is exact: never */
        }
        const uint32_t speed = r->speed_seen[flat];
        if (m->status == DFI_STATUS_BRN) {
            list[n] = (dfi_residual_entry){DFI_RES_BURN, flat, 10u, speed, 0u, true};
            n += 1u;
        } else if (m->status == DFI_STATUS_PSN || m->status == DFI_STATUS_TOX) {
            /* psn and tox have the same handler order (9, data/conditions.ts:123-161) */
            list[n] = (dfi_residual_entry){DFI_RES_POISON, flat, 9u, speed, 0u, true};
            n += 1u;
        }
        /* Leech Seed's drain (order 8, decision 0047): an entry only for a standing holder whose seed has a source */
        if (m->hp != 0u && b->tail.sides[flat / 2u].positions[flat % 2u].leech_seed_source != 0u) {
            /* Leech Seed's onResidualOrder 8 with no sub-order: a Condition on a Pokemon has subOrder 2 (sim/battle.ts:954-976:
             * the effectTypeOrder table; the side and field overrides at :971-980 do not apply to a volatile on a Pokemon). */
            list[n] = (dfi_residual_entry){DFI_RES_LEECH, flat, 8u, speed, 2u, true};
            n += 1u;
        }
        /* Curse's residual (step G84b, decision 0063; onResidualOrder 12, a condition: sub-order 2): an entry for a standing holder */
        if (m->hp != 0u && (b->tail.sides[flat / 2u].positions[flat % 2u].position_flags & DFI_POSFLAG_CURSED) != 0u) {
            list[n] = (dfi_residual_entry){DFI_RES_CURSE, flat, 12u, speed, 2u, true};
            n += 1u;
        }
        /* The volatiles with a duration handler of their own, in the one fixed order of residual_order.h (Heal
         * Block, Throat Chop, Yawn, Taunt, Encore, then the counters of the turn): Heal Block (order 20, data/moves.ts:8273-8320), Throat Chop (22,
         * :19389-19423), Yawn (23, :21152), Taunt (15, :18992) and Encore (16). Each is an entry of the sorted list at its
         * order (the reference's fieldEvent counts every duration down and ends it when its turn comes, :517-527). The
         * ones whose end shows something (Heal Block, Yawn, Taunt) are callbacks, a tie that draws, exactly when they end
         * in this residual: a tie of handlers that end nowhere shows nothing and is not drawn (the converter drops that
         * draw from the tape). Throat Chop's end is silent: its count goes down below. */
        {
            const dfi_tail_pos *vt = &b->tail.sides[flat / 2u].positions[flat % 2u];
            if (vt->heal_block_turns != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_HEAL_BLOCK, flat, 20u, speed, 2u, vt->heal_block_turns == 1u};
                n += 1u;
            }
            if (vt->disable_slot != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_DISABLE, flat, 17u, speed, 2u, vt->disable_turns == 1u};
                n += 1u;
            }
            if (vt->throat_chop_turns != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_DURATION, flat, 22u, speed, 2u, false};
                n += 1u;
            }
            if (vt->yawn_turns != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_YAWN, flat, 23u, speed, 2u, vt->yawn_turns == 1u};
                n += 1u;
            }
            if (vt->taunt_turns != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_TAUNT, flat, 15u, speed, 2u, vt->taunt_turns == 1u};
                n += 1u;
            }
            if (vt->encore_slot != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_ENCORE, flat, 16u, speed, 2u, true};
                n += 1u;
            }
            /* Perish Song (order 24, data/moves.ts:13261-13272; step G26): a volatile with a duration and a callback every
             * turn (its count line), so a handler of the sort whose tie is a drawn shuffle, like Encore's. It sorts after
             * Heal Block's (20) and Disable's (17) end lines, which are entries of the same list. */
            if (vt->perish != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_PERISH, flat, 24u, speed, 2u, true};
                n += 1u;
            }
            /* lockedmove (step G56, data/conditions.ts:253-285): no order (the pin's onResidual has no onResidualOrder), sub-order 2
             * (a condition), and a callback with a duration: the countdown, or its end when no Outrage was used this turn. */
            if (vt->lock_turns != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_LOCK, flat, DFI_RES_NO_ORDER, speed, 2u, true};
                n += 1u;
            }
            /* The partial trap (step G90, decision 0060; order 13, sub-order 2): a callback every turn, like Perish Song's count. */
            if (vt->trap_turns != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_PARTIAL_TRAP, flat, 13u, speed, 2u, true};
                n += 1u;
            }
            /* Roost's volatile (duration 1, onResidualOrder 25, data/moves.ts:15444-15455): its end is silent, the bit goes at
             * that entry (step G42). */
            if ((vt->single_turn & DFI_SINGLE_TURN_ROOST) != 0u) {
                list[n] = (dfi_residual_entry){DFI_RES_DURATION, flat, 25u, speed, 2u, false};
                n += 1u;
            }
        }
        const uint32_t ends = ((((uint32_t)pos->flags & DFI_VOL_PROTECT) != 0u) ? 1u : 0u) +
                              (pos->stall_level != 0u ? 1u : 0u) +
                              ((((uint32_t)pos->flags & DFI_VOL_FLINCH) != 0u) ? 1u : 0u) +
                              (pos->charge_turns != 0u ? 1u : 0u) +
                              ((((uint32_t)pos->flags & DFI_VOL_HELPING_HAND) != 0u) ? 1u : 0u) +
                              ((((uint32_t)pos->flags & DFI_VOL_FOLLOW_ME) != 0u) ? 1u : 0u) +
                              /* mustrecharge has a duration (2) and no callback: an end handler of the residual's sort,
                               * like the stall counter (data/conditions.ts:364-378; step G17). */
                              (b->tail.sides[flat / 2u].positions[flat % 2u].must_recharge != 0u ? 1u : 0u) +
                              /* Ally Switch's volatile (step G80, decision 0044): a duration handler with no order (no onResidualOrder,
                               * data/moves.ts:302-357 condition `allyswitch`, duration 2), sub-order 2 (a condition), present while the
                               * volatile is. It takes a place in the selection sort of the residual, and the sort's swaps move the
                               * other handlers (sim/battle.ts:429-455, speedSort; fieldEvent collects every holder's handlers in
                               * position order, sim/battle.ts:484-510). Recorded: fz_80_29, step 32 (two burned Milotic). */
                              (b->tail.sides[flat / 2u].positions[flat % 2u].ally_switch != 0u ? 1u : 0u);
        for (uint32_t k = 0u; k < ends; ++k) {
            list[n] = (dfi_residual_entry){DFI_RES_DURATION, flat, DFI_RES_NO_ORDER, speed, 2u, false};
            n += 1u;
        }
        /* Speed Boost's onResidual (step G32, order 28, sub-order 2): the ability's handlers come before the item's in a
         * Pokemon's list (sim/battle.ts:1097-1130). */
        if (dfi_ability(r->b, m, DFI_ABILITY_SPEEDBOOST)) {
            list[n] = (dfi_residual_entry){DFI_RES_SPEED_BOOST, flat, 28u, speed, 2u, true};
            n += 1u;
        }
        /* Moody's onResidual (step G73, data/abilities.ts:2701-2734): order 28, sub-order 2, as Speed Boost's, and a callback
         * (its handler is run in every tie; its draws are the sample of dfi_moody). One ability per Pokemon: the same slot. */
        if (dfi_ability(r->b, m, DFI_ABILITY_MOODY)) {
            list[n] = (dfi_residual_entry){DFI_RES_MOODY, flat, 28u, speed, 2u, true};
            n += 1u;
        }
        if (dfi_holds(r->b, m, DFI_ITEM_LEFTOVERS)) {
            list[n] = (dfi_residual_entry){DFI_RES_LEFTOVERS, flat, 5u, speed, 4u, true};
            n += 1u;
        }
        /* White Herb's onResidual (order 29, an item: sub-order 8; Team C). */
        if (dfi_holds(r->b, m, DFI_ITEM_WHITEHERB)) {
            list[n] = (dfi_residual_entry){DFI_RES_WHITE_HERB, flat, 29u, speed, 8u, true};
            n += 1u;
        }
        if (b->terrain == DFI_TERRAIN_GRASSY) {
            list[n] = (dfi_residual_entry){DFI_RES_GRASSY, flat, 5u, speed, 2u, true};
            n += 1u;
        }
    }
    *count = n;
    return DUOFORGE_OK;
}

#endif
