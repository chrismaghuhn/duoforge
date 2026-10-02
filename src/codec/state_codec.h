#ifndef DUOFORGE_CODEC_STATE_CODEC_H
#define DUOFORGE_CODEC_STATE_CODEC_H
/*
 * Canonical battle state encoding v3 (docs/decisions/0002, 0005, 0006): a
 * 20-byte envelope (kind BATTLE_STATE, schema 3, semantics 3, total_length
 * 1009) and a fixed-size body. All slots are always emitted, unused ones in
 * their canonical form; there is no padding and no host-endianness
 * dependence. Never raw struct bytes.
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
 *    86     2  turn (u16)
 *    88     1  result (u8)
 *    89     5  weather, weather_turns, terrain, terrain_turns,
 *              trick_room_turns (u8 each)
 *    94     1  queue_len (u8)
 *    95   120  12 queue records of 10 bytes: kind, side, slot, move_slot,
 *              target, reserve (u8 each), activation_id (u32)
 *   215   397  side 0, then side 1 at 612:
 *                +0 member_count, +1 brought_mask, +2 requested_slots,
 *                +3 mega_used, +4 sealed, +5 seen_mask (u8 each),
 *                +6 brought_order[6] (u8, 0xFF unused),
 *                +12 reflect_turns, +13 light_screen_turns,
 *                +14 tailwind_turns (u8 each),
 *                +15 + 21*p position p:
 *                    +0 occupant (u8, 0xFF empty), +1 activation (u32),
 *                    +5 stages[7] (u8, biased by 6), +12 flags,
 *                    +13 stall_level, +14 stall_turns, +15 confusion_turns,
 *                    +16 charge_turns, +17 locked_move, +18 locked_target,
 *                    +19 move_actions, +20 switch_flag (u8 each),
 *                +57 + 5*p sealed command p: kind, move_slot, target, mega,
 *                    reserve,
 *                +67 + 7*m knowledge about opposing member m: hp_percent,
 *                    hp_flag, revealed, moves_used[4] (u8 each),
 *                +109 + 48*m member m (m = 0..5):
 *                    +0 species_id (u16), +2 hp (u16), +4 hp_max (u16),
 *                    +6 stats[5] (u16 each), +16 move_count,
 *                    +17 mega_capable, +18 is_mega, +19 gender, +20 nature,
 *                    +21 stat_points[6], +27 status, +28 status_counter,
 *                    +29 item, +30 item_consumed, +31 ability (u8 each),
 *                    +32 + 4*k move k: move_id (u16), pp (u8), pp_max (u8)
 *
 * The POOL state tail (docs/decisions/0015 section 7, schema 0x0103 = "v3 +
 * pool tail rev 1", 42 more bytes: 1051 in all). It is present exactly under
 * the two POOL data kinds, whose states carry that schema; the four other
 * kinds (and SYNTHETIC) keep schema 3 and the 1009 bytes above, unchanged.
 *
 *  1009    42  side 0, then side 1 at 1030:
 *                +0 wide_guard (u8), +1 2 reserved bytes (zero),
 *                +3 + 6*p position p: last_move, encore_slot, encore_turns,
 *                    throat_chop_turns, heal_block_turns (u8 each) and one
 *                    reserved byte (zero),
 *                +15 + m soak_type of roster member m (u8, m = 0..5)
 */
#include <stdbool.h>
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
#define DFI_ENC_TURN_OFF 86u
#define DFI_ENC_RESULT_OFF 88u
#define DFI_ENC_WEATHER_OFF 89u
#define DFI_ENC_WEATHER_TURNS_OFF 90u
#define DFI_ENC_TERRAIN_OFF 91u
#define DFI_ENC_TERRAIN_TURNS_OFF 92u
#define DFI_ENC_TRICK_ROOM_OFF 93u
#define DFI_ENC_QUEUE_LEN_OFF 94u
#define DFI_ENC_QUEUE_OFF 95u
#define DFI_ENC_QUEUE_RECORD_SIZE 10u
#define DFI_ENC_QUEUE_ACTIVATION_OFF 6u
#define DFI_ENC_SIDE_OFF 215u
#define DFI_ENC_SIDE_SIZE 397u

/* The state schema ids. The low byte is the layout of the body (3), the high byte the revision of the POOL tail
 * (0 = none). 4 stays free for the schema of certified pool teams (decision 0015 section 7). */
