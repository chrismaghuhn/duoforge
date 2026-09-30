#include "pbd/version.h"

#define PBD_STRINGIFY_(x) #x
#define PBD_STRINGIFY(x) PBD_STRINGIFY_(x)

/* Derived from the numeric macros so it cannot disagree with pbd_version().
 * The smoke test compares it with PBD_VERSION_STRING to catch header drift. */
static const char pbd_version_string_value[] =
    PBD_STRINGIFY(PBD_VERSION_MAJOR) "." PBD_STRINGIFY(PBD_VERSION_MINOR) "." PBD_STRINGIFY(
        PBD_VERSION_PATCH);

PbdVersion pbd_version(void)
{
    PbdVersion version;
    version.major = (uint32_t)PBD_VERSION_MAJOR;
    version.minor = (uint32_t)PBD_VERSION_MINOR;
    version.patch = (uint32_t)PBD_VERSION_PATCH;
    return version;
}

const char *pbd_version_string(void)
{
    return pbd_version_string_value;
}

PbdCoreStage pbd_core_stage(void)
{
    return PBD_CORE_STAGE_FOUNDATION;
}
