# Keep the original interpreter, timeout, environment and fallback contracts.

function(duoforge_add_python_test _name _module _tier _area)
    if(DUOFORGE_PYTHON)
        add_test(NAME duoforge.python.${_name}
            COMMAND "${DUOFORGE_PYTHON}" -m unittest -v ${_module}
            WORKING_DIRECTORY "${PROJECT_SOURCE_DIR}")
        set_tests_properties(duoforge.python.${_name} PROPERTIES TIMEOUT 600 ENVIRONMENT
            "DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;DUOFORGE_LAYOUT_DUMP=$<TARGET_FILE:duoforge_layout_dump>;DUOFORGE_STATE_LAYOUT_DUMP=$<TARGET_FILE:duoforge_state_layout_dump>;PYTHONPATH=${PROJECT_SOURCE_DIR}/python;PYTHONDONTWRITEBYTECODE=1")
    else()
        add_test(NAME duoforge.python.${_name}
            COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: DUOFORGE_PYTHON is empty")
        set_tests_properties(duoforge.python.${_name} PROPERTIES
            SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
    endif()
    duoforge_label_test("duoforge.python.${_name}" "${_tier}" "${_area}" python ci-no-skip ${ARGN})
endfunction()

function(duoforge_add_learner_test _name _module _tier _area)
    if(DUOFORGE_LEARN_PYTHON)
        add_test(NAME duoforge.python.${_name}
            COMMAND "${DUOFORGE_LEARN_PYTHON}" -m unittest -v ${_module}
            WORKING_DIRECTORY "${PROJECT_SOURCE_DIR}")
        set_tests_properties(duoforge.python.${_name} PROPERTIES TIMEOUT 900 ENVIRONMENT
            "DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;PYTHONPATH=${PROJECT_SOURCE_DIR}/python;PYTHONDONTWRITEBYTECODE=1")
    else()
        add_test(NAME duoforge.python.${_name}
            COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: DUOFORGE_LEARN_PYTHON is empty")
        set_tests_properties(duoforge.python.${_name} PROPERTIES
            SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
    endif()
    duoforge_label_test("duoforge.python.${_name}" "${_tier}" "${_area}" python ci-no-skip requires-jax ${ARGN})
endfunction()

function(duoforge_add_reference_python_test _name _module _tier _area)
    if(DUOFORGE_PYTHON AND DUOFORGE_PS_REFERENCE_DIR AND DUOFORGE_NODE)
        add_test(NAME duoforge.python.${_name}
            COMMAND "${DUOFORGE_PYTHON}" -m unittest -v ${_module}
            WORKING_DIRECTORY "${PROJECT_SOURCE_DIR}")
        set_tests_properties(duoforge.python.${_name} PROPERTIES TIMEOUT 900 ENVIRONMENT
            "DUOFORGE_NODE=${DUOFORGE_NODE};DUOFORGE_PS_REFERENCE_DIR=${DUOFORGE_PS_REFERENCE_DIR};DUOFORGE_DIFF_RUNNER=$<TARGET_FILE:duoforge_diff_runner>;DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;PYTHONPATH=${PROJECT_SOURCE_DIR}/python;PYTHONDONTWRITEBYTECODE=1")
    else()
        add_test(NAME duoforge.python.${_name}
            COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: needs DUOFORGE_PYTHON, Node and DUOFORGE_PS_REFERENCE_DIR")
        set_tests_properties(duoforge.python.${_name} PROPERTIES SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
    endif()
    duoforge_label_test("duoforge.python.${_name}" "${_tier}" "${_area}" python ci-no-skip ${ARGN})
endfunction()
