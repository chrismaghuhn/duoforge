#ifndef DUOFORGE_COMBAT_ABILITIES_CURRENT_H
#define DUOFORGE_COMBAT_ABILITIES_CURRENT_H

#include "core/inline.h"
#include "data/pool_tables.h"
#include "state/battle_internal.h"

/* The family row of an ability code (1 + id, 0 for none); the row of no family
 * without one. The member invariant bounds the ability id, so the guard on it only
 * keeps the read in the table. The turn code passes the ability the member has now
 * (dfi_ability_family_now below: the POOL tail's ability_now, else the
 * sheet's); no rule here reads a member's sheet ability, so none can be asked the
 * wrong one. */
static inline dfi_ability_family dfi_ability_family_for(uint32_t ability)
{
    dfi_ability_family none = {DFI_ABILITY_FAMILY_NONE, DFI_FAMILY_PARAM_NONE};
    if (ability == 0u || ability > DFI_POOL_ABILITY_COUNT) {
        return none;
    }
    return dfi_pool_ability_family[ability - 1u];
}

/* The member's ability now, stored as 1 + id (0 = none): the one the member's sheet says, or the one that the POOL tail's
 * ability_now holds for it (Trace and the other effects that change an ability; zero under every other kind, and zero
 * unless something changed it). Every rule of the turn code reads the ability through this, never through
 * dfi_member.ability, which is the sheet's (and the Mega forme's) ability. `m` is a member of `b`; no heap, one tail
 * read for a member that is found on a side. */
static DFI_ALWAYS_INLINE uint32_t dfi_ability_code(const struct duoforge_battle *b, const dfi_member *m)
{
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const dfi_member *first = &b->sides[s].members[0];
        if (m >= first && m < first + DUOFORGE_MAX_ROSTER) {
            const uint32_t now = b->tail.sides[s].ability_now[m - first];
            return now != 0u ? now : m->ability;
        }
    }
    return m->ability;
}

/* The family row of the member's ability now (combat/abilities/current.h). */
static inline dfi_ability_family dfi_ability_family_now(const struct duoforge_battle *b, const dfi_member *m)
{
    return dfi_ability_family_for(m == NULL ? 0u : dfi_ability_code(b, m));
}

/* The member's ability is `id` (abilities are stored as 1 + id). */
static DFI_ALWAYS_INLINE bool dfi_ability(const struct duoforge_battle *b, const dfi_member *m, uint32_t id)
{
    return m != NULL && dfi_ability_code(b, m) == 1u + id;
}

#endif
