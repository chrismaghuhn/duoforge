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
