#ifndef DUOFORGE_STATE_BATTLE_INTERNAL_H
#define DUOFORGE_STATE_BATTLE_INTERNAL_H
/*
 * Owned battle state v2 (in memory). sizeof and padding are NOT a contract:
 * persistence goes only through the canonical codec (docs/decisions/0002,
 * 0005). The state has no bool fields, so any byte pattern is a loadable (if
 * invalid) state; the invariant checker and codec are memory-safe on it.
 *
 * Canonical in-memory form (an invariant): every member at index >=
 * member_count is all-zero, every move slot at index >= move_count is
 * all-zero, an empty position is exactly {activation 0, occupant NONE},
 * brought_order entries at index >= popcount(brought_mask) are NONE and an
 * unsealed side has all-zero sealed commands.
 */
#include <stdint.h>

#include <duoforge/duoforge.h>

#include "rng/pcg32.h"

_Static_assert(DUOFORGE_MAX_ROSTER <= 8u, "brought_mask and seen_mask are u8");

#define DFI_OCCUPANT_NONE 0xFFu

/* Slot command kinds (also the public record values). */
#define DFI_SLOT_NONE 0u
#define DFI_SLOT_MOVE 1u
#define DFI_SLOT_SWITCH 2u
#define DFI_SLOT_PASS 3u

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
    uint8_t mega_capable; /* 0/1 synthetic stone-holder flag (open information) */
    dfi_move_slot moves[DUOFORGE_MAX_MOVE_SLOTS];
} dfi_member;

typedef struct dfi_active_slot {
    uint32_t activation_id; /* 0 = empty */
    uint8_t occupant;       /* roster index; DFI_OCCUPANT_NONE = empty */
} dfi_active_slot;

/* A sealed slot command (the accepted choice retained across a pause). */
typedef struct dfi_slot_cmd {
    uint8_t kind; /* DFI_SLOT_* */
    uint8_t move_slot;
    uint8_t target; /* flat position 0..3 or DUOFORGE_TARGET_NONE */
    uint8_t mega;
    uint8_t reserve;
} dfi_slot_cmd;

typedef struct dfi_side {
    dfi_member members[DUOFORGE_MAX_ROSTER];
    dfi_active_slot positions[DUOFORGE_ACTIVE_PER_SIDE];
    dfi_slot_cmd sealed_cmds[DUOFORGE_ACTIVE_PER_SIDE];
    uint8_t brought_order[DUOFORGE_MAX_ROSTER]; /* pick order; PRIVATE to the owner */
    uint8_t member_count;
    uint8_t brought_mask;
    uint8_t requested_slots; /* bit k: position k needs a slot command */
    uint8_t mega_used;       /* side-wide once-per-battle flag (public) */
    uint8_t sealed;          /* 0/1: sealed_cmds hold an accepted choice */
    uint8_t seen_mask;       /* knowledge of THIS player: opponent members seen in battle */
} dfi_side;

struct duoforge_battle {
    uint8_t context_fingerprint[DUOFORGE_DIGEST_SIZE];
    dfi_rng rng;
    uint32_t next_activation_id; /* >= 1; UINT32_MAX means exhausted */
    uint32_t request_epoch;      /* >= 1; UINT32_MAX means exhausted */
    uint8_t boundary_kind;       /* DUOFORGE_BOUNDARY_* */
    uint8_t request_mask;        /* bit s: side s must respond */
    dfi_side sides[DUOFORGE_SIDE_COUNT];
};

#endif
