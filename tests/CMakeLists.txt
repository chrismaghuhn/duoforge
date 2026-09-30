# Every registered test is finite and carries an explicit timeout.

add_executable(pbd_smoke_test smoke/smoke_version.c)
target_link_libraries(pbd_smoke_test PRIVATE pbd::core)
set_target_properties(pbd_smoke_test PROPERTIES
    C_STANDARD 17
    C_STANDARD_REQUIRED ON
    C_EXTENSIONS OFF)
pbd_configure_target(pbd_smoke_test)

add_test(NAME pbd.smoke.version COMMAND pbd_smoke_test)
set_tests_properties(pbd.smoke.version PROPERTIES TIMEOUT 30)

# Source-lock / support-manifest scaffolding checks (CMake script, no extra
# dependencies). The negative fixtures must be rejected by the checker.
set(_pbd_manifest_checker "${CMAKE_CURRENT_SOURCE_DIR}/manifest/check_manifests.cmake")
set(_pbd_manifest_fixtures "${CMAKE_CURRENT_SOURCE_DIR}/manifest/fixtures")

add_test(NAME pbd.manifest.scaffold
    COMMAND "${CMAKE_COMMAND}"
        "-DPBD_SOURCE_LOCK=${PROJECT_SOURCE_DIR}/manifests/source_lock.json"
        "-DPBD_SUPPORT_MANIFEST=${PROJECT_SOURCE_DIR}/manifests/support_manifest.json"
        -P "${_pbd_manifest_checker}")

foreach(_pbd_bad IN ITEMS
        pinned_placeholder_revision
        unpinned_with_revision
        certified_while_unpinned)
    add_test(NAME pbd.manifest.rejects.${_pbd_bad}
        COMMAND "${CMAKE_COMMAND}"
            "-DPBD_SOURCE_LOCK=${_pbd_manifest_fixtures}/${_pbd_bad}/source_lock.json"
            "-DPBD_SUPPORT_MANIFEST=${_pbd_manifest_fixtures}/${_pbd_bad}/support_manifest.json"
            -P "${_pbd_manifest_checker}")
    # Must fail with the checker's own diagnostic, not e.g. a missing file.
    set_tests_properties(pbd.manifest.rejects.${_pbd_bad} PROPERTIES
        PASS_REGULAR_EXPRESSION "pbd-manifest-check: REJECTED")
endforeach()

set_tests_properties(
    pbd.manifest.scaffold
    pbd.manifest.rejects.pinned_placeholder_revision
    pbd.manifest.rejects.unpinned_with_revision
    pbd.manifest.rejects.certified_while_unpinned
    PROPERTIES TIMEOUT 30)
