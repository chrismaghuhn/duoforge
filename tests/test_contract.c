/*
 * T32 duoforge.request.contract (white-box fixtures): the M2 part of the
 * DECISION_CONTRACT section 8 minimum: a snapshot (encode/decode and
 * copy) at every exposed boundary kind restores an identical model-visible
 * surface (requests, candidates) and identical private state; late and
 * stale responses are rejected atomically at every boundary; two-side
 * replacement and two-side pivot request both sides with independent
 * domains; a one-side pivot keeps the waiting side's sealed commitment and
 * excludes it from the request; a re-prompted TURN keeps the sealed choice
 * across a snapshot round trip.
 */
#include <stdio.h>
#include <string.h>

#include "codec/state_codec.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"

static duoforge_side_choice ca[DUOFORGE_MAX_CANDIDATES];
static duoforge_side_choice cb[DUOFORGE_MAX_CANDIDATES];

/* Model-visible surface of both players: requests and candidate bytes. */
typedef struct surface {
    duoforge_status req_status[2];
    duoforge_request req[2];
    duoforge_status cand_status[2];
    uint32_t count[2];
    uint8_t digest[2][DUOFORGE_DIGEST_SIZE];
} surface;

static void capture(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, surface *s)
{
    memset(s, 0, sizeof *s);
    for (uint32_t p = 0; p < 2; ++p) {
        s->req_status[p] = duoforge_battle_request(ctx, b, p, &s->req[p]);
        s->cand_status[p] = duoforge_battle_candidates(ctx, b, p, ca, DUOFORGE_MAX_CANDIDATES, &s->count[p]);
        if (s->cand_status[p] == DUOFORGE_OK) {
            /* A plain byte digest (FNV-1a) of the candidate records. */
            uint32_t h = 2166136261u;
            const uint8_t *bytes = (const uint8_t *)ca;
            for (size_t i = 0; i < (size_t)s->count[p] * sizeof ca[0]; ++i) {
                h = (h ^ bytes[i]) * 16777619u;
            }
            memcpy(s->digest[p], &h, sizeof h);
            memcpy(cb, ca, (size_t)s->count[p] * sizeof ca[0]);
        }
    }
    (void)t;
}

static void check_snapshot(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, const char *what)
{
    /* encode -> decode into a fresh handle built from any setup; and copy. */
    uint8_t enc[DUOFORGE_STATE_V2_ENCODED_SIZE];
    df_encode(ctx, b, enc);
    duoforge_battle *restored = NULL;
    uint8_t *in = df_heap_copy(enc, sizeof enc);
    DF_CHECK(t, duoforge_battle_create_decoded(ctx, in, sizeof enc, &restored) == DUOFORGE_OK);
    df_free(in);
    duoforge_battle *copied = NULL;
    DF_CHECK(t, duoforge_battle_clone(ctx, b, &copied) == DUOFORGE_OK);
    memset(copied, 0x5A, sizeof *copied); /* scribble, then restore in place */
    memcpy(copied->context_fingerprint, b->context_fingerprint, DUOFORGE_DIGEST_SIZE);
    DF_CHECK(t, duoforge_battle_copy(ctx, copied, b) == DUOFORGE_OK);
    bool eq = false;
    DF_CHECK(t, duoforge_battle_equal(ctx, b, restored, &eq) == DUOFORGE_OK && eq);
    DF_CHECK(t, duoforge_battle_equal(ctx, b, copied, &eq) == DUOFORGE_OK && eq);
    DF_CHECK(t, duoforge_battle_check(ctx, restored) == DUOFORGE_OK);
    /* Same model-visible surface for both players. */
    surface s0;
    surface s1;
    capture(t, ctx, b, &s0);
    capture(t, ctx, restored, &s1);
    if (!DF_CHECK(t, memcmp(&s0, &s1, sizeof s0) == 0)) {
        fprintf(stderr, "  surface differs after restore: %s\n", what);
    }
    /* Private state too: sealed commitments, bench order and knowledge. */
    for (unsigned s = 0; s < 2; ++s) {
        DF_CHECK(t, memcmp(restored->sides[s].sealed_cmds, b->sides[s].sealed_cmds, sizeof b->sides[s].sealed_cmds) == 0);
        DF_CHECK(t, memcmp(restored->sides[s].brought_order, b->sides[s].brought_order, DUOFORGE_MAX_ROSTER) == 0);
        DF_CHECK(t, restored->sides[s].sealed == b->sides[s].sealed && restored->sides[s].seen_mask == b->sides[s].seen_mask);
    }
    duoforge_battle_destroy(restored);
    duoforge_battle_destroy(copied);
}

