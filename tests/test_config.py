# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Tests for configuration resolution."""

import pytest

from beman_local_ci.lib.config import (
    ResolvedConfig,
    resolve_cmake_extra_args,
    resolve_config,
    resolve_cpp_version,
    resolve_test_string,
    resolve_toolchain_file,
)
from beman_local_ci.lib.matrix import CIJob


def test_resolve_test_string_default():
    """Test parsing Debug.Default."""
    build_config, test_type = resolve_test_string("Debug.Default")
    assert build_config == "Debug"
    assert test_type == "Default"


def test_resolve_test_string_tsan():
    """Test parsing Release.TSan."""
    build_config, test_type = resolve_test_string("Release.TSan")
    assert build_config == "Release"
    assert test_type == "TSan"


def test_resolve_test_string_custom():
    """Test parsing custom test string with CMake flags."""
    build_config, test_type = resolve_test_string(
        "Debug.-DBEMAN_UTF_VIEW_BUILD_PAPER=ON"
    )
    assert build_config == "Debug"
    assert test_type == "-DBEMAN_UTF_VIEW_BUILD_PAPER=ON"


def test_resolve_test_string_invalid():
    """Test error on invalid format."""
    with pytest.raises(ValueError, match="Invalid test string format"):
        resolve_test_string("InvalidFormat")


def test_resolve_cmake_extra_args_default():
    """Test Default maps to empty string."""
    assert resolve_cmake_extra_args("Default") == ""


def test_resolve_cmake_extra_args_tsan():
    """Test TSan mapping."""
    assert resolve_cmake_extra_args("TSan") == "-DBEMAN_BUILDSYS_SANITIZER=TSan"


def test_resolve_cmake_extra_args_maxsan():
    """Test MaxSan mapping."""
    assert resolve_cmake_extra_args("MaxSan") == "-DBEMAN_BUILDSYS_SANITIZER=MaxSan"


def test_resolve_cmake_extra_args_werror():
    """Test Werror mapping."""
    result = resolve_cmake_extra_args("Werror")
    assert "-Werror=all" in result
    assert "-Werror=extra" in result


def test_resolve_cmake_extra_args_dynamic():
    """Test Dynamic mapping."""
    assert resolve_cmake_extra_args("Dynamic") == "-DBUILD_SHARED_LIBS=on"


def test_resolve_cmake_extra_args_coverage():
    """Test Coverage mapping."""
    result = resolve_cmake_extra_args("Coverage")
    assert "--coverage" in result
    assert "-fprofile-abs-path" in result


def test_resolve_cmake_extra_args_custom():
    """Test pass-through for custom flags."""
    custom = "-DBEMAN_UTF_VIEW_BUILD_PAPER=ON"
    assert resolve_cmake_extra_args(custom) == custom


def test_resolve_toolchain_file_gcc():
    """Test toolchain selection for GCC."""
    assert (
        resolve_toolchain_file("gcc", "libstdc++") == "infra/cmake/gnu-toolchain.cmake"
    )


def test_resolve_toolchain_file_clang_libstdcpp():
    """Test toolchain selection for clang with libstdc++."""
    assert (
        resolve_toolchain_file("clang", "libstdc++")
        == "infra/cmake/llvm-toolchain.cmake"
    )


def test_resolve_toolchain_file_clang_libcpp():
    """Test toolchain selection for clang with libc++."""
    assert (
        resolve_toolchain_file("clang", "libc++")
        == "infra/cmake/llvm-libc++-toolchain.cmake"
    )


def test_resolve_toolchain_file_unsupported_compiler():
    """Test error on unsupported compiler."""
    with pytest.raises(ValueError, match="Unsupported compiler"):
        resolve_toolchain_file("msvc", "stl")


def test_resolve_toolchain_file_unknown_stdlib():
    """Test error on unknown stdlib for clang."""
    with pytest.raises(ValueError, match="Unknown stdlib"):
        resolve_toolchain_file("clang", "unknown")


def test_resolve_cpp_version():
    """Test stripping c++ prefix."""
    assert resolve_cpp_version("c++26") == "26"
    assert resolve_cpp_version("c++23") == "23"
    assert resolve_cpp_version("c++20") == "20"
    assert resolve_cpp_version("c++17") == "17"


def test_resolve_cpp_version_without_prefix():
    """Test handling version without prefix."""
    assert resolve_cpp_version("26") == "26"


def test_resolve_config_debug_default():
    """Test full config resolution for Debug.Default."""
    job = CIJob(
        compiler="gcc",
        version="15",
        cxxversion="c++26",
        stdlib="libstdc++",
        test="Debug.Default",
    )

    config = resolve_config(job)

    assert config.build_config == "Debug"
    assert config.cmake_extra_args == ""
    assert config.toolchain_file == "infra/cmake/gnu-toolchain.cmake"
    assert config.cpp_version == "26"


def test_resolve_config_release_tsan():
    """Test full config resolution for Release.TSan."""
    job = CIJob(
        compiler="clang",
        version="21",
        cxxversion="c++26",
        stdlib="libc++",
        test="Release.TSan",
    )

    config = resolve_config(job)

    assert config.build_config == "Release"
    assert config.cmake_extra_args == "-DBEMAN_BUILDSYS_SANITIZER=TSan"
    assert config.toolchain_file == "infra/cmake/llvm-libc++-toolchain.cmake"
    assert config.cpp_version == "26"


def test_resolve_config_custom_test():
    """Test full config resolution with custom test string."""
    job = CIJob(
        compiler="gcc",
        version="trunk",
        cxxversion="c++26",
        stdlib="libstdc++",
        test="Debug.-DBEMAN_UTF_VIEW_BUILD_PAPER=ON",
    )

    config = resolve_config(job)

    assert config.build_config == "Debug"
    assert config.cmake_extra_args == "-DBEMAN_UTF_VIEW_BUILD_PAPER=ON"
    assert config.toolchain_file == "infra/cmake/gnu-toolchain.cmake"
    assert config.cpp_version == "26"


def test_resolved_config_frozen():
    """Test that ResolvedConfig is immutable."""
    config = ResolvedConfig(
        build_config="Debug",
        cmake_extra_args="",
        toolchain_file="infra/cmake/gnu-toolchain.cmake",
        cpp_version="26",
    )

    with pytest.raises(Exception):  # FrozenInstanceError
        config.build_config = "Release"
