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
#define DFI_WEATHER_SAND 3u /* POOL (decision 0018): Sandstorm */
#define DFI_WEATHER_SNOW 4u /* POOL: Snowscape */
#define DFI_TERRAIN_NONE 0u
#define DFI_TERRAIN_GRASSY 1u
#define DFI_TERRAIN_PSYCHIC 2u /* Team C: Psychic Surge */
#define DFI_TERRAIN_ELECTRIC 3u /* POOL (step G25): Electric Surge, Electric Terrain */
#define DFI_TERRAIN_MISTY 4u    /* POOL (step G25): Misty Terrain */
#define DFI_FIELD_TURNS_MAX 5u  /* Trick Room, and weather and terrain without the rock or Terrain Extender */
#define DFI_FIELD_TURNS_EXTENDED_MAX 8u /* step G55: weather or terrain set with its rock or Terrain Extender */
#define DFI_SCREEN_TURNS_MAX 8u /* Reflect and Light Screen with Light Clay */
#define DFI_TAILWIND_TURNS_MAX 4u

#define DFI_STAT_STAGE_COUNT 7u /* atk, def, spa, spd, spe, accuracy, evasion */
#define DFI_STAGE_NEUTRAL 6u    /* stored biased: 0..12 means -6..+6 */
#define DFI_STAGE_MAX 12u
#define DFI_VOL_FLINCH 1u
#define DFI_VOL_PROTECT 2u
#define DFI_VOL_FLASH_FIRE 4u
#define DFI_VOL_FLAGS_MAX 7u
#define DFI_VOL_FOLLOW_ME 8u     /* Team C: Follow Me's volatile (duration 1, ends in the residual) */
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
/* A damaging self-switch move (selfSwitch: true) has a flag value of its own, so that the position says which move
 * pivots, and the switch event can name it: the table dfi_pivot_moves (state/closure_member.h) pairs each value with
 * its move. A value is valid under the kinds whose tables hold the move. */
#define DFI_SWITCH_FLIP_TURN 4u /* Flip Turn (the TEAM_C and POOL kinds) */
#define DFI_SWITCH_UTURN 5u     /* U-turn (the POOL kinds only), step G5 */
#define DFI_SWITCH_VOLT_SWITCH 6u /* Volt Switch (the POOL kinds only), step G32 */
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
    uint8_t move_slot; /* MOVE: 0..3, DFI_MOVE_SLOT_STRUGGLE or DUOFORGE_MOVE_SLOT_RECHARGE */
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

/* The POOL state tail (docs/decisions/0015 section 7, "v3 + pool tail rev 5"): the room that the pool mechanics need
 * beyond the schema-3 state (Encore, Throat Chop, Heal Block, Soak and Wide Guard of rev 1; the volatile, side and
 * field conditions and the per-member overrides that decision 0018 declares as view fields, rev 2; the Protect
 * variant, rev 3; the move result, the single-turn markers, the hits taken, the ability state, the lock counter, Quick
 * Guard, the second type and the member flags, rev 4; the Illusion state of decision 0026 and the slot and Future Sight
 * fields of lane A, rev 5, all zero until their steps) and nothing else.
 * It is part of the state only under the two POOL kinds (encode, decode, digest, equal, invariants); under the four
 * other kinds it is absent: all zero in memory (an invariant) and not in the encoding. Of the fields that rev 2
 * adds, only item_now is written so far (Knock Off, step G16). Every field is a plain byte or an aligned u16, so the structs have no padding and no pointer, and
 * their size is fixed (static asserts in codec/state_codec.h).
 *
 * The bounds below are those of the pinned data and of the research, not mechanics: a step that finds one wrong
 * changes the revision (0x0403) and says so. */
