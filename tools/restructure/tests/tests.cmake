# tools/restructure: the code-diff and callgrind tools of the phase-cut proofs (fn_diff, callgrind_gate), offline.
if(DUOFORGE_PYTHON)
    add_test(NAME duoforge.tools.restructure
        COMMAND "${DUOFORGE_PYTHON}" "${PROJECT_SOURCE_DIR}/tools/restructure/tests/test_restructure_tools.py")
    set_tests_properties(duoforge.tools.restructure PROPERTIES TIMEOUT 120 ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1")
else()
    add_test(NAME duoforge.tools.restructure
        COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: DUOFORGE_PYTHON is empty")
    set_tests_properties(duoforge.tools.restructure PROPERTIES SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
endif()
duoforge_label_test(duoforge.tools.restructure quick tools ci-no-skip)
