/*
 * Search support (decision 0022): the search seeds and the leaf expansion of
 * a one-turn lookahead. Each leaf is the single-battle calls copy, reseed,
 * step and the encoder's row, run on the leaf batch's workers through the
 * batch runtime's leaf hook (batch/batch_each.h). The rows are the
 * encoder's: this file only hands it a row index (encode/encode_internal.h).
 */
#include <duoforge/duoforge_search.h>

#include <stdbool.h>
#include <string.h>

#include "batch/batch_each.h"
#include "encode/encode_internal.h"
#include "state/observation_digest.h"
#include "state/request.h"
#include "search/error_lock.h"

#define DFI_SEARCH_TAG 0x5345415243480001u /* "SEARCH", 1 */

void duoforge_search_seeds(uint64_t seed, uint64_t key, uint32_t sample, uint64_t *out_initstate,
                           uint64_t *out_initseq)
{
    const uint64_t h = dfi_splitmix(dfi_splitmix(seed + DFI_SEARCH_TAG) + key);
    const uint64_t s = dfi_splitmix(h + sample);
    if (out_initstate != NULL) {
        *out_initstate = dfi_splitmix(s + 1u);
    }
    if (out_initseq != NULL) {
        *out_initseq = dfi_splitmix(s + 2u) >> 1; /* < 2^63 (decision 0001) */
    }
}

typedef struct dfi_expand_job {
    const duoforge_batch *roots;
    uint32_t version;
    uint64_t mask;
    uint64_t seed;
    uint32_t obs_size;
    const duoforge_request *root_requests;
    const duoforge_factored_domain *root_domains;
    const uint64_t *keys;
    const uint8_t *viewers;
    const uint32_t *root_envs;
    const uint32_t *samples;
    const duoforge_factored_choice *choices;
    duoforge_status *step_statuses;
    duoforge_status *encode_statuses;
    duoforge_step_result *results;
    uint32_t *leaf_results;
    uint8_t *digests;
    duoforge_status *digest_statuses;
    duoforge_eval_error *error;
    dfi_error_lock error_lock;
    uint32_t error_phase;
    void *obs; /* count rows of obs_size float32 values, written by the encoder (encode/encode_internal.h) */
} dfi_expand_job;

/* Diagnostics are a bounded copy, never a formatter or private filename. */
static void dfi_expand_error(duoforge_eval_error *error, uint32_t leaf,
                              const char *phase, const char *reason)
{
    if (error == NULL) { return; }
    memset(error, 0, sizeof *error);
    error->leaf = leaf;
    for (uint32_t k = 0u; phase[k] != '\0' && k + 1u < sizeof error->phase; ++k) {
        error->phase[k] = phase[k];
    }
    for (uint32_t k = 0u; reason[k] != '\0' && k + 1u < sizeof error->reason; ++k) {
        error->reason[k] = reason[k];
    }
}

/* Only failing leaves with requested diagnostics contend. The lock protects
 * a fixed stack record, not the battle hot path or a growable error log.
 * Phase priority then logical leaf index makes the winner schedule-independent. */
static void dfi_expand_report(dfi_expand_job *j, uint32_t i, uint32_t phase_rank,
                               const char *phase, const char *reason)
{
    if (j->error == NULL) { return; }
    dfi_error_lock_enter(&j->error_lock);
    if (phase_rank < j->error_phase || (phase_rank == j->error_phase && i < j->error->leaf)) {
        j->error_phase = phase_rank;
        dfi_expand_error(j->error, i, phase, reason);
    }
    dfi_error_lock_leave(&j->error_lock);
}

/* Legacy expansion never calls this function or allocates its SHA scratch. */
static duoforge_status dfi_expand_observed(dfi_expand_job *j, uint32_t i,
    const duoforge_context *ctx, duoforge_battle *leaf,
    const duoforge_decision_bundle *bundle, duoforge_step_result *result)
{
    if (leaf->boundary_kind == DUOFORGE_BOUNDARY_TURN &&
        (leaf->sides[0].sealed != 0u || leaf->sides[1].sealed != 0u)) {
        /* A missing observation key never removes an otherwise valid edge.
         * Retained commands are not observed yet; execute the ordinary step
         * and refuse only its digest, leaving step/result/encoding intact. */
        const duoforge_status st = duoforge_battle_step(ctx, leaf, bundle, result);
        if (st == DUOFORGE_OK) {
            j->digest_statuses[i] = DUOFORGE_E_UNSUPPORTED;
            dfi_expand_report(j, i, 2u, "digest", "observation_reprompt_unsupported");
        }
        return st;
    }
    dfi_observation_digest observation;
    observation.viewer = j->viewers[j->root_envs[i]];
    const duoforge_status st = dfi_battle_step_observed(ctx, leaf, bundle, NULL, 0u, NULL, result, NULL, &observation);
    if (st == DUOFORGE_OK) {
        j->digest_statuses[i] = observation.status;
        if (observation.status == DUOFORGE_OK && !observation.complete) {
            j->digest_statuses[i] = DUOFORGE_E_INVARIANT;
            dfi_expand_report(j, i, 2u, "digest", "observation_incomplete");
        } else if (observation.status != DUOFORGE_OK) {
            dfi_expand_report(j, i, 2u, "digest", observation.reason);
        } else {
            memcpy(j->digests + (size_t)i * DUOFORGE_DIGEST_SIZE, observation.digest, DUOFORGE_DIGEST_SIZE);
        }
    }
    return st;
}

