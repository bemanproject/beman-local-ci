# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Tests for matrix expansion."""

import json
from pathlib import Path

import pytest

from beman_local_ci.lib.matrix import (
    CIJob,
    expand_matrix,
    extract_matrix_config,
    get_jobs_from_repo,
)


def test_cijob_creation():
    """Test CIJob dataclass creation."""
    job = CIJob(
        compiler="gcc",
        version="15",
        cxxversion="c++26",
        stdlib="libstdc++",
        test="Debug.Default",
    )
    assert job.compiler == "gcc"
    assert job.version == "15"
    assert str(job) == "gcc 15 c++26 libstdc++ Debug.Default"


def test_cijob_frozen():
    """Test that CIJob is immutable."""
    job = CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default")
    with pytest.raises(Exception):  # FrozenInstanceError
        job.compiler = "clang"


def test_expand_matrix_simple(sample_matrix_simple):
    """Test matrix expansion with simple config."""
    jobs = list(expand_matrix(sample_matrix_simple))

    assert len(jobs) == 2
    assert jobs[0] == CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default")
    assert jobs[1] == CIJob("gcc", "15", "c++26", "libstdc++", "Release.Default")


def test_expand_matrix_utf_view(sample_matrix_utf_view):
    """Test matrix expansion with custom test strings."""
    jobs = list(expand_matrix(sample_matrix_utf_view))

    assert len(jobs) == 2
    assert jobs[0].test == "Debug.Default"
    assert jobs[1].test == "Debug.-DBEMAN_UTF_VIEW_BUILD_PAPER=ON"
    assert jobs[1].compiler == "gcc"
    assert jobs[1].version == "trunk"


def test_expand_matrix_skips_appleclang():
    """Test that appleclang jobs are skipped."""
    matrix = {
        "appleclang": [
            {
                "versions": ["latest"],
                "tests": [
                    {
                        "cxxversions": ["c++26"],
                        "tests": [
                            {"stdlibs": ["libc++"], "tests": ["Release.Default"]}
                        ],
                    }
                ],
            }
        ]
    }
    jobs = list(expand_matrix(matrix))
    assert len(jobs) == 0


def test_expand_matrix_skips_msvc():
    """Test that MSVC jobs are skipped."""
    matrix = {
        "msvc": [
            {
                "versions": ["latest"],
                "tests": [
                    {
                        "cxxversions": ["c++23"],
                        "tests": [{"stdlibs": ["stl"], "tests": ["Debug.Default"]}],
                    }
                ],
            }
        ]
    }
    jobs = list(expand_matrix(matrix))
    assert len(jobs) == 0


def test_expand_matrix_multiple_compilers():
    """Test expansion with multiple compilers and versions."""
    matrix = {
        "gcc": [
            {
                "versions": ["15", "14"],
                "tests": [
                    {
                        "cxxversions": ["c++26"],
                        "tests": [
                            {"stdlibs": ["libstdc++"], "tests": ["Debug.Default"]}
                        ],
                    }
                ],
            }
        ],
        "clang": [
            {
                "versions": ["21"],
                "tests": [
                    {
                        "cxxversions": ["c++26"],
                        "tests": [
                            {
                                "stdlibs": ["libc++", "libstdc++"],
                                "tests": ["Release.Default"],
                            }
                        ],
                    }
                ],
            }
        ],
    }

    jobs = list(expand_matrix(matrix))

    # Should have: gcc 15, gcc 14, clang 21 with libc++, clang 21 with libstdc++
    assert len(jobs) == 4

    gcc_jobs = [j for j in jobs if j.compiler == "gcc"]
    clang_jobs = [j for j in jobs if j.compiler == "clang"]

    assert len(gcc_jobs) == 2
    assert len(clang_jobs) == 2

    gcc_versions = {j.version for j in gcc_jobs}
    assert gcc_versions == {"15", "14"}

    clang_stdlibs = {j.stdlib for j in clang_jobs}
    assert clang_stdlibs == {"libc++", "libstdc++"}


def test_extract_matrix_config():
    """Test extracting matrix_config from CI YAML."""
    ci_yaml = {
        "jobs": {
            "build-and-test": {
                "uses": "bemanproject/infra-workflows/.github/workflows/reusable-beman-build-and-test.yml@1.3.0",
                "with": {
                    "matrix_config": json.dumps(
                        {
                            "gcc": [
                                {
                                    "versions": ["15"],
                                    "tests": [
                                        {
                                            "cxxversions": ["c++26"],
                                            "tests": [
                                                {
                                                    "stdlibs": ["libstdc++"],
                                                    "tests": ["Debug.Default"],
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ]
                        }
                    )
                },
            }
        }
    }

    matrix_config = extract_matrix_config(ci_yaml)
    assert "gcc" in matrix_config
    assert matrix_config["gcc"][0]["versions"] == ["15"]


def test_extract_matrix_config_missing():
    """Test error when matrix_config is missing."""
    ci_yaml = {"jobs": {"build-and-test": {"with": {}}}}

    with pytest.raises(ValueError, match="No matrix_config found"):
        extract_matrix_config(ci_yaml)


def test_get_jobs_from_repo_exemplar():
    """Integration test: read exemplar CI config."""
    repo_path = Path("/workspace/beman-submodules/exemplar")
    if not repo_path.exists():
        pytest.skip("Exemplar repo not available")

    jobs = get_jobs_from_repo(repo_path)

    # Exemplar should have many jobs
    assert len(jobs) > 0

    # Check that we have gcc and clang jobs
    compilers = {j.compiler for j in jobs}
    assert "gcc" in compilers
    assert "clang" in compilers

    # Should not have appleclang or msvc
    assert "appleclang" not in compilers
    assert "msvc" not in compilers


def test_get_jobs_from_repo_utf_view():
    """Integration test: read utf_view CI config."""
    repo_path = Path("/workspace/beman-submodules/utf_view")
    if not repo_path.exists():
        pytest.skip("UTF View repo not available")

    jobs = get_jobs_from_repo(repo_path)

    # Should have the custom test string
    custom_tests = [j for j in jobs if "BEMAN_UTF_VIEW_BUILD_PAPER" in j.test]
    assert len(custom_tests) > 0
    assert custom_tests[0].test == "Debug.-DBEMAN_UTF_VIEW_BUILD_PAPER=ON"
