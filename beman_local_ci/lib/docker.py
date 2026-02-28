# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Docker command construction and execution."""

import subprocess
import tempfile
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
cmake --install /build --config {resolved.build_config} --prefix /opt/beman.package
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

    cmd = [
        "docker",
        "run",
        "--rm",
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
        base_dir = Path(tempfile.gettempdir()) / "beman-local-ci"

    base_dir.mkdir(parents=True, exist_ok=True)

    # Create unique dir name from job parameters
    # Use sanitized names (replace special chars)
    job_name = f"{job.compiler}-{job.version}-{job.cxxversion}-{job.stdlib}-{job.test}"
    job_name = job_name.replace("/", "_").replace(" ", "_").replace(":", "_")

    build_dir = base_dir / job_name
    build_dir.mkdir(parents=True, exist_ok=True)

    return build_dir
