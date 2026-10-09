#ifndef DUOFORGE_STATE_INVARIANTS_H
#define DUOFORGE_STATE_INVARIANTS_H
/*
 * Structural invariant checker v3 (docs/decisions/0002, 0005, 0006). Reports the
 * FIRST violation in a fixed order. Every count, occupant, index and mask is
 * range-checked before it is used as an index or shift count, so the checker
 * is memory- and UB-safe on arbitrary bytes. It does not mutate.
 *
 * Deliberately allowed (structural, not reachability): fainted occupants and
 * reserves, pp 0, empty positions, any RNG state and draw count,
 * non-contiguous activation ids, REPLACEMENT/PIVOT/TERMINAL boundaries and
 * field, side, volatile, knowledge and queue values that no mechanic of the
 * closure produces. Decodability is therefore not reachability.
 *
 * The v3 ids check value ranges and canonical form only: TURN_COUNTER (0
 * exactly at TEAM_SELECTION), RESULT (nonzero exactly at TERMINAL), FIELD,
 * MEMBER_EXTRA (SYNTHETIC data has no stats, natures, statuses, items or
 * abilities: all zero; CLOSURE members agree with the generated tables and
 * formulas, see dfi_closure_member_valid), SIDE_CONDITION, VOLATILE (an empty position is the
 * cleared position), SWITCH_FLAG (exactly the requested slots of a PIVOT),
 * KNOWLEDGE (nothing about an unseen member; the display of an active member
 * is current; a revealed fact is a fact) and QUEUE (non-empty exactly at
 * PIVOT).
 *
 * The TAIL ids (docs/decisions/0015 section 7) check the POOL state tail: it
 * is all zero under every other kind (TAIL_KIND); under the POOL kinds each
 * value is in its range, a pair that is zero together is, a position without a
 * standing occupant has no tail, a soak type, a current ability and a toxic
 * stage are on a member standing on the field (step G11: a Mega Evolved one
 * can be Soaked; the type ends with its Mega Evolution when that comes later)
 * (TAIL_FIELD, TAIL_SIDE, TAIL_POSITION, TAIL_MEMBER). TAIL_SCHEMA and
 * TAIL_RESERVED are reported by the decoder only.
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
    DFI_INV_TURN_COUNTER,
    DFI_INV_RESULT,
    DFI_INV_FIELD,
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
    DFI_INV_MEMBER_EXTRA,
    DFI_INV_UNUSED_MEMBER_NONZERO,
    DFI_INV_BROUGHT_OUT_OF_RANGE,
    DFI_INV_BROUGHT_COUNT,
    DFI_INV_BROUGHT_ORDER,
    DFI_INV_MEGA_USED_RANGE,
    DFI_INV_SIDE_CONDITION,
    DFI_INV_EMPTY_WITH_ACTIVATION,
    DFI_INV_OCCUPIED_WITHOUT_ACTIVATION,
    DFI_INV_OCCUPANT_RANGE,
    DFI_INV_OCCUPANT_NOT_BROUGHT,
    DFI_INV_ACTIVATION_NOT_ISSUED,
    DFI_INV_OCCUPANT_DUPLICATE,
    DFI_INV_VOLATILE,
    DFI_INV_REQUESTED_SLOTS,
    DFI_INV_SWITCH_FLAG,
    DFI_INV_SEALED_RANGE,
    DFI_INV_SEALED_RULE,
    DFI_INV_SEALED_COMMAND,
    DFI_INV_ACTIVATION_DUPLICATE,
    DFI_INV_SEEN_MASK,
    DFI_INV_KNOWLEDGE,
    DFI_INV_QUEUE,
    DFI_INV_TAIL_KIND,     /* a tail that is not all zero under a kind without the POOL tail */
    DFI_INV_TAIL_SIDE,     /* a side condition (Wide Guard, Aurora Veil, Toxic Spikes, Stealth Rock, Spikes, Sticky Web) out of range */
    DFI_INV_TAIL_POSITION, /* a position's tail out of range, inconsistent, or nonzero at an empty or fainted position */
    DFI_INV_TAIL_MEMBER,   /* a roster member's soak type, current ability, forme, item or toxic stage out of range or where it cannot be */
    DFI_INV_TAIL_SCHEMA,   /* decode: the artifact's schema is not the one of the context's kind */
    DFI_INV_TAIL_RESERVED, /* decode: a reserved byte of the tail is not zero */
    DFI_INV_TAIL_FIELD,    /* Gravity's turns out of range (or the field block's pad byte is not zero) */
    DFI_INV_TAIL_PARTY,    /* step G46: a party order that is not the permutation of the brought members (the first n entries, n
                            * the brought count, each a brought member once; the rest empty; bits 18-23 zero) */
    DFI_INV_COUNT
} dfi_invariant;

/* Returns OK, E_CONTEXT_MISMATCH (fingerprint) or E_INVARIANT; writes
 * *out_first (nullable) only on failure. */
duoforge_status dfi_state_check(const duoforge_context *ctx, const struct duoforge_battle *b,
                                dfi_invariant *out_first);
/* The same check of `b`, given `validated` (nullable): a battle that passed
 * dfi_state_check under the same context. A member byte-identical to the
 * same member of `validated` passed the member rules, which depend on the
 * member alone, so they are not run again (the result is the same). */
duoforge_status dfi_state_check_since(const duoforge_context *ctx, const struct duoforge_battle *b,
                                      const struct duoforge_battle *validated, dfi_invariant *out_first);
/* The check of the model-facing queries (decision 0011): every rule of
 * dfi_state_check except a CLOSURE member's derived values and move legality
 * (dfi_closure_member_ranges runs instead of dfi_closure_member_valid). Every
 * index, count and divisor stays checked, so a query never reads out of
 * bounds. The rules left out run where the state changes (create, step,
 * decode) and in encode, digest and check. */
duoforge_status dfi_state_check_query(const duoforge_context *ctx, const struct duoforge_battle *b,
                                      dfi_invariant *out_first);
const char *dfi_invariant_name(dfi_invariant id);

/* Bit mask of occupied positions of a side (bounded loop, no stored index). */
uint32_t dfi_side_occupied_mask(const dfi_side *side);

#endif
