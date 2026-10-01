#ifndef DUOFORGE_STATE_REQUEST_H
#define DUOFORGE_STATE_REQUEST_H
/*
 * Requests, complete joint side-choice domains and the decision step
 * (docs/decisions/0005). Everything here is model-facing except the
 * re-prompt transition, so:
 *  - a request, a count or a candidate list of player p is computed from
 *    p's own side data and public facts only (occupancy, mega_used);
 *  - validation of a submitted response checks it against p's offered
 *    domain by byte equality with an enumerated candidate, never through
 *    the opponent's data;
 *  - engine-side failures surface as one opaque E_INVARIANT.
 */
#include <stddef.h>
#include <stdint.h>

#include <duoforge/duoforge.h>

#include "rng/draw.h"
#include "state/battle_internal.h"

/* Caller-visible records have no implicit padding (decision 0002 section 8). */
_Static_assert(sizeof(duoforge_slot_command) == 8u, "slot command is 8 bytes");
_Static_assert(offsetof(duoforge_slot_command, reserved) == 5u, "slot command layout");
_Static_assert(sizeof(duoforge_side_choice) == 32u, "side choice is 32 bytes");
_Static_assert(offsetof(duoforge_side_choice, side) == 4u, "side choice layout: side");
_Static_assert(offsetof(duoforge_side_choice, picks) == 7u, "side choice layout: picks");
_Static_assert(offsetof(duoforge_side_choice, reserved) == 13u, "side choice layout: reserved");
_Static_assert(offsetof(duoforge_side_choice, slots) == 16u, "side choice layout: slots");
_Static_assert(sizeof(duoforge_decision_bundle) == 72u, "bundle is 72 bytes");
_Static_assert(offsetof(duoforge_decision_bundle, responses) == 8u, "bundle layout");
_Static_assert(sizeof(duoforge_request) == 12u, "request is 12 bytes");
_Static_assert(offsetof(duoforge_request, boundary_kind) == 8u, "request layout");
_Static_assert(sizeof(duoforge_step_result) == 8u, "step result is 8 bytes");

/* duoforge_battle_step with an optional TEST-ONLY tape (decision 0006
 * section 5): with tape != NULL the turn's draws come from the tape, and
 * *out_tape_used (nullable) receives how many entries were consumed, also on
 * failure. The public step passes NULL. */
duoforge_status dfi_battle_step_tape(const duoforge_context *ctx, duoforge_battle *battle,
                                     const duoforge_decision_bundle *bundle, const dfi_tape_entry *tape,
                                     uint32_t tape_len, uint32_t *out_tape_used, duoforge_step_result *out_result);

/* The same with the events of decision 0007: with buffers != NULL each
 * player's events of the step, as duoforge_battle_step_events. */
duoforge_status dfi_battle_step_events_tape(const duoforge_context *ctx, duoforge_battle *battle,
                                            const duoforge_decision_bundle *bundle, const dfi_tape_entry *tape,
                                            uint32_t tape_len, uint32_t *out_tape_used,
                                            duoforge_step_result *out_result, duoforge_event_buffer *buffers);

/* Rule-authorized re-prompt of one side at TURN (DECISION_CONTRACT section
 * 6): the other side's accepted choice is sealed, the request mask shrinks
 * to `side`, the epoch increments. No M2 mechanic triggers it; it exists so
 * the sealed-commitment machinery is real and tested. Preconditions
 * (E_INVARIANT otherwise): boundary TURN, request mask 3, the other side's
 * choice structurally valid. E_EXHAUSTED at the epoch limit, before any
 * mutation. Commits only after the invariant checker accepts the result. */
duoforge_status dfi_reprompt_side(const duoforge_context *ctx, struct duoforge_battle *b, uint32_t side,
                                  const duoforge_side_choice *other_accepted);

#endif
