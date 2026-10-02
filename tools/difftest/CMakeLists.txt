# The differential runner (docs/research/expansion/differential-testing.md,
# component 3): the records reader, shared with the sync test of
# tests/CMakeLists.txt, and the runner. White-box like the conformance test,
# and built with the tests, whose support code has the comparators.

add_library(duoforge_difftest_records STATIC records.c)
target_include_directories(duoforge_difftest_records PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}"
    "${PROJECT_SOURCE_DIR}/tests"
    "${PROJECT_SOURCE_DIR}/src")
target_link_libraries(duoforge_difftest_records PUBLIC duoforge)
duoforge_configure_target(duoforge_difftest_records)