/* rev 1 */
#define DFI_TAIL_MOVE_MAX 5u          /* last_move: 0 none, 1..4 move slot + 1, 5 Struggle */
#define DFI_TAIL_ENCORE_SLOT_MAX 4u   /* encore_slot: 0 none, 1..4 move slot + 1 */
#define DFI_TAIL_ENCORE_TURNS_MAX 4u  /* Encore lasts 3 turns, 4 when the target had moved */
#define DFI_TAIL_THROAT_CHOP_MAX 2u
#define DFI_TAIL_HEAL_BLOCK_MAX 5u    /* Heal Block lasts 5 turns, 2 from Psychic Noise */
#define DFI_TAIL_WIDE_GUARD_MAX 1u    /* set by Wide Guard, ends in the residual of the turn */
/* rev 2, per position (data/moves.ts and data/conditions.ts of the pin) */
#define DFI_TAIL_PERISH_MAX 4u        /* perishsong: duration 4, the count shown is duration - 1 */
#define DFI_TAIL_TAUNT_MAX 4u         /* taunt: duration 3, 4 when the target had not moved */
#define DFI_TAIL_DISABLE_SLOT_MAX 4u  /* disable_slot: 0 none, 1..4 move slot + 1 */
#define DFI_TAIL_DISABLE_TURNS_MAX 5u /* disable: duration 5 */
#define DFI_TAIL_TRAP_TURNS_MAX 8u    /* partiallytrapped: 5 or 6 turns, 8 with a Grip Claw */
#define DFI_TAIL_SOURCE_MAX 4u        /* trap_source and leech_seed_source: 0 none, else flat position + 1 */
#define DFI_TAIL_YAWN_MAX 2u          /* yawn: duration 2 */
#define DFI_TAIL_STOCKPILE_MAX 3u     /* layers; stockpile_def and stockpile_spd count the boosts the layers gave */
#define DFI_TAIL_FLAG_MAX 1u          /* imprison, must_recharge, trap_band, focus_energy, charge, glaive_rush */
/* rev 3: the variants of the Protect volatile (Protect and Detect, Spiky Shield; Baneful Bunker is next when a Toxapex ability is marked) */
#define DFI_PROTECT_PLAIN 0u
#define DFI_PROTECT_SPIKY_SHIELD 1u
#define DFI_TAIL_PROTECT_KIND_MAX 1u
/* rev 4, per position (decision 0015 section 7, the audit of tail-rev4-proposal.md section 4.1; no mechanic writes them yet).
 * move_result: two bits for this turn (0-1) and two for the last turn (2-3), each DFI_MOVE_RESULT_*; the pin's
 * moveThisTurnResult and moveLastTurnResult (Stomping Tantrum reads `=== false`, so null must not count as a failure). */
#define DFI_MOVE_RESULT_UNDEFINED 0u
#define DFI_MOVE_RESULT_TRUE 1u
#define DFI_MOVE_RESULT_FALSE 2u
#define DFI_MOVE_RESULT_NULL 3u
#define DFI_TAIL_MOVE_RESULT_MASK 0x0Fu /* bits 4-7 are zero */
#define DFI_MOVE_RESULT_LAST_SHIFT 2u
/* single_turn: one-turn volatiles that the position's flags byte (full) cannot hold; both end in the residual of the turn, on
 * switch-out and on faint. RAGE_POWDER belongs to the Follow Me flag (the move that set it also sets that flag). */
#define DFI_SINGLE_TURN_RAGE_POWDER 1u
#define DFI_SINGLE_TURN_ROOST 2u
#define DFI_TAIL_SINGLE_TURN_MASK 3u    /* bits 2-7 are free and zero */
#define DFI_TAIL_HITS_TAKEN_MAX 6u      /* Rage Fist: power 50 + 50 * n is capped at 350 */
#define DFI_TAIL_ABILITY_STATE_MAX 6u   /* Supreme Overlord 0-5 fallen allies, Protean 0/1, Illusion roster index + 1 */
#define DFI_TAIL_LOCK_TURNS_MAX 3u      /* lockedmove (Outrage, Thrash, Petal Dance): 2 or 3 turns */
/* rev 4, per side and per roster member */
#define DFI_TAIL_QUICK_GUARD_MAX 1u     /* set by Quick Guard, ends in the residual of the turn */
/* hazard_order: the creation order of the hazards that are up on the side (the pin's effectOrder, sim/battle.ts:994-1000), which
 * is the order of the switch-in handlers. Two bits per slot, slot 0 in bits 1:0 (the first created) to slot 3 in bits 7:6; a slot
 * holds a DFI_HAZARD_* kind. With n kinds up (layers > 0) the first n slots are exactly those kinds, each once, and the others
 * are 0; n = 0 is the byte 0. A new kind takes slot n, more layers keep their slot, an ended kind leaves and the later ones
 * shift down, a kind that is put up again goes last. No engine reader yet (step G37 sets and reads it). */
