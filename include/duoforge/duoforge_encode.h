#ifndef DUOFORGE_ENCODE_H
#define DUOFORGE_ENCODE_H

/*
 * The observation encoder in C (decision 0021): the policy inputs of one
 * player, byte-equal to the reference python/duoforge/features.py for every
 * encoder version and view-extension mask. A pure function of the
 * observation, the factored domain and the view extension; it never reads a
 * battle. One of the two files of the source lint's floating-point exception
 * (with src/encode/encode.c): the outputs are float32 by contract, and every
 * value is one exactly rounded IEEE-754 operation away from its integer
 * inputs (decision 0021 section 3).
 *
 * Outputs of one player, as features.encode gives them for that version:
 *   obs        duoforge_encoder_size(version) floats
 *   slots      DUOFORGE_ENCODER_SLOT_VALUES floats (2 slot lists x 32 options x 12)
 *   pair_mask  DUOFORGE_ENCODER_PAIR_VALUES bytes, 0 or 1 (32 x 32)
 *
 * Refusals (features.py raises ValueError for each; the outputs are then all
 * zero):
 *   E_UNSUPPORTED      a value the version or mask cannot show: Sand, Snow,
 *                      Electric or Misty Terrain or Tox without its mask bit,
 *                      a Recharge option under versions 1 and 2, a REVIVE option under versions 1 to 4, a mask bit
 *                      the records' library does not support;
 *   E_INVALID_ARGUMENT anything malformed: an unknown version, a mask past
 *                      the version's feature bits or nonzero under versions 1
 *                      and 2, an unknown boundary, weather, terrain, location,
 *                      ailment, occupant, flag, slot kind, move slot or
 *                      target, a field past its range, records of another
 *                      boundary or revision, a domain of another boundary;
 *   E_NULL_ARGUMENT    a NULL pointer, or ext NULL while the mask has a
 *                      record bit.
 * The checks run in the reference's order, so a row with two faults gets the
 * same refusal on both sides.
 */
#include <duoforge/duoforge_batch.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DUOFORGE_ENCODER_MIN 1u
#define DUOFORGE_ENCODER_MAX 5u
#define DUOFORGE_ENCODER_SLOT_FEATURES 12u
#define DUOFORGE_ENCODER_SLOT_VALUES (DUOFORGE_ACTIVE_PER_SIDE * DUOFORGE_MAX_SLOT_OPTIONS * DUOFORGE_ENCODER_SLOT_FEATURES)
#define DUOFORGE_ENCODER_PAIR_VALUES (DUOFORGE_MAX_SLOT_OPTIONS * DUOFORGE_MAX_SLOT_OPTIONS)

/* The obs width of an encoder version (607 for 1 and 2, 842 for 3, 850 for 4, 862 for 5);
   E_INVALID_ARGUMENT for another version. */
duoforge_status duoforge_encoder_size(uint32_t version, uint32_t *out_obs_size);

/* The inputs of one player (see above). ext may be NULL when ext_supported
   has no record bit. */
duoforge_status duoforge_encode(uint32_t version, uint64_t ext_supported, const duoforge_observation *observation,
                                const duoforge_factored_domain *domain, const duoforge_observation_ext *ext,
                                float *obs, float *slots, uint8_t *pair_mask);

/* The RL loop's query and encoding in one pass over the environments, in the
   batch workers: per environment and player p, the request, observation and
   factored domain as duoforge_batch_query_factored (each output may be NULL:
   not written), the view extension when ext_supported has a record bit, and
   duoforge_encode into row 2 * env + p of obs, slots and pair_mask.
   statuses[env] (not NULL) receives the environment's outcome, the encoder's
   refusals included; they are never a battle's. The call returns the status
   of the lowest failing environment. The battles are not changed. A failing
   environment's rows are all zero, and once player 0 fails, player 1's
   request, observation and domain are not refreshed either; statuses[env] is
   the query's or the encoder's code (query again to tell them apart). */
duoforge_status duoforge_batch_query_encoded(duoforge_batch *batch, uint32_t version, uint64_t ext_supported,
                                             duoforge_request *requests, duoforge_observation *observations,
                                             duoforge_factored_domain *domains, float *obs, float *slots,
                                             uint8_t *pair_mask, duoforge_status *statuses);

#ifdef __cplusplus
}
#endif

#endif
