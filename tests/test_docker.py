# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Tests for Docker command construction."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from beman_local_ci.lib.config import ResolvedConfig
from beman_local_ci.lib.docker import (
    build_docker_command,
    build_docker_script,
    check_docker,
    create_build_dir,
    docker_image,
)
from beman_local_ci.lib.matrix import CIJob


def test_docker_image_gcc():
    """Test Docker image name for GCC."""
    job = CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default")
    assert docker_image(job) == "ghcr.io/bemanproject/infra-containers-gcc:15"


def test_docker_image_clang():
    """Test Docker image name for Clang."""
    job = CIJob("clang", "21", "c++26", "libc++", "Debug.Default")
    assert docker_image(job) == "ghcr.io/bemanproject/infra-containers-clang:21"


def test_docker_image_trunk():
    """Test Docker image name for trunk version."""
    job = CIJob("gcc", "trunk", "c++26", "libstdc++", "Debug.Default")
    assert docker_image(job) == "ghcr.io/bemanproject/infra-containers-gcc:trunk"


def test_build_docker_script_basic():
    """Test basic Docker script generation."""
    config = ResolvedConfig(
        build_config="Debug",
        cmake_extra_args="",
        toolchain_file="infra/cmake/gnu-toolchain.cmake",
        cpp_version="26",
    )

    script = build_docker_script(config, jobs=8)

    # Check for all required steps
    assert "::step::configure" in script
    assert "::step::build" in script
    assert "::step::header_sets" in script
    assert "::step::install" in script
    assert "::step::test" in script
    assert "::step::done" in script

    # Check CMake configuration
    assert "cmake -B /build -S /src" in script
    assert "-DCMAKE_CXX_STANDARD=26" in script
    assert 'DCMAKE_TOOLCHAIN_FILE="/src/infra/cmake/gnu-toolchain.cmake"' in script
    assert (
        '-DCMAKE_PROJECT_TOP_LEVEL_INCLUDES="/src/infra/cmake/use-fetch-content.cmake"'
        in script
    )

    # Check build command
    assert "cmake --build /build --config Debug --parallel 8 --verbose" in script

    # Check test command
    assert "ctest --test-dir /build --build-config Debug --output-on-failure" in script


def test_build_docker_script_with_extra_args():
    """Test Docker script with extra CMake args."""
    config = ResolvedConfig(
        build_config="Release",
        cmake_extra_args="-DBEMAN_BUILDSYS_SANITIZER=TSan",
        toolchain_file="infra/cmake/llvm-toolchain.cmake",
        cpp_version="26",
    )

    script = build_docker_script(config, jobs=4)

    assert "-DBEMAN_BUILDSYS_SANITIZER=TSan" in script
    assert "--config Release" in script
    assert "--parallel 4" in script


def test_build_docker_script_custom_test():
    """Test Docker script with custom test args."""
    config = ResolvedConfig(
        build_config="Debug",
        cmake_extra_args="-DBEMAN_UTF_VIEW_BUILD_PAPER=ON",
        toolchain_file="infra/cmake/gnu-toolchain.cmake",
        cpp_version="26",
    )

    script = build_docker_script(config, jobs=1)

    assert "-DBEMAN_UTF_VIEW_BUILD_PAPER=ON" in script


def test_build_docker_command():
    """Test full Docker command construction."""
    job = CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default")
    config = ResolvedConfig(
        build_config="Debug",
        cmake_extra_args="",
        toolchain_file="infra/cmake/gnu-toolchain.cmake",
        cpp_version="26",
    )
    repo_path = Path("/workspace/test-repo")
    build_dir = Path("/tmp/build")

    cmd = build_docker_command(job, config, repo_path, jobs=8, build_dir=build_dir)

    assert cmd[0] == "docker"
    assert cmd[1] == "run"
    assert "--rm" in cmd

    # Check volume mounts
    assert "-v" in cmd
    mount_indices = [i for i, x in enumerate(cmd) if x == "-v"]
    assert len(mount_indices) == 2

    # Check for read-only source mount
    src_mount = cmd[mount_indices[0] + 1]
    assert src_mount.endswith(":/src:ro")

    # Check for build mount
    build_mount = cmd[mount_indices[1] + 1]
    assert ":/build" in build_mount

    # Check environment variable
    assert "-e" in cmd
    env_index = cmd.index("-e")
    assert cmd[env_index + 1] == "CMAKE_GENERATOR=Ninja Multi-Config"

    # Check image
    assert "ghcr.io/bemanproject/infra-containers-gcc:15" in cmd

    # Check bash -c
    assert "bash" in cmd
    assert "-c" in cmd


def test_create_build_dir_default():
    """Test creating build directory with default base."""
    job = CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default")

    build_dir = create_build_dir(job)

    assert build_dir.exists()
    assert "gcc" in str(build_dir)
    assert "15" in str(build_dir)
    assert build_dir.is_dir()

    # Cleanup
    build_dir.rmdir()


def test_create_build_dir_custom_base():
    """Test creating build directory with custom base."""
    job = CIJob("clang", "21", "c++26", "libc++", "Release.TSan")
    base_dir = Path(tempfile.mkdtemp())

    build_dir = create_build_dir(job, base_dir=base_dir)

    assert build_dir.exists()
    assert build_dir.parent == base_dir
    assert "clang" in str(build_dir)
    assert "21" in str(build_dir)

    # Cleanup
    build_dir.rmdir()
    base_dir.rmdir()


def test_create_build_dir_sanitizes_name():
    """Test that build dir name is sanitized."""
    job = CIJob("gcc", "trunk", "c++26", "libstdc++", "Debug.-DFOO=ON")
    base_dir = Path(tempfile.mkdtemp())

    build_dir = create_build_dir(job, base_dir=base_dir)

    # Should not contain special characters that could cause issues
    assert "/" not in build_dir.name
    assert (
        ":" not in build_dir.name or build_dir.name.count(":") <= 1
    )  # Windows drive letter

    # Cleanup
    build_dir.rmdir()
    base_dir.rmdir()


def test_create_build_dir_idempotent():
    """Test that creating same build dir twice is safe."""
    job = CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default")
    base_dir = Path(tempfile.mkdtemp())

    build_dir1 = create_build_dir(job, base_dir=base_dir)
    build_dir2 = create_build_dir(job, base_dir=base_dir)

    assert build_dir1 == build_dir2
    assert build_dir1.exists()

    # Cleanup
    build_dir1.rmdir()
    base_dir.rmdir()


@patch("subprocess.run")
def test_check_docker_success(mock_run):
    """Test successful Docker check."""
    mock_run.return_value = MagicMock(returncode=0)

    # Should not raise
    check_docker()

    mock_run.assert_called_once()
    assert mock_run.call_args[0][0] == ["docker", "info"]


@patch("subprocess.run")
def test_check_docker_not_running(mock_run):
    """Test Docker check when daemon is not running."""
    mock_run.return_value = MagicMock(returncode=1, stderr="Cannot connect to daemon")

    with pytest.raises(RuntimeError, match="Docker is not accessible"):
        check_docker()


@patch("subprocess.run")
def test_check_docker_not_installed(mock_run):
    """Test Docker check when Docker is not installed."""
    mock_run.side_effect = FileNotFoundError()

    with pytest.raises(RuntimeError, match="Docker command not found"):
        check_docker()


@patch("subprocess.run")
def test_check_docker_timeout(mock_run):
    """Test Docker check timeout."""
    from subprocess import TimeoutExpired

    mock_run.side_effect = TimeoutExpired(cmd="docker info", timeout=5)

    with pytest.raises(RuntimeError, match="timed out"):
        check_docker()
