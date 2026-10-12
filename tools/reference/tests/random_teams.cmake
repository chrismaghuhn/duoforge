# The random training teams (tools/reference/random_teams.py): the paste translation, the composition and the output
# guard with DUOFORGE_PYTHON (it reads pastes with duoforge.teams); with the pinned Showdown also its generator.
if(DUOFORGE_PYTHON)
    add_test(NAME duoforge.reference.random_teams
        COMMAND "${DUOFORGE_PYTHON}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_random_teams.py")
    duoforge_label_test(duoforge.reference.random_teams quick tools ci-no-skip python)
    set_tests_properties(duoforge.reference.random_teams PROPERTIES TIMEOUT 120  ENVIRONMENT
        "DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;PYTHONDONTWRITEBYTECODE=1")
    if(DUOFORGE_PS_REFERENCE_DIR AND DUOFORGE_NODE)
        add_test(NAME duoforge.reference.random_teams_pin
            COMMAND "${DUOFORGE_PYTHON}" "${PROJECT_SOURCE_DIR}/tools/reference/tests/test_random_teams.py"
                "${DUOFORGE_NODE}" "${DUOFORGE_PS_REFERENCE_DIR}")
        duoforge_label_test(duoforge.reference.random_teams_pin reference tools ci-no-skip)
        set_tests_properties(duoforge.reference.random_teams_pin PROPERTIES TIMEOUT 300
            ENVIRONMENT "DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>;PYTHONDONTWRITEBYTECODE=1")
    endif()
else()
    add_test(NAME duoforge.reference.random_teams COMMAND "${CMAKE_COMMAND}" -E echo "DUOFORGE_SKIP: DUOFORGE_PYTHON is empty")
    duoforge_label_test(duoforge.reference.random_teams quick tools ci-no-skip python)
    set_tests_properties(duoforge.reference.random_teams PROPERTIES SKIP_REGULAR_EXPRESSION "DUOFORGE_SKIP:")
endif()
