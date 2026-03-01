# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Tests for CLI."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from beman_local_ci.cli import create_parser, main


def test_create_parser():
    """Test parser creation."""
    parser = create_parser()
    assert parser is not None


def test_parser_defaults():
    """Test default argument values."""
    parser = create_parser()
    args, _ = parser.parse_known_args([])

    assert args.directory == Path.cwd()
    assert args.jobs == os.cpu_count()
    assert args.parallel == 2
    assert args.dry_run is False
    assert args.verbose is False


def test_parser_directory():
    """Test -C/--directory argument."""
    parser = create_parser()

    args, _ = parser.parse_known_args(["-C", "/some/path"])
    assert args.directory == Path("/some/path")

    args, _ = parser.parse_known_args(["--directory", "/other/path"])
    assert args.directory == Path("/other/path")


def test_parser_jobs():
    """Test -j/--jobs argument."""
    parser = create_parser()

    args, _ = parser.parse_known_args(["-j", "16"])
    assert args.jobs == 16

    args, _ = parser.parse_known_args(["--jobs", "8"])
    assert args.jobs == 8


def test_parser_parallel():
    """Test -p/--parallel argument."""
    parser = create_parser()

    args, _ = parser.parse_known_args(["-p", "4"])
    assert args.parallel == 4

    args, _ = parser.parse_known_args(["--parallel", "2"])
    assert args.parallel == 2

    args, _ = parser.parse_known_args(["-p", "all"])
    assert args.parallel is None

    args, _ = parser.parse_known_args(["--parallel", "all"])
    assert args.parallel is None


def test_parser_dry_run():
    """Test --dry-run flag."""
    parser = create_parser()

    args, _ = parser.parse_known_args(["--dry-run"])
    assert args.dry_run is True


def test_parser_verbose():
    """Test -v/--verbose flag."""
    parser = create_parser()

    args, _ = parser.parse_known_args(["-v"])
    assert args.verbose is True

    args, _ = parser.parse_known_args(["--verbose"])
    assert args.verbose is True


def test_parser_separates_filter_tokens():
    """Test that parser separates filter tokens from global options."""
    parser = create_parser()

    args, filter_tokens = parser.parse_known_args(
        ["-C", "/path", "--compiler", "gcc", "--versions", "15"]
    )

    assert args.directory == Path("/path")
    assert filter_tokens == ["--compiler", "gcc", "--versions", "15"]


def test_parser_filter_tokens_only():
    """Test parsing with only filter tokens."""
    parser = create_parser()

    args, filter_tokens = parser.parse_known_args(
        ["--compiler", "gcc", "--compiler", "clang"]
    )

    assert filter_tokens == ["--compiler", "gcc", "--compiler", "clang"]


@patch("beman_local_ci.cli.check_docker")
@patch("beman_local_ci.cli.get_jobs_from_repo")
@patch("beman_local_ci.cli.run_jobs")
def test_main_success(mock_run_jobs, mock_get_jobs, mock_check_docker):
    """Test main() with successful execution."""
    from beman_local_ci.lib.matrix import CIJob

    mock_check_docker.return_value = None
    mock_get_jobs.return_value = [
        CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default")
    ]
    mock_run_jobs.return_value = 0

    with patch(
        "sys.argv",
        ["beman-local-ci", "-C", "/workspace/beman-submodules/exemplar", "--dry-run"],
    ):
        # Skip if exemplar doesn't exist
        if not Path("/workspace/beman-submodules/exemplar").exists():
            pytest.skip("Exemplar repo not available")

        exit_code = main()

    assert exit_code == 0
    mock_get_jobs.assert_called_once()
    mock_run_jobs.assert_called_once()


@patch("beman_local_ci.cli.check_docker")
def test_main_docker_not_available(mock_check_docker, capsys):
    """Test main() when Docker is not available."""
    mock_check_docker.side_effect = RuntimeError("Docker not found")

    with patch(
        "sys.argv", ["beman-local-ci", "-C", "/workspace/beman-submodules/exemplar"]
    ):
        if not Path("/workspace/beman-submodules/exemplar").exists():
            pytest.skip("Exemplar repo not available")

        exit_code = main()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Docker not found" in captured.err


def test_main_repo_not_found(capsys):
    """Test main() with non-existent repository."""
    with patch("sys.argv", ["beman-local-ci", "-C", "/nonexistent/path"]):
        exit_code = main()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "does not exist" in captured.err


def test_main_ci_yaml_not_found(tmp_path, capsys):
    """Test main() with repository missing CI YAML."""
    with patch("sys.argv", ["beman-local-ci", "-C", str(tmp_path)]):
        exit_code = main()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "CI YAML not found" in captured.err


@patch("beman_local_ci.cli.check_docker")
@patch("beman_local_ci.cli.get_jobs_from_repo")
def test_main_invalid_filter(mock_get_jobs, mock_check_docker, capsys):
    """Test main() with invalid filter syntax."""
    mock_check_docker.return_value = None

    with patch(
        "sys.argv",
        [
            "beman-local-ci",
            "-C",
            "/workspace/beman-submodules/exemplar",
            "--versions",
            "15",
        ],
    ):
        if not Path("/workspace/beman-submodules/exemplar").exists():
            pytest.skip("Exemplar repo not available")

        exit_code = main()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Error parsing filters" in captured.err


@patch("beman_local_ci.cli.check_docker")
@patch("beman_local_ci.cli.get_jobs_from_repo")
@patch("beman_local_ci.cli.run_jobs")
def test_main_with_filters(mock_run_jobs, mock_get_jobs, mock_check_docker):
    """Test main() with filter arguments."""
    from beman_local_ci.lib.matrix import CIJob

    mock_check_docker.return_value = None
    mock_get_jobs.return_value = [
        CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default"),
        CIJob("gcc", "14", "c++26", "libstdc++", "Debug.Default"),
        CIJob("clang", "21", "c++26", "libc++", "Debug.Default"),
    ]
    mock_run_jobs.return_value = 0

    with patch(
        "sys.argv",
        [
            "beman-local-ci",
            "-C",
            "/workspace/beman-submodules/exemplar",
            "--dry-run",
            "--compiler",
            "gcc",
            "--versions",
            "15",
        ],
    ):
        if not Path("/workspace/beman-submodules/exemplar").exists():
            pytest.skip("Exemplar repo not available")

        exit_code = main()

    assert exit_code == 0

    # Check that run_jobs was called with filtered jobs
    call_args = mock_run_jobs.call_args
    jobs = call_args.kwargs["jobs"]

    # Should only have gcc 15 jobs
    assert len(jobs) == 1
    assert jobs[0].compiler == "gcc"
    assert jobs[0].version == "15"


@patch("beman_local_ci.cli.check_docker")
@patch("beman_local_ci.cli.get_jobs_from_repo")
def test_main_no_matching_jobs(mock_get_jobs, mock_check_docker, capsys):
    """Test main() when filters match no jobs."""
    from beman_local_ci.lib.matrix import CIJob

    mock_check_docker.return_value = None
    mock_get_jobs.return_value = [
        CIJob("gcc", "15", "c++26", "libstdc++", "Debug.Default")
    ]

    with patch(
        "sys.argv",
        [
            "beman-local-ci",
            "-C",
            "/workspace/beman-submodules/exemplar",
            "--dry-run",
            "--compiler",
            "clang",
        ],
    ):
        if not Path("/workspace/beman-submodules/exemplar").exists():
            pytest.skip("Exemplar repo not available")

        exit_code = main()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "No jobs match" in captured.out
