# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Matrix expansion logic for Beman CI configurations."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import yaml


@dataclass(frozen=True)
class CIJob:
    """A single CI job configuration."""

    compiler: str
    version: str
    cxxversion: str
    stdlib: str
    test: str

    def __str__(self) -> str:
        """Human-readable job description."""
        return f"{self.compiler} {self.version} {self.cxxversion} {self.stdlib} {self.test}"


def read_ci_yaml(repo_path: Path) -> dict:
    """Read and parse the ci_tests.yml file."""
    ci_yaml_path = repo_path / ".github" / "workflows" / "ci_tests.yml"
    if not ci_yaml_path.exists():
        raise FileNotFoundError(f"CI YAML not found: {ci_yaml_path}")

    with open(ci_yaml_path, "r") as f:
        return yaml.safe_load(f)


def extract_matrix_config(ci_yaml: dict) -> dict:
    """Extract the matrix_config JSON from the build-and-test job."""
    jobs = ci_yaml.get("jobs", {})
    build_and_test = jobs.get("build-and-test", {})
    with_params = build_and_test.get("with", {})
    matrix_config_str = with_params.get("matrix_config", "")

    if not matrix_config_str:
        raise ValueError("No matrix_config found in build-and-test job")

    # The matrix_config is a multi-line string containing JSON
    # Strip whitespace and parse as JSON
    matrix_config_str = matrix_config_str.strip()
    return json.loads(matrix_config_str)


def expand_matrix(matrix_config: dict) -> Iterator[CIJob]:
    """
    Expand the hierarchical matrix config into individual jobs.

    Replicates the expansion logic from the reusable workflow's
    configure_test_matrix job (lines 30-50).
    """
    for compiler, compiler_tests in matrix_config.items():
        # Skip unsupported compilers
        if compiler in ("appleclang", "msvc"):
            continue

        for compiler_test in compiler_tests:
            for version in compiler_test["versions"]:
                for versions_test in compiler_test["tests"]:
                    for cxxversion in versions_test["cxxversions"]:
                        for cxxversion_test in versions_test["tests"]:
                            for stdlib in cxxversion_test["stdlibs"]:
                                for stdlib_test in cxxversion_test["tests"]:
                                    yield CIJob(
                                        compiler=compiler,
                                        version=version,
                                        cxxversion=cxxversion,
                                        stdlib=stdlib,
                                        test=stdlib_test,
                                    )


def get_jobs_from_repo(repo_path: Path) -> list[CIJob]:
    """Read CI config from a repository and return all expanded jobs."""
    ci_yaml = read_ci_yaml(repo_path)
    matrix_config = extract_matrix_config(ci_yaml)
    return list(expand_matrix(matrix_config))
