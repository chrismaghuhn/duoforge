#ifndef DUOFORGE_COMBAT_FIELD_MAGIC_ROOM_H
#define DUOFORGE_COMBAT_FIELD_MAGIC_ROOM_H

/* Private field-family implementation (step K5, #475, decision 0015 5dm). Included by turn.c at the existing helper dependency
 * boundary; turn flow owns evaluation order. Magic Room (data/moves.ts:10754-10797): a pseudo weather of five turns (Persistent,
 * the seven-turn form, is not in the pool) that makes every Pokemon ignore its item (the effect helpers of combat/items/held.h).
 * Its state is the tail's magic_room_turns and magic_room_source (the setter's member code, the Attract encoding). */
#include "combat/run_internal.h"

/* The setter of the room as the end line prints it (`[of] ' + this.effectState.source`, data/moves.ts:10788-10790): the Pokemon's
 * toString() at the moment of the end (sim/pokemon.ts:531-533), its slot while it is active, its fullname `p1: Name` (side and name) once it is not. The event carries
 * `other` = the setter's position while it stands on the field (dfi_attract_source_flat: on the field and not fainted), else
 * DUOFORGE_NO_POSITION with the member code in `id`. The code is the room's own, read before it is cleared. */
static inline duoforge_event dfi_magic_room_end_event(const struct duoforge_battle *b)
{
    const uint32_t code = b->tail.magic_room_source; /* 1..12 while the room is up (the invariant) */
    const uint32_t flat = dfi_attract_source_flat(b, code);
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_FIELD_END, DUOFORGE_NO_POSITION);
    e.detail = (uint8_t)DUOFORGE_FIELD_MAGIC_ROOM;
    e.other = (uint8_t)flat;
    const uint32_t named = flat == DUOFORGE_NO_POSITION ? code : 0u; /* the code names a setter that is not on the field */
    e.id = (uint16_t)named;
    return e;
}

/* One byte, locked_move, holds the move of a Choice lock AND the move of a charge or of a lockedmove (Outrage). Under Magic Room a
 * Choice-locked holder may use another move (the volatile stays, its onBeforeMove and onDisableMove return, data/conditions.ts:
 * 332-345); if that move charges or locks, the byte would have to keep two moves. That is not modelled: refused (E_UNSUPPORTED). */
static inline bool dfi_magic_room_lock_conflict(const dfi_active_slot *pos, uint32_t move_slot)
{
    return ((uint32_t)pos->flags & DFI_VOL_CHOICE_LOCK) != 0u && (uint32_t)pos->locked_move != move_slot + 1u;
}

/* Magic Room as a move (moveHit -> addPseudoWeather, sim/field.ts:186-212). The room that is up is REMOVED by its own re-use
 * (onFieldRestart, :10783-10785): `-fieldend|move: Magic Room|[of] <setter>` with no -fieldstart, the move's result true, the timer
 * and the setter cleared. Otherwise it starts for five turns with `-fieldstart|move: Magic Room|[of] <user>` (:10768-10774); the
 * End event it runs on every active holder's item (:10775-10777) is a no-op: no pool item has an End handler, and singleEvent
 * gates an item's End for a Pokemon that ignores its item (sim/battle.ts:609) anyway. `user` is the flat position of the user. */
static void dfi_run_magic_room(dfi_run *r, uint32_t user)
{
    struct duoforge_battle *b = r->b;
    if (b->tail.magic_room_turns != 0u) {
        const duoforge_event e = dfi_magic_room_end_event(b);
        b->tail.magic_room_turns = 0u;
        b->tail.magic_room_source = 0u;
        dfi_emit(r, &e); /* [-fieldend] ... [of] setter */
    } else {
        const uint32_t side = user / DUOFORGE_ACTIVE_PER_SIDE;
        const uint32_t occupant = dfi_pos(b, user)->occupant;
        b->tail.magic_room_turns = (uint8_t)DFI_TAIL_MAGIC_ROOM_MAX;
        b->tail.magic_room_source = (uint8_t)(1u + side * DUOFORGE_MAX_ROSTER + occupant); /* wide-operands-reviewed: 1..12 */
        duoforge_event e = dfi_event_make(DUOFORGE_EVENT_FIELD_START, DUOFORGE_NO_POSITION);
        e.detail = (uint8_t)DUOFORGE_FIELD_MAGIC_ROOM;
        e.other = (uint8_t)user;
        dfi_emit(r, &e); /* [-fieldstart] ... [of] user */
    }
    r->mres |= DFI_MRES_TRUE; /* addPseudoWeather, and its removal on a restart, return true */
}

/* The residual of the room (onFieldResidualOrder 27, SubOrder 6: after Gravity (27.2), before the terrains (27.7)): one turn less,
 * and the end line with the setter when the last is gone. Returns true when the room ended in this call. */
static inline bool dfi_magic_room_residual(dfi_run *r)
{
    struct duoforge_battle *b = r->b;
    if (b->tail.magic_room_turns == 0u) {
        return false;
    }
    b->tail.magic_room_turns = (uint8_t)((uint32_t)b->tail.magic_room_turns - 1u); /* wide-operands-reviewed: >= 1 */
    if (b->tail.magic_room_turns != 0u) {
        return false;
    }
    const duoforge_event e = dfi_magic_room_end_event(b);
    b->tail.magic_room_source = 0u;
    dfi_emit(r, &e); /* [-fieldend] ... [of] setter */
    return true;
}

#endif
