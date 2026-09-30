#ifndef DUOFORGE_STATE_CLOSURE_MEMBER_H
#define DUOFORGE_STATE_CLOSURE_MEMBER_H
/*
 * Members of CLOSURE battles (docs/decisions/0006 section 2): setup
 * validation, the derived fields (stats, PP, stone flag), the support gate
 * and the member invariant. Every function reads the generated closure
 * tables only; none allocates or mutates global state.
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

/* Validation of one registered member of a CLOSURE setup (the side rules,
 * Species Clause and Item Clause, are separate). dev: the data kind allows
 * No Ability. */
bool dfi_closure_member_setup_valid(bool dev, const duoforge_member_setup *m);

/* Species Clause and Item Clause over the registered members of a side.
 * Precondition: every registered member passed the member validation. */
bool dfi_closure_side_clauses_hold(const duoforge_side_setup *side);

/* True iff every mechanic the setup needs is marked in the manifest.
 * Precondition: the setup passed validation. */
bool dfi_closure_setup_supported(const dfi_support_manifest *manifest, const duoforge_battle_setup *setup);

/* Builds the member of a validated setup: derived stats, HP, PP, stone flag,
 * stored ids. Returns false only on an engine bug. */
bool dfi_closure_member_init(const duoforge_member_setup *src, dfi_member *dst);

/* The member invariant of CLOSURE data (reported as DFI_INV_MEMBER_EXTRA):
 * a base forme, a legal gender, nature and Stat Points in range, the current
 * ability of the forme (or No Ability for dev), the stone flag and the Mega
 * forme consistent with the item, stats and PP equal to the formulas, moves
 * of the set without repeats, and a status with a matching counter.
 * Precondition: the generic member checks passed (species < 16, move ids
 * < 37, move count 1..4, pp <= pp_max, hp <= hp_max, stone flag <= 1). */
bool dfi_closure_member_valid(bool dev, const dfi_member *m);

/* WHITE-BOX: duoforge_battle_create without the support gate. Tests use it
 * to inspect the state a legal CLOSURE team produces while its mechanics are
 * not implemented; the public create always applies the gate. */
duoforge_status dfi_battle_create_ungated(const duoforge_context *ctx, const duoforge_battle_setup *setup,
                                          duoforge_battle **out_battle);

#endif
