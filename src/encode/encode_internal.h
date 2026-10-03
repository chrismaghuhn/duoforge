#ifndef DFI_ENCODE_INTERNAL_H
#define DFI_ENCODE_INTERNAL_H

/*
 * The encoder's internal entry points for the search's leaf expansion
 * (decision 0022). A leaf's row is the row duoforge_batch_query_encoded writes
 * for that player of that battle, by the same code in src/encode/encode.c.
 * The rows are passed as void * with a row index, so this header and its
 * callers hold no floating point: the source lint's exception stays with the
 * encoder's two files (decision 0021).
 */
#include <duoforge/duoforge_encode.h>

/* The checks duoforge_batch_query_encoded runs before any row: the version's
   obs width into *out_obs_size, or E_INVALID_ARGUMENT for an unknown version
   or a mask past the version's feature bits (*out_obs_size untouched). */
duoforge_status dfi_encoder_check(uint32_t version, uint64_t ext_supported, uint32_t *out_obs_size);

/* Player p of `battle` queried and encoded as duoforge_batch_query_encoded
   does it for one row (request, observation and factored domain, the view
   extension when the mask has a record bit, then duoforge_encode), into row
   `row` of `rows`: rows of obs_size float32 values each. The slots and the
   pair mask stay on the stack. A failing query or a refused row leaves the
   row all zero. version and ext_supported must have passed dfi_encoder_check. */
duoforge_status dfi_encode_leaf(const duoforge_context *ctx, const duoforge_battle *battle, uint32_t p,
                                uint32_t version, uint64_t ext_supported, uint32_t obs_size, void *rows, uint32_t row);

/* Row `row` of `rows` (obs_size float32 values each) set to all zero. */
void dfi_encode_clear(void *rows, uint32_t obs_size, uint32_t row);

#endif
