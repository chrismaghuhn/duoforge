#ifndef DUOFORGE_COMBAT_EVENTS_H
#define DUOFORGE_COMBAT_EVENTS_H

/*
 * The events of one step in canonical form (docs/decisions/0007 section 6):
 * one record per protocol line the game shows, with the exact HP of every
 * Pokemon. dfi_event_project turns a record into one player's view, where
 * the opponent's HP is the percent display. Events are outputs, not state.
 */
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "core/inline.h"
#include "state/battle_internal.h"

struct dfi_observation_digest;

typedef struct dfi_events {
    duoforge_event rec[DUOFORGE_MAX_EVENTS];
    uint32_t count;
    struct dfi_observation_digest *observation; /* NULL in every legacy path */
    bool overflow; /* more than DUOFORGE_MAX_EVENTS: the step fails with E_INVARIANT */
} dfi_events;

/* A record of `kind` about `position`; other NO_POSITION, everything else 0. An inline definition, forced into every
 * caller: after the phase cuts of step 4 the LTO link stopped inlining it from events.c. events.c holds its one external
 * definition (C99 inline), so the symbol and the library's exports stay as they were. */
DFI_ALWAYS_INLINE duoforge_event dfi_event_make(uint32_t kind, uint32_t position)
{
    duoforge_event e;
    memset(&e, 0, sizeof e);
    e.kind = (uint8_t)kind;         /* <= DUOFORGE_EVENT_ITEM_START */
    e.position = (uint8_t)position; /* < 4 or DUOFORGE_NO_POSITION */
    e.other = (uint8_t)DUOFORGE_NO_POSITION;
    return e;
}

/* Appends a record; past the profile bound it only sets `overflow`. */
void dfi_events_push(dfi_events *events, const duoforge_event *e);

/* Player `player`'s view of a canonical record: HP of the opponent's
 * Pokemon as the percent display with its colour flag (decision 0005
 * section 6), the player's own HP exact. */
void dfi_event_project(const duoforge_event *in, uint32_t player, duoforge_event *out);

/* The HP of member `m` on a record, exact (no status once it has fainted). */
void dfi_event_set_hp(duoforge_event *e, const dfi_member *m);

/* [switch]: the member at `flat` (occupied) entered, with its HP. */
duoforge_event dfi_event_switch(const struct duoforge_battle *b, uint32_t flat);

/* The knowledge each player folds from the events it sees (decision 0007
 * section 6): the only writer of seen masks and knowledge in a step.
 * `before` is the battle at the start of the step (the occupants), `after`
 * the battle the step made; events before `first` were folded already and
 * only move the occupants. False when a line that shows HP carries no
 * percent display for the opponent (the step is then E_INVARIANT). */
bool dfi_events_fold_knowledge(const struct duoforge_battle *before, struct duoforge_battle *after,
                               const dfi_events *events, uint32_t first);

#endif
