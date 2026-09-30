/*
 * T10 duoforge.state.clone_equal: clone, copy (snapshot/restore), equality,
 * fork independence, padding independence, context mismatch, corrupt-state
 * safety and reseeding a fork. Expectations: the clone/copy/equal contract
 * (docs/decisions/0002) and golden F2 (independent model).
 */
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "codec/state_codec.h"
#include "rng/pcg32.h"
#include "support/check.h"
#include "support/fixtures.h"

static bool api_equal(df_test *t, const duoforge_context *ctx, const duoforge_battle *a, const duoforge_battle *b)
{
    bool eq = false;
    DF_CHECK(t, duoforge_battle_equal(ctx, a, b, &eq) == DUOFORGE_OK);
    return eq;
}

static void raw(const duoforge_battle *b, uint8_t out[DUOFORGE_STATE_V1_ENCODED_SIZE])
{
    memset(out, 0, DUOFORGE_STATE_V1_ENCODED_SIZE);
    dfi_encode_unchecked(b, out);
}

/* Runs an equal() call that must fail, with *out preset to both false and
 * true (rule S3); it must stay unchanged. */
static void equal_fails(df_test *t, const duoforge_context *ctx, const duoforge_battle *a,
                        const duoforge_battle *b, duoforge_status expected)
{
    for (unsigned preset = 0; preset < 2; ++preset) {
        bool out = preset == 1;
        DF_CHECK(t, duoforge_battle_equal(ctx, a, b, &out) == expected);
        DF_CHECK(t, out == (preset == 1));
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.clone_equal");

    duoforge_context *c1 = df_make_context(&df_config_c1);
    duoforge_context *c2 = df_make_context(&df_config_c2);
    duoforge_battle_setup setup;
    df_setup_f1(&setup);
    duoforge_battle *f1 = df_make_battle(c1, &setup);
    duoforge_battle *f2 = df_make_f2(c1);
    uint8_t e1[DUOFORGE_STATE_V1_ENCODED_SIZE];
    uint8_t e2[DUOFORGE_STATE_V1_ENCODED_SIZE];

    /* Clone of F1: equal, same encoding and digest. */
    duoforge_battle *k = NULL;
    DF_CHECK(&t, duoforge_battle_clone(c1, f1, &k) == DUOFORGE_OK && k != NULL);
    DF_CHECK(&t, api_equal(&t, c1, f1, k));
    df_encode(c1, f1, e1);
    df_encode(c1, k, e2);
    DF_CHECK_BYTES(&t, e2, e1, sizeof e1, "clone encoding");
    {
        uint8_t d1[DUOFORGE_DIGEST_SIZE];
        uint8_t d2[DUOFORGE_DIGEST_SIZE];
        DF_CHECK(&t, duoforge_battle_digest(c1, f1, d1) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_digest(c1, k, d2) == DUOFORGE_OK);
        DF_CHECK_BYTES(&t, d2, d1, sizeof d1, "clone digest");
    }

    /* Clone of a decoded golden F2. */
    {
        uint8_t *in = df_heap_copy(df_golden_f2, DUOFORGE_STATE_V1_ENCODED_SIZE);
        duoforge_battle *d = NULL;
        duoforge_battle *dc = NULL;
        DF_CHECK(&t, duoforge_battle_create_decoded(c1, in, DUOFORGE_STATE_V1_ENCODED_SIZE, &d) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_clone(c1, d, &dc) == DUOFORGE_OK);
        df_encode(c1, dc, e2);
        DF_CHECK_BYTES(&t, e2, df_golden_f2, sizeof e2, "clone of decoded F2");
        DF_CHECK(&t, api_equal(&t, c1, dc, f2));
        duoforge_battle_destroy(dc);
        duoforge_battle_destroy(d);
        df_free(in);
    }

    /* copy F2 into a battle created from F1 (restore from snapshot). */
    {
        duoforge_battle *dst = df_make_battle(c1, &setup);
        DF_CHECK(&t, duoforge_battle_copy(c1, dst, f2) == DUOFORGE_OK);
        df_encode(c1, dst, e2);
        DF_CHECK_BYTES(&t, e2, df_golden_f2, sizeof e2, "copy F2 into F1 handle");
        duoforge_battle_destroy(dst);
    }

    /* Aliased copy: OK and unchanged under the matching context ... */
    DF_CHECK(&t, duoforge_battle_copy(c1, k, k) == DUOFORGE_OK);
    DF_CHECK(&t, api_equal(&t, c1, k, f1));
    /* ... but a context mismatch comes first even when dst == src. */
    raw(k, e1);
    DF_CHECK(&t, duoforge_battle_copy(c2, k, k) == DUOFORGE_E_CONTEXT_MISMATCH);
    raw(k, e2);
    DF_CHECK_BYTES(&t, e2, e1, sizeof e1, "aliased mismatch unchanged");

    /* Independence: a draw or HP poke on the clone does not touch the source. */
    {
        raw(f1, e1);
        uint32_t v = 0;
        DF_CHECK(&t, dfi_rng_next_u32(&k->rng, &v) == DUOFORGE_OK);
        raw(f1, e2);
        DF_CHECK_BYTES(&t, e2, e1, sizeof e1, "source unchanged after clone draw");
        DF_CHECK(&t, !api_equal(&t, c1, f1, k));
        DF_CHECK(&t, duoforge_battle_copy(c1, k, f1) == DUOFORGE_OK);
        k->sides[1].members[2].hp = 1u;
        raw(f1, e2);
        DF_CHECK_BYTES(&t, e2, e1, sizeof e1, "source unchanged after clone poke");
        DF_CHECK(&t, !api_equal(&t, c1, f1, k));
        DF_CHECK(&t, duoforge_battle_copy(c1, k, f1) == DUOFORGE_OK);
    }

    /* Forks draw identical streams (64 raw draws). */
    {
        duoforge_battle *a = NULL;
        duoforge_battle *b = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, f2, &a) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_clone(c1, f2, &b) == DUOFORGE_OK);
        unsigned diff = 0;
        for (unsigned i = 0; i < 64; ++i) {
            uint32_t x = 0;
            uint32_t y = 1;
            (void)dfi_rng_next_u32(&a->rng, &x);
            (void)dfi_rng_next_u32(&b->rng, &y);
            diff += x != y ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, diff, 0u);
        DF_CHECK(&t, api_equal(&t, c1, a, b));

        /* Reseeding a fork decorrelates it; nothing but the RNG changes. */
        raw(a, e1);
        DF_CHECK(&t, duoforge_battle_reseed(c1, b, 7u, 9u) == DUOFORGE_OK);
        raw(b, e2);
        unsigned outside = 0;
        for (unsigned i = 0; i < sizeof e1; ++i) {
            outside += (e1[i] != e2[i] && (i < 52u || i >= 76u)) ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, outside, 0u);
        dfi_rng fresh;
        dfi_rng_seed(&fresh, 7u, 9u);
        DF_CHECK(&t, b->rng.state == fresh.state && b->rng.inc == fresh.inc && b->rng.draws == 0u);
        DF_CHECK(&t, duoforge_battle_check(c1, b) == DUOFORGE_OK);
        DF_CHECK(&t, !api_equal(&t, c1, a, b));
        /* Reseed failures are atomic. */
        raw(b, e1);
        DF_CHECK(&t, duoforge_battle_reseed(c1, b, 1u, UINT64_C(0x8000000000000000)) == DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_reseed(c2, b, 1u, 2u) == DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK(&t, duoforge_battle_reseed(NULL, b, 1u, 2u) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_reseed(c1, NULL, 1u, 2u) == DUOFORGE_E_NULL_ARGUMENT);
        raw(b, e2);
        DF_CHECK_BYTES(&t, e2, e1, sizeof e1, "reseed failures unchanged");
        duoforge_battle_destroy(a);
        duoforge_battle_destroy(b);
    }

    /* Equality relation over F1, F2 and 20 single-field variants of F1:
     * equal <=> encodings identical <=> digests equal. */
    {
        enum { N = 22 };
        duoforge_battle *v[N];
        for (unsigned i = 0; i < N; ++i) {
            v[i] = NULL;
            DF_CHECK(&t, duoforge_battle_clone(c1, i == 1 ? f2 : f1, &v[i]) == DUOFORGE_OK);
        }
        v[2]->rng.state ^= 1u;
        v[3]->rng.inc ^= 2u;
        v[4]->rng.draws += 1u;
        v[5]->next_activation_id += 1u;
        v[6]->sides[0].members[0].hp = (uint16_t)(v[6]->sides[0].members[0].hp - 1u);
        v[7]->sides[1].members[3].hp_max = (uint16_t)(v[7]->sides[1].members[3].hp_max + 1u);
        v[8]->sides[0].members[5].species_id = 7u;
        v[9]->sides[1].members[0].moves[2].pp = (uint8_t)(v[9]->sides[1].members[0].moves[2].pp - 1u);
        v[10]->sides[0].members[3].moves[3].pp_max = (uint8_t)(v[10]->sides[0].members[3].moves[3].pp_max + 1u);
        v[11]->sides[0].members[1].moves[1].move_id = 30u;
        v[12]->sides[1].positions[1].activation_id = 9u;
        v[12]->next_activation_id = 10u;
        v[13]->sides[0].positions[0].occupant = 3u;
        v[14]->sides[1].brought_mask = 0x0Fu; /* unchanged value: must stay equal to F1 */
        v[15]->sides[0].members[4].hp = 0u;
        v[16]->sides[1].members[1].moves[0].pp = 0u;
        v[17]->rng.state ^= UINT64_C(0x8000000000000000);
        v[18]->rng.draws = UINT64_MAX;
        v[19]->sides[0].members[2].moves[2].pp = (uint8_t)(v[19]->sides[0].members[2].moves[2].pp - 1u);
        v[20]->sides[1].members[0].species_id = 11u;
        v[21]->sides[0].positions[1].activation_id = 7u;
        v[21]->next_activation_id = 8u;
        unsigned mismatches = 0;
        for (unsigned i = 0; i < N; ++i) {
            for (unsigned j = 0; j < N; ++j) {
                uint8_t a[DUOFORGE_STATE_V1_ENCODED_SIZE];
                uint8_t b[DUOFORGE_STATE_V1_ENCODED_SIZE];
                uint8_t da[DUOFORGE_DIGEST_SIZE];
                uint8_t db[DUOFORGE_DIGEST_SIZE];
                raw(v[i], a);
                raw(v[j], b);
                const bool bytes_eq = memcmp(a, b, sizeof a) == 0;
                const bool api_eq = api_equal(&t, c1, v[i], v[j]);
                DF_CHECK(&t, duoforge_battle_digest(c1, v[i], da) == DUOFORGE_OK);
                DF_CHECK(&t, duoforge_battle_digest(c1, v[j], db) == DUOFORGE_OK);
                const bool dig_eq = memcmp(da, db, sizeof da) == 0;
                mismatches += (bytes_eq != api_eq || bytes_eq != dig_eq) ? 1u : 0u;
                mismatches += (i == j && !api_eq) ? 1u : 0u;                          /* reflexive */
                mismatches += (api_eq != api_equal(&t, c1, v[j], v[i])) ? 1u : 0u; /* symmetric */
            }
        }
        DF_CHECK_EQ_U64(&t, mismatches, 0u);
        DF_CHECK(&t, api_equal(&t, c1, v[14], v[0]));
        for (unsigned i = 1; i < N; ++i) {
            if (i != 14) {
                DF_CHECK(&t, !api_equal(&t, c1, v[i], v[0]));
            }
        }
        for (unsigned i = 0; i < N; ++i) {
            duoforge_battle_destroy(v[i]);
        }
    }

    /* Padding independence: states assembled on 0x00 and 0xAA backgrounds with
     * the same named fields compare equal, encode and digest identically. */
    {
        duoforge_battle *a = NULL;
        duoforge_battle *b = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, f2, &a) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_clone(c1, f2, &b) == DUOFORGE_OK);
        memset(a, 0x00, sizeof *a);
        memset(b, 0xAA, sizeof *b);
        const duoforge_battle *src = f2;
        duoforge_battle *dsts[2] = {a, b};
        for (unsigned d = 0; d < 2; ++d) {
            duoforge_battle *x = dsts[d];
            memcpy(x->context_fingerprint, src->context_fingerprint, DUOFORGE_DIGEST_SIZE);
            x->rng.state = src->rng.state;
            x->rng.inc = src->rng.inc;
            x->rng.draws = src->rng.draws;
            x->next_activation_id = src->next_activation_id;
            for (unsigned s = 0; s < 2; ++s) {
                x->sides[s].member_count = src->sides[s].member_count;
                x->sides[s].brought_mask = src->sides[s].brought_mask;
                for (unsigned p = 0; p < 2; ++p) {
                    x->sides[s].positions[p].occupant = src->sides[s].positions[p].occupant;
                    x->sides[s].positions[p].activation_id = src->sides[s].positions[p].activation_id;
                }
                for (unsigned m = 0; m < DUOFORGE_MAX_ROSTER; ++m) {
                    const dfi_member *sm = &src->sides[s].members[m];
                    dfi_member *dm = &x->sides[s].members[m];
                    dm->species_id = sm->species_id;
                    dm->hp = sm->hp;
                    dm->hp_max = sm->hp_max;
                    dm->move_count = sm->move_count;
                    for (unsigned q = 0; q < DUOFORGE_MAX_MOVE_SLOTS; ++q) {
                        dm->moves[q].move_id = sm->moves[q].move_id;
                        dm->moves[q].pp = sm->moves[q].pp;
                        dm->moves[q].pp_max = sm->moves[q].pp_max;
                    }
                }
            }
        }
        DF_CHECK(&t, api_equal(&t, c1, a, b));
        df_encode(c1, a, e1);
        df_encode(c1, b, e2);
        DF_CHECK_BYTES(&t, e1, e2, sizeof e1, "padding-independent encoding");
        DF_CHECK_BYTES(&t, e1, df_golden_f2, sizeof e1, "padding-independent encoding = golden F2");
        uint8_t da[DUOFORGE_DIGEST_SIZE];
        uint8_t db[DUOFORGE_DIGEST_SIZE];
        DF_CHECK(&t, duoforge_battle_digest(c1, a, da) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_digest(c1, b, db) == DUOFORGE_OK);
        DF_CHECK_BYTES(&t, da, db, sizeof da, "padding-independent digest");
        duoforge_battle_destroy(a);
        duoforge_battle_destroy(b);
    }

    /* Context mismatch: copy/equal/clone fail and change nothing. */
    {
        duoforge_battle *x = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, f1, &x) == DUOFORGE_OK);
        x->context_fingerprint[0] ^= 0xFFu; /* bound to "another context" */
        raw(x, e1);
        DF_CHECK(&t, duoforge_battle_copy(c1, x, f1) == DUOFORGE_E_CONTEXT_MISMATCH);
        raw(x, e2);
        DF_CHECK_BYTES(&t, e2, e1, sizeof e1, "copy dst mismatch unchanged");
        raw(k, e1);
        DF_CHECK(&t, duoforge_battle_copy(c1, k, x) == DUOFORGE_E_CONTEXT_MISMATCH);
        raw(k, e2);
        DF_CHECK_BYTES(&t, e2, e1, sizeof e1, "copy src mismatch unchanged");
        equal_fails(&t, c1, f1, x, DUOFORGE_E_CONTEXT_MISMATCH);
        equal_fails(&t, c1, x, f1, DUOFORGE_E_CONTEXT_MISMATCH);
        max_align_t sentinel;
        duoforge_battle *const marker = (duoforge_battle *)(void *)&sentinel;
        duoforge_battle *out = marker;
        DF_CHECK(&t, duoforge_battle_clone(c1, x, &out) == DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK(&t, out == marker);
        duoforge_battle_destroy(x);
    }

    /* Corrupt state: copy/clone/equal succeed (no invariant check) and stay
     * memory-safe; equal is deterministic. */
    {
        duoforge_battle *x = NULL;
        duoforge_battle *y = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, f1, &x) == DUOFORGE_OK);
        x->sides[0].member_count = 0xFFu;
        DF_CHECK(&t, duoforge_battle_clone(c1, x, &y) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_copy(c1, k, x) == DUOFORGE_OK);
        DF_CHECK(&t, api_equal(&t, c1, x, y));
        DF_CHECK(&t, api_equal(&t, c1, x, y));
        DF_CHECK(&t, duoforge_battle_check(c1, x) == DUOFORGE_E_INVARIANT);
        duoforge_battle_destroy(x);
        duoforge_battle_destroy(y);
    }

    duoforge_battle_destroy(k);
    duoforge_battle_destroy(f1);
    duoforge_battle_destroy(f2);
    duoforge_context_destroy(c1);
    duoforge_context_destroy(c2);
    return df_test_end(&t);
}
