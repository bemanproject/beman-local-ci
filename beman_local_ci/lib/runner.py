# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Parallel job execution and result reporting."""

import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from beman_local_ci.lib.config import resolve_config
from beman_local_ci.lib.docker import build_docker_command, create_build_dir
from beman_local_ci.lib.matrix import CIJob

# Thread-safe registry of (cidfile, Popen) for every container currently running.
# Populated by run_job; read by _kill_all_containers on Ctrl-C.
_active_procs_lock = threading.Lock()
_active_procs: set[tuple[Path, "subprocess.Popen[str]"]] = set()


def _kill_all_containers() -> None:
    """
    SIGKILL every Docker container that is currently being tracked.

    For each active job we:
      1. Read the container ID from its --cidfile and run `docker kill -s KILL`.
      2. Also kill the docker-CLI subprocess directly, in case the cidfile was
         not yet written (i.e. the container had not fully started).
    """
    with _active_procs_lock:
        active = list(_active_procs)

    for cidfile, proc in active:
        try:
            cid = cidfile.read_text().strip()
            if cid:
                subprocess.run(
                    ["docker", "kill", "--signal", "KILL", cid],
                    capture_output=True,
                    timeout=5,
                )
        except Exception:
            pass


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

    # Create the cidfile path without actually creating the file; Docker writes
    # the container ID to it once the container starts, and refuses to run if
    # the file already exists.
    tmp = tempfile.NamedTemporaryFile(suffix=".cid", delete=False)
    cidfile = Path(tmp.name)
    tmp.close()
    cidfile.unlink()

    # Inject --cidfile right after --rm so we can identify the container later.
    rm_idx = cmd.index("--rm")
    cmd = cmd[: rm_idx + 1] + ["--cidfile", str(cidfile)] + cmd[rm_idx + 1 :]

    start_time = time.time()
    proc: "subprocess.Popen[str] | None" = None

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        with _active_procs_lock:
            _active_procs.add((cidfile, proc))

        try:
            stdout, stderr = proc.communicate(timeout=1800)  # 30 minute timeout
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            return JobResult(
                job=job,
                success=False,
                duration_secs=time.time() - start_time,
                output="Job timed out after 30 minutes",
                return_code=-1,
            )

        output = stdout
        if stderr:
            output += "\n" + stderr

        return JobResult(
            job=job,
            success=proc.returncode == 0,
            duration_secs=time.time() - start_time,
            output=output,
            return_code=proc.returncode,
        )

    except Exception as e:
        return JobResult(
            job=job,
            success=False,
            duration_secs=time.time() - start_time,
            output=f"Error running job: {e}",
            return_code=-1,
        )

    finally:
        if proc is not None:
            with _active_procs_lock:
                _active_procs.discard((cidfile, proc))
        cidfile.unlink(missing_ok=True)


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
        Exit code: 0 if all passed, 1 if any failed, 130 if interrupted (Ctrl-C)
    """
    if not jobs:
        print("No jobs to run")
        return 0

    print(f"Running {len(jobs)} job(s)")
    if dry_run:
        print("[DRY RUN MODE - no commands will be executed]")
    print()

    results: list[JobResult] = []

    # Use ThreadPoolExecutor for parallel execution.
    # Manage the executor manually (not as a context manager) so we can call
    # shutdown(cancel_futures=True) on Ctrl-C without waiting for the threads.
    max_workers = max_parallel if max_parallel else len(jobs)
    executor = ThreadPoolExecutor(max_workers=max_workers)

    future_to_job = {
        executor.submit(run_job, job, repo_path, build_jobs, verbose, dry_run): job
        for job in jobs
    }

    try:
        for future in as_completed(future_to_job):
            result = future.result()
            results.append(result)
            print_job_status(result, verbose)
    except KeyboardInterrupt:
        print("\nInterrupted — killing running containers...")
        _kill_all_containers()
        executor.shutdown(wait=False, cancel_futures=True)
        return 130

    executor.shutdown(wait=False)
    print_summary(results)
    return 1 if any(not r.success for r in results) else 0
