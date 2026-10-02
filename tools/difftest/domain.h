#ifndef DUOFORGE_TOOLS_DIFFTEST_DOMAIN_H
#define DUOFORGE_TOOLS_DIFFTEST_DOMAIN_H
/*
 * The domain check of the differential runner: the set of choices that the
 * reference (Showdown) accepted from a side before a step, against the engine's
 * candidates for that side (duoforge_battle_candidates). Both are sets of
 * dfr_choice; the reference's comes in the records (a D record and its C
 * records), the engine's is made here from its candidates.
 *
 * A difference is a finding either way: a candidate that Showdown does not
 * accept is engine-only, a choice that Showdown accepts and the engine does not
 * offer is reference-only.
 */
#include <stddef.h>
#include <stdint.h>

#include "records.h"

#define DFD_EXAMPLES 3u /* the examples kept of each kind of difference */

typedef struct dfd_diff {
    uint32_t engine_only;
    uint32_t reference_only;
    dfr_choice engine_examples[DFD_EXAMPLES];    /* the first engine-only choices, in the order of the sets */
    dfr_choice reference_examples[DFD_EXAMPLES]; /* likewise; only min(count, DFD_EXAMPLES) are meaningful */
} dfd_diff;

/* A candidate of the engine as a member of a set of choices: its epoch and its side are not part of it. */
dfr_choice dfd_choice_of(const duoforge_side_choice *candidate);

/* The multiset `engine` (`engine_count` choices; they are sorted in place) against the strictly ascending set
 * `reference`. A choice that the engine lists twice is engine-only the second time: its domain is a set. */
void dfd_compare(dfr_choice *engine, uint32_t engine_count, const dfr_choice *reference, uint32_t reference_count,
                 dfd_diff *out);

/* A choice as text for the messages, NUL-terminated and cut to `cap` bytes:
 *   team 2 4 0 1              the roster indices picked, leads first
 *   slots move 1 -> 2 mega, switch 3          move_slot -> flat target position (none for no target)
 *   slots pass, none          a slot of kind PASS or NONE
 * The shape is the same for every choice, so a message can be parsed back into the kinds of its commands. */
void dfd_format(const dfr_choice *choice, char *out, size_t cap);

#endif
