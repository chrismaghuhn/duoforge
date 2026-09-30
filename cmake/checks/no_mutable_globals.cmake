# Checks that the DuoForge static library defines no writable static storage
# (run with cmake -P). See docs/decisions/0003.
#
# Usage: cmake "-DOBJDUMP=<objdump>" -DLIB=<libduoforge.a> -DSANITIZERS=<ON|OFF> -P no_mutable_globals.cmake
#
# Fails on any object symbol in .data/.bss/.tdata/.tbss (except .data.rel.ro)
# and on any common symbol. It is non-vacuous: it also fails unless the
# symbol table shows the function duoforge_version_string in a text section.
# Prints "DUOFORGE_SKIP: <reason>" (registered as a skip) when the check
# cannot run meaningfully: no objdump, a sanitizer build (instrumentation adds
# writable globals), or a non-ELF library such as MSVC output.

cmake_minimum_required(VERSION 3.23)

if(NOT DEFINED LIB OR NOT EXISTS "${LIB}")
    message(FATAL_ERROR "no-mutable-globals: LIB is missing or does not exist: '${LIB}'")
endif()
if(NOT DEFINED OBJDUMP OR OBJDUMP STREQUAL "" OR OBJDUMP MATCHES "NOTFOUND$")
    message("DUOFORGE_SKIP: objdump not available")
    return()
endif()
if(SANITIZERS)
    message("DUOFORGE_SKIP: sanitizer instrumentation adds writable globals")
    return()
endif()

execute_process(
    COMMAND "${OBJDUMP}" -t "${LIB}"
    RESULT_VARIABLE _rc
    OUTPUT_VARIABLE _out
    ERROR_VARIABLE _err)
if(NOT _rc EQUAL 0)
    message(FATAL_ERROR "no-mutable-globals: objdump failed (${_rc}): ${_err}")
endif()
if(NOT _out MATCHES "file format elf")
    message("DUOFORGE_SKIP: library is not ELF")
    return()
endif()

string(REPLACE ";" "@" _out "${_out}")
string(REPLACE "\n" ";" _lines "${_out}")
set(_bad 0)
set(_found_anchor FALSE)
foreach(_line IN LISTS _lines)
    if(_line MATCHES "F \\.text[^ \t]*[ \t].*duoforge_version_string$")
        set(_found_anchor TRUE)
    endif()
    if(_line MATCHES "\\*COM\\*")
        message("no-mutable-globals: common symbol: ${_line}")
        math(EXPR _bad "${_bad} + 1")
    elseif(_line MATCHES " O \\.(data|bss|tdata|tbss)")
        if(NOT _line MATCHES " O \\.data\\.rel\\.ro")
            message("no-mutable-globals: writable object: ${_line}")
            math(EXPR _bad "${_bad} + 1")
        endif()
    endif()
endforeach()

if(NOT _found_anchor)
    message(FATAL_ERROR "no-mutable-globals: anchor function duoforge_version_string not found (vacuous check)")
endif()
if(_bad GREATER 0)
    message(FATAL_ERROR "no-mutable-globals: ${_bad} writable static object(s)")
endif()
message("no-mutable-globals: OK")
