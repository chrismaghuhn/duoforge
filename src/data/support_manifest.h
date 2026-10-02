#ifndef DUOFORGE_DATA_SUPPORT_MANIFEST_H
#define DUOFORGE_DATA_SUPPORT_MANIFEST_H
/*
 * Support manifest of the combat closure (docs/decisions/0006 section 2):
 * which mechanics are implemented and tested. Setup of a CLOSURE battle
 * computes the mechanics both teams need and fails with E_UNSUPPORTED unless
 * every one of them is marked here; a step checks the same for the battle it
 * runs (a decoded state may hold anything the tables know). This is the
 * no-fake-success gate: only the step that implements and tests a mechanic
 * may set its flag, and the two reference teams pass only when the last flag
 * is set (step 13).
 *
 * The manifest covers the ids of the pool tables (decision 0015). Every id
 * that a step of the expansion adds starts unmarked; a step marks only what
 * it tested.
 *
 * The manifest is code, not data: it is not part of the context fingerprint.
 */
#include <stdint.h>

#include "data/pool_tables.h"

typedef struct dfi_support_manifest {
    uint8_t turn_core;      /* turn order, damage, stages, PP, Struggle (step 2); every battle needs it */
    uint8_t switching;      /* switching, fainting, replacement and the win rule (step 3); a step that
                               needs them fails with E_UNSUPPORTED until this is set */
    uint8_t mega_evolution; /* the Mega action and the forme change */
    uint8_t moves[DFI_POOL_MOVE_COUNT]; /* Struggle's entry is part of the turn core */
    uint8_t abilities[DFI_POOL_ABILITY_COUNT];
    uint8_t items[DFI_POOL_ITEM_COUNT];
} dfi_support_manifest;

/* The manifest of this build. */
extern const dfi_support_manifest dfi_support;

#endif
