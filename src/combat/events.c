/*
 * Event records of a step (docs/decisions/0007 section 6). The engine
 * records each event once with exact values; each player receives a
 * projection in which the opponent's HP is shown as the percent display,
 * as on that player's screen.
 */
#include "combat/events.h"

#include <stddef.h>
#include <string.h>

#include "state/knowledge.h"

_Static_assert(sizeof(duoforge_event) == 20u, "event is 20 bytes");
_Static_assert(offsetof(duoforge_event, id) == 4u, "event layout: id");
_Static_assert(offsetof(duoforge_event, hp) == 8u, "event layout: hp");
_Static_assert(offsetof(duoforge_event, hp_kind) == 12u, "event layout: hp kind");
_Static_assert(offsetof(duoforge_event, reserved) == 18u, "event layout: reserved");

duoforge_event dfi_event_make(uint32_t kind, uint32_t position)
{
    duoforge_event e;
    memset(&e, 0, sizeof e);
    e.kind = (uint8_t)kind;         /* <= DUOFORGE_EVENT_RESULT */
    e.position = (uint8_t)position; /* < 4 or DUOFORGE_NO_POSITION */
    e.other = (uint8_t)DUOFORGE_NO_POSITION;
    return e;
}

void dfi_events_push(dfi_events *events, const duoforge_event *e)
{
    if (events->count >= DUOFORGE_MAX_EVENTS) {
        events->overflow = true;
        return;
    }
    events->rec[events->count] = *e;
    events->count += 1u;
}

void dfi_event_project(const duoforge_event *in, uint32_t player, duoforge_event *out)
{
    *out = *in;
    if (in->hp_kind != DUOFORGE_HP_EXACT || in->position == DUOFORGE_NO_POSITION ||
        (uint32_t)in->position / 2u == player) {
        return;
    }
    uint8_t percent = 0u;
    uint8_t flag = 0u;
    dfi_hp_display(in->hp, in->hp_max, &percent, &flag);
    out->hp = percent;
    out->hp_max = 100u;
    out->hp_kind = (uint8_t)DUOFORGE_HP_PERCENT;
    out->hp_flag = flag;
}
