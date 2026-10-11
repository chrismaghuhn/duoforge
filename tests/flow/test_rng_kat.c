/*
 * T4 duoforge.rng.kat (white-box): the DuoForge RNG reproduces the pinned
 * pcg-c-basic reference exactly: seeding, raw words, bounded draws and the
 * number of raw words each bounded draw consumes. Expectations come only
 * from tests/data/pcg32_kat_vectors.h, generated from the pinned reference.
 */
#include "data/pcg32_kat_vectors.h"
#include "rng/pcg32.h"
#include "support/check.h"

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.rng.kat");

    for (unsigned s = 0; s < DF_KAT_SEED_COUNT; ++s) {
        const df_kat_seed *k = &df_kat_seeds[s];
        dfi_rng rng;
        dfi_rng_seed(&rng, k->initstate, k->initseq);
        DF_CHECK_EQ_U64(&t, rng.state, k->state);
        DF_CHECK_EQ_U64(&t, rng.inc, k->inc);
        DF_CHECK_EQ_U64(&t, rng.draws, 0u);
        DF_CHECK(&t, dfi_rng_is_valid(&rng));

        for (unsigned i = 0; i < DF_KAT_RAW_COUNT; ++i) {
            uint32_t v = 0xDEADBEEFu;
            DF_CHECK_EQ_U64(&t, dfi_rng_next_u32(&rng, &v), DUOFORGE_OK);
            DF_CHECK_EQ_U64(&t, v, k->raw[i]);
        }
        DF_CHECK_EQ_U64(&t, rng.state, k->state_after_raw);
        DF_CHECK_EQ_U64(&t, rng.draws, DF_KAT_RAW_COUNT);

        for (unsigned b = 0; b < DF_KAT_BOUND_COUNT; ++b) {
            const df_kat_bounded *kb = &k->bounded[b];
            dfi_rng r2;
            dfi_rng_seed(&r2, k->initstate, k->initseq);
            uint64_t total = 0;
            for (unsigned i = 0; i < DF_KAT_CALLS; ++i) {
                const uint64_t before = r2.draws;
                uint32_t v = 0xDEADBEEFu;
                DF_CHECK_EQ_U64(&t, dfi_rng_bounded_u32(&r2, kb->bound, &v), DUOFORGE_OK);
                DF_CHECK_EQ_U64(&t, v, kb->value[i]);
                DF_CHECK_EQ_U64(&t, r2.draws - before, kb->draws[i]);
                total += kb->draws[i];
            }
            DF_CHECK_EQ_U64(&t, r2.draws, total);
        }

        dfi_rng r3;
        dfi_rng_seed(&r3, k->initstate, k->initseq);
        for (unsigned i = 0; i < DF_KAT_SHUFFLE_COUNT; ++i) {
            const uint64_t before = r3.draws;
            uint32_t v = 0xDEADBEEFu;
            DF_CHECK_EQ_U64(&t, dfi_rng_bounded_u32(&r3, DF_KAT_SHUFFLE_FIRST - i, &v), DUOFORGE_OK);
            DF_CHECK_EQ_U64(&t, v, k->shuffle_value[i]);
            DF_CHECK_EQ_U64(&t, r3.draws - before, k->shuffle_draws[i]);
        }
    }

    /* Literal cross-check with the published pcg32-demo output for (42, 54). */
    {
        dfi_rng rng;
        uint32_t a = 0;
        uint32_t b = 0;
        dfi_rng_seed(&rng, 42u, 54u);
        (void)dfi_rng_next_u32(&rng, &a);
        (void)dfi_rng_next_u32(&rng, &b);
        DF_CHECK_EQ_U64(&t, a, 0xa15c02b7u);
        DF_CHECK_EQ_U64(&t, b, 0x7b47f409u);
    }

    /* The KAT must contain at least one rejection (a bounded draw using more
     * than one raw word), otherwise rejection accounting is untested. */
    {
        unsigned multi = 0;
        for (unsigned s = 0; s < DF_KAT_SEED_COUNT; ++s) {
            for (unsigned b = 0; b < DF_KAT_BOUND_COUNT; ++b) {
                for (unsigned i = 0; i < DF_KAT_CALLS; ++i) {
                    multi += df_kat_seeds[s].bounded[b].draws[i] > 1u ? 1u : 0u;
                }
            }
        }
        DF_CHECK(&t, multi > 0);
    }

    return df_test_end(&t);
}
