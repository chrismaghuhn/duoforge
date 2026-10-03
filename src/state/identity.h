#ifndef DUOFORGE_STATE_IDENTITY_H
#define DUOFORGE_STATE_IDENTITY_H
/*
 * Identity model (internal in M1; conventions in docs/decisions/0002).
 *
 * - A position is (side, slot): side 0/1 corresponds to Showdown p1/p2 and
 *   slot 0/1 to a/b (naming only, no parity claim). The flat index
 *   side*2+slot gives 0=p1a, 1=p1b, 2=p2a, 3=p2b.
 * - A member is (side, roster index). The roster index is the registration
 *   order and never changes; brought selection and active occupancy are
 *   mappings, not reorderings.
 * - Every placement issues a fresh battle-wide activation id (1..UINT32_MAX-1,
 *   0 = none), including re-entry of the same member. A binding
 *   (position, activation id) therefore goes stale when the occupant is
 *   replaced, so a replacement never inherits an old occupant's command.
 *
 * These are internal in-process types; their padding is irrelevant because
 * they are never hashed, serialized or handed to callers. Every error leaves
 * the battle and every out-parameter untouched, and every primitive is
 * memory- and UB-safe on arbitrary (even corrupt) state.
 */
#include <stdbool.h>
#include <stdint.h>

#include <duoforge/duoforge.h>

#include "state/battle_internal.h"

typedef struct dfi_position_id {
    uint8_t side;
    uint8_t slot;
} dfi_position_id;

typedef struct dfi_member_id {
    uint8_t side;
    uint8_t roster;
} dfi_member_id;

typedef struct dfi_binding {
    dfi_position_id position;
    uint32_t activation_id;
} dfi_binding;

/* Writes the cleared position: no occupant, no activation, neutral stages,
 * no volatile state. */
void dfi_slot_clear(dfi_active_slot *slot);
/* True iff everything after occupant equals the cleared position. */
bool dfi_slot_volatile_is_clear(const dfi_active_slot *slot);
/* The POOL tail of the occupant of flat position `flat` (side * 2 + slot) when it leaves the field or faints
 * (decision 0015 section 7): the position's fields and the soak type, the current ability and the toxic stage
 * of the occupant, which end with the activation (the current item and forme of a member outlive it). Call it before the position is cleared (it reads the occupant). A no-op for an empty position. */
void dfi_tail_clear_occupant(struct duoforge_battle *b, uint32_t flat);

bool dfi_position_valid(dfi_position_id p);
/* Precondition: dfi_position_valid(p). */
uint32_t dfi_position_flat(dfi_position_id p);
bool dfi_member_valid(const struct duoforge_battle *b, dfi_member_id m);

/* Places a brought member into an empty position with a fresh activation id.
 * E_INVARIANT: invalid position, roster out of range, not brought, position
 * occupied, member active in the other slot, or a zero activation counter.
 * E_EXHAUSTED: activation ids exhausted. Does not check HP (a rules
 * decision). The position starts with a cleared volatile block, and the
 * opponent sees the member: seen bit and HP display. */
duoforge_status dfi_place(struct duoforge_battle *b, dfi_position_id p, uint8_t roster,
                          dfi_binding *out_binding);
/* E_INVARIANT for an invalid or empty position. Leaves the cleared
 * position; the opponent's knowledge of the member stays as last seen. */
duoforge_status dfi_vacate(struct duoforge_battle *b, dfi_position_id p);
/* E_INVARIANT for an invalid position; an empty position gives activation 0. */
duoforge_status dfi_current_binding(const struct duoforge_battle *b, dfi_position_id p, dfi_binding *out);
/* True iff the position is valid, occupied and holds this nonzero activation id. */
bool dfi_binding_is_current(const struct duoforge_battle *b, dfi_binding x);

#endif
