#ifndef DUOFORGE_CODEC_STATE_CODEC_H
#define DUOFORGE_CODEC_STATE_CODEC_H
/*
 * Canonical battle state encoding v2 (docs/decisions/0002, 0005): a 20-byte
 * envelope (kind BATTLE_STATE, schema 2, semantics 2, total_length 438) and a
 * fixed-size body. All slots are always emitted, unused ones zero; there is
 * no padding and no host-endianness dependence. Never raw struct bytes.
 *
 *   off  size  field
 *     0    20  envelope
 *    20    32  context fingerprint
 *    52     8  rng.state (u64)
 *    60     8  rng.inc (u64)
 *    68     8  rng.draws (u64)
 *    76     4  next_activation_id (u32)
 *    80     1  boundary_kind (u8)
 *    81     1  request_mask (u8)
 *    82     4  request_epoch (u32)
 *    86   176  side 0, then side 1 at 262:
 *                +0 member_count, +1 brought_mask, +2 requested_slots,
 *                +3 mega_used, +4 sealed, +5 seen_mask (u8 each),
 *                +6 brought_order[6] (u8, 0xFF unused),
 *                +12 + 5*p position p: occupant (u8, 0xFF empty), activation (u32),
 *                +22 + 5*p sealed command p: kind, move_slot, target, mega, reserve,
 *                +32 + 24*m member m (m = 0..5):
 *                    +0 species_id (u16), +2 hp (u16), +4 hp_max (u16),
 *                    +6 move_count (u8), +7 mega_capable (u8), +8 + 4*k move k:
 *                        move_id (u16), pp (u8), pp_max (u8)
 */
#include <stddef.h>
#include <stdint.h>

#include <duoforge/duoforge.h>

#include "codec/envelope.h"
#include "state/battle_internal.h"
#include "state/invariants.h"

#define DFI_ENC_FINGERPRINT_OFF 20u
#define DFI_ENC_RNG_STATE_OFF 52u
#define DFI_ENC_RNG_INC_OFF 60u
#define DFI_ENC_RNG_DRAWS_OFF 68u
#define DFI_ENC_NEXT_ACTIVATION_OFF 76u
#define DFI_ENC_BOUNDARY_OFF 80u
#define DFI_ENC_REQUEST_MASK_OFF 81u
#define DFI_ENC_EPOCH_OFF 82u
#define DFI_ENC_SIDE_OFF 86u
#define DFI_ENC_SIDE_SIZE 176u
#define DFI_ENC_SIDE_MEMBER_COUNT_OFF 0u
#define DFI_ENC_SIDE_BROUGHT_OFF 1u
#define DFI_ENC_SIDE_REQUESTED_OFF 2u
#define DFI_ENC_SIDE_MEGA_USED_OFF 3u
#define DFI_ENC_SIDE_SEALED_OFF 4u
#define DFI_ENC_SIDE_SEEN_OFF 5u
#define DFI_ENC_SIDE_ORDER_OFF 6u
#define DFI_ENC_SIDE_POS_OFF 12u
#define DFI_ENC_POS_SIZE 5u
#define DFI_ENC_SIDE_SEALED_CMD_OFF 22u
#define DFI_ENC_CMD_SIZE 5u
#define DFI_ENC_SIDE_MEMBERS_OFF 32u
#define DFI_ENC_MEMBER_SIZE 24u
#define DFI_ENC_MEMBER_SPECIES_OFF 0u
#define DFI_ENC_MEMBER_HP_OFF 2u
#define DFI_ENC_MEMBER_HP_MAX_OFF 4u
#define DFI_ENC_MEMBER_MOVE_COUNT_OFF 6u
#define DFI_ENC_MEMBER_MEGA_OFF 7u
#define DFI_ENC_MOVE_OFF 8u
#define DFI_ENC_MOVE_SIZE 4u

_Static_assert(DFI_ENC_FINGERPRINT_OFF == DFI_ENVELOPE_SIZE, "fingerprint follows the envelope");
_Static_assert(DFI_ENC_RNG_STATE_OFF == DFI_ENC_FINGERPRINT_OFF + DUOFORGE_DIGEST_SIZE, "rng follows the fingerprint");
_Static_assert(DFI_ENC_BOUNDARY_OFF == DFI_ENC_NEXT_ACTIVATION_OFF + 4u, "boundary follows the activation counter");
_Static_assert(DFI_ENC_SIDE_OFF == DFI_ENC_EPOCH_OFF + 4u, "sides follow the epoch");
_Static_assert(DFI_ENC_SIDE_ORDER_OFF + DUOFORGE_MAX_ROSTER == DFI_ENC_SIDE_POS_OFF, "order precedes positions");
_Static_assert(DFI_ENC_SIDE_POS_OFF + DUOFORGE_ACTIVE_PER_SIDE * DFI_ENC_POS_SIZE == DFI_ENC_SIDE_SEALED_CMD_OFF,
               "positions precede sealed commands");
_Static_assert(DFI_ENC_SIDE_SEALED_CMD_OFF + DUOFORGE_ACTIVE_PER_SIDE * DFI_ENC_CMD_SIZE == DFI_ENC_SIDE_MEMBERS_OFF,
               "sealed commands precede members");
_Static_assert(DFI_ENC_MOVE_OFF + DUOFORGE_MAX_MOVE_SLOTS * DFI_ENC_MOVE_SIZE == DFI_ENC_MEMBER_SIZE,
               "member block is 24 bytes");
_Static_assert(DFI_ENC_SIDE_MEMBERS_OFF + DUOFORGE_MAX_ROSTER * DFI_ENC_MEMBER_SIZE == DFI_ENC_SIDE_SIZE,
               "side block is 176 bytes");
_Static_assert(DFI_ENC_SIDE_OFF + DUOFORGE_SIDE_COUNT * DFI_ENC_SIDE_SIZE == DUOFORGE_STATE_V2_ENCODED_SIZE,
               "state v2 is 438 bytes");

/* Writes all 438 bytes unconditionally with fixed-capacity loops; never
 * branches on or indexes by a stored value, so it is memory-safe on corrupt
 * state. Does not validate. */
void dfi_encode_unchecked(const struct duoforge_battle *b, uint8_t out[DUOFORGE_STATE_V2_ENCODED_SIZE]);

/* Strict decode into *out (only written on OK). Order: MALFORMED (size < 20,
 * magic) -> SCHEMA_MISMATCH (kind, schema) -> SEMANTICS_MISMATCH ->
 * MALFORMED (total_length != size, size != 438) -> CONTEXT_MISMATCH
 * (embedded fingerprint) -> parse -> MALFORMED (invariant; id in
 * *out_invariant if non-NULL). */
duoforge_status dfi_decode_state(const duoforge_context *ctx, const uint8_t *bytes, size_t size,
                                 struct duoforge_battle *out, dfi_invariant *out_invariant);

#endif
