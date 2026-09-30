/*
 * T21 duoforge.rng.reference_differential (white-box, optional): built only
 * with DUOFORGE_PCG_REFERENCE_DIR pointing at the pinned pcg-c-basic
 * checkout. A driver instance of the REFERENCE generator chooses 256 seed
 * pairs and, for 4,000 operations each, the operation kind and bound; after
 * every operation the DuoForge state must equal the reference state and the
 * values must match. Bound 0 is never passed to the reference (it divides by
 * zero); zero-bound behaviour is covered by T5.
 */
#include "pcg_basic.h"
#include "rng/pcg32.h"
#include "support/check.h"

#define SEED_PAIRS 256u
#define OPS_PER_PAIR 4000u

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.rng.reference_differential");

    pcg32_random_t driver;
    pcg32_srandom_r(&driver, 0x5eedu, 0x5eedu);
    static const uint32_t special[] = {1u, 0x80000000u, 0x80000001u, 0xFFFFFFFFu};
    unsigned long mismatches = 0;
    unsigned long ops = 0;

    for (unsigned p = 0; p < SEED_PAIRS; ++p) {
        const uint64_t initstate = ((uint64_t)pcg32_random_r(&driver) << 32) | pcg32_random_r(&driver);
        const uint64_t initseq =
            (((uint64_t)pcg32_random_r(&driver) << 32) | pcg32_random_r(&driver)) & UINT64_C(0x7FFFFFFFFFFFFFFF);
        pcg32_random_t ref;
        dfi_rng ours;
        pcg32_srandom_r(&ref, initstate, initseq);
        dfi_rng_seed(&ours, initstate, initseq);
        if (ref.state != ours.state || ref.inc != ours.inc) {
            ++mismatches;
        }
        for (unsigned i = 0; i < OPS_PER_PAIR; ++i) {
            const uint32_t r = pcg32_random_r(&driver);
            const uint32_t r2 = pcg32_random_r(&driver);
            uint32_t mine = 0;
            uint32_t theirs = 0;
            if ((r & 3u) == 0u) {
                theirs = pcg32_random_r(&ref);
                if (dfi_rng_next_u32(&ours, &mine) != DUOFORGE_OK) {
                    ++mismatches;
                }
            } else {
                uint32_t bound;
                if ((r & 0xFFu) == 1u) {
                    bound = special[(r >> 8) & 3u];
                } else {
                    /* Log-uniform over the full range, never 0, cannot wrap. */
                    const uint32_t s = r2 & 31u;
                    bound = r >> s;
                    if (bound == 0u) {
                        bound = 1u;
                    }
                }
                theirs = pcg32_boundedrand_r(&ref, bound);
                if (dfi_rng_bounded_u32(&ours, bound, &mine) != DUOFORGE_OK) {
                    ++mismatches;
                }
            }
            ++ops;
            if (mine != theirs || ref.state != ours.state || ref.inc != ours.inc) {
                ++mismatches;
            }
        }
    }
    DF_CHECK_EQ_U64(&t, mismatches, 0u);
    DF_CHECK_EQ_U64(&t, ops, (uint64_t)SEED_PAIRS * OPS_PER_PAIR);
    return df_test_end(&t);
}
