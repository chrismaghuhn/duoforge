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

duoforge_add_test(NAME duoforge.eval.lifecycle SOURCES eval/test_lifecycle.c WHITEBOX LIBS duoforge_batch TIMEOUT 30 TIER quick AREA engine LABELS ci-tsan)
if(UNIX AND NOT APPLE AND CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_definitions(duoforge_eval_lifecycle PRIVATE DF_EVAL_ALLOC_WRAP)
    target_link_options(duoforge_eval_lifecycle PRIVATE
        "LINKER:--wrap=malloc" "LINKER:--wrap=calloc" "LINKER:--wrap=realloc" "LINKER:--wrap=free")
endif()
find_package(Python3 COMPONENTS Interpreter)
if(Python3_Interpreter_FOUND)
    add_test(NAME duoforge.eval.artifact COMMAND "${Python3_EXECUTABLE}"
        "${PROJECT_SOURCE_DIR}/tools/eval/tests/test_artifact.py" "$<TARGET_FILE:duoforge_eval_lifecycle>")
    set_tests_properties(duoforge.eval.artifact PROPERTIES TIMEOUT 60 ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1")
    duoforge_label_test(duoforge.eval.artifact quick tools ci-no-skip ci-tsan)
endif()

# E3n fixed-point normalization and residual operators; runtime synthetic vectors.
duoforge_add_test(NAME duoforge.eval.normalization SOURCES eval/test_normalization.c WHITEBOX TIER quick AREA engine)
if(CMAKE_C_COMPILER_ID MATCHES "^(GNU|Clang)$" AND NOT MSVC
        AND NOT CMAKE_C_SIMULATE_ID STREQUAL "MSVC")
    target_compile_definitions(duoforge_eval_normalization PRIVATE DF_EVAL_ALLOC_HOOKS)
    target_link_options(duoforge_eval_normalization PRIVATE
        "LINKER:--wrap=malloc" "LINKER:--wrap=calloc" "LINKER:--wrap=realloc" "LINKER:--wrap=free")
endif()
if(DUOFORGE_PYTHON)
    add_test(NAME duoforge.eval.normalization_oracle COMMAND "${DUOFORGE_PYTHON}"
        "${PROJECT_SOURCE_DIR}/tools/eval/tests/normalization_oracle.py" "$<TARGET_FILE:duoforge_eval_normalization>")
    duoforge_label_test(duoforge.eval.normalization_oracle quick engine python ci-no-skip)
    set_tests_properties(duoforge.eval.normalization_oracle PROPERTIES TIMEOUT 60)
else()
    add_test(NAME duoforge.eval.normalization_oracle COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: DUOFORGE_PYTHON is empty")
    duoforge_label_test(duoforge.eval.normalization_oracle quick engine python ci-no-skip)
    set_tests_properties(duoforge.eval.normalization_oracle PROPERTIES TIMEOUT 60 SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
endif()
