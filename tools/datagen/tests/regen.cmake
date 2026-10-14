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
# Every fact of the format definition against its line of the pinned checkout (restructure step 10).
add_test(NAME duoforge.data.format_pin
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/gen_format.py"
        --pin "${DUOFORGE_PS_REFERENCE_DIR}")
duoforge_label_test(duoforge.data.format_pin reference tools)
set_tests_properties(duoforge.data.format_pin PROPERTIES TIMEOUT 60)
# Every fact of the Champions OU definition against its line of the pinned checkout (step O1 of the Gen 9 OU spec).
add_test(NAME duoforge.data.format_pin_champions_ou
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/gen_format.py"
        --format champions-ou --pin "${DUOFORGE_PS_REFERENCE_DIR}")
duoforge_label_test(duoforge.data.format_pin_champions_ou reference tools)
set_tests_properties(duoforge.data.format_pin_champions_ou PROPERTIES TIMEOUT 60)
