# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Tests for Docker command construction."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from beman_local_ci.lib.config import ResolvedConfig
from beman_local_ci.lib.docker import (
    _image_has_arm64,
    _is_macos_arm64,
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


# ── macOS arm64 / platform detection ─────────────────────────────────────────


@patch("platform.system", return_value="Darwin")
@patch("platform.machine", return_value="arm64")
def test_is_macos_arm64_true(mock_machine, mock_system):
    """Detects macOS Apple Silicon correctly."""
    assert _is_macos_arm64() is True


@patch("platform.system", return_value="Linux")
@patch("platform.machine", return_value="aarch64")
def test_is_macos_arm64_false_linux(mock_machine, mock_system):
    """Returns False on Linux arm64."""
    assert _is_macos_arm64() is False


@patch("platform.system", return_value="Darwin")
@patch("platform.machine", return_value="x86_64")
def test_is_macos_arm64_false_intel_mac(mock_machine, mock_system):
    """Returns False on Intel Mac."""
    assert _is_macos_arm64() is False


_MULTIARCH_MANIFEST = json.dumps(
    {
        "schemaVersion": 2,
        "manifests": [
            {"platform": {"architecture": "amd64", "os": "linux"}},
            {"platform": {"architecture": "arm64", "os": "linux"}},
        ],
    }
)

_AMD64_ONLY_MANIFEST = json.dumps(
    {
        "schemaVersion": 2,
        "manifests": [
            {"platform": {"architecture": "amd64", "os": "linux"}},
        ],
    }
)

_SINGLE_ARCH_MANIFEST = json.dumps(
    {
        "schemaVersion": 2,
        "config": {"mediaType": "application/vnd.oci.image.config.v1+json"},
    }
)


@patch("subprocess.run")
def test_image_has_arm64_multiarch(mock_run):
    """Returns True when manifest list contains arm64."""
    _image_has_arm64.cache_clear()
    mock_run.return_value = MagicMock(returncode=0, stdout=_MULTIARCH_MANIFEST)
    assert _image_has_arm64("ghcr.io/bemanproject/infra-containers-clang:21") is True
    _image_has_arm64.cache_clear()


@patch("subprocess.run")
def test_image_has_arm64_amd64_only(mock_run):
    """Returns False when manifest list has no arm64 entry."""
    _image_has_arm64.cache_clear()
    mock_run.return_value = MagicMock(returncode=0, stdout=_AMD64_ONLY_MANIFEST)
    assert _image_has_arm64("ghcr.io/bemanproject/infra-containers-clang:18") is False
    _image_has_arm64.cache_clear()


@patch("subprocess.run")
def test_image_has_arm64_single_arch_manifest(mock_run):
    """Returns True for single-arch manifest (no manifests array)."""
    _image_has_arm64.cache_clear()
    mock_run.return_value = MagicMock(returncode=0, stdout=_SINGLE_ARCH_MANIFEST)
    assert _image_has_arm64("ghcr.io/bemanproject/infra-containers-gcc:15") is True
    _image_has_arm64.cache_clear()


@patch("subprocess.run")
def test_image_has_arm64_inspect_fails(mock_run):
    """Returns True (safe default) when manifest inspect fails."""
    _image_has_arm64.cache_clear()
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
    assert _image_has_arm64("ghcr.io/bemanproject/infra-containers-clang:18") is True
    _image_has_arm64.cache_clear()


@patch("subprocess.run")
def test_image_has_arm64_exception(mock_run):
    """Returns True (safe default) when subprocess raises."""
    _image_has_arm64.cache_clear()
    mock_run.side_effect = Exception("network error")
    assert _image_has_arm64("ghcr.io/bemanproject/infra-containers-clang:18") is True
    _image_has_arm64.cache_clear()


@patch("beman_local_ci.lib.docker._is_macos_arm64", return_value=True)
@patch(
    "beman_local_ci.lib.docker._image_has_arm64",
    return_value=False,
)
def test_build_docker_command_adds_platform_on_macos_amd64_only(
    mock_has_arm64, mock_is_macos
):
    """--platform linux/amd64 is injected on macOS arm64 for amd64-only images."""
    job = CIJob("clang", "18", "c++26", "libc++", "Debug.Default")
    config = ResolvedConfig(
        build_config="Debug",
        cmake_extra_args="",
        toolchain_file="infra/cmake/llvm-libc++-toolchain.cmake",
        cpp_version="26",
    )
    cmd = build_docker_command(
        job, config, Path("/repo"), jobs=4, build_dir=Path("/build")
    )

    assert "--platform" in cmd
    platform_idx = cmd.index("--platform")
    assert cmd[platform_idx + 1] == "linux/amd64"


@patch("beman_local_ci.lib.docker._is_macos_arm64", return_value=True)
@patch(
    "beman_local_ci.lib.docker._image_has_arm64",
    return_value=True,
)
def test_build_docker_command_arm64_platform_on_macos_multiarch(
    mock_has_arm64, mock_is_macos
):
    """--platform linux/arm64 is injected on macOS arm64 for arm64-capable images."""
    job = CIJob("clang", "21", "c++26", "libc++", "Debug.Default")
    config = ResolvedConfig(
        build_config="Debug",
        cmake_extra_args="",
        toolchain_file="infra/cmake/llvm-libc++-toolchain.cmake",
        cpp_version="26",
    )
    cmd = build_docker_command(
        job, config, Path("/repo"), jobs=4, build_dir=Path("/build")
    )

    assert "--platform" in cmd
    platform_idx = cmd.index("--platform")
    assert cmd[platform_idx + 1] == "linux/arm64"


@patch("beman_local_ci.lib.docker._is_macos_arm64", return_value=False)
def test_build_docker_command_no_platform_on_linux(mock_is_macos):
    """--platform is never injected on Linux regardless of image manifest."""
    job = CIJob("clang", "18", "c++26", "libc++", "Debug.Default")
    config = ResolvedConfig(
        build_config="Debug",
        cmake_extra_args="",
        toolchain_file="infra/cmake/llvm-libc++-toolchain.cmake",
        cpp_version="26",
    )
    cmd = build_docker_command(
        job, config, Path("/repo"), jobs=4, build_dir=Path("/build")
    )

    assert "--platform" not in cmd
