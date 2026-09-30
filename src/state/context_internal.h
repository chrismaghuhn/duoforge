#ifndef DUOFORGE_STATE_CONTEXT_INTERNAL_H
#define DUOFORGE_STATE_CONTEXT_INTERNAL_H
/* Immutable context (docs/decisions/0002, 0005, 0006 section 2). */
#include <stdbool.h>
#include <stdint.h>

#include <duoforge/duoforge.h>

/* Canonical context bytes: the v1 preimage (31 bytes: envelope, structural
 * constants, data kind, roster, brought count, species and move counts)
 * followed by a 32-byte data hash: the SHA-256 of the target-class table
 * (SYNTHETIC) or the hash of the generated closure tables (CLOSURE kinds),
 * whose counts are then those of the tables. Encode-only. */
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
    uint8_t table_hash[DUOFORGE_DIGEST_SIZE];  /* SYNTHETIC: SHA-256 of the table; CLOSURE: the closure hash */
    uint8_t move_target_classes[DFI_CONTEXT_TABLE_CAPACITY]; /* entries >= move_count are zero */
};

/* True for DUOFORGE_DATA_KIND_CLOSURE and _CLOSURE_DEV: species ids are
 * closure forme ids and move ids closure move ids. */
bool dfi_context_is_closure(const struct duoforge_context *ctx);

void dfi_context_canonical_bytes(const struct duoforge_context *ctx, uint8_t out[DFI_CONTEXT_BYTES_SIZE]);
bool dfi_context_fingerprint_matches(const struct duoforge_context *ctx,
                                     const uint8_t fingerprint[DUOFORGE_DIGEST_SIZE]);

#endif
