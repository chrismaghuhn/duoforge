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
    duoforge_label_test(duoforge.rng.kat_regen quick flow ci-rng-reference)
    set_tests_properties(duoforge.rng.kat_regen PROPERTIES TIMEOUT 120)

    duoforge_add_test(NAME duoforge.rng.reference_differential
        SOURCES flow/test_rng_reference_differential.c WHITEBOX
        TIMEOUT 120 LABELS ci-rng-reference LIBS duoforge_pcg_reference TIER quick AREA flow)
endif()
