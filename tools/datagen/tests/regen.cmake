add_test(NAME duoforge.data.closure_regen
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/gen_closure.py"
        "${DUOFORGE_PS_REFERENCE_DIR}" --check)
set_tests_properties(duoforge.data.closure_regen PROPERTIES TIMEOUT 120 LABELS reference)
add_test(NAME duoforge.data.extended_regen
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/gen_closure.py"
        "${DUOFORGE_PS_REFERENCE_DIR}" --team-c --check)
set_tests_properties(duoforge.data.extended_regen PROPERTIES TIMEOUT 120 LABELS reference)
add_test(NAME duoforge.data.pool_regen
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/gen_closure.py"
        "${DUOFORGE_PS_REFERENCE_DIR}" --pool --check)
set_tests_properties(duoforge.data.pool_regen PROPERTIES TIMEOUT 120 LABELS reference)
