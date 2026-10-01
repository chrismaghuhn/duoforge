/*
 * Batch runtime (decision 0012): environments of one context run by a fixed
 * worker pool. Every environment is an ordinary battle and every operation
 * on it a single-battle call, so a batch is the same calls one by one.
 */
#include <duoforge/duoforge_batch.h>

#include <string.h>

#include "batch/pool.h"
#include "core/alloc.h"

/* Per-worker scratch: a candidate list and the event buffers of a step. */
typedef struct dfi_batch_scratch {
    duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];
    duoforge_event events[DUOFORGE_SIDE_COUNT][DUOFORGE_MAX_EVENTS];
} dfi_batch_scratch;

typedef struct dfi_batch_env {
    duoforge_battle *battle;
    uint32_t episode;
    bool terminal;
} dfi_batch_env;

struct duoforge_batch {
    const duoforge_context *ctx;
    uint64_t seed;
    uint32_t env_count;
    dfi_batch_env *env;
    duoforge_battle_setup *setups;
    dfi_pool *pool;
    dfi_batch_scratch *scratch; /* one per worker */
};

/* ------------------------------------------------------------------ seeds */

/* One splitmix64 step from state z (Steele, Lea, Flood 2014). */
static uint64_t dfi_splitmix(uint64_t z)
{
    z += 0x9E3779B97F4A7C15u;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9u;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBu;
    return z ^ (z >> 31);
}

#define DFI_BATCH_TAG_STATE  0x6466737461746531u /* "dfstate1" */
#define DFI_BATCH_TAG_SEQ    0x6466736571756531u /* "dfseque1" */
#define DFI_BATCH_TAG_POLICY 0x6466706f6c696331u /* "dfpolic1" */

void duoforge_batch_seeds(uint64_t seed, uint32_t env, uint32_t episode, uint64_t *out_initstate,
                          uint64_t *out_initseq, uint64_t *out_policy_seed)
{
    const uint64_t key = seed ^ dfi_splitmix(((uint64_t)env << 32) | episode);
    if (out_initstate != NULL) {
        *out_initstate = dfi_splitmix(key ^ DFI_BATCH_TAG_STATE);
    }
    if (out_initseq != NULL) {
        *out_initseq = dfi_splitmix(key ^ DFI_BATCH_TAG_SEQ) >> 1; /* < 2^63 (decision 0001) */
    }
    if (out_policy_seed != NULL) {
        *out_policy_seed = dfi_splitmix(key ^ DFI_BATCH_TAG_POLICY);
    }
}

/* The next value of a policy stream (splitmix64 with state *s). */
static uint64_t dfi_policy_next(uint64_t *s)
{
    const uint64_t v = dfi_splitmix(*s);
    *s += 0x9E3779B97F4A7C15u;
    return v;
}

/* ------------------------------------------------------------ environments */

/* A fresh battle of environment `e` in `episode`. */
static duoforge_status dfi_batch_make(const struct duoforge_batch *b, uint32_t e, uint32_t episode,
                                      duoforge_battle **out)
{
    duoforge_battle_setup setup = b->setups[e];
    duoforge_batch_seeds(b->seed, e, episode, &setup.rng_initstate, &setup.rng_initseq, NULL);
    return duoforge_battle_create(b->ctx, &setup, out);
}

/* Resets environment `e` to `episode`; it keeps its battle on failure. */
static duoforge_status dfi_batch_reset(struct duoforge_batch *b, uint32_t e, uint32_t episode)
{
    duoforge_battle *fresh = NULL;
    const duoforge_status st = dfi_batch_make(b, e, episode, &fresh);
    if (st != DUOFORGE_OK) {
        return st;
    }
    duoforge_battle_destroy(b->env[e].battle);
    b->env[e].battle = fresh;
    b->env[e].episode = episode;
    b->env[e].terminal = false;
    return DUOFORGE_OK;
}

