# The table generator refuses move shapes it does not model (no checkout needed).
add_test(NAME duoforge.data.gen_closure_refusals
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/tests/test_gen_closure.py")
duoforge_label_test(duoforge.data.gen_closure_refusals quick tools)
set_tests_properties(duoforge.data.gen_closure_refusals PROPERTIES TIMEOUT 60
    ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
# Every Python test script CTest runs keeps unittest.main() last, so no TestCase is left unrun (issue #457).
add_test(NAME duoforge.data.test_main_last
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/tests/test_main_last.py")
duoforge_label_test(duoforge.data.test_main_last quick tools)
set_tests_properties(duoforge.data.test_main_last PROPERTIES TIMEOUT 60
    ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
# The generated names of the data query API against the macros of the headers and the
# key() mapping of the trace converter (no checkout needed).
add_test(NAME duoforge.data.pool_names
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/tests/test_pool_names.py")
duoforge_label_test(duoforge.data.pool_names quick tools)
set_tests_properties(duoforge.data.pool_names PROPERTIES TIMEOUT 60
    ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
# The whole-pool rows (decision 0015 section 4.2) against the committed output of the pinned validator, with code
# of its own: the ids, the formes and their Mega links, the learnable moves and legal abilities, the move rows and
# the UNMODELED markers (no checkout needed).
add_test(NAME duoforge.data.pool_rows
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/tests/test_pool_rows.py")
duoforge_label_test(duoforge.data.pool_rows quick tools)
set_tests_properties(duoforge.data.pool_rows PROPERTIES TIMEOUT 60
    ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
# The classes of the unsupported pool entries (hand-work, data-only with its witness, modelled-unmarked) on small
# snippets of the pinned layout (no checkout needed; the checkout counts run only with DUOFORGE_PS_REFERENCE_DIR).
add_test(NAME duoforge.data.classify_unsupported
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/tests/test_classify_unsupported.py")
duoforge_label_test(duoforge.data.classify_unsupported quick tools)
set_tests_properties(duoforge.data.classify_unsupported PROPERTIES TIMEOUT 60
    ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
# The format definition data/formats/reg-mc.json (restructure step 10): the generated format header, the pool
# tables reproduced exactly from it and the named format constants in code (no checkout needed).
add_test(NAME duoforge.data.format_regmc
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/tests/test_format.py")
duoforge_label_test(duoforge.data.format_regmc quick tools)
set_tests_properties(duoforge.data.format_regmc PROPERTIES TIMEOUT 60
    ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
# The format definition data/formats/champions-ou.json (step O1 of the Gen 9 OU spec): the facts against the rule
# table of its pool source, the pool inside today's pool tables and Reg M-C's pool, and the engine's header still
# Reg M-C's (no checkout needed).
add_test(NAME duoforge.data.format_champions_ou
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/tests/test_format_champions_ou.py")
duoforge_label_test(duoforge.data.format_champions_ou quick tools)
set_tests_properties(duoforge.data.format_champions_ou PROPERTIES TIMEOUT 60
    ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
