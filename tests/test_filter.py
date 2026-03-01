# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Tests for filter parsing and matching."""

import pytest

from beman_local_ci.lib.filter import (
    FilterGroup,
    filter_jobs,
    matches_filters,
    parse_filter_args,
)
from beman_local_ci.lib.matrix import CIJob


@pytest.fixture
def sample_jobs():
    """Sample jobs for testing."""
    return [
        CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default"),
        CIJob("gcc", "15", "c++26", "libstdc++", "Release.Default"),
        CIJob("gcc", "14", "c++26", "libstdc++", "Debug.Default"),
        CIJob("clang", "21", "c++26", "libc++", "Debug.Default"),
        CIJob("clang", "21", "c++26", "libstdc++", "Release.TSan"),
        CIJob("clang", "20", "c++23", "libc++", "Release.Default"),
    ]


# ── FilterGroup.matches unit tests ──────────────────────────────────


class TestFilterGroupMatches:
    """Unit tests for FilterGroup.matches."""

    def test_all_none_matches_everything(self):
        fg = FilterGroup()
        assert fg.matches(CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default"))

    def test_compiler_match(self):
        fg = FilterGroup(compilers=["gcc"])
        assert fg.matches(CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default"))
        assert not fg.matches(
            CIJob("clang", "21", "c++26", "libc++", "Debug.Default")
        )

    def test_compiler_multi(self):
        fg = FilterGroup(compilers=["gcc", "clang"])
        assert fg.matches(CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default"))
        assert fg.matches(CIJob("clang", "21", "c++26", "libc++", "Debug.Default"))

    def test_versions_only(self):
        fg = FilterGroup(versions=["15"])
        assert fg.matches(CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default"))
        assert not fg.matches(
            CIJob("gcc", "14", "c++26", "libstdc++", "Debug.Default")
        )

    def test_cxxversions_only(self):
        fg = FilterGroup(cxxversions=["c++26"])
        assert fg.matches(CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default"))
        assert not fg.matches(
            CIJob("clang", "20", "c++23", "libc++", "Release.Default")
        )

    def test_stdlibs_only(self):
        fg = FilterGroup(stdlibs=["libc++"])
        assert fg.matches(CIJob("clang", "21", "c++26", "libc++", "Debug.Default"))
        assert not fg.matches(
            CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default")
        )

    def test_tests_only(self):
        fg = FilterGroup(tests=["Debug.Default"])
        assert fg.matches(CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default"))
        assert not fg.matches(
            CIJob("clang", "21", "c++26", "libstdc++", "Release.TSan")
        )

    def test_multiple_dimensions(self):
        fg = FilterGroup(
            compilers=["clang"],
            versions=["21"],
            stdlibs=["libc++"],
            tests=["Debug.Default"],
        )
        assert fg.matches(CIJob("clang", "21", "c++26", "libc++", "Debug.Default"))
        assert not fg.matches(
            CIJob("clang", "21", "c++26", "libstdc++", "Release.TSan")
        )
        assert not fg.matches(
            CIJob("gcc", "21", "c++26", "libc++", "Debug.Default")
        )

    def test_all_five_dimensions(self):
        fg = FilterGroup(
            compilers=["gcc"],
            versions=["15"],
            cxxversions=["c++26"],
            stdlibs=["libstdc++"],
            tests=["Debug.Default"],
        )
        assert fg.matches(CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default"))
        assert not fg.matches(
            CIJob("gcc", "15", "c++23", "libstdc++", "Debug.Default")
        )
        assert not fg.matches(
            CIJob("gcc", "15", "c++26", "libc++", "Debug.Default")
        )
        assert not fg.matches(
            CIJob("gcc", "15", "c++26", "libstdc++", "Release.TSan")
        )


# ── parse_filter_args tests ─────────────────────────────────────────


class TestParseFilterArgs:
    """Tests for the argument parser."""

    def test_empty(self):
        assert parse_filter_args([]) == []

    def test_single_compiler(self):
        groups = parse_filter_args(["--compiler", "gcc"])
        assert len(groups) == 1
        assert groups[0].compilers == ["gcc"]
        assert groups[0].versions is None

    def test_compiler_with_versions(self):
        groups = parse_filter_args(["--compiler", "gcc", "--versions", "15,14"])
        assert len(groups) == 1
        assert groups[0].compilers == ["gcc"]
        assert groups[0].versions == ["15", "14"]

    def test_full_filter(self):
        groups = parse_filter_args(
            [
                "--compiler", "gcc",
                "--versions", "15",
                "--cxxversions", "c++26,c++23",
                "--stdlibs", "libstdc++",
                "--tests", "Debug.Default",
            ]
        )
        assert len(groups) == 1
        g = groups[0]
        assert g.compilers == ["gcc"]
        assert g.versions == ["15"]
        assert g.cxxversions == ["c++26", "c++23"]
        assert g.stdlibs == ["libstdc++"]
        assert g.tests == ["Debug.Default"]

    def test_multiple_compilers_create_multiple_groups(self):
        groups = parse_filter_args(
            ["--compiler", "gcc", "--versions", "15", "--compiler", "clang"]
        )
        assert len(groups) == 2
        assert groups[0].compilers == ["gcc"]
        assert groups[0].versions == ["15"]
        assert groups[1].compilers == ["clang"]
        assert groups[1].versions is None

    def test_comma_separated_compilers(self):
        groups = parse_filter_args(["--compiler", "gcc,clang"])
        assert len(groups) == 1
        assert groups[0].compilers == ["gcc", "clang"]

    def test_standalone_cxxversions_no_compiler(self):
        """--cxxversions without preceding --compiler creates implicit group."""
        groups = parse_filter_args(["--cxxversions", "c++26"])
        assert len(groups) == 1
        assert groups[0].compilers is None
        assert groups[0].cxxversions == ["c++26"]

    def test_standalone_versions_no_compiler(self):
        groups = parse_filter_args(["--versions", "15"])
        assert len(groups) == 1
        assert groups[0].compilers is None
        assert groups[0].versions == ["15"]

    def test_standalone_stdlibs_no_compiler(self):
        groups = parse_filter_args(["--stdlibs", "libc++"])
        assert len(groups) == 1
        assert groups[0].compilers is None
        assert groups[0].stdlibs == ["libc++"]

    def test_standalone_tests_no_compiler(self):
        groups = parse_filter_args(["--tests", "Debug.Default"])
        assert len(groups) == 1
        assert groups[0].compilers is None
        assert groups[0].tests == ["Debug.Default"]

    def test_last_writer_wins(self):
        """Same flag twice in one group: last value wins."""
        groups = parse_filter_args(
            ["--compiler", "gcc", "--versions", "15", "--versions", "14"]
        )
        assert len(groups) == 1
        assert groups[0].versions == ["14"]

    def test_compiler_starts_new_group_resets_dimensions(self):
        groups = parse_filter_args(
            [
                "--compiler", "gcc",
                "--versions", "15",
                "--cxxversions", "c++26",
                "--compiler", "clang",
                "--cxxversions", "c++23",
            ]
        )
        assert len(groups) == 2
        assert groups[0].compilers == ["gcc"]
        assert groups[0].versions == ["15"]
        assert groups[0].cxxversions == ["c++26"]
        assert groups[1].compilers == ["clang"]
        assert groups[1].versions is None
        assert groups[1].cxxversions == ["c++23"]

    def test_implicit_group_then_compiler_group(self):
        groups = parse_filter_args(
            ["--cxxversions", "c++26", "--compiler", "gcc", "--versions", "15"]
        )
        assert len(groups) == 2
        assert groups[0].compilers is None
        assert groups[0].cxxversions == ["c++26"]
        assert groups[1].compilers == ["gcc"]
        assert groups[1].versions == ["15"]


# ── Error cases ──────────────────────────────────────────────────────


class TestParseFilterArgsErrors:
    """Error handling in parse_filter_args."""

    def test_compiler_missing_value(self):
        with pytest.raises(ValueError, match="--compiler requires a value"):
            parse_filter_args(["--compiler"])

    def test_versions_missing_value(self):
        with pytest.raises(ValueError, match="--versions requires a value"):
            parse_filter_args(["--compiler", "gcc", "--versions"])

    def test_cxxversions_missing_value(self):
        with pytest.raises(ValueError, match="--cxxversions requires a value"):
            parse_filter_args(["--cxxversions"])

    def test_stdlibs_missing_value(self):
        with pytest.raises(ValueError, match="--stdlibs requires a value"):
            parse_filter_args(["--stdlibs"])

    def test_tests_missing_value(self):
        with pytest.raises(ValueError, match="--tests requires a value"):
            parse_filter_args(["--tests"])

    def test_unknown_arg(self):
        with pytest.raises(ValueError, match="Unknown filter argument"):
            parse_filter_args(["--unknown", "value"])

    def test_empty_comma_values(self):
        with pytest.raises(ValueError, match="requires at least one non-empty value"):
            parse_filter_args(["--compiler", ",,,"])


# ── matches_filters / filter_jobs integration ────────────────────────


class TestMatchesFilters:
    """Integration tests for matches_filters and filter_jobs."""

    def test_empty_filters_matches_all(self, sample_jobs):
        for job in sample_jobs:
            assert matches_filters(job, [])

    def test_compiler_only(self, sample_jobs):
        filters = [FilterGroup(compilers=["gcc"])]
        gcc_jobs = [j for j in sample_jobs if matches_filters(j, filters)]
        assert len(gcc_jobs) == 3
        assert all(j.compiler == "gcc" for j in gcc_jobs)

    def test_multiple_groups_or(self, sample_jobs):
        filters = [
            FilterGroup(compilers=["gcc"]),
            FilterGroup(compilers=["clang"]),
        ]
        matched = [j for j in sample_jobs if matches_filters(j, filters)]
        assert len(matched) == len(sample_jobs)

    def test_specific_version(self, sample_jobs):
        filters = [FilterGroup(compilers=["gcc"], versions=["15"])]
        matched = [j for j in sample_jobs if matches_filters(j, filters)]
        assert len(matched) == 2
        assert all(j.compiler == "gcc" and j.version == "15" for j in matched)

    def test_complex_filter(self, sample_jobs):
        filters = [
            FilterGroup(
                compilers=["clang"],
                versions=["21"],
                stdlibs=["libc++"],
                tests=["Debug.Default"],
            )
        ]
        matched = [j for j in sample_jobs if matches_filters(j, filters)]
        assert len(matched) == 1
        assert matched[0] == CIJob(
            "clang", "21", "c++26", "libc++", "Debug.Default"
        )

    def test_standalone_cxxversion_filter(self, sample_jobs):
        """The motivating use case: --compiler gcc --cxxversions c++26."""
        filters = [FilterGroup(compilers=["gcc"], cxxversions=["c++26"])]
        matched = filter_jobs(sample_jobs, filters)
        assert len(matched) == 3
        assert all(j.compiler == "gcc" and j.cxxversion == "c++26" for j in matched)

    def test_cxxversion_only_no_compiler(self, sample_jobs):
        filters = [FilterGroup(cxxversions=["c++23"])]
        matched = filter_jobs(sample_jobs, filters)
        assert len(matched) == 1
        assert matched[0].cxxversion == "c++23"

    def test_filter_jobs_empty_filters(self, sample_jobs):
        assert filter_jobs(sample_jobs, []) == sample_jobs

    def test_filter_jobs_convenience(self, sample_jobs):
        filters = [FilterGroup(compilers=["gcc"])]
        filtered = filter_jobs(sample_jobs, filters)
        assert len(filtered) == 3
        assert all(j.compiler == "gcc" for j in filtered)


# ── End-to-end: parse_filter_args → filter_jobs ─────────────────────


class TestEndToEnd:
    """Parse CLI tokens and filter jobs in one pass."""

    def test_compiler_cxxversions_directly(self, sample_jobs):
        """--compiler gcc --cxxversions c++26 (was an error before)."""
        groups = parse_filter_args(["--compiler", "gcc", "--cxxversions", "c++26"])
        matched = filter_jobs(sample_jobs, groups)
        assert len(matched) == 3
        assert all(j.compiler == "gcc" and j.cxxversion == "c++26" for j in matched)

    def test_standalone_cxxversions(self, sample_jobs):
        groups = parse_filter_args(["--cxxversions", "c++23"])
        matched = filter_jobs(sample_jobs, groups)
        assert len(matched) == 1

    def test_two_compiler_groups(self, sample_jobs):
        groups = parse_filter_args(
            [
                "--compiler", "gcc", "--versions", "15",
                "--compiler", "clang", "--versions", "21", "--stdlibs", "libc++",
            ]
        )
        matched = filter_jobs(sample_jobs, groups)
        # gcc 15: 2 jobs; clang 21 + libc++: 1 job
        assert len(matched) == 3
