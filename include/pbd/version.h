/*
 * pokemon-doubles-core — version and implementation-stage query.
 *
 * This header is the only public surface of the M0 foundation. It does not
 * describe battle state, requests, commands or replay artifacts; those
 * contracts do not exist yet and must not be inferred from this file.
 *
 * The PBD_VERSION_* macros below are the single source of truth for the
 * project version; the top-level CMakeLists.txt parses them.
 */
#ifndef PBD_VERSION_H
#define PBD_VERSION_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PBD_VERSION_MAJOR 0
#define PBD_VERSION_MINOR 1
#define PBD_VERSION_PATCH 0
#define PBD_VERSION_STRING "0.1.0"

typedef struct PbdVersion {
    uint32_t major;
    uint32_t minor;
    uint32_t patch;
} PbdVersion;

/*
 * Implementation stage of the linked core library. Values are provisional
 * and will be revised when later milestones add real capabilities.
 */
typedef uint32_t PbdCoreStage;

/* Build/test foundation only: no RNG, state, decisions or battle simulation. */
#define PBD_CORE_STAGE_FOUNDATION ((PbdCoreStage)1u)

/* Version of the linked library (may differ from the macros above if a stale
 * library is linked against a newer header). */
PbdVersion pbd_version(void);

/* NUL-terminated "MAJOR.MINOR.PATCH" with static storage duration. */
const char *pbd_version_string(void);

/* Implementation stage of the linked library. */
PbdCoreStage pbd_core_stage(void);

#ifdef __cplusplus
}
#endif

#endif /* PBD_VERSION_H */
