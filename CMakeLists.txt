cmake_minimum_required(VERSION 3.23)

project(duoforge VERSION 0.1.0 LANGUAGES C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

option(DUOFORGE_ENABLE_SANITIZERS
    "Enable AddressSanitizer and UndefinedBehaviorSanitizer for supported compilers"
    OFF
)

include(CTest)

function(duoforge_enable_warnings target)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /permissive-)
    elseif(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang|AppleClang")
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
    endif()
endfunction()

function(duoforge_enable_sanitizers target)
    if(NOT DUOFORGE_ENABLE_SANITIZERS)
        return()
    endif()

    if(MSVC)
        message(FATAL_ERROR
            "DUOFORGE_ENABLE_SANITIZERS requires GCC or Clang in this project"
        )
    elseif(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang|AppleClang")
        target_compile_options(${target} PRIVATE
            -fsanitize=address,undefined
            -fno-omit-frame-pointer
        )
    else()
        message(FATAL_ERROR
            "DUOFORGE_ENABLE_SANITIZERS is unsupported by this C compiler"
        )
    endif()
endfunction()

add_library(duoforge STATIC
    src/duoforge.c
)
target_include_directories(duoforge PUBLIC
    "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
    "$<INSTALL_INTERFACE:include>"
)
duoforge_enable_warnings(duoforge)
duoforge_enable_sanitizers(duoforge)

if(BUILD_TESTING)
    add_executable(duoforge_smoke_test
        tests/smoke_test.c
    )
    target_link_libraries(duoforge_smoke_test PRIVATE duoforge)
    duoforge_enable_warnings(duoforge_smoke_test)
    duoforge_enable_sanitizers(duoforge_smoke_test)

    if(DUOFORGE_ENABLE_SANITIZERS)
        target_link_options(duoforge_smoke_test PRIVATE
            -fsanitize=address,undefined
        )
    endif()

    add_test(NAME duoforge_smoke_test COMMAND duoforge_smoke_test)
endif()
