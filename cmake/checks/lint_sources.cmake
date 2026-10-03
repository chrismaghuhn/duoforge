# Source lint for DuoForge (run with cmake -P). See docs/decisions/0003.
#
# Usage:
#   cmake -DROOT=<repo> -P cmake/checks/lint_sources.cmake
#   cmake -DROOT=<repo> "-DFILES=<abs1>|<abs2>" -P cmake/checks/lint_sources.cmake
#
# Scans src/**/*.c, src/**/*.h and include/**/*.h (or the FILES override).
# Prints "<file>:<line>: <rule-id>" per finding and fails if any finding exists.
# Comments and strings are linted too: reword text instead of weakening a rule.
#
# Regexes are applied per line only. Never apply a regex with a repeated group
# to a whole file: CMake's regex engine recurses and can overflow the stack.

cmake_minimum_required(VERSION 3.23)

if(NOT DEFINED ROOT)
    message(FATAL_ERROR "lint: ROOT is required")
endif()

if(DEFINED FILES AND NOT FILES STREQUAL "")
    string(REPLACE "|" ";" _files "${FILES}")
else()
    file(GLOB_RECURSE _files
        "${ROOT}/src/*.c" "${ROOT}/src/*.h" "${ROOT}/include/*.h")
    list(SORT _files)
endif()

set(_boundary "(^|[^A-Za-z0-9_])")
set(_re_banned_call "${_boundary}(rand|srand|time|clock|getenv|localtime|gmtime|setjmp|longjmp|memcmp|assert|printf|fprintf|puts)[ \t]*\\(")
set(_re_alloc_call "${_boundary}(malloc|calloc|realloc|free)[ \t]*\\(")
set(_re_banned_token "${_boundary}(float|double|_Thread_local|thread_local|long|short|int|signed|unsigned|int8_t|int16_t|int32_t|int64_t|intptr_t|intmax_t|ptrdiff_t)([^A-Za-z0-9_]|$)")
# The files that compute in floating point: src/state/tiebreak.c (the reference's
# tiebreak arithmetic) and the encoder, whose outputs are float32 by contract
# (src/encode/encode.c and its header, decision 0021); and the files that only
# pass the encoder's float32 rows through: its internal header for one player
# and the search's leaf expansion (decision 0022). Every other banned token
# still applies to them.
set(_re_banned_token_fp "${_boundary}(_Thread_local|thread_local|long|short|int|signed|unsigned|int8_t|int16_t|int32_t|int64_t|intptr_t|intmax_t|ptrdiff_t)([^A-Za-z0-9_]|$)")
set(_fp_files "src/state/tiebreak.c" "src/encode/encode.c" "include/duoforge/duoforge_encode.h"
    "src/encode/encode_internal.h" "src/search/search.c" "include/duoforge/duoforge_search.h")
set(_re_long_suffix "${_boundary}(0[xX][0-9a-fA-F]+|[0-9]+)[uU]?[lL]")
set(_re_pragma_pack "#[ \t]*pragma[ \t]+pack")
set(_re_attr_packed "__attribute__[ \t]*\\(\\(packed")
set(_re_result_cast "\\((uint(8|16|32|64)_t|size_t)\\)[ \t]*\\(")
set(_marker "wide-operands-reviewed")

set(_findings 0)

foreach(_file IN LISTS _files)
    if(NOT EXISTS "${_file}")
        message(FATAL_ERROR "lint: file not found: ${_file}")
    endif()
    file(RELATIVE_PATH _rel "${ROOT}" "${_file}")

    # non-ascii: pair the hex digits first so the byte check stays aligned.
    file(READ "${_file}" _hex HEX)
    string(REGEX REPLACE "(..)" "\\1 " _spaced "${_hex}")
    if(" ${_spaced}" MATCHES " [89a-f][0-9a-f]")
        message("${_rel}:0: non-ascii")
        math(EXPR _findings "${_findings} + 1")
    endif()

    file(READ "${_file}" _text)
    # Neutralize characters with CMake list semantics before splitting lines.
    string(REPLACE "\\" "@" _text "${_text}")
    string(REPLACE ";" "@" _text "${_text}")
    string(REPLACE "[" "@" _text "${_text}")
    string(REPLACE "]" "@" _text "${_text}")
    string(REPLACE "\n" ";" _lines "${_text}")

    set(_re_token "${_re_banned_token}")
    if(_rel IN_LIST _fp_files)
        set(_re_token "${_re_banned_token_fp}")
    endif()

    set(_is_alloc_file FALSE)
    if(_rel STREQUAL "src/core/alloc.c")
        set(_is_alloc_file TRUE)
    endif()

    set(_n 0)
    foreach(_line IN LISTS _lines)
        math(EXPR _n "${_n} + 1")
        if("${_line}" MATCHES "${_re_banned_call}")
            message("${_rel}:${_n}: banned-call")
            math(EXPR _findings "${_findings} + 1")
        endif()
        if(NOT _is_alloc_file AND "${_line}" MATCHES "${_re_alloc_call}")
            message("${_rel}:${_n}: alloc-call")
            math(EXPR _findings "${_findings} + 1")
        endif()
        if("${_line}" MATCHES "${_re_token}")
            message("${_rel}:${_n}: banned-token")
            math(EXPR _findings "${_findings} + 1")
        endif()
        if("${_line}" MATCHES "${_re_long_suffix}")
            message("${_rel}:${_n}: long-suffix")
            math(EXPR _findings "${_findings} + 1")
        endif()
        if("${_line}" MATCHES "${_re_pragma_pack}" OR "${_line}" MATCHES "${_re_attr_packed}")
            message("${_rel}:${_n}: packed")
            math(EXPR _findings "${_findings} + 1")
        endif()
        if("${_line}" MATCHES "${_re_result_cast}")
            string(FIND "${_line}" "${_marker}" _pos)
            if(_pos EQUAL -1)
                message("${_rel}:${_n}: result-cast")
                math(EXPR _findings "${_findings} + 1")
            endif()
        endif()
    endforeach()
endforeach()

list(LENGTH _files _file_count)
if(_findings GREATER 0)
    message(FATAL_ERROR "lint: ${_findings} finding(s) in ${_file_count} file(s)")
endif()
message("lint: OK (${_file_count} files)")
