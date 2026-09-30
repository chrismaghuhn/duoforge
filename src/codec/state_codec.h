#ifndef DUOFORGE_CODEC_STATE_CODEC_H
#define DUOFORGE_CODEC_STATE_CODEC_H
/*
 * Canonical battle state encoding v1 (docs/decisions/0002): a 20-byte
 * envelope (kind BATTLE_STATE, schema 1, semantics 1, total_length 380) and a
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
 *    80   150  side 0, then side 1 at 230:
 *                +0 member_count (u8), +1 brought_mask (u8),
 *                +2 pos0 occupant (u8, 0xFF empty), +3 pos0 activation (u32),
 *                +7 pos1 occupant (u8), +8 pos1 activation (u32),
 *                +12 + 23*m member m (m = 0..5):
 *                    +0 species_id (u16), +2 hp (u16), +4 hp_max (u16),
 *                    +6 move_count (u8), +7 + 4*k move k (k = 0..3):
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
#define DFI_ENC_SIDE_OFF 80u
#define DFI_ENC_SIDE_SIZE 150u
#define DFI_ENC_SIDE_MEMBER_COUNT_OFF 0u
#define DFI_ENC_SIDE_BROUGHT_OFF 1u
#define DFI_ENC_SIDE_POS_OFF 2u
#define DFI_ENC_POS_SIZE 5u
#define DFI_ENC_SIDE_MEMBERS_OFF 12u
#define DFI_ENC_MEMBER_SIZE 23u
#define DFI_ENC_MEMBER_SPECIES_OFF 0u
#define DFI_ENC_MEMBER_HP_OFF 2u
#define DFI_ENC_MEMBER_HP_MAX_OFF 4u
#define DFI_ENC_MEMBER_MOVE_COUNT_OFF 6u
#define DFI_ENC_MOVE_OFF 7u
#define DFI_ENC_MOVE_SIZE 4u

_Static_assert(DFI_ENC_FINGERPRINT_OFF == DFI_ENVELOPE_SIZE, "fingerprint follows the envelope");
_Static_assert(DFI_ENC_RNG_STATE_OFF == DFI_ENC_FINGERPRINT_OFF + DUOFORGE_DIGEST_SIZE, "rng follows the fingerprint");
_Static_assert(DFI_ENC_SIDE_OFF == DFI_ENC_NEXT_ACTIVATION_OFF + 4u, "sides follow the activation counter");
_Static_assert(DFI_ENC_SIDE_POS_OFF + DUOFORGE_ACTIVE_PER_SIDE * DFI_ENC_POS_SIZE == DFI_ENC_SIDE_MEMBERS_OFF,
               "positions precede members");
_Static_assert(DFI_ENC_MOVE_OFF + DUOFORGE_MAX_MOVE_SLOTS * DFI_ENC_MOVE_SIZE == DFI_ENC_MEMBER_SIZE,
               "member block is 23 bytes");
_Static_assert(DFI_ENC_SIDE_MEMBERS_OFF + DUOFORGE_MAX_ROSTER * DFI_ENC_MEMBER_SIZE == DFI_ENC_SIDE_SIZE,
               "side block is 150 bytes");
_Static_assert(DFI_ENC_SIDE_OFF + DUOFORGE_SIDE_COUNT * DFI_ENC_SIDE_SIZE == DUOFORGE_STATE_V1_ENCODED_SIZE,
               "state v1 is 380 bytes");

/* Writes all 380 bytes unconditionally with fixed-capacity loops; never
 * branches on or indexes by a stored value, so it is memory-safe on corrupt
 * state. Does not validate. */
void dfi_encode_unchecked(const struct duoforge_battle *b, uint8_t out[DUOFORGE_STATE_V1_ENCODED_SIZE]);

/* Strict decode into *out (only written on OK). Order: MALFORMED (size < 20,
 * magic) -> SCHEMA_MISMATCH (kind, schema) -> SEMANTICS_MISMATCH ->
 * MALFORMED (total_length != size, size != 380) -> CONTEXT_MISMATCH
 * (embedded fingerprint) -> parse -> MALFORMED (invariant; id in
 * *out_invariant if non-NULL). */
duoforge_status dfi_decode_state(const duoforge_context *ctx, const uint8_t *bytes, size_t size,
                                 struct duoforge_battle *out, dfi_invariant *out_invariant);

#endif
