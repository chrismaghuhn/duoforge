# The certified dataset of the closure matchups (docs/decisions/0010, M5
# step 4). The reference teams come from the test support, so the tool
# builds with the tests.

add_executable(duoforge_certify certify.c)
target_link_libraries(duoforge_certify PRIVATE duoforge duoforge_test_support)
duoforge_configure_target(duoforge_certify)
if(WIN32)
    target_compile_definitions(duoforge_certify PRIVATE _CRT_SECURE_NO_WARNINGS)
endif()

add_test(NAME duoforge.certify.dataset
    COMMAND duoforge_certify verify "${PROJECT_SOURCE_DIR}/docs/certification/closure-v1/dataset.txt")
set_tests_properties(duoforge.certify.dataset PROPERTIES TIMEOUT 600 LABELS certify)
foreach(_kind IN ITEMS digest choice seed)
    add_test(NAME duoforge.certify.negative.${_kind}
        COMMAND "${CMAKE_COMMAND}" "-DCERTIFY=$<TARGET_FILE:duoforge_certify>"
            "-DDATASET=${PROJECT_SOURCE_DIR}/docs/certification/closure-v1/dataset.txt"
            "-DOUT=${CMAKE_CURRENT_BINARY_DIR}/dataset_${_kind}.txt" "-DKIND=${_kind}"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/mutate_check.cmake")
    set_tests_properties(duoforge.certify.negative.${_kind} PROPERTIES TIMEOUT 600 LABELS certify)
endforeach()
