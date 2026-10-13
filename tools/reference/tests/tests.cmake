# Independent format pins and mutation controls use only the standard library.
add_test(NAME duoforge.reference.format_pins
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_battle_pins.py")
duoforge_label_test(duoforge.reference.format_pins quick tools ci-no-skip)
set_tests_properties(duoforge.reference.format_pins PROPERTIES TIMEOUT 60
    ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;DUOFORGE_CMAKE=${CMAKE_COMMAND}")

# Observe every frozen certified/fixture/live pin independently in CI. Native
# profiles retain a visible skip; configured Python/Showdown jobs must run it.
if(DUOFORGE_PYTHON AND DUOFORGE_NODE AND DUOFORGE_PS_REFERENCE_DIR)
    add_test(NAME duoforge.reference.battle_pins
        COMMAND "${DUOFORGE_PYTHON}" "${PROJECT_SOURCE_DIR}/tools/reference/capture_battle_pins.py"
            "${PROJECT_SOURCE_DIR}" --check)
    set_tests_properties(duoforge.reference.battle_pins PROPERTIES TIMEOUT 600 ENVIRONMENT
        "DUOFORGE_NODE=${DUOFORGE_NODE};DUOFORGE_PS_REFERENCE_DIR=${DUOFORGE_PS_REFERENCE_DIR};DUOFORGE_DIFF_RUNNER=$<TARGET_FILE:duoforge_diff_runner>;DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;PYTHONPATH=${PROJECT_SOURCE_DIR}/python;PYTHONDONTWRITEBYTECODE=1;OPENBLAS_NUM_THREADS=1")
else()
    add_test(NAME duoforge.reference.battle_pins
        COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: needs Python, Node and pinned Showdown")
    set_tests_properties(duoforge.reference.battle_pins PROPERTIES SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
endif()
duoforge_label_test(duoforge.reference.battle_pins full tools ci-no-skip)

add_test(NAME duoforge.reference.conformance_tables
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/trace_to_c.py"
        "${PROJECT_SOURCE_DIR}" --check)
duoforge_label_test(duoforge.reference.conformance_tables full tools ci-no-skip)
set_tests_properties(duoforge.reference.conformance_tables PROPERTIES TIMEOUT 60)
# The converter as a library: its refusals carry their rules and messages,
# and the three generated headers are what the library makes (no checkout needed).
add_test(NAME duoforge.reference.converter_api
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_trace_to_c.py")
duoforge_label_test(duoforge.reference.converter_api full tools ci-no-skip)
set_tests_properties(duoforge.reference.converter_api PROPERTIES TIMEOUT 120
    ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
# The records of the differential runner (tools/difftest): written from the
# committed battles by tools/reference/conformance_records.py, they must be
# exactly what the compiled tables hold. The setup test writes them, the
# two builds of the sync test (closure, Team C) read them.
set(_records_dir "${CMAKE_CURRENT_BINARY_DIR}/conformance_records")
add_test(NAME duoforge.reference.records_write
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/conformance_records.py"
        --all "${PROJECT_SOURCE_DIR}" --out "${_records_dir}")
duoforge_label_test(duoforge.reference.records_write full tools ci-no-skip)
set_tests_properties(duoforge.reference.records_write PROPERTIES TIMEOUT 120
    FIXTURES_SETUP duoforge_conformance_records ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
include(interactions/records.cmake)
# The runner's --dump-views (the Showdown live adapter's oracle): every closure battle's views
# at every step, the first ones against the public API (needs DUOFORGE_PYTHON).
if(DUOFORGE_PYTHON)
    add_test(NAME duoforge.reference.dump_views
        COMMAND "${DUOFORGE_PYTHON}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_dump_views.py"
            "$<TARGET_FILE:duoforge_diff_runner>" "${_records_dir}/closure.records")
    duoforge_label_test(duoforge.reference.dump_views full tools ci-no-skip)
    set_tests_properties(duoforge.reference.dump_views PROPERTIES TIMEOUT 300
        FIXTURES_REQUIRED duoforge_conformance_records ENVIRONMENT
        "DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;PYTHONPATH=${PROJECT_SOURCE_DIR}/python;PYTHONDONTWRITEBYTECODE=1")
else()
    add_test(NAME duoforge.reference.dump_views
        COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: DUOFORGE_PYTHON is empty")
    duoforge_label_test(duoforge.reference.dump_views full tools ci-no-skip)
    set_tests_properties(duoforge.reference.dump_views PROPERTIES SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
endif()
# The replay driver without Node: the buckets and the order of its output with
# fake children and the real converter, the records writer, and every committed
# battle through the runner of this build (a stand-in answers the reference).
add_test(NAME duoforge.reference.diff_driver
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_diff_driver.py")
duoforge_label_test(duoforge.reference.diff_driver full tools ci-no-skip)
set_tests_properties(duoforge.reference.diff_driver PROPERTIES TIMEOUT 300
    ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;DUOFORGE_DIFF_RUNNER=$<TARGET_FILE:duoforge_diff_runner>")
# The random mode of the driver without Node: how battle i follows from (seed, i), the bucket of
# each step of the pipeline and what wins, the files of a case, a run cut into chunks (the result
# does not depend on the cut), children that die or hang (stand-in processes), the machine lock
# (in a temporary directory, never the real one), the domain samples (made sets of choices as the
# converter makes them) and committed battles through the real runner.
add_test(NAME duoforge.reference.diff_random
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_diff_random.py")
duoforge_label_test(duoforge.reference.diff_random full tools ci-no-skip)
# 600 s: the machine lock tests start many bash processes, slow on Windows (about 4 min of the file there).
set_tests_properties(duoforge.reference.diff_random PROPERTIES TIMEOUT 600
    ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;DUOFORGE_DIFF_RUNNER=$<TARGET_FILE:duoforge_diff_runner>")
# The corpus of kept fuzz battles (decision 0015 section 6, tests/reference/corpus): every battle through the
# converter and the runner of this build, from the stored traces and without Node; all of them must PASS. It runs
# in every CI job that runs the whole suite, the ASan and UBSan job included (the TSan job runs only the batch tests).
add_test(NAME duoforge.reference.corpus
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/diff_driver.py" corpus
        --runner "$<TARGET_FILE:duoforge_diff_runner>" --workers 4
        --out "${CMAKE_CURRENT_BINARY_DIR}/diff_corpus")
duoforge_label_test(duoforge.reference.corpus quick tools ci-no-skip)
set_tests_properties(duoforge.reference.corpus PROPERTIES TIMEOUT 900 ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
# What the corpus is on disk: every spec has its trace and the other way round, the purposes say why each
# battle is there, the traces are of this pin and harness, and the whole stays under the cap of 20 MB.
add_test(NAME duoforge.reference.corpus_size
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_corpus_layout.py")
duoforge_label_test(duoforge.reference.corpus_size quick tools ci-no-skip)
set_tests_properties(duoforge.reference.corpus_size PROPERTIES TIMEOUT 120 ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
# The corpus tooling without Node: the signatures, the greedy choice and the cut, the layout checks, the replay and
# promote (coverage and defects), with committed battles for the fuzz and the reference.
add_test(NAME duoforge.reference.diff_corpus
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_diff_corpus.py")
duoforge_label_test(duoforge.reference.diff_corpus full tools ci-no-skip)
set_tests_properties(duoforge.reference.diff_corpus PROPERTIES TIMEOUT 300
    ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;DUOFORGE_DIFF_RUNNER=$<TARGET_FILE:duoforge_diff_runner>")
# The team registry (data/teams, one file for each team and an index shared with the learner): the committed registry
# is as it must be (every gender stated, a file never changed under its id, the files of the old locations equal),
# and the checks catch what they are for. The importer of pastes (tools/reference/import_paste.py) without Node:
# what it normalises and reports, what it refuses, and what it writes, with a stand-in for the pokedex.
add_test(NAME duoforge.reference.team_registry
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_team_registry.py")
duoforge_label_test(duoforge.reference.team_registry full tools ci-no-skip)
# The committed registry is checked whole once; the tests of the checks and of adding use a small copy of it
# (copy_registry), so the time grows with that one check only: 18 s alone (GCC debug, 1,414 teams, 2026-10-09; it was
# 161 s when every subtest checked a whole copy). 600 s is the margin for ASan and a busy machine.
set_tests_properties(duoforge.reference.team_registry PROPERTIES TIMEOUT 600 ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
add_test(NAME duoforge.reference.import_paste
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_import_paste.py")
duoforge_label_test(duoforge.reference.import_paste quick tools ci-no-skip)
set_tests_properties(duoforge.reference.import_paste PROPERTIES TIMEOUT 120 ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
# The bulk import of the VGCPastes sheet (tools/reference/import_vgcpastes.py) without Node or the library: the
# sheet rows, pool/pending/illegal, duplicates, the entries, a write into a copy of the registry (which it checks
# whole, hence the time of team_registry).
add_test(NAME duoforge.reference.import_vgcpastes
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_import_vgcpastes.py")
duoforge_label_test(duoforge.reference.import_vgcpastes full tools ci-no-skip)
set_tests_properties(duoforge.reference.import_vgcpastes PROPERTIES TIMEOUT 600 ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
