#ifndef DUOFORGE_DUOFORGE_H
#define DUOFORGE_DUOFORGE_H
/*
 * DuoForge public API -- PROVISIONAL. Not a frozen ABI.
 */
#ifdef __cplusplus
extern "C" {
#endif

#define DUOFORGE_VERSION_MAJOR 0
#define DUOFORGE_VERSION_MINOR 1
#define DUOFORGE_VERSION_PATCH 0
#define DUOFORGE_VERSION_STRING "0.1.0"

const char *duoforge_version_string(void);

#ifdef __cplusplus
}
#endif

#endif
