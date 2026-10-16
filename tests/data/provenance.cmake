# The static columns have no engine reader (decision 0020 item 5): only the tables and the data query API name them.
add_test(NAME duoforge.data.static_unread
    COMMAND "${CMAKE_COMMAND}" "-DSRC_DIR=${PROJECT_SOURCE_DIR}/src" -P "${PROJECT_SOURCE_DIR}/cmake/checks/static_columns_unread.cmake")
duoforge_label_test(duoforge.data.static_unread quick data)
set_tests_properties(duoforge.data.static_unread PROPERTIES TIMEOUT 30)
# The generated files must stay exactly what tools/datagen/gen_closure.py
# wrote; regenerate and update these hashes together.
foreach(_gen IN ITEMS
        "closure_tables.h=18e2999c683958c41d6f9c1b1ad9610c37f00e0a0431628439f75b70a7169c7f"
        "closure_tables.c=490de42298e34cfd38192d979fd022367bf53693a5fa1855f1cc6ad034d8450a"
        "extended_tables.h=b2abef243fcbfdd87654940076b9fe2fe80b117d74893a7567741f26b9075a7d"
        "extended_tables.c=9e736fa467713283418c4edf8f56b8d844452e596ba422adbd52483d20f7cc17"
        "pool_tables.h=4003f3cec150b48c7215a4469ec17ed0edc2a3940204fedd77a1cbeb2b847f0b"
        "pool_tables.c=585de36e19f17aa43cc4e5db7bf7c19a98622e98d5b9d64a36b45827c47dfb2c")
    string(REPLACE "=" ";" _parts "${_gen}")
    list(GET _parts 0 _file)
    list(GET _parts 1 _expected)
    add_test(NAME duoforge.provenance.${_file}
        COMMAND "${CMAKE_COMMAND}"
            "-DFILE=${PROJECT_SOURCE_DIR}/src/data/${_file}"
            -DEXPECTED=${_expected}
            -P "${PROJECT_SOURCE_DIR}/cmake/checks/file_sha256.cmake")
    duoforge_label_test(duoforge.provenance.${_file} quick data)
    set_tests_properties(duoforge.provenance.${_file} PROPERTIES TIMEOUT 30)
endforeach()
