# 0003 — M1 build and evidence policy

Status: **proposed**. It is implemented in M1 and becomes binding when the owner accepts the reviewed M1 change.

## Build

- **CMake ≥ 3.23**, verified locally with 3.23.3 and 3.28.3. The language mode is C17 without extensions.
- **The static library `duoforge`** is built from `src/`. C++ is used only for an optional `extern "C"` link test.
- **Warnings are set per target** (`cmake/DuoforgeTargetOptions.cmake`):
  - GCC/Clang: `-Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Wstrict-prototypes -Wmissing-prototypes -Wcast-qual -Wvla -Wundef -Wformat=2 -Wimplicit-fallthrough`, plus `-Warith-conversion` on GCC only (Clang lacks it).
  - MSVC: `/W4 /permissive- /utf-8`.
  - `DUOFORGE_WARNINGS_AS_ERRORS` (default OFF, so newer compilers do not break users; ON in CI and in all local verification) adds `-Werror` or `/WX`.
  - There are no per-warning suppressions; an MSVC exception would need a written justification here, and none currently exists.
- **The warning set is not a promotion-safety proof.** Neither GCC nor Clang diagnoses a cast applied to a promoted result, or a 32×32→64 product that wraps before widening. Promotion safety relies on:
  - review;
  - the `result-cast` lint marker;
  - extreme-value tests (0xFF bytes, `UINTn_MAX`) under GCC UBSan.
- **Sanitizers.** `DUOFORGE_ENABLE_SANITIZERS` enables ASan+UBSan with `-fno-sanitize-recover=all` on GCC/Clang, with link flags on executables only; on MSVC it is a configure error.
  - Liveness canaries prove the setup. The UBSan canary runs with `halt_on_error=0`, because `halt_on_error=1` would mask a missing compile flag.
  - `abort_on_error` is never used: CTest would report an abort even when the expected output matched.
- **Tests are finite.** Every test has an explicit timeout (30 s default; 60–120 s for sweeps). Presets set `noTestsAction: error` and a 120 s default. Tests never use `assert`/`NDEBUG`, so the full suite runs in Release.

## Automated evidence

| Check | What it enforces |
|---|---|
| `duoforge.lint.sources` | Over `src/` and `include/`: no `rand`/`time`/`clock`/`getenv`/`setjmp`/`memcmp`/`assert`/`printf`-family calls; allocation only in `src/core/alloc.c`; no floating point, no thread-local storage, no signed or implicitly sized integer types; no `L`-suffixed literals; no packing pragmas; no unmarked cast of a parenthesized expression; ASCII only. Comments are linted too; reword text rather than weaken a rule. |
| `duoforge.lint.selftest` | The lint detects each rule on byte-exact fixtures (`tests/lint_fixtures`, `-text` in `.gitattributes`), has no alignment false positive, and does not crash on a >64 KB file. Regexes are applied per line only, because CMake regex recursion can overflow the stack. |
| `duoforge.lint.no_mutable_globals` | objdump shows no writable static storage in the library. It is non-vacuous: it requires the `duoforge_version_string` text symbol. It reports **SKIPPED** (never PASS) on sanitizer and non-ELF (MSVC) builds. |
| `duoforge.provenance.pcg_license` | The vendored Apache-2.0 license is byte-exact. |
| `duoforge.sanitizer.canary_*` | UBSan is non-recovering by compile flag, and ASan is live. |
| `duoforge.api.cxx_link` and the header check | The `extern "C"` guard works; the public header is self-contained. |
| `duoforge.rng.kat_regen`, `duoforge.rng.reference_differential` (optional, label `reference`) | These run only with `DUOFORGE_PCG_REFERENCE_DIR`. Configure verifies the pinned hashes. The upstream file is built as an isolated third-party library without the project warning set (it is not warning-clean under it). |

## CI

- **`.github/workflows/ci.yml`:**
  - Linux (`ubuntu-24.04`): gcc/clang × Debug/Release, plus a GCC ASan+UBSan job.
  - Windows (`windows-latest`): MSVC x64 Debug/Release and a Win32 Release row. The Win32 row asserts `pointer_bits=32` from the smoke test output.
  - Every job has `timeout-minutes: 15` and uses `--no-tests=error --timeout 120`.
  - `actions/checkout` is pinned to the v6.1.0 commit `d23441a48e516b6c34aea4fa41551a30e30af803` (verified with `git ls-remote` on 2026-09-30).
- **`.github/workflows/rng-reference.yml`** is separate, because path filters exist only per workflow. It fetches the pinned pcg-c-basic, checks the three hashes and runs the reference tests. A fetch failure is reported as **BLOCKED** in the step summary, not as a KAT regression.
- **Not added (follow-ups):**
  - Clang sanitizer CI: compiler-rt is unavailable in the local verification environment, so the job cannot be verified here.
  - Linux `-m32`: the Win32 row covers 32-bit `size_t`.
  - A big-endian (qemu) job.

## Offline oracle

`tools/state_model/state_v1_model.py` is a stdlib-only structural model written from decision 0002, **never run by CTest**. Its output hash is recorded in 0002. Test expectations are embedded as C arrays and literals, so tests need no Python and do no file I/O.

## Result labels

| Label | Meaning |
|---|---|
| PASS | Observed passing on the stated revision and configuration. |
| FAIL | Observed failing. |
| NOT_RUN | Not executed; a workflow file alone is not a run. |
| BLOCKED | Could not run for an external reason (for example network or toolchain), stated. |
| SKIPPED | The check ran and determined it does not apply (for example the globals check on MSVC). |
