# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Shared pytest fixtures."""

import pytest


@pytest.fixture
def sample_matrix_simple():
    """Simple matrix config for testing."""
    return {
        "gcc": [
            {
                "versions": ["15"],
                "tests": [
                    {
                        "cxxversions": ["c++26"],
                        "tests": [
                            {
                                "stdlibs": ["libstdc++"],
                                "tests": ["Debug.Default", "Release.Default"],
                            }
                        ],
                    }
                ],
            }
        ]
    }


@pytest.fixture
def sample_matrix_utf_view():
    """UTF View matrix config with custom test string."""
    return {
        "gcc": [
            {
                "versions": ["trunk"],
                "tests": [
                    {
                        "cxxversions": ["c++26"],
                        "tests": [
                            {
                                "stdlibs": ["libstdc++"],
                                "tests": [
                                    "Debug.Default",
                                    "Debug.-DBEMAN_UTF_VIEW_BUILD_PAPER=ON",
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