#define DFI_STATE_SCHEMA_V3 DUOFORGE_STATE_SCHEMA_VERSION
#define DFI_STATE_SCHEMA_POOL_TAIL_REV1 0x0103u
/* The POOL tail. */
#define DFI_ENC_TAIL_OFF DUOFORGE_STATE_V3_ENCODED_SIZE
#define DFI_ENC_TAIL_SIDE_SIZE 21u
#define DFI_ENC_TAIL_SIZE (DUOFORGE_SIDE_COUNT * DFI_ENC_TAIL_SIDE_SIZE)
#define DFI_ENC_TAIL_WIDE_GUARD_OFF 0u
#define DFI_ENC_TAIL_SIDE_RESERVED_OFF 1u
#define DFI_ENC_TAIL_SIDE_RESERVED_SIZE 2u
#define DFI_ENC_TAIL_POS_OFF 3u
#define DFI_ENC_TAIL_POS_SIZE 6u
#define DFI_ENC_TAIL_POS_LAST_MOVE_OFF 0u
#define DFI_ENC_TAIL_POS_ENCORE_SLOT_OFF 1u
#define DFI_ENC_TAIL_POS_ENCORE_TURNS_OFF 2u
#define DFI_ENC_TAIL_POS_THROAT_CHOP_OFF 3u
#define DFI_ENC_TAIL_POS_HEAL_BLOCK_OFF 4u
#define DFI_ENC_TAIL_POS_RESERVED_OFF 5u
#define DFI_ENC_TAIL_SOAK_OFF 15u
/* The encoded size of a state under a POOL kind, and the largest of any kind: buffers of tests and tools that do
 * not ask duoforge_battle_encoded_size. Not a public constant. */
#define DFI_STATE_POOL_ENCODED_SIZE (DFI_ENC_TAIL_OFF + DFI_ENC_TAIL_SIZE)
#define DFI_STATE_ENCODED_MAX DFI_STATE_POOL_ENCODED_SIZE

#define DFI_ENC_SIDE_MEMBER_COUNT_OFF 0u
#define DFI_ENC_SIDE_BROUGHT_OFF 1u
#define DFI_ENC_SIDE_REQUESTED_OFF 2u
#define DFI_ENC_SIDE_MEGA_USED_OFF 3u
#define DFI_ENC_SIDE_SEALED_OFF 4u
#define DFI_ENC_SIDE_SEEN_OFF 5u
#define DFI_ENC_SIDE_ORDER_OFF 6u
#define DFI_ENC_SIDE_REFLECT_OFF 12u
#define DFI_ENC_SIDE_LIGHT_SCREEN_OFF 13u
#define DFI_ENC_SIDE_TAILWIND_OFF 14u
#define DFI_ENC_SIDE_POS_OFF 15u
#define DFI_ENC_POS_SIZE 21u
#define DFI_ENC_POS_ACTIVATION_OFF 1u
#define DFI_ENC_POS_STAGES_OFF 5u
#define DFI_ENC_POS_FLAGS_OFF 12u
#define DFI_ENC_POS_STALL_LEVEL_OFF 13u
#define DFI_ENC_POS_STALL_TURNS_OFF 14u
#define DFI_ENC_POS_CONFUSION_OFF 15u
#define DFI_ENC_POS_CHARGE_OFF 16u
#define DFI_ENC_POS_LOCKED_MOVE_OFF 17u
#define DFI_ENC_POS_LOCKED_TARGET_OFF 18u
#define DFI_ENC_POS_MOVE_ACTIONS_OFF 19u
#define DFI_ENC_POS_SWITCH_FLAG_OFF 20u
#define DFI_ENC_SIDE_SEALED_CMD_OFF 57u
#define DFI_ENC_CMD_SIZE 5u
#define DFI_ENC_SIDE_KNOWLEDGE_OFF 67u
#define DFI_ENC_KNOWLEDGE_SIZE 7u
#define DFI_ENC_KNOWLEDGE_USED_OFF 3u
#define DFI_ENC_SIDE_MEMBERS_OFF 109u
#define DFI_ENC_MEMBER_SIZE 48u