/* A bundle that must be rejected with `expected`, leaving the state unchanged. */
static void rejected(df_test *t, const duoforge_context *ctx, duoforge_battle *b, const duoforge_decision_bundle *bd,
                     duoforge_status expected, const char *what)
{
    uint8_t before[DUOFORGE_STATE_V2_ENCODED_SIZE];
    uint8_t after[DUOFORGE_STATE_V2_ENCODED_SIZE];
    duoforge_step_result res;
    memset(&res, 0xA5, sizeof res);
    df_encode(ctx, b, before);
    const duoforge_status st = duoforge_battle_step(ctx, b, bd, &res);
    df_encode(ctx, b, after);
    if (!DF_CHECK(t, st == expected)) {
        fprintf(stderr, "  %s: %s, expected %s\n", what, duoforge_status_name(st), duoforge_status_name(expected));
    }
    DF_CHECK_BYTES(t, after, before, sizeof after, what);
    DF_CHECK(t, res.epoch == 0xA5A5A5A5u);
}

/* Valid bundle from candidate 0 of every requested side. */
static void first_bundle(df_test *t, const duoforge_context *ctx, const duoforge_battle *b,
                         duoforge_decision_bundle *bd)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = b->request_mask;
    for (uint32_t s = 0; s < 2; ++s) {
        if ((((uint32_t)b->request_mask >> s) & 1u) != 0u) {
            uint32_t n = 0;
            DF_CHECK(t, duoforge_battle_candidates(ctx, b, s, ca, DUOFORGE_MAX_CANDIDATES, &n) == DUOFORGE_OK && n > 0);
            bd->responses[s] = ca[0];
        }
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.request.contract");

    duoforge_context *c1 = df_make_context(&df_config_c1);
    duoforge_context *c4 = df_make_context(&df_config_c4);

    /* Snapshot at every exposed boundary kind, plus a re-prompted TURN. */
    {
        duoforge_battle *g1 = df_make_g1(c1);
        duoforge_battle *f1 = df_make_f1(c1);
        duoforge_battle *f2 = df_make_f2(c1);
        duoforge_battle *f4 = df_make_f4(c1);
        duoforge_battle *f5 = df_make_f5(c1);
        duoforge_battle *f6 = df_make_f6(c1);
        duoforge_battle *f11 = df_make_f11(c4);
        check_snapshot(&t, c1, g1, "TEAM_SELECTION");
        check_snapshot(&t, c1, f1, "TURN");
        check_snapshot(&t, c1, f2, "TURN with fainted active");
        check_snapshot(&t, c1, f4, "REPLACEMENT (two sides)");
        check_snapshot(&t, c1, f5, "PIVOT (one side)");
        check_snapshot(&t, c1, f6, "PIVOT (two sides)");
        check_snapshot(&t, c4, f11, "REPLACEMENT (forced passes)");
        duoforge_battle *rp = df_make_f1(c1);
        uint32_t n = 0;
        DF_CHECK(&t, duoforge_battle_candidates(c1, rp, 1, ca, DUOFORGE_MAX_CANDIDATES, &n) == DUOFORGE_OK);
        DF_CHECK(&t, dfi_reprompt_side(c1, rp, 0, &ca[7]) == DUOFORGE_OK);
        check_snapshot(&t, c1, rp, "re-prompted TURN");
        duoforge_battle_destroy(rp);
        duoforge_battle_destroy(g1);
        duoforge_battle_destroy(f1);
        duoforge_battle_destroy(f2);
        duoforge_battle_destroy(f4);
        duoforge_battle_destroy(f5);
        duoforge_battle_destroy(f6);
        duoforge_battle_destroy(f11);
    }

    /* Late and stale responses at every boundary: epoch - 1, epoch + 1 and
     * a stale response inside an otherwise current bundle. */
    {
        duoforge_battle *fx[5] = {df_make_g1(c1), df_make_f1(c1), df_make_f4(c1), df_make_f5(c1), df_make_f6(c1)};
        for (unsigned i = 0; i < 5; ++i) {
            duoforge_decision_bundle good;
            first_bundle(&t, c1, fx[i], &good);
            duoforge_decision_bundle bd = good;
            bd.epoch = good.epoch - 1u;
            rejected(&t, c1, fx[i], &bd, DUOFORGE_E_STALE_EPOCH, "late bundle");
            bd = good;
            bd.epoch = good.epoch + 1u;
            rejected(&t, c1, fx[i], &bd, DUOFORGE_E_STALE_EPOCH, "future bundle");
            for (uint32_t s = 0; s < 2; ++s) {
                if ((((uint32_t)fx[i]->request_mask >> s) & 1u) == 0u) {
                    continue;
                }
                bd = good;
                bd.responses[s].epoch = good.epoch - 1u;
                rejected(&t, c1, fx[i], &bd, DUOFORGE_E_STALE_EPOCH, "stale response");
            }
            duoforge_battle_destroy(fx[i]);
        }
    }

    /* Two-side replacement (F4): both sides requested, each with its own
     * slot and its own reserves; neither response depends on the other. */
    {
        duoforge_battle *f4 = df_make_f4(c1);
        duoforge_request r0;
        duoforge_request r1;
        DF_CHECK(&t, duoforge_battle_request(c1, f4, 0, &r0) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_request(c1, f4, 1, &r1) == DUOFORGE_OK);
        DF_CHECK(&t, r0.requested == 1u && r0.slot_mask == 1u && r0.candidate_count == 2u);
        DF_CHECK(&t, r1.requested == 1u && r1.slot_mask == 2u && r1.candidate_count == 2u);
        uint32_t n0 = 0;
        uint32_t n1 = 0;
        DF_CHECK(&t, duoforge_battle_candidates(c1, f4, 0, ca, DUOFORGE_MAX_CANDIDATES, &n0) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_candidates(c1, f4, 1, cb, DUOFORGE_MAX_CANDIDATES, &n1) == DUOFORGE_OK);
        /* All four pairings are accepted up to the honest UNSUPPORTED. */
        for (uint32_t i = 0; i < n0; ++i) {
            for (uint32_t j = 0; j < n1; ++j) {
                duoforge_decision_bundle bd;
                memset(&bd, 0, sizeof bd);
                bd.epoch = 3u;
                bd.response_mask = 3u;
                bd.responses[0] = ca[i];
                bd.responses[1] = cb[j];
                rejected(&t, c1, f4, &bd, DUOFORGE_E_UNSUPPORTED, "two-side replacement pairing");
            }
        }
        /* One side alone is not enough: the bundle needs both. */
        duoforge_decision_bundle half;
        memset(&half, 0, sizeof half);
        half.epoch = 3u;
        half.response_mask = 1u;
        half.responses[0] = ca[0];
        rejected(&t, c1, f4, &half, DUOFORGE_E_INVALID_ARGUMENT, "half a replacement bundle");
        duoforge_battle_destroy(f4);
    }

    /* One-side pivot continuation (F5): side 1 waits with its sealed choice;
     * side 0's domain is the forced-switch domain; side 1 gets no request
     * and no candidates; the sealed commitment survives the pause. */
    {
        duoforge_battle *f5 = df_make_f5(c1);
        duoforge_request r0;
        duoforge_request r1;
        DF_CHECK(&t, duoforge_battle_request(c1, f5, 0, &r0) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_request(c1, f5, 1, &r1) == DUOFORGE_OK);
        DF_CHECK(&t, r0.boundary_kind == DUOFORGE_BOUNDARY_PIVOT && r0.requested == 1u && r0.slot_mask == 1u &&
                         r0.candidate_count == 2u);
        DF_CHECK(&t, r1.boundary_kind == DUOFORGE_BOUNDARY_PIVOT && r1.requested == 0u && r1.slot_mask == 0u &&
                         r1.candidate_count == 0u && r1.epoch == 3u);
        uint32_t n = 0xDEADBEEFu;
        DF_CHECK(&t, duoforge_battle_candidates(c1, f5, 1, ca, DUOFORGE_MAX_CANDIDATES, &n) == DUOFORGE_OK && n == 0u);
        DF_CHECK(&t, f5->sides[1].sealed == 1u && f5->sides[1].sealed_cmds[0].kind == DUOFORGE_SLOT_SWITCH);
        duoforge_decision_bundle bd;
        first_bundle(&t, c1, f5, &bd);
        rejected(&t, c1, f5, &bd, DUOFORGE_E_UNSUPPORTED, "pivot continuation (honest UNSUPPORTED)");
        DF_CHECK(&t, f5->sides[1].sealed == 1u); /* still sealed after the rejected execution */
        /* Two-side pivot (F6): both requested, both domains are the forced
         * switch domains of their own side. */
        duoforge_battle *f6 = df_make_f6(c1);
        DF_CHECK(&t, duoforge_battle_request(c1, f6, 0, &r0) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_request(c1, f6, 1, &r1) == DUOFORGE_OK);
        DF_CHECK(&t, r0.requested == 1u && r0.slot_mask == 1u && r0.candidate_count == 2u);
        DF_CHECK(&t, r1.requested == 1u && r1.slot_mask == 2u && r1.candidate_count == 2u);
        first_bundle(&t, c1, f6, &bd);
        rejected(&t, c1, f6, &bd, DUOFORGE_E_UNSUPPORTED, "two-side pivot (honest UNSUPPORTED)");
        duoforge_battle_destroy(f5);
        duoforge_battle_destroy(f6);
    }

    duoforge_context_destroy(c1);
    duoforge_context_destroy(c4);
    return df_test_end(&t);
}