/* The lowest failing environment's status, or OK. */
static duoforge_status dfi_batch_first(const duoforge_status *statuses, uint32_t n)
{
    for (uint32_t i = 0u; i < n; ++i) {
        if (statuses[i] != DUOFORGE_OK) {
            return statuses[i];
        }
    }
    return DUOFORGE_OK;
}

duoforge_status duoforge_batch_create(const duoforge_context *ctx, const duoforge_batch_config *config,
                                      duoforge_batch **out_batch)
{
    if (ctx == NULL || config == NULL || out_batch == NULL || config->setups == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    const duoforge_batch_config c = *config;
    if (c.env_count < 1u || c.env_count > DUOFORGE_BATCH_MAX_ENVS || c.worker_count < 1u ||
        c.worker_count > DUOFORGE_BATCH_MAX_WORKERS) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    struct duoforge_batch *b = dfi_alloc_zeroed(sizeof *b);
    if (b == NULL) {
        return DUOFORGE_E_OUT_OF_MEMORY;
    }
    b->ctx = ctx;
    b->seed = c.seed;
    b->env_count = c.env_count;
    b->env = dfi_alloc_zeroed(sizeof *b->env * c.env_count);
    b->setups = dfi_alloc_zeroed(sizeof *b->setups * c.env_count);
    b->scratch = dfi_alloc_zeroed(sizeof *b->scratch * c.worker_count);
    b->pool = dfi_pool_create(c.worker_count);
    if (b->env == NULL || b->setups == NULL || b->scratch == NULL || b->pool == NULL) {
        duoforge_batch_destroy(b);
        return DUOFORGE_E_OUT_OF_MEMORY;
    }
    memcpy(b->setups, c.setups, sizeof *b->setups * c.env_count);
    for (uint32_t e = 0u; e < c.env_count; ++e) {
        const duoforge_status st = dfi_batch_make(b, e, 0u, &b->env[e].battle);
        if (st != DUOFORGE_OK) {
            duoforge_batch_destroy(b);
            return st;
        }
    }
    *out_batch = b;
    return DUOFORGE_OK;
}

void duoforge_batch_destroy(duoforge_batch *batch)
{
    if (batch == NULL) {
        return;
    }
    dfi_pool_destroy(batch->pool);
    if (batch->env != NULL) {
        for (uint32_t e = 0u; e < batch->env_count; ++e) {
            duoforge_battle_destroy(batch->env[e].battle);
        }
    }
    dfi_free(batch->env);
    dfi_free(batch->setups);
    dfi_free(batch->scratch);
    dfi_free(batch);
}

uint32_t duoforge_batch_env_count(const duoforge_batch *batch)
{
    return batch != NULL ? batch->env_count : 0u;
}

const duoforge_battle *duoforge_batch_env(const duoforge_batch *batch, uint32_t env)
{
    return batch != NULL && env < batch->env_count ? batch->env[env].battle : NULL;
}

uint32_t duoforge_batch_env_episode(const duoforge_batch *batch, uint32_t env)
{
    return batch != NULL && env < batch->env_count ? batch->env[env].episode : 0u;
}

/* ------------------------------------------------------------------ query */

typedef struct dfi_query_job {
    struct duoforge_batch *b;
    duoforge_request *requests;
    duoforge_observation *observations;
    duoforge_side_choice *candidates;
    uint32_t *counts;
    duoforge_factored_domain *domains;
    duoforge_status *statuses;
} dfi_query_job;

static void dfi_query_slice(void *job, uint32_t worker, uint32_t begin, uint32_t end)
{
    (void)worker;
    const dfi_query_job *j = job;
    const duoforge_context *ctx = j->b->ctx;
    for (uint32_t e = begin; e < end; ++e) {
        const duoforge_battle *battle = j->b->env[e].battle;
        duoforge_status st = DUOFORGE_OK;
        for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT && st == DUOFORGE_OK; ++p) {
            const size_t at = (size_t)e * DUOFORGE_SIDE_COUNT + p;
            if (j->requests != NULL) {
                st = duoforge_battle_request(ctx, battle, p, &j->requests[at]);
            }
            if (st == DUOFORGE_OK && j->observations != NULL) {
                st = duoforge_battle_observe(ctx, battle, p, &j->observations[at]);
            }
            if (st == DUOFORGE_OK && j->counts != NULL) {
                duoforge_side_choice *out =
                    j->candidates != NULL ? &j->candidates[at * DUOFORGE_MAX_CANDIDATES] : NULL;
                uint32_t n = 0u;
                if (out != NULL) {
                    st = duoforge_battle_candidates(ctx, battle, p, out, DUOFORGE_MAX_CANDIDATES, &n);
                } else {
                    duoforge_request rq;
                    st = duoforge_battle_request(ctx, battle, p, &rq);
                    n = rq.candidate_count;
                }
                j->counts[at] = n;
            }
            if (st == DUOFORGE_OK && j->domains != NULL) {
                st = duoforge_battle_factored(ctx, battle, p, &j->domains[at]);
            }
        }
        j->statuses[e] = st;
    }
}

