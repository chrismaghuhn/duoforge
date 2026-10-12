# Live Python tests; CTest names and execution settings stay unchanged.
duoforge_add_python_test(live_unit python.tests.live.test_live_unit)
duoforge_add_python_test(live_client python.tests.live.test_live_client)
duoforge_add_python_test(live_search python.tests.live.test_live_search)
duoforge_add_python_test(live_arena python.tests.live.test_live_arena)
duoforge_add_python_test(pkmn_arena python.tests.live.test_pkmn_arena)
duoforge_add_learner_test(pkmn_arena_net python.tests.live.test_pkmn_arena_net)
duoforge_add_reference_python_test(live python.tests.live.test_live)
