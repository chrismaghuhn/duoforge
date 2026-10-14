#ifndef DUOFORGE_COMBAT_FIELD_SIDE_CONDITIONS_H
#define DUOFORGE_COMBAT_FIELD_SIDE_CONDITIONS_H

/* Private field-family implementation. Included by turn.c at the
 * existing helper dependency boundary; turn flow owns evaluation order. */
#include "combat/run_internal.h"

/* The side conditions that count down in the residual, by sub-order: Reflect, Light Screen, Tailwind, Aurora Veil. */
#define DFI_SIDE_KINDS 4u

/* side.removeSideCondition for the three screens that Psychic Fangs breaks (step G30), in the order of its onTryHit:
 * Reflect, Light Screen, Aurora Veil. A condition that is not up is not removed and shows nothing; one that is shows
 * -sideend|side|its name. */
static inline void dfi_break_screens(dfi_run *r, uint32_t side)
{
    struct duoforge_battle *b = r->b;
    static const uint8_t kinds[3] = {DUOFORGE_SIDE_REFLECT, DUOFORGE_SIDE_LIGHT_SCREEN, DUOFORGE_SIDE_AURORA_VEIL};
    uint8_t *turns[3] = {&b->sides[side].reflect_turns, &b->sides[side].light_screen_turns,
                         &b->tail.sides[side].aurora_veil_turns};
    for (uint32_t k = 0u; k < 3u; ++k) {
        if (*turns[k] != 0u) {
            *turns[k] = 0u;
            duoforge_event e = dfi_event_make(DUOFORGE_EVENT_SIDE_END, DUOFORGE_NO_POSITION);
            e.detail = (uint8_t)side;
            e.amount = kinds[k];
            dfi_emit(r, &e); /* [-sideend] */
        }
    }
}

static inline uint8_t *dfi_side_turns(struct duoforge_battle *b, uint32_t s, uint32_t k)
{
    dfi_side *sd = &b->sides[s];
    return k == 0u ? &sd->reflect_turns
           : k == 1u ? &sd->light_screen_turns
           : k == 2u ? &sd->tailwind_turns
                     : &b->tail.sides[s].aurora_veil_turns; /* the tail is zero under every kind but POOL */
}

#endif
