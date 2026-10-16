# tools/coverage (restructure step 8): the replay coverage tools offline, without the library or private data.
if(DUOFORGE_PYTHON)
    add_test(NAME duoforge.tools.coverage
        COMMAND "${DUOFORGE_PYTHON}" "${PROJECT_SOURCE_DIR}/tools/coverage/tests/test_coverage.py")
    set_tests_properties(duoforge.tools.coverage PROPERTIES TIMEOUT 300 ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1")
else()
    add_test(NAME duoforge.tools.coverage
        COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: DUOFORGE_PYTHON is empty")
    set_tests_properties(duoforge.tools.coverage PROPERTIES SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
endif()
duoforge_label_test(duoforge.tools.coverage quick tools ci-no-skip)
