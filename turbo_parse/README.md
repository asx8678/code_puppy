# turbo_parse

[![CI](https://github.com/mpfaffenberger/code_puppy/actions/workflows/turbo_parse.yml/badge.svg)](https://github.com/mpfaffenberger/code_puppy/actions/workflows/turbo_parse.yml)
[![Crates.io](https://img.shields.io/badge/Rust-turbo_parse-orange?logo=rust)](https://github.com/mpfaffenberger/code_puppy/tree/main/turbo_parse)
[![Python Versions](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue?logo=python)](https://pypi.org/project/turbo-parse/)
[![Platforms](https://img.shields.io/badge/platforms-linux%20|%20macos%20|%20windows-lightgrey)](./CI.md)

High-performance parsing with tree-sitter and PyO3 bindings for Code Puppy.

## Building

```bash
maturin develop --release  # For development
maturin build --release    # For distribution
```

## Usage

```python
import turbo_parse

# Check module health
result = turbo_parse.health_check()
print(result)  # {'available': True, 'version': '0.1.0'}
```

## Supported Languages

- Python
- Rust
- JavaScript
- TypeScript / TSX
- Elixir
