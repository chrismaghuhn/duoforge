# Evaluation-run Python tests (restructure step 8): the run helper and the forwarders of the moved entry points.
duoforge_add_python_test(runs python.tests.eval.test_runs quick eval)
duoforge_add_learner_test(eval_forwarders python.tests.eval.test_forwarders full eval)
