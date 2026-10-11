/*
 * duoforge.request.query_checks: the model-facing queries run the query
 * check (decision 0011). A corrupted derived value or move of a CLOSURE
 * member passes the queries and is reported where the full check runs
 * (check, step, encode, digest); a corrupted index, count or divisor is
 * reported by the queries themselves.
 */
#include <stdio.h>
#include <string.h>

#include "data/closure_tables.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"

static duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];

/* The statuses of request, candidates and observe for player 0. */
static void queries(const duoforge_context *ctx, const duoforge_battle *b, duoforge_status out[3])
{
    duoforge_request rq;
    duoforge_observation ob;
    uint32_t n = 0u;
    out[0] = duoforge_battle_request(ctx, b, 0u, &rq);
    out[1] = duoforge_battle_candidates(ctx, b, 0u, cands, DUOFORGE_MAX_CANDIDATES, &n);
    out[2] = duoforge_battle_observe(ctx, b, 0u, &ob);
}

static bool all_are(const duoforge_status st[3], duoforge_status want)
{
    return st[0] == want && st[1] == want && st[2] == want;
}

/* A valid bundle at the battle's boundary: every requested player's first
 * candidate. */
static bool first_bundle(const duoforge_context *ctx, const duoforge_battle *b, duoforge_decision_bundle *out)
{
    memset(out, 0, sizeof *out);
    for (uint32_t p = 0u; p < 2u; ++p) {
        duoforge_request rq;
        uint32_t n = 0u;
        if (duoforge_battle_request(ctx, b, p, &rq) != DUOFORGE_OK) {
            return false;
        }
        out->epoch = rq.epoch;
        if (rq.requested != 0u) {
            if (duoforge_battle_candidates(ctx, b, p, cands, DUOFORGE_MAX_CANDIDATES, &n) != DUOFORGE_OK || n == 0u) {
                return false;
            }
            out->response_mask = (uint8_t)(out->response_mask | (1u << p));
            out->responses[p] = cands[0];
        }
    }
    return true;
}

/* The full check reports the corruption: check, step, encode and digest. */
static void full_reports(df_test *t, const duoforge_context *ctx, duoforge_battle *x,
                         const duoforge_decision_bundle *bundle, const char *what)
{
    uint8_t digest[DUOFORGE_DIGEST_SIZE];
    uint8_t bytes[4096];
    size_t written = 0u;
    duoforge_step_result res;
    const bool ok = duoforge_battle_check(ctx, x) == DUOFORGE_E_INVARIANT &&
                    duoforge_battle_digest(ctx, x, digest) == DUOFORGE_E_INVARIANT &&
                    duoforge_battle_encode(ctx, x, bytes, sizeof bytes, &written) == DUOFORGE_E_INVARIANT &&
                    duoforge_battle_step(ctx, x, bundle, &res) == DUOFORGE_E_INVARIANT;
    if (!DF_CHECK(t, ok)) {
        fprintf(stderr, "  %s: the full check does not report it\n", what);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.request.query_checks");
    duoforge_context *ctx = df_make_context(&df_config_k1);
    duoforge_battle_setup s;
    df_setup_teams(&s);
    duoforge_battle *b = df_make_battle(ctx, &s);
    duoforge_battle *x = NULL;
    DF_CHECK(&t, b != NULL && duoforge_battle_clone(ctx, b, &x) == DUOFORGE_OK);
    duoforge_decision_bundle bundle;
    DF_CHECK(&t, first_bundle(ctx, b, &bundle));
    duoforge_status st[3];
    queries(ctx, b, st);
    DF_CHECK(&t, all_are(st, DUOFORGE_OK) && duoforge_battle_check(ctx, b) == DUOFORGE_OK);

    /* Derived values and move legality: the queries pass, the full check
     * reports them. */
    {
        DF_CHECK(&t, duoforge_battle_copy(ctx, x, b) == DUOFORGE_OK);
        x->sides[1].members[0].stats[1] = (uint16_t)(x->sides[1].members[0].stats[1] + 1u);
        queries(ctx, x, st);
        DF_CHECK(&t, all_are(st, DUOFORGE_OK));
        full_reports(&t, ctx, x, &bundle, "a derived stat");
    }
    {
        DF_CHECK(&t, duoforge_battle_copy(ctx, x, b) == DUOFORGE_OK);
        dfi_move_slot *mv = &x->sides[0].members[2].moves[1];
        mv->pp_max = (uint8_t)(mv->pp_max + 1u); /* pp <= pp_max still holds */
        queries(ctx, x, st);
        DF_CHECK(&t, all_are(st, DUOFORGE_OK));
        full_reports(&t, ctx, x, &bundle, "a PP maximum");
    }
    {
        DF_CHECK(&t, duoforge_battle_copy(ctx, x, b) == DUOFORGE_OK);
        dfi_member *m = &x->sides[1].members[3];
        m->moves[1] = m->moves[0]; /* a repeated move */
        queries(ctx, x, st);
        DF_CHECK(&t, all_are(st, DUOFORGE_OK));
        full_reports(&t, ctx, x, &bundle, "a repeated move");
    }

    /* Indices, counts and divisors: the queries report them. */
    {
        DF_CHECK(&t, duoforge_battle_copy(ctx, x, b) == DUOFORGE_OK);
        x->sides[1].members[0].nature = (uint8_t)DFI_NATURE_COUNT;
        queries(ctx, x, st);
        DF_CHECK(&t, all_are(st, DUOFORGE_E_INVARIANT));
    }
    {
        DF_CHECK(&t, duoforge_battle_copy(ctx, x, b) == DUOFORGE_OK);
        x->sides[0].members[1].species_id = 200u;
        queries(ctx, x, st);
        DF_CHECK(&t, all_are(st, DUOFORGE_E_INVARIANT));
    }
    {
        DF_CHECK(&t, duoforge_battle_copy(ctx, x, b) == DUOFORGE_OK);
        x->sides[1].members[4].hp_max = 0u;
        x->sides[1].members[4].hp = 0u;
        queries(ctx, x, st);
        DF_CHECK(&t, all_are(st, DUOFORGE_E_INVARIANT));
    }
    {
        DF_CHECK(&t, duoforge_battle_copy(ctx, x, b) == DUOFORGE_OK);
        x->sides[0].members[0].moves[0].move_id = 250u;
        queries(ctx, x, st);
        DF_CHECK(&t, all_are(st, DUOFORGE_E_INVARIANT));
    }

    duoforge_battle_destroy(x);
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
