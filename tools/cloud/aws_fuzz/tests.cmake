        add_test(NAME duoforge.cloud.aws_fuzz_guards
            COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/cloud/aws_fuzz/test_guards.py")
        set_tests_properties(duoforge.cloud.aws_fuzz_guards PROPERTIES TIMEOUT 300
            ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;DUOFORGE_BASH=${DUOFORGE_BASH}")
