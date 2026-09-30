# 0001 — M0 build foundation

Status: **proposed, pending owner review**. Scope: build/test infrastructure only. This note records no battle, state, RNG, request or replay contract.

## Decisions

1. **Build system:** CMake, declared minimum **3.21** (presets schema v3; CMake knows MSVC's C17 mode from 3.21). Verified locally with 3.28.3 and 3.21.4 on Linux. Other versions are untested.
2. **Language mode:** ISO C17 without compiler extensions (`C_STANDARD 17`, `C_STANDARD_REQUIRED ON`, `C_EXTENSIONS OFF`), set per target.
3. **Library shape:** one static library `pbd_core` (alias `pbd::core`). Architecture modules become directories inside it once they exist; no per-module libraries yet.
4. **Public surface:** only `include/pbd/version.h`, which declares the version and implementation-stage queries. The `PBD_VERSION_*` macros are the single version source; CMake parses them. `PbdCoreStage` is provisional and currently has one value, `FOUNDATION`, meaning the build/test foundation only, with no simulation. Public types use fixed-width integers rather than enums.
5. **Warnings:** chosen per compiler front end. GCC/Clang get `-Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Wstrict-prototypes -Wmissing-prototypes -Wformat=2 -Wundef -Wcast-qual -Wvla`. MSVC and clang-cl get `/W4 /utf-8`. `PBD_WARNINGS_AS_ERRORS` (default OFF, ON in CI) adds `-Werror` or `/WX`. An unknown compiler gets a configure warning, not guessed flags.
6. **Sanitizers:** `PBD_SANITIZE` (for example `address,undefined`) applies to GCC/Clang only. For MSVC-style compilers, requesting it is a configure error, so it is never silently ignored.
7. **Presets:** `ninja-debug`, `ninja-release` and `ninja-asan-ubsan` for GCC/Clang, plus `vs2022` (multi-config) with the `vs2022-debug` and `vs2022-release` build/test presets. Build trees go under `build/<preset>`.
8. **Tests:** registered with CTest. Every test has an explicit timeout, and the test presets set a 60 s default and error when no tests are found.
9. **Manifests:** `manifests/source_lock.json` and `manifests/support_manifest.json` use draft schemas (`*.v0-draft`) and are validated by a CMake script. The checker rejects:
   - an UNPINNED source that carries a revision or hash;
   - a PINNED source that lacks a well-formed commit id or file hashes;
   - any certification claim while sources are unpinned or the profile/teams are unselected.

   The checker has negative fixtures. It checks structure only, not provenance.

## Alternatives considered

- **Meson or plain Makefiles.** Rejected in favour of CMake, which the task asks for, has first-class Visual Studio generators, and supports presets.
- **A generated version header** (`configure_file`). Rejected because a checked-in header is simpler to read and review. The version is parsed from it instead.
- **A Python manifest validator.** Rejected because it would add a Python dependency to the core test run. The CMake `string(JSON)` command is enough for this check.
- **`include(CTest)`.** Rejected because it adds CDash dashboard targets that are not needed; `enable_testing()` is enough.

## Consequences

- Changing the version means editing `include/pbd/version.h` only.
- A future module adds sources to `pbd_core` and calls `pbd_configure_target` for any new target.
- The manifest schemas are drafts. Later milestones may reshape them, and each such change must update the checker and fixtures together.

## Evidence

Evidence is the local runs listed in the M0 report and the tests in `tests/`. Hosted CI counts as evidence only once a run on the relevant revision has actually been observed.
