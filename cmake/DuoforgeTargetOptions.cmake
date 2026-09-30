# Compiler-specific warning and sanitizer settings for DuoForge targets.
#
# Flags are chosen per compiler front end. MSVC and clang-cl get MSVC-style
# options; GCC and Clang get GCC-style options. Settings are applied per
# target, never through global flags. See docs/decisions/0003.
#
# The warning set is NOT a proof of integer-promotion safety: neither GCC nor
# Clang diagnoses a cast applied to a promoted result, and Clang has no
# -Warith-conversion. Promotion safety relies on review, the source lint and
# extreme-value tests under GCC UBSan (docs/decisions/0003).

option(DUOFORGE_WARNINGS_AS_ERRORS "Treat compiler warnings as errors" OFF)

function(duoforge_configure_target target)
    get_target_property(_type ${target} TYPE)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /permissive- /utf-8)
        if(DUOFORGE_WARNINGS_AS_ERRORS)
            target_compile_options(${target} PRIVATE /WX)
        endif()
        if(DUOFORGE_ENABLE_SANITIZERS)
            message(FATAL_ERROR "DUOFORGE_ENABLE_SANITIZERS requires GCC or Clang in this project")
        endif()
    elseif(CMAKE_C_COMPILER_ID MATCHES "^(GNU|Clang|AppleClang)$")
        target_compile_options(${target} PRIVATE
            -Wall
            -Wextra
            -Wpedantic
            -Wconversion
            -Wsign-conversion
            -Wshadow
            -Wstrict-prototypes
            -Wmissing-prototypes
            -Wcast-qual
            -Wvla
            -Wundef
            -Wformat=2
            -Wimplicit-fallthrough)
        if(CMAKE_C_COMPILER_ID STREQUAL "GNU")
            target_compile_options(${target} PRIVATE -Warith-conversion)
        endif()
        if(DUOFORGE_WARNINGS_AS_ERRORS)
            target_compile_options(${target} PRIVATE -Werror)
        endif()
        if(DUOFORGE_ENABLE_SANITIZERS)
            target_compile_options(${target} PRIVATE
                -fsanitize=address,undefined
                -fno-sanitize-recover=all
                -fno-omit-frame-pointer)
            # Link options have no effect on static libraries.
            if(_type STREQUAL "EXECUTABLE")
                target_link_options(${target} PRIVATE -fsanitize=address,undefined)
            endif()
        endif()
    else()
        message(WARNING "No warning flags configured for C compiler '${CMAKE_C_COMPILER_ID}'")
        if(DUOFORGE_ENABLE_SANITIZERS)
            message(FATAL_ERROR "DUOFORGE_ENABLE_SANITIZERS is unsupported for '${CMAKE_C_COMPILER_ID}'")
        endif()
    endif()
endfunction()
