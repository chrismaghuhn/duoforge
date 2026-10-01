/*
 * duoforge.batch.equivalence: the batch runtime (decision 0012) plays what
 * the single-battle API plays. The native mode gives the same records for
 * 1, 2, 3, 4, 8 and 16 workers as a sequential reference; the step mode,
 * driven with the same policy, ends every environment in the reference's
 * final state; a reset gives the next episode's fresh battle; a failing
 * environment keeps its state while the others step.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge_batch.h>

#include "support/check.h"
#include "support/fixtures.h"

#define ENVS 37u
#define EPISODES 3u
#define MAX_STEPS 1000u
#define SEED 0x2026100200000012u

static duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];
static duoforge_side_choice all_cands[ENVS * 2u * DUOFORGE_MAX_CANDIDATES];
static uint32_t counts[ENVS * 2u];
static duoforge_request requests[ENVS * 2u];
static duoforge_event events[2][DUOFORGE_MAX_EVENTS];
static duoforge_battle_setup setups[ENVS];
static duoforge_batch_episode ref[ENVS * (EPISODES + 1u)]; /* episodes 0..EPISODES */
static duoforge_batch_episode got[ENVS * EPISODES];

static uint64_t next(uint64_t *s)
{
    *s += 0x9E3779B97F4A7C15u;
    uint64_t z = *s;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9u;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBu;
    return z ^ (z >> 31);
}

/* Episode `k` of environment `e` played with the single-battle API. */
static bool reference(const duoforge_context *ctx, uint32_t e, uint32_t k, duoforge_batch_episode *rec)
{
    duoforge_battle_setup s = setups[e];
    uint64_t policy = 0u;
    duoforge_batch_seeds(SEED, e, k, &s.rng_initstate, &s.rng_initseq, &policy);
    duoforge_battle *b = NULL;
    if (duoforge_battle_create(ctx, &s, &b) != DUOFORGE_OK) {
        return false;
    }
    memset(rec, 0, sizeof *rec);
    rec->env = e;
    rec->episode = k;
    bool ok = true;
    for (;;) {
        duoforge_decision_bundle bd;
        memset(&bd, 0, sizeof bd);
        for (uint32_t p = 0u; p < 2u && ok; ++p) {
            duoforge_request rq;
            uint32_t n = 0u;
            ok = duoforge_battle_request(ctx, b, p, &rq) == DUOFORGE_OK;
            bd.epoch = rq.epoch;
            if (ok && rq.requested != 0u) {
                ok = duoforge_battle_candidates(ctx, b, p, cands, DUOFORGE_MAX_CANDIDATES, &n) == DUOFORGE_OK &&
                     n > 0u;
                if (ok) {
                    bd.response_mask = (uint8_t)(bd.response_mask | (1u << p));
                    bd.responses[p] = cands[next(&policy) % n];
                    rec->decisions += 1u;
                }
            }
        }
        if (!ok || bd.response_mask == 0u || rec->steps >= MAX_STEPS) {
            break;
        }
        duoforge_step_result res;
        duoforge_event_buffer buffers[2] = {{events[0], DUOFORGE_MAX_EVENTS, 0u}, {events[1], DUOFORGE_MAX_EVENTS, 0u}};
        ok = duoforge_battle_step_events(ctx, b, &bd, &res, buffers) == DUOFORGE_OK;
        for (uint32_t i = 0u; ok && i < buffers[0].count; ++i) {
            if (events[0][i].kind == DUOFORGE_EVENT_RESULT) {
                rec->result = events[0][i].detail;
            }
        }
        rec->steps += 1u;
    }
    duoforge_observation ob;
    memset(&ob, 0, sizeof ob);
    ok = ok && duoforge_battle_observe(ctx, b, 0u, &ob) == DUOFORGE_OK &&
         duoforge_battle_digest(ctx, b, rec->digest) == DUOFORGE_OK;
    rec->turns = ok ? ob.turn : 0u;
    duoforge_battle_destroy(b);
    return ok;
}

