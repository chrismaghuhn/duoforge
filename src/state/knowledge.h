#ifndef DUOFORGE_STATE_KNOWLEDGE_H
#define DUOFORGE_STATE_KNOWLEDGE_H
/*
 * Per-player knowledge of the opposing members (docs/decisions/0006
 * section 6). A player learns the HP display of a member while it is
 * active; after it leaves, the last display is what the player keeps.
 * Observations read this record, never the opposing member itself.
 */
#include <stdbool.h>
#include <stdint.h>

#include "state/battle_internal.h"

/* Champions HP display (sim/pokemon.ts:2060-2073 at the pin): floor percent,
 * minimum 1 while alive, colour flag at exactly 20 and 50. A zero hp_max
 * (corrupt state) gives 0 and no flag. Requires hp <= 65535. */
void dfi_hp_display(uint32_t hp, uint32_t hp_max, uint8_t *out_percent, uint8_t *out_flag);
/* True iff (percent, flag) is a pair dfi_hp_display can produce. */
bool dfi_hp_display_valid(uint32_t percent, uint32_t flag);

/* The opponent of `side` records the current HP display of member `roster`.
 * Preconditions: side < 2, roster < DUOFORGE_MAX_ROSTER. */
void dfi_knowledge_see_hp(struct duoforge_battle *b, uint32_t side, uint32_t roster);
/* Records the HP display of every active member (after an HP change).
 * Occupants out of range are skipped. */
void dfi_knowledge_refresh_active(struct duoforge_battle *b);

#endif
