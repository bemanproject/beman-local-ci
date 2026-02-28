# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Configuration resolution for CI jobs."""

from dataclasses import dataclass

from beman_local_ci.lib.matrix import CIJob


@dataclass(frozen=True)
class ResolvedConfig:
    """Resolved build configuration for a CI job."""

    build_config: str  # "Debug" or "Release"
    cmake_extra_args: str  # Additional CMake arguments
    toolchain_file: str  # Path to toolchain file
    cpp_version: str  # C++ version without "c++" prefix


def resolve_test_string(test: str) -> tuple[str, str]:
    """
    Parse test string into build_config and test_type.

    Replicates lines 106-111 of the reusable workflow:
    - build_config = ${test%%[.]*}  (everything before first dot)
    - test_type = ${test##*[.]}      (everything after last dot)

    Examples:
        "Debug.Default" -> ("Debug", "Default")
        "Release.TSan" -> ("Release", "TSan")
        "Debug.-DFOO=ON" -> ("Debug", "-DFOO=ON")
    """
    if "." not in test:
        raise ValueError(f"Invalid test string format: {test}")

    parts = test.split(".", 1)
    build_config = parts[0]
    test_type = parts[1]

    return build_config, test_type


def resolve_cmake_extra_args(test_type: str) -> str:
    """
    Map test_type to CMake extra arguments.

    Replicates lines 113-124 of the reusable workflow.
    """
    if test_type == "Default":
        return ""
    elif test_type == "TSan":
        return "-DBEMAN_BUILDSYS_SANITIZER=TSan"
    elif test_type == "MaxSan":
        return "-DBEMAN_BUILDSYS_SANITIZER=MaxSan"
    elif test_type == "Werror":
        return "-DCMAKE_CXX_FLAGS='-Werror=all -Werror=extra'"
    elif test_type == "Dynamic":
        return "-DBUILD_SHARED_LIBS=on"
    elif test_type == "Coverage":
        return "-DCMAKE_CXX_FLAGS='-fno-default-inline -fno-inline --coverage -fprofile-abs-path'"
    else:
        # Pass through as-is (e.g., "-DBEMAN_UTF_VIEW_BUILD_PAPER=ON")
        return test_type


def resolve_toolchain_file(compiler: str, stdlib: str) -> str:
    """
    Select toolchain file based on compiler and stdlib.

    Replicates lines 92-104 of the reusable workflow.
    """
    if compiler == "gcc":
        return "infra/cmake/gnu-toolchain.cmake"
    elif compiler.startswith("clang"):
        if stdlib == "libstdc++":
            return "infra/cmake/llvm-toolchain.cmake"
        elif stdlib == "libc++":
            return "infra/cmake/llvm-libc++-toolchain.cmake"
        else:
            raise ValueError(f"Unknown stdlib for clang: {stdlib}")
    else:
        raise ValueError(f"Unsupported compiler: {compiler}")


def resolve_cpp_version(cxxversion: str) -> str:
    """
    Strip "c++" prefix from cxxversion.

    Replicates line 94 of the reusable workflow:
    cpp_version=${cxxversion#c++}

    Example: "c++26" -> "26"
    """
    if cxxversion.startswith("c++"):
        return cxxversion[3:]
    return cxxversion


def resolve_config(job: CIJob) -> ResolvedConfig:
    """Resolve full configuration for a CI job."""
    build_config, test_type = resolve_test_string(job.test)
    cmake_extra_args = resolve_cmake_extra_args(test_type)
    toolchain_file = resolve_toolchain_file(job.compiler, job.stdlib)
    cpp_version = resolve_cpp_version(job.cxxversion)

    return ResolvedConfig(
        build_config=build_config,
        cmake_extra_args=cmake_extra_args,
        toolchain_file=toolchain_file,
        cpp_version=cpp_version,
    )
