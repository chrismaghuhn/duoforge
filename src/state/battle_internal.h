#ifndef DUOFORGE_STATE_BATTLE_INTERNAL_H
#define DUOFORGE_STATE_BATTLE_INTERNAL_H
/*
 * Owned battle state v3 (in memory). sizeof and padding are NOT a contract:
 * persistence goes only through the canonical codec (docs/decisions/0002,
 * 0005, 0006). The state has no bool fields, so any byte pattern is a
 * loadable (if invalid) state; the invariant checker and codec are
 * memory-safe on it.
 *
 * Canonical in-memory form (an invariant): every member at index >=
 * member_count is all-zero, every move slot at index >= move_count is
 * all-zero, an empty position is exactly the cleared position (occupant
 * NONE, activation 0, neutral stages, no volatile), brought_order entries at
 * index >= popcount(brought_mask) are NONE, an unsealed side has all-zero
 * sealed commands, queue records at index >= queue_len are all-zero and the
 * knowledge about an unseen member is all-zero.
 *
 * v3 adds the groups of decision 0006 section 3; the combat of the closure
 * (src/combat/turn.c) writes them for CLOSURE data.
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

/* Value ranges of the v3 groups (decision 0006 section 3). */
#define DFI_RESULT_NONE 0u
#define DFI_RESULT_SIDE0 1u
#define DFI_RESULT_SIDE1 2u
#define DFI_RESULT_TIE 3u

#define DFI_WEATHER_NONE 0u
#define DFI_WEATHER_RAIN 1u
#define DFI_WEATHER_SUN 2u
#define DFI_TERRAIN_NONE 0u
#define DFI_TERRAIN_GRASSY 1u
#define DFI_FIELD_TURNS_MAX 5u  /* weather, terrain and Trick Room */
#define DFI_SCREEN_TURNS_MAX 8u /* Reflect and Light Screen with Light Clay */
#define DFI_TAILWIND_TURNS_MAX 4u

#define DFI_STAT_STAGE_COUNT 7u /* atk, def, spa, spd, spe, accuracy, evasion */
#define DFI_STAGE_NEUTRAL 6u    /* stored biased: 0..12 means -6..+6 */
#define DFI_STAGE_MAX 12u
#define DFI_VOL_FLINCH 1u
#define DFI_VOL_PROTECT 2u
#define DFI_VOL_FLASH_FIRE 4u
#define DFI_VOL_FLAGS_MAX 7u
#define DFI_VOL_HELPING_HAND 16u /* Team C: Helping Hand's volatile (duration 1, ends in the residual) */
#define DFI_VOL_UNBURDEN 32u    /* Team C: Unburden's volatile, set when its holder's item is used */
#define DFI_VOL_CHOICE_LOCK 64u /* Team C: Choice Scarf's choicelock; the move in locked_move */
#define DFI_VOL_NEWLY_SWITCHED 128u /* Team C: pokemon.newlySwitched, from its switch-in to the end of the turn */
#define DFI_STALL_LEVEL_MAX 6u /* success chance 1 / 3^level */
#define DFI_STALL_TURNS_MAX 2u
#define DFI_CONFUSION_TURNS_MAX 5u
#define DFI_CHARGE_TURNS_MAX 2u
#define DFI_MOVE_SLOT_STRUGGLE 4u /* queue move_slot value for Struggle */
#define DFI_SWITCH_NONE 0u
#define DFI_SWITCH_MOVE 1u           /* a self-switch move (Parting Shot) */
#define DFI_SWITCH_EMERGENCY_EXIT 2u /* the ability */
#define DFI_SWITCH_FAINTED 3u        /* checkFainted's flag, kept by a pass at a REPLACEMENT */
#define DFI_SWITCH_FLIP_TURN 4u      /* Flip Turn, a damaging self-switch move (TEAM_C kinds only) */
#define DFI_REVEALED_ITEM_CONSUMED 1u
#define DFI_REVEALED_MEGA 2u
#define DFI_MEMBER_STAT_COUNT 5u  /* atk, def, spa, spd, spe (HP is hp_max) */
#define DFI_STAT_POINT_COUNT 6u

/* Action queue (continuation data; non-empty exactly at a PIVOT boundary). */
#define DFI_QUEUE_CAPACITY 12u
#define DFI_Q_NONE 0u
#define DFI_Q_SWITCH_IN 1u  /* forced switch-in, order class 3 */
#define DFI_Q_RUN_SWITCH 2u /* entry effects, order class 101 */
#define DFI_Q_SWITCH 3u     /* voluntary switch, order class 103 */
#define DFI_Q_MEGA 4u       /* order class 104 */
#define DFI_Q_MOVE 5u       /* order class 200 */
#define DFI_Q_RESIDUAL 6u   /* order class 300 */

