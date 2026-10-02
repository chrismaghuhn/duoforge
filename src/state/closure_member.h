#ifndef DUOFORGE_STATE_CLOSURE_MEMBER_H
#define DUOFORGE_STATE_CLOSURE_MEMBER_H
/*
 * Members of the combat data kinds (docs/decisions/0006 section 2, 0009,
 * 0015): setup validation, the derived fields (stats, PP, stone flag), the
 * support gate and the member invariant. Every function reads the generated
 * pool tables only (the CLOSURE and TEAM_C kinds see their prefix of them
 * through dfi_kind_limits); none allocates or mutates global state.
 */
#include <stdbool.h>
#include <stdint.h>

#include <duoforge/duoforge.h>

#include "data/support_manifest.h"
#include "state/battle_internal.h"

/* Stored gender values equal the public DUOFORGE_GENDER_* values. */
#define DFI_GENDER_MALE 1u
#define DFI_GENDER_FEMALE 2u
#define DFI_GENDER_NONE 3u

/* True iff the gender is legal for a forme's gender rule. */
bool dfi_gender_legal(uint32_t gender_rule, uint32_t gender);

/* What a combat data kind may use (decisions 0009 section 3, 0015 section 2):
 * the CLOSURE kinds the closure prefix of the pool tables, the TEAM_C kinds
 * the extended prefix, the POOL kinds all of them; the DEV kinds also allow
 * No Ability. The ids of the kind's counts bound every id at setup and in
 * the invariants (an ability is bounded through its forme). The first four
 * kinds take a member's moves and ability from the forme's set; the POOL
 * kinds from the moves it learns and the abilities it may have. */
typedef struct dfi_kind_limits {
    uint32_t forme_count;     /* species ids below this */
    uint32_t move_count;      /* move ids below this */
    uint32_t item_count;      /* an item is 1 + its id, so at most this */
    uint32_t ability_count;   /* ability ids below this (an ability is 1 + its id) */
    uint32_t switch_flag_max; /* DFI_SWITCH_FAINTED; DFI_SWITCH_FLIP_TURN for TEAM_C; DFI_SWITCH_UTURN for POOL */
    uint32_t status_max;      /* DFI_STATUS_SLP; DFI_STATUS_PSN for TEAM_C and POOL */
    uint32_t vol_flags_mask;  /* DFI_VOL_* bits a position may carry: TEAM_C and POOL add the choice lock */
    uint32_t terrain_max;     /* DFI_TERRAIN_GRASSY; DFI_TERRAIN_PSYCHIC for TEAM_C and POOL */
    bool pool_rules;          /* POOL kinds: the learnable moves and legal abilities of the forme, not its set */
    bool dev;
} dfi_kind_limits;

/* Precondition: data_kind is one of the six combat kinds. */
dfi_kind_limits dfi_kind_limits_of(uint32_t data_kind);

/* The damaging self-switch moves: the switch flag that a position gets when the move pivots, and the move. The
 * flags are consecutive from DFI_SWITCH_FLIP_TURN, in the order of the table; dfi_kind_limits.switch_flag_max
 * of a kind is the last flag whose move its tables hold. A move with the SELF_SWITCH data flag and a status move
 * of Parting Shot's kind are not in it: a damaging one that is missing is refused at the move (E_UNSUPPORTED),
 * and the support manifest marks only moves that are here (tests/test_pool_tables.c). */
typedef struct dfi_pivot_move {
    uint8_t flag; /* DFI_SWITCH_* */
    uint16_t move; /* the move id of the pool tables: a u16, as everywhere (the pool has 511 moves; Volt Switch is above 255) */
} dfi_pivot_move;
#define DFI_PIVOT_MOVE_COUNT 2u
extern const dfi_pivot_move dfi_pivot_moves[DFI_PIVOT_MOVE_COUNT];

/* The entry for a move, or NULL when the move does not pivot with a flag of its own. */
const dfi_pivot_move *dfi_pivot_of_move(uint32_t move);
/* The entry for a switch flag value, or NULL when the value is none, Parting Shot's, Emergency Exit's or fainted. */
const dfi_pivot_move *dfi_pivot_of_flag(uint32_t flag);

/* The rules of what a member may have, one implementation for the setup, the
 * member invariant and the data query API (duoforge_data_*): none of them
 * restates a rule. */

/* A member may be of the forme: an id of the kind, and a base forme (a Mega
 * forme is reached in battle, never set up). */
bool dfi_forme_setup_legal(const dfi_kind_limits *lim, uint32_t species);

/* A member of base forme `species` may have the move (an id): the forme's set
 * under the first four kinds, the moves it learns under the POOL kinds. False
 * for an id at or beyond the kind's count. Precondition: species is below
 * the kind's forme count. */
