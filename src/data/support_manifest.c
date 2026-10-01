#include "data/support_manifest.h"

/* Step 2 (turn core): turn order with speed ties, single-target and spread
 * damage, accuracy, critical hits, the random factor, STAB, the type chart,
 * stat stages, self-boosting moves, secondary stat changes, PP, Struggle and
 * Protect with its stall counter. Every move marked here uses nothing else.
 * Step 3: voluntary switches, fainting, replacements and the win rule.
 * No ability, item, status or Mega Evolution is implemented yet. */
const dfi_support_manifest dfi_support = {
    .turn_core = 1u,
    .switching = 1u,
    .moves =
        {
            [DFI_MOVE_HIGHHORSEPOWER] = 1u,
            [DFI_MOVE_PROTECT] = 1u,
            [DFI_MOVE_MUDDYWATER] = 1u,
            [DFI_MOVE_COIL] = 1u,
            [DFI_MOVE_SHADOWSNEAK] = 1u,
            [DFI_MOVE_SWORDSDANCE] = 1u,
            [DFI_MOVE_FOCUSBLAST] = 1u,
            [DFI_MOVE_SHADOWBALL] = 1u,
            [DFI_MOVE_NASTYPLOT] = 1u,
            [DFI_MOVE_DRILLRUN] = 1u,
            [DFI_MOVE_DRAGONPULSE] = 1u,
            [DFI_MOVE_SNARL] = 1u,
            [DFI_MOVE_PSYCHIC] = 1u,
            [DFI_MOVE_SPIRITBREAK] = 1u,
        },
};
