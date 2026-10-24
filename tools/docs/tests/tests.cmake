# tools/docs: the generated support README and the decision 0015 entry ids of docs/mechanics (restructure step 11).
add_test(NAME duoforge.docs.support_readme
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/docs/mechanics_docs.py" --check-readme)
duoforge_label_test(duoforge.docs.support_readme quick tools)
set_tests_properties(duoforge.docs.support_readme PROPERTIES TIMEOUT 60 ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
# Every entry id is in one mechanic file, the frozen redirect table of 0015 resolves, and every id cited next to
# "0015" in a tracked file exists (needs a git checkout).
add_test(NAME duoforge.docs.mechanics_ids
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/docs/mechanics_docs.py" --check-ids)
duoforge_label_test(duoforge.docs.mechanics_ids quick tools)
set_tests_properties(duoforge.docs.mechanics_ids PROPERTIES TIMEOUT 120 ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