/* Leaf i (dfi_batch_leaves): copy, reseed, step, then the result or the row. */
static void dfi_expand_leaf(void *arg, uint32_t i, const duoforge_context *ctx, duoforge_battle *leaf,
                            bool *terminal)
{
    dfi_expand_job *j = arg;
    const uint32_t r = j->root_envs[i];
    duoforge_step_result *result = &j->results[i];
    memset(result, 0, sizeof *result);
    j->leaf_results[i] = 0u;
    j->encode_statuses[i] = DUOFORGE_OK;
    if (j->digests != NULL) {
        memset(j->digests + (size_t)i * DUOFORGE_DIGEST_SIZE, 0, DUOFORGE_DIGEST_SIZE);
        j->digest_statuses[i] = DUOFORGE_OK;
    }

    uint64_t initstate = 0u;
    uint64_t initseq = 0u;
    duoforge_search_seeds(j->seed, j->keys[r], j->samples[i], &initstate, &initseq);
    duoforge_decision_bundle bundle;
    duoforge_status st = duoforge_battle_copy(ctx, leaf, duoforge_batch_env(j->roots, r));
    const bool copied = st == DUOFORGE_OK;
    if (st == DUOFORGE_OK) {
        st = duoforge_battle_reseed(ctx, leaf, initstate, initseq);
    }
    if (st == DUOFORGE_OK) {
        st = dfi_factored_bundle(&j->root_requests[2u * r], &j->root_domains[2u * r], &j->choices[2u * i], &bundle);
    }
    if (st == DUOFORGE_OK) {
        st = j->digests != NULL ? dfi_expand_observed(j, i, ctx, leaf, &bundle, result)
                               : duoforge_battle_step(ctx, leaf, &bundle, result);
    }

    /* The TERMINAL flag follows the battle: after a failed step the leaf is
       still the root's copy, so its flag is the root's. */
    const bool ended = st == DUOFORGE_OK && result->boundary_kind == DUOFORGE_BOUNDARY_TERMINAL;
    uint32_t outcome = 0u;
    if (copied && (st != DUOFORGE_OK || ended)) {
        const duoforge_status read = duoforge_battle_result(ctx, leaf, &outcome);
        if (read == DUOFORGE_OK) {
            *terminal = outcome != 0u;
        } else if (st == DUOFORGE_OK) {
            st = read; /* the step's outcome cannot be read: an engine failure of this leaf */
        }
    } else if (copied) {
        *terminal = false;
    }
    j->step_statuses[i] = st;
    if (st != DUOFORGE_OK || ended) {
        if (st == DUOFORGE_OK) {
            j->leaf_results[i] = outcome;
        }
        if (st != DUOFORGE_OK) {
            dfi_expand_report(j, i, 1u, "step", "expand_step_refused");
            if (j->digests != NULL) {
                memset(j->digests + (size_t)i * DUOFORGE_DIGEST_SIZE, 0, DUOFORGE_DIGEST_SIZE);
            }
        }
        if (j->obs != NULL) { dfi_encode_clear(j->obs, j->obs_size, i); }
        return;
    }
    if (j->obs != NULL) {
        j->encode_statuses[i] = dfi_encode_leaf(ctx, leaf, j->viewers[r], j->version, j->mask, j->obs_size, j->obs, i);
        if (j->encode_statuses[i] != DUOFORGE_OK) { dfi_expand_report(j, i, 3u, "encode", "expand_encode_refused"); }
    }
}

/* True iff the two contexts have the same fingerprint, so their battles copy into each other. */
static bool dfi_search_same_context(const duoforge_context *a, const duoforge_context *b)
{
    if (a == b) {
        return true;
    }
    uint8_t fa[DUOFORGE_DIGEST_SIZE];
    uint8_t fb[DUOFORGE_DIGEST_SIZE];
    if (duoforge_context_fingerprint(a, fa) != DUOFORGE_OK || duoforge_context_fingerprint(b, fb) != DUOFORGE_OK) {
        return false;
    }
    for (uint32_t k = 0u; k < DUOFORGE_DIGEST_SIZE; ++k) {
        if (fa[k] != fb[k]) {
            return false;
        }
    }
    return true;
}

