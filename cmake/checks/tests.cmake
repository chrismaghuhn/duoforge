# Source lint and its self-test.
add_test(NAME duoforge.lint.sources
    COMMAND "${CMAKE_COMMAND}" "-DROOT=${PROJECT_SOURCE_DIR}"
        -P "${PROJECT_SOURCE_DIR}/cmake/checks/lint_sources.cmake")
duoforge_label_test(duoforge.lint.sources full tools)
add_test(NAME duoforge.lint.selftest
    COMMAND "${CMAKE_COMMAND}" "-DROOT=${PROJECT_SOURCE_DIR}"
        "-DWORK=${CMAKE_CURRENT_BINARY_DIR}/lint_selftest"
        -P "${PROJECT_SOURCE_DIR}/cmake/checks/lint_selftest.cmake")
duoforge_label_test(duoforge.lint.selftest quick tools)
set_tests_properties(duoforge.lint.sources PROPERTIES TIMEOUT 60)
set_tests_properties(duoforge.lint.selftest PROPERTIES TIMEOUT 60)

# No writable static storage in the library (ELF toolchains only).
add_test(NAME duoforge.lint.no_mutable_globals
    COMMAND "${CMAKE_COMMAND}" "-DOBJDUMP=${CMAKE_OBJDUMP}" "-DLIB=$<TARGET_FILE:duoforge>"
        "-DSANITIZERS=${DUOFORGE_ENABLE_SANITIZERS}"
        -P "${PROJECT_SOURCE_DIR}/cmake/checks/no_mutable_globals.cmake")
duoforge_label_test(duoforge.lint.no_mutable_globals quick tools)
set_tests_properties(duoforge.lint.no_mutable_globals PROPERTIES
    TIMEOUT 60 SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")

