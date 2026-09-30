#ifndef DUOFORGE_RNG_PCG32_H
#define DUOFORGE_RNG_PCG32_H
/*
 * DuoForge gameplay RNG contract (docs/decisions/0001), internal.
 *
 * PCG32 XSH-RR 64/32 exactly as pinned pcg-c-basic, per battle instance, no
 * global generator. Adds draw accounting, explicit exhaustion and an atomic
 * bounded draw. Pointers are non-NULL preconditions.
 *
 * - Seeding consumes zero counted draws (draws = 0 afterwards).
 * - Every raw 32-bit word counts as one draw, including rejected words of a
 *   bounded draw.
 * - draws == UINT64_MAX means exhausted: E_EXHAUSTED, nothing mutated.
 * - bound == 0 is an internal contract violation: E_INVARIANT, nothing
 *   mutated (upstream would divide by zero).
 * - A failed bounded draw leaves the generator and *out untouched, even when
 *   exhaustion hits between a rejected and an accepted word.
 */
#include <stdbool.h>
#include <stdint.h>

#include <duoforge/duoforge.h>

typedef struct dfi_rng {
    uint64_t state;
    uint64_t inc; /* always odd */
    uint64_t draws;
} dfi_rng;

void dfi_rng_seed(dfi_rng *rng, uint64_t initstate, uint64_t initseq);
duoforge_status dfi_rng_next_u32(dfi_rng *rng, uint32_t *out);
duoforge_status dfi_rng_bounded_u32(dfi_rng *rng, uint32_t bound, uint32_t *out);
bool dfi_rng_is_valid(const dfi_rng *rng);

#endif
