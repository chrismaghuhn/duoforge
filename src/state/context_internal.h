#ifndef DUOFORGE_STATE_CONTEXT_INTERNAL_H
#define DUOFORGE_STATE_CONTEXT_INTERNAL_H
/* Immutable synthetic context (docs/decisions/0002). */
#include <stdbool.h>
#include <stdint.h>

#include <duoforge/duoforge.h>

/* Canonical context bytes v1: the fingerprint preimage (encode-only). */
#define DFI_CONTEXT_BYTES_SIZE 31u

struct duoforge_context {
    uint8_t data_kind; /* validated, narrowed copies of the config */
    uint8_t max_roster;
    uint8_t brought_count;
    uint16_t species_count;
    uint16_t move_count;
    uint8_t fingerprint[DUOFORGE_DIGEST_SIZE]; /* computed once at create */
};

void dfi_context_canonical_bytes(const struct duoforge_context *ctx, uint8_t out[DFI_CONTEXT_BYTES_SIZE]);
bool dfi_context_fingerprint_matches(const struct duoforge_context *ctx,
                                     const uint8_t fingerprint[DUOFORGE_DIGEST_SIZE]);

#endif