#define DFI_ENC_MEMBER_SPECIES_OFF 0u
#define DFI_ENC_MEMBER_HP_OFF 2u
#define DFI_ENC_MEMBER_HP_MAX_OFF 4u
#define DFI_ENC_MEMBER_STATS_OFF 6u
#define DFI_ENC_MEMBER_MOVE_COUNT_OFF 16u
#define DFI_ENC_MEMBER_MEGA_OFF 17u
#define DFI_ENC_MEMBER_IS_MEGA_OFF 18u
#define DFI_ENC_MEMBER_GENDER_OFF 19u
#define DFI_ENC_MEMBER_NATURE_OFF 20u
#define DFI_ENC_MEMBER_STAT_POINTS_OFF 21u
#define DFI_ENC_MEMBER_STATUS_OFF 27u
#define DFI_ENC_MEMBER_STATUS_COUNTER_OFF 28u
#define DFI_ENC_MEMBER_ITEM_OFF 29u
#define DFI_ENC_MEMBER_ITEM_CONSUMED_OFF 30u
#define DFI_ENC_MEMBER_ABILITY_OFF 31u
#define DFI_ENC_MOVE_OFF 32u
#define DFI_ENC_MOVE_SIZE 4u

_Static_assert(DFI_ENC_FINGERPRINT_OFF == DFI_ENVELOPE_SIZE, "fingerprint follows the envelope");
_Static_assert(DFI_ENC_RNG_STATE_OFF == DFI_ENC_FINGERPRINT_OFF + DUOFORGE_DIGEST_SIZE, "rng follows the fingerprint");
_Static_assert(DFI_ENC_BOUNDARY_OFF == DFI_ENC_NEXT_ACTIVATION_OFF + 4u, "boundary follows the activation counter");
_Static_assert(DFI_ENC_TURN_OFF == DFI_ENC_EPOCH_OFF + 4u, "turn follows the epoch");
_Static_assert(DFI_ENC_QUEUE_OFF == DFI_ENC_QUEUE_LEN_OFF + 1u, "queue follows its length");
_Static_assert(DFI_ENC_QUEUE_ACTIVATION_OFF + 4u == DFI_ENC_QUEUE_RECORD_SIZE, "queue record is 10 bytes");
_Static_assert(DFI_ENC_QUEUE_OFF + DFI_QUEUE_CAPACITY * DFI_ENC_QUEUE_RECORD_SIZE == DFI_ENC_SIDE_OFF,
               "sides follow the queue");
_Static_assert(DFI_ENC_SIDE_ORDER_OFF + DUOFORGE_MAX_ROSTER == DFI_ENC_SIDE_REFLECT_OFF,
               "order precedes side conditions");
_Static_assert(DFI_ENC_POS_STAGES_OFF + DFI_STAT_STAGE_COUNT == DFI_ENC_POS_FLAGS_OFF, "stages precede flags");
_Static_assert(DFI_ENC_POS_SWITCH_FLAG_OFF + 1u == DFI_ENC_POS_SIZE, "position block is 21 bytes");
_Static_assert(DFI_ENC_SIDE_POS_OFF + DUOFORGE_ACTIVE_PER_SIDE * DFI_ENC_POS_SIZE == DFI_ENC_SIDE_SEALED_CMD_OFF,
               "positions precede sealed commands");
_Static_assert(DFI_ENC_SIDE_SEALED_CMD_OFF + DUOFORGE_ACTIVE_PER_SIDE * DFI_ENC_CMD_SIZE == DFI_ENC_SIDE_KNOWLEDGE_OFF,
               "sealed commands precede knowledge");
_Static_assert(DFI_ENC_KNOWLEDGE_USED_OFF + DUOFORGE_MAX_MOVE_SLOTS == DFI_ENC_KNOWLEDGE_SIZE,
               "knowledge record is 7 bytes");
_Static_assert(DFI_ENC_SIDE_KNOWLEDGE_OFF + DUOFORGE_MAX_ROSTER * DFI_ENC_KNOWLEDGE_SIZE == DFI_ENC_SIDE_MEMBERS_OFF,
               "knowledge precedes members");
_Static_assert(DFI_ENC_MEMBER_STATS_OFF + 2u * DFI_MEMBER_STAT_COUNT == DFI_ENC_MEMBER_MOVE_COUNT_OFF,
               "stats precede the move count");
