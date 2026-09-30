/*
 * T5 duoforge.rng.contract (white-box): the DuoForge-authored parts of the
 * RNG contract (docs/decisions/0001): zero bound, exhaustion, atomic
 * bounded draws across a rejection, seed aliasing, instance independence.
 * Anchor values come from the pinned KAT (seed 42, 54).
 */
#include <string.h>

#include "rng/pcg32.h"
#include "support/check.h"

#define SEED_STATE UINT64_C(0x185706b82c2e03f8)
#define SEED_INC UINT64_C(0x6d)

static bool rng_same(const dfi_rng *a, const dfi_rng *b)
{
    return a->state == b->state && a->inc == b->inc && a->draws == b->draws;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.rng.contract");

    dfi_rng seeded;
    dfi_rng_seed(&seeded, 42u, 54u);
    DF_CHECK_EQ_U64(&t, seeded.state, SEED_STATE);
    DF_CHECK_EQ_U64(&t, seeded.inc, SEED_INC);

    /* bound 0: internal contract violation, nothing mutated. */
    {
        dfi_rng r = seeded;
        uint32_t out = 0xDEADBEEFu;
        DF_CHECK_EQ_U64(&t, dfi_rng_bounded_u32(&r, 0u, &out), DUOFORGE_E_INVARIANT);
        DF_CHECK(&t, rng_same(&r, &seeded));
        DF_CHECK_EQ_U64(&t, out, 0xDEADBEEFu);
    }

    /* bound 1: returns 0 and consumes exactly one draw (reference parity). */
    {
        dfi_rng r = seeded;
        uint32_t out = 0xDEADBEEFu;
        DF_CHECK_EQ_U64(&t, dfi_rng_bounded_u32(&r, 1u, &out), DUOFORGE_OK);
        DF_CHECK_EQ_U64(&t, out, 0u);
        DF_CHECK_EQ_U64(&t, r.draws, 1u);
    }

    /* Raw exhaustion. */
    {
        dfi_rng r = seeded;
        r.draws = UINT64_MAX - 1u;
        uint32_t out = 0xDEADBEEFu;
        DF_CHECK_EQ_U64(&t, dfi_rng_next_u32(&r, &out), DUOFORGE_OK);
        DF_CHECK_EQ_U64(&t, out, 0xa15c02b7u);
        DF_CHECK_EQ_U64(&t, r.draws, UINT64_MAX);
        const dfi_rng before = r;
        out = 0xDEADBEEFu;
        DF_CHECK_EQ_U64(&t, dfi_rng_next_u32(&r, &out), DUOFORGE_E_EXHAUSTED);
        DF_CHECK(&t, rng_same(&r, &before));
        DF_CHECK_EQ_U64(&t, out, 0xDEADBEEFu);
        out = 0xDEADBEEFu;
        DF_CHECK_EQ_U64(&t, dfi_rng_bounded_u32(&r, 6u, &out), DUOFORGE_E_EXHAUSTED);
        DF_CHECK(&t, rng_same(&r, &before));
        DF_CHECK_EQ_U64(&t, out, 0xDEADBEEFu);
    }

    /* A one-draw bounded call can use the last available draw. */
    {
        dfi_rng r = seeded;
        r.draws = UINT64_MAX - 1u;
        uint32_t out = 0;
        DF_CHECK_EQ_U64(&t, dfi_rng_bounded_u32(&r, 0x80000001u, &out), DUOFORGE_OK);
        DF_CHECK_EQ_U64(&t, out, 559678134u);
        DF_CHECK_EQ_U64(&t, r.draws, UINT64_MAX);
    }

    /* Mid-rejection atomicity: the 2nd bounded(0x80000001) call needs 2 draws
     * (the first is rejected). With only 1 draw left it must fail atomically. */
    {
        dfi_rng r = seeded;
        uint32_t out = 0;
        DF_CHECK_EQ_U64(&t, dfi_rng_bounded_u32(&r, 0x80000001u, &out), DUOFORGE_OK);
        DF_CHECK_EQ_U64(&t, out, 559678134u);
        DF_CHECK_EQ_U64(&t, r.draws, 1u);

        dfi_rng positive = r;
        dfi_rng exhausted = r;
        exhausted.draws = UINT64_MAX - 1u;
        const dfi_rng before = exhausted;
        out = 0xDEADBEEFu;
        DF_CHECK_EQ_U64(&t, dfi_rng_bounded_u32(&exhausted, 0x80000001u, &out), DUOFORGE_E_EXHAUSTED);
        DF_CHECK(&t, rng_same(&exhausted, &before));
        DF_CHECK_EQ_U64(&t, out, 0xDEADBEEFu);

        /* Positive control on a copy with draws available. */
        out = 0;
        DF_CHECK_EQ_U64(&t, dfi_rng_bounded_u32(&positive, 0x80000001u, &out), DUOFORGE_OK);
        DF_CHECK_EQ_U64(&t, out, 974992175u);
        DF_CHECK_EQ_U64(&t, positive.draws, 3u);
    }

    /* Seed aliasing: bit 63 of initseq is discarded by the shift. */
    {
        static const uint64_t states[] = {0u, 42u, UINT64_C(0x0123456789abcdef), UINT64_MAX};
        static const uint64_t seqs[] = {0u, 54u, UINT64_C(0x7edcba9876543210), UINT64_C(0x7FFFFFFFFFFFFFFF)};
        for (unsigned i = 0; i < 4; ++i) {
            dfi_rng a;
            dfi_rng b;
            dfi_rng_seed(&a, states[i], seqs[i]);
            dfi_rng_seed(&b, states[i], seqs[i] ^ UINT64_C(0x8000000000000000));
            DF_CHECK(&t, rng_same(&a, &b));
        }
        /* Distinct initseq < 2^63 give distinct inc; distinct initstate give
         * distinct state (64 samples each). */
        uint64_t incs[64];
        uint64_t sts[64];
        for (unsigned i = 0; i < 64; ++i) {
            dfi_rng r;
            dfi_rng_seed(&r, 7u, (uint64_t)i * UINT64_C(0x0101010101010101) & UINT64_C(0x7FFFFFFFFFFFFFFF));
            incs[i] = r.inc;
            dfi_rng_seed(&r, (uint64_t)i * UINT64_C(0x9E3779B97F4A7C15), 9u);
            sts[i] = r.state;
        }
        unsigned dup = 0;
        for (unsigned i = 0; i < 64; ++i) {
            for (unsigned j = i + 1; j < 64; ++j) {
                dup += (incs[i] == incs[j]) ? 1u : 0u;
                dup += (sts[i] == sts[j]) ? 1u : 0u;
            }
        }
        DF_CHECK_EQ_U64(&t, dup, 0u);
    }

    /* Instances are independent: interleaved use equals sequential use, and a
     * struct copy continues identically. */
    {
        dfi_rng a;
        dfi_rng b;
        dfi_rng a2;
        dfi_rng b2;
        dfi_rng_seed(&a, 42u, 54u);
        dfi_rng_seed(&b, 1u, 1u);
        a2 = a;
        b2 = b;
        uint32_t seq_a[32];
        uint32_t seq_b[32];
        for (unsigned i = 0; i < 32; ++i) {
            (void)dfi_rng_next_u32(&a2, &seq_a[i]);
        }
        for (unsigned i = 0; i < 32; ++i) {
            (void)dfi_rng_next_u32(&b2, &seq_b[i]);
        }
        unsigned diff = 0;
        for (unsigned i = 0; i < 32; ++i) {
            uint32_t x = 0;
            uint32_t y = 0;
            (void)dfi_rng_next_u32(&a, &x);
            (void)dfi_rng_next_u32(&b, &y);
            diff += (x != seq_a[i] ? 1u : 0u) + (y != seq_b[i] ? 1u : 0u);
        }
        DF_CHECK_EQ_U64(&t, diff, 0u);

        dfi_rng c;
        dfi_rng_seed(&c, 3u, 4u);
        dfi_rng d = c;
        diff = 0;
        for (unsigned i = 0; i < 32; ++i) {
            uint32_t x = 0;
            uint32_t y = 0;
            (void)dfi_rng_next_u32(&c, &x);
            (void)dfi_rng_next_u32(&d, &y);
            diff += (x != y) ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, diff, 0u);
    }

    /* inc must be odd. */
    {
        dfi_rng r = seeded;
        DF_CHECK(&t, dfi_rng_is_valid(&r));
        r.inc &= ~UINT64_C(1);
        DF_CHECK(&t, !dfi_rng_is_valid(&r));
    }

    return df_test_end(&t);
}