#define DFI_HAZARD_STEALTH_ROCK 0u
#define DFI_HAZARD_SPIKES 1u
#define DFI_HAZARD_TOXIC_SPIKES 2u
#define DFI_HAZARD_STICKY_WEB 3u
#define DFI_HAZARD_KIND_COUNT 4u
#define DFI_TAIL_TYPE2_TYPELESS 255u    /* type2: 0 none, 1..DFI_TYPE_COUNT = type id + 1, 255 = the type is gone (Burn Up, Double Shock) */
#define DFI_TAIL_MEMBER_FLAG_HERO_SHOWN 1u /* member flags: Zero to Hero's message was shown (bits 1-7 are free and zero) */
#define DFI_TAIL_MEMBER_FLAGS_MASK 1u
/* rev 2, per side and per field */
#define DFI_TAIL_AURORA_VEIL_MAX 8u   /* 5 turns, 8 with Light Clay */
#define DFI_TAIL_TOXIC_SPIKES_MAX 2u
#define DFI_TAIL_STEALTH_ROCK_MAX 1u
#define DFI_TAIL_SPIKES_MAX 3u
#define DFI_TAIL_STICKY_WEB_MAX 1u
#define DFI_TAIL_GRAVITY_MAX 5u       /* gravity: duration 5 */
/* rev 2, per roster member */
#define DFI_TAIL_ITEM_NONE 255u       /* item_now: the member holds nothing (0 = as the member says, 1..254 = item id + 1) */
#define DFI_TAIL_TOXIC_STAGE_MAX 15u  /* the toxic counter stops at 15 */
#define DFI_TAIL_TOXIC_STATUS 6u      /* DUOFORGE_AILMENT_TOX (DFI_STATUS_TOX): the status that a toxic stage needs. POOL only (the
                                       * status bound of the other kinds is below it, step G36). */

typedef struct dfi_tail_pos {
    uint16_t substitute_hp;    /* 0 = no Substitute, else its HP (at most a quarter of the occupant's maximum HP) */
    uint16_t trap_move;        /* the move that partially traps the occupant: move id + 1, 0 = not trapped */
    uint8_t last_move;         /* Encore: the move the occupant used last */
    uint8_t encore_slot;       /* the one move slot the occupant may choose; 0 = not encored */
    uint8_t encore_turns;      /* 0 exactly when encore_slot is 0 */
    uint8_t throat_chop_turns; /* sound moves are barred while nonzero */
    uint8_t heal_block_turns;  /* healing and heal-flag moves are barred while nonzero */
    uint8_t perish;            /* Perish Song: the duration counter, 0 = none */
    uint8_t taunt_turns;       /* status moves are barred while nonzero */
    uint8_t disable_slot;      /* the move slot that Disable bars (move slot + 1); 0 exactly when disable_turns is 0 */
    uint8_t disable_turns;
    uint8_t imprison;          /* 0/1: the occupant used Imprison */
    uint8_t must_recharge;     /* 0/1: the occupant must recharge on its next action */
    uint8_t trap_turns;        /* partial trap: turns left; zero exactly when trap_source and trap_move are */
    uint8_t trap_source;       /* flat position of the trapper + 1 (never the occupant's own) */
    uint8_t trap_band;         /* 0/1: the trapper holds a Binding Band (1/6 per turn, not 1/8); 0 when not trapped */
    uint8_t leech_seed_source; /* flat position that gets the HP + 1, 0 = no Leech Seed (never the occupant's own) */
    uint8_t yawn_turns;        /* Yawn: turns until sleep, 0 = none */
    uint8_t focus_energy;      /* 0/1 */
    uint8_t stockpile;         /* layers 0..3 */
    uint8_t stockpile_def;     /* the Defense boosts the layers gave (0..stockpile) */
    uint8_t stockpile_spd;     /* the Special Defense boosts the layers gave (0..stockpile) */
    uint8_t charge;            /* 0/1: Charge, its next Electric move is doubled */
    uint8_t glaive_rush;       /* 0/1: hit as vulnerable until it moves again */
    uint8_t protect_kind;      /* tail rev 3 (step G20): which Protect variant the DFI_VOL_PROTECT volatile is, DFI_PROTECT_*;
                                * nonzero only while the volatile is up (it ends with it, in the residual) */
    uint8_t move_result;       /* tail rev 4: this turn's and last turn's result of the occupant's move, DFI_MOVE_RESULT_* in two bits each */
    uint8_t single_turn;       /* tail rev 4: DFI_SINGLE_TURN_* bits of the one-turn volatiles that the flags byte has no room for */
    uint8_t hits_taken;        /* tail rev 4: damaging hits the occupant has taken since it came in, 0..DFI_TAIL_HITS_TAKEN_MAX (Rage Fist) */
    uint8_t ability_state;     /* tail rev 4: the state of the occupant's current ability, 0..DFI_TAIL_ABILITY_STATE_MAX (its meaning goes with the ability) */
    uint8_t lock_turns;        /* tail rev 4: the turns that a lockedmove volatile has left, 0..DFI_TAIL_LOCK_TURNS_MAX */
    uint8_t slot_pending;      /* tail rev 5 (lane A, the slot's pending effect; bit 0 Healing Wish): zero, nothing writes it yet */
    uint8_t future_sight;      /* tail rev 5 (lane A): 2 bits of turns, 3 bits for the source, 3 spare; zero, nothing writes it yet */
} dfi_tail_pos;

