# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Parallel job execution and result reporting."""

import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from beman_local_ci.lib.config import resolve_config
from beman_local_ci.lib.docker import build_docker_command, create_build_dir
from beman_local_ci.lib.matrix import CIJob


@dataclass
class JobResult:
    """Result of running a CI job."""

    job: CIJob
    success: bool
    duration_secs: float
    output: str
    return_code: int


def run_job(
    job: CIJob,
    repo_path: Path,
    build_jobs: int,
    verbose: bool = False,
    dry_run: bool = False,
) -> JobResult:
    """
    Execute a single CI job.

    Args:
        job: The CI job to run
        repo_path: Path to the repository
        build_jobs: Number of parallel build jobs (-j flag)
        verbose: Print detailed output
        dry_run: Print command without executing

    Returns:
        JobResult with execution details
    """
    resolved = resolve_config(job)
    build_dir = create_build_dir(job)

    cmd = build_docker_command(job, resolved, repo_path, build_jobs, build_dir)

    if dry_run:
        # In dry-run mode, just return success
        cmd_str = " ".join(cmd)
        return JobResult(
            job=job,
            success=True,
            duration_secs=0.0,
            output=f"[DRY RUN] {cmd_str}",
            return_code=0,
        )

    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 minute timeout
        )

        duration = time.time() - start_time
        success = result.returncode == 0

        # Combine stdout and stderr
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr

        return JobResult(
            job=job,
            success=success,
            duration_secs=duration,
            output=output,
            return_code=result.returncode,
        )

    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        return JobResult(
            job=job,
            success=False,
            duration_secs=duration,
            output="Job timed out after 30 minutes",
            return_code=-1,
        )
    except Exception as e:
        duration = time.time() - start_time
        return JobResult(
            job=job,
            success=False,
            duration_secs=duration,
            output=f"Error running job: {e}",
            return_code=-1,
        )


def print_job_status(result: JobResult, verbose: bool = False) -> None:
    """Print status for a completed job."""
    status = "✓ PASS" if result.success else "✗ FAIL"
    duration_str = f"{result.duration_secs:.1f}s"

    print(f"{status} [{duration_str}] {result.job}")

    if verbose or not result.success:
        # Print output for failed jobs or when verbose
        print("=" * 80)
        print(result.output)
        print("=" * 80)


def print_summary(results: list[JobResult]) -> None:
    """Print summary of all job results."""
    passed = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)
    total = len(results)

    print("\n" + "=" * 80)
    print(f"Summary: {passed} passed, {failed} failed, {total} total")

    if failed > 0:
        print("\nFailed jobs:")
        for result in results:
            if not result.success:
                print(f"  - {result.job}")


def run_jobs(
    jobs: list[CIJob],
    repo_path: Path,
    build_jobs: int,
    max_parallel: int | None = None,
    verbose: bool = False,
    dry_run: bool = False,
) -> int:
    """
    Run CI jobs in parallel.

    Args:
        jobs: List of CI jobs to run
        repo_path: Path to the repository
        build_jobs: Number of parallel build jobs (-j flag)
        max_parallel: Maximum number of jobs to run in parallel (None = unlimited)
        verbose: Print detailed output
        dry_run: Print commands without executing

    Returns:
        Exit code: 0 if all jobs passed, 1 if any failed
    """
    if not jobs:
        print("No jobs to run")
        return 0

    print(f"Running {len(jobs)} job(s)")
    if dry_run:
        print("[DRY RUN MODE - no commands will be executed]")
    print()

    results: list[JobResult] = []

    # Use ThreadPoolExecutor for parallel execution
    # I/O-bound tasks (waiting on Docker) benefit from threads
    max_workers = max_parallel if max_parallel else len(jobs)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all jobs
        future_to_job = {
            executor.submit(run_job, job, repo_path, build_jobs, verbose, dry_run): job
            for job in jobs
        }

        # Process results as they complete
        for future in as_completed(future_to_job):
            result = future.result()
            results.append(result)
            print_job_status(result, verbose)

    # Print summary
    print_summary(results)

    # Return exit code
    any_failed = any(not r.success for r in results)
    return 1 if any_failed else 0
