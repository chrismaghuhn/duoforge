/*
 * PCG Random Number Generation for C.
 *
 * Copyright 2014 Melissa O'Neill <oneill@pcg-random.org>
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 * For additional information about the PCG random number generation scheme,
 * including its license and other licensing options, visit
 *
 *       http://www.pcg-random.org
 */
/*
 * Modified for DuoForge, 2026 (Apache License 2.0, section 4(b)).
 *
 * Derived from imneme/pcg-c-basic at commit
 * bc39cd76ac3d541e618606bcc6e1e5ba5e5e6aa3, file pcg_basic.c
 * (sha256 b6582a071a8a090a293621523c063d125a532d772a2a1eb7d60b3e695fe47746).
 * The license text is in third_party/pcg-c-basic/LICENSE.txt; provenance is
 * recorded in third_party/pcg-c-basic/PROVENANCE.md.
 *
 * Derived here: the multiplier, the seeding sequence, the LCG step, the
 * XSH-RR output function, the rejection threshold and the accept/reduce
 * predicate of pcg32_srandom_r, pcg32_random_r and pcg32_boundedrand_r.
 *
 * Modifications: renamed to dfi_pcg32_*; split into pure functions without
 * a global generator; the threshold uses the 64-bit form
 * (2^32 - bound) % bound instead of a unary minus; explicit casts.
 * Status codes, draw accounting, exhaustion and the rejection loop are
 * DuoForge code in src/rng/pcg32.c, which is not derived from pcg-c-basic.
 */
#include "rng/pcg32_derived.h"

#include "core/arith.h"

uint64_t dfi_pcg32_step(uint64_t state, uint64_t inc)
{
    return state * DFI_PCG32_MULT + inc; /* intentional mod 2^64 */
}

uint32_t dfi_pcg32_output(uint64_t old_state)
{
    /* Operands are 64-bit; the casts narrow already-wide values. */
    const uint32_t xorshifted = (uint32_t)(((old_state >> 18u) ^ old_state) >> 27u); /* wide-operands-reviewed */
    const uint32_t rot = (uint32_t)(old_state >> 59u); /* wide-operands-reviewed */
    return dfi_rotr32(xorshifted, rot);
}

void dfi_pcg32_seed_raw(uint64_t initstate, uint64_t initseq, uint64_t *state, uint64_t *inc)
{
    const uint64_t increment = (initseq << 1u) | 1u;
    uint64_t s = 0u;
    s = dfi_pcg32_step(s, increment);
    s += initstate; /* intentional mod 2^64 */
    s = dfi_pcg32_step(s, increment);
    *state = s;
    *inc = increment;
}

uint32_t dfi_pcg32_threshold(uint32_t bound)
{
    const uint64_t b = bound;
    return (uint32_t)((UINT64_C(0x100000000) - b) % b); /* wide-operands-reviewed */
}

bool dfi_pcg32_accept(uint32_t r, uint32_t bound, uint32_t threshold, uint32_t *out)
{
    if (r < threshold) {
        return false;
    }
    *out = r % bound;
    return true;
}
