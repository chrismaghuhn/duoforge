#include "rng/pcg32.h"

#include "rng/pcg32_derived.h"

void dfi_rng_seed(dfi_rng *rng, uint64_t initstate, uint64_t initseq)
{
    uint64_t state = 0u;
    uint64_t inc = 0u;
    dfi_pcg32_seed_raw(initstate, initseq, &state, &inc);
    rng->state = state;
    rng->inc = inc;
    rng->draws = 0u;
}

duoforge_status dfi_rng_next_u32(dfi_rng *rng, uint32_t *out)
{
    if (rng->draws == UINT64_MAX) {
        return DUOFORGE_E_EXHAUSTED;
    }
    const uint64_t old_state = rng->state;
    rng->state = dfi_pcg32_step(old_state, rng->inc);
    rng->draws += 1u;
    *out = dfi_pcg32_output(old_state);
    return DUOFORGE_OK;
}

duoforge_status dfi_rng_bounded_u32(dfi_rng *rng, uint32_t bound, uint32_t *out)
{
    if (bound == 0u) {
        return DUOFORGE_E_INVARIANT;
    }
    const uint32_t threshold = dfi_pcg32_threshold(bound);
    /* Work on a copy; commit only when a word is accepted. Every attempt
     * consumes a counted draw, so the u64 counter bounds this loop. */
    dfi_rng work = *rng;
    for (;;) {
        uint32_t r = 0u;
        const duoforge_status status = dfi_rng_next_u32(&work, &r);
        if (status != DUOFORGE_OK) {
            return status;
        }
        uint32_t value = 0u;
        if (dfi_pcg32_accept(r, bound, threshold, &value)) {
            *rng = work;
            *out = value;
            return DUOFORGE_OK;
        }
    }
}

bool dfi_rng_is_valid(const dfi_rng *rng)
{
    return (rng->inc & 1u) == 1u;
}
