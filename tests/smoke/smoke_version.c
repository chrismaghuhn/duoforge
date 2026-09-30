/*
 * M0 smoke test: proves that the static core library links and that its
 * version/stage query returns the values promised by the public header.
 *
 * Bounded: a fixed number of straight-line checks, no loops over external
 * input. This test says nothing about simulated Pokémon correctness; the
 * core implements no battle simulation yet.
 *
 * Uses explicit checks instead of assert() so Release builds (NDEBUG) still
 * test something.
 */
#include "pbd/version.h"

#include <stdio.h>
#include <string.h>

static void check(int *failures, int condition, const char *what)
{
    if (!condition) {
        (void)fprintf(stderr, "FAIL: %s\n", what);
        ++*failures;
    }
}

int main(void)
{
    const PbdVersion version = pbd_version();
    const char *version_string = pbd_version_string();
    char expected_string[48];
    int written;
    int failures = 0;

    check(&failures, version.major == (uint32_t)PBD_VERSION_MAJOR, "runtime major matches header");
    check(&failures, version.minor == (uint32_t)PBD_VERSION_MINOR, "runtime minor matches header");
    check(&failures, version.patch == (uint32_t)PBD_VERSION_PATCH, "runtime patch matches header");

    check(&failures, version_string != NULL, "version string is non-null");
    if (version_string != NULL) {
        check(&failures, strcmp(version_string, PBD_VERSION_STRING) == 0,
              "runtime version string matches PBD_VERSION_STRING");

        written = snprintf(expected_string, sizeof expected_string, "%lu.%lu.%lu",
                           (unsigned long)version.major, (unsigned long)version.minor,
                           (unsigned long)version.patch);
        check(&failures, written > 0 && (size_t)written < sizeof expected_string,
              "formatted numeric version fits the buffer");
        if (written > 0 && (size_t)written < sizeof expected_string) {
            check(&failures, strcmp(version_string, expected_string) == 0,
                  "version string agrees with numeric version");
        }
    }

    check(&failures, pbd_core_stage() == PBD_CORE_STAGE_FOUNDATION,
          "core reports FOUNDATION stage (no battle simulation implemented)");

    if (failures != 0) {
        (void)fprintf(stderr, "pbd smoke test: %d check(s) failed\n", failures);
        return 1;
    }

    (void)printf("pbd smoke test: PASS (version %s, stage FOUNDATION)\n",
                 version_string != NULL ? version_string : "?");
    return 0;
}
