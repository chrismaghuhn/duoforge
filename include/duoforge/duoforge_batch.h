#ifndef DUOFORGE_BATCH_H
#define DUOFORGE_BATCH_H

/*
 * Batch runtime (decision 0012, roadmap M6): many independent battles
 * ("environments") of one context, run together by a fixed pool of worker
 * threads. A thin layer over the single-battle API: every environment is an
 * ordinary duoforge_battle and every call on it is a single-battle call, so a
 * batch plays exactly what the same calls one by one would play, for any
 * worker count. Environments are split into fixed contiguous slices, one per
 * worker; the caller's thread runs the first slice.
 *
 * Seeds: an environment's battle and policy seeds are a pure function of the
 * batch seed, the environment index and its episode number
 * (duoforge_batch_seeds), never of a worker.
 *
 * Outcomes are atomic per environment: a failing environment keeps its
 * state, the others go on; a batch call returns the status of the lowest
 * failing environment, or OK.
 *
 * A batch is not thread-safe itself: one caller at a time.
 */
#include <duoforge/duoforge.h>

#define DUOFORGE_BATCH_MAX_ENVS    65536u
#define DUOFORGE_BATCH_MAX_WORKERS 256u
/* The candidate index of a player without a request (duoforge_batch_step_indices). */
#define DUOFORGE_BATCH_NO_CHOICE   0xFFFFu
/* duoforge_batch_step_query flag: an environment whose episode ends starts
   its next one in the same pass. */
#define DUOFORGE_BATCH_AUTORESET   1u

typedef struct duoforge_batch duoforge_batch;

typedef struct duoforge_batch_config {
    uint32_t env_count;                  /* 1..DUOFORGE_BATCH_MAX_ENVS */
    uint32_t worker_count;               /* threads including the caller's, 1..DUOFORGE_BATCH_MAX_WORKERS */
    uint64_t seed;                       /* the batch seed of the derivation */
    const duoforge_battle_setup *setups; /* env_count setups; rng_initstate and rng_initseq are replaced per episode */
} duoforge_batch_config;

/* One finished episode of the native mode. */
typedef struct duoforge_batch_episode {
    uint32_t env;
    uint32_t episode;
    uint32_t steps;     /* steps to TERMINAL */
    uint32_t decisions; /* side choices made */
    uint32_t turns;     /* the final turn */
    uint32_t result;    /* DUOFORGE_RESULT_* */
    uint8_t digest[DUOFORGE_DIGEST_SIZE]; /* of the final state */
} duoforge_batch_episode;

/* The seeds of environment `env` in episode `episode`: rng_initstate, an
 * rng_initseq below 2^63 (decision 0001) and the native policy's seed.
 * splitmix64 over the batch seed with the tags documented in decision 0012. */
void duoforge_batch_seeds(uint64_t seed, uint32_t env, uint32_t episode, uint64_t *out_initstate,
                          uint64_t *out_initseq, uint64_t *out_policy_seed);

/* Creates every environment at episode 0. Checks: NULL -> INVALID_ARGUMENT
   (counts) -> the setups' own checks (the first failing environment's status).
   *out_batch is written only on success. */
duoforge_status duoforge_batch_create(const duoforge_context *ctx, const duoforge_batch_config *config,
                                      duoforge_batch **out_batch);
void duoforge_batch_destroy(duoforge_batch *batch); /* NULL is a no-op */

uint32_t duoforge_batch_env_count(const duoforge_batch *batch);
/* The environment's battle for single-battle queries, owned by the batch and
   valid until the environment is reset; NULL when env is out of range. */
const duoforge_battle *duoforge_batch_env(const duoforge_batch *batch, uint32_t env);
uint32_t duoforge_batch_env_episode(const duoforge_batch *batch, uint32_t env);

/* Step mode, in parallel. For every environment and player p the request,
   the observation and the candidates into requests[2 * env + p],
   observations[2 * env + p], candidates[(2 * env + p) * DUOFORGE_MAX_CANDIDATES]
   and candidate_counts[2 * env + p]; any output may be NULL (skipped). */
duoforge_status duoforge_batch_query(duoforge_batch *batch, duoforge_request *requests,
                                     duoforge_observation *observations, duoforge_side_choice *candidates,
                                     uint32_t *candidate_counts);

/* Step mode, in parallel: duoforge_battle_step(bundles[env]) for every
   environment that is not TERMINAL; statuses[env] and results[env] receive
   its outcome (a TERMINAL environment gets OK and an all-zero result). */
duoforge_status duoforge_batch_step(duoforge_batch *batch, const duoforge_decision_bundle *bundles,
                                    duoforge_status *statuses, duoforge_step_result *results);

/* Step mode with the factored domain, in parallel: as duoforge_batch_query,
   with domains[2 * env + p] from duoforge_battle_factored in place of the
   candidate lists; any output may be NULL (skipped). */
duoforge_status duoforge_batch_query_factored(duoforge_batch *batch, duoforge_request *requests,
                                              duoforge_observation *observations,
                                              duoforge_factored_domain *domains);