/* tail rev 5 (decision 0026, Illusion), per side: the foe's shown state of the holder on this side. Nothing writes it yet,
 * every byte is zero and refused otherwise. shown: the roster index + 1 of the member whose name carries the values the foe
 * was shown for the holder, else 0; override: the values shown on that name (HP percent, HP colour flag, status, flags);
 * snapshot: the foe's knowledge of the disguise's row before it came in (hp percent, hp flag, revealed, moves used, status,
 * location); pending: the uses of the holder's moves that are not on the disguise's open sheet, per holder slot. */
typedef struct dfi_tail_illusion {
    uint8_t shown;
    uint8_t override[4];
    uint8_t snapshot[9];
    uint8_t pending[4];
} dfi_tail_illusion; /* 18 bytes, no padding */

typedef struct dfi_tail_side {
    dfi_tail_pos positions[DUOFORGE_ACTIVE_PER_SIDE];
    uint16_t ability_now[DUOFORGE_MAX_ROSTER]; /* per roster member: 0 = the member's own ability, else ability id + 1
                                                * (Trace, Skill Swap...); only for a member standing on the field */
    uint16_t forme_now[DUOFORGE_MAX_ROSTER];   /* 0 = the member's own forme, else forme id + 1 (Aegislash, Palafin...) */
    uint8_t wide_guard;                        /* 0/1: this turn only */
    uint8_t aurora_veil_turns;
    uint8_t toxic_spikes;                      /* layers */
    uint8_t stealth_rock;                      /* 0/1 */
    uint8_t spikes;                            /* layers */
    uint8_t sticky_web;                        /* 0/1 */
    uint8_t quick_guard;                       /* tail rev 4: 0/1, this turn only */
    uint8_t soak_type[DUOFORGE_MAX_ROSTER];    /* per roster member: 0 none, else type id + 1 (the type Soak set); DFI_TAIL_TYPE2_TYPELESS
                                                * (Double Shock, decision 0025): the first slot is ???, type2 is the second type (nonzero) */
    uint8_t item_now[DUOFORGE_MAX_ROSTER];     /* per roster member: 0 = as the member says, 1..254 = item id + 1,
                                                * DFI_TAIL_ITEM_NONE = holds nothing (Trick, Knock Off) */
    uint8_t toxic_stage[DUOFORGE_MAX_ROSTER];  /* per roster member: the toxic counter, 0 = none */
    uint8_t type2[DUOFORGE_MAX_ROSTER];        /* tail rev 4, per roster member: 0 none, type id + 1, DFI_TAIL_TYPE2_TYPELESS (Burn Up, Double Shock) */
    uint8_t member_flags[DUOFORGE_MAX_ROSTER]; /* tail rev 4, per roster member: DFI_TAIL_MEMBER_FLAG_* (Zero to Hero's message shown) */
    uint8_t hazard_order;                      /* tail rev 4: the creation order of the hazards that are up, 2 bits per slot (see above) */
    dfi_tail_illusion illusion;                /* tail rev 5 (decision 0026): the foe's shown state of the holder, zero until Illusion */
} dfi_tail_side;

