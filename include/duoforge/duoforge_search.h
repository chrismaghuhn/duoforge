#ifndef DUOFORGE_SEARCH_H
#define DUOFORGE_SEARCH_H

/*
 * Search support (decision 0022, roadmap M12): the leaves of a one-turn
 * lookahead expanded in the batch workers, and the seeds of their chance.
 * The engine holds no search logic here: it copies, reseeds, steps and
 * encodes; choosing the pairs and reading the values is the caller's. The
 * rows are the encoder's float32 rows (duoforge_encode.h), taken here as
 * void *, so this header holds no floating point (the source lint's
 * exception stays with the encoder's two files).
 *
 * A leaf is a copy of a root (an environment of another batch, the "root
 * batch") after one step with one factored choice per requested player, its
 * gameplay RNG replaced by the search seeds of (seed, key, sample) first. The
 * seeds depend on these three values only: never on the choices, so the
 * samples are common random numbers across the cells of a table, and never on
 * a worker, a chunk or the leaf's position.
 *
 * Copy and reseed are privileged operations (decision 0002): a search on the
 * true state of a battle is an oracle benchmark (ARCHITECTURE section 10).
 */
#include <duoforge/duoforge_encode.h>

#ifdef __cplusplus
extern "C" {
#endif

/* The leaf seeds of (seed, key, sample), with splitmix64 the finalizer of
   x + 0x9E3779B97F4A7C15 (decision 0012):
     h         = splitmix64(splitmix64(seed + 0x5345415243480001) + key)
     s         = splitmix64(h + sample)
     initstate = splitmix64(s + 1)
     initseq   = splitmix64(s + 2) >> 1   (below 2^63, decision 0001)
   Either output may be NULL (not written). */
void duoforge_search_seeds(uint64_t seed, uint64_t key, uint32_t sample, uint64_t *out_initstate,
                           uint64_t *out_initseq);

/* Expands `count` leaves into environments 0 .. count - 1 of `leaves`, in
   parallel on its workers, in one pass. For leaf i with root environment
   r = root_envs[i] of `roots`:
     1. the leaf environment becomes a copy of root r (duoforge_battle_copy);
     2. it is reseeded with duoforge_search_seeds(seed, keys[r], samples[i]);
     3. it is stepped with the bundle of choices[2 * i] and choices[2 * i + 1]
        in the domains root_domains[2 * r + p] of the requests
        root_requests[2 * r + p] (the arrays of the roots' last
        duoforge_batch_query_encoded or _query_factored), built and checked
        exactly as duoforge_batch_step_factored builds them; a player whose
        request has requested 0 gives no response and its choice is ignored;
        step_statuses[i] and results[i] receive the outcome (results[i] is
        all zero when the step fails);
     4. at TERMINAL leaf_results[i] receives DUOFORGE_RESULT_*, the row is all
        zero and encode_statuses[i] is OK: such a leaf is scored by its
        result. Otherwise leaf_results[i] is 0, and player viewers[r] of the
        leaf is queried and encoded as duoforge_batch_query_encoded queries
        and encodes one row (version, ext_supported) into row i of obs:
        obs holds count rows of width = duoforge_encoder_size(version)
        float32 values, as duoforge_batch_query_encoded's obs does;
        encode_statuses[i] receives the row's status, the query's or the
        encoder's. A failed step leaves encode_statuses[i] OK and the
        row all zero.
   Outcomes are atomic per leaf: the call returns the lowest failing leaf's
   step status, else the lowest failing leaf's encode status, else OK. Two
   arrays keep a refused step (the engine's) apart from a refused row (the
   encoder's). A leaf environment's TERMINAL flag follows its battle; its
   episode number is not changed. The roots are only read and must not
   change during the call; only one caller uses either batch at a time. No
   allocation: a leaf's temporaries live on the stack.
   Checks before any leaf is touched, in this order:
     E_NULL_ARGUMENT     leaves or roots NULL, or with count > 0 any array;
     E_CONTEXT_MISMATCH  the batches' contexts have different fingerprints;
     E_INVALID_ARGUMENT  an unknown version or a mask past its feature bits
                         (as duoforge_batch_query_encoded checks them);
                         leaves == roots; count past the leaf batch; a root
                         environment past the root batch; a viewer other
                         than 0 or 1.
   count 0 is OK after these checks, with every array allowed NULL. */
duoforge_status duoforge_batch_expand(duoforge_batch *leaves, const duoforge_batch *roots, uint32_t version,
                                      uint64_t ext_supported, uint64_t seed, const duoforge_request *root_requests,
                                      const duoforge_factored_domain *root_domains, const uint64_t *keys,
                                      const uint8_t *viewers, uint32_t count, const uint32_t *root_envs,
                                      const uint32_t *samples, const duoforge_factored_choice *choices,
                                      duoforge_status *step_statuses, duoforge_status *encode_statuses,
                                      duoforge_step_result *results, uint32_t *leaf_results, void *obs);

#ifdef __cplusplus
}
#endif

#endif
