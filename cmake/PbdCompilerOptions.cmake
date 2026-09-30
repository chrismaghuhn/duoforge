# Compiler-specific warning and sanitizer settings for pbd targets.
#
# Flags are chosen per compiler front end: MSVC-style options for MSVC and
# clang-cl, GCC-style options for GCC and Clang. Nothing GCC-only is passed
# to MSVC. Settings are applied per target, never through global flags.

set(PBD_SANITIZE "" CACHE STRING
    "Sanitizers for GCC/Clang builds, e.g. 'address,undefined'. Empty disables them.")

if(PBD_SANITIZE AND MSVC)
    # Not silently ignored: MSVC sanitizer support is untested here.
    message(FATAL_ERROR
        "PBD_SANITIZE='${PBD_SANITIZE}' is not supported with MSVC-style compilers in this project yet.")
endif()

function(pbd_configure_target target)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /utf-8)
        if(PBD_WARNINGS_AS_ERRORS)
            target_compile_options(${target} PRIVATE /WX)
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
            -Wformat=2
            -Wundef
            -Wcast-qual
            -Wvla)
        if(PBD_WARNINGS_AS_ERRORS)
            target_compile_options(${target} PRIVATE -Werror)
        endif()
        if(PBD_SANITIZE)
            target_compile_options(${target} PRIVATE
                -fsanitize=${PBD_SANITIZE}
                -fno-sanitize-recover=all
                -fno-omit-frame-pointer)
            target_link_options(${target} PRIVATE -fsanitize=${PBD_SANITIZE})
        endif()
    else()
        message(WARNING
            "No warning flags configured for C compiler '${CMAKE_C_COMPILER_ID}'; it is untested.")
        if(PBD_SANITIZE)
            message(FATAL_ERROR
                "PBD_SANITIZE is only supported for GCC/Clang, not '${CMAKE_C_COMPILER_ID}'.")
        endif()
    endif()
endfunction()