typedef struct dfi_member {
    uint16_t species_id; /* SYNTHETIC: caller id; later the base forme id */
    uint16_t hp;         /* 0 means fainted */
    uint16_t hp_max;
    uint16_t stats[DFI_MEMBER_STAT_COUNT]; /* current stats; SYNTHETIC: 0 */
    uint8_t move_count;
    uint8_t mega_capable; /* 0/1 stone-holder flag (open information) */
    uint8_t is_mega;      /* 0/1; persists for the battle */
    uint8_t gender;
    uint8_t nature;
    uint8_t stat_points[DFI_STAT_POINT_COUNT];
    uint8_t status;
    uint8_t status_counter; /* sleep and freeze turns */
    uint8_t item;           /* 0 = none */
    uint8_t item_consumed;  /* 0/1 */
    uint8_t ability;        /* 0 = none; the current ability */
    dfi_move_slot moves[DUOFORGE_MAX_MOVE_SLOTS];
} dfi_member;

/* An active position. Everything after occupant is the volatile block: it
 * belongs to the activation and is cleared when the position is entered or
 * left. */
typedef struct dfi_active_slot {
    uint32_t activation_id;               /* 0 = empty */
    uint8_t occupant;                     /* roster index; DFI_OCCUPANT_NONE = empty */
    uint8_t stages[DFI_STAT_STAGE_COUNT]; /* biased by DFI_STAGE_NEUTRAL */
    uint8_t flags;                        /* DFI_VOL_* */
    uint8_t stall_level;                  /* 0 = no stall volatile */
    uint8_t stall_turns;
    uint8_t confusion_turns; /* 0 = not confused */
    uint8_t charge_turns;    /* 0 = not charging */
    uint8_t locked_move;     /* 0 = none, else move slot + 1 */
    uint8_t locked_target;   /* flat position or DUOFORGE_TARGET_NONE while locked */
    uint8_t move_actions;    /* move actions since entry (saturating) */
    uint8_t switch_flag;     /* DFI_SWITCH_*: why this slot must switch at a PIVOT */
} dfi_active_slot;

/* What a player remembers about one opposing member (decision 0006
 * section 6): the HP display when last seen and the observed move uses. */
typedef struct dfi_knowledge {
    uint8_t hp_percent;
    uint8_t hp_flag;  /* DUOFORGE_HP_FLAG_* */
    uint8_t revealed; /* DFI_REVEALED_*: public facts seen (consumed item, Mega forme) */
    uint8_t moves_used[DUOFORGE_MAX_MOVE_SLOTS]; /* saturating */
} dfi_knowledge;

/* One queued action. The order class follows from the kind; priority and
 * speed are recomputed whenever the queue is sorted, so they are not state. */
typedef struct dfi_queue_record {
    uint32_t activation_id; /* binding of the actor; 0 for SWITCH_IN and RESIDUAL */
    uint8_t kind;           /* DFI_Q_* */
    uint8_t side;
    uint8_t slot;
    uint8_t move_slot; /* MOVE: 0..3 or DFI_MOVE_SLOT_STRUGGLE */
    uint8_t target;    /* MOVE: flat position or DUOFORGE_TARGET_NONE */
    uint8_t reserve;   /* SWITCH and SWITCH_IN: roster index */
} dfi_queue_record;

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
    dfi_knowledge knowledge[DUOFORGE_MAX_ROSTER]; /* of THIS player about the opposing members */
    uint8_t brought_order[DUOFORGE_MAX_ROSTER]; /* pick order; PRIVATE to the owner */
    uint8_t member_count;
    uint8_t brought_mask;
    uint8_t requested_slots; /* bit k: position k needs a slot command */
    uint8_t mega_used;       /* side-wide once-per-battle flag (public) */
    uint8_t sealed;          /* 0/1: sealed_cmds hold an accepted choice */
    uint8_t seen_mask;       /* knowledge of THIS player: opponent members seen in battle */
    uint8_t reflect_turns;
    uint8_t light_screen_turns;
    uint8_t tailwind_turns;
} dfi_side;

struct duoforge_battle {
    uint8_t context_fingerprint[DUOFORGE_DIGEST_SIZE];
    dfi_rng rng;
    uint32_t next_activation_id; /* >= 1; UINT32_MAX means exhausted */
    uint32_t request_epoch;      /* >= 1; UINT32_MAX means exhausted */
    uint8_t boundary_kind;       /* DUOFORGE_BOUNDARY_* */
    uint8_t request_mask;        /* bit s: side s must respond; 0 only at TERMINAL */
    uint16_t turn;               /* 0 at TEAM_SELECTION, then >= 1 */
    uint8_t result;              /* DFI_RESULT_*; nonzero exactly at TERMINAL */
    uint8_t weather;
    uint8_t weather_turns;
    uint8_t terrain;
    uint8_t terrain_turns;
    uint8_t trick_room_turns;
    uint8_t queue_len;
    dfi_queue_record queue[DFI_QUEUE_CAPACITY];
    dfi_side sides[DUOFORGE_SIDE_COUNT];
};

#endif
