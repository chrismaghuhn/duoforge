# Self-test for lint_sources.cmake (run with cmake -P). See docs/decisions/0003.
#
# Usage: cmake -DROOT=<repo> -DWORK=<scratch dir> -P cmake/checks/lint_selftest.cmake
#
# Runs the lint on byte-exact fixtures (tests/lint_fixtures, never compiled)
# and on a generated clean file larger than 64 KB, and checks the exit status
# and the reported rule ids. Prints "LINT_SELFTEST OK" on success.

cmake_minimum_required(VERSION 3.23)

foreach(_v IN ITEMS ROOT WORK)
    if(NOT DEFINED ${_v})
        message(FATAL_ERROR "lint selftest: ${_v} is required")
    endif()
endforeach()

set(_lint "${ROOT}/cmake/checks/lint_sources.cmake")
set(_fix "${ROOT}/tests/lint_fixtures")

# expect: CLEAN, or the exact rule id that must be reported. count: expected
# number of findings (lines ending in ": <rule>").
function(_lint_case file expect count)
    set(_case_root "${ROOT}")
    if(ARGC GREATER 3)
        set(_case_root "${ARGV3}") # a root whose relative paths the case sets up
    endif()
    execute_process(
        COMMAND "${CMAKE_COMMAND}" "-DROOT=${_case_root}" "-DFILES=${file}" -P "${_lint}"
        RESULT_VARIABLE _rc
        OUTPUT_VARIABLE _out
        ERROR_VARIABLE _err)
    set(_all "${_out}${_err}")
    get_filename_component(_name "${file}" NAME)
    if(expect STREQUAL "CLEAN")
        if(NOT _rc EQUAL 0)
            message("lint selftest: ${_name}: expected clean, got rc=${_rc}\n${_all}")
            set(_bad 1 PARENT_SCOPE)
        endif()
        return()
    endif()
    if(_rc EQUAL 0)
        message("lint selftest: ${_name}: expected '${expect}', lint passed\n${_all}")
        set(_bad 1 PARENT_SCOPE)
        return()
    endif()
    string(REGEX MATCHALL ":[0-9]+: [a-z-]+" _hits "${_all}")
    set(_matching 0)
    set(_other 0)
    foreach(_h IN LISTS _hits)
        if(_h MATCHES ": ${expect}$")
            math(EXPR _matching "${_matching} + 1")
        else()
            math(EXPR _other "${_other} + 1")
        endif()
    endforeach()
    if(NOT _matching EQUAL count OR NOT _other EQUAL 0)
        message("lint selftest: ${_name}: expected ${count}x '${expect}' only, got ${_matching} matching and ${_other} other\n${_all}")
        set(_bad 1 PARENT_SCOPE)
    endif()
    set(_last_output "${_all}" PARENT_SCOPE)
endfunction()

set(_bad 0)

# 1. A clean file larger than 64 KB must not crash the per-line regexes.
file(MAKE_DIRECTORY "${WORK}")
string(REPEAT "/* clean filler line for the lint size test: abcdefghij 0123456789 */\n" 1100 _filler)
file(WRITE "${WORK}/big_clean.h" "${_filler}")
file(SIZE "${WORK}/big_clean.h" _big_size)
if(_big_size LESS 70000)
    message(FATAL_ERROR "lint selftest: generated file too small (${_big_size} bytes)")
endif()
_lint_case("${WORK}/big_clean.h" CLEAN 0)

# 2. Byte-level and rule fixtures.
_lint_case("${_fix}/non_ascii.h" non-ascii 1)
_lint_case("${_fix}/ctrl_ascii.h" CLEAN 0)
_lint_case("${_fix}/banned_call.c" banned-call 1)
if(NOT _last_output MATCHES "banned_call.c:4: banned-call")
    message("lint selftest: banned_call.c: finding not reported on line 4\n${_last_output}")
    set(_bad 1)
