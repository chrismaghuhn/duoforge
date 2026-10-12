# The vendored upstream license must stay byte-exact.
add_test(NAME duoforge.provenance.pcg_license
    COMMAND "${CMAKE_COMMAND}"
        "-DFILE=${PROJECT_SOURCE_DIR}/third_party/pcg-c-basic/LICENSE.txt"
        -DEXPECTED=b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1
        -P "${PROJECT_SOURCE_DIR}/cmake/checks/file_sha256.cmake")
duoforge_label_test(duoforge.provenance.pcg_license quick data)
set_tests_properties(duoforge.provenance.pcg_license PROPERTIES TIMEOUT 30)
