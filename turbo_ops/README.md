# Turbo Ops

High-performance batch file operations with PyO3 bindings for Code Puppy.

## Overview

Turbo Ops provides Rust-native implementations of common file operations:
- `list_files`: Directory traversal with metadata
- `grep`: Pattern matching across files
- `read_files`: File content reading with token estimation

The crate supports batch execution with parallel processing using rayon.

## Installation

Build and install with maturin:

```bash
cd turbo_ops
maturin develop --release  # For development
maturin build --release  # For distribution
```

## Python API

### Batch Execution

```python
import turbo_ops
import json

# Define operations
operations = [
    {
        "type": "list_files",
        "args": {"directory": ".", "recursive": True},
        "id": "list-src",
        "priority": 1
    },
    {
        "type": "grep",
        "args": {"search_string": "def ", "directory": "src"},
        "id": "find-functions",
        "priority": 2
    },
    {
        "type": "read_files",
        "args": {
            "file_paths": ["src/lib.rs", "Cargo.toml"],
            "start_line": 1,
            "num_lines": 50
        },
        "id": "read-config",
        "priority": 3
    }
]

# Execute in parallel (default)
result = turbo_ops.batch(operations)
print(json.dumps(result, indent=2))

# Or execute sequentially
result = turbo_ops.batch(operations, parallel=False)

# Or use priority-based grouping (parallel within priorities, sequential between)
result = turbo_ops.batch_grouped(operations)
```

### Single Operations

```python
# List files
files = turbo_ops.list_files(".", recursive=True)

# Search
matches = turbo_ops.grep("class.*:", directory="src")

# Read files
content = turbo_ops.read_files(
    ["file1.py", "file2.py"],
    start_line=1,
    num_lines=100
)
```

## Operation Types

### list_files

Args:
- `directory`: Path to list (default: ".")
- `recursive`: Whether to recurse into subdirectories (default: true)

Returns:
- `files`: List of file info dicts with `path`, `name`, `is_dir`, `size`, `modified`
- `total_count`: Number of files
- `directory`, `recursive`: The input parameters

### grep

Args:
- `search_string`: Pattern to search for (supports `(?i)` prefix for case-insensitive)
- `directory`: Directory to search (default: ".")

Returns:
- `matches`: List of matches with `file_path`, `line_number`, `line_content`
- `total_matches`: Number of matches found
- `search_string`, `directory`: The input parameters

### read_files

Args:
- `file_paths`: List of file paths to read
- `start_line`: Optional starting line (1-indexed)
- `num_lines`: Optional number of lines to read

Returns:
- `files`: List of file results with `file_path`, `content`, `num_tokens`, `error`, `success`
- `total_files`: Number of files attempted
- `successful_reads`: Number of successfully read files

## Batch Result Format

```json
{
  "status": "completed|partial|failed",
  "success_count": 2,
  "error_count": 0,
  "total_count": 2,
  "results": [
    {
      "operation_id": "list-src",
      "operation_type": "list_files",
      "status": "success",
      "data": {...},
      "error": null,
      "duration_ms": 12.5
    }
  ],
  "total_duration_ms": 45.2,
  "started_at": "2024-01-15T10:30:00Z",
  "completed_at": "2024-01-15T10:30:00.045Z"
}
```

## Performance

Turbo Ops uses Rayon for parallel execution, automatically distributing work
across available CPU cores. Single operations can also be used for direct
file access without the overhead of batch coordination.

## Testing

Run Rust unit tests:

```bash
cargo test
```

Run Python integration tests (after maturin develop):

```bash
python -c "import turbo_ops; print(turbo_ops.health_check())"
```
