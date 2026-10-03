/*
 * Search support (decision 0022): the search seeds and the leaf expansion of
 * a one-turn lookahead. Each leaf is the single-battle calls copy, reseed,
 * step and the encoder's row, run on the leaf batch's workers through the
 * batch runtime's leaf hook (batch/batch_each.h).
 */
#include <duoforge/duoforge_search.h>

#include <stdbool.h>
#include <string.h>

#include "batch/batch_each.h"
#include "encode/encode_internal.h"

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
    float *obs;
} dfi_expand_job;

/* Leaf i (dfi_batch_leaves): copy, reseed, step, then the result or the row. */
static void dfi_expand_leaf(void *arg, uint32_t i, const duoforge_context *ctx, duoforge_battle *leaf,
                            bool *terminal)
{
    const dfi_expand_job *j = arg;
    const uint32_t r = j->root_envs[i];
    float *row = &j->obs[(size_t)i * j->obs_size];
    duoforge_step_result *result = &j->results[i];
    memset(result, 0, sizeof *result);
    j->leaf_results[i] = 0u;
    j->encode_statuses[i] = DUOFORGE_OK;

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
        st = duoforge_battle_step(ctx, leaf, &bundle, result);
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
        memset(row, 0, (size_t)j->obs_size * sizeof *row);
        return;
    }

    float slots[DUOFORGE_ENCODER_SLOT_VALUES];
    uint8_t pair_mask[DUOFORGE_ENCODER_PAIR_VALUES];
    duoforge_observation observation;
    duoforge_factored_domain domain;
    j->encode_statuses[i] = dfi_encode_player(ctx, leaf, j->viewers[r], j->version, j->mask, j->obs_size, NULL,
                                              &observation, &domain, row, slots, pair_mask);
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

duoforge_status duoforge_batch_expand(duoforge_batch *leaves, const duoforge_batch *roots, uint32_t version,
                                      uint64_t ext_supported, uint64_t seed, const duoforge_request *root_requests,
                                      const duoforge_factored_domain *root_domains, const uint64_t *keys,
                                      const uint8_t *viewers, uint32_t count, const uint32_t *root_envs,
                                      const uint32_t *samples, const duoforge_factored_choice *choices,
                                      duoforge_status *step_statuses, duoforge_status *encode_statuses,
                                      duoforge_step_result *results, uint32_t *leaf_results, float *obs)
{
    if (leaves == NULL || roots == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (count > 0u && (root_requests == NULL || root_domains == NULL || keys == NULL || viewers == NULL ||
                       root_envs == NULL || samples == NULL || choices == NULL || step_statuses == NULL ||
                       encode_statuses == NULL || results == NULL || leaf_results == NULL || obs == NULL)) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (!dfi_search_same_context(dfi_batch_context(leaves), dfi_batch_context(roots))) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    uint32_t obs_size = 0u;
    const duoforge_status checked = dfi_encoder_check(version, ext_supported, &obs_size);
    if (checked != DUOFORGE_OK) {
        return checked;
    }
    if (leaves == roots || count > duoforge_batch_env_count(leaves)) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    const uint32_t root_count = duoforge_batch_env_count(roots);
    for (uint32_t i = 0u; i < count; ++i) {
        if (root_envs[i] >= root_count || viewers[root_envs[i]] > 1u) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
    }
    if (count == 0u) {
        return DUOFORGE_OK;
    }

    dfi_expand_job job = {roots,         version,      ext_supported, seed,    obs_size,
                          root_requests, root_domains, keys,          viewers, root_envs,
                          samples,       choices,      step_statuses, encode_statuses, results,
                          leaf_results,  obs};
    dfi_batch_leaves(leaves, count, dfi_expand_leaf, &job);
    for (uint32_t i = 0u; i < count; ++i) {
        if (step_statuses[i] != DUOFORGE_OK) {
            return step_statuses[i];
        }
    }
    for (uint32_t i = 0u; i < count; ++i) {
        if (encode_statuses[i] != DUOFORGE_OK) {
            return encode_statuses[i];
        }
    }
    return DUOFORGE_OK;
}
