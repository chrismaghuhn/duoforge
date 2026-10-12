        add_test(NAME duoforge.cloud.aws_fuzz_guards
            COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/cloud/aws_fuzz/test_guards.py")
        duoforge_label_test(duoforge.cloud.aws_fuzz_guards full tools)
        set_tests_properties(duoforge.cloud.aws_fuzz_guards PROPERTIES TIMEOUT 300
            ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;DUOFORGE_BASH=${DUOFORGE_BASH}")
