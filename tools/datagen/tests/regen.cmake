add_test(NAME duoforge.data.closure_regen
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/gen_closure.py"
        "${DUOFORGE_PS_REFERENCE_DIR}" --check)
duoforge_label_test(duoforge.data.closure_regen reference tools)
set_tests_properties(duoforge.data.closure_regen PROPERTIES TIMEOUT 120)
add_test(NAME duoforge.data.extended_regen
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/gen_closure.py"
        "${DUOFORGE_PS_REFERENCE_DIR}" --team-c --check)
duoforge_label_test(duoforge.data.extended_regen reference tools)
set_tests_properties(duoforge.data.extended_regen PROPERTIES TIMEOUT 120)
add_test(NAME duoforge.data.pool_regen
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/gen_closure.py"
        "${DUOFORGE_PS_REFERENCE_DIR}" --pool --check)
duoforge_label_test(duoforge.data.pool_regen reference tools)
set_tests_properties(duoforge.data.pool_regen PROPERTIES TIMEOUT 120)
