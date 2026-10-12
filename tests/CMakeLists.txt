# DuoForge tests. Every test is finite and has an explicit timeout.
include(support/labels.cmake)

# duoforge_add_test(NAME <ctest name> SOURCES <files...> [WHITEBOX]
#                   [TIMEOUT <s>] TIER <tier> AREA <area> [LABELS <selectors...>] [LIBS <libs...>] [ARGS <arguments...>])
# The executable name is NAME with '.' replaced by '_'. WHITEBOX adds src/ to
# the include path so a test can exercise internal functions. ARGS are the
# command line arguments of the test.
function(duoforge_add_test)
    cmake_parse_arguments(T "WHITEBOX" "NAME;TIMEOUT;TIER;AREA" "SOURCES;LABELS;LIBS;ARGS" ${ARGN})
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
    duoforge_label_test("${T_NAME}" "${T_TIER}" "${T_AREA}" ${T_LABELS})
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
            support/conformance_compare.c support/reference_digest.c)
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

include("${PROJECT_SOURCE_DIR}/tests/data/provenance.cmake")
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
        include("${PROJECT_SOURCE_DIR}/tools/cloud/aws_fuzz/tests.cmake")
        include("${PROJECT_SOURCE_DIR}/tools/cloud/p1_pilot/tests/tests.cmake")
        include("${PROJECT_SOURCE_DIR}/tools/cloud/gcp_watch/tests.cmake")
    endif()
    include("${PROJECT_SOURCE_DIR}/tools/datagen/tests/tests.cmake")
endif()

include("${PROJECT_SOURCE_DIR}/tests/data/license.cmake")
include(flow/pcg.cmake)

include("${PROJECT_SOURCE_DIR}/tests/header_check/tests.cmake")
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

include("${PROJECT_SOURCE_DIR}/cmake/checks/tests.cmake")
include("${PROJECT_SOURCE_DIR}/tests/canary/tests.cmake")
include("${PROJECT_SOURCE_DIR}/tools/state_model/tests/tests.cmake")
