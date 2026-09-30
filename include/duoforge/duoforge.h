#ifndef DUOFORGE_DUOFORGE_H
#define DUOFORGE_DUOFORGE_H
/*
 * DuoForge public API -- PROVISIONAL. Not a frozen ABI.
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DUOFORGE_VERSION_MAJOR 0
#define DUOFORGE_VERSION_MINOR 1
#define DUOFORGE_VERSION_PATCH 0
#define DUOFORGE_VERSION_STRING "0.1.0"

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
#define DUOFORGE_E_INVARIANT          8u  /* internal consistency failure (engine bug) */
#define DUOFORGE_E_EXHAUSTED          9u  /* a monotonic counter would overflow */
#define DUOFORGE_E_OUT_OF_MEMORY      10u

const char *duoforge_version_string(void);
/* "DUOFORGE_OK", ...; any other value gives "DUOFORGE_STATUS_UNKNOWN". */
const char *duoforge_status_name(duoforge_status status);

#ifdef __cplusplus
}
#endif

#endif
