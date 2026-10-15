# Private synthetic integer oracle, no model load or trained parameters.
duoforge_add_test(NAME duoforge.eval.kernels SOURCES eval/test_kernels.c WHITEBOX TIER quick AREA engine)
# Clang's GNU-style driver can target the MSVC runtime/linker. That target
# cannot use GNU --wrap; keep the allocation watch on GNU-compatible linkers.
if(CMAKE_C_COMPILER_ID MATCHES "^(GNU|Clang)$" AND NOT MSVC
        AND NOT CMAKE_C_SIMULATE_ID STREQUAL "MSVC")
    target_compile_definitions(duoforge_eval_kernels PRIVATE DF_EVAL_ALLOC_HOOKS)
    target_link_options(duoforge_eval_kernels PRIVATE
        "LINKER:--wrap=malloc" "LINKER:--wrap=calloc" "LINKER:--wrap=realloc" "LINKER:--wrap=free")
endif()
if(DUOFORGE_PYTHON)
    add_test(NAME duoforge.eval.integer_oracle COMMAND "${DUOFORGE_PYTHON}"
        "${PROJECT_SOURCE_DIR}/tools/eval/tests/integer_oracle.py" "$<TARGET_FILE:duoforge_eval_kernels>")
    duoforge_label_test(duoforge.eval.integer_oracle quick engine python ci-no-skip)
    set_tests_properties(duoforge.eval.integer_oracle PROPERTIES TIMEOUT 60)
    add_test(NAME duoforge.eval.input_oracle COMMAND "${DUOFORGE_PYTHON}"
        "${PROJECT_SOURCE_DIR}/tools/eval/tests/input_oracle.py" "$<TARGET_FILE:duoforge_eval_kernels>")
    duoforge_label_test(duoforge.eval.input_oracle quick engine python ci-no-skip)
    set_tests_properties(duoforge.eval.input_oracle PROPERTIES TIMEOUT 60)
    add_test(NAME duoforge.eval.input_layout COMMAND "${DUOFORGE_PYTHON}"
        "${PROJECT_SOURCE_DIR}/tools/eval/input_layout.py" --check)
    duoforge_label_test(duoforge.eval.input_layout quick tools python ci-no-skip)
    set_tests_properties(duoforge.eval.input_layout PROPERTIES TIMEOUT 60)
else()
    foreach(_name IN ITEMS integer_oracle input_oracle input_layout)
        add_test(NAME duoforge.eval.${_name} COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: DUOFORGE_PYTHON is empty")
        if(_name STREQUAL "input_layout")
            set(_area tools)
        else()
            set(_area engine)
        endif()
        duoforge_label_test(duoforge.eval.${_name} quick ${_area} python ci-no-skip)
        set_tests_properties(duoforge.eval.${_name} PROPERTIES TIMEOUT 60 SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
    endforeach()
endif()
