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
    COMMAND "${DUOFORGE_NODE}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_ps_trace_run.js"
        "${DUOFORGE_PS_REFERENCE_DIR}")
set_tests_properties(duoforge.reference.trace_run PROPERTIES TIMEOUT 600 LABELS reference)
# The persistent worker (differential loop): its JSON-lines protocol over raw pipes.
add_test(NAME duoforge.reference.worker_protocol
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_ps_worker.py"
        "${DUOFORGE_NODE}" "${DUOFORGE_PS_REFERENCE_DIR}")
set_tests_properties(duoforge.reference.worker_protocol PROPERTIES TIMEOUT 120 LABELS reference
    ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
# Random play (the worker's "play"): the policy generator, how a choice is drawn,
# judged by Showdown and enumerated, and real battles of the committed teams.
add_test(NAME duoforge.reference.play_policy
    COMMAND "${DUOFORGE_NODE}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_ps_play.js"
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
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_diff_random_smoke.py"
        "${DUOFORGE_NODE}" "${DUOFORGE_PS_REFERENCE_DIR}" "$<TARGET_FILE:duoforge_diff_runner>"
        "${CMAKE_CURRENT_BINARY_DIR}/diff_random_smoke")
set_tests_properties(duoforge.reference.diff_random_smoke PROPERTIES TIMEOUT 600 LABELS reference
    ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
# The domain check end to end: 8 battles with every request sampled (--domain-rate 1.0),
# the engine's candidates against what Showdown accepts for the side, before every step;
# the same battles without the check come to the same: sampling changes nothing else.
add_test(NAME duoforge.reference.diff_domain_smoke
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_diff_domain_smoke.py"
        "${DUOFORGE_NODE}" "${DUOFORGE_PS_REFERENCE_DIR}" "$<TARGET_FILE:duoforge_diff_runner>"
        "${CMAKE_CURRENT_BINARY_DIR}/diff_domain_smoke")
set_tests_properties(duoforge.reference.diff_domain_smoke PROPERTIES TIMEOUT 600 LABELS reference
    ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
# A team file of the random mode (--team): six battles of one that equals team A are those of team A,
# their kept battles byte for byte.
add_test(NAME duoforge.reference.diff_team_smoke
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_diff_team_smoke.py"
        "${DUOFORGE_NODE}" "${DUOFORGE_PS_REFERENCE_DIR}" "$<TARGET_FILE:duoforge_diff_runner>"
        "${CMAKE_CURRENT_BINARY_DIR}/diff_team_smoke")
set_tests_properties(duoforge.reference.diff_team_smoke PROPERTIES TIMEOUT 600 LABELS reference
    ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
# Random play under the POOL data kind (step G5): a team that carries U-turn (an id of the pool tables, which
# Team C does not have) plays ten battles that all PASS under POOL, some with [from] U-turn.
add_test(NAME duoforge.reference.diff_pool_smoke
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_diff_pool_smoke.py"
        "${DUOFORGE_NODE}" "${DUOFORGE_PS_REFERENCE_DIR}" "$<TARGET_FILE:duoforge_diff_runner>"
        "${CMAKE_CURRENT_BINARY_DIR}/diff_pool_smoke")
set_tests_properties(duoforge.reference.diff_pool_smoke PROPERTIES TIMEOUT 600 LABELS reference
    ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
# Step G7: a team with Wide Guard plays twenty battles that all PASS under POOL, every request sampled for the
# domain check, some with a guard that stops a spread move.
add_test(NAME duoforge.reference.diff_wide_guard_smoke
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_diff_wide_guard_smoke.py"
        "${DUOFORGE_NODE}" "${DUOFORGE_PS_REFERENCE_DIR}" "$<TARGET_FILE:duoforge_diff_runner>"
        "${CMAKE_CURRENT_BINARY_DIR}/diff_wide_guard_smoke")
set_tests_properties(duoforge.reference.diff_wide_guard_smoke PROPERTIES TIMEOUT 900 LABELS reference
    ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
# The paste importer (data/teams) with the pinned pokedex: the facts it reads, the owner's raw pastes of
# decision 0004, the registry as a fixed point of the importer, and the command line end to end.
add_test(NAME duoforge.reference.import_paste_pin
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_import_paste_pin.py"
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
