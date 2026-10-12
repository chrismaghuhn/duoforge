        # The Google Cloud watchdog (tools/cloud/gcp_watch): the same, with a stub gcloud and the round with stand-ins.
        add_test(NAME duoforge.cloud.gcp_watch_guards
            COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/cloud/gcp_watch/test_guards.py")
        duoforge_label_test(duoforge.cloud.gcp_watch_guards full tools)
        set_tests_properties(duoforge.cloud.gcp_watch_guards PROPERTIES TIMEOUT 600
            ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;DUOFORGE_BASH=${DUOFORGE_BASH}")
