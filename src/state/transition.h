#ifndef DUOFORGE_STATE_TRANSITION_H
#define DUOFORGE_STATE_TRANSITION_H
/*
 * Mechanics-free state transitions of M2 (docs/decisions/0005). Every
 * transition works on a stack copy and commits only after the invariant
 * checker accepts the result, so a failure leaves the battle unchanged.
 * Inputs are already validated against the offered domain by the caller;
 * a violated precondition is an engine bug (E_INVARIANT), never a caller
 * error.
 */
#include <duoforge/duoforge.h>

#include "state/battle_internal.h"

typedef struct dfi_team_picks {
    uint8_t picks[DUOFORGE_SIDE_COUNT][DUOFORGE_MAX_ROSTER];
} dfi_team_picks;

/* TEAM_SELECTION -> TURN. picks->picks[s][i] for i < brought_count are the
 * ordered roster indices of side s (entries beyond are ignored). The first
 * min(2, brought_count) picks lead in slot order; both sides' brought sets
 * are stored before any placement; placements run in canonical order
 * s0a, s0b, s1a, s1b; the epoch increments last. E_EXHAUSTED if the epoch
 * or the activation counter would overflow (checked before any mutation). */
duoforge_status dfi_apply_team_selection(const duoforge_context *ctx, struct duoforge_battle *b,
                                         const dfi_team_picks *picks);

#endif
