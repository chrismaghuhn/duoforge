#ifndef DFI_BATCH_EACH_H
#define DFI_BATCH_EACH_H

/*
 * An internal hook of the batch runtime for the encoder (decision 0021),
 * which keeps its floating point out of batch.c: fn(arg, env, ctx, battle)
 * runs for every environment over the worker slices, as every batch call
 * does; statuses[env] receives its status, and the call returns the status of
 * the lowest failing environment. fn must not change the battle.
 */
#include <duoforge/duoforge_batch.h>

typedef duoforge_status (*dfi_batch_env_fn)(void *arg, uint32_t env, const duoforge_context *ctx,
                                            const duoforge_battle *battle);

duoforge_status dfi_batch_each(duoforge_batch *batch, dfi_batch_env_fn fn, void *arg, duoforge_status *statuses);

#endif
