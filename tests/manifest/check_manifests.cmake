# Checks the source-lock and support-manifest scaffolding for honesty rules:
#
#   * an UNPINNED source has no revision and no file hashes (no placeholders);
#   * a PINNED source has a 40-hex commit and a non-zero 64-hex SHA-256 per file;
#   * the lock is PINNED only when every entry is PINNED;
#   * nothing claims certification while the lock is unpinned or the
#     profile/teams are not selected.
#
# It validates structure only. It cannot prove that a recorded revision or
# hash is the one that was actually used.
#
# Usage: cmake -DPBD_SOURCE_LOCK=<file> -DPBD_SUPPORT_MANIFEST=<file> -P check_manifests.cmake

cmake_minimum_required(VERSION 3.21)

function(pbd_reject reason)
    message(FATAL_ERROR "pbd-manifest-check: REJECTED: ${reason}")
endfunction()

function(pbd_json_get out json)
    string(JSON _value ERROR_VARIABLE _err GET "${json}" ${ARGN})
    if(_err)
        pbd_reject("missing field '${ARGN}': ${_err}")
    endif()
    set(${out} "${_value}" PARENT_SCOPE)
endfunction()

function(pbd_json_type out json)
    string(JSON _type ERROR_VARIABLE _err TYPE "${json}" ${ARGN})
    if(_err)
        pbd_reject("missing field '${ARGN}': ${_err}")
    endif()
    set(${out} "${_type}" PARENT_SCOPE)
endfunction()

foreach(_var IN ITEMS PBD_SOURCE_LOCK PBD_SUPPORT_MANIFEST)
    if(NOT DEFINED ${_var} OR NOT EXISTS "${${_var}}")
        # Deliberately not the REJECTED prefix: a missing file is a usage error.
        message(FATAL_ERROR "pbd-manifest-check: usage error: ${_var} is not an existing file")
    endif()
endforeach()

# --- source lock -------------------------------------------------------------

file(READ "${PBD_SOURCE_LOCK}" _lock)
string(JSON _probe ERROR_VARIABLE _parse_err TYPE "${_lock}")
if(_parse_err)
    pbd_reject("source lock is not valid JSON: ${_parse_err}")
endif()

pbd_json_get(_schema "${_lock}" schema)
if(NOT _schema STREQUAL "pbd.source-lock.v0-draft")
    pbd_reject("unexpected source-lock schema '${_schema}'")
endif()

pbd_json_get(_lock_status "${_lock}" lock_status)
if(NOT _lock_status MATCHES "^(UNPINNED|PINNED)$")
    pbd_reject("lock_status must be UNPINNED or PINNED, got '${_lock_status}'")
endif()

string(JSON _entry_count ERROR_VARIABLE _err LENGTH "${_lock}" entries)
if(_err OR _entry_count EQUAL 0)
    pbd_reject("source lock needs a non-empty 'entries' array")
endif()

