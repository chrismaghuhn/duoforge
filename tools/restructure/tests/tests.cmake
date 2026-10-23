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
# Restructure step 6: tests/renames.tsv against the tree (every historical test name has its row; a done rename leaves no
# old name in a living file). Stdlib only.
add_test(NAME duoforge.lint.test_renames
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/restructure/test_audit.py" "${PROJECT_SOURCE_DIR}" --check)
duoforge_label_test(duoforge.lint.test_renames quick tools ci-no-skip)
set_tests_properties(duoforge.lint.test_renames PROPERTIES TIMEOUT 60 ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1")