/* Runs a query job over every environment: the lowest failing status. */
static duoforge_status dfi_batch_query_run(duoforge_batch *batch, dfi_query_job *job)
{
    duoforge_status *statuses = dfi_alloc_zeroed(sizeof *statuses * batch->env_count);
    if (statuses == NULL) {
        return DUOFORGE_E_OUT_OF_MEMORY;
    }
    job->statuses = statuses;
    dfi_pool_run(batch->pool, dfi_query_slice, job, batch->env_count);
    const duoforge_status st = dfi_batch_first(statuses, batch->env_count);
    dfi_free(statuses);
    return st;
}

duoforge_status duoforge_batch_query(duoforge_batch *batch, duoforge_request *requests,
                                     duoforge_observation *observations, duoforge_side_choice *candidates,
                                     uint32_t *candidate_counts)
{
    if (batch == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (candidates != NULL && candidate_counts == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT; /* the candidates need their counts */
    }
    dfi_query_job job = {batch, requests, observations, candidates, candidate_counts, NULL, NULL};
    return dfi_batch_query_run(batch, &job);
}

duoforge_status duoforge_batch_query_factored(duoforge_batch *batch, duoforge_request *requests,
                                              duoforge_observation *observations,
                                              duoforge_factored_domain *domains)
{
    if (batch == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    dfi_query_job job = {batch, requests, observations, NULL, NULL, domains, NULL};
    return dfi_batch_query_run(batch, &job);
}

/* ------------------------------------------------------------------- step */

typedef struct dfi_step_job {
    struct duoforge_batch *b;
    const duoforge_decision_bundle *bundles;
    duoforge_status *statuses;
    duoforge_step_result *results;
} dfi_step_job;

/* Steps environment `e` with `bundle`; a TERMINAL environment gets OK and an
   all-zero result. */
static duoforge_status dfi_step_env(struct duoforge_batch *b, uint32_t e, const duoforge_decision_bundle *bundle,
                                    duoforge_step_result *result)
{
    dfi_batch_env *env = &b->env[e];
    memset(result, 0, sizeof *result);
    if (env->terminal) {
        return DUOFORGE_OK;
    }
    const duoforge_status st = duoforge_battle_step(b->ctx, env->battle, bundle, result);
    if (st == DUOFORGE_OK && result->boundary_kind == DUOFORGE_BOUNDARY_TERMINAL) {
        env->terminal = true;
    }
    return st;
}

static void dfi_step_slice(void *job, uint32_t worker, uint32_t begin, uint32_t end)
{
    (void)worker;
    const dfi_step_job *j = job;
    for (uint32_t e = begin; e < end; ++e) {
        j->statuses[e] = dfi_step_env(j->b, e, &j->bundles[e], &j->results[e]);
    }
}

duoforge_status duoforge_batch_step(duoforge_batch *batch, const duoforge_decision_bundle *bundles,
                                    duoforge_status *statuses, duoforge_step_result *results)
{
    if (batch == NULL || bundles == NULL || statuses == NULL || results == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    dfi_step_job job = {batch, bundles, statuses, results};
    dfi_pool_run(batch->pool, dfi_step_slice, &job, batch->env_count);
    return dfi_batch_first(statuses, batch->env_count);
}

/* ------------------------------------------- step by index or by factor */

/* The query's arrays and one choice per requested player: a candidate index
   (indices) or a factored choice (domains != NULL). */
typedef struct dfi_choice_job {
    struct duoforge_batch *b;
    const duoforge_request *requests;
    const duoforge_side_choice *candidates;
    const uint32_t *counts;
    const uint16_t *indices;
    const duoforge_factored_domain *domains;
    const duoforge_factored_choice *choices;
    duoforge_status *statuses;
    duoforge_step_result *results;
} dfi_choice_job;

/* The response at `at` (2 * env + p) by candidate index; E_INVALID_ARGUMENT
   for an index past its list (NO_CHOICE is past every list). */
static duoforge_status dfi_index_response(const dfi_choice_job *j, size_t at, duoforge_side_choice *out)
{
    const uint32_t index = j->indices[at];
    if (index >= j->counts[at] || index >= DUOFORGE_MAX_CANDIDATES) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    *out = j->candidates[at * DUOFORGE_MAX_CANDIDATES + index];
    return DUOFORGE_OK;
}

/* The response at `at` of player `p` by factored choice, built as the
   enumeration builds a candidate; E_INVALID_ARGUMENT for a SLOTS pair past
   the lists or not allowed, or a domain without a request. The step checks
   a TEAM_SELECTION tuple. */
static duoforge_status dfi_factored_response(const dfi_choice_job *j, size_t at, uint32_t p,
                                             duoforge_side_choice *out)
{
    const duoforge_factored_domain *d = &j->domains[at];
    const duoforge_factored_choice *c = &j->choices[at];
    memset(out, 0, sizeof *out);
    out->epoch = d->epoch;
    out->side = (uint8_t)p;
    out->kind = d->kind;
    if (d->kind == DUOFORGE_CHOICE_TEAM_SELECTION) {
        out->pick_count = d->pick_count;
        memcpy(out->picks, c->picks, sizeof out->picks);
        return DUOFORGE_OK;
    }
    const uint32_t i = c->slot[0];
    const uint32_t k = c->slot[1];
    if (d->kind != DUOFORGE_CHOICE_SLOTS || i >= d->slot_count[0] || k >= d->slot_count[1] ||
        i >= DUOFORGE_MAX_SLOT_OPTIONS || k >= DUOFORGE_MAX_SLOT_OPTIONS || ((d->allowed[i] >> k) & 1u) == 0u) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    out->slots[0] = d->slots[0][i];
    out->slots[1] = d->slots[1][k];
    return DUOFORGE_OK;
}

/* Fills the zeroed bundle of environment `e`; E_INVALID_ARGUMENT for a
   requested player whose choice is not in the query's domain. */
static duoforge_status dfi_choice_bundle(const dfi_choice_job *j, uint32_t e, duoforge_decision_bundle *bundle)
{
    bundle->epoch = j->requests[2u * e].epoch;
    for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT; ++p) {
        const size_t at = (size_t)2u * e + p;
        if (j->requests[at].requested == 0u) {
            continue;
        }
        const duoforge_status st = j->domains != NULL ? dfi_factored_response(j, at, p, &bundle->responses[p])
                                                      : dfi_index_response(j, at, &bundle->responses[p]);
        if (st != DUOFORGE_OK) {
            return st;
        }
        bundle->response_mask = (uint8_t)(bundle->response_mask | (1u << p)); /* wide-operands-reviewed: < 4 */
    }
    return DUOFORGE_OK;
}

static void dfi_choice_slice(void *job, uint32_t worker, uint32_t begin, uint32_t end)
{
    (void)worker;
    const dfi_choice_job *j = job;
    for (uint32_t e = begin; e < end; ++e) {
        duoforge_decision_bundle bundle;
        memset(&bundle, 0, sizeof bundle);
        j->statuses[e] = j->b->env[e].terminal ? DUOFORGE_OK : dfi_choice_bundle(j, e, &bundle);
        if (j->statuses[e] == DUOFORGE_OK) {
            j->statuses[e] = dfi_step_env(j->b, e, &bundle, &j->results[e]);
        } else {
            memset(&j->results[e], 0, sizeof j->results[e]);
        }
    }
}

duoforge_status duoforge_batch_step_indices(duoforge_batch *batch, const duoforge_request *requests,
                                            const duoforge_side_choice *candidates, const uint32_t *counts,
                                            const uint16_t *indices, duoforge_status *statuses,
                                            duoforge_step_result *results)
{
    if (batch == NULL || requests == NULL || candidates == NULL || counts == NULL || indices == NULL ||
        statuses == NULL || results == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    dfi_choice_job job = {batch, requests, candidates, counts, indices, NULL, NULL, statuses, results};
    dfi_pool_run(batch->pool, dfi_choice_slice, &job, batch->env_count);
    return dfi_batch_first(statuses, batch->env_count);
}

duoforge_status duoforge_batch_step_factored(duoforge_batch *batch, const duoforge_request *requests,
                                             const duoforge_factored_domain *domains,
                                             const duoforge_factored_choice *choices, duoforge_status *statuses,
                                             duoforge_step_result *results)
{
    if (batch == NULL || requests == NULL || domains == NULL || choices == NULL || statuses == NULL ||
        results == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    dfi_choice_job job = {batch, requests, NULL, NULL, NULL, domains, choices, statuses, results};
    dfi_pool_run(batch->pool, dfi_choice_slice, &job, batch->env_count);
    return dfi_batch_first(statuses, batch->env_count);
}

/* ------------------------------------------------------------------ reset */

typedef struct dfi_reset_job {
    struct duoforge_batch *b;
    duoforge_status *statuses;
} dfi_reset_job;

static void dfi_reset_slice(void *job, uint32_t worker, uint32_t begin, uint32_t end)
{
    (void)worker;
    const dfi_reset_job *j = job;
    for (uint32_t e = begin; e < end; ++e) {
        const dfi_batch_env *env = &j->b->env[e];
        j->statuses[e] = env->terminal ? dfi_batch_reset(j->b, e, env->episode + 1u) : DUOFORGE_OK;
    }
}

duoforge_status duoforge_batch_reset_terminal(duoforge_batch *batch)
{
    if (batch == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    duoforge_status *statuses = dfi_alloc_zeroed(sizeof *statuses * batch->env_count);
    if (statuses == NULL) {
        return DUOFORGE_E_OUT_OF_MEMORY;
    }
    dfi_reset_job job = {batch, statuses};
    dfi_pool_run(batch->pool, dfi_reset_slice, &job, batch->env_count);
    const duoforge_status st = dfi_batch_first(statuses, batch->env_count);
    dfi_free(statuses);
    return st;
}

duoforge_status duoforge_batch_reset(duoforge_batch *batch, uint32_t env, uint32_t episode)
{
    if (batch == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (env >= batch->env_count) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    return dfi_batch_reset(batch, env, episode);
}

/* ------------------------------------------------------------ native mode */

typedef struct dfi_play_job {
    struct duoforge_batch *b;
    uint32_t episodes;
    uint32_t max_steps;
    duoforge_batch_episode *records;
    duoforge_status *statuses;
} dfi_play_job;

/* Plays environment `e` from a fresh reset to TERMINAL with the uniform
 * random policy; fills `rec`. */
static duoforge_status dfi_play_episode(struct duoforge_batch *b, dfi_batch_scratch *s, uint32_t e,
                                        uint32_t episode, uint32_t max_steps, duoforge_batch_episode *rec)
{
    duoforge_status st = dfi_batch_reset(b, e, episode);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const duoforge_context *ctx = b->ctx;
    duoforge_battle *battle = b->env[e].battle;
    uint64_t policy = 0u;
    duoforge_batch_seeds(b->seed, e, episode, NULL, NULL, &policy);
    memset(rec, 0, sizeof *rec);
    rec->env = e;
    rec->episode = episode;
    for (;;) {
        duoforge_request rq;
        duoforge_decision_bundle bd;
        memset(&bd, 0, sizeof bd);
        for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT; ++p) {
            st = duoforge_battle_request(ctx, battle, p, &rq);
            if (st != DUOFORGE_OK) {
                return st;
            }
            bd.epoch = rq.epoch;
            if (rq.requested == 0u) {
                continue;
            }
            uint32_t n = 0u;
            st = duoforge_battle_candidates(ctx, battle, p, s->cands, DUOFORGE_MAX_CANDIDATES, &n);
            if (st != DUOFORGE_OK) {
                return st;
            }
            if (n == 0u) {
                return DUOFORGE_E_INVARIANT; /* a requested player always has a candidate */
            }
            bd.response_mask = (uint8_t)(bd.response_mask | (1u << p)); /* wide-operands-reviewed: < 4 */
            bd.responses[p] = s->cands[dfi_policy_next(&policy) % n];
            rec->decisions += 1u;
        }
        if (bd.response_mask == 0u) {
            break; /* TERMINAL */
        }
        if (rec->steps >= max_steps) {
            return DUOFORGE_E_INVARIANT; /* past the caller's bound */
        }
        duoforge_step_result res;
        duoforge_event_buffer buffers[DUOFORGE_SIDE_COUNT] = {{s->events[0], DUOFORGE_MAX_EVENTS, 0u},
                                                               {s->events[1], DUOFORGE_MAX_EVENTS, 0u}};
        st = duoforge_battle_step_events(ctx, battle, &bd, &res, buffers);
        if (st != DUOFORGE_OK) {
            return st;
        }
        for (uint32_t i = 0u; i < buffers[0].count; ++i) {
            if (s->events[0][i].kind == DUOFORGE_EVENT_RESULT) {
                rec->result = s->events[0][i].detail;
            }
        }
        rec->steps += 1u;
    }
    duoforge_observation ob;
    st = duoforge_battle_observe(ctx, battle, 0u, &ob);
    if (st == DUOFORGE_OK) {
        rec->turns = ob.turn;
        st = duoforge_battle_digest(ctx, battle, rec->digest);
    }
    b->env[e].terminal = st == DUOFORGE_OK;
    return st;
}

static void dfi_play_slice(void *job, uint32_t worker, uint32_t begin, uint32_t end)
{
    const dfi_play_job *j = job;
    dfi_batch_scratch *s = &j->b->scratch[worker];
    for (uint32_t e = begin; e < end; ++e) {
        duoforge_status st = DUOFORGE_OK;
        const uint32_t first = j->b->env[e].episode + 1u;
        for (uint32_t k = 0u; k < j->episodes && st == DUOFORGE_OK; ++k) {
            duoforge_batch_episode rec;
            st = dfi_play_episode(j->b, s, e, first + k, j->max_steps, &rec);
            if (st == DUOFORGE_OK && j->records != NULL) {
                j->records[(size_t)e * j->episodes + k] = rec;
            }
        }
        j->statuses[e] = st;
    }
}

duoforge_status duoforge_batch_play_random(duoforge_batch *batch, uint32_t episodes, uint32_t max_steps,
                                           duoforge_batch_episode *records)
{
    if (batch == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    duoforge_status *statuses = dfi_alloc_zeroed(sizeof *statuses * batch->env_count);
    if (statuses == NULL) {
        return DUOFORGE_E_OUT_OF_MEMORY;
    }
    dfi_play_job job = {batch, episodes, max_steps, records, statuses};
    dfi_pool_run(batch->pool, dfi_play_slice, &job, batch->env_count);
    const duoforge_status st = dfi_batch_first(statuses, batch->env_count);
    dfi_free(statuses);
    return st;
}
