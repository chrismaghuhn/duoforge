# Sanitizer liveness canaries.
if(DUOFORGE_ENABLE_SANITIZERS)
    foreach(_c IN ITEMS ubsan asan)
        add_executable(duoforge_canary_${_c} canary/canary_${_c}.c)
        duoforge_configure_target(duoforge_canary_${_c})
        add_test(NAME duoforge.sanitizer.canary_${_c} COMMAND duoforge_canary_${_c})
        duoforge_label_test(duoforge.sanitizer.canary_${_c} quick tools sanitizer-canary)
    endforeach()
    # In optimized builds UBSan's object-size check would abort before ASan
    # reports; the ASan canary must prove ASan alone.
    target_compile_options(duoforge_canary_asan PRIVATE -fno-sanitize=undefined)
    # halt_on_error=0 is mandatory: only the compile flag
    # -fno-sanitize-recover=all may stop this canary.
    set_tests_properties(duoforge.sanitizer.canary_ubsan PROPERTIES
        TIMEOUT 30
        ENVIRONMENT "UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=0"
        PASS_REGULAR_EXPRESSION "runtime error: signed integer overflow"
        FAIL_REGULAR_EXPRESSION "CANARY_SURVIVED")
    set_tests_properties(duoforge.sanitizer.canary_asan PROPERTIES
        TIMEOUT 30
        ENVIRONMENT "ASAN_OPTIONS=detect_leaks=0"
        PASS_REGULAR_EXPRESSION "AddressSanitizer: heap-buffer-overflow"
        FAIL_REGULAR_EXPRESSION "CANARY_SURVIVED")
endif()
