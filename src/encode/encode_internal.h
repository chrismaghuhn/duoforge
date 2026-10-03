#ifndef DFI_ENCODE_INTERNAL_H
#define DFI_ENCODE_INTERNAL_H

/*
 * The encoder's batch path for one player (decision 0021), shared with the
 * search's leaf expansion (decision 0022), so a leaf's row is the row
 * duoforge_batch_query_encoded writes for that player of that battle, by the
 * same code. One of the files of the source lint's floating-point exception:
 * it passes float32 rows through and computes nothing in floating point.
 */
#include <duoforge/duoforge_encode.h>

/* The checks duoforge_batch_query_encoded runs before any row: the version's
   obs width into *out_obs_size, or E_INVALID_ARGUMENT for an unknown version
   or a mask past the version's feature bits (*out_obs_size untouched). */
duoforge_status dfi_encoder_check(uint32_t version, uint64_t ext_supported, uint32_t *out_obs_size);

/* Player p of `battle` as duoforge_batch_query_encoded queries and encodes
   one row: the request, observation and factored domain (into the given
   records, request may be NULL), the view extension when the mask has a
   record bit, then duoforge_encode into obs (obs_size floats), slots and
   pair_mask. A failing query leaves the row all zero, as a refused one is.
   version and ext_supported must have passed dfi_encoder_check. */
duoforge_status dfi_encode_player(const duoforge_context *ctx, const duoforge_battle *battle, uint32_t p,
                                  uint32_t version, uint64_t ext_supported, uint32_t obs_size,
                                  duoforge_request *request, duoforge_observation *observation,
                                  duoforge_factored_domain *domain, float *obs, float *slots, uint8_t *pair_mask);

#endif
