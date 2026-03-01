# beman-local-ci

Run Beman CI matrix locally via Docker.

## Installation

```bash
uv pip install -e .
```

## Usage

```bash
# Run all jobs for a repository
beman-local-ci -C /path/to/repo

# Run with filters
beman-local-ci -C /path/to/repo --compiler gcc --versions 15

# Dry run to see what would be executed
beman-local-ci -C /path/to/repo --dry-run

# Control parallelism
beman-local-ci -C /path/to/repo -j 8 -p 4
```

## Options

- `-C DIR`: Repository directory (default: current directory)
- `-j N`: Build parallelism (default: CPU count / 2)
- `-p N`: Max parallel CI jobs (default: auto based on Docker memory, use `all` for unlimited)
- `--dry-run`: Print commands without executing
- `--verbose`: Show detailed output
- `--compiler COMPILER`: Filter by compiler (gcc, clang)
- `--versions V1,V2`: Filter by versions
- `--cxxversions V1,V2`: Filter by C++ versions
- `--stdlibs S1,S2`: Filter by standard libraries
- `--tests T1,T2`: Filter by test types
