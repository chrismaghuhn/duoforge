# The random training teams (tools/reference/random_teams.py): the paste translation, the composition and the output
# guard with DUOFORGE_PYTHON (it reads pastes with duoforge.teams); with the pinned Showdown also its generator.
if(DUOFORGE_PYTHON)
    add_test(NAME duoforge.reference.random_teams
        COMMAND "${DUOFORGE_PYTHON}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_random_teams.py")
    set_tests_properties(duoforge.reference.random_teams PROPERTIES TIMEOUT 120 LABELS python ENVIRONMENT
        "DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;PYTHONDONTWRITEBYTECODE=1")
    if(DUOFORGE_PS_REFERENCE_DIR AND DUOFORGE_NODE)
        add_test(NAME duoforge.reference.random_teams_pin
            COMMAND "${DUOFORGE_PYTHON}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_random_teams.py"
                "${DUOFORGE_NODE}" "${DUOFORGE_PS_REFERENCE_DIR}")
        set_tests_properties(duoforge.reference.random_teams_pin PROPERTIES TIMEOUT 300 LABELS reference
            ENVIRONMENT "DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;PYTHONDONTWRITEBYTECODE=1")
    endif()
else()
    add_test(NAME duoforge.reference.random_teams COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: DUOFORGE_PYTHON is empty")
    set_tests_properties(duoforge.reference.random_teams PROPERTIES SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
endif()
