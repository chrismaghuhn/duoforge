# Header self-containment (build-time check).
add_library(duoforge_header_check OBJECT header_check/duoforge_h_twice.c)
target_link_libraries(duoforge_header_check PRIVATE duoforge)
duoforge_configure_target(duoforge_header_check)

# extern "C" link check from C++ (not with sanitizers: the C++ target does not
# get the sanitizer link flags).
if(CMAKE_CXX_COMPILER AND NOT DUOFORGE_ENABLE_SANITIZERS AND NOT DUOFORGE_ENABLE_TSAN)
    add_executable(duoforge_cxx_link header_check/cxx_link.cpp)
    target_link_libraries(duoforge_cxx_link PRIVATE duoforge_batch)
    set_target_properties(duoforge_cxx_link PROPERTIES
        CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON CXX_EXTENSIONS OFF)
    if(MSVC)
        target_compile_options(duoforge_cxx_link PRIVATE /W4 /permissive- /utf-8)
        if(DUOFORGE_WARNINGS_AS_ERRORS)
            target_compile_options(duoforge_cxx_link PRIVATE /WX)
        endif()
    else()
        target_compile_options(duoforge_cxx_link PRIVATE -Wall -Wextra -Wpedantic)
        if(DUOFORGE_WARNINGS_AS_ERRORS)
            target_compile_options(duoforge_cxx_link PRIVATE -Werror)
        endif()
    endif()
    add_test(NAME duoforge.api.cxx_link COMMAND duoforge_cxx_link)
    duoforge_label_test(duoforge.api.cxx_link quick engine)
    set_tests_properties(duoforge.api.cxx_link PROPERTIES TIMEOUT 30)
endif()

# The export of dfi_event_make from the shared library (restructure step 4): linked against duoforge_shared alone, so
# the call resolves through the import library. Runs on every toolchain; the DLL's directory is put on PATH on Windows.
add_executable(duoforge_shared_export_event_make header_check/shared_export_event_make.c)
target_link_libraries(duoforge_shared_export_event_make PRIVATE duoforge_shared)
duoforge_configure_target(duoforge_shared_export_event_make)
add_test(NAME duoforge.engine.shared_export_event_make COMMAND duoforge_shared_export_event_make)
duoforge_label_test(duoforge.engine.shared_export_event_make quick engine ci-no-skip)
set_tests_properties(duoforge.engine.shared_export_event_make PROPERTIES TIMEOUT 30)
if(WIN32)
    set_tests_properties(duoforge.engine.shared_export_event_make PROPERTIES
        ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:$<TARGET_FILE_DIR:duoforge_shared>")
endif()
