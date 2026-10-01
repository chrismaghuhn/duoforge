#ifndef DUOFORGE_STATE_KNOWLEDGE_H
#define DUOFORGE_STATE_KNOWLEDGE_H
/*
 * Per-player knowledge of the opposing members (docs/decisions/0006
 * section 6). A player learns the HP display of a member while it is
 * active; after it leaves, the last display is what the player keeps.
 * Observations read this record, never the opposing member itself. In a
 * step only the event fold writes it (dfi_events_fold_knowledge, decision
 * 0007 section 6): what a player knows is what its events showed.
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

#endif
