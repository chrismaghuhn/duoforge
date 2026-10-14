/* Decision 0082/E1b: public expansion, real reconstructed worlds, workers,
 * chunk/permutation invariance, preflight, refusal phases and legacy parity. */
#include <string.h>
#include <duoforge/duoforge_search.h>
#include <duoforge/duoforge_view.h>
#include "batch/batch_each.h"
#include "state/request.h"
#include "state/observation_digest.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"
#define CHECK_BYTES(t, a, b, n, why) DF_CHECK_BYTES((t), (const uint8_t *)(a), (const uint8_t *)(b), (n), (why))
#define N 8u
#define WIDTH 850u
#define SEED UINT64_C(0x2026101400000082)
typedef struct output {
    duoforge_status step[N + 1u], encode[N + 1u], digest_status[N + 1u];
    duoforge_step_result result[N + 1u];
    uint32_t outcome[N + 1u];
    uint8_t digest[(N + 1u) * 32u];
    float rows[(N + 1u) * WIDTH];
} output;
static output a, b, old, sentinel;
static duoforge_request requests[4];
static duoforge_factored_domain domains[4];
static uint64_t keys[2] = {91u, 91u};
static uint8_t viewers[2] = {0u, 0u};
static uint32_t roots_of[N], samples[N];
static duoforge_factored_choice choices[2u * N];
static uint64_t mask;
static duoforge_batch *make(df_test *t, const duoforge_context *ctx, uint32_t n, uint32_t workers)
{
    duoforge_battle_setup setup[N];
    for (uint32_t i = 0u; i < n; ++i) { DF_CHECK(t, duoforge_reference_setup(0u, &setup[i]) == DUOFORGE_OK); }
    duoforge_batch_config config = {n, workers, SEED, setup};
    duoforge_batch *batch = NULL;
    DF_CHECK(t, duoforge_batch_create(ctx, &config, &batch) == DUOFORGE_OK);
    return batch;
}
static duoforge_factored_choice first(const duoforge_factored_domain *d)
{
    duoforge_factored_choice c = {0};
    if (d->kind == DUOFORGE_CHOICE_TEAM_SELECTION) {
        for (uint32_t k = 0u; k < d->pick_count; ++k) { c.picks[k] = (uint8_t)k; }
    } else {
        for (uint32_t i = 0u; i < d->slot_count[0]; ++i) {
            for (uint32_t j = 0u; j < d->slot_count[1]; ++j) {
                if (((d->allowed[i] >> j) & 1u) != 0u) { c.slot[0] = (uint8_t)i; c.slot[1] = (uint8_t)j; return c; }
            }
        }
    }
    return c;
}
static void query(df_test *t, duoforge_batch *roots)
{
    DF_CHECK(t, duoforge_batch_query_factored(roots, requests, NULL, domains) == DUOFORGE_OK);
    for (uint32_t i = 0u; i < N; ++i) {
        roots_of[i] = i % 2u; samples[i] = i / 2u;
        for (uint32_t p = 0u; p < 2u; ++p) { choices[2u * i + p] = first(&domains[2u * roots_of[i] + p]); }
    }
    duoforge_observation_ext ext;
    DF_CHECK(t, duoforge_battle_observe_ext(dfi_batch_context(roots), duoforge_batch_env(roots, 0u), 0u, &ext) == DUOFORGE_OK);
    mask = ext.supported & ((UINT64_C(1) << DUOFORGE_VIEWEXT_FEATURE_TRANSFORM) - 1u);
}
static duoforge_status expand(duoforge_batch *leaves, duoforge_batch *roots, uint32_t count,
                               output *out, bool rows, duoforge_eval_error *error)
{
    return duoforge_batch_expand_digest(leaves, roots, 4u, mask, SEED, requests, domains, keys, viewers,
        count, roots_of, samples, choices, out->step, out->encode, out->result, out->outcome,
        rows ? out->rows : NULL, out->digest, out->digest_status, error);
}
static void compare(df_test *t, const duoforge_context *ctx, const duoforge_batch *x,
                      const duoforge_batch *y, uint32_t count)
{
    for (uint32_t i = 0u; i < count; ++i) {
        bool equal = false;
        DF_CHECK(t, duoforge_battle_equal(ctx, duoforge_batch_env(x, i), duoforge_batch_env(y, i), &equal) == DUOFORGE_OK && equal);
    }
}
static void parity(df_test *t, const duoforge_context *ctx, duoforge_batch *roots,
                     duoforge_batch *one, duoforge_batch *many)
{
    uint8_t root_before[2][32], root_after[32];
    for (uint32_t i = 0u; i < 2u; ++i) { DF_CHECK(t, duoforge_battle_digest(ctx, duoforge_batch_env(roots, i), root_before[i]) == DUOFORGE_OK); }
    query(t, roots); memset(&a, 0xA5, sizeof a); b = a; old = a; sentinel = a;
    duoforge_eval_error error;
    const duoforge_status got = expand(one, roots, N, &a, true, &error);
    DF_CHECK(t, got == expand(many, roots, N, &b, true, &error));
    CHECK_BYTES(t, &a, &b, sizeof a, "worker-independent outputs and untouched tails");
    compare(t, ctx, one, many, N);
    const duoforge_status legacy = duoforge_batch_expand(many, roots, 4u, mask, SEED, requests, domains, keys,
        viewers, N, roots_of, samples, choices, old.step, old.encode, old.result, old.outcome, old.rows);
    DF_CHECK(t, got == legacy);
    CHECK_BYTES(t, a.step, old.step, sizeof a.step, "legacy step statuses");
    CHECK_BYTES(t, a.encode, old.encode, sizeof a.encode, "legacy encoder statuses");
    CHECK_BYTES(t, a.result, old.result, sizeof a.result, "legacy step results");
    CHECK_BYTES(t, a.outcome, old.outcome, sizeof a.outcome, "legacy terminal utilities");
    CHECK_BYTES(t, a.rows, old.rows, sizeof a.rows, "legacy encoder rows");
    compare(t, ctx, one, many, N);
    for (uint32_t i = 0u; i < N; ++i) {
        DF_CHECK(t, a.step[i] == DUOFORGE_OK && a.digest_status[i] == DUOFORGE_OK);
        duoforge_battle *ref = NULL;
        DF_CHECK(t, duoforge_battle_clone(ctx, duoforge_batch_env(roots, roots_of[i]), &ref) == DUOFORGE_OK);
        uint64_t state, seq; duoforge_search_seeds(SEED, keys[roots_of[i]], samples[i], &state, &seq);
        DF_CHECK(t, duoforge_battle_reseed(ctx, ref, state, seq) == DUOFORGE_OK);
        duoforge_decision_bundle bundle;
        DF_CHECK(t, dfi_factored_bundle(&requests[2u * roots_of[i]], &domains[2u * roots_of[i]], &choices[2u * i], &bundle) == DUOFORGE_OK);
        dfi_observation_digest observer; observer.viewer = viewers[roots_of[i]];
        duoforge_step_result result;
        DF_CHECK(t, dfi_battle_step_observed(ctx, ref, &bundle, NULL, 0u, NULL, &result, NULL, &observer) == DUOFORGE_OK);
        DF_CHECK(t, observer.complete && observer.status == DUOFORGE_OK);
        CHECK_BYTES(t, a.digest + 32u * i, observer.digest, 32u, "single observed step parity");
        duoforge_battle_destroy(ref);
    }
    CHECK_BYTES(t, a.digest + 32u * N, sentinel.digest + 32u * N, 32u, "digest tail untouched");
    /* Reorder and a shorter chunk: each logical leaf keeps its key. */
    for (uint32_t i = 0u; i < N / 2u; ++i) {
        const uint32_t other = N - 1u - i;
        const uint32_t r = roots_of[i], s = samples[i]; roots_of[i] = roots_of[other]; samples[i] = samples[other];
        roots_of[other] = r; samples[other] = s;
        for (uint32_t p = 0u; p < 2u; ++p) {
            const duoforge_factored_choice c = choices[2u * i + p];
            choices[2u * i + p] = choices[2u * other + p]; choices[2u * other + p] = c;
        }
    }
    b = sentinel; DF_CHECK(t, expand(many, roots, 3u, &b, false, NULL) == DUOFORGE_OK);
    for (uint32_t i = 0u; i < 3u; ++i) { CHECK_BYTES(t, b.digest + 32u * i, a.digest + 32u * (N - 1u - i), 32u, "chunk/permutation parity"); }
    CHECK_BYTES(t, b.rows, sentinel.rows, sizeof b.rows, "digest-only mode never writes rows");
    CHECK_BYTES(t, b.digest + 3u * 32u, sentinel.digest + 3u * 32u, (N - 2u) * 32u, "short chunk digest tail");
    for (uint32_t i = 0u; i < 2u; ++i) {
        DF_CHECK(t, duoforge_battle_digest(ctx, duoforge_batch_env(roots, i), root_after) == DUOFORGE_OK);
        CHECK_BYTES(t, root_before[i], root_after, 32u, "roots and RNG stay read-only");
    }
}
static void preflight(df_test *t, const duoforge_context *ctx, duoforge_batch *roots, duoforge_batch *leaves)
{
    query(t, roots); uint8_t before[N][32], after[32];
    for (uint32_t i = 0u; i < N; ++i) { DF_CHECK(t, duoforge_battle_digest(ctx, duoforge_batch_env(leaves, i), before[i]) == DUOFORGE_OK); }
    memset(&a, 0xA5, sizeof a); sentinel = a;
    duoforge_eval_error error;
    viewers[1] = 2u; /* A valid first leaf must not execute before this later invalid viewer. */
    DF_CHECK(t, expand(leaves, roots, N, &a, true, &error) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, error.leaf == UINT32_MAX && strcmp(error.phase, "preflight") == 0 && strcmp(error.reason, "observation_viewer") == 0);
    CHECK_BYTES(t, &a, &sentinel, sizeof a, "viewer preflight preserves every output byte");
    for (uint32_t i = 0u; i < N; ++i) {
        DF_CHECK(t, duoforge_battle_digest(ctx, duoforge_batch_env(leaves, i), after) == DUOFORGE_OK);
        CHECK_BYTES(t, before[i], after, 32u, "viewer preflight preserves every leaf/RNG");
    }
    viewers[1] = 0u;
    roots_of[1] = UINT32_MAX;
    DF_CHECK(t, expand(leaves, roots, N, &a, false, &error) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, strcmp(error.reason, "expand_root_index") == 0);
    roots_of[1] = 1u;
    DF_CHECK(t, expand(leaves, roots, N + 1u, &a, false, &error) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, expand(roots, roots, 0u, &a, false, &error) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_batch_expand_digest(leaves, roots, 4u, mask, SEED, NULL, NULL, NULL, NULL,
        0u, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, &error) == DUOFORGE_OK);
    DF_CHECK(t, error.leaf == UINT32_MAX && error.phase[0] == '\0' && error.reason[0] == '\0');
    DF_CHECK(t, duoforge_batch_expand_digest(leaves, roots, 4u, mask, SEED, requests, domains, keys, viewers,
        N, roots_of, samples, choices, a.step, a.encode, a.result, a.outcome, NULL, NULL, a.digest_status, &error) == DUOFORGE_E_NULL_ARGUMENT);
    CHECK_BYTES(t, &a, &sentinel, sizeof a, "other preflights preserve output bytes");
}
static void reprompt(void *arg, uint32_t i, const duoforge_context *ctx, duoforge_battle *root, bool *terminal)
{
    df_test *t = arg;
    (void)i; (void)terminal;
    duoforge_side_choice accepted[DUOFORGE_MAX_CANDIDATES]; uint32_t count = 0u;
    DF_CHECK(t, duoforge_battle_candidates(ctx, root, 1u, accepted, DUOFORGE_MAX_CANDIDATES, &count) == DUOFORGE_OK && count > 0u);
    DF_CHECK(t, dfi_reprompt_side(ctx, root, 0u, &accepted[0]) == DUOFORGE_OK);
}
static void determinization(df_test *t, const duoforge_context *ctx, duoforge_batch *truth,
                              duoforge_batch *worlds, duoforge_batch *leaves)
{
    query(t, truth);
    duoforge_factored_choice team_choices[4];
    for (uint32_t p = 0u; p < 4u; ++p) { team_choices[p] = first(&domains[p]); }
    duoforge_status status[2]; duoforge_step_result result[2];
    DF_CHECK(t, duoforge_batch_step_factored(truth, requests, domains, team_choices, status, result) == DUOFORGE_OK);
    duoforge_public_state views[2]; duoforge_hypothesis hypotheses[2];
    DF_CHECK(t, duoforge_battle_public(ctx, duoforge_batch_env(truth, 0u), 0u, &views[0]) == DUOFORGE_OK);
    views[1] = views[0];
    DF_CHECK(t, duoforge_battle_hypothesis(ctx, duoforge_batch_env(truth, 0u), 0u, &hypotheses[0]) == DUOFORGE_OK);
    hypotheses[1] = hypotheses[0];
    const uint32_t bench = hypotheses[0].pick_order[2];
    hypotheses[1].pick_order[2] = hypotheses[0].pick_order[3];
    hypotheses[1].pick_order[3] = hypotheses[0].pick_order[2];
    /* An unseen brought bench member has a different hidden spread/max HP. */
    memset(hypotheses[1].stat_points[bench], 0, 6u);
    hypotheses[1].stat_points[bench][0] = hypotheses[0].stat_points[bench][0] == 0u ? 1u : 0u;
    DF_CHECK(t, duoforge_batch_from_view(worlds, views, hypotheses, 2u, status) == DUOFORGE_OK);
    bool equal = true;
    DF_CHECK(t, duoforge_battle_equal(ctx, duoforge_batch_env(worlds, 0u), duoforge_batch_env(worlds, 1u), &equal) == DUOFORGE_OK && !equal);
    for (uint32_t i = 0u; i < 2u; ++i) {
        duoforge_public_state same;
        DF_CHECK(t, duoforge_battle_public(ctx, duoforge_batch_env(worlds, i), 0u, &same) == DUOFORGE_OK);
        CHECK_BYTES(t, &views[0], &same, sizeof same, "both worlds rebuild the identical parent history/view");
    }
    query(t, worlds); memset(&a, 0xA5, sizeof a);
    CHECK_BYTES(t, choices, choices + 2u, 2u * sizeof choices[0], "same joint action across determinizations");
    DF_CHECK(t, expand(leaves, worlds, 2u, &a, false, NULL) == DUOFORGE_OK);
    DF_CHECK(t, a.step[0] == DUOFORGE_OK && a.step[1] == DUOFORGE_OK && a.digest_status[0] == DUOFORGE_OK && a.digest_status[1] == DUOFORGE_OK);
    CHECK_BYTES(t, a.digest, a.digest + 32u, 32u, "E1 gate: real reconstructed worlds, real step, equal viewer digest");
    /* Turn reprompt: no observer ran for its retained/sealed command. */
    dfi_batch_leaves(worlds, 1u, reprompt, t);
    query(t, worlds); duoforge_eval_error error; memset(&a, 0xA5, sizeof a);
    DF_CHECK(t, expand(leaves, worlds, 2u, &a, true, &error) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, error.leaf == 0u && strcmp(error.phase, "digest") == 0 && strcmp(error.reason, "observation_reprompt_unsupported") == 0);
    uint8_t zero[32] = {0}; CHECK_BYTES(t, a.digest, zero, 32u, "reprompt publishes no key");
    DF_CHECK(t, a.step[0] == DUOFORGE_OK && a.digest_status[0] == DUOFORGE_E_UNSUPPORTED && a.encode[0] == DUOFORGE_OK);
    DF_CHECK(t, a.step[1] == DUOFORGE_OK && a.digest_status[1] == DUOFORGE_OK);
    duoforge_batch *legacy = make(t, ctx, N, 1u);
    old = sentinel;
    DF_CHECK(t, duoforge_batch_expand(legacy, worlds, 4u, mask, SEED, requests, domains, keys,
        viewers, 2u, roots_of, samples, choices, old.step, old.encode, old.result, old.outcome, old.rows) == DUOFORGE_OK);
    CHECK_BYTES(t, a.step, old.step, 2u * sizeof a.step[0], "reprompt steps equal legacy success");
    CHECK_BYTES(t, a.encode, old.encode, 2u * sizeof a.encode[0], "reprompt encoder statuses equal legacy");
    CHECK_BYTES(t, a.result, old.result, 2u * sizeof a.result[0], "reprompt results equal legacy");
    CHECK_BYTES(t, a.outcome, old.outcome, 2u * sizeof a.outcome[0], "reprompt outcomes equal legacy");
    CHECK_BYTES(t, a.rows, old.rows, 2u * WIDTH * sizeof a.rows[0], "reprompt rows equal legacy");
    compare(t, ctx, leaves, legacy, 2u);
    for (uint32_t workers = 1u; workers <= 3u; ++workers) {
        duoforge_batch *other = make(t, ctx, N, workers);
        b = sentinel; DF_CHECK(t, expand(other, worlds, 2u, &b, true, &error) == DUOFORGE_E_UNSUPPORTED);
        DF_CHECK(t, error.leaf == 0u && strcmp(error.phase, "digest") == 0 && strcmp(error.reason, "observation_reprompt_unsupported") == 0);
        CHECK_BYTES(t, a.step, b.step, 2u * sizeof a.step[0], "reprompt step statuses independent of workers");
        CHECK_BYTES(t, a.digest_status, b.digest_status, 2u * sizeof a.digest_status[0], "reprompt digest statuses independent of workers");
        CHECK_BYTES(t, a.rows, b.rows, 2u * WIDTH * sizeof a.rows[0], "reprompt rows independent of workers");
        compare(t, ctx, other, legacy, 2u);
        duoforge_batch_destroy(other);
    }
    duoforge_batch_destroy(legacy);
    const duoforge_factored_choice valid = choices[2];
    choices[2].slot[0] = UINT8_MAX;
    DF_CHECK(t, expand(leaves, worlds, 2u, &a, false, &error) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, a.step[0] == DUOFORGE_OK && a.digest_status[0] == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, a.step[1] == DUOFORGE_E_INVALID_ARGUMENT && a.digest_status[1] == DUOFORGE_OK);
    DF_CHECK(t, error.leaf == 1u && strcmp(error.phase, "step") == 0);
    CHECK_BYTES(t, a.digest + 32u, zero, 32u, "genuine step failure still publishes no key");
    choices[2] = valid;
}
int main(void)
{
    df_test t; df_test_begin(&t, "duoforge.search.digest");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    duoforge_batch *roots = make(&t, ctx, 2u, 1u), *one = make(&t, ctx, N, 1u), *many = make(&t, ctx, N, 3u);
    const uint32_t workers[] = {1u, 2u, 3u, 4u, 8u, 16u};
    for (uint32_t i = 0u; i < sizeof workers / sizeof workers[0]; ++i) {
        viewers[0] = (uint8_t)(i % 2u); viewers[1] = (uint8_t)(1u - i % 2u);
        duoforge_batch *other = make(&t, ctx, N, workers[i]);
        parity(&t, ctx, roots, one, other);
        duoforge_batch_destroy(other);
    }
    viewers[0] = 0u; viewers[1] = 0u;
    preflight(&t, ctx, roots, many);
    duoforge_batch *worlds = make(&t, ctx, 2u, 1u);
    determinization(&t, ctx, roots, worlds, one);
    duoforge_batch_destroy(worlds);
    duoforge_batch_destroy(many); duoforge_batch_destroy(one); duoforge_batch_destroy(roots); duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
