#ifndef DFI_COMBAT_MULTIACCURACY_H
#define DFI_COMBAT_MULTIACCURACY_H

/*
 * The later hits of a multiaccuracy move (step G33). The Champions hit loop scales the move's accuracy by the two stages in
 * floating point with no floor (data/mods/champions/scripts.ts:481-510); the engine has no floating point outside the
 * tiebreak and compares `v x D < N` for the exact rational instead (turn.c, dfi_accuracy_check). That this equals the
 * reference was proved by tools/datagen/pool_families.js (checkG33) for the accuracy 90 of Triple Axel and every pair of stages
 * (169 of 169), and for no other accuracy: another base accuracy can put the real value next to an integer where the
 * binary64 arithmetic and the rational differ. A multiaccuracy move with another accuracy is refused (E_UNSUPPORTED) until its
 * proof is added there and the value here; the only multiaccuracy rows of the pool are Triple Axel (90) and Population Bomb
 * (90, not marked).
 */
#include <stdbool.h>
#include <stdint.h>

#define DFI_MULTIACCURACY_PROVEN_BASE 90u

static inline bool dfi_multiaccuracy_proven(uint32_t base_accuracy)
{
    return base_accuracy == DFI_MULTIACCURACY_PROVEN_BASE;
}

#endif
