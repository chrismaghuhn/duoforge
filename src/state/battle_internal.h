#ifndef DUOFORGE_STATE_BATTLE_INTERNAL_H
#define DUOFORGE_STATE_BATTLE_INTERNAL_H
/*
 * Owned battle state v1 (in memory). sizeof and padding are NOT a contract:
 * persistence goes only through the canonical codec (docs/decisions/0002).
 * The state has no bool fields, so any byte pattern is a loadable (if
 * invalid) state; the invariant checker and codec are memory-safe on it.
 *
 * Canonical in-memory form (an invariant): every member at index >=
 * member_count is all-zero, every move slot at index >= move_count is
 * all-zero, and an empty position is exactly {activation 0, occupant NONE}.
 */
#include <stdint.h>

#include <duoforge/duoforge.h>

#include "rng/pcg32.h"

_Static_assert(DUOFORGE_MAX_ROSTER <= 8u, "brought_mask is a u8");

#define DFI_OCCUPANT_NONE 0xFFu

typedef struct dfi_move_slot {
    uint16_t move_id;
    uint8_t pp;
    uint8_t pp_max;
} dfi_move_slot;

typedef struct dfi_member {
    uint16_t species_id;
    uint16_t hp; /* 0 means fainted */
    uint16_t hp_max;
    uint8_t move_count;
    dfi_move_slot moves[DUOFORGE_MAX_MOVE_SLOTS];
} dfi_member;

typedef struct dfi_active_slot {
    uint32_t activation_id; /* 0 = empty */
    uint8_t occupant;       /* roster index; DFI_OCCUPANT_NONE = empty */
} dfi_active_slot;

typedef struct dfi_side {
    dfi_member members[DUOFORGE_MAX_ROSTER];
    dfi_active_slot positions[DUOFORGE_ACTIVE_PER_SIDE];
    uint8_t member_count;
    uint8_t brought_mask;
} dfi_side;

struct duoforge_battle {
    uint8_t context_fingerprint[DUOFORGE_DIGEST_SIZE];
    dfi_rng rng;
    uint32_t next_activation_id; /* >= 1; UINT32_MAX means exhausted */
    dfi_side sides[DUOFORGE_SIDE_COUNT];
};

#endif
