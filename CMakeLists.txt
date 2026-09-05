cmake_minimum_required(VERSION 3.25)
project(PortableCommandRuntime VERSION 0.1.0 LANGUAGES NONE)

# M0 只注册架构门禁；M1 才增加正式 C++ 组件。
include(CTest)
if(BUILD_TESTING)
    find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter)
    add_test(NAME architecture.boundaries
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/check_boundaries.py"
            "${CMAKE_CURRENT_SOURCE_DIR}" --allow-empty)
    add_test(NAME architecture.boundary_negative_probes
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/architecture/test_boundaries.py")
    add_test(NAME architecture.evidence_failure_guards
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/architecture/test_evidence.py")
endif()