bool dfi_forme_move_legal(const dfi_kind_limits *lim, uint32_t species, uint32_t move);

/* A member of base forme `species` may have the ability (1 + its id; 0 is No
 * Ability): the forme's own under the first four kinds, one of its legal
 * abilities under the POOL kinds; No Ability under the DEV kinds only. False
 * for an id beyond the kind's count. Same precondition. */
bool dfi_forme_ability_legal(const dfi_kind_limits *lim, uint32_t species, uint32_t ability);

/* The stone of the base forme as an item id, DFI_CLOSURE_NONE if it has none
 * (a member holds it as item 1 + this id). */
uint32_t dfi_forme_stone(uint32_t species);

/* Stat Points: each stat at most DUOFORGE_STAT_POINTS_MAX and their sum at
 * most DUOFORGE_STAT_POINTS_TOTAL_MAX. */
bool dfi_stat_points_valid(const uint32_t *sp);

/* The support gate by id (decision 0006 section 2): true iff the manifest
 * marks the id (an id at or beyond the tables' counts is not marked). The
 * gate of a setup is the conjunction of these over what a member has, and of
 * dfi_manifest_mega for a member that holds the stone of its forme, with the
 * turn core. */
bool dfi_manifest_move(const dfi_support_manifest *s, uint32_t move);
bool dfi_manifest_ability(const dfi_support_manifest *s, uint32_t ability);
bool dfi_manifest_item(const dfi_support_manifest *s, uint32_t item);
/* Mega Evolution of the base forme `species`: it has a Mega forme, the
 * manifest marks Mega Evolution and the ability the Mega forme brings. */
bool dfi_manifest_mega(const dfi_support_manifest *s, uint32_t species);

/* Validation of one registered member of a combat setup (the side rules,
 * Species Clause and Item Clause, are separate). */
bool dfi_closure_member_setup_valid(const dfi_kind_limits *lim, const duoforge_member_setup *m);

/* Species Clause and Item Clause over the registered members of a side.
 * Precondition: every registered member passed the member validation. */
bool dfi_closure_side_clauses_hold(const duoforge_side_setup *side);

/* True iff every mechanic the setup needs is marked in the manifest.
 * Precondition: the setup passed validation. */
bool dfi_closure_setup_supported(const dfi_support_manifest *manifest, const duoforge_battle_setup *setup);

/* The same gate for a battle (it may have been decoded): every mechanic its
 * registered members can reach is marked. Precondition: the battle passed
 * the invariant check under a CLOSURE context. */
bool dfi_closure_battle_supported(const dfi_support_manifest *manifest, const struct duoforge_battle *b);

/* Builds the member of a validated setup: derived stats, HP, PP, stone flag,
 * stored ids. Returns false only on an engine bug. */
bool dfi_closure_member_init(const duoforge_member_setup *src, dfi_member *dst);

/* The member invariant of combat data (reported as DFI_INV_MEMBER_EXTRA):
 * a base forme, a legal gender, nature and Stat Points in range, the current
 * ability of the forme (or No Ability for dev), an item the kind allows, the
 * stone flag and the Mega forme consistent with the item, stats and PP equal
 * to the formulas, moves of the set without repeats, and a status with a
 * matching counter. Under the POOL kinds the ability is one of the forme's
 * legal abilities and the moves are ones it learns. Precondition: the generic
 * member checks passed (species and move ids below the context's counts, move
 * count 1..4, pp <= pp_max, hp <= hp_max, stone flag <= 1). */
bool dfi_closure_member_valid(const dfi_kind_limits *lim, const dfi_member *m);
/* The part of dfi_closure_member_valid without the derived values and the
 * move legality (stats and HP maximum from the formulas, moves of the set
 * without repeats, PP maxima): forme, gender, nature, stat points, item
 * and Mega flags, ability, status and counter. The model-facing queries
 * run this part (decision 0011). Same precondition. */
bool dfi_closure_member_ranges(const dfi_kind_limits *lim, const dfi_member *m);

/* Mega Evolution of a member that holds its own stone (formeChange of the
 * Champions mod, isPermanent): the Mega forme's stats and ability; HP stays.
 * False, with *m unchanged, if it cannot. */
bool dfi_closure_member_mega_evolve(dfi_member *m);

/* WHITE-BOX: duoforge_battle_create without the support gate. Tests use it
 * to inspect the state a legal combat team produces while its mechanics are
 * not implemented; the public create always applies the gate. */
duoforge_status dfi_battle_create_ungated(const duoforge_context *ctx, const duoforge_battle_setup *setup,
                                          duoforge_battle **out_battle);

#endif
