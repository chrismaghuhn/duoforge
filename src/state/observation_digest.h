#ifndef DUOFORGE_STATE_OBSERVATION_DIGEST_H
#define DUOFORGE_STATE_OBSERVATION_DIGEST_H
/* Decision 0082. Private scratch, not battle state or a public layout. */
#include <duoforge/duoforge.h>
#include "core/private.h"
#include "core/sha256.h"
#include "state/battle_internal.h"
#define DFI_OBSERVATION_REQUEST_MAX 1024u
#define DFI_OBSERVATION_LINE_MAX 64u
typedef struct dfi_visible_identity {
    uint16_t forme; /* displayed species/forme at emission time, not a roster index */
    uint8_t gender;
    uint8_t valid;
    uint8_t side; /* step K5: the side of the identity, set only for Magic Room's end line (FIELD_END detail 7), which names a Pokemon that may be benched */
} dfi_visible_identity;
typedef struct dfi_observation_digest {
    dfi_sha256_state hash;
    dfi_visible_identity identity[DUOFORGE_MAX_EVENTS];
    uint32_t viewer;
    uint32_t rows;
    duoforge_status status;
    bool complete;
    uint8_t digest[DFI_SHA256_SIZE];
    char reason[128];
} dfi_observation_digest;
/* Both encoders serialize a whitelist, not raw records. Required size is
 * reported on E_CAPACITY and the output stays untouched. Inputs are existing
 * viewer-authorized query results, not particle-filled public records. */
DFI_PRIVATE duoforge_status dfi_observation_line_encode(const duoforge_event *projected,
    const dfi_visible_identity *identity, uint8_t *out, uint32_t capacity, uint32_t *size);
DFI_PRIVATE duoforge_status dfi_observation_request_encode(const duoforge_step_result *result,
    const duoforge_request *request, const duoforge_observation *view,
    const duoforge_observation_ext *ext, const duoforge_factored_domain *domain,
    uint8_t *out, uint32_t capacity, uint32_t *size);
DFI_PRIVATE duoforge_status dfi_observation_digest_init(dfi_observation_digest *digest, uint32_t viewer);
/* Capture immutable displayed identity before later forme changes. */
DFI_PRIVATE void dfi_observation_capture(dfi_observation_digest *digest,
    const struct duoforge_battle *battle, const duoforge_event *event, uint32_t index);
/* Called after projection, before any knowledge-fold continue, i >= first. */
DFI_PRIVATE void dfi_observation_fold(dfi_observation_digest *digest,
    const duoforge_event *projected, uint32_t index);
/* Called only after successful commit. Projection failure has its own
 * sticky status and zero digest; it never changes the step's outcome.
 * event_count is the independently staged engine count, not digest->rows. */
DFI_PRIVATE void dfi_observation_finish_view(dfi_observation_digest *digest,
    const duoforge_step_result *result, const duoforge_request *request,
    const duoforge_observation *view, const duoforge_observation_ext *ext,
    const duoforge_factored_domain *domain, uint32_t event_count);
DFI_PRIVATE void dfi_observation_finish(dfi_observation_digest *digest,
    const duoforge_context *ctx, const duoforge_battle *battle,
    const duoforge_step_result *result, uint32_t event_count);
#endif