static duoforge_status dfi_expand(duoforge_batch *leaves, const duoforge_batch *roots, uint32_t version,
                                      uint64_t ext_supported, uint64_t seed, const duoforge_request *root_requests,
                                      const duoforge_factored_domain *root_domains, const uint64_t *keys,
                                      const uint8_t *viewers, uint32_t count, const uint32_t *root_envs,
                                      const uint32_t *samples, const duoforge_factored_choice *choices,
                                      duoforge_status *step_statuses, duoforge_status *encode_statuses,
                                      duoforge_step_result *results, uint32_t *leaf_results, void *obs,
                                      bool observed, uint8_t *digests, duoforge_status *digest_statuses,
                                      duoforge_eval_error *error)
{
    dfi_expand_error(error, UINT32_MAX, "", "");
    if (leaves == NULL || roots == NULL) {
        dfi_expand_error(error, UINT32_MAX, "preflight", "expand_batch_null");
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (count > 0u && (root_requests == NULL || root_domains == NULL || keys == NULL || viewers == NULL ||
                       root_envs == NULL || samples == NULL || choices == NULL || step_statuses == NULL ||
                       encode_statuses == NULL || results == NULL || leaf_results == NULL ||
                       (!observed && obs == NULL) || (observed && (digests == NULL || digest_statuses == NULL)))) {
        dfi_expand_error(error, UINT32_MAX, "preflight", "expand_array_null");
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (!dfi_search_same_context(dfi_batch_context(leaves), dfi_batch_context(roots))) {
        dfi_expand_error(error, UINT32_MAX, "preflight", "expand_context_mismatch");
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    uint32_t obs_size = 0u;
    const duoforge_status checked = dfi_encoder_check(version, ext_supported, &obs_size);
    if (checked != DUOFORGE_OK) {
        dfi_expand_error(error, UINT32_MAX, "preflight", "expand_encoder_config");
        return checked;
    }
    if (leaves == roots || count > duoforge_batch_env_count(leaves)) {
        dfi_expand_error(error, UINT32_MAX, "preflight", "expand_leaf_capacity_or_alias");
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    const uint32_t root_count = duoforge_batch_env_count(roots);
    for (uint32_t i = 0u; i < count; ++i) {
        if (root_envs[i] >= root_count) {
            dfi_expand_error(error, UINT32_MAX, "preflight", "expand_root_index");
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
        if (viewers[root_envs[i]] > 1u) {
            dfi_expand_error(error, UINT32_MAX, "preflight", "observation_viewer");
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
    }
    if (count == 0u) {
        return DUOFORGE_OK;
    }

    dfi_expand_job job = {
        .roots = roots, .version = version, .mask = ext_supported, .seed = seed, .obs_size = obs_size,
        .root_requests = root_requests, .root_domains = root_domains, .keys = keys, .viewers = viewers,
        .root_envs = root_envs, .samples = samples, .choices = choices, .step_statuses = step_statuses,
        .encode_statuses = encode_statuses, .results = results, .leaf_results = leaf_results,
        .digests = observed ? digests : NULL, .digest_statuses = digest_statuses, .error = error,
        .error_lock = DFI_ERROR_LOCK_INIT, .error_phase = UINT32_MAX, .obs = obs
    };
    dfi_batch_leaves(leaves, count, dfi_expand_leaf, &job);
    duoforge_status status = DUOFORGE_OK;
    for (uint32_t i = 0u; i < count && status == DUOFORGE_OK; ++i) { status = step_statuses[i]; }
    if (observed) {
        for (uint32_t i = 0u; i < count && status == DUOFORGE_OK; ++i) { status = digest_statuses[i]; }
    }
    for (uint32_t i = 0u; i < count && status == DUOFORGE_OK; ++i) { status = encode_statuses[i]; }
    if (error != NULL) { dfi_error_lock_destroy(&job.error_lock); }
    return status;
}

/* The legacy ABI keeps its required encoder output and exact status ordering. */
duoforge_status duoforge_batch_expand(duoforge_batch *leaves, const duoforge_batch *roots,
    uint32_t version, uint64_t ext_supported, uint64_t seed,
    const duoforge_request *root_requests, const duoforge_factored_domain *root_domains,
    const uint64_t *keys, const uint8_t *viewers, uint32_t count,
    const uint32_t *root_envs, const uint32_t *samples, const duoforge_factored_choice *choices,
    duoforge_status *step_statuses, duoforge_status *encode_statuses,
    duoforge_step_result *results, uint32_t *leaf_results, void *obs)
{
    return dfi_expand(leaves, roots, version, ext_supported, seed, root_requests, root_domains,
        keys, viewers, count, root_envs, samples, choices, step_statuses, encode_statuses,
        results, leaf_results, obs, false, NULL, NULL, NULL);
}

duoforge_status duoforge_batch_expand_digest(duoforge_batch *leaves, const duoforge_batch *roots,
    uint32_t version, uint64_t ext_supported, uint64_t seed,
    const duoforge_request *root_requests, const duoforge_factored_domain *root_domains,
    const uint64_t *keys, const uint8_t *viewers, uint32_t count,
    const uint32_t *root_envs, const uint32_t *samples, const duoforge_factored_choice *choices,
    duoforge_status *step_statuses, duoforge_status *encode_statuses,
    duoforge_step_result *results, uint32_t *leaf_results, void *obs,
    uint8_t *digests, duoforge_status *digest_statuses, duoforge_eval_error *out_error)
{
    return dfi_expand(leaves, roots, version, ext_supported, seed, root_requests, root_domains,
        keys, viewers, count, root_envs, samples, choices, step_statuses, encode_statuses,
        results, leaf_results, obs, true, digests, digest_statuses, out_error);
}
