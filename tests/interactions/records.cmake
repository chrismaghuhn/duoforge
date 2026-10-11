duoforge_add_test(NAME duoforge.reference.runner_records SOURCES interactions/test_runner_records.c WHITEBOX
    LIBS duoforge_difftest_records TIMEOUT 60 ARGS "${_records_dir}/closure.records")
duoforge_add_test(NAME duoforge.reference.runner_records_team_c SOURCES interactions/test_runner_records.c WHITEBOX
    LIBS duoforge_difftest_records TIMEOUT 60 ARGS "${_records_dir}/team_c.records")
target_compile_definitions(duoforge_reference_runner_records_team_c PRIVATE DF_CONFORMANCE_TEAM_C)
duoforge_add_test(NAME duoforge.reference.runner_records_pool SOURCES interactions/test_runner_records.c WHITEBOX
    LIBS duoforge_difftest_records TIMEOUT 60 ARGS "${_records_dir}/pool.records")
target_compile_definitions(duoforge_reference_runner_records_pool PRIVATE DF_CONFORMANCE_POOL_DATA)
set_tests_properties(duoforge.reference.runner_records duoforge.reference.runner_records_team_c
    duoforge.reference.runner_records_pool PROPERTIES FIXTURES_REQUIRED duoforge_conformance_records)
if(WIN32)
    # fopen is fine in a test (the MSVC runtime warns, also under Clang).
    target_compile_definitions(duoforge_reference_runner_records PRIVATE _CRT_SECURE_NO_WARNINGS)
    target_compile_definitions(duoforge_reference_runner_records_team_c PRIVATE _CRT_SECURE_NO_WARNINGS)
    target_compile_definitions(duoforge_reference_runner_records_pool PRIVATE _CRT_SECURE_NO_WARNINGS)
endif()
