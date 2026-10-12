# Replay Python tests; CTest names and execution settings stay unchanged.
duoforge_add_python_test(replay_unit python.tests.replay.test_replay_unit)
duoforge_add_python_test(openings python.tests.replay.test_openings)
duoforge_add_python_test(book python.tests.replay.test_book)
duoforge_add_python_test(replay_teams python.tests.replay.test_replay_teams)
duoforge_add_reference_python_test(replay python.tests.replay.test_replay)
