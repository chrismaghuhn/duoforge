#ifndef DUOFORGE_STATE_CLOSURE_MEMBER_H
#define DUOFORGE_STATE_CLOSURE_MEMBER_H
/*
 * Members of the combat data kinds (docs/decisions/0006 section 2, 0009):
 * setup validation, the derived fields (stats, PP, stone flag), the support
 * gate and the member invariant. Every function reads the generated extended
 * tables only (the CLOSURE kinds see their closure prefix through
 * dfi_kind_limits); none allocates or mutates global state.
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

/* What a combat data kind may use (decision 0009 section 3): the CLOSURE
 * kinds the closure prefix of the extended tables, the TEAM_C kinds all of
 * them; the DEV kinds also allow No Ability. */
typedef struct dfi_kind_limits {
    uint32_t forme_count;     /* species ids below this */
    uint32_t item_count;      /* an item is 1 + its id, so at most this */
    uint32_t switch_flag_max; /* DFI_SWITCH_FAINTED; DFI_SWITCH_FLIP_TURN for TEAM_C */
    uint32_t status_max;      /* DFI_STATUS_SLP; DFI_STATUS_PSN for TEAM_C */
    uint32_t vol_flags_mask;  /* DFI_VOL_* bits a position may carry: TEAM_C adds the choice lock */
    bool dev;
} dfi_kind_limits;

/* Precondition: data_kind is one of the four combat kinds. */
dfi_kind_limits dfi_kind_limits_of(uint32_t data_kind);

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
 * matching counter. Precondition: the generic member checks passed (species
 * and move ids below the context's counts, move count 1..4, pp <= pp_max,
 * hp <= hp_max, stone flag <= 1). */
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