set(_any_unpinned FALSE)
math(EXPR _last_entry "${_entry_count} - 1")
foreach(_i RANGE ${_last_entry})
    pbd_json_get(_id "${_lock}" entries ${_i} id)
    pbd_json_get(_status "${_lock}" entries ${_i} status)
    pbd_json_type(_revision_type "${_lock}" entries ${_i} revision)

    string(JSON _file_count ERROR_VARIABLE _err LENGTH "${_lock}" entries ${_i} files)
    if(_err)
        pbd_reject("entry '${_id}' needs a 'files' array")
    endif()

    if(_status STREQUAL "UNPINNED")
        set(_any_unpinned TRUE)
        if(NOT _revision_type STREQUAL "NULL")
            pbd_reject("entry '${_id}' is UNPINNED but records a revision")
        endif()
    elseif(_status STREQUAL "PINNED")
        if(NOT _revision_type STREQUAL "STRING")
            pbd_reject("entry '${_id}' is PINNED without a revision string")
        endif()
        pbd_json_get(_revision "${_lock}" entries ${_i} revision)
        if(NOT _revision MATCHES "^[0-9a-f]+$")
            pbd_reject("entry '${_id}' revision '${_revision}' is not a lowercase hex commit id")
        endif()
        string(LENGTH "${_revision}" _revision_len)
        if(NOT _revision_len EQUAL 40 OR _revision MATCHES "^0+$")
            pbd_reject("entry '${_id}' revision '${_revision}' is not a plausible full commit id")
        endif()
        if(_file_count EQUAL 0)
            pbd_reject("entry '${_id}' is PINNED but lists no files")
        endif()
    else()
        pbd_reject("entry '${_id}' has unknown status '${_status}'")
    endif()

    if(_file_count GREATER 0)
        math(EXPR _last_file "${_file_count} - 1")
        foreach(_f RANGE ${_last_file})
            pbd_json_get(_path "${_lock}" entries ${_i} files ${_f} path)
            pbd_json_type(_hash_type "${_lock}" entries ${_i} files ${_f} sha256)
            if(_status STREQUAL "UNPINNED")
                if(NOT _hash_type STREQUAL "NULL")
                    pbd_reject("entry '${_id}' is UNPINNED but '${_path}' records a hash")
                endif()
            else()
                if(NOT _hash_type STREQUAL "STRING")
                    pbd_reject("entry '${_id}' file '${_path}' is PINNED without sha256")
                endif()
                pbd_json_get(_hash "${_lock}" entries ${_i} files ${_f} sha256)
                string(LENGTH "${_hash}" _hash_len)
                if(NOT _hash MATCHES "^[0-9a-f]+$" OR NOT _hash_len EQUAL 64 OR _hash MATCHES "^0+$")
                    pbd_reject("entry '${_id}' file '${_path}' has an implausible sha256 '${_hash}'")
                endif()
            endif()
        endforeach()
    endif()
endforeach()

if(_any_unpinned AND NOT _lock_status STREQUAL "UNPINNED")
    pbd_reject("lock_status is '${_lock_status}' although at least one entry is UNPINNED")
endif()
if(NOT _any_unpinned AND NOT _lock_status STREQUAL "PINNED")
    pbd_reject("every entry is PINNED but lock_status is '${_lock_status}'")
endif()

# --- support manifest --------------------------------------------------------

file(READ "${PBD_SUPPORT_MANIFEST}" _support)
string(JSON _probe ERROR_VARIABLE _parse_err TYPE "${_support}")
if(_parse_err)
    pbd_reject("support manifest is not valid JSON: ${_parse_err}")
endif()

pbd_json_get(_schema "${_support}" schema)
if(NOT _schema STREQUAL "pbd.support-manifest.v0-draft")
    pbd_reject("unexpected support-manifest schema '${_schema}'")
endif()

pbd_json_get(_certification "${_support}" certification)
set(_blocking_selection FALSE)
foreach(_field IN ITEMS rules_profile information_profile teams)
    pbd_json_get(_value "${_support}" ${_field})
    if(_value STREQUAL "NOT_SELECTED")
        set(_blocking_selection TRUE)
    endif()
endforeach()

if(NOT _certification STREQUAL "NONE")
    if(_any_unpinned)
        pbd_reject("certification '${_certification}' claimed while sources are UNPINNED")
    endif()
    if(_blocking_selection)
        pbd_reject("certification '${_certification}' claimed while profile/teams are NOT_SELECTED")
    endif()
endif()

string(JSON _area_count ERROR_VARIABLE _err LENGTH "${_support}" areas)
if(_err OR _area_count EQUAL 0)
    pbd_reject("support manifest needs a non-empty 'areas' array")
endif()
math(EXPR _last_area "${_area_count} - 1")
foreach(_a RANGE ${_last_area})
    pbd_json_get(_area_id "${_support}" areas ${_a} id)
    pbd_json_get(_area_status "${_support}" areas ${_a} status)
    if(NOT _area_status MATCHES "^(UNSUPPORTED|IMPLEMENTED|TESTED|CERTIFIED)$")
        pbd_reject("area '${_area_id}' has unknown status '${_area_status}'")
    endif()
    if(_area_status STREQUAL "CERTIFIED" AND _certification STREQUAL "NONE")
        pbd_reject("area '${_area_id}' is CERTIFIED but manifest certification is NONE")
    endif()
endforeach()

message(STATUS "pbd-manifest-check: OK (${_entry_count} source entries, ${_area_count} areas, lock ${_lock_status}, certification ${_certification})")
