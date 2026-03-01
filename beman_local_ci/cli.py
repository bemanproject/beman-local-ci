# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Command-line interface for beman-local-ci."""

import argparse
import math
import os
import platform
import sys
from pathlib import Path

from beman_local_ci.lib.docker import (
    check_build_cache_ownership,
    check_docker,
    get_docker_memory_bytes,
    get_system_memory_bytes,
)
from beman_local_ci.lib.filter import filter_jobs, parse_filter_args
from beman_local_ci.lib.matrix import get_jobs_from_repo
from beman_local_ci.lib.runner import run_jobs


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for global options."""
    parser = argparse.ArgumentParser(
        description="Run Beman CI matrix locally via Docker",
        epilog="""
Filter syntax (all dimensions are independent — omitted ones match all):
  --compiler C1,C2          Filter by compiler (gcc, clang). Starts a new filter group.
  --versions V1,V2          Filter by compiler versions
  --cxxversions V1,V2       Filter by C++ standard versions
  --stdlibs S1,S2           Filter by standard libraries
  --tests T1,T2             Filter by test types

  Multiple --compiler flags create OR groups. Within a group, dimensions are ANDed.
  Flags before the first --compiler create an implicit group (all compilers).

Examples:
  # Run all jobs
  beman-local-ci -C /path/to/repo

  # Run only gcc jobs
  beman-local-ci -C /path/to/repo --compiler gcc

  # Run only c++26 jobs (any compiler)
  beman-local-ci -C /path/to/repo --cxxversions c++26

  # Run gcc 15 c++26 jobs
  beman-local-ci -C /path/to/repo --compiler gcc --versions 15 --cxxversions c++26

  # Run gcc 15 OR clang 21 libc++ jobs
  beman-local-ci --compiler gcc --versions 15 --compiler clang --versions 21 --stdlibs libc++
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-C",
        "--directory",
        metavar="DIR",
        type=Path,
        default=Path.cwd(),
        help="Repository directory (default: current directory)",
    )

    parser.add_argument(
        "-j",
        "--jobs",
        metavar="N",
        type=int,
        default=None,
        help="Number of parallel build jobs (default: CPU count when -p 1, CPU count / 2 otherwise)",
    )

    _AUTO_PARALLEL = "auto"

    def parallel_type(value: str) -> int | str | None:
        if value == "all":
            return None
        if value == _AUTO_PARALLEL:
            return _AUTO_PARALLEL
        try:
            n = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"invalid value '{value}': expected a positive integer or 'all'"
            )
        if n < 1:
            raise argparse.ArgumentTypeError(
                f"invalid value '{value}': must be at least 1"
            )
        return n

    parser.add_argument(
        "-p",
        "--parallel",
        metavar="N",
        type=parallel_type,
        default="auto",
        help="Maximum number of parallel CI jobs (default: auto based on Docker memory, use 'all' for unlimited)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print Docker commands without executing them",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output for all jobs",
    )

    parser.add_argument(
        "--track-performance",
        action="store_true",
        help="Report peak CPU and memory usage for each job",
    )

    return parser


def main() -> int:
    """Main entry point."""
    parser = create_parser()

    # Parse known args to separate global options from filter tokens
    args, filter_tokens = parser.parse_known_args()

    # Validate repository directory
    repo_path = args.directory.resolve()
    if not repo_path.exists():
        print(
            f"Error: Repository directory does not exist: {repo_path}", file=sys.stderr
        )
        return 1

    ci_yaml_path = repo_path / ".github" / "workflows" / "ci_tests.yml"
    if not ci_yaml_path.exists():
        print(f"Error: CI YAML not found: {ci_yaml_path}", file=sys.stderr)
        return 1

    # Check Docker availability (skip in dry-run mode)
    if not args.dry_run:
        try:
            check_docker()
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    # Resolve auto-parallelism from Docker memory.
    GIB = 1024**3
    MEMORY_PER_CONTAINER_GIB = 5.9
    # Docker Desktop reserves overhead from the configured value (e.g.
    # slider set to 12 GB → 11.67 GiB reported).  A small fudge avoids
    # penalising users who set exactly the recommended amount.
    DOCKER_OVERHEAD_GIB = 0.5

    if args.parallel == "auto":
        docker_mem = get_docker_memory_bytes()
        if docker_mem is not None:
            effective_gib = docker_mem / GIB + DOCKER_OVERHEAD_GIB
            parallelism = max(1, math.floor(effective_gib / MEMORY_PER_CONTAINER_GIB))
            args.parallel = parallelism

            system_mem = get_system_memory_bytes()
            if system_mem is not None:
                epsilon = 0.5 * GIB
                if docker_mem < system_mem * 0.75 - epsilon:
                    # Suggest the highest parallelism reachable within
                    # 75% of system memory.
                    system_gib = system_mem / GIB
                    best_p = math.floor(
                        (system_gib * 0.75 + DOCKER_OVERHEAD_GIB)
                        / MEMORY_PER_CONTAINER_GIB
                    )
                    if best_p > parallelism:
                        needed_gib = best_p * 6
                        msg = (
                            f"Selected parallelism {parallelism} "
                            f"(increase available Docker memory to "
                            f"{needed_gib} GiB to increase default "
                            f"parallelism to {best_p})."
                        )
                        if platform.system() == "Darwin":
                            msg += "\n  Docker Desktop: Settings > Resources > Memory"
                    else:
                        msg = f"Selected parallelism {parallelism}."
                    print(msg, file=sys.stderr)
        else:
            args.parallel = 2  # fallback when Docker memory can't be queried

    # Resolve -j default now that -p is known.
    if args.jobs is None:
        nproc = os.cpu_count() or 1
        args.jobs = nproc if args.parallel == 1 else max(1, nproc // 2)

    # Check build cache ownership
    if not args.dry_run:
        cache_err = check_build_cache_ownership()
        if cache_err:
            print(f"Error: {cache_err}", file=sys.stderr)
            return 1

    # Parse filter arguments
    try:
        filters = parse_filter_args(filter_tokens)
    except ValueError as e:
        print(f"Error parsing filters: {e}", file=sys.stderr)
        print("\nUse --help to see filter syntax", file=sys.stderr)
        return 1

    # Load and expand matrix
    try:
        all_jobs = get_jobs_from_repo(repo_path)
    except Exception as e:
        print(f"Error loading CI matrix: {e}", file=sys.stderr)
        return 1

    # Apply filters
    filtered_jobs = filter_jobs(all_jobs, filters)

    if not filtered_jobs:
        print("No jobs match the specified filters")
        return 1

    # Print job count
    if filters:
        print(f"Filtered to {len(filtered_jobs)} of {len(all_jobs)} total jobs")

    # Run jobs
    exit_code = run_jobs(
        jobs=filtered_jobs,
        repo_path=repo_path,
        build_jobs=args.jobs,
        max_parallel=args.parallel,
        verbose=args.verbose,
        dry_run=args.dry_run,
        track_performance=args.track_performance,
    )

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
