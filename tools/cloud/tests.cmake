# The cloud launch scripts print decimals with a dot under a German locale too (MaxPrice=1.50, not 1,50): the price,
# cost cap and request of tools/cloud/aws_fuzz and tools/cloud/p1_pilot, and both guard suites, under de_DE.UTF-8. It
# reports itself skipped without that locale; ci-no-skip keeps the job that generates it from skipping it.
add_test(NAME duoforge.cloud.numeric_locale
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/cloud/test_numeric_locale.py")
duoforge_label_test(duoforge.cloud.numeric_locale full tools ci-no-skip)
set_tests_properties(duoforge.cloud.numeric_locale PROPERTIES TIMEOUT 600 SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:"
    ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;DUOFORGE_BASH=${DUOFORGE_BASH}")
