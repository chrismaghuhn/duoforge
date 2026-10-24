# The static columns have no engine reader (decision 0020 item 5): only the tables and the data query API name them.
add_test(NAME duoforge.data.static_unread
    COMMAND "${CMAKE_COMMAND}" "-DSRC_DIR=${PROJECT_SOURCE_DIR}/src" -P "${PROJECT_SOURCE_DIR}/cmake/checks/static_columns_unread.cmake")
duoforge_label_test(duoforge.data.static_unread quick data)
set_tests_properties(duoforge.data.static_unread PROPERTIES TIMEOUT 30)
# The generated files must stay exactly what tools/datagen/gen_closure.py
# wrote; regenerate and update these hashes together.
foreach(_gen IN ITEMS
        "closure_tables.h=18e2999c683958c41d6f9c1b1ad9610c37f00e0a0431628439f75b70a7169c7f"
        "closure_tables.c=494378dcf41d6c708809465dc5e999dfa669592a900ffefc64ce2ced5db54b28"
        "extended_tables.h=d246ade9a3c62b8050d00f04f438de46bfba90ef47f65662eeeb2bc2725d8e66"
        "extended_tables.c=bd1d776674195523cae1018762519bc55f96671889224c0df9820054bd0a398d"
        "pool_tables.h=52f87d545f3a152e1d799d5c9c40cdb7825eeadfa8472f3e3bd466aa3c43d89d"
        "pool_tables.c=aff29ef8ebe6aae1221f36f6355754bec6b4d9677c614bcab9c93c40f4cfd93b")
    string(REPLACE "=" ";" _parts "${_gen}")
    list(GET _parts 0 _file)
    list(GET _parts 1 _expected)
    add_test(NAME duoforge.provenance.${_file}
        COMMAND "${CMAKE_COMMAND}"
            "-DFILE=${PROJECT_SOURCE_DIR}/src/data/formats/reg-mc/${_file}"
            -DEXPECTED=${_expected}
            -P "${PROJECT_SOURCE_DIR}/cmake/checks/file_sha256.cmake")
    duoforge_label_test(duoforge.provenance.${_file} quick data)
    set_tests_properties(duoforge.provenance.${_file} PROPERTIES TIMEOUT 30)
endforeach()
