# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Docker command construction and execution."""

import json
import os
import platform
import subprocess
import tempfile
from functools import cache
from pathlib import Path

from beman_local_ci.lib.config import ResolvedConfig
from beman_local_ci.lib.matrix import CIJob


def check_docker() -> None:
    """
    Check if Docker is available and accessible.

    Raises RuntimeError with helpful message if Docker is not available.
    """
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Docker is not accessible. Error: {result.stderr}\n"
                "Please ensure Docker is installed and running."
            )
    except FileNotFoundError:
        raise RuntimeError(
            "Docker command not found. Please install Docker:\n"
            "https://docs.docker.com/get-docker/"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Docker info command timed out. Is Docker daemon running?")


def get_docker_memory_bytes() -> int | None:
    """Return the total memory available to Docker, in bytes."""
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.MemTotal}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except Exception:
        pass
    return None


def get_system_memory_bytes() -> int | None:
    """Return total physical memory in bytes (POSIX only)."""
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


def _is_macos_arm64() -> bool:
    """Check if running on macOS with Apple Silicon."""
    return platform.system() == "Darwin" and platform.machine() == "arm64"


@cache
def _image_has_arm64(image: str) -> bool:
    """
    Check if a Docker image manifest list includes an arm64 entry.

    Results are cached per image to avoid repeated registry queries when
    multiple jobs share the same compiler image.

    Returns True if arm64 is available or if the check cannot be completed,
    so that the caller only adds --platform when arm64 is definitively absent.
    """
    try:
        result = subprocess.run(
            ["docker", "manifest", "inspect", image],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return True  # Can't determine; don't force emulation
        data = json.loads(result.stdout)
        manifests = data.get("manifests", [])
        if not manifests:
            return True  # Single-arch manifest; Docker resolves it natively
        return any(
            m.get("platform", {}).get("architecture") == "arm64" for m in manifests
        )
    except Exception:
        return True  # Can't determine; don't force emulation


def docker_image(job: CIJob) -> str:
    """
    Generate Docker image name for a job.

    Format: ghcr.io/bemanproject/infra-containers-{compiler}:{version}
    """
    return f"ghcr.io/bemanproject/infra-containers-{job.compiler}:{job.version}"


def build_docker_script(
    resolved: ResolvedConfig, jobs: int, cmake_extra_args: str = ""
) -> str:
    """
    Build the bash script to run inside the Docker container.

    Replicates the CMake workflow from the reusable workflow:
    - Configure with CMake (lines 133-142)
    - Build (line 148)
    - Run header sets check (line 149)
    - Install (line 150)
    - Test (line 154)
    """
    # Format extra args - add space prefix if not empty
    extra_args = f" {cmake_extra_args}" if cmake_extra_args else ""
    if resolved.cmake_extra_args:
        extra_args += f" {resolved.cmake_extra_args}"

    script = f"""set -e
echo "::step::configure"
cmake -B /build -S /src \\
  -DCMAKE_CXX_STANDARD={resolved.cpp_version} \\
  -DCMAKE_TOOLCHAIN_FILE="/src/{resolved.toolchain_file}" \\
  -DCMAKE_PROJECT_TOP_LEVEL_INCLUDES="/src/infra/cmake/use-fetch-content.cmake"{extra_args}
echo "::step::build"
cmake --build /build --config {resolved.build_config} --parallel {jobs} --verbose
echo "::step::header_sets"
cmake --build /build --config {resolved.build_config} --target all_verify_interface_header_sets
echo "::step::install"
cmake --install /build --config {resolved.build_config} --prefix /build/stagedir
echo "::step::test"
ctest --test-dir /build --build-config {resolved.build_config} --output-on-failure
echo "::step::done"
"""
    return script


def build_docker_command(
    job: CIJob,
    resolved: ResolvedConfig,
    repo_path: Path,
    jobs: int,
    build_dir: Path,
) -> list[str]:
    """
    Build the complete docker run command.

    Args:
        job: The CI job configuration
        resolved: Resolved build configuration
        repo_path: Path to the repository
        jobs: Number of parallel build jobs
        build_dir: Unique build directory for this job

    Returns:
        List of command arguments suitable for subprocess.run()
    """
    image = docker_image(job)
    script = build_docker_script(resolved, jobs)

    # Mount repo as read-only, build dir as read-write
    # Use absolute paths
    repo_path = repo_path.resolve()
    build_dir = build_dir.resolve()

    # On macOS Apple Silicon, always pass --platform explicitly so that Docker
    # never falls back to a stale amd64 layer from the local image cache:
    #   - arm64-capable images  → --platform linux/arm64  (native, fast)
    #   - amd64-only images     → --platform linux/amd64  (Rosetta 2 emulation)
    # When the manifest check cannot be completed we keep the flag absent and
    # let Docker choose, which is the same as the non-macOS behaviour.
    platform_args: list[str] = []
    if _is_macos_arm64():
        platform_args = (
            ["--platform", "linux/arm64"]
            if _image_has_arm64(image)
            else ["--platform", "linux/amd64"]
        )

    cmd = [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        *platform_args,
        "-v",
        f"{repo_path}:/src:ro",
        "-v",
        f"{build_dir}:/build",
        "-e",
        "CMAKE_GENERATOR=Ninja Multi-Config",
        image,
        "bash",
        "-c",
        script,
    ]

    return cmd


BUILD_CACHE_DIR = Path(tempfile.gettempdir()) / "beman-local-ci"


def check_build_cache_ownership() -> str | None:
    """Check that the build cache dir has no root-owned files.

    Scans up to two levels deep (the job dirs and their immediate children)
    to detect root-owned entries without walking the entire tree.

    Returns None on success, or an error message string if any
    root-owned entry is found.
    """
    if not BUILD_CACHE_DIR.exists():
        return None

    uid = os.getuid()
    root_uid = 0

    # Check the top-level dir itself, then job dirs (depth 1) and their
    # immediate children (depth 2).
    dirs_to_scan = [BUILD_CACHE_DIR]
    for depth, parent in enumerate(dirs_to_scan):
        try:
            for entry in parent.iterdir():
                try:
                    if entry.stat().st_uid == root_uid and root_uid != uid:
                        return (
                            f"Build cache contains root-owned files "
                            f"(e.g. {entry}).\n"
                            f"Fix with: sudo rm -rf {BUILD_CACHE_DIR}"
                        )
                    # Queue job dirs (depth 0→1) for one more level of scanning.
                    if depth == 0 and entry.is_dir():
                        dirs_to_scan.append(entry)
                except OSError:
                    pass
        except OSError:
            pass

    return None


def create_build_dir(job: CIJob, base_dir: Path | None = None) -> Path:
    """
    Create a unique build directory for a job.

    Args:
        job: The CI job
        base_dir: Base directory for build dirs (default: system temp)

    Returns:
        Path to the created build directory
    """
    if base_dir is None:
        base_dir = BUILD_CACHE_DIR

    base_dir.mkdir(parents=True, exist_ok=True)

    # Create unique dir name from job parameters
    # Use sanitized names (replace special chars)
    job_name = f"{job.compiler}-{job.version}-{job.cxxversion}-{job.stdlib}-{job.test}"
    job_name = job_name.replace("/", "_").replace(" ", "_").replace(":", "_")

    build_dir = base_dir / job_name
    build_dir.mkdir(parents=True, exist_ok=True)

    return build_dir
