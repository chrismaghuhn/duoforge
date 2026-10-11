# C tests for flow. Included from tests/ so binary and fixture paths stay unchanged.
# Black-box smoke test (M0), kept under its original name.
add_executable(duoforge_smoke_test flow/smoke_test.c)
target_link_libraries(duoforge_smoke_test PRIVATE duoforge)
duoforge_configure_target(duoforge_smoke_test)
add_test(NAME duoforge_smoke_test COMMAND duoforge_smoke_test)
set_tests_properties(duoforge_smoke_test PROPERTIES TIMEOUT 30)

# The residual handler list: when the order of a Pokemon's volatiles (not stored) cannot change the outcome (brute force).
# Its 40000 random lists run in four shards (the trials [i * 10000, (i + 1) * 10000)): in one test they took 125 to
# 177 s under ASan+UBSan (Debug, a loaded machine, 2026-10-09), over the 120 s limit; one shard takes 13 to 28 s there.
foreach(_shard RANGE 3)
    duoforge_add_test(NAME duoforge.combat.residual_order.${_shard} SOURCES flow/test_residual_order.c WHITEBOX TIMEOUT 120
        ARGS ${_shard} 4)
endforeach()

duoforge_add_test(NAME duoforge.rng.kat SOURCES flow/test_rng_kat.c WHITEBOX)
duoforge_add_test(NAME duoforge.rng.contract SOURCES flow/test_rng_contract.c WHITEBOX)
duoforge_add_test(NAME duoforge.state.setup SOURCES flow/test_setup.c WHITEBOX)
duoforge_add_test(NAME duoforge.state.identity SOURCES flow/test_identity.c WHITEBOX)
duoforge_add_test(NAME duoforge.state.invariants SOURCES flow/test_invariants.c WHITEBOX)
duoforge_add_test(NAME duoforge.state.setup_sweep SOURCES flow/test_setup_sweep.c TIMEOUT 60)

duoforge_add_test(NAME duoforge.state.clone_equal SOURCES flow/test_clone_equal.c WHITEBOX)
duoforge_add_test(NAME duoforge.codec.golden SOURCES flow/test_codec_golden.c WHITEBOX)
duoforge_add_test(NAME duoforge.codec.negative SOURCES flow/test_codec_negative.c WHITEBOX)
duoforge_add_test(NAME duoforge.codec.mutation SOURCES flow/test_codec_mutation.c WHITEBOX TIMEOUT 180)
duoforge_add_test(NAME duoforge.api.atomicity SOURCES flow/test_api_atomicity.c WHITEBOX)

# M2: requests, joint commands, step, contract minimum tests.
duoforge_add_test(NAME duoforge.request.domain SOURCES flow/test_request_domain.c WHITEBOX TIMEOUT 60)
duoforge_add_test(NAME duoforge.request.step SOURCES flow/test_step.c WHITEBOX TIMEOUT 60)
duoforge_add_test(NAME duoforge.request.contract SOURCES flow/test_contract.c WHITEBOX TIMEOUT 60)
duoforge_add_test(NAME duoforge.request.information SOURCES flow/test_information.c WHITEBOX TIMEOUT 60)
duoforge_add_test(NAME duoforge.request.accepts SOURCES flow/test_step_accepts.c TIMEOUT 120)
duoforge_add_test(NAME duoforge.request.query_checks SOURCES flow/test_query_checks.c WHITEBOX)
duoforge_add_test(NAME duoforge.request.candidates_digest SOURCES flow/test_candidates_digest.c TIMEOUT 120)
duoforge_add_test(NAME duoforge.request.factored SOURCES flow/test_factored.c TIMEOUT 120)
duoforge_add_test(NAME duoforge.combat.turn SOURCES flow/test_turn.c WHITEBOX TIMEOUT 120)
duoforge_add_test(NAME duoforge.state.pool_g46_party SOURCES flow/test_pool_g46_party.c WHITEBOX TIMEOUT 120)
# The queued action of a fainted Pokemon: no ability and no item of it counts for its priority and Speed (d04 to d06).
duoforge_add_test(NAME duoforge.state.pool_fainted_holder SOURCES flow/test_pool_fainted_holder.c WHITEBOX TIMEOUT 60)
