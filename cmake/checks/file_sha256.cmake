# Compares a file's SHA-256 with an expected value (run with cmake -P).
#
# Usage: cmake -DFILE=<path> -DEXPECTED=<64 lowercase hex> -P file_sha256.cmake

cmake_minimum_required(VERSION 3.23)

if(NOT DEFINED FILE OR NOT EXISTS "${FILE}")
    message(FATAL_ERROR "file-sha256: FILE is missing or does not exist: '${FILE}'")
endif()
if(NOT EXPECTED MATCHES "^[0-9a-f]+$")
    message(FATAL_ERROR "file-sha256: EXPECTED must be lowercase hex")
endif()
string(LENGTH "${EXPECTED}" _len)
if(NOT _len EQUAL 64)
    message(FATAL_ERROR "file-sha256: EXPECTED must be 64 hex digits")
endif()
file(SHA256 "${FILE}" _actual)
if(NOT _actual STREQUAL EXPECTED)
    message(FATAL_ERROR "file-sha256: mismatch for ${FILE}\n  expected ${EXPECTED}\n  actual   ${_actual}")
endif()
message("file-sha256: OK ${_actual}")
