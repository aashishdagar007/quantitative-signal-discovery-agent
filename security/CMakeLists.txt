cmake_minimum_required(VERSION 3.17)
project(SecurityProfiler VERSION 1.0.0 LANGUAGES CXX)

# ── C++17 standard ─────────────────────────────────────────────────────────
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# ── Compiler flags ─────────────────────────────────────────────────────────
if(MSVC)
    add_compile_options(/W4 /WX- /O2 /EHsc)
else()
    add_compile_options(-Wall -Wextra -O2 -fPIC)
    if(CMAKE_BUILD_TYPE STREQUAL "Debug")
        add_compile_options(-g -fsanitize=address,undefined)
        add_link_options(-fsanitize=address,undefined)
    endif()
endif()

# ── Shared library (for Python ctypes binding) ──────────────────────────────
add_library(security_profiler SHARED
    src/security_profiler.cpp
)
target_include_directories(security_profiler PUBLIC src/)

# Link pthreads on Linux
if(UNIX AND NOT APPLE)
    target_link_libraries(security_profiler PUBLIC pthread)
endif()

# ── Standalone test executable ──────────────────────────────────────────────
add_executable(security_test
    src/security_main.cpp
    src/security_profiler.cpp
)
target_include_directories(security_test PRIVATE src/)

if(UNIX AND NOT APPLE)
    target_link_libraries(security_test PRIVATE pthread)
endif()

# ── Install ─────────────────────────────────────────────────────────────────
install(TARGETS security_profiler DESTINATION lib)
install(FILES src/security_profiler.h DESTINATION include)
