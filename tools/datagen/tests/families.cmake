# The family columns of the pool tables (decision 0015), against the pinned handlers: every
# family member's handler is called with a probe for each of the 18 types and must agree
# with the generated type, weather or terrain; the pool's ids are also validated by the
# pinned TeamValidator.
add_test(NAME duoforge.data.pool_families
    COMMAND "${DUOFORGE_NODE}" "${PROJECT_SOURCE_DIR}/tools/datagen/pool_families.js"
        "${DUOFORGE_PS_REFERENCE_DIR}" "${PROJECT_SOURCE_DIR}")
set_tests_properties(duoforge.data.pool_families PROPERTIES TIMEOUT 600 LABELS reference)
