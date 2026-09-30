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
if(CMAKE_CXX_COMPILER AND NOT DUOFORGE_ENABLE_SANITIZERS)
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
