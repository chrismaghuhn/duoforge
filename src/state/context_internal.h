#ifndef DUOFORGE_STATE_CONTEXT_INTERNAL_H
#define DUOFORGE_STATE_CONTEXT_INTERNAL_H
/* Immutable synthetic context v2 (docs/decisions/0002, 0005). */
#include <stdbool.h>
#include <stdint.h>

#include <duoforge/duoforge.h>

/* Canonical context bytes v2: the v1 preimage (31 bytes, schema 2 /
 * semantics 2 / length 63) followed by the SHA-256 of the target-class
 * table. Encode-only. */
#define DFI_CONTEXT_BYTES_SIZE 63u
#define DFI_CONTEXT_TABLE_HASH_OFF 31u
#define DFI_CONTEXT_TABLE_CAPACITY 65535u

struct duoforge_context {
    uint8_t data_kind; /* validated, narrowed copies of the config */
    uint8_t max_roster;
    uint8_t brought_count;
    uint16_t species_count;
    uint16_t move_count;
    uint8_t fingerprint[DUOFORGE_DIGEST_SIZE]; /* computed once at create */
    uint8_t table_hash[DUOFORGE_DIGEST_SIZE];  /* SHA-256 of move_target_classes[0..move_count) */
    uint8_t move_target_classes[DFI_CONTEXT_TABLE_CAPACITY]; /* entries >= move_count are zero */
};

void dfi_context_canonical_bytes(const struct duoforge_context *ctx, uint8_t out[DFI_CONTEXT_BYTES_SIZE]);
bool dfi_context_fingerprint_matches(const struct duoforge_context *ctx,
                                     const uint8_t fingerprint[DUOFORGE_DIGEST_SIZE]);

#endif