/* Step mode by candidate index, in parallel: for every environment that is
   not TERMINAL, the bundle of the last query's arrays is stepped as in
   duoforge_batch_step. Its epoch is requests[2 * env].epoch; for each player
   p with requests[2 * env + p].requested the response is
   candidates[(2 * env + p) * DUOFORGE_MAX_CANDIDATES + indices[2 * env + p]].
   An index at or past counts[2 * env + p], DUOFORGE_BATCH_NO_CHOICE included,
   fails that environment with E_INVALID_ARGUMENT and leaves it unchanged. */
duoforge_status duoforge_batch_step_indices(duoforge_batch *batch, const duoforge_request *requests,
                                            const duoforge_side_choice *candidates, const uint32_t *counts,
                                            const uint16_t *indices, duoforge_status *statuses,
                                            duoforge_step_result *results);

/* Step mode by factored choice, in parallel: as duoforge_batch_step_indices,
   with the response of each requested player p built from
   domains[2 * env + p] and choices[2 * env + p]. A SLOTS choice whose pair
   bit is not set, or whose index is past its slot list, fails that
   environment with E_INVALID_ARGUMENT; the step checks a TEAM_SELECTION
   choice. */
duoforge_status duoforge_batch_step_factored(duoforge_batch *batch, const duoforge_request *requests,
                                             const duoforge_factored_domain *domains,
                                             const duoforge_factored_choice *choices, duoforge_status *statuses,
                                             duoforge_step_result *results);

/* The RL loop's batch step in one pass over the environments (decision
   0013): each environment is stepped as by duoforge_batch_step_indices
   (requests, candidates and candidate_counts hold the last query), then,
   with DUOFORGE_BATCH_AUTORESET in flags, reset to its next episode if it is
   TERMINAL, and then queried as by duoforge_batch_query into the same
   arrays. episode_results[env] receives the result (DUOFORGE_RESULT_*, never
   0) of an episode that is TERMINAL after the step, 0 otherwise; with the
   flag a nonzero entry therefore marks exactly the environments this call
   reset, including those already TERMINAL on entry (their results entry is
   all-zero). observations and episode_results may be NULL; another flag bit
   is E_INVALID_ARGUMENT. A failing step leaves its environment unchanged and
   its outputs describe that boundary. If the step succeeds and the reset or
   the query fails, the step stays applied, statuses[env] reports the
   failure and episode_results[env] is 0: the result is reported by the call
   that resets the environment. Equivalent to step_indices, the results,
   reset_terminal (with the flag) and query, in one pass instead of three. */
duoforge_status duoforge_batch_step_query(duoforge_batch *batch, uint32_t flags, const uint16_t *indices,
                                          duoforge_request *requests, duoforge_observation *observations,
                                          duoforge_side_choice *candidates, uint32_t *candidate_counts,
                                          uint32_t *episode_results, duoforge_status *statuses,
                                          duoforge_step_result *results);

/* The view extension of every environment's players, in parallel (decision
   0018): out[2 * env + p] = duoforge_battle_observe_ext of player p. A failing
   environment leaves its entries unspecified; the call returns the status of
   the lowest failing environment. */
duoforge_status duoforge_batch_observe_ext(duoforge_batch *batch, duoforge_observation_ext *out);

/* Resets every TERMINAL environment to its next episode, in parallel. */
duoforge_status duoforge_batch_reset_terminal(duoforge_batch *batch);

/* Resets environment env to `episode`: a fresh battle from the seed
   derivation. Out of range is E_INVALID_ARGUMENT; a failed reset keeps the
   environment as it was. */
duoforge_status duoforge_batch_reset(duoforge_batch *batch, uint32_t env, uint32_t episode);

/* Resets environment envs[i] to episode episodes[i] with setup setups[i],
   i < count (decision 0017): each setup passes the checks of
   duoforge_battle_create (its rng fields are replaced by the seed
   derivation, as at create and reset), becomes the environment's setup, and
   a fresh battle starts. Outcomes are atomic per environment: a failing one
   keeps its setup and battle and its status goes to statuses[i] when
   statuses is given; the call returns the status of the lowest failing i, or
   OK. Checks before any change: NULL batch, or NULL envs, episodes or setups
   with count > 0, is E_NULL_ARGUMENT; an environment out of range or listed
   twice is E_INVALID_ARGUMENT and nothing changes. count 0 is a no-op. It
   runs on the batch's workers and allocates as duoforge_batch_reset does:
   one fresh battle per environment. */
duoforge_status duoforge_batch_reset_setups(duoforge_batch *batch, uint32_t count, const uint32_t *envs,
                                            const uint32_t *episodes, const duoforge_battle_setup *setups,
                                            duoforge_status *statuses);

/* Native mode, in parallel: every environment plays `episodes` further
   episodes from fresh resets with the uniform random policy (each requested
   player, in player order, takes candidate next() % count of a splitmix64
   stream from its policy seed), at most max_steps steps each (more is
   E_INVARIANT). Writes episodes[env * episodes + k] when the array is given. */
duoforge_status duoforge_batch_play_random(duoforge_batch *batch, uint32_t episodes, uint32_t max_steps,
                                           duoforge_batch_episode *records);

#endif
