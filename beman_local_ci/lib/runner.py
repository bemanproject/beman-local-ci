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
from beman_local_ci.lib.docker import (
    BUILD_CACHE_DIR,
    build_docker_command,
    create_build_dir,
)
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


class _StatsCollector:
    """Polls ``docker stats`` in a background thread, tracking peak values."""

    def __init__(self, cidfile: Path):
        self.cidfile = cidfile
        self.peak_cpu_percent = 0.0
        self.peak_memory_mib = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._poll, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    # ── internals ─────────────────────────────────────────────────────────

    def _poll(self) -> None:
        while not self._stop.is_set():
            try:
                cid = self.cidfile.read_text().strip()
                if not cid:
                    self._stop.wait(0.5)
                    continue
                result = subprocess.run(
                    [
                        "docker",
                        "stats",
                        "--no-stream",
                        "--format",
                        "{{.CPUPerc}}\t{{.MemUsage}}",
                        cid,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    start_new_session=True,
                )
                if result.returncode == 0:
                    self._parse(result.stdout.strip())
            except Exception:
                pass
            self._stop.wait(1)

    def _parse(self, line: str) -> None:
        parts = line.split("\t")
        if len(parts) < 2:
            return
        try:
            cpu = float(parts[0].rstrip("%"))
            self.peak_cpu_percent = max(self.peak_cpu_percent, cpu)
        except ValueError:
            pass
        try:
            mem_str = parts[1].split("/")[0].strip()
            self.peak_memory_mib = max(self.peak_memory_mib, self._parse_mem(mem_str))
        except (ValueError, IndexError):
            pass

    @staticmethod
    def _parse_mem(s: str) -> float:
        """Parse a Docker memory string (e.g. '1.23GiB') to MiB."""
        s = s.strip()
        for suffix, factor in (("GiB", 1024), ("MiB", 1), ("KiB", 1 / 1024)):
            if s.endswith(suffix):
                return float(s[: -len(suffix)]) * factor
        if s.endswith("B"):
            return float(s[:-1]) / (1024 * 1024)
        return 0.0


@dataclass
class JobResult:
    """Result of running a CI job."""

    job: CIJob
    success: bool
    duration_secs: float
    output: str
    return_code: int
    peak_cpu_percent: float | None = None
    peak_memory_mib: float | None = None


def run_job(
    job: CIJob,
    repo_path: Path,
    build_jobs: int,
    verbose: bool = False,
    dry_run: bool = False,
    track_performance: bool = False,
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
    build_dir = create_build_dir(job, repo_name=repo_path.name)

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
    collector: _StatsCollector | None = None

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

        with _active_procs_lock:
            _active_procs.add((cidfile, proc))

        if track_performance:
            collector = _StatsCollector(cidfile)
            collector.start()

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

        peak_cpu = None
        peak_mem = None
        if collector is not None:
            collector.stop()
            peak_cpu = collector.peak_cpu_percent
            peak_mem = collector.peak_memory_mib
            collector = None

        return JobResult(
            job=job,
            success=proc.returncode == 0,
            duration_secs=time.time() - start_time,
            output=output,
            return_code=proc.returncode,
            peak_cpu_percent=peak_cpu,
            peak_memory_mib=peak_mem,
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
        if collector is not None:
            collector.stop()
        if proc is not None:
            with _active_procs_lock:
                _active_procs.discard((cidfile, proc))
        cidfile.unlink(missing_ok=True)


def _format_memory(mib: float) -> str:
    """Format MiB as a human-readable string."""
    if mib >= 1024:
        return f"{mib / 1024:.1f} GiB"
    return f"{mib:.0f} MiB"


def print_job_status(result: JobResult, verbose: bool = False) -> None:
    """Print status for a completed job."""
    status = "✓ PASS" if result.success else "✗ FAIL"
    duration_str = f"{result.duration_secs:.1f}s"

    perf = ""
    if result.peak_memory_mib is not None:
        perf = (
            f"  [peak: {_format_memory(result.peak_memory_mib)} mem, "
            f"{result.peak_cpu_percent:.0f}% cpu]"
        )

    print(f"{status} [{duration_str}] {result.job}{perf}")

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
        print(f"\nNote: You can clear the build cache with: rm -rf {BUILD_CACHE_DIR}")


def run_jobs(
    jobs: list[CIJob],
    repo_path: Path,
    build_jobs: int,
    max_parallel: int | None = None,
    verbose: bool = False,
    dry_run: bool = False,
    track_performance: bool = False,
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
        track_performance: Poll docker stats and report peak CPU/memory per job

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
        executor.submit(
            run_job, job, repo_path, build_jobs, verbose, dry_run, track_performance
        ): job
        for job in jobs
    }

    try:
        for future in as_completed(future_to_job):
            result = future.result()
            results.append(result)
            print_job_status(result, verbose)
    except KeyboardInterrupt:
        print("\nInterrupted — killing running containers...")
        executor.shutdown(wait=False, cancel_futures=True)
        _kill_all_containers()
        # Wait for worker threads to finish now that containers are dead.
        # Without this, the ThreadPoolExecutor atexit handler blocks on
        # t.join() during interpreter shutdown, requiring a second Ctrl-C.
        executor.shutdown(wait=True)
        return 130

    executor.shutdown(wait=False)
    print_summary(results)
    return 1 if any(not r.success for r in results) else 0
