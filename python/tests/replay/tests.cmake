# Replay Python tests; CTest names and execution settings stay unchanged.
duoforge_add_python_test(replay_unit python.tests.replay.test_replay_unit full replay)
duoforge_add_python_test(openings python.tests.replay.test_openings quick replay)
duoforge_add_python_test(book python.tests.replay.test_book quick replay)
duoforge_add_python_test(replay_teams python.tests.replay.test_replay_teams quick replay)
duoforge_add_reference_python_test(replay python.tests.replay.test_replay reference replay)
