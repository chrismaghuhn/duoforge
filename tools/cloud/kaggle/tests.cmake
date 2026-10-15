        # tools/cloud/kaggle (#458): offline, a stub kaggle first on the PATH; nothing reaches Kaggle.
        add_test(NAME duoforge.cloud.kaggle
            COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/cloud/kaggle/test_kaggle.py")
        duoforge_label_test(duoforge.cloud.kaggle full tools)
        set_tests_properties(duoforge.cloud.kaggle PROPERTIES TIMEOUT 300 ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1")
