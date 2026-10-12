# DuoForge tests. Every test is finite and has an explicit timeout.

# duoforge_add_test(NAME <ctest name> SOURCES <files...> [WHITEBOX]
#                   [TIMEOUT <s>] [LABELS <labels...>] [LIBS <libs...>] [ARGS <arguments...>])
# The executable name is NAME with '.' replaced by '_'. WHITEBOX adds src/ to
# the include path so a test can exercise internal functions. ARGS are the
# command line arguments of the test.
function(duoforge_add_test)
    cmake_parse_arguments(T "WHITEBOX" "NAME;TIMEOUT" "SOURCES;LABELS;LIBS;ARGS" ${ARGN})
    if(NOT T_TIMEOUT)
        set(T_TIMEOUT 30)
    endif()
    string(REPLACE "." "_" _exe "${T_NAME}")
    add_executable(${_exe} ${T_SOURCES})
    target_link_libraries(${_exe} PRIVATE duoforge ${T_LIBS})
    if(TARGET duoforge_test_support)
        target_link_libraries(${_exe} PRIVATE duoforge_test_support)
    endif()
    target_include_directories(${_exe} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
    if(T_WHITEBOX)
        target_include_directories(${_exe} PRIVATE "${PROJECT_SOURCE_DIR}/src")
    endif()
    duoforge_configure_target(${_exe})
    add_test(NAME ${T_NAME} COMMAND ${_exe} ${T_ARGS})
    set_tests_properties(${T_NAME} PROPERTIES TIMEOUT ${T_TIMEOUT})
    if(T_LABELS)
        set_tests_properties(${T_NAME} PROPERTIES LABELS "${T_LABELS}")
    endif()
    if(DUOFORGE_ENABLE_SANITIZERS)
        # Never abort_on_error: CTest would report an abort even when the
        # expected output matched (docs/decisions/0003).
        set_tests_properties(${T_NAME} PROPERTIES ENVIRONMENT
            "ASAN_OPTIONS=detect_leaks=1;UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1")
    endif()
endfunction()

# Shared test support (explicit test context, no globals).
add_library(duoforge_test_support STATIC support/check.c support/fixtures.c support/goldens.c
            support/goldens_legacy.c support/team_c.c support/pool.c support/factored.c
            support/conformance_compare.c)
target_include_directories(duoforge_test_support PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")
# The F2 fixture builder and the conformance comparators are white-box.
target_include_directories(duoforge_test_support PRIVATE "${PROJECT_SOURCE_DIR}/src")
target_link_libraries(duoforge_test_support PUBLIC duoforge)
duoforge_configure_target(duoforge_test_support)

# Area registrations retain tests/ as their source and binary directory.
include(flow/tests.cmake)
include(mechanics/tests.cmake)
include(items/tests.cmake)
include(abilities/tests.cmake)
include(moves/tests.cmake)
include(forms/tests.cmake)
include(data/tests.cmake)
include(interactions/tests.cmake)

# The static columns have no engine reader (decision 0020 item 5): only the tables and the data query API name them.
add_test(NAME duoforge.data.static_unread
    COMMAND "${CMAKE_COMMAND}" "-DSRC_DIR=${PROJECT_SOURCE_DIR}/src" -P "${PROJECT_SOURCE_DIR}/cmake/checks/static_columns_unread.cmake")
set_tests_properties(duoforge.data.static_unread PROPERTIES TIMEOUT 30)
# The generated files must stay exactly what tools/datagen/gen_closure.py
# wrote; regenerate and update these hashes together.
foreach(_gen IN ITEMS
        "closure_tables.h=f6ef34b31d74a60f9c28e0bce8d3cc39a68a2ee03c7d17532090c9fca42fb25b"
        "closure_tables.c=490de42298e34cfd38192d979fd022367bf53693a5fa1855f1cc6ad034d8450a"
        "extended_tables.h=b2abef243fcbfdd87654940076b9fe2fe80b117d74893a7567741f26b9075a7d"
        "extended_tables.c=9e736fa467713283418c4edf8f56b8d844452e596ba422adbd52483d20f7cc17"
        "pool_tables.h=30e779174bb73baa328ba66a363858820d2fcaf2ea6e356b9b3e26a2a2cd8847"
        "pool_tables.c=815f6228e5bff388a12c6bffb0ec73ea19203919acfe9b10f2a3f21f0dadfb7e")
    string(REPLACE "=" ";" _parts "${_gen}")
    list(GET _parts 0 _file)
    list(GET _parts 1 _expected)
    add_test(NAME duoforge.provenance.${_file}
        COMMAND "${CMAKE_COMMAND}"
            "-DFILE=${PROJECT_SOURCE_DIR}/src/data/${_file}"
            -DEXPECTED=${_expected}
            -P "${PROJECT_SOURCE_DIR}/cmake/checks/file_sha256.cmake")
    set_tests_properties(duoforge.provenance.${_file} PROPERTIES TIMEOUT 30)
endforeach()
# Optional: regenerate from a pinned Pokemon Showdown checkout and compare.
if(DUOFORGE_PS_REFERENCE_DIR)
    find_package(Python3 COMPONENTS Interpreter REQUIRED)
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
    # The arithmetic reference values, recomputed by the pinned Showdown.
    find_program(DUOFORGE_NODE node)
    if(DUOFORGE_NODE)
        add_test(NAME duoforge.reference.arith
            COMMAND "${DUOFORGE_NODE}" "${PROJECT_SOURCE_DIR}/tools/reference/arith_ref.js"
                "${DUOFORGE_PS_REFERENCE_DIR}" --check "${CMAKE_CURRENT_SOURCE_DIR}/reference/arith_ref.h")
        set_tests_properties(duoforge.reference.arith PROPERTIES TIMEOUT 120 LABELS reference)
        # The tiebreak values of tests/reference/tiebreak_ref.h, recomputed by the pinned Showdown: its
        # Battle.tiebreak() on fresh replays of the committed battles at several stops of each.
        add_test(NAME duoforge.reference.tiebreak_ref
            COMMAND "${DUOFORGE_NODE}" "${PROJECT_SOURCE_DIR}/tools/reference/tiebreak_ref.js"
                "${DUOFORGE_PS_REFERENCE_DIR}" "${PROJECT_SOURCE_DIR}"
                --check "${CMAKE_CURRENT_SOURCE_DIR}/reference/tiebreak_ref.h")
        set_tests_properties(duoforge.reference.tiebreak_ref PROPERTIES TIMEOUT 900 LABELS reference)
        # Step G57: the reflectable moves of the Champions Dex (flags.reflectable), recomputed by the pinned Showdown; the
        # generated bit DFI_MOVE_FLAG3_REFLECTABLE (dfi_pool_move_flags3) is checked against them by duoforge.state.pool_g57.
        add_test(NAME duoforge.reference.reflect_ref
            COMMAND "${DUOFORGE_NODE}" "${PROJECT_SOURCE_DIR}/tools/reference/reflect_ref.js"
                "${DUOFORGE_PS_REFERENCE_DIR}" --check "${CMAKE_CURRENT_SOURCE_DIR}/reference/reflect_ref.h")
        set_tests_properties(duoforge.reference.reflect_ref PROPERTIES TIMEOUT 120 LABELS reference)
        # The family columns of the pool tables (decision 0015), against the pinned handlers: every
        # family member's handler is called with a probe for each of the 18 types and must agree
        # with the generated type, weather or terrain; the pool's ids are also validated by the
        # pinned TeamValidator.
        add_test(NAME duoforge.data.pool_families
            COMMAND "${DUOFORGE_NODE}" "${PROJECT_SOURCE_DIR}/tools/datagen/pool_families.js"
                "${DUOFORGE_PS_REFERENCE_DIR}" "${PROJECT_SOURCE_DIR}")
        set_tests_properties(duoforge.data.pool_families PROPERTIES TIMEOUT 600 LABELS reference)
        # Every committed battle trace is reproduced by the pinned Showdown.
        file(GLOB _specs "${CMAKE_CURRENT_SOURCE_DIR}/reference/specs/*.json")
        foreach(_spec IN LISTS _specs)
            get_filename_component(_name "${_spec}" NAME_WE)
            add_test(NAME duoforge.reference.trace.${_name}
                COMMAND "${DUOFORGE_NODE}" "${PROJECT_SOURCE_DIR}/tools/reference/ps_trace.js"
                    "${DUOFORGE_PS_REFERENCE_DIR}" "${_spec}"
                    --check "${CMAKE_CURRENT_SOURCE_DIR}/reference/traces/${_name}.json")
            set_tests_properties(duoforge.reference.trace.${_name} PROPERTIES TIMEOUT 120 LABELS reference)
        endforeach()
        # The same specs through run() in one process, as the persistent worker
        # records them: identical to the traces, and again after other runs.
        add_test(NAME duoforge.reference.trace_run
            COMMAND "${DUOFORGE_NODE}" "${PROJECT_SOURCE_DIR}/tools/reference/test_ps_trace_run.js"
                "${DUOFORGE_PS_REFERENCE_DIR}")
        set_tests_properties(duoforge.reference.trace_run PROPERTIES TIMEOUT 600 LABELS reference)
        # The persistent worker (differential loop): its JSON-lines protocol over raw pipes.
        add_test(NAME duoforge.reference.worker_protocol
            COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/test_ps_worker.py"
                "${DUOFORGE_NODE}" "${DUOFORGE_PS_REFERENCE_DIR}")
        set_tests_properties(duoforge.reference.worker_protocol PROPERTIES TIMEOUT 120 LABELS reference
            ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
        # Random play (the worker's "play"): the policy generator, how a choice is drawn,
        # judged by Showdown and enumerated, and real battles of the committed teams.
        add_test(NAME duoforge.reference.play_policy
            COMMAND "${DUOFORGE_NODE}" "${PROJECT_SOURCE_DIR}/tools/reference/test_ps_play.js"
                "${DUOFORGE_PS_REFERENCE_DIR}")
        set_tests_properties(duoforge.reference.play_policy PROPERTIES TIMEOUT 300 LABELS reference)
        # The differential loop in replay mode: every committed battle through the
        # worker, the converter and the runner must come out PASS.
        add_test(NAME duoforge.reference.diff_replay
            COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/diff_driver.py" replay
                --checkout "${DUOFORGE_PS_REFERENCE_DIR}" --node "${DUOFORGE_NODE}"
                --runner "$<TARGET_FILE:duoforge_diff_runner>" --workers 4
                --out "${CMAKE_CURRENT_BINARY_DIR}/diff_replay")
        set_tests_properties(duoforge.reference.diff_replay PROPERTIES TIMEOUT 900 LABELS reference
            ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
        # The random mode end to end (no machine lock: local_ci.sh holds it already): 16 battles
        # that the pinned Showdown plays itself, run twice and once in pieces (chunks), the files
        # byte-identical, and their buckets, signatures and lengths as in
        # tests/reference/random_smoke_golden.json.
        add_test(NAME duoforge.reference.diff_random_smoke
            COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/test_diff_random_smoke.py"
                "${DUOFORGE_NODE}" "${DUOFORGE_PS_REFERENCE_DIR}" "$<TARGET_FILE:duoforge_diff_runner>"
                "${CMAKE_CURRENT_BINARY_DIR}/diff_random_smoke")
        set_tests_properties(duoforge.reference.diff_random_smoke PROPERTIES TIMEOUT 600 LABELS reference
            ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
        # The domain check end to end: 8 battles with every request sampled (--domain-rate 1.0),
        # the engine's candidates against what Showdown accepts for the side, before every step;
        # the same battles without the check come to the same: sampling changes nothing else.
        add_test(NAME duoforge.reference.diff_domain_smoke
            COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/test_diff_domain_smoke.py"
                "${DUOFORGE_NODE}" "${DUOFORGE_PS_REFERENCE_DIR}" "$<TARGET_FILE:duoforge_diff_runner>"
                "${CMAKE_CURRENT_BINARY_DIR}/diff_domain_smoke")
        set_tests_properties(duoforge.reference.diff_domain_smoke PROPERTIES TIMEOUT 600 LABELS reference
            ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
        # A team file of the random mode (--team): six battles of one that equals team A are those of team A,
        # their kept battles byte for byte.
        add_test(NAME duoforge.reference.diff_team_smoke
            COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/test_diff_team_smoke.py"
                "${DUOFORGE_NODE}" "${DUOFORGE_PS_REFERENCE_DIR}" "$<TARGET_FILE:duoforge_diff_runner>"
                "${CMAKE_CURRENT_BINARY_DIR}/diff_team_smoke")
        set_tests_properties(duoforge.reference.diff_team_smoke PROPERTIES TIMEOUT 600 LABELS reference
            ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
        # Random play under the POOL data kind (step G5): a team that carries U-turn (an id of the pool tables, which
        # Team C does not have) plays ten battles that all PASS under POOL, some with [from] U-turn.
        add_test(NAME duoforge.reference.diff_pool_smoke
            COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/test_diff_pool_smoke.py"
                "${DUOFORGE_NODE}" "${DUOFORGE_PS_REFERENCE_DIR}" "$<TARGET_FILE:duoforge_diff_runner>"
                "${CMAKE_CURRENT_BINARY_DIR}/diff_pool_smoke")
        set_tests_properties(duoforge.reference.diff_pool_smoke PROPERTIES TIMEOUT 600 LABELS reference
            ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
        # Step G7: a team with Wide Guard plays twenty battles that all PASS under POOL, every request sampled for the
        # domain check, some with a guard that stops a spread move.
        add_test(NAME duoforge.reference.diff_wide_guard_smoke
            COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/test_diff_wide_guard_smoke.py"
                "${DUOFORGE_NODE}" "${DUOFORGE_PS_REFERENCE_DIR}" "$<TARGET_FILE:duoforge_diff_runner>"
                "${CMAKE_CURRENT_BINARY_DIR}/diff_wide_guard_smoke")
        set_tests_properties(duoforge.reference.diff_wide_guard_smoke PROPERTIES TIMEOUT 900 LABELS reference
            ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
        # The paste importer (data/teams) with the pinned pokedex: the facts it reads, the owner's raw pastes of
        # decision 0004, the registry as a fixed point of the importer, and the command line end to end.
        add_test(NAME duoforge.reference.import_paste_pin
            COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/test_import_paste_pin.py"
                "${DUOFORGE_NODE}" "${DUOFORGE_PS_REFERENCE_DIR}")
        set_tests_properties(duoforge.reference.import_paste_pin PROPERTIES TIMEOUT 300 LABELS reference
            ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
        # The client streams of the live adapter's tests: every closure battle replayed from its
        # trace's inputs, with each step's lines equal to the trace.
        add_test(NAME duoforge.reference.client_streams
            COMMAND "${DUOFORGE_NODE}" "${PROJECT_SOURCE_DIR}/tools/reference/ps_client.js"
                "${DUOFORGE_PS_REFERENCE_DIR}" "${PROJECT_SOURCE_DIR}" --all --check)
        set_tests_properties(duoforge.reference.client_streams PROPERTIES TIMEOUT 300 LABELS reference)
        # The spectator channel of every committed battle (closure, Team C, pool): the fixtures of the M11
        # replay pipeline, each battle replayed from its trace's inputs.
        add_test(NAME duoforge.reference.spectator_streams
            COMMAND "${DUOFORGE_NODE}" "${PROJECT_SOURCE_DIR}/tools/reference/ps_client.js"
                "${DUOFORGE_PS_REFERENCE_DIR}" "${PROJECT_SOURCE_DIR}" --every --spectator --check)
        set_tests_properties(duoforge.reference.spectator_streams PROPERTIES TIMEOUT 300 LABELS reference
            PASS_REGULAR_EXPRESSION "ps_client: [0-9]+ battles match their traces")
        # The Showdown live adapter against the pinned Showdown and the runner's views (spec section 8).
        if(DUOFORGE_PYTHON)
            add_test(NAME duoforge.python.live
                COMMAND "${DUOFORGE_PYTHON}" -m unittest -v python.tests.test_live
                WORKING_DIRECTORY "${PROJECT_SOURCE_DIR}")
            set_tests_properties(duoforge.python.live PROPERTIES LABELS "python;reference" TIMEOUT 900 ENVIRONMENT
                "DUOFORGE_NODE=${DUOFORGE_NODE};DUOFORGE_PS_REFERENCE_DIR=${DUOFORGE_PS_REFERENCE_DIR};DUOFORGE_DIFF_RUNNER=$<TARGET_FILE:duoforge_diff_runner>;DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;PYTHONPATH=${PROJECT_SOURCE_DIR}/python;PYTHONDONTWRITEBYTECODE=1")
            set(_duoforge_live_registered ON)
            # The M11 replay pipeline against every committed battle's spectator log and DuoForge's views.
            add_test(NAME duoforge.python.replay
                COMMAND "${DUOFORGE_PYTHON}" -m unittest -v python.tests.test_replay
                WORKING_DIRECTORY "${PROJECT_SOURCE_DIR}")
            set_tests_properties(duoforge.python.replay PROPERTIES LABELS "python;reference" TIMEOUT 900 ENVIRONMENT
                "DUOFORGE_NODE=${DUOFORGE_NODE};DUOFORGE_PS_REFERENCE_DIR=${DUOFORGE_PS_REFERENCE_DIR};DUOFORGE_DIFF_RUNNER=$<TARGET_FILE:duoforge_diff_runner>;DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;PYTHONPATH=${PROJECT_SOURCE_DIR}/python;PYTHONDONTWRITEBYTECODE=1")
        endif()
    endif()
endif()
if(NOT _duoforge_live_registered)
    add_test(NAME duoforge.python.live
        COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: needs DUOFORGE_PYTHON, Node and DUOFORGE_PS_REFERENCE_DIR")
    set_tests_properties(duoforge.python.live PROPERTIES LABELS python SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
    add_test(NAME duoforge.python.replay
        COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: needs DUOFORGE_PYTHON, Node and DUOFORGE_PS_REFERENCE_DIR")
    set_tests_properties(duoforge.python.replay PROPERTIES LABELS python SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
endif()
# The conformance tables must be what the converter makes of the traces.
find_package(Python3 COMPONENTS Interpreter)
if(Python3_Interpreter_FOUND)
    add_test(NAME duoforge.reference.conformance_tables
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/trace_to_c.py"
            "${PROJECT_SOURCE_DIR}" --check)
    set_tests_properties(duoforge.reference.conformance_tables PROPERTIES TIMEOUT 60)
    # The converter as a library: its refusals carry their rules and messages,
    # and the three generated headers are what the library makes (no checkout needed).
    add_test(NAME duoforge.reference.converter_api
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/test_trace_to_c.py")
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
    set_tests_properties(duoforge.reference.records_write PROPERTIES TIMEOUT 120
        FIXTURES_SETUP duoforge_conformance_records ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
    include(interactions/records.cmake)
    # The runner's --dump-views (the Showdown live adapter's oracle): every closure battle's views
    # at every step, the first ones against the public API (needs DUOFORGE_PYTHON).
    if(DUOFORGE_PYTHON)
        add_test(NAME duoforge.reference.dump_views
            COMMAND "${DUOFORGE_PYTHON}" "${PROJECT_SOURCE_DIR}/tools/reference/test_dump_views.py"
                "$<TARGET_FILE:duoforge_diff_runner>" "${_records_dir}/closure.records")
        set_tests_properties(duoforge.reference.dump_views PROPERTIES TIMEOUT 300
            FIXTURES_REQUIRED duoforge_conformance_records ENVIRONMENT
            "DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;PYTHONPATH=${PROJECT_SOURCE_DIR}/python;PYTHONDONTWRITEBYTECODE=1")
    else()
        add_test(NAME duoforge.reference.dump_views
            COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: DUOFORGE_PYTHON is empty")
        set_tests_properties(duoforge.reference.dump_views PROPERTIES SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
    endif()
    # The replay driver without Node: the buckets and the order of its output with
    # fake children and the real converter, the records writer, and every committed
    # battle through the runner of this build (a stand-in answers the reference).
    add_test(NAME duoforge.reference.diff_driver
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/test_diff_driver.py")
    set_tests_properties(duoforge.reference.diff_driver PROPERTIES TIMEOUT 300
        ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;DUOFORGE_DIFF_RUNNER=$<TARGET_FILE:duoforge_diff_runner>")
    # The random mode of the driver without Node: how battle i follows from (seed, i), the bucket of
    # each step of the pipeline and what wins, the files of a case, a run cut into chunks (the result
    # does not depend on the cut), children that die or hang (stand-in processes), the machine lock
    # (in a temporary directory, never the real one), the domain samples (made sets of choices as the
    # converter makes them) and committed battles through the real runner.
    add_test(NAME duoforge.reference.diff_random
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/test_diff_random.py")
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
    set_tests_properties(duoforge.reference.corpus PROPERTIES TIMEOUT 900 ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
    # What the corpus is on disk: every spec has its trace and the other way round, the purposes say why each
    # battle is there, the traces are of this pin and harness, and the whole stays under the cap of 20 MB.
    add_test(NAME duoforge.reference.corpus_size
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/test_corpus_layout.py")
    set_tests_properties(duoforge.reference.corpus_size PROPERTIES TIMEOUT 120 ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
    # The corpus tooling without Node: the signatures, the greedy choice and the cut, the layout checks, the replay and
    # promote (coverage and defects), with committed battles for the fuzz and the reference.
    add_test(NAME duoforge.reference.diff_corpus
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/test_diff_corpus.py")
    set_tests_properties(duoforge.reference.diff_corpus PROPERTIES TIMEOUT 300
        ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;DUOFORGE_DIFF_RUNNER=$<TARGET_FILE:duoforge_diff_runner>")
    # The team registry (data/teams, one file for each team and an index shared with the learner): the committed registry
    # is as it must be (every gender stated, a file never changed under its id, the files of the old locations equal),
    # and the checks catch what they are for. The importer of pastes (tools/reference/import_paste.py) without Node:
    # what it normalises and reports, what it refuses, and what it writes, with a stand-in for the pokedex.
    add_test(NAME duoforge.reference.team_registry
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/test_team_registry.py")
    # The committed registry is checked whole once; the tests of the checks and of adding use a small copy of it
    # (copy_registry), so the time grows with that one check only: 18 s alone (GCC debug, 1,414 teams, 2026-10-09; it was
    # 161 s when every subtest checked a whole copy). 600 s is the margin for ASan and a busy machine.
    set_tests_properties(duoforge.reference.team_registry PROPERTIES TIMEOUT 600 ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
    add_test(NAME duoforge.reference.import_paste
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/test_import_paste.py")
    set_tests_properties(duoforge.reference.import_paste PROPERTIES TIMEOUT 120 ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
    # The bulk import of the VGCPastes sheet (tools/reference/import_vgcpastes.py) without Node or the library: the
    # sheet rows, pool/pending/illegal, duplicates, the entries, a write into a copy of the registry (which it checks
    # whole, hence the time of team_registry).
    add_test(NAME duoforge.reference.import_vgcpastes
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/test_import_vgcpastes.py")
    set_tests_properties(duoforge.reference.import_vgcpastes PROPERTIES TIMEOUT 600 ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
    # The AWS fuzz tooling (tools/cloud/aws_fuzz): its guards, the request, the user data and the policy text, offline,
    # with a stub aws first on the PATH. It needs a bash; on Windows that is Git's, not the WSL launcher in System32.
    if(WIN32)
        find_program(DUOFORGE_BASH NAMES bash HINTS "$ENV{ProgramFiles}/Git/bin" "$ENV{LocalAppData}/Programs/Git/bin"
            NO_DEFAULT_PATH)
    else()
        find_program(DUOFORGE_BASH NAMES bash)
    endif()
    if(DUOFORGE_BASH)
        add_test(NAME duoforge.cloud.aws_fuzz_guards
            COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/cloud/aws_fuzz/test_guards.py")
        set_tests_properties(duoforge.cloud.aws_fuzz_guards PROPERTIES TIMEOUT 300
            ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;DUOFORGE_BASH=${DUOFORGE_BASH}")
        # The P1 pilot launcher (tools/cloud/p1_pilot): the same guards with a stub aws, and the user data run with
        # stand-ins for shutdown, aws, git and the workload (the three self-termination mechanisms).
        add_test(NAME duoforge.cloud.p1_pilot_guards
            COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/cloud/p1_pilot/test_guards.py")
        set_tests_properties(duoforge.cloud.p1_pilot_guards PROPERTIES TIMEOUT 600
            ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;DUOFORGE_BASH=${DUOFORGE_BASH}")
        # The Google Cloud watchdog (tools/cloud/gcp_watch): the same, with a stub gcloud and the round with stand-ins.
        add_test(NAME duoforge.cloud.gcp_watch_guards
            COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/cloud/gcp_watch/test_guards.py")
        set_tests_properties(duoforge.cloud.gcp_watch_guards PROPERTIES TIMEOUT 600
            ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;DUOFORGE_BASH=${DUOFORGE_BASH}")
    endif()
    # The table generator refuses move shapes it does not model (no checkout needed).
    add_test(NAME duoforge.data.gen_closure_refusals
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/test_gen_closure.py")
    set_tests_properties(duoforge.data.gen_closure_refusals PROPERTIES TIMEOUT 60
        ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
    # The generated names of the data query API against the macros of the headers and the
    # key() mapping of the trace converter (no checkout needed).
    add_test(NAME duoforge.data.pool_names
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/test_pool_names.py")
    set_tests_properties(duoforge.data.pool_names PROPERTIES TIMEOUT 60
        ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
    # The whole-pool rows (decision 0015 section 4.2) against the committed output of the pinned validator, with code
    # of its own: the ids, the formes and their Mega links, the learnable moves and legal abilities, the move rows and
    # the UNMODELED markers (no checkout needed).
    add_test(NAME duoforge.data.pool_rows
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/datagen/test_pool_rows.py")
    set_tests_properties(duoforge.data.pool_rows PROPERTIES TIMEOUT 60
        ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
endif()

# The vendored upstream license must stay byte-exact.
add_test(NAME duoforge.provenance.pcg_license
    COMMAND "${CMAKE_COMMAND}"
        "-DFILE=${PROJECT_SOURCE_DIR}/third_party/pcg-c-basic/LICENSE.txt"
        -DEXPECTED=b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1
        -P "${PROJECT_SOURCE_DIR}/cmake/checks/file_sha256.cmake")
set_tests_properties(duoforge.provenance.pcg_license PROPERTIES TIMEOUT 30)

include(flow/pcg.cmake)

# Header self-containment (build-time check).
add_library(duoforge_header_check OBJECT header_check/duoforge_h_twice.c)
target_link_libraries(duoforge_header_check PRIVATE duoforge)
duoforge_configure_target(duoforge_header_check)

# extern "C" link check from C++ (not with sanitizers: the C++ target does not
# get the sanitizer link flags).
if(CMAKE_CXX_COMPILER AND NOT DUOFORGE_ENABLE_SANITIZERS AND NOT DUOFORGE_ENABLE_TSAN)
    add_executable(duoforge_cxx_link header_check/cxx_link.cpp)
    target_link_libraries(duoforge_cxx_link PRIVATE duoforge_batch)
    set_target_properties(duoforge_cxx_link PROPERTIES
        CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON CXX_EXTENSIONS OFF)
    if(MSVC)
        target_compile_options(duoforge_cxx_link PRIVATE /W4 /permissive- /utf-8)
        if(DUOFORGE_WARNINGS_AS_ERRORS)
            target_compile_options(duoforge_cxx_link PRIVATE /WX)
        endif()
    else()
        target_compile_options(duoforge_cxx_link PRIVATE -Wall -Wextra -Wpedantic)
        if(DUOFORGE_WARNINGS_AS_ERRORS)
            target_compile_options(duoforge_cxx_link PRIVATE -Werror)
        endif()
    endif()
    add_test(NAME duoforge.api.cxx_link COMMAND duoforge_cxx_link)
    set_tests_properties(duoforge.api.cxx_link PROPERTIES TIMEOUT 30)
endif()

# The Python package (M7, decision 0013), run with DUOFORGE_PYTHON; without
# an interpreter each test reports skipped instead of passing silently.

foreach(_py layout lib equivalence recipes policies_features example learn_numpy live_unit live_client live_search live_arena pkmn_arena bench step_events attract_faint positions replay_unit openings book expert_data expert_teacher expert_contract expert_eval ticks book_preview preview_search data batch_setups learn_v2_numpy teams features_ext encoder6 random_pool bc_numpy encode_c search_numpy search_expand repo_hygiene view vgcpastes_engine replay_teams perft state_layout)
    if(DUOFORGE_PYTHON)
        add_test(NAME duoforge.python.${_py}
            COMMAND "${DUOFORGE_PYTHON}" -m unittest -v python.tests.test_${_py}
            WORKING_DIRECTORY "${PROJECT_SOURCE_DIR}")
        set_tests_properties(duoforge.python.${_py} PROPERTIES LABELS python TIMEOUT 600 ENVIRONMENT
            "DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;DUOFORGE_LAYOUT_DUMP=$<TARGET_FILE:duoforge_layout_dump>;DUOFORGE_STATE_LAYOUT_DUMP=$<TARGET_FILE:duoforge_state_layout_dump>;PYTHONPATH=${PROJECT_SOURCE_DIR}/python;PYTHONDONTWRITEBYTECODE=1")
    else()
        add_test(NAME duoforge.python.${_py}
            COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: DUOFORGE_PYTHON is empty")
        set_tests_properties(duoforge.python.${_py} PROPERTIES LABELS python
            SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
    endif()
endforeach()

# The random training teams (tools/reference/random_teams.py): the paste translation, the composition and the output
# guard with DUOFORGE_PYTHON (it reads pastes with duoforge.teams); with the pinned Showdown also its generator.
if(DUOFORGE_PYTHON)
    add_test(NAME duoforge.reference.random_teams
        COMMAND "${DUOFORGE_PYTHON}" "${PROJECT_SOURCE_DIR}/tools/reference/test_random_teams.py")
    set_tests_properties(duoforge.reference.random_teams PROPERTIES TIMEOUT 120 LABELS python ENVIRONMENT
        "DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;PYTHONDONTWRITEBYTECODE=1")
    if(DUOFORGE_PS_REFERENCE_DIR AND DUOFORGE_NODE)
        add_test(NAME duoforge.reference.random_teams_pin
            COMMAND "${DUOFORGE_PYTHON}" "${PROJECT_SOURCE_DIR}/tools/reference/test_random_teams.py"
                "${DUOFORGE_NODE}" "${DUOFORGE_PS_REFERENCE_DIR}")
        set_tests_properties(duoforge.reference.random_teams_pin PROPERTIES TIMEOUT 300 LABELS reference
            ENVIRONMENT "DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;PYTHONDONTWRITEBYTECODE=1")
    endif()
else()
    add_test(NAME duoforge.reference.random_teams COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: DUOFORGE_PYTHON is empty")
    set_tests_properties(duoforge.reference.random_teams PROPERTIES SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
endif()

# The learner pipeline (decisions 0014, 0017) needs JAX: DUOFORGE_LEARN_PYTHON.
foreach(_learn learn learn_v2 bc search honest pkmn_arena_net luck ledger pfsp value_rows distill collect_expert learner_contract p1_eval encoder6_net random_pool_train mmd)
    if(DUOFORGE_LEARN_PYTHON)
        add_test(NAME duoforge.python.${_learn}
            COMMAND "${DUOFORGE_LEARN_PYTHON}" -m unittest -v python.tests.test_${_learn}
            WORKING_DIRECTORY "${PROJECT_SOURCE_DIR}")
        set_tests_properties(duoforge.python.${_learn} PROPERTIES LABELS "python;learn" TIMEOUT 900 ENVIRONMENT
            "DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;PYTHONPATH=${PROJECT_SOURCE_DIR}/python;PYTHONDONTWRITEBYTECODE=1")
    else()
        add_test(NAME duoforge.python.${_learn}
            COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: DUOFORGE_LEARN_PYTHON is empty")
        set_tests_properties(duoforge.python.${_learn} PROPERTIES LABELS "python;learn"
            SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
    endif()
endforeach()

# Source lint and its self-test.
add_test(NAME duoforge.lint.sources
    COMMAND "${CMAKE_COMMAND}" "-DROOT=${PROJECT_SOURCE_DIR}"
        -P "${PROJECT_SOURCE_DIR}/cmake/checks/lint_sources.cmake")
add_test(NAME duoforge.lint.selftest
    COMMAND "${CMAKE_COMMAND}" "-DROOT=${PROJECT_SOURCE_DIR}"
        "-DWORK=${CMAKE_CURRENT_BINARY_DIR}/lint_selftest"
        -P "${PROJECT_SOURCE_DIR}/cmake/checks/lint_selftest.cmake")
set_tests_properties(duoforge.lint.sources PROPERTIES TIMEOUT 60)
set_tests_properties(duoforge.lint.selftest PROPERTIES TIMEOUT 60)

# No writable static storage in the library (ELF toolchains only).
add_test(NAME duoforge.lint.no_mutable_globals
    COMMAND "${CMAKE_COMMAND}" "-DOBJDUMP=${CMAKE_OBJDUMP}" "-DLIB=$<TARGET_FILE:duoforge>"
        "-DSANITIZERS=${DUOFORGE_ENABLE_SANITIZERS}"
        -P "${PROJECT_SOURCE_DIR}/cmake/checks/no_mutable_globals.cmake")
set_tests_properties(duoforge.lint.no_mutable_globals PROPERTIES
    TIMEOUT 60 SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")

# Sanitizer liveness canaries.
if(DUOFORGE_ENABLE_SANITIZERS)
    foreach(_c IN ITEMS ubsan asan)
        add_executable(duoforge_canary_${_c} canary/canary_${_c}.c)
        duoforge_configure_target(duoforge_canary_${_c})
        add_test(NAME duoforge.sanitizer.canary_${_c} COMMAND duoforge_canary_${_c})
    endforeach()
    # In optimized builds UBSan's object-size check would abort before ASan
    # reports; the ASan canary must prove ASan alone.
    target_compile_options(duoforge_canary_asan PRIVATE -fno-sanitize=undefined)
    # halt_on_error=0 is mandatory: only the compile flag
    # -fno-sanitize-recover=all may stop this canary.
    set_tests_properties(duoforge.sanitizer.canary_ubsan PROPERTIES
        TIMEOUT 30 LABELS sanitizer-canary
        ENVIRONMENT "UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=0"
        PASS_REGULAR_EXPRESSION "runtime error: signed integer overflow"
        FAIL_REGULAR_EXPRESSION "CANARY_SURVIVED")
    set_tests_properties(duoforge.sanitizer.canary_asan PROPERTIES
        TIMEOUT 30 LABELS sanitizer-canary
        ENVIRONMENT "ASAN_OPTIONS=detect_leaks=0"
        PASS_REGULAR_EXPRESSION "AddressSanitizer: heap-buffer-overflow"
        FAIL_REGULAR_EXPRESSION "CANARY_SURVIVED")
endif()
# The state model's pool table hash equals the hash that duoforge.data.pool_tables proves for the generated tables, so
# that a step which regenerates the tables cannot leave the model's POOL fingerprints stale (no checkout needed).
# The state model's POOL tail (its --pool-tail part only) derives the envelope, the example and every sweep[] row that
# duoforge.state.pool_tail pins, so that a step which adds a tail byte or rule cannot leave the model behind.
if(Python3_Interpreter_FOUND)
    add_test(NAME duoforge.data.model_pool_hash
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/state_model/test_model_pins.py" PoolTableHash)
    set_tests_properties(duoforge.data.model_pool_hash PROPERTIES TIMEOUT 60
        ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
    add_test(NAME duoforge.state.model_pool_tail
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/state_model/test_model_pins.py" PoolTailSweep)
    set_tests_properties(duoforge.state.model_pool_tail PROPERTIES TIMEOUT 120
        ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
endif()
