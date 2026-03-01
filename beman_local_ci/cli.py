# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Command-line interface for beman-local-ci."""

import argparse
import os
import sys
from pathlib import Path

from beman_local_ci.lib.docker import check_docker
from beman_local_ci.lib.filter import filter_jobs, parse_filter_args
from beman_local_ci.lib.matrix import get_jobs_from_repo
from beman_local_ci.lib.runner import run_jobs


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for global options."""
    parser = argparse.ArgumentParser(
        description="Run Beman CI matrix locally via Docker",
        epilog="""
Filter syntax:
  --compiler COMPILER       Filter by compiler (gcc, clang)
  --versions V1,V2          Filter by compiler versions (must follow --compiler)
  --cxxversions V1,V2       Filter by C++ versions (must follow --versions)
  --stdlibs S1,S2           Filter by standard libraries (must follow --versions)
  --tests T1,T2             Filter by test types (must follow --versions)

Examples:
  # Run all jobs
  beman-local-ci -C /path/to/repo

  # Run only gcc 15 jobs
  beman-local-ci -C /path/to/repo --compiler gcc --versions 15

  # Run clang 21 with libc++ and Debug builds
  beman-local-ci -C /path/to/repo --compiler clang --versions 21 --stdlibs libc++ --tests Debug.Default

  # Run multiple compiler/version combinations
  beman-local-ci --compiler gcc --versions 15,14 --compiler clang --versions 21
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
        default=os.cpu_count(),
        help="Number of parallel build jobs (default: CPU count)",
    )

    def parallel_type(value: str) -> int | None:
        if value == "all":
            return None
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
        default=2,
        help="Maximum number of parallel CI jobs (default: 2, use 'all' for unlimited)",
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
    )

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
