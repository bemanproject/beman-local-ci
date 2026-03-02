# beman-local-ci

Run Beman CI matrix locally via Docker.

## Installation

```bash
uv pip install -e .
```

## Usage

```bash
# Run all jobs for a repository
uv run beman-local-ci -C /path/to/repo

# Dry run to see what would be executed
uv run beman-local-ci -C /path/to/repo --dry-run

# Control parallelism
uv run beman-local-ci -C /path/to/repo -j 8 -p 4
```

## Options

- `-C DIR`: Repository directory (default: current directory)
- `-j N`: Build parallelism (default: CPU count when `-p 1`, CPU count / 2 otherwise)
- `-p N`: Max parallel CI jobs (default: auto based on Docker memory, use `all` for unlimited)
- `--dry-run`: Print commands without executing
- `--verbose`: Show detailed output
- `--track-performance`: Report peak CPU and memory usage for each job

## Filter syntax

All dimensions are independent — omitted ones match all values.

- `--compiler C1,C2`: Filter by compiler (gcc, clang). Starts a new filter group.
- `--versions V1,V2`: Filter by compiler versions
- `--cxxversions V1,V2`: Filter by C++ standard versions
- `--stdlibs S1,S2`: Filter by standard libraries
- `--tests T1,T2`: Filter by test types

Multiple `--compiler` flags create OR groups. Within a group, dimensions are ANDed.
Flags before the first `--compiler` create an implicit group (all compilers).

### Examples

```bash
# Run only gcc jobs
beman-local-ci -C /path/to/repo --compiler gcc

# Run only c++26 jobs (any compiler)
beman-local-ci -C /path/to/repo --cxxversions c++26

# Run gcc 15 c++26 jobs
beman-local-ci -C /path/to/repo --compiler gcc --versions 15 --cxxversions c++26

# Run gcc 15 OR clang 21 libc++ jobs
beman-local-ci --compiler gcc --versions 15 --compiler clang --versions 21 --stdlibs libc++
```
