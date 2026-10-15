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

# Compiled, frozen value graphs; parameters exist only in temporary synthetic files.
duoforge_add_test(NAME duoforge.eval.graphs SOURCES eval/test_graph.c WHITEBOX LIBS duoforge_batch TIER quick AREA engine)
if(CMAKE_C_COMPILER_ID MATCHES "^(GNU|Clang)$" AND NOT MSVC
        AND NOT CMAKE_C_SIMULATE_ID STREQUAL "MSVC")
    target_compile_definitions(duoforge_eval_graphs PRIVATE DF_EVAL_ALLOC_HOOKS)
    target_link_options(duoforge_eval_graphs PRIVATE
        "LINKER:--wrap=malloc" "LINKER:--wrap=calloc" "LINKER:--wrap=realloc" "LINKER:--wrap=free")
endif()
if(DUOFORGE_PYTHON)
    foreach(_graph IN ITEMS full small medium)
        add_test(NAME duoforge.eval.graph_${_graph} COMMAND "${DUOFORGE_PYTHON}"
            "${PROJECT_SOURCE_DIR}/tools/eval/tests/graph_oracle.py" "$<TARGET_FILE:duoforge_eval_graphs>" "${_graph}")
        duoforge_label_test(duoforge.eval.graph_${_graph} full engine python ci-no-skip)
        set_tests_properties(duoforge.eval.graph_${_graph} PROPERTIES TIMEOUT 120)
    endforeach()
    add_test(NAME duoforge.eval.graph_registry COMMAND "${DUOFORGE_PYTHON}"
        "${PROJECT_SOURCE_DIR}/tools/eval/graph_registry.py" --check)
    duoforge_label_test(duoforge.eval.graph_registry quick tools python ci-no-skip)
    add_test(NAME duoforge.eval.graph_registry_rules COMMAND "${DUOFORGE_PYTHON}"
        "${PROJECT_SOURCE_DIR}/tools/eval/tests/test_graph_registry.py")
    duoforge_label_test(duoforge.eval.graph_registry_rules quick tools python ci-no-skip)
    add_test(NAME duoforge.eval.graph_arithmetic COMMAND "${DUOFORGE_PYTHON}"
        "${PROJECT_SOURCE_DIR}/tools/eval/tests/graph_arithmetic_oracle.py" "$<TARGET_FILE:duoforge_eval_graphs>")
    duoforge_label_test(duoforge.eval.graph_arithmetic quick engine python ci-no-skip)
