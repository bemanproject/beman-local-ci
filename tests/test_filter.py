# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Tests for filter parsing and matching."""

import pytest

from beman_local_ci.lib.filter import (
    CompilerFilter,
    VersionFilter,
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


def test_version_filter_matches_version():
    """Test VersionFilter matches correct version."""
    vf = VersionFilter(versions=["15"])
    job = CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default")
    assert vf.matches(job)


def test_version_filter_rejects_wrong_version():
    """Test VersionFilter rejects wrong version."""
    vf = VersionFilter(versions=["15"])
    job = CIJob("gcc", "14", "c++26", "libstdc++", "Debug.Default")
    assert not vf.matches(job)


def test_version_filter_multiple_versions():
    """Test VersionFilter with multiple versions."""
    vf = VersionFilter(versions=["15", "14"])
    job1 = CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default")
    job2 = CIJob("gcc", "14", "c++26", "libstdc++", "Debug.Default")
    job3 = CIJob("gcc", "13", "c++26", "libstdc++", "Debug.Default")

    assert vf.matches(job1)
    assert vf.matches(job2)
    assert not vf.matches(job3)


def test_version_filter_with_cxxversion():
    """Test VersionFilter with cxxversion filter."""
    vf = VersionFilter(versions=["15"], cxxversions=["c++26"])
    job1 = CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default")
    job2 = CIJob("gcc", "15", "c++23", "libstdc++", "Debug.Default")

    assert vf.matches(job1)
    assert not vf.matches(job2)


def test_version_filter_with_stdlib():
    """Test VersionFilter with stdlib filter."""
    vf = VersionFilter(versions=["21"], stdlibs=["libc++"])
    job1 = CIJob("clang", "21", "c++26", "libc++", "Debug.Default")
    job2 = CIJob("clang", "21", "c++26", "libstdc++", "Debug.Default")

    assert vf.matches(job1)
    assert not vf.matches(job2)


def test_version_filter_with_test():
    """Test VersionFilter with test filter."""
    vf = VersionFilter(versions=["15"], tests=["Debug.Default"])
    job1 = CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default")
    job2 = CIJob("gcc", "15", "c++26", "libstdc++", "Release.TSan")

    assert vf.matches(job1)
    assert not vf.matches(job2)


def test_version_filter_with_all_subfilters():
    """Test VersionFilter with all sub-filters."""
    vf = VersionFilter(
        versions=["15"],
        cxxversions=["c++26"],
        stdlibs=["libstdc++"],
        tests=["Debug.Default"],
    )

    job_match = CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default")
    job_wrong_cxx = CIJob("gcc", "15", "c++23", "libstdc++", "Debug.Default")
    job_wrong_stdlib = CIJob("gcc", "15", "c++26", "libc++", "Debug.Default")
    job_wrong_test = CIJob("gcc", "15", "c++26", "libstdc++", "Release.TSan")

    assert vf.matches(job_match)
    assert not vf.matches(job_wrong_cxx)
    assert not vf.matches(job_wrong_stdlib)
    assert not vf.matches(job_wrong_test)


def test_compiler_filter_matches_compiler():
    """Test CompilerFilter matches correct compiler."""
    cf = CompilerFilter(compiler="gcc")
    job_gcc = CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default")
    job_clang = CIJob("clang", "21", "c++26", "libc++", "Debug.Default")

    assert cf.matches(job_gcc)
    assert not cf.matches(job_clang)


def test_compiler_filter_no_version_filters_matches_all():
    """Test CompilerFilter with no version filters matches all versions."""
    cf = CompilerFilter(compiler="gcc")
    job1 = CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default")
    job2 = CIJob("gcc", "14", "c++23", "libstdc++", "Release.TSan")

    assert cf.matches(job1)
    assert cf.matches(job2)


def test_compiler_filter_with_version_filters():
    """Test CompilerFilter with version filters."""
    cf = CompilerFilter(
        compiler="gcc", version_filters=[VersionFilter(versions=["15"])]
    )

    job1 = CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default")
    job2 = CIJob("gcc", "14", "c++26", "libstdc++", "Debug.Default")

    assert cf.matches(job1)
    assert not cf.matches(job2)


def test_parse_filter_args_empty():
    """Test parsing empty filter args."""
    filters = parse_filter_args([])
    assert filters == []


def test_parse_filter_args_single_compiler():
    """Test parsing single compiler filter."""
    filters = parse_filter_args(["--compiler", "gcc"])

    assert len(filters) == 1
    assert filters[0].compiler == "gcc"
    assert filters[0].version_filters == []


def test_parse_filter_args_compiler_with_versions():
    """Test parsing compiler with versions."""
    filters = parse_filter_args(["--compiler", "gcc", "--versions", "15,14"])

    assert len(filters) == 1
    assert filters[0].compiler == "gcc"
    assert len(filters[0].version_filters) == 1
    assert filters[0].version_filters[0].versions == ["15", "14"]


def test_parse_filter_args_full_filter():
    """Test parsing full filter with all sub-filters."""
    filters = parse_filter_args(
        [
            "--compiler",
            "gcc",
            "--versions",
            "15",
            "--cxxversions",
            "c++26,c++23",
            "--stdlibs",
            "libstdc++",
            "--tests",
            "Debug.Default",
        ]
    )

    assert len(filters) == 1
    cf = filters[0]
    assert cf.compiler == "gcc"
    assert len(cf.version_filters) == 1

    vf = cf.version_filters[0]
    assert vf.versions == ["15"]
    assert vf.cxxversions == ["c++26", "c++23"]
    assert vf.stdlibs == ["libstdc++"]
    assert vf.tests == ["Debug.Default"]


def test_parse_filter_args_multiple_compilers():
    """Test parsing multiple compiler filters."""
    filters = parse_filter_args(
        ["--compiler", "gcc", "--versions", "15", "--compiler", "clang"]
    )

    assert len(filters) == 2
    assert filters[0].compiler == "gcc"
    assert filters[1].compiler == "clang"


def test_parse_filter_args_multiple_version_filters():
    """Test parsing multiple version filters for same compiler."""
    filters = parse_filter_args(
        [
            "--compiler",
            "gcc",
            "--versions",
            "15",
            "--tests",
            "Debug.Default",
            "--versions",
            "14",
            "--tests",
            "Release.TSan",
        ]
    )

    assert len(filters) == 1
    cf = filters[0]
    assert cf.compiler == "gcc"
    assert len(cf.version_filters) == 2

    vf1 = cf.version_filters[0]
    assert vf1.versions == ["15"]
    assert vf1.tests == ["Debug.Default"]

    vf2 = cf.version_filters[1]
    assert vf2.versions == ["14"]
    assert vf2.tests == ["Release.TSan"]


def test_parse_filter_args_error_no_compiler_value():
    """Test error when --compiler has no value."""
    with pytest.raises(ValueError, match="--compiler requires a value"):
        parse_filter_args(["--compiler"])


def test_parse_filter_args_error_no_versions_value():
    """Test error when --versions has no value."""
    with pytest.raises(ValueError, match="--versions requires a value"):
        parse_filter_args(["--compiler", "gcc", "--versions"])


def test_parse_filter_args_error_versions_without_compiler():
    """Test error when --versions appears before --compiler."""
    with pytest.raises(ValueError, match="--versions must follow --compiler"):
        parse_filter_args(["--versions", "15"])


def test_parse_filter_args_error_cxxversions_without_versions():
    """Test error when --cxxversions appears without --versions."""
    with pytest.raises(ValueError, match="--cxxversions must follow --versions"):
        parse_filter_args(["--compiler", "gcc", "--cxxversions", "c++26"])


def test_parse_filter_args_error_unknown_arg():
    """Test error on unknown argument."""
    with pytest.raises(ValueError, match="Unknown filter argument"):
        parse_filter_args(["--unknown", "value"])


def test_matches_filters_empty_filters_matches_all(sample_jobs):
    """Test that empty filter list matches all jobs."""
    for job in sample_jobs:
        assert matches_filters(job, [])


def test_matches_filters_compiler_only(sample_jobs):
    """Test filtering by compiler only."""
    filters = [CompilerFilter(compiler="gcc")]

    gcc_jobs = [j for j in sample_jobs if matches_filters(j, filters)]
    assert len(gcc_jobs) == 3
    assert all(j.compiler == "gcc" for j in gcc_jobs)


def test_matches_filters_multiple_compilers(sample_jobs):
    """Test filtering with multiple compilers."""
    filters = [CompilerFilter(compiler="gcc"), CompilerFilter(compiler="clang")]

    # Should match all jobs
    matched = [j for j in sample_jobs if matches_filters(j, filters)]
    assert len(matched) == len(sample_jobs)


def test_matches_filters_specific_version(sample_jobs):
    """Test filtering by specific version."""
    filters = [
        CompilerFilter(compiler="gcc", version_filters=[VersionFilter(versions=["15"])])
    ]

    matched = [j for j in sample_jobs if matches_filters(j, filters)]
    assert len(matched) == 2
    assert all(j.compiler == "gcc" and j.version == "15" for j in matched)


def test_matches_filters_complex(sample_jobs):
    """Test complex filter with multiple constraints."""
    filters = [
        CompilerFilter(
            compiler="clang",
            version_filters=[
                VersionFilter(
                    versions=["21"], stdlibs=["libc++"], tests=["Debug.Default"]
                )
            ],
        )
    ]

    matched = [j for j in sample_jobs if matches_filters(j, filters)]
    assert len(matched) == 1
    assert matched[0].compiler == "clang"
    assert matched[0].version == "21"
    assert matched[0].stdlib == "libc++"
    assert matched[0].test == "Debug.Default"


def test_filter_jobs(sample_jobs):
    """Test filter_jobs convenience function."""
    filters = [CompilerFilter(compiler="gcc")]
    filtered = filter_jobs(sample_jobs, filters)

    assert len(filtered) == 3
    assert all(j.compiler == "gcc" for j in filtered)


def test_filter_jobs_empty_filters_returns_all(sample_jobs):
    """Test filter_jobs with empty filters returns all jobs."""
    filtered = filter_jobs(sample_jobs, [])
    assert filtered == sample_jobs
