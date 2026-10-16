#ifndef DUOFORGE_COMBAT_MECHANICS_DAMAGE_CONTEXT_H
#define DUOFORGE_COMBAT_MECHANICS_DAMAGE_CONTEXT_H

/* Private damage implementation (restructure step 4, damage): the locals that the phases of dfi_get_damage share. Split
 * from src/combat/turn.c@dc9ce14b; every phase is forced inline into dfi_get_damage (DFI_ALWAYS_INLINE), so the
 * context is a stack object of that one frame (14 fields, 64 bytes on LP64: four pointers, four bools, six uint32_t),
 * never on the heap. */
#include "combat/run_internal.h"
#include "core/inline.h"

typedef struct dfi_damage_ctx {
    const dfi_member *a;        /* the attacker */
    const dfi_member *d;        /* the defender */
    const dfi_active_slot *ap;  /* the attacker's position */
    const dfi_active_slot *dp;  /* the defender's position */
    bool spread;                /* the hit is one of a spread move */
    bool crit;                  /* the critical hit, after the CriticalHit cancel (crit phase) */
    bool physical;              /* the move's category is physical (stats phase) */
    bool ok;                    /* no chained modifier overflowed (base power phase, tested in the attack phase) */
    uint32_t atk_index;         /* the stage index of the attack stat (stats phase) */
    uint32_t attack;            /* the attack stat (stats phase, then the attack phase) */
    uint32_t defense;           /* the defense stat (stats phase) */
    uint32_t damage;            /* the damage (0 from the stats phase, then the base damage and modify phases) */
    uint32_t base_power;        /* the base power after its chain (base power phase) */
    uint32_t mod;               /* the type effectiveness, DFI_BIAS6 neutral (base damage phase) */
} dfi_damage_ctx;

#endif
