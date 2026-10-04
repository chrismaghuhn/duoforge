cmake_minimum_required(VERSION 3.23)

project(duoforge VERSION 0.2.0 LANGUAGES C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

option(DUOFORGE_ENABLE_SANITIZERS
    "Enable AddressSanitizer and UndefinedBehaviorSanitizer for supported compilers"
    OFF
)
option(DUOFORGE_ENABLE_TSAN
    "Enable ThreadSanitizer (GCC/Clang) for the batch runtime's tests"
    OFF
)
if(DUOFORGE_ENABLE_TSAN AND DUOFORGE_ENABLE_SANITIZERS)
    message(FATAL_ERROR "duoforge: DUOFORGE_ENABLE_TSAN and DUOFORGE_ENABLE_SANITIZERS cannot be combined")
endif()
option(DUOFORGE_ENABLE_IPO
    "Link-time optimization of Release builds; the library then links only with the same toolchain"
    OFF
)
set(DUOFORGE_PCG_REFERENCE_DIR "" CACHE PATH
    "Optional checkout of pcg-c-basic at the pinned revision for reference tests")
set(DUOFORGE_PS_REFERENCE_DIR "" CACHE PATH
    "Optional checkout of Pokemon Showdown at the pinned revision for reference tests")

include(CTest)
include(cmake/DuoforgeTargetOptions.cmake)

# Link-time optimization of Release builds, opt-in (decision 0008 section 8):
# LTO objects are compiler-specific, so a library built with them links only
# with the same toolchain. GCC builds fat objects (machine code next to the
# LTO data) so that the binary checks still see the code. A toolchain that
# cannot do it fails the configuration instead of building without it.
set(DUOFORGE_IPO OFF)
if(DUOFORGE_ENABLE_IPO)
    if(DUOFORGE_ENABLE_SANITIZERS OR DUOFORGE_ENABLE_TSAN)
        message(FATAL_ERROR "duoforge: DUOFORGE_ENABLE_IPO cannot be combined with a sanitizer")
    endif()
    include(CheckIPOSupported)
    check_ipo_supported(RESULT _duoforge_ipo_ok OUTPUT _duoforge_ipo_output LANGUAGES C)
    if(NOT _duoforge_ipo_ok)
        message(FATAL_ERROR "duoforge: no link-time optimization with this toolchain: ${_duoforge_ipo_output}")
    endif()
    set(DUOFORGE_IPO_FAT OFF)
    if(CMAKE_C_COMPILER_ID STREQUAL "GNU")
        set(CMAKE_C_COMPILE_OPTIONS_IPO -flto=auto -ffat-lto-objects)
        set(DUOFORGE_IPO_FAT ON)
    elseif(CMAKE_C_COMPILER_ID STREQUAL "Clang" AND NOT CMAKE_C_SIMULATE_ID STREQUAL "MSVC")
        include(CheckCCompilerFlag)
        check_c_compiler_flag("-flto=thin -ffat-lto-objects" DUOFORGE_C_FAT_LTO)
        if(DUOFORGE_C_FAT_LTO)
            set(CMAKE_C_COMPILE_OPTIONS_IPO -flto=thin -ffat-lto-objects)
            set(DUOFORGE_IPO_FAT ON)
        endif()
    endif()
    set(CMAKE_INTERPROCEDURAL_OPTIMIZATION_RELEASE ON)
    set(DUOFORGE_IPO ON)
endif()

set(DUOFORGE_SOURCES
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
    src/state/data_query.c
    src/state/invariants.c
    src/state/battle.c
    src/state/transition.c
    src/state/request.c
    src/state/reference_teams.c
    src/state/observation.c
    src/state/tiebreak.c
    src/data/closure_tables.c
    src/data/extended_tables.c
    src/data/pool_tables.c
    src/data/formulas.c
    src/data/support_manifest.c
    src/codec/state_codec.c
    src/combat/events.c
    src/combat/turn.c
)
# The tiebreak (src/state/tiebreak.c) reproduces the reference's binary64 arithmetic
# bit for bit: nothing may contract into a fused multiply-add. GCC's ISO modes
# default to that, Clang and MSVC are told in the file; this states it for GCC
# and Clang whatever the language mode (no -ffast-math is used anywhere).
if(NOT MSVC)
    set_source_files_properties(src/state/tiebreak.c PROPERTIES COMPILE_OPTIONS "-ffp-contract=off")
endif()
add_library(duoforge STATIC ${DUOFORGE_SOURCES})
target_include_directories(duoforge
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:include>"
    PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/src"
)
duoforge_configure_target(duoforge)

# Batch runtime (decision 0012): a separate library over the public API,
# with its worker threads.
find_package(Threads REQUIRED)
set(DUOFORGE_BATCH_SOURCES
    src/batch/pool.c
    src/batch/batch.c
    src/encode/encode.c
    src/search/search.c
    src/state/view.c
)
# The encoder (src/encode/encode.c, decision 0021) is byte-equal to the reference's float32
# encoder: as for the tiebreak, nothing may contract into a fused multiply-add.
if(NOT MSVC)
    set_source_files_properties(src/encode/encode.c PROPERTIES COMPILE_OPTIONS "-ffp-contract=off")
endif()
add_library(duoforge_batch STATIC ${DUOFORGE_BATCH_SOURCES})
target_include_directories(duoforge_batch PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src")
target_link_libraries(duoforge_batch PUBLIC duoforge Threads::Threads)
duoforge_configure_target(duoforge_batch)

# The shared library of the Python package (M7, decision 0013): the core and
# the batch runtime in one module, every function exported.
add_library(duoforge_shared SHARED ${DUOFORGE_SOURCES} ${DUOFORGE_BATCH_SOURCES})
target_include_directories(duoforge_shared
    PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include"
    PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src")
target_link_libraries(duoforge_shared PRIVATE Threads::Threads)
set_target_properties(duoforge_shared PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    WINDOWS_EXPORT_ALL_SYMBOLS ON)
if(MSVC)
    # WINDOWS_EXPORT_ALL_SYMBOLS reads the objects' symbol tables, which
    # /GL objects do not have: link-time code generation stays off here (the
    # per-configuration property overrides the general one).
    set_target_properties(duoforge_shared PROPERTIES
        INTERPROCEDURAL_OPTIMIZATION OFF
        INTERPROCEDURAL_OPTIMIZATION_RELEASE OFF)
endif()
duoforge_configure_target(duoforge_shared)

# The struct layouts and constants as JSON, for the Python layout test.
add_executable(duoforge_layout_dump tools/layout/layout_dump.c)
target_include_directories(duoforge_layout_dump PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/include")
duoforge_configure_target(duoforge_layout_dump)

set(DUOFORGE_PYTHON "" CACHE FILEPATH
    "Python 3.10+ with NumPy 2 for the duoforge.python tests (empty: the tests report skipped)")
set(DUOFORGE_LEARN_PYTHON "" CACHE FILEPATH
    "Python with JAX and optax for duoforge.python.learn (decision 0014; empty: the test reports skipped)")

if(BUILD_TESTING)
    # C++ is optional and used only for the extern "C" link check.
    include(CheckLanguage)
    check_language(CXX)
    if(CMAKE_CXX_COMPILER)
        enable_language(CXX)
        # Without fat objects the library holds only LTO data of the C compiler.
        if(DUOFORGE_IPO AND NOT DUOFORGE_IPO_FAT AND NOT CMAKE_CXX_COMPILER_ID STREQUAL CMAKE_C_COMPILER_ID)
            message(FATAL_ERROR "duoforge: DUOFORGE_ENABLE_IPO needs the C++ compiler of the same toolchain "
                                "(C: ${CMAKE_C_COMPILER_ID}, C++: ${CMAKE_CXX_COMPILER_ID})")
        endif()
    endif()
    add_subdirectory(tests)
    option(DUOFORGE_BUILD_BENCH "Build the benchmark API and driver (with the tests)" ON)
    if(DUOFORGE_BUILD_BENCH)
        add_subdirectory(bench)
    endif()
    add_subdirectory(certify)
    add_subdirectory(tools/difftest)
endif()
