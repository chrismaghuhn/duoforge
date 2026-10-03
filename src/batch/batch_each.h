#ifndef DFI_BATCH_EACH_H
#define DFI_BATCH_EACH_H

/*
 * Internal hooks of the batch runtime for the encoder (decision 0021) and the
 * search (decision 0022), which keep their floating point out of batch.c.
 *
 * dfi_batch_each: fn(arg, env, ctx, battle) runs for every environment over
 * the worker slices, as every batch call does; statuses[env] receives its
 * status, and the call returns the status of the lowest failing environment.
 * fn must not change the battle.
 */
#include <duoforge/duoforge_batch.h>

#include <stdbool.h>

typedef duoforge_status (*dfi_batch_env_fn)(void *arg, uint32_t env, const duoforge_context *ctx,
                                            const duoforge_battle *battle);

duoforge_status dfi_batch_each(duoforge_batch *batch, dfi_batch_env_fn fn, void *arg, duoforge_status *statuses);

/* The query of one player in the order every batch query uses (request,
   observation, candidates with their count, factored domain); each output may
   be NULL (skipped); candidates need count. */
duoforge_status dfi_batch_query_player(const duoforge_context *ctx, const duoforge_battle *battle, uint32_t p,
                                       duoforge_request *request, duoforge_observation *observation,
                                       duoforge_side_choice *candidates, uint32_t *count,
                                       duoforge_factored_domain *domain);

/* dfi_batch_leaves: fn(arg, env, ctx, battle, terminal) runs for every env <
   count (at most the environment count) over the worker slices with
   environment env's battle, which fn may overwrite, and the environment's
   TERMINAL flag, which fn keeps true to that battle. fn writes its own
   outputs; nothing else of the environment changes (its episode stays). */
typedef void (*dfi_batch_leaf_fn)(void *arg, uint32_t env, const duoforge_context *ctx, duoforge_battle *battle,
                                  bool *terminal);

void dfi_batch_leaves(duoforge_batch *batch, uint32_t count, dfi_batch_leaf_fn fn, void *arg);

/* The context the batch was created with. */
const duoforge_context *dfi_batch_context(const duoforge_batch *batch);

/* The bundle of one boundary from both players' requests, factored domains
   and factored choices (two entries each), as duoforge_batch_step_factored
   builds it: the epoch of player 0's request; for each requested player the
   response built as the enumeration builds a candidate; an unrequested
   player's response stays all zero. E_INVALID_ARGUMENT for a SLOTS pair past
   the lists or not allowed, or a requested player whose domain has another
   kind; the step checks a TEAM_SELECTION tuple. *bundle is zeroed first. */
duoforge_status dfi_factored_bundle(const duoforge_request *requests, const duoforge_factored_domain *domains,
                                    const duoforge_factored_choice *choices, duoforge_decision_bundle *bundle);

/* One splitmix64 step from state z (Steele, Lea, Flood 2014): the finalizer
   of z + 0x9E3779B97F4A7C15 (decisions 0012 and 0022). */
static inline uint64_t dfi_splitmix(uint64_t z)
{
    z += 0x9E3779B97F4A7C15u;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9u;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBu;
    return z ^ (z >> 31);
}

#endif
