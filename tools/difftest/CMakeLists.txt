# The differential runner (docs/research/expansion/differential-testing.md,
# component 3): the records reader and the domain check (the engine's
# candidates against the reference's accepted choices), shared with the tests
# of tests/CMakeLists.txt, and the runner. White-box like the conformance test,
# and built with the tests, whose support code has the comparators.

add_library(duoforge_difftest_records STATIC records.c domain.c)
target_include_directories(duoforge_difftest_records PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}"
    "${PROJECT_SOURCE_DIR}/tests"
    "${PROJECT_SOURCE_DIR}/src")
target_link_libraries(duoforge_difftest_records PUBLIC duoforge)
duoforge_configure_target(duoforge_difftest_records)

add_executable(duoforge_diff_runner diff_runner.c)
target_link_libraries(duoforge_diff_runner PRIVATE duoforge_difftest_records duoforge_test_support duoforge_batch)
duoforge_configure_target(duoforge_diff_runner)
if(WIN32)
    # fopen is fine in a tool (the MSVC runtime warns, also under Clang).
    target_compile_definitions(duoforge_diff_runner PRIVATE _CRT_SECURE_NO_WARNINGS)
endif()
