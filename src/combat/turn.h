#ifndef DUOFORGE_COMBAT_TURN_H
#define DUOFORGE_COMBAT_TURN_H
/*
 * The turn core of the combat closure (docs/decisions/0006 sections 4 and 5,
 * step 2 of tasks/M3_M4_COMBAT_CLOSURE.md), mirroring the pinned reference:
 *
 *  - the action queue: one move action per acting slot plus the residual
 *    action, sorted like Battle.speedSort (sim/battle.ts:429-463): order,
 *    then priority, then speed, ties shuffled with SPEED_TIE draws; sorted
 *    again before every move action (sim/battle.ts:2917-2926);
 *  - a move: target, PP, Protect and its stall counter, type immunity,
 *    accuracy with stages, critical hit, damage (src/core/modifier.c),
 *    secondary stat changes, self-boosts, Struggle with its recoil;
 *  - the residual phase: the Protect and stall durations;
 *  - the end of the turn: the next TURN boundary.
 *
 * Whatever a turn needs that is not implemented yet (switching, fainting,
 * Mega Evolution, any unmarked move, ability or item) fails with
 * E_UNSUPPORTED; the caller runs the turn on a working copy, so nothing is
 * committed then.
 *
 * Draws: only where a value can change the outcome (decision 0006 section
 * 5.1, proposal B). Shuffle bounds are relative to the tied group.
 */
#include <duoforge/duoforge.h>

#include "combat/events.h"
#include "rng/draw.h"
#include "state/battle_internal.h"

/* Runs the TURN boundary of a CLOSURE battle. responses[s] is the validated
 * side choice of each requested side (an unrequested side acts on its sealed
 * commands). On OK *b is at the next boundary. On failure *b is partially
 * advanced and must be discarded. */
duoforge_status dfi_turn_run(const duoforge_context *ctx, struct duoforge_battle *b,
                             const duoforge_side_choice responses[DUOFORGE_SIDE_COUNT], dfi_draws *draws,
                             dfi_events *events);

/* Whether the Pokemon at the position `flat` (an occupied one) may not switch at the TURN boundary: a standing foe has Shadow Tag
 * (step G41) and it is neither a holder nor a Ghost type. Read by the request builder (src/state/request.c); pivots, replacements
 * and forced switches ignore it. */
bool dfi_switch_trapped(const struct duoforge_battle *b, uint32_t flat);
/* Illusion (decision 0026): the disguise of the lead at `slot` of `side` at team start, if its holder disguises. */
bool dfi_illusion_lead_disguise(const struct duoforge_battle *b, uint32_t side, uint32_t slot, uint32_t *roster);

/* The start of a CLOSURE battle, right after team selection placed the
 * leads: their entry effects run (runSwitch of the reference's 'start'
 * action). A no-op for other data kinds. On failure *b must be discarded. */
duoforge_status dfi_turn_start(const duoforge_context *ctx, struct duoforge_battle *b, dfi_draws *draws,
                               dfi_events *events);

#endif