_Static_assert(DFI_ENC_MEMBER_STAT_POINTS_OFF + DFI_STAT_POINT_COUNT == DFI_ENC_MEMBER_STATUS_OFF,
               "stat points precede the status");
_Static_assert(DFI_ENC_MOVE_OFF + DUOFORGE_MAX_MOVE_SLOTS * DFI_ENC_MOVE_SIZE == DFI_ENC_MEMBER_SIZE,
               "member block is 48 bytes");
_Static_assert(DFI_ENC_SIDE_MEMBERS_OFF + DUOFORGE_MAX_ROSTER * DFI_ENC_MEMBER_SIZE == DFI_ENC_SIDE_SIZE,
               "side block is 397 bytes");
_Static_assert(DFI_ENC_SIDE_OFF + DUOFORGE_SIDE_COUNT * DFI_ENC_SIDE_SIZE == DUOFORGE_STATE_V3_ENCODED_SIZE,
               "state v3 is 1009 bytes");
_Static_assert(DFI_ENC_TAIL_POS_OFF == DFI_ENC_TAIL_SIDE_RESERVED_OFF + DFI_ENC_TAIL_SIDE_RESERVED_SIZE,
               "positions follow the side's reserved bytes");
_Static_assert(DFI_ENC_TAIL_POS_OFF + DUOFORGE_ACTIVE_PER_SIDE * DFI_ENC_TAIL_POS_SIZE == DFI_ENC_TAIL_SOAK_OFF,
               "soak types follow the positions");
_Static_assert(DFI_ENC_TAIL_SOAK_OFF + DUOFORGE_MAX_ROSTER == DFI_ENC_TAIL_SIDE_SIZE, "tail side block is 21 bytes");
_Static_assert(DFI_ENC_TAIL_POS_RESERVED_OFF + 1u == DFI_ENC_TAIL_POS_SIZE, "tail position block is 6 bytes");
_Static_assert(DFI_STATE_POOL_ENCODED_SIZE == 1051u, "the state with the POOL tail is 1051 bytes");
_Static_assert(sizeof(dfi_pool_tail) == DFI_ENC_TAIL_SIZE - DUOFORGE_SIDE_COUNT * (DFI_ENC_TAIL_SIDE_RESERVED_SIZE +
                                                                                    DUOFORGE_ACTIVE_PER_SIDE),
               "the tail in memory has no padding and none of the reserved bytes");

/* True for the kinds whose states carry the POOL tail: _POOL and _POOL_DEV. */
bool dfi_context_has_pool_tail(const struct duoforge_context *ctx);
/* The schema id and the encoded size of the states of a context: schema 3 and 1009 bytes, or with the POOL tail
 * DFI_STATE_SCHEMA_POOL_TAIL_REV1 and 1051. */
uint16_t dfi_state_schema_of(const struct duoforge_context *ctx);
size_t dfi_state_encoded_size_of(const struct duoforge_context *ctx);

/* Writes dfi_state_encoded_size_of(ctx) bytes (at most DFI_STATE_ENCODED_MAX) unconditionally with fixed-capacity
 * loops; never branches on or indexes by a stored value, so it is memory-safe on corrupt state. The tail is
 * written exactly under the POOL kinds, whatever the state holds (the invariants refuse a tail elsewhere). Does
 * not validate. Returns the size written. */
size_t dfi_encode_unchecked(const struct duoforge_context *ctx, const struct duoforge_battle *b, uint8_t *out);

/* Strict decode into *out (only written on OK). Order: MALFORMED (size < 20,
 * magic) -> SCHEMA_MISMATCH (kind, a schema that is not v3 or v3 + pool tail
 * rev 1) -> SEMANTICS_MISMATCH -> MALFORMED (total_length != size, size not
 * that of the schema) -> CONTEXT_MISMATCH (embedded fingerprint) -> parse ->
 * MALFORMED (invariant; id in *out_invariant if non-NULL). The schema must
 * be the one of the context's kind and the reserved bytes of the tail zero:
 * both are invariants (DFI_INV_TAIL_SCHEMA, DFI_INV_TAIL_RESERVED). */
duoforge_status dfi_decode_state(const duoforge_context *ctx, const uint8_t *bytes, size_t size,
                                 struct duoforge_battle *out, dfi_invariant *out_invariant);

#endif
