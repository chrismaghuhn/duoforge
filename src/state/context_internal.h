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
 * of the extended tables (TEAM_C kinds) or of the pool tables with their
 * family columns (POOL kinds), whose counts are then those of the kind's
 * tables. Encode-only. */
#define DFI_CONTEXT_BYTES_SIZE 63u
#define DFI_CONTEXT_TABLE_HASH_OFF 31u
#define DFI_CONTEXT_TABLE_CAPACITY 65535u
/* The certified profile (decision 0010): a CLOSURE context registers
 * DUOFORGE_MAX_ROSTER members per side and brings this many. */
#define DFI_CLOSURE_BROUGHT_COUNT 4u

struct duoforge_context {
    uint8_t data_kind; /* validated, narrowed copies of the config */
    uint8_t max_roster;
    uint8_t brought_count;
    uint16_t species_count;
    uint16_t move_count;
    uint8_t fingerprint[DUOFORGE_DIGEST_SIZE]; /* computed once at create */
    uint8_t table_hash[DUOFORGE_DIGEST_SIZE];  /* SYNTHETIC: SHA-256 of the table; else the tables' hash */
    uint8_t move_target_classes[DFI_CONTEXT_TABLE_CAPACITY]; /* entries >= move_count are zero */
};

/* True for the combat data kinds, which read the generated tables (the pool
 * tables, under every kind): DUOFORGE_DATA_KIND_CLOSURE and _CLOSURE_DEV (the
 * closure prefix), _TEAM_C and _TEAM_C_DEV (the extended prefix, decision
 * 0009) and _POOL and _POOL_DEV (all of them, decision 0015). Species ids are
 * forme ids and move ids move ids of those tables. */
bool dfi_context_is_closure(const struct duoforge_context *ctx);

/* True for the kinds with the certified profile of decision 0010 (a context
 * of DUOFORGE_MAX_ROSTER and DFI_CLOSURE_BROUGHT_COUNT, exactly
 * DUOFORGE_MAX_ROSTER members per side): CLOSURE, and TEAM_C and POOL, which
 * take it over (decisions 0009 section 3.4 and 0015 section 2). The DEV kinds
 * take brought..max. */
bool dfi_kind_full_roster(uint32_t data_kind);

void dfi_context_canonical_bytes(const struct duoforge_context *ctx, uint8_t out[DFI_CONTEXT_BYTES_SIZE]);
bool dfi_context_fingerprint_matches(const struct duoforge_context *ctx,
                                     const uint8_t fingerprint[DUOFORGE_DIGEST_SIZE]);

#endif
