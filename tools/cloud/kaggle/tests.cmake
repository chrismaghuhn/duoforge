        # tools/cloud/kaggle (#458): offline, a stub kaggle first on the PATH; nothing reaches Kaggle. The pseudonym
        # tests read and write the dataset's npz files, so the test runs with DUOFORGE_PYTHON (NumPy 2) and reports
        # skipped without it; ci-no-skip keeps a job that sets it from skipping it.
        if(DUOFORGE_PYTHON)
            add_test(NAME duoforge.cloud.kaggle
                COMMAND "${DUOFORGE_PYTHON}" "${PROJECT_SOURCE_DIR}/tools/cloud/kaggle/test_kaggle.py")
            set_tests_properties(duoforge.cloud.kaggle PROPERTIES TIMEOUT 300 ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1")
        else()
            add_test(NAME duoforge.cloud.kaggle
                COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: DUOFORGE_PYTHON is empty")
            set_tests_properties(duoforge.cloud.kaggle PROPERTIES SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
        endif()
        duoforge_label_test(duoforge.cloud.kaggle full tools ci-no-skip)
