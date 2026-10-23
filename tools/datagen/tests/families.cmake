# The family columns of the pool tables (decision 0015), against the pinned handlers: every
# family member's handler is called with a probe for each of the 18 types and must agree
# with the generated type, weather or terrain; the pool's ids are also validated by the
# pinned TeamValidator.
add_test(NAME duoforge.data.pool_families
    COMMAND "${DUOFORGE_NODE}" "${PROJECT_SOURCE_DIR}/tools/datagen/pool_families.js"
        "${DUOFORGE_PS_REFERENCE_DIR}" "${PROJECT_SOURCE_DIR}")
duoforge_label_test(duoforge.data.pool_families reference tools)
set_tests_properties(duoforge.data.pool_families PROPERTIES TIMEOUT 600)
# The pool source of each format definition, made again by the pinned TeamValidator
# (docs/research/expansion/tools/build_legal_pool.js) and compared with the committed file.
foreach(_format reg-mc champions-ou gen9ou)
    string(REPLACE "-" "_" _name "${_format}")
    add_test(NAME duoforge.data.format_pool_${_name}
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/tests/check_format_pool.py"
            "${DUOFORGE_NODE}" "${DUOFORGE_PS_REFERENCE_DIR}" "${_format}")
    duoforge_label_test(duoforge.data.format_pool_${_name} reference tools)
    set_tests_properties(duoforge.data.format_pool_${_name} PROPERTIES TIMEOUT 600
        ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
endforeach()
