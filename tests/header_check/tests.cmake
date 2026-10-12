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
    set_tests_properties(duoforge.api.cxx_link PROPERTIES TIMEOUT 30)
endif()

