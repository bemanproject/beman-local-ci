# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""CLI filter parsing and job matching."""

from dataclasses import dataclass, field

from beman_local_ci.lib.matrix import CIJob


@dataclass
class VersionFilter:
    """Filter for a specific set of compiler versions."""

    versions: list[str]
    cxxversions: list[str] | None = None
    stdlibs: list[str] | None = None
    tests: list[str] | None = None

    def matches(self, job: CIJob) -> bool:
        """Check if this version filter matches the job."""
        # Version must match
        if job.version not in self.versions:
            return False

        # Check sub-filters (None means match all)
        if self.cxxversions is not None and job.cxxversion not in self.cxxversions:
            return False

        if self.stdlibs is not None and job.stdlib not in self.stdlibs:
            return False

        if self.tests is not None and job.test not in self.tests:
            return False

        return True


@dataclass
class CompilerFilter:
    """Filter for a specific compiler."""

    compiler: str
    version_filters: list[VersionFilter] = field(default_factory=list)

    def matches(self, job: CIJob) -> bool:
        """Check if this compiler filter matches the job."""
        # Compiler must match
        if job.compiler != self.compiler:
            return False

        # If no version filters, match all versions
        if not self.version_filters:
            return True

        # Check if any version filter matches
        return any(vf.matches(job) for vf in self.version_filters)


def parse_filter_args(args: list[str]) -> list[CompilerFilter]:
    """
    Parse filter arguments into CompilerFilter objects.

    State machine parser:
    - --compiler X: start new CompilerFilter
    - --versions X,Y: start new VersionFilter within current compiler
    - --cxxversions/--stdlibs/--tests: attach to current version filter

    Returns empty list if no filters specified (match all).
    """
    if not args:
        return []

    filters: list[CompilerFilter] = []
    current_compiler: CompilerFilter | None = None
    current_version: VersionFilter | None = None

    i = 0
    while i < len(args):
        arg = args[i]

        if arg == "--compiler":
            if i + 1 >= len(args):
                raise ValueError("--compiler requires a value")

            # Start new compiler filter
            current_compiler = CompilerFilter(compiler=args[i + 1])
            filters.append(current_compiler)
            current_version = None  # Reset version context
            i += 2

        elif arg == "--versions":
            if i + 1 >= len(args):
                raise ValueError("--versions requires a value")
            if current_compiler is None:
                raise ValueError("--versions must follow --compiler")

            # Start new version filter
            versions = args[i + 1].split(",")
            current_version = VersionFilter(versions=versions)
            current_compiler.version_filters.append(current_version)
            i += 2

        elif arg == "--cxxversions":
            if i + 1 >= len(args):
                raise ValueError("--cxxversions requires a value")
            if current_version is None:
                raise ValueError("--cxxversions must follow --versions")

            current_version.cxxversions = args[i + 1].split(",")
            i += 2

        elif arg == "--stdlibs":
            if i + 1 >= len(args):
                raise ValueError("--stdlibs requires a value")
            if current_version is None:
                raise ValueError("--stdlibs must follow --versions")

            current_version.stdlibs = args[i + 1].split(",")
            i += 2

        elif arg == "--tests":
            if i + 1 >= len(args):
                raise ValueError("--tests requires a value")
            if current_version is None:
                raise ValueError("--tests must follow --versions")

            current_version.tests = args[i + 1].split(",")
            i += 2

        else:
            raise ValueError(f"Unknown filter argument: {arg}")

    return filters


def matches_filters(job: CIJob, filters: list[CompilerFilter]) -> bool:
    """
    Check if a job matches any of the filters.

    Empty filter list matches all jobs.
    """
    if not filters:
        return True

    return any(f.matches(job) for f in filters)


def filter_jobs(jobs: list[CIJob], filters: list[CompilerFilter]) -> list[CIJob]:
    """Filter jobs based on CompilerFilter list."""
    return [job for job in jobs if matches_filters(job, filters)]
