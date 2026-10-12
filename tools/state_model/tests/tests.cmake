# The state model's pool table hash equals the hash that duoforge.data.pool_tables proves for the generated tables, so
# that a step which regenerates the tables cannot leave the model's POOL fingerprints stale (no checkout needed).
# The state model's POOL tail (its --pool-tail part only) derives the envelope, the example and every sweep[] row that
# duoforge.state.pool_tail pins, so that a step which adds a tail byte or rule cannot leave the model behind.
if(Python3_Interpreter_FOUND)
    add_test(NAME duoforge.data.model_pool_hash
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/state_model/tests/test_model_pins.py" PoolTableHash)
    set_tests_properties(duoforge.data.model_pool_hash PROPERTIES TIMEOUT 60
        ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
    add_test(NAME duoforge.state.model_pool_tail
        COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/state_model/tests/test_model_pins.py" PoolTailSweep)
    set_tests_properties(duoforge.state.model_pool_tail PROPERTIES TIMEOUT 120
        ENVIRONMENT PYTHONDONTWRITEBYTECODE=1)
endif()
