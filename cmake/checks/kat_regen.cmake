# Regenerates the PCG32 KAT header with the generator built against the
# pinned reference and compares it byte-for-byte with the committed file.
#
# Usage: cmake -DGEN=<generator exe> -DOUT=<output file> -DEXPECTED=<committed header> -P kat_regen.cmake

cmake_minimum_required(VERSION 3.23)

foreach(_v IN ITEMS GEN OUT EXPECTED)
    if(NOT DEFINED ${_v})
        message(FATAL_ERROR "kat-regen: ${_v} is required")
    endif()
endforeach()
execute_process(COMMAND "${GEN}" OUTPUT_FILE "${OUT}" RESULT_VARIABLE _rc ERROR_VARIABLE _err)
if(NOT _rc EQUAL 0)
    message(FATAL_ERROR "kat-regen: generator failed (${_rc}): ${_err}")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -E compare_files "${OUT}" "${EXPECTED}" RESULT_VARIABLE _cmp)
if(NOT _cmp EQUAL 0)
    message(FATAL_ERROR "kat-regen: regenerated KAT differs from ${EXPECTED} (see ${OUT})")
endif()
file(SHA256 "${OUT}" _sha)
message("kat-regen: OK ${_sha}")
