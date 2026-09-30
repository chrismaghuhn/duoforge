#ifndef DUOFORGE_DUOFORGE_H
#define DUOFORGE_DUOFORGE_H
/*
 * DuoForge public API -- PROVISIONAL (M1). Not a frozen ABI
 * (docs/decisions/0002).
 *
 * The library holds no mutable global state. A context is immutable after
 * creation and is designed to be shareable read-only across threads; this is
 * not yet tested under concurrency (M6). A battle handle must not be used
 * concurrently. Public input structs are read exactly once per call.
 *
 * PRIVILEGED: encode, decode, digest, equal, check and reseed operate on the
 * full hidden state (including the gameplay RNG). Their outputs are
 * diagnostics, replay or search-host artifacts and must never be
 * model-facing (no observations, features or candidate ids).
 *
 * Failure atomicity: on any non-OK return no battle, context or RNG state is
 * mutated, no out-parameter or caller buffer is written, and nothing is
 * allocated or leaked.
 *
 * M1 is structural only: there is no step, request, command or observation
 * function, and no Pokemon rules are implemented.
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DUOFORGE_VERSION_MAJOR 0
#define DUOFORGE_VERSION_MINOR 2
#define DUOFORGE_VERSION_PATCH 0
#define DUOFORGE_VERSION_STRING "0.2.0"

/* Identifiers of the artifacts that exist in M1 (registry: decision 0002). */
#define DUOFORGE_SEMANTICS_ID           1u   /* "duoforge-m1-foundation" */
#define DUOFORGE_CONTEXT_SCHEMA_VERSION 1u
#define DUOFORGE_STATE_SCHEMA_VERSION   1u
#define DUOFORGE_STATE_V1_ENCODED_SIZE  380u /* schema 1 only; size buffers via duoforge_battle_encoded_size */
#define DUOFORGE_DIGEST_SIZE            32u

/* Structural capacities of state schema 1 (initial profile bound). */
#define DUOFORGE_SIDE_COUNT       2u
#define DUOFORGE_ACTIVE_PER_SIDE  2u
#define DUOFORGE_MAX_ROSTER       6u
#define DUOFORGE_MAX_MOVE_SLOTS   4u
#define DUOFORGE_ROSTER_NONE      0xFFu /* "no member" in setup leads */

/*
 * Status codes. Values are stable within M1; renumbering before the
 * ABI-stability decision is a deliberate, reviewed change
 * (docs/decisions/0002).
 */
typedef uint32_t duoforge_status;
#define DUOFORGE_OK                   0u
#define DUOFORGE_E_NULL_ARGUMENT      1u  /* a required pointer argument is NULL */
#define DUOFORGE_E_INVALID_ARGUMENT   2u  /* config/setup value outside its domain */
#define DUOFORGE_E_CONTEXT_MISMATCH   3u  /* handle/encoding bound to another context fingerprint */
#define DUOFORGE_E_CAPACITY           4u  /* caller buffer too small; M1 encode writes nothing */
#define DUOFORGE_E_MALFORMED          5u  /* encoded bytes structurally or semantically invalid */
#define DUOFORGE_E_SCHEMA_MISMATCH    6u  /* wrong artifact kind or unsupported schema version */
#define DUOFORGE_E_SEMANTICS_MISMATCH 7u  /* encoded under another semantics id */
#define DUOFORGE_E_INVARIANT          8u  /* internal consistency failure (engine bug): state
                                             invariant or internal contract violated */
#define DUOFORGE_E_EXHAUSTED          9u  /* a monotonic counter would overflow */
#define DUOFORGE_E_OUT_OF_MEMORY      10u

const char *duoforge_version_string(void);
/* "DUOFORGE_OK", ...; any other value gives "DUOFORGE_STATUS_UNKNOWN". */
const char *duoforge_status_name(duoforge_status status);

/* ---- immutable synthetic context ---- */
#define DUOFORGE_DATA_KIND_SYNTHETIC 1u /* only accepted value in M1: no real Pokedex data */
typedef struct duoforge_context duoforge_context;
typedef struct duoforge_context_config {
    uint32_t data_kind;     /* == DUOFORGE_DATA_KIND_SYNTHETIC */
    uint32_t max_roster;    /* 1..DUOFORGE_MAX_ROSTER */
    uint32_t brought_count; /* 1..max_roster */
    uint32_t species_count; /* 1..65535; synthetic species ids 0..species_count-1 */
    uint32_t move_count;    /* 1..65535; synthetic move ids 0..move_count-1 */
} duoforge_context_config;
/* Checks: NULL(config, out) -> INVALID_ARGUMENT (fields in order) -> OUT_OF_MEMORY. */
duoforge_status duoforge_context_create(const duoforge_context_config *config,
                                        duoforge_context **out_context);
