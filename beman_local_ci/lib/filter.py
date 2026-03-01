# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""CLI filter parsing and job matching."""

from dataclasses import dataclass

from beman_local_ci.lib.matrix import CIJob


@dataclass
class FilterGroup:
    """Flat filter where each dimension is independent.

    None means "match all" for that dimension.
    """

    compilers: list[str] | None = None
    versions: list[str] | None = None
    cxxversions: list[str] | None = None
    stdlibs: list[str] | None = None
    tests: list[str] | None = None

    def matches(self, job: CIJob) -> bool:
        """Check if this filter group matches the job."""
        if self.compilers is not None and job.compiler not in self.compilers:
            return False
        if self.versions is not None and job.version not in self.versions:
            return False
        if self.cxxversions is not None and job.cxxversion not in self.cxxversions:
            return False
        if self.stdlibs is not None and job.stdlib not in self.stdlibs:
            return False
        if self.tests is not None and job.test not in self.tests:
            return False
        return True


def _parse_comma_values(raw: str, flag: str) -> list[str]:
    """Split comma-separated values, stripping whitespace. Error if empty."""
    values = [v.strip() for v in raw.split(",") if v.strip()]
    if not values:
        raise ValueError(f"{flag} requires at least one non-empty value")
    return values


def parse_filter_args(args: list[str]) -> list[FilterGroup]:
    """
    Parse filter arguments into FilterGroup objects.

    Rules:
    - --compiler X,Y starts a new FilterGroup (OR boundary).
    - --versions, --cxxversions, --stdlibs, --tests set their field on the
      current group.
    - If no --compiler precedes a dimension flag, an implicit group
      (compilers=None) is created.
    - Same flag twice in one group: last writer wins.

    Returns empty list if no filters specified (match all).
    """
    if not args:
        return []

    filters: list[FilterGroup] = []
    current: FilterGroup | None = None

    DIMENSION_FLAGS = ("--versions", "--cxxversions", "--stdlibs", "--tests")

    i = 0
    while i < len(args):
        arg = args[i]

        if arg == "--compiler":
            if i + 1 >= len(args):
                raise ValueError("--compiler requires a value")
            current = FilterGroup(
                compilers=_parse_comma_values(args[i + 1], "--compiler")
            )
            filters.append(current)
            i += 2

        elif arg in DIMENSION_FLAGS:
            if i + 1 >= len(args):
                raise ValueError(f"{arg} requires a value")
            values = _parse_comma_values(args[i + 1], arg)

            # Create implicit group if no --compiler preceded this flag
            if current is None:
                current = FilterGroup()
                filters.append(current)

            if arg == "--versions":
                current.versions = values
            elif arg == "--cxxversions":
                current.cxxversions = values
            elif arg == "--stdlibs":
                current.stdlibs = values
            elif arg == "--tests":
                current.tests = values

            i += 2

        else:
            raise ValueError(f"Unknown filter argument: {arg}")

    return filters


def matches_filters(job: CIJob, filters: list[FilterGroup]) -> bool:
    """
    Check if a job matches any of the filters.

    Empty filter list matches all jobs.
    """
    if not filters:
        return True

    return any(f.matches(job) for f in filters)


def filter_jobs(jobs: list[CIJob], filters: list[FilterGroup]) -> list[CIJob]:
    """Filter jobs based on FilterGroup list."""
    return [job for job in jobs if matches_filters(job, filters)]
