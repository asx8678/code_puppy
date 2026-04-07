# turbo_parse

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