endif()
_lint_case("${_fix}/banned_token.c" banned-token 1)
_lint_case("${_fix}/banned_suffix.c" long-suffix 1)
_lint_case("${_fix}/cast_paren.c" result-cast 1)

# 3. Floating point is banned everywhere except src/state/tiebreak.c, the
# encoder's two files and the files that pass its rows through (decision 0022),
# and even there every other banned token still applies.
file(MAKE_DIRECTORY "${WORK}/fp/src/state")
file(WRITE "${WORK}/fp/src/state/tiebreak.c" "static double fixture_fp;
static float fixture_fp2;
")
_lint_case("${WORK}/fp/src/state/tiebreak.c" CLEAN 0 "${WORK}/fp")
file(WRITE "${WORK}/fp/src/state/tiebreak.c" "static double fixture_fp;
static long fixture_long;
")
_lint_case("${WORK}/fp/src/state/tiebreak.c" banned-token 1 "${WORK}/fp")
file(WRITE "${WORK}/fp/src/state/other.c" "static double fixture_fp;
static float fixture_fp2;
")
_lint_case("${WORK}/fp/src/state/other.c" banned-token 2 "${WORK}/fp")
# The encoder's two files (decision 0021) have the same exception, and nothing more:
# a float elsewhere, batch.c included, still fails.
file(MAKE_DIRECTORY "${WORK}/fp/src/encode" "${WORK}/fp/src/batch" "${WORK}/fp/include/duoforge")
file(WRITE "${WORK}/fp/src/encode/encode.c" "static double fixture_fp;
static float fixture_fp2;
")
_lint_case("${WORK}/fp/src/encode/encode.c" CLEAN 0 "${WORK}/fp")
file(WRITE "${WORK}/fp/src/encode/encode.c" "static float fixture_fp;
static long fixture_long;
")
_lint_case("${WORK}/fp/src/encode/encode.c" banned-token 1 "${WORK}/fp")
file(WRITE "${WORK}/fp/include/duoforge/duoforge_encode.h" "void fixture(float *obs);
")
_lint_case("${WORK}/fp/include/duoforge/duoforge_encode.h" CLEAN 0 "${WORK}/fp")
file(WRITE "${WORK}/fp/src/batch/batch.c" "static float fixture_fp;
")
_lint_case("${WORK}/fp/src/batch/batch.c" banned-token 1 "${WORK}/fp")
file(WRITE "${WORK}/fp/src/encode/other.c" "static float fixture_fp;
")
_lint_case("${WORK}/fp/src/encode/other.c" banned-token 1 "${WORK}/fp")
# The files that pass the encoder's rows through (decision 0022) have the same
# exception, and nothing more: a float in another file of src/search still fails.
file(MAKE_DIRECTORY "${WORK}/fp/src/search")
file(WRITE "${WORK}/fp/src/search/search.c" "static float *fixture_rows;
")
_lint_case("${WORK}/fp/src/search/search.c" CLEAN 0 "${WORK}/fp")
file(WRITE "${WORK}/fp/src/search/search.c" "static float *fixture_rows;
static unsigned fixture_word;
")
_lint_case("${WORK}/fp/src/search/search.c" banned-token 1 "${WORK}/fp")
file(WRITE "${WORK}/fp/include/duoforge/duoforge_search.h" "void fixture(float *obs);
")
_lint_case("${WORK}/fp/include/duoforge/duoforge_search.h" CLEAN 0 "${WORK}/fp")
file(WRITE "${WORK}/fp/src/encode/encode_internal.h" "void fixture(float *obs);
")
_lint_case("${WORK}/fp/src/encode/encode_internal.h" CLEAN 0 "${WORK}/fp")
file(WRITE "${WORK}/fp/src/search/other.c" "static float fixture_fp;
")
_lint_case("${WORK}/fp/src/search/other.c" banned-token 1 "${WORK}/fp")

if(_bad)
    message(FATAL_ERROR "LINT_SELFTEST FAILED")
endif()
message("LINT_SELFTEST OK (${_big_size}-byte clean file, 6 fixtures, 3 floating-point cases)")