static duoforge_batch *make_batch(df_test *t, const duoforge_context *ctx, uint32_t workers)
{
    duoforge_batch_config c = {ENVS, workers, SEED, setups};
    duoforge_batch *b = NULL;
    DF_CHECK(t, duoforge_batch_create(ctx, &c, &b) == DUOFORGE_OK && b != NULL);
    return b;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.batch.equivalence");
    duoforge_context *ctx = df_make_context(&df_config_k1);
    duoforge_battle_setup teams;
    df_setup_teams(&teams);
    static const uint32_t pick[4][2] = {{0u, 1u}, {1u, 0u}, {0u, 0u}, {1u, 1u}};
    for (uint32_t e = 0u; e < ENVS; ++e) {
        setups[e] = teams;
        setups[e].sides[0] = teams.sides[pick[e % 4u][0]];
        setups[e].sides[1] = teams.sides[pick[e % 4u][1]];
    }
    for (uint32_t e = 0u; e < ENVS; ++e) {
        for (uint32_t k = 0u; k <= EPISODES; ++k) {
            DF_CHECK(&t, reference(ctx, e, k, &ref[e * (EPISODES + 1u) + k]));
        }
    }

    /* Seeds: a pure function, initseq below 2^63. */
    {
        uint64_t a[3];
        uint64_t b[3];
        duoforge_batch_seeds(SEED, 5u, 2u, &a[0], &a[1], &a[2]);
        duoforge_batch_seeds(SEED, 5u, 2u, &b[0], &b[1], &b[2]);
        DF_CHECK(&t, memcmp(a, b, sizeof a) == 0 && a[1] < (1ull << 63));
        duoforge_batch_seeds(SEED, 5u, 3u, &b[0], &b[1], &b[2]);
        DF_CHECK(&t, a[0] != b[0] && a[2] != b[2]);
    }

    /* Configuration checks: nothing is written on failure. */
    {
        duoforge_batch *marker = (duoforge_batch *)(void *)&t;
        duoforge_batch *out = marker;
        duoforge_batch_config c = {0u, 1u, SEED, setups};
        DF_CHECK(&t, duoforge_batch_create(ctx, &c, &out) == DUOFORGE_E_INVALID_ARGUMENT && out == marker);
        c.env_count = ENVS;
        c.worker_count = 0u;
        DF_CHECK(&t, duoforge_batch_create(ctx, &c, &out) == DUOFORGE_E_INVALID_ARGUMENT && out == marker);
        c.worker_count = DUOFORGE_BATCH_MAX_WORKERS + 1u;
        DF_CHECK(&t, duoforge_batch_create(ctx, &c, &out) == DUOFORGE_E_INVALID_ARGUMENT && out == marker);
        c.worker_count = 2u;
        c.setups = NULL;
        DF_CHECK(&t, duoforge_batch_create(ctx, &c, &out) == DUOFORGE_E_NULL_ARGUMENT && out == marker);
        DF_CHECK(&t, duoforge_batch_create(NULL, &c, &out) == DUOFORGE_E_NULL_ARGUMENT && out == marker);
        duoforge_batch_destroy(NULL);
    }

    /* Native mode: episodes 1..EPISODES, the same records for every worker count. */
    static const uint32_t worker_counts[] = {1u, 2u, 3u, 4u, 8u, 16u};
    for (size_t w = 0u; w < sizeof worker_counts / sizeof worker_counts[0]; ++w) {
        duoforge_batch *b = make_batch(&t, ctx, worker_counts[w]);
        if (b == NULL) {
            continue;
        }
        memset(got, 0, sizeof got);
        DF_CHECK(&t, duoforge_batch_play_random(b, EPISODES, MAX_STEPS, got) == DUOFORGE_OK);
        unsigned bad = 0u;
        for (uint32_t e = 0u; e < ENVS; ++e) {
            for (uint32_t k = 0u; k < EPISODES; ++k) {
                if (memcmp(&got[e * EPISODES + k], &ref[e * (EPISODES + 1u) + k + 1u], sizeof got[0]) != 0) {
                    bad += 1u;
                }
            }
            DF_CHECK_EQ_U64(&t, duoforge_batch_env_episode(b, e), EPISODES);
        }
        if (!DF_CHECK_EQ_U64(&t, bad, 0u)) {
            fprintf(stderr, "  native mode, %u workers: %u records differ\n", worker_counts[w], bad);
        }
        duoforge_batch_destroy(b);
    }

    /* Step mode with the same policy: episode 0 to the end, then a reset. */
    static const uint32_t step_workers[] = {1u, 4u};
    for (size_t w = 0u; w < sizeof step_workers / sizeof step_workers[0]; ++w) {
        duoforge_batch *b = make_batch(&t, ctx, step_workers[w]);
        if (b == NULL) {
            continue;
        }
        uint64_t policy[ENVS];
        for (uint32_t e = 0u; e < ENVS; ++e) {
            duoforge_batch_seeds(SEED, e, 0u, NULL, NULL, &policy[e]);
        }
        static duoforge_decision_bundle bundles[ENVS];
        static duoforge_status statuses[ENVS];
        static duoforge_step_result results[ENVS];
        bool live = true;
        for (uint32_t round = 0u; live && round < MAX_STEPS; ++round) {
            if (!DF_CHECK(&t, duoforge_batch_query(b, requests, NULL, all_cands, counts) == DUOFORGE_OK)) {
                break;
            }
            live = false;
            for (uint32_t e = 0u; e < ENVS; ++e) {
                memset(&bundles[e], 0, sizeof bundles[e]);
                for (uint32_t p = 0u; p < 2u; ++p) {
                    const duoforge_request *rq = &requests[e * 2u + p];
                    bundles[e].epoch = rq->epoch;
                    if (rq->requested != 0u) {
                        const uint32_t n = counts[e * 2u + p];
                        bundles[e].response_mask = (uint8_t)(bundles[e].response_mask | (1u << p));
                        bundles[e].responses[p] = all_cands[(e * 2u + p) * DUOFORGE_MAX_CANDIDATES + next(&policy[e]) % n];
                        live = true;
                    }
                }
            }
            if (live) {
                DF_CHECK(&t, duoforge_batch_step(b, bundles, statuses, results) == DUOFORGE_OK);
            }
        }
        unsigned bad = 0u;
        for (uint32_t e = 0u; e < ENVS; ++e) {
            uint8_t d[DUOFORGE_DIGEST_SIZE];
            if (duoforge_battle_digest(ctx, duoforge_batch_env(b, e), d) != DUOFORGE_OK ||
                memcmp(d, ref[e * (EPISODES + 1u)].digest, sizeof d) != 0) {
                bad += 1u;
            }
        }
        if (!DF_CHECK_EQ_U64(&t, bad, 0u)) {
            fprintf(stderr, "  step mode, %u workers: %u environments differ\n", step_workers[w], bad);
        }
        /* Every environment is TERMINAL: a reset gives episode 1's fresh battle. */
        DF_CHECK(&t, duoforge_batch_reset_terminal(b) == DUOFORGE_OK);
        bad = 0u;
        for (uint32_t e = 0u; e < ENVS; ++e) {
            duoforge_battle_setup s = setups[e];
            duoforge_batch_seeds(SEED, e, 1u, &s.rng_initstate, &s.rng_initseq, NULL);
            duoforge_battle *fresh = NULL;
            uint8_t want[DUOFORGE_DIGEST_SIZE];
            uint8_t have[DUOFORGE_DIGEST_SIZE];
            if (duoforge_battle_create(ctx, &s, &fresh) != DUOFORGE_OK ||
                duoforge_battle_digest(ctx, fresh, want) != DUOFORGE_OK ||
                duoforge_battle_digest(ctx, duoforge_batch_env(b, e), have) != DUOFORGE_OK ||
                memcmp(want, have, sizeof want) != 0 || duoforge_batch_env_episode(b, e) != 1u) {
                bad += 1u;
            }
            duoforge_battle_destroy(fresh);
        }
        DF_CHECK_EQ_U64(&t, bad, 0u);
        duoforge_batch_destroy(b);
    }

    /* Outcomes are atomic per environment. */
    {
        duoforge_batch *b = make_batch(&t, ctx, 4u);
        if (b != NULL) {
            static duoforge_decision_bundle bundles[ENVS];
            static duoforge_status statuses[ENVS];
            static duoforge_step_result results[ENVS];
            DF_CHECK(&t, duoforge_batch_query(b, requests, NULL, all_cands, counts) == DUOFORGE_OK);
            for (uint32_t e = 0u; e < ENVS; ++e) {
                memset(&bundles[e], 0, sizeof bundles[e]);
                bundles[e].epoch = requests[e * 2u].epoch;
                for (uint32_t p = 0u; p < 2u; ++p) {
                    bundles[e].response_mask = (uint8_t)(bundles[e].response_mask | (1u << p));
                    bundles[e].responses[p] = all_cands[(e * 2u + p) * DUOFORGE_MAX_CANDIDATES];
                }
            }
            bundles[5].epoch += 1u; /* a stale bundle for environment 5 */
            bundles[9].epoch += 1u;
            uint8_t before[DUOFORGE_DIGEST_SIZE];
            uint8_t after[DUOFORGE_DIGEST_SIZE];
            DF_CHECK(&t, duoforge_battle_digest(ctx, duoforge_batch_env(b, 5u), before) == DUOFORGE_OK);
            DF_CHECK(&t, duoforge_batch_step(b, bundles, statuses, results) == DUOFORGE_E_STALE_EPOCH);
            DF_CHECK(&t, duoforge_battle_digest(ctx, duoforge_batch_env(b, 5u), after) == DUOFORGE_OK &&
                             memcmp(before, after, sizeof before) == 0);
            unsigned stepped = 0u;
            for (uint32_t e = 0u; e < ENVS; ++e) {
                stepped += statuses[e] == DUOFORGE_OK ? 1u : 0u;
            }
            DF_CHECK(&t, statuses[5] == DUOFORGE_E_STALE_EPOCH && statuses[9] == DUOFORGE_E_STALE_EPOCH);
            DF_CHECK_EQ_U64(&t, stepped, ENVS - 2u);
            duoforge_batch_destroy(b);
        }
    }

    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
