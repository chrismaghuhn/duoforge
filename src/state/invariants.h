#ifndef DUOFORGE_STATE_INVARIANTS_H
#define DUOFORGE_STATE_INVARIANTS_H
/*
 * Structural invariant checker v2 (docs/decisions/0002, 0005). Reports the
 * FIRST violation in a fixed order. Every count, occupant, index and mask is
 * range-checked before it is used as an index or shift count, so the checker
 * is memory- and UB-safe on arbitrary bytes. It does not mutate.
 *
 * Deliberately allowed (structural, not reachability): fainted occupants and
 * reserves, pp 0, empty positions, any RNG state and draw count,
 * non-contiguous activation ids, and REPLACEMENT/PIVOT boundaries that no
 * mechanic produces yet. Decodability is therefore not reachability.
 */
#include <duoforge/duoforge.h>

#include "state/battle_internal.h"

typedef enum dfi_invariant {
    DFI_INV_NONE = 0,
    DFI_INV_CONTEXT_FINGERPRINT,
    DFI_INV_RNG_INC_EVEN,
    DFI_INV_NEXT_ACTIVATION_ZERO,
    DFI_INV_BOUNDARY_KIND,
    DFI_INV_EPOCH_ZERO,
    DFI_INV_REQUEST_MASK,
    DFI_INV_MEMBER_COUNT,
    DFI_INV_SPECIES_RANGE,
    DFI_INV_HP_MAX_ZERO,
    DFI_INV_HP_ABOVE_MAX,
    DFI_INV_MOVE_COUNT,
    DFI_INV_MOVE_ID_RANGE,
    DFI_INV_PP_MAX_ZERO,
    DFI_INV_PP_ABOVE_MAX,
    DFI_INV_UNUSED_MOVE_NONZERO,
    DFI_INV_MEGA_CAPABLE_RANGE,
    DFI_INV_UNUSED_MEMBER_NONZERO,
    DFI_INV_BROUGHT_OUT_OF_RANGE,
    DFI_INV_BROUGHT_COUNT,
    DFI_INV_BROUGHT_ORDER,
    DFI_INV_MEGA_USED_RANGE,
    DFI_INV_EMPTY_WITH_ACTIVATION,
    DFI_INV_OCCUPIED_WITHOUT_ACTIVATION,
    DFI_INV_OCCUPANT_RANGE,
    DFI_INV_OCCUPANT_NOT_BROUGHT,
    DFI_INV_ACTIVATION_NOT_ISSUED,
    DFI_INV_OCCUPANT_DUPLICATE,
    DFI_INV_REQUESTED_SLOTS,
    DFI_INV_SEALED_RANGE,
    DFI_INV_SEALED_RULE,
    DFI_INV_SEALED_COMMAND,
    DFI_INV_ACTIVATION_DUPLICATE,
    DFI_INV_SEEN_MASK,
    DFI_INV_COUNT
} dfi_invariant;

/* Returns OK, E_CONTEXT_MISMATCH (fingerprint) or E_INVARIANT; writes
 * *out_first (nullable) only on failure. */
duoforge_status dfi_state_check(const duoforge_context *ctx, const struct duoforge_battle *b,
                                dfi_invariant *out_first);
const char *dfi_invariant_name(dfi_invariant id);

/* Bit mask of occupied positions of a side (bounded loop, no stored index). */
uint32_t dfi_side_occupied_mask(const dfi_side *side);

#endif
