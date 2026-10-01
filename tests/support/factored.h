#ifndef DUOFORGE_TESTS_SUPPORT_FACTORED_H
#define DUOFORGE_TESTS_SUPPORT_FACTORED_H

/*
 * The factored domain read back independently of the engine (M7 spec
 * section 2): SLOTS as the allowed pairs in row-major order, TEAM_SELECTION
 * as the ordered tuples of distinct roster indices by lexicographic
 * unranking. The rank of a choice is its index in the joint list.
 */
#include <duoforge/duoforge.h>

/* The joint list of `d` as duoforge_battle_candidates lists it for `side`;
   returns its length. `out` holds DUOFORGE_MAX_CANDIDATES choices. */
uint32_t df_factored_expand(const duoforge_factored_domain *d, uint32_t side, duoforge_side_choice *out);

/* The factored choice of joint rank `k`, which must be below the length. */
duoforge_factored_choice df_factored_choice(const duoforge_factored_domain *d, uint32_t k);

#endif