else()
    foreach(_graph IN ITEMS full small medium registry registry_rules arithmetic)
        add_test(NAME duoforge.eval.graph_${_graph} COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: DUOFORGE_PYTHON is empty")
        if(_graph STREQUAL "registry" OR _graph STREQUAL "registry_rules")
            duoforge_label_test(duoforge.eval.graph_${_graph} quick tools python ci-no-skip)
        elseif(_graph STREQUAL "arithmetic")
            duoforge_label_test(duoforge.eval.graph_${_graph} quick engine python ci-no-skip)
        else()
            duoforge_label_test(duoforge.eval.graph_${_graph} full engine python ci-no-skip)
        endif()
        set_tests_properties(duoforge.eval.graph_${_graph} PROPERTIES TIMEOUT 120 SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
    endforeach()
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

# E3b private tile scheduling: runtime synthetic parameters, no file or training.
duoforge_add_test(NAME duoforge.eval.tiles SOURCES eval/test_tiles.c WHITEBOX LIBS duoforge_batch TIER quick AREA engine)
if(CMAKE_C_COMPILER_ID MATCHES "^(GNU|Clang)$" AND NOT MSVC
        AND NOT CMAKE_C_SIMULATE_ID STREQUAL "MSVC")
    target_compile_definitions(duoforge_eval_tiles PRIVATE DF_EVAL_ALLOC_HOOKS)
    target_link_options(duoforge_eval_tiles PRIVATE
        "LINKER:--wrap=malloc" "LINKER:--wrap=calloc" "LINKER:--wrap=realloc" "LINKER:--wrap=free")
endif()
foreach(_graph IN ITEMS full small medium)
    if(_graph STREQUAL "full")
        set(_graph_id 1001)
    elseif(_graph STREQUAL "small")
        set(_graph_id 1002)
    else()
        set(_graph_id 1003)
    endif()
    add_test(NAME duoforge.eval.tiles_${_graph} COMMAND duoforge_eval_tiles ${_graph_id})
    duoforge_label_test(duoforge.eval.tiles_${_graph} full engine)
    set_tests_properties(duoforge.eval.tiles_${_graph} PROPERTIES TIMEOUT 300)
endforeach()
add_test(NAME duoforge.eval.tiles_concurrent COMMAND duoforge_eval_tiles --race)
duoforge_label_test(duoforge.eval.tiles_concurrent full engine ci-tsan)
set_tests_properties(duoforge.eval.tiles_concurrent PROPERTIES TIMEOUT 300)

# E4 offline private-artifact bridge; CI exercises synthetic data only.
add_executable(duoforge_bc6_runner "${PROJECT_SOURCE_DIR}/tools/eval/bc6_runner.c")
target_include_directories(duoforge_bc6_runner PRIVATE "${PROJECT_SOURCE_DIR}/src")
target_link_libraries(duoforge_bc6_runner PRIVATE duoforge_batch duoforge)
duoforge_configure_target(duoforge_bc6_runner)
get_target_property(_bc6_ipo duoforge_bc6_runner INTERPROCEDURAL_OPTIMIZATION)
if(NOT _bc6_ipo)
    set(_bc6_ipo OFF)
endif()
target_compile_definitions(duoforge_bc6_runner PRIVATE
    DFE4_COMPILER="${CMAKE_C_COMPILER_ID}" DFE4_PLATFORM="${CMAKE_SYSTEM_NAME}"
    DFE4_CONFIG="$<CONFIG>" DFE4_IPO="${_bc6_ipo}")
if(DUOFORGE_PYTHON)
    foreach(_check IN ITEMS export_bc6 bc6_gates)
        add_test(NAME duoforge.eval.${_check} COMMAND "${DUOFORGE_PYTHON}"
            "${PROJECT_SOURCE_DIR}/tools/eval/tests/test_${_check}.py")
        duoforge_label_test(duoforge.eval.${_check} full tools python ci-no-skip)
        set_tests_properties(duoforge.eval.${_check} PROPERTIES TIMEOUT 300 ENVIRONMENT
            "DUOFORGE_E4_RUNNER=$<TARGET_FILE:duoforge_eval_graphs>;DUOFORGE_BC6_RUNNER=$<TARGET_FILE:duoforge_bc6_runner>;DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;PYTHONPATH=${PROJECT_SOURCE_DIR}/python;PYTHONDONTWRITEBYTECODE=1;OPENBLAS_NUM_THREADS=1;JAX_PLATFORMS=cpu")
    endforeach()
else()
    foreach(_check IN ITEMS export_bc6 bc6_gates)
        add_test(NAME duoforge.eval.${_check} COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: needs NumPy/Python")
        duoforge_label_test(duoforge.eval.${_check} full tools python ci-no-skip)
        set_tests_properties(duoforge.eval.${_check} PROPERTIES SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
    endforeach()
endif()
if(DUOFORGE_LEARN_PYTHON AND DUOFORGE_NODE AND DUOFORGE_PS_REFERENCE_DIR)
    add_test(NAME duoforge.eval.bc6_float COMMAND "${DUOFORGE_LEARN_PYTHON}"
        "${PROJECT_SOURCE_DIR}/tools/eval/tests/test_bc6_float.py")
    set_tests_properties(duoforge.eval.bc6_float PROPERTIES TIMEOUT 300 ENVIRONMENT
        "DUOFORGE_E4_RUNNER=$<TARGET_FILE:duoforge_eval_graphs>;DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;PYTHONPATH=${PROJECT_SOURCE_DIR}/python;PYTHONDONTWRITEBYTECODE=1;OPENBLAS_NUM_THREADS=1;JAX_PLATFORMS=cpu;DUOFORGE_NODE=${DUOFORGE_NODE};DUOFORGE_PS_REFERENCE_DIR=${DUOFORGE_PS_REFERENCE_DIR}")
else()
    add_test(NAME duoforge.eval.bc6_float COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: needs JAX, Node 22 and pinned Showdown")
    set_tests_properties(duoforge.eval.bc6_float PROPERTIES SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
endif()
duoforge_label_test(duoforge.eval.bc6_float slow tools python ci-no-skip requires-jax)