void duoforge_context_destroy(duoforge_context *context); /* NULL is a no-op */
/* SHA-256 of the canonical context bytes: semantics id, context schema,
   structural constants and config. Independent of platform and build. */
duoforge_status duoforge_context_fingerprint(const duoforge_context *context,
                                             uint8_t out_fingerprint[DUOFORGE_DIGEST_SIZE]);

/* ---- SYNTHETIC battle setup for M1 structural states. Every entry at or
   after a count must be all-zero. brought_mask and leads are fixture
   placement, not a team-selection rule or profile; M2 replaces this path
   (decision 0002). ---- */
typedef struct duoforge_move_setup {
    uint32_t move_id; /* < context move_count */
    uint32_t pp_max;  /* 1..255 */
} duoforge_move_setup;
typedef struct duoforge_member_setup {
    uint32_t species_id; /* < context species_count */
    uint32_t hp_max;     /* 1..65535 (synthetic input; M3 derives it) */
    uint32_t move_count; /* 1..DUOFORGE_MAX_MOVE_SLOTS */
    duoforge_move_setup moves[DUOFORGE_MAX_MOVE_SLOTS];
} duoforge_member_setup;
typedef struct duoforge_side_setup {
    uint32_t member_count; /* brought_count..max_roster; registered roster, stable order */
    uint32_t brought_mask; /* SYNTHETIC placement: bit i means roster index i is brought */
    uint32_t leads[DUOFORGE_ACTIVE_PER_SIDE]; /* SYNTHETIC placement; slot b is NONE iff brought_count == 1 */
    duoforge_member_setup members[DUOFORGE_MAX_ROSTER];
} duoforge_side_setup;
typedef struct duoforge_battle_setup {
    uint64_t rng_initstate;
    uint64_t rng_initseq; /* must be < 2^63 (decision 0001) */
    duoforge_side_setup sides[DUOFORGE_SIDE_COUNT];
} duoforge_battle_setup;

/* ---- owned battle state: opaque, pointer-free, bound to a context by
   fingerprint (not by pointer); every call checks the fingerprint ---- */
typedef struct duoforge_battle duoforge_battle;

/* Allocating. */
duoforge_status duoforge_battle_create(const duoforge_context *ctx, const duoforge_battle_setup *setup,
                                       duoforge_battle **out_battle);
duoforge_status duoforge_battle_create_decoded(const duoforge_context *ctx, const uint8_t *bytes,
                                               size_t size, duoforge_battle **out_battle);
duoforge_status duoforge_battle_clone(const duoforge_context *ctx, const duoforge_battle *src,
                                      duoforge_battle **out_battle);
void duoforge_battle_destroy(duoforge_battle *battle); /* NULL is a no-op */

/* Allocation-free. */
/* In-process snapshot/restore: after NULL and context checks, dst == src is a no-op. */
duoforge_status duoforge_battle_copy(const duoforge_context *ctx, duoforge_battle *dst,
                                     const duoforge_battle *src);
duoforge_status duoforge_battle_decode(const duoforge_context *ctx, duoforge_battle *dst,
                                       const uint8_t *bytes, size_t size);
duoforge_status duoforge_battle_check(const duoforge_context *ctx, const duoforge_battle *battle);
/* True iff the canonical encodings are byte-identical (covers every field,
   including the RNG state and draw counter). */
duoforge_status duoforge_battle_equal(const duoforge_context *ctx, const duoforge_battle *a,
                                      const duoforge_battle *b, bool *out_equal);
duoforge_status duoforge_battle_encoded_size(const duoforge_context *ctx, const duoforge_battle *battle,
                                             size_t *out_size);
duoforge_status duoforge_battle_encode(const duoforge_context *ctx, const duoforge_battle *battle,
                                       uint8_t *buffer, size_t capacity, size_t *out_written);
duoforge_status duoforge_battle_digest(const duoforge_context *ctx, const duoforge_battle *battle,
                                       uint8_t out_digest[DUOFORGE_DIGEST_SIZE]);
/* Fork support (PRIVILEGED): replaces the gameplay RNG with a fresh seed
   (draw counter 0), e.g. to decorrelate a copied battle for search. Nothing
   else changes. rng_initseq must be < 2^63 (decision 0001). */
duoforge_status duoforge_battle_reseed(const duoforge_context *ctx, duoforge_battle *battle,
                                       uint64_t rng_initstate, uint64_t rng_initseq);

#ifdef __cplusplus
}
#endif

#endif
