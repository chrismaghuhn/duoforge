#ifndef DUOFORGE_DATA_SUPPORT_MANIFEST_H
#define DUOFORGE_DATA_SUPPORT_MANIFEST_H
/*
 * Support manifest of the combat closure (docs/decisions/0006 section 2):
 * which mechanics are implemented and tested. Setup of a CLOSURE battle
 * computes the mechanics both teams need and fails with E_UNSUPPORTED unless
 * every one of them is marked here. This is the no-fake-success gate: only
 * the step that implements and tests a mechanic may set its flag, and the
 * two reference teams pass only when the last flag is set (step 13).
 *
 * The manifest is code, not data: it is not part of the context fingerprint.
 */
#include <stdint.h>

#include "data/closure_tables.h"

typedef struct dfi_support_manifest {
    uint8_t core;           /* turn loop, damage, switching, fainting, win rule and Struggle */
    uint8_t mega_evolution; /* the Mega action and the forme change */
    uint8_t moves[DFI_MOVE_COUNT];
    uint8_t abilities[DFI_ABILITY_COUNT];
    uint8_t items[DFI_ITEM_COUNT];
} dfi_support_manifest;

/* The manifest of this build. */
extern const dfi_support_manifest dfi_support;

#endif
