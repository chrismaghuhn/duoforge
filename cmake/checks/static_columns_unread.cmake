# The generated static columns of decision 0020 (dfi_pool_move_static_flags, dfi_pool_move_static_hits) are data for the
# static read API only: no engine code may read them. They may appear in the generated tables (which define them and
# write them into the canonical bytes) and in the data query API (state/data_query.c, which gives them out) and nowhere
# else under src/.
#
#   cmake -DSRC_DIR=<repo>/src -P static_columns_unread.cmake
if(NOT SRC_DIR)
    message(FATAL_ERROR "static_columns_unread: SRC_DIR is not set")
endif()
file(GLOB_RECURSE _sources "${SRC_DIR}/*.c" "${SRC_DIR}/*.h")
set(_allowed "data/pool_tables.c" "data/pool_tables.h" "state/data_query.c")
set(_names dfi_pool_move_static_flags dfi_pool_move_static_hits)
set(_seen 0)
foreach(_file IN LISTS _sources)
    file(RELATIVE_PATH _rel "${SRC_DIR}" "${_file}")
    file(READ "${_file}" _text)
    foreach(_name IN LISTS _names)
        string(FIND "${_text}" "${_name}" _pos)
        if(NOT _pos EQUAL -1)
            list(FIND _allowed "${_rel}" _at)
            if(NOT _at EQUAL -1)
                math(EXPR _seen "${_seen} + 1")
            else()
                message(FATAL_ERROR "static_columns_unread: ${_rel} reads ${_name}, which has no engine reader (decision 0020)")
            endif()
        endif()
    endforeach()
endforeach()
# the check is not vacuous: the generated tables define both columns and the API reads both
if(_seen LESS 4)
    message(FATAL_ERROR "static_columns_unread: the columns were found in ${_seen} places, expected at least 4")
endif()
message(STATUS "static_columns_unread: ok (${_seen} places)")
