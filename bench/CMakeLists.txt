# Benchmark API, action tally and driver (docs/decisions/0008). The reference
# teams come from the test support, so the benchmark builds with the tests.

add_custom_target(duoforge_bench_revision
    COMMAND ${CMAKE_COMMAND} -DSRC=${PROJECT_SOURCE_DIR} -DOUT=${CMAKE_CURRENT_BINARY_DIR}/bench_revision.h
            -P ${PROJECT_SOURCE_DIR}/cmake/bench_revision.cmake
    BYPRODUCTS ${CMAKE_CURRENT_BINARY_DIR}/bench_revision.h
    COMMENT "Writing the benchmark revision")

add_library(duoforge_bench_lib STATIC bench.c tally.c)
target_include_directories(duoforge_bench_lib PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")
target_link_libraries(duoforge_bench_lib PUBLIC duoforge duoforge_test_support)
duoforge_configure_target(duoforge_bench_lib)

string(TOUPPER "${CMAKE_BUILD_TYPE}" _bench_bt)
set(_bench_flags "${CMAKE_C_FLAGS} ${CMAKE_C_FLAGS_${_bench_bt}}")
string(STRIP "${_bench_flags}" _bench_flags)

add_executable(duoforge_bench main.c)
add_dependencies(duoforge_bench duoforge_bench_revision)
target_include_directories(duoforge_bench PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
target_link_libraries(duoforge_bench PRIVATE duoforge_bench_lib)
target_compile_definitions(duoforge_bench PRIVATE
    "DFB_BUILD_TYPE=\"$<CONFIG>\""
    "DFB_C_COMPILER=\"${CMAKE_C_COMPILER_ID} ${CMAKE_C_COMPILER_VERSION}\""
    "DFB_C_FLAGS=\"${_bench_flags}\"")
duoforge_configure_target(duoforge_bench)
if(WIN32)
    # getenv, fopen and gmtime are fine in a driver (the MSVC runtime warns,
    # also under Clang).
    target_compile_definitions(duoforge_bench PRIVATE _CRT_SECURE_NO_WARNINGS)
endif()

# A functional smoke run (tiny workload; it checks the report, not the speed).
add_test(NAME duoforge.bench.smoke
    COMMAND duoforge_bench --battles 2 --repetitions 1 --warmup 0 --out ${CMAKE_CURRENT_BINARY_DIR}/bench_smoke.json)
set_tests_properties(duoforge.bench.smoke PROPERTIES TIMEOUT 120 LABELS bench)

# The action tally on random real-team battles.
add_executable(duoforge_bench_tally test_tally.c)
target_link_libraries(duoforge_bench_tally PRIVATE duoforge_bench_lib)
duoforge_configure_target(duoforge_bench_tally)
add_test(NAME duoforge.bench.tally COMMAND duoforge_bench_tally)
set_tests_properties(duoforge.bench.tally PROPERTIES TIMEOUT 60 LABELS bench)