/* party_order (step G46, decision 0015 section 7): the side.pokemon order of the pin, per side, as the permutation of the
 * brought members. Entry k (k = 0..5, the Showdown index in side.pokemon: the two actives, then the bench) holds roster index
 * + 1 in 3 bits, 0 = empty; the entries are packed little-endian into 3 bytes per side (entry k at bits 3k..3k+2 of the
 * 24-bit value; bits 18-23 are unused and zero). Entries 0..n-1 are the n brought members, n = popcount(brought_mask), and
 * the rest are 0: so the zeroed block is valid before the picks. It is written at team selection (pick order: the leads
 * first) and every switch-in swaps the incoming member's entry with the outgoing one's (sim/battle-actions.ts:120-133),
 * so a drag's draw (getRandomSwitchable: the bench in this order) and Ally Switch read it. Illusion reads it later. */
#define DFI_PARTY_BYTES_PER_SIDE 3u
#define DFI_PARTY_ENTRY_BITS 3u
#define DFI_PARTY_ENTRY_MASK 7u
#define DFI_PARTY_USED_BITS (DUOFORGE_MAX_ROSTER * DFI_PARTY_ENTRY_BITS)
/* A public view hides the foe's bench entries (positions 2 and up): the value 7 is no roster index + 1 (the roster is 6), so
 * it is never a state's entry and a from-view world replaces it with the hypothesis's order (view.c). */
#define DFI_PARTY_HIDDEN 7u
_Static_assert(DUOFORGE_MAX_ROSTER < DFI_PARTY_HIDDEN, "the hidden party entry is no roster index + 1");

typedef struct dfi_pool_tail {
    dfi_tail_side sides[DUOFORGE_SIDE_COUNT];
    uint8_t gravity_turns;
    uint8_t party_order[DUOFORGE_SIDE_COUNT][DFI_PARTY_BYTES_PER_SIDE]; /* step G46, see above */
    uint8_t field_pad; /* always zero: the reserved byte +7 of the encoded field block */
} dfi_pool_tail;

/* The packed value of one side's party order, and one entry of it (roster index + 1, 0 = empty). */
static inline uint32_t dfi_party_word(const dfi_pool_tail *t, uint32_t side)
{
    return (uint32_t)t->party_order[side][0] | (uint32_t)t->party_order[side][1] << 8 | (uint32_t)t->party_order[side][2] << 16;
}

static inline uint32_t dfi_party_entry(const dfi_pool_tail *t, uint32_t side, uint32_t k)
{
    return dfi_party_word(t, side) >> (k * DFI_PARTY_ENTRY_BITS) & DFI_PARTY_ENTRY_MASK;
}

static inline void dfi_party_put(dfi_pool_tail *t, uint32_t side, uint32_t k, uint32_t value)
{
    uint32_t w = dfi_party_word(t, side);
    w &= ~(DFI_PARTY_ENTRY_MASK << (k * DFI_PARTY_ENTRY_BITS));
    w |= (value & DFI_PARTY_ENTRY_MASK) << (k * DFI_PARTY_ENTRY_BITS);
    t->party_order[side][0] = (uint8_t)(w & 0xFFu); /* wide-operands-reviewed: masked to 8 bits */
    t->party_order[side][1] = (uint8_t)(w >> 8 & 0xFFu); /* wide-operands-reviewed: masked to 8 bits */
    t->party_order[side][2] = (uint8_t)(w >> 16 & 0xFFu); /* wide-operands-reviewed: masked to 8 bits */
}

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
    dfi_pool_tail tail; /* POOL kinds only; all zero otherwise */
};

/* The move that the occupant of the position (side * 2 + slot) used last, from the tail's last_move (move slot + 1) and the
 * occupant's moves; UINT32_MAX when it has used none, used Struggle or the position is empty. The tail is zero under
 * every kind but POOL. Step G30: Rage Powder shares the position's DFI_VOL_FOLLOW_ME bit with Follow Me, which is told
 * apart by this (the volatile is set by the move that the occupant is using, and nothing else is used before the
 * residual ends it, so the last move is the one that set it). */
static inline uint32_t dfi_last_move_id(const struct duoforge_battle *b, uint32_t flat)
{
    const uint32_t s = flat / 2u;
    const uint32_t p = flat % 2u;
    const uint32_t last = b->tail.sides[s].positions[p].last_move;
    const uint32_t occupant = b->sides[s].positions[p].occupant;
    if (last == 0u || last > DUOFORGE_MAX_MOVE_SLOTS || occupant >= DUOFORGE_MAX_ROSTER) {
        return UINT32_MAX;
    }
    const dfi_member *m = &b->sides[s].members[occupant];
    return last <= m->move_count ? (uint32_t)m->moves[last - 1u].move_id : UINT32_MAX;
}

#endif
