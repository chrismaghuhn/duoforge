/*
 * duoforge.search.seeds: duoforge_search_seeds (decision 0022). Pinned values
 * of the formula; every initseq below 2^63; every pair accepted by
 * duoforge_battle_reseed; NULL outputs skipped.
 *
 * The pinned values come from the formula of decision 0022 section 2 in
 * Python (duoforge_learn.pairing.splitmix64 is the same finalizer):
 *   sm = lambda v: int(splitmix64(np.uint64(v & M)))      # M = 2^64 - 1
 *   h = sm(sm(seed + 0x5345415243480001) + key); s = sm(h + sample)
 *   initstate, initseq = sm(s + 1), sm(s + 2) >> 1
 */
#include <string.h>

#include <duoforge/duoforge_search.h>

#include "support/check.h"
#include "support/fixtures.h"
#include "support/team_c.h"

static const duoforge_context_config team_c_config = {DUOFORGE_DATA_KIND_TEAM_C, 6u, 4u, 0u, 0u, NULL};

/* splitmix64 as a stream: the next value of state *s. */
static uint64_t next(uint64_t *s)
{
    uint64_t z = (*s += 0x9E3779B97F4A7C15u);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9u;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBu;
    return z ^ (z >> 31);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.search.seeds");

    /* test_known_values */
    {
        static const struct {
            uint64_t seed, key;
            uint32_t sample;
            uint64_t initstate, initseq;
        } known[3] = {
            {0u, 0u, 0u, 0xd0679ab4d0a42833u, 0x74a4499fafb31cd8u},
            {0x2026100300000221u, 1u, 15u, 0x37e44fbeb84812c6u, 0x698c12ebca821d99u},
            {UINT64_MAX, UINT64_MAX, UINT32_MAX, 0x43a865eb46e4347cu, 0x0fd17315430e9824u},
        };
        for (uint32_t k = 0u; k < 3u; ++k) {
            uint64_t initstate = 0u;
            uint64_t initseq = 0u;
            duoforge_search_seeds(known[k].seed, known[k].key, known[k].sample, &initstate, &initseq);
            DF_CHECK_EQ_U64(&t, initstate, known[k].initstate);
            DF_CHECK_EQ_U64(&t, initseq, known[k].initseq);
        }
    }

    /* test_null_outputs_are_skipped */
    {
        uint64_t initstate = 0u;
        uint64_t initseq = 0u;
        duoforge_search_seeds(5u, 6u, 7u, &initstate, NULL);
        duoforge_search_seeds(5u, 6u, 7u, NULL, &initseq);
        duoforge_search_seeds(5u, 6u, 7u, NULL, NULL);
        uint64_t both_state = 0u;
        uint64_t both_seq = 0u;
        duoforge_search_seeds(5u, 6u, 7u, &both_state, &both_seq);
        DF_CHECK_EQ_U64(&t, initstate, both_state);
        DF_CHECK_EQ_U64(&t, initseq, both_seq);
    }

    /* test_initseq_below_2_63 and test_reseed_accepts */
    {
        duoforge_context *ctx = df_make_context(&team_c_config);
        duoforge_battle_setup setup;
        DF_CHECK(&t, duoforge_reference_setup(0u, &setup) == DUOFORGE_OK);
        duoforge_battle *battle = df_make_battle(ctx, &setup);
        uint64_t stream = 0x2026100300000300u;
        bool below = true;
        bool accepted = true;
        for (uint32_t k = 0u; k < 10000u; ++k) {
            uint64_t initstate = 0u;
            uint64_t initseq = 0u;
            const uint64_t seed = next(&stream);
            const uint64_t key = next(&stream);
            duoforge_search_seeds(seed, key, (uint32_t)(next(&stream) >> 32), &initstate, &initseq);
            below = below && initseq < (UINT64_C(1) << 63);
            accepted = accepted && duoforge_battle_reseed(ctx, battle, initstate, initseq) == DUOFORGE_OK;
        }
        DF_CHECK(&t, below);
        DF_CHECK(&t, accepted);
        duoforge_battle_destroy(battle);
        duoforge_context_destroy(ctx);
    }

    return df_test_end(&t);
}
