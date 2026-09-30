# pokemon-doubles-core — M0 build foundation.
#
# 3.21 is the declared minimum because the presets use schema version 3 and
# CMake needs to know MSVC's C17 mode. Only CMake 3.28.3 has actually been
# exercised; see README.md for the verified toolchains.
cmake_minimum_required(VERSION 3.21)

# The public header is the single source of truth for the version.
file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/include/pbd/version.h" _pbd_version_lines
    REGEX "^#define PBD_VERSION_(MAJOR|MINOR|PATCH) [0-9]+$")
foreach(_pbd_part IN ITEMS MAJOR MINOR PATCH)
    string(REGEX MATCH "#define PBD_VERSION_${_pbd_part} ([0-9]+)" _pbd_match "${_pbd_version_lines}")
    if(NOT _pbd_match)
        message(FATAL_ERROR "Cannot parse PBD_VERSION_${_pbd_part} from include/pbd/version.h")
    endif()
    set(_pbd_version_${_pbd_part} "${CMAKE_MATCH_1}")
endforeach()

project(pokemon_doubles_core
    VERSION "${_pbd_version_MAJOR}.${_pbd_version_MINOR}.${_pbd_version_PATCH}"
    DESCRIPTION "Headless deterministic Pokemon doubles battle core (M0 foundation only)"
    LANGUAGES C)

option(PBD_BUILD_TESTS "Build and register pbd tests" ${PROJECT_IS_TOP_LEVEL})
option(PBD_WARNINGS_AS_ERRORS "Treat compiler warnings as errors" OFF)

set(CMAKE_C_EXTENSIONS OFF)

list(APPEND CMAKE_MODULE_PATH "${PROJECT_SOURCE_DIR}/cmake")
include(PbdCompilerOptions)

add_library(pbd_core STATIC
    src/version.c)
add_library(pbd::core ALIAS pbd_core)
target_include_directories(pbd_core PUBLIC
    "$<BUILD_INTERFACE:${PROJECT_SOURCE_DIR}/include>")
target_compile_features(pbd_core PUBLIC c_std_17)
set_target_properties(pbd_core PROPERTIES
    C_STANDARD 17
    C_STANDARD_REQUIRED ON
    C_EXTENSIONS OFF)
pbd_configure_target(pbd_core)

if(PBD_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()
