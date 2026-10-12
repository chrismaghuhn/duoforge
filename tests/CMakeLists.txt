# DuoForge tests. Every test is finite and has an explicit timeout.

# duoforge_add_test(NAME <ctest name> SOURCES <files...> [WHITEBOX]
#                   [TIMEOUT <s>] [LABELS <labels...>] [LIBS <libs...>] [ARGS <arguments...>])
# The executable name is NAME with '.' replaced by '_'. WHITEBOX adds src/ to
# the include path so a test can exercise internal functions. ARGS are the
# command line arguments of the test.
function(duoforge_add_test)
    cmake_parse_arguments(T "WHITEBOX" "NAME;TIMEOUT" "SOURCES;LABELS;LIBS;ARGS" ${ARGN})
    if(NOT T_TIMEOUT)
        set(T_TIMEOUT 30)
    endif()
    string(REPLACE "." "_" _exe "${T_NAME}")
    add_executable(${_exe} ${T_SOURCES})
    target_link_libraries(${_exe} PRIVATE duoforge ${T_LIBS})
    if(TARGET duoforge_test_support)
        target_link_libraries(${_exe} PRIVATE duoforge_test_support)
    endif()
    target_include_directories(${_exe} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
    if(T_WHITEBOX)
        target_include_directories(${_exe} PRIVATE "${PROJECT_SOURCE_DIR}/src")
    endif()
    duoforge_configure_target(${_exe})
    add_test(NAME ${T_NAME} COMMAND ${_exe} ${T_ARGS})
    set_tests_properties(${T_NAME} PROPERTIES TIMEOUT ${T_TIMEOUT})
    if(T_LABELS)
        set_tests_properties(${T_NAME} PROPERTIES LABELS "${T_LABELS}")
    endif()
    if(DUOFORGE_ENABLE_SANITIZERS)
        # Never abort_on_error: CTest would report an abort even when the
        # expected output matched (docs/decisions/0003).
        set_tests_properties(${T_NAME} PROPERTIES ENVIRONMENT
            "ASAN_OPTIONS=detect_leaks=1;UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1")
    endif()
endfunction()

# Shared test support (explicit test context, no globals).
add_library(duoforge_test_support STATIC support/check.c support/fixtures.c support/goldens.c
            support/goldens_legacy.c support/team_c.c support/pool.c support/factored.c
            support/conformance_compare.c)
target_include_directories(duoforge_test_support PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")
# The F2 fixture builder and the conformance comparators are white-box.
target_include_directories(duoforge_test_support PRIVATE "${PROJECT_SOURCE_DIR}/src")
target_link_libraries(duoforge_test_support PUBLIC duoforge)
duoforge_configure_target(duoforge_test_support)

# Area registrations retain tests/ as their source and binary directory.
include(flow/tests.cmake)
include(mechanics/tests.cmake)
include(items/tests.cmake)
include(abilities/tests.cmake)
include(moves/tests.cmake)
include(forms/tests.cmake)
include(data/tests.cmake)
include(interactions/tests.cmake)

# The static columns have no engine reader (decision 0020 item 5): only the tables and the data query API name them.
add_test(NAME duoforge.data.static_unread
    COMMAND "${CMAKE_COMMAND}" "-DSRC_DIR=${PROJECT_SOURCE_DIR}/src" -P "${PROJECT_SOURCE_DIR}/cmake/checks/static_columns_unread.cmake")
set_tests_properties(duoforge.data.static_unread PROPERTIES TIMEOUT 30)
# The generated files must stay exactly what tools/datagen/gen_closure.py
# wrote; regenerate and update these hashes together.
foreach(_gen IN ITEMS
        "closure_tables.h=f6ef34b31d74a60f9c28e0bce8d3cc39a68a2ee03c7d17532090c9fca42fb25b"
        "closure_tables.c=490de42298e34cfd38192d979fd022367bf53693a5fa1855f1cc6ad034d8450a"
        "extended_tables.h=b2abef243fcbfdd87654940076b9fe2fe80b117d74893a7567741f26b9075a7d"
        "extended_tables.c=9e736fa467713283418c4edf8f56b8d844452e596ba422adbd52483d20f7cc17"
        "pool_tables.h=fc4601a46a561da76980f07fac072a642c575c5c22e19269de229f11cb271970"
        "pool_tables.c=08acc5eaae81972e88b65d4f106451366e5350f128534a3a5d301c681e9d7228")
    string(REPLACE "=" ";" _parts "${_gen}")
    list(GET _parts 0 _file)
    list(GET _parts 1 _expected)
    add_test(NAME duoforge.provenance.${_file}
        COMMAND "${CMAKE_COMMAND}"
            "-DFILE=${PROJECT_SOURCE_DIR}/src/data/${_file}"
            -DEXPECTED=${_expected}
            -P "${PROJECT_SOURCE_DIR}/cmake/checks/file_sha256.cmake")
    set_tests_properties(duoforge.provenance.${_file} PROPERTIES TIMEOUT 30)
endforeach()
# Optional: regenerate from a pinned Pokemon Showdown checkout and compare.
if(DUOFORGE_PS_REFERENCE_DIR)
    find_package(Python3 COMPONENTS Interpreter REQUIRED)
    include("${PROJECT_SOURCE_DIR}/tools/datagen/tests/regen.cmake")
    # The arithmetic reference values, recomputed by the pinned Showdown.
    find_program(DUOFORGE_NODE node)
    if(DUOFORGE_NODE)
        include("${PROJECT_SOURCE_DIR}/tools/reference/tests/pinned.cmake")
        include("${PROJECT_SOURCE_DIR}/tools/datagen/tests/families.cmake")
    endif()
endif()
# The conformance tables must be what the converter makes of the traces.
find_package(Python3 COMPONENTS Interpreter)
if(Python3_Interpreter_FOUND)
    include("${PROJECT_SOURCE_DIR}/tools/reference/tests/tests.cmake")
    # The AWS fuzz tooling (tools/cloud/aws_fuzz): its guards, the request, the user data and the policy text, offline,
    # with a stub aws first on the PATH. It needs a bash; on Windows that is Git's, not the WSL launcher in System32.
    if(WIN32)
        find_program(DUOFORGE_BASH NAMES bash HINTS "$ENV{ProgramFiles}/Git/bin" "$ENV{LocalAppData}/Programs/Git/bin"
            NO_DEFAULT_PATH)
    else()
        find_program(DUOFORGE_BASH NAMES bash)
    endif()
    if(DUOFORGE_BASH)
        add_test(NAME duoforge.cloud.aws_fuzz_guards
            COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/cloud/aws_fuzz/test_guards.py")
        set_tests_properties(duoforge.cloud.aws_fuzz_guards PROPERTIES TIMEOUT 300
            ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;DUOFORGE_BASH=${DUOFORGE_BASH}")
        include("${PROJECT_SOURCE_DIR}/tools/cloud/p1_pilot/tests/tests.cmake")
        # The Google Cloud watchdog (tools/cloud/gcp_watch): the same, with a stub gcloud and the round with stand-ins.
        add_test(NAME duoforge.cloud.gcp_watch_guards
            COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/cloud/gcp_watch/test_guards.py")
        set_tests_properties(duoforge.cloud.gcp_watch_guards PROPERTIES TIMEOUT 600
            ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;DUOFORGE_BASH=${DUOFORGE_BASH}")
    endif()
    include("${PROJECT_SOURCE_DIR}/tools/datagen/tests/tests.cmake")
endif()

# The vendored upstream license must stay byte-exact.
add_test(NAME duoforge.provenance.pcg_license
    COMMAND "${CMAKE_COMMAND}"
        "-DFILE=${PROJECT_SOURCE_DIR}/third_party/pcg-c-basic/LICENSE.txt"
        -DEXPECTED=b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1
        -P "${PROJECT_SOURCE_DIR}/cmake/checks/file_sha256.cmake")
set_tests_properties(duoforge.provenance.pcg_license PROPERTIES TIMEOUT 30)

include(flow/pcg.cmake)

# Header self-containment (build-time check).
add_library(duoforge_header_check OBJECT header_check/duoforge_h_twice.c)
target_link_libraries(duoforge_header_check PRIVATE duoforge)
duoforge_configure_target(duoforge_header_check)

# extern "C" link check from C++ (not with sanitizers: the C++ target does not
# get the sanitizer link flags).
if(CMAKE_CXX_COMPILER AND NOT DUOFORGE_ENABLE_SANITIZERS AND NOT DUOFORGE_ENABLE_TSAN)
    add_executable(duoforge_cxx_link header_check/cxx_link.cpp)
    target_link_libraries(duoforge_cxx_link PRIVATE duoforge_batch)
    set_target_properties(duoforge_cxx_link PROPERTIES
        CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON CXX_EXTENSIONS OFF)
    if(MSVC)
        target_compile_options(duoforge_cxx_link PRIVATE /W4 /permissive- /utf-8)
        if(DUOFORGE_WARNINGS_AS_ERRORS)
            target_compile_options(duoforge_cxx_link PRIVATE /WX)
        endif()
    else()
        target_compile_options(duoforge_cxx_link PRIVATE -Wall -Wextra -Wpedantic)
        if(DUOFORGE_WARNINGS_AS_ERRORS)
            target_compile_options(duoforge_cxx_link PRIVATE -Werror)
        endif()
    endif()
    add_test(NAME duoforge.api.cxx_link COMMAND duoforge_cxx_link)
    set_tests_properties(duoforge.api.cxx_link PROPERTIES TIMEOUT 30)
endif()

# The Python package (M7, decision 0013), run with DUOFORGE_PYTHON; without
# an interpreter each test reports skipped instead of passing silently.


include("${PROJECT_SOURCE_DIR}/python/tests/support/register.cmake")
include("${PROJECT_SOURCE_DIR}/python/tests/engine/tests.cmake")
include("${PROJECT_SOURCE_DIR}/python/tests/learn/tests.cmake")
include("${PROJECT_SOURCE_DIR}/python/tests/search/tests.cmake")
include("${PROJECT_SOURCE_DIR}/python/tests/live/tests.cmake")
include("${PROJECT_SOURCE_DIR}/python/tests/replay/tests.cmake")
include("${PROJECT_SOURCE_DIR}/python/tests/data/tests.cmake")

include("${PROJECT_SOURCE_DIR}/tools/reference/tests/random_teams.cmake")

# The learner pipeline (decisions 0014, 0017) needs JAX: DUOFORGE_LEARN_PYTHON.

# Source lint and its self-test.
add_test(NAME duoforge.lint.sources
    COMMAND "${CMAKE_COMMAND}" "-DROOT=${PROJECT_SOURCE_DIR}"
        -P "${PROJECT_SOURCE_DIR}/cmake/checks/lint_sources.cmake")
add_test(NAME duoforge.lint.selftest
    COMMAND "${CMAKE_COMMAND}" "-DROOT=${PROJECT_SOURCE_DIR}"
        "-DWORK=${CMAKE_CURRENT_BINARY_DIR}/lint_selftest"
        -P "${PROJECT_SOURCE_DIR}/cmake/checks/lint_selftest.cmake")
set_tests_properties(duoforge.lint.sources PROPERTIES TIMEOUT 60)
set_tests_properties(duoforge.lint.selftest PROPERTIES TIMEOUT 60)

# No writable static storage in the library (ELF toolchains only).
add_test(NAME duoforge.lint.no_mutable_globals
    COMMAND "${CMAKE_COMMAND}" "-DOBJDUMP=${CMAKE_OBJDUMP}" "-DLIB=$<TARGET_FILE:duoforge>"
        "-DSANITIZERS=${DUOFORGE_ENABLE_SANITIZERS}"
        -P "${PROJECT_SOURCE_DIR}/cmake/checks/no_mutable_globals.cmake")
set_tests_properties(duoforge.lint.no_mutable_globals PROPERTIES
    TIMEOUT 60 SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")

# Sanitizer liveness canaries.
if(DUOFORGE_ENABLE_SANITIZERS)
    foreach(_c IN ITEMS ubsan asan)
        add_executable(duoforge_canary_${_c} canary/canary_${_c}.c)
        duoforge_configure_target(duoforge_canary_${_c})
        add_test(NAME duoforge.sanitizer.canary_${_c} COMMAND duoforge_canary_${_c})
    endforeach()
    # In optimized builds UBSan's object-size check would abort before ASan
    # reports; the ASan canary must prove ASan alone.
    target_compile_options(duoforge_canary_asan PRIVATE -fno-sanitize=undefined)
    # halt_on_error=0 is mandatory: only the compile flag
    # -fno-sanitize-recover=all may stop this canary.
    set_tests_properties(duoforge.sanitizer.canary_ubsan PROPERTIES
        TIMEOUT 30 LABELS sanitizer-canary
        ENVIRONMENT "UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=0"
        PASS_REGULAR_EXPRESSION "runtime error: signed integer overflow"
        FAIL_REGULAR_EXPRESSION "CANARY_SURVIVED")
    set_tests_properties(duoforge.sanitizer.canary_asan PROPERTIES
        TIMEOUT 30 LABELS sanitizer-canary
        ENVIRONMENT "ASAN_OPTIONS=detect_leaks=0"
        PASS_REGULAR_EXPRESSION "AddressSanitizer: heap-buffer-overflow"
        FAIL_REGULAR_EXPRESSION "CANARY_SURVIVED")
endif()
include("${PROJECT_SOURCE_DIR}/tools/state_model/tests/tests.cmake")
