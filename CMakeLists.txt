cmake_minimum_required(VERSION 3.23)

project(duoforge VERSION 0.2.0 LANGUAGES C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

option(DUOFORGE_ENABLE_SANITIZERS
    "Enable AddressSanitizer and UndefinedBehaviorSanitizer for supported compilers"
    OFF
)
set(DUOFORGE_PCG_REFERENCE_DIR "" CACHE PATH
    "Optional checkout of pcg-c-basic at the pinned revision for reference tests")
set(DUOFORGE_PS_REFERENCE_DIR "" CACHE PATH
    "Optional checkout of Pokemon Showdown at the pinned revision for reference tests")

include(CTest)
include(cmake/DuoforgeTargetOptions.cmake)

add_library(duoforge STATIC
    src/duoforge.c
    src/core/alloc.c
    src/core/sha256.c
    src/core/modifier.c
    src/rng/pcg32_derived.c
    src/rng/pcg32.c
    src/rng/draw.c
    src/state/context.c
    src/state/identity.c
    src/state/knowledge.c
    src/state/closure_member.c
    src/state/invariants.c
    src/state/battle.c
    src/state/transition.c
    src/state/request.c
    src/state/observation.c
    src/data/closure_tables.c
    src/data/formulas.c
    src/data/support_manifest.c
    src/codec/state_codec.c
    src/combat/turn.c
)
target_include_directories(duoforge
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:include>"
    PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/src"
)
duoforge_configure_target(duoforge)

if(BUILD_TESTING)
    # C++ is optional and used only for the extern "C" link check.
    include(CheckLanguage)
    check_language(CXX)
    if(CMAKE_CXX_COMPILER)
        enable_language(CXX)
    endif()
    add_subdirectory(tests)
endif()
