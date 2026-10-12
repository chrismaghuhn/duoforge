# The P1 pilot launcher (tools/cloud/p1_pilot): the same guards with a stub aws, and the user data run with
# stand-ins for shutdown, aws, git and the workload (the three self-termination mechanisms).
add_test(NAME duoforge.cloud.p1_pilot_guards
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/cloud/p1_pilot/tests/test_guards.py")
duoforge_label_test(duoforge.cloud.p1_pilot_guards full tools)
set_tests_properties(duoforge.cloud.p1_pilot_guards PROPERTIES TIMEOUT 600
    ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;DUOFORGE_BASH=${DUOFORGE_BASH}")
