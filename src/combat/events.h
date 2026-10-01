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

#include <duoforge/duoforge.h>

typedef struct dfi_events {
    duoforge_event rec[DUOFORGE_MAX_EVENTS];
    uint32_t count;
    bool overflow; /* more than DUOFORGE_MAX_EVENTS: the step fails with E_INVARIANT */
} dfi_events;

/* A record of `kind` about `position`; other NO_POSITION, everything else 0. */
duoforge_event dfi_event_make(uint32_t kind, uint32_t position);

/* Appends a record; past the profile bound it only sets `overflow`. */
void dfi_events_push(dfi_events *events, const duoforge_event *e);

/* Player `player`'s view of a canonical record: HP of the opponent's
 * Pokemon as the percent display with its colour flag (decision 0005
 * section 6), the player's own HP exact. */
void dfi_event_project(const duoforge_event *in, uint32_t player, duoforge_event *out);

#endif
