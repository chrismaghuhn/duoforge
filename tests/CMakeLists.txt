# DuoForge tests. Every test is finite and has an explicit timeout.

# duoforge_add_test(NAME <ctest name> SOURCES <files...> [WHITEBOX]
#                   [TIMEOUT <s>] [LABELS <labels...>] [LIBS <libs...>])
# The executable name is NAME with '.' replaced by '_'. WHITEBOX adds src/ to
# the include path so a test can exercise internal functions.
function(duoforge_add_test)
    cmake_parse_arguments(T "WHITEBOX" "NAME;TIMEOUT" "SOURCES;LABELS;LIBS" ${ARGN})
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
    add_test(NAME ${T_NAME} COMMAND ${_exe})
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
            support/goldens_legacy.c support/team_c.c support/factored.c)
target_include_directories(duoforge_test_support PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")
# The F2 fixture builder is white-box.
target_include_directories(duoforge_test_support PRIVATE "${PROJECT_SOURCE_DIR}/src")
target_link_libraries(duoforge_test_support PUBLIC duoforge)
duoforge_configure_target(duoforge_test_support)

duoforge_add_test(NAME duoforge.unit.arith SOURCES test_arith.c WHITEBOX)
duoforge_add_test(NAME duoforge.unit.sha256 SOURCES test_sha256.c WHITEBOX)
duoforge_add_test(NAME duoforge.unit.modifier SOURCES test_modifier.c WHITEBOX)

duoforge_add_test(NAME duoforge.rng.kat SOURCES test_rng_kat.c WHITEBOX)
duoforge_add_test(NAME duoforge.rng.contract SOURCES test_rng_contract.c WHITEBOX)

duoforge_add_test(NAME duoforge.state.context SOURCES test_context.c)
duoforge_add_test(NAME duoforge.state.setup SOURCES test_setup.c WHITEBOX)
duoforge_add_test(NAME duoforge.state.identity SOURCES test_identity.c WHITEBOX)
duoforge_add_test(NAME duoforge.state.knowledge SOURCES test_knowledge.c WHITEBOX)
duoforge_add_test(NAME duoforge.state.closure_setup SOURCES test_closure_setup.c WHITEBOX)
duoforge_add_test(NAME duoforge.state.invariants SOURCES test_invariants.c WHITEBOX)
duoforge_add_test(NAME duoforge.state.setup_sweep SOURCES test_setup_sweep.c TIMEOUT 60)

duoforge_add_test(NAME duoforge.state.clone_equal SOURCES test_clone_equal.c WHITEBOX)
duoforge_add_test(NAME duoforge.codec.golden SOURCES test_codec_golden.c WHITEBOX)
duoforge_add_test(NAME duoforge.codec.negative SOURCES test_codec_negative.c WHITEBOX)
duoforge_add_test(NAME duoforge.codec.mutation SOURCES test_codec_mutation.c WHITEBOX TIMEOUT 180)
duoforge_add_test(NAME duoforge.api.atomicity SOURCES test_api_atomicity.c WHITEBOX)

# M2: requests, joint commands, step, contract minimum tests.
duoforge_add_test(NAME duoforge.request.domain SOURCES test_request_domain.c WHITEBOX TIMEOUT 60)
duoforge_add_test(NAME duoforge.request.step SOURCES test_step.c WHITEBOX TIMEOUT 60)
duoforge_add_test(NAME duoforge.request.contract SOURCES test_contract.c WHITEBOX TIMEOUT 60)
duoforge_add_test(NAME duoforge.request.information SOURCES test_information.c WHITEBOX TIMEOUT 60)
duoforge_add_test(NAME duoforge.request.accepts SOURCES test_step_accepts.c TIMEOUT 120)
duoforge_add_test(NAME duoforge.request.query_checks SOURCES test_query_checks.c WHITEBOX)
duoforge_add_test(NAME duoforge.request.candidates_digest SOURCES test_candidates_digest.c TIMEOUT 120)
duoforge_add_test(NAME duoforge.batch.equivalence SOURCES test_batch.c LIBS duoforge_batch TIMEOUT 300)
duoforge_add_test(NAME duoforge.api.reference SOURCES test_reference_api.c)
duoforge_add_test(NAME duoforge.batch.step_indices SOURCES test_batch_indices.c LIBS duoforge_batch TIMEOUT 300)
duoforge_add_test(NAME duoforge.request.factored SOURCES test_factored.c TIMEOUT 120)
duoforge_add_test(NAME duoforge.batch.step_factored SOURCES test_batch_factored.c LIBS duoforge_batch TIMEOUT 300)
duoforge_add_test(NAME duoforge.batch.step_query SOURCES test_batch_step_query.c LIBS duoforge_batch TIMEOUT 300)

# Combat closure: battles recorded from the pinned reference, replayed with
# their draws as a tape (tests/reference/conformance.h is generated by
# tools/reference/trace_to_c.py from the committed traces).
duoforge_add_test(NAME duoforge.reference.conformance SOURCES test_conformance.c WHITEBOX TIMEOUT 60)
# Team C (decision 0009): the same driver over tests/reference/conformance_team_c.h.
duoforge_add_test(NAME duoforge.reference.conformance_team_c SOURCES test_conformance.c WHITEBOX TIMEOUT 60)
target_compile_definitions(duoforge_reference_conformance_team_c PRIVATE DF_CONFORMANCE_TEAM_C)
duoforge_add_test(NAME duoforge.combat.turn SOURCES test_turn.c WHITEBOX TIMEOUT 120)
duoforge_add_test(NAME duoforge.combat.closure_gate SOURCES test_closure_gate.c WHITEBOX TIMEOUT 600)

# M3: generated closure tables and Champions formulas (decision 0006).
duoforge_add_test(NAME duoforge.data.closure_tables SOURCES test_closure_tables.c WHITEBOX)
# Team C (decision 0009): the extended tables, whose prefix is the closure.
duoforge_add_test(NAME duoforge.data.extended_tables SOURCES test_extended_tables.c WHITEBOX)
duoforge_add_test(NAME duoforge.state.team_c_setup SOURCES test_team_c_setup.c WHITEBOX)
# The generated files must stay exactly what tools/datagen/gen_closure.py
# wrote; regenerate and update these hashes together.
foreach(_gen IN ITEMS
        "closure_tables.h=f6ef34b31d74a60f9c28e0bce8d3cc39a68a2ee03c7d17532090c9fca42fb25b"
        "closure_tables.c=490de42298e34cfd38192d979fd022367bf53693a5fa1855f1cc6ad034d8450a"
        "extended_tables.h=b2abef243fcbfdd87654940076b9fe2fe80b117d74893a7567741f26b9075a7d"
        "extended_tables.c=9e736fa467713283418c4edf8f56b8d844452e596ba422adbd52483d20f7cc17")
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
    add_test(NAME duoforge.data.closure_regen
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/gen_closure.py"
            "${DUOFORGE_PS_REFERENCE_DIR}" --check)
    set_tests_properties(duoforge.data.closure_regen PROPERTIES TIMEOUT 120 LABELS reference)
    add_test(NAME duoforge.data.extended_regen
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/gen_closure.py"
            "${DUOFORGE_PS_REFERENCE_DIR}" --team-c --check)
    set_tests_properties(duoforge.data.extended_regen PROPERTIES TIMEOUT 120 LABELS reference)
    # The arithmetic reference values, recomputed by the pinned Showdown.
    find_program(DUOFORGE_NODE node)
    if(DUOFORGE_NODE)
        add_test(NAME duoforge.reference.arith
            COMMAND "${DUOFORGE_NODE}" "${PROJECT_SOURCE_DIR}/tools/reference/arith_ref.js"
                "${DUOFORGE_PS_REFERENCE_DIR}" --check "${CMAKE_CURRENT_SOURCE_DIR}/reference/arith_ref.h")
        set_tests_properties(duoforge.reference.arith PROPERTIES TIMEOUT 120 LABELS reference)
        # Every committed battle trace is reproduced by the pinned Showdown.
        file(GLOB _specs "${CMAKE_CURRENT_SOURCE_DIR}/reference/specs/*.json")
        foreach(_spec IN LISTS _specs)
            get_filename_component(_name "${_spec}" NAME_WE)
            add_test(NAME duoforge.reference.trace.${_name}
                COMMAND "${DUOFORGE_NODE}" "${PROJECT_SOURCE_DIR}/tools/reference/ps_trace.js"
                    "${DUOFORGE_PS_REFERENCE_DIR}" "${_spec}"
                    --check "${CMAKE_CURRENT_SOURCE_DIR}/reference/traces/${_name}.json")
            set_tests_properties(duoforge.reference.trace.${_name} PROPERTIES TIMEOUT 120 LABELS reference)
        endforeach()
    endif()
endif()
# The conformance tables must be what the converter makes of the traces.
find_package(Python3 COMPONENTS Interpreter)
if(Python3_Interpreter_FOUND)
    add_test(NAME duoforge.reference.conformance_tables
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/trace_to_c.py"
            "${PROJECT_SOURCE_DIR}" --check)
    set_tests_properties(duoforge.reference.conformance_tables PROPERTIES TIMEOUT 60)
    # The table generator refuses move shapes it does not model (no checkout needed).
    add_test(NAME duoforge.data.gen_closure_refusals
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/test_gen_closure.py")
    set_tests_properties(duoforge.data.gen_closure_refusals PROPERTIES TIMEOUT 60
        ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
endif()

# The vendored upstream license must stay byte-exact.
add_test(NAME duoforge.provenance.pcg_license
    COMMAND "${CMAKE_COMMAND}"
        "-DFILE=${PROJECT_SOURCE_DIR}/third_party/pcg-c-basic/LICENSE.txt"
        -DEXPECTED=b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1
        -P "${PROJECT_SOURCE_DIR}/cmake/checks/file_sha256.cmake")
set_tests_properties(duoforge.provenance.pcg_license PROPERTIES TIMEOUT 30)

# Optional reference tests against a pinned pcg-c-basic checkout.
if(DUOFORGE_PCG_REFERENCE_DIR)
    set(_ref "${DUOFORGE_PCG_REFERENCE_DIR}")
    foreach(_pin IN ITEMS
            "pcg_basic.c=b6582a071a8a090a293621523c063d125a532d772a2a1eb7d60b3e695fe47746"
            "pcg_basic.h=cd823ddc225da9be520a54f13ef2c491506c353800cae04e8b673b2de58f2cc4")
        string(REPLACE "=" ";" _parts "${_pin}")
        list(GET _parts 0 _file)
        list(GET _parts 1 _expected)
        if(NOT EXISTS "${_ref}/${_file}")
            message(FATAL_ERROR "DUOFORGE_PCG_REFERENCE_DIR: ${_ref}/${_file} not found")
        endif()
        file(SHA256 "${_ref}/${_file}" _actual)
        if(NOT _actual STREQUAL _expected)
            message(FATAL_ERROR "DUOFORGE_PCG_REFERENCE_DIR: ${_file} sha256 ${_actual} != pinned ${_expected}")
        endif()
    endforeach()
    # Isolated third-party build: the pinned upstream code is not
    # warning-clean under the project flag set, so it never gets it.
    add_library(duoforge_pcg_reference STATIC "${_ref}/pcg_basic.c")
    set_target_properties(duoforge_pcg_reference PROPERTIES
        C_STANDARD 17 C_STANDARD_REQUIRED ON C_EXTENSIONS OFF)
    target_include_directories(duoforge_pcg_reference SYSTEM PUBLIC "${_ref}")
    if(DUOFORGE_ENABLE_SANITIZERS)
        target_compile_options(duoforge_pcg_reference PRIVATE -fsanitize=address,undefined)
    endif()

    add_executable(duoforge_gen_pcg32_kat "${PROJECT_SOURCE_DIR}/tools/kat/gen_pcg32_kat.c")
    target_link_libraries(duoforge_gen_pcg32_kat PRIVATE duoforge_pcg_reference)
    duoforge_configure_target(duoforge_gen_pcg32_kat)
    add_test(NAME duoforge.rng.kat_regen
        COMMAND "${CMAKE_COMMAND}" "-DGEN=$<TARGET_FILE:duoforge_gen_pcg32_kat>"
            "-DOUT=${CMAKE_CURRENT_BINARY_DIR}/pcg32_kat_vectors.h"
            "-DEXPECTED=${CMAKE_CURRENT_SOURCE_DIR}/data/pcg32_kat_vectors.h"
            -P "${PROJECT_SOURCE_DIR}/cmake/checks/kat_regen.cmake")
    set_tests_properties(duoforge.rng.kat_regen PROPERTIES TIMEOUT 120 LABELS reference)

    duoforge_add_test(NAME duoforge.rng.reference_differential
        SOURCES test_rng_reference_differential.c WHITEBOX
        TIMEOUT 120 LABELS reference LIBS duoforge_pcg_reference)
endif()

# Black-box smoke test (M0), kept under its original name.
add_executable(duoforge_smoke_test smoke_test.c)
target_link_libraries(duoforge_smoke_test PRIVATE duoforge)
duoforge_configure_target(duoforge_smoke_test)
add_test(NAME duoforge_smoke_test COMMAND duoforge_smoke_test)
set_tests_properties(duoforge_smoke_test PROPERTIES TIMEOUT 30)

# Header self-containment (build-time check).
add_library(duoforge_header_check OBJECT header_check/duoforge_h_twice.c)
target_link_libraries(duoforge_header_check PRIVATE duoforge)
duoforge_configure_target(duoforge_header_check)

# extern "C" link check from C++ (not with sanitizers: the C++ target does not
# get the sanitizer link flags).
if(CMAKE_CXX_COMPILER AND NOT DUOFORGE_ENABLE_SANITIZERS AND NOT DUOFORGE_ENABLE_TSAN)
    add_executable(duoforge_cxx_link header_check/cxx_link.cpp)
    target_link_libraries(duoforge_cxx_link PRIVATE duoforge)
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
foreach(_py layout lib equivalence recipes policies_features example learn_numpy)
    if(DUOFORGE_PYTHON)
        add_test(NAME duoforge.python.${_py}
            COMMAND "${DUOFORGE_PYTHON}" -m unittest -v python.tests.test_${_py}
            WORKING_DIRECTORY "${PROJECT_SOURCE_DIR}")
        set_tests_properties(duoforge.python.${_py} PROPERTIES LABELS python TIMEOUT 600 ENVIRONMENT
            "DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;DUOFORGE_LAYOUT_DUMP=$<TARGET_FILE:duoforge_layout_dump>;PYTHONPATH=${PROJECT_SOURCE_DIR}/python;PYTHONDONTWRITEBYTECODE=1")
    else()
        add_test(NAME duoforge.python.${_py}
            COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: DUOFORGE_PYTHON is empty")
        set_tests_properties(duoforge.python.${_py} PROPERTIES LABELS python
            SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
    endif()
endforeach()

# The learner pipeline (decision 0014) needs JAX: DUOFORGE_LEARN_PYTHON.
if(DUOFORGE_LEARN_PYTHON)
    add_test(NAME duoforge.python.learn
        COMMAND "${DUOFORGE_LEARN_PYTHON}" -m unittest -v python.tests.test_learn
        WORKING_DIRECTORY "${PROJECT_SOURCE_DIR}")
    set_tests_properties(duoforge.python.learn PROPERTIES LABELS "python;learn" TIMEOUT 900 ENVIRONMENT
        "DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;PYTHONPATH=${PROJECT_SOURCE_DIR}/python;PYTHONDONTWRITEBYTECODE=1")
else()
    add_test(NAME duoforge.python.learn
        COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: DUOFORGE_LEARN_PYTHON is empty")
    set_tests_properties(duoforge.python.learn PROPERTIES LABELS "python;learn"
        SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
endif()

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
