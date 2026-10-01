#ifndef DUOFORGE_BATCH_POOL_H
#define DUOFORGE_BATCH_POOL_H

/*
 * A fixed pool of worker threads for the batch runtime (decision 0012).
 * dfi_pool_run splits [0, items) into `workers` contiguous slices, slice w
 * = [items * w / workers, items * (w + 1) / workers); the calling thread runs
 * slice 0 and returns when every slice is done. The handoff runs under one
 * mutex, so everything a worker wrote is visible to the caller afterwards.
 */
#include <stdbool.h>
#include <stdint.h>

typedef void (*dfi_pool_fn)(void *job, uint32_t worker, uint32_t begin, uint32_t end);

typedef struct dfi_pool dfi_pool;

/* NULL when a thread or the memory cannot be had. workers >= 1. */
dfi_pool *dfi_pool_create(uint32_t workers);
void dfi_pool_destroy(dfi_pool *pool); /* NULL is a no-op; joins every thread */
void dfi_pool_run(dfi_pool *pool, dfi_pool_fn fn, void *job, uint32_t items);
uint32_t dfi_pool_workers(const dfi_pool *pool);

#endif
