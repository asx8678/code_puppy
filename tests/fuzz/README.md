# Fuzz Testing for Symbol Extraction

This directory contains hypothesis-based fuzz tests for the symbol extraction functionality.

## Running the Tests

### Run all fuzz tests:
```bash
# Run with default (CI) profile - 50 examples per test
pytest tests/fuzz/ -v

# Run with local profile - 200 examples per test
pytest tests/fuzz/ -v --hypothesis-profile=local

# Run with max examples for thorough testing
pytest tests/fuzz/ -v --hypothesis-profile=thorough
```

### Run specific fuzz tests:
```bash
# Python fuzz tests only
pytest tests/fuzz/test_symbol_extraction.py::test_python_symbol_extraction_never_crashes -v

# Rust fuzz tests only
pytest tests/fuzz/test_symbol_extraction.py::test_rust_symbol_extraction_never_crashes -v

# JavaScript fuzz tests only
pytest tests/fuzz/test_symbol_extraction.py::test_javascript_symbol_extraction_never_crashes -v
```

### Skip slow tests:
```bash
# Skip slow tests (edge cases, thorough fuzzing)
pytest tests/fuzz/ -v -m "not slow"
```

## Test Profiles

### CI Profile (`ci`)
- Used in continuous integration
- 50 examples per test
- Faster execution
- Good baseline coverage

### Local Profile (`local`)
- Default for local development
- 100 examples per test
- Balanced speed vs coverage

### Thorough Profile (`thorough`)
- Deep testing mode
- 500 examples per test
- Use when investigating specific issues

## What Gets Tested

### Properties Verified
1. **No crashes**: extract_symbols never crashes on valid code
2. **Success status**: Returns success=True for valid code
3. **Non-negative symbol count**: Number of symbols is always >= 0
4. **Valid symbol names**: All symbol names are non-empty, valid UTF-8 strings
5. **Required fields present**: Each symbol has name, kind, and location

### Edge Cases Covered
- Empty files
- Files with only comments
- Files with unicode characters
- Very long symbol names (up to 1000 chars)
- Deeply nested structures
- Files with many symbols (up to 1000)

### Languages Tested
- Python
- Rust
- JavaScript
- TypeScript (implied via JS tests)
- Elixir

## Found Issues

Document any bugs or edge cases discovered by fuzzing here:

| Date | Issue | Severity | Status |
|------|-------|----------|--------|
| - | - | - | - |

## Adding New Fuzz Tests

When adding new property-based tests:

1. Use appropriate strategies from this module
2. Set `max_examples` based on test speed
3. Mark long-running tests with `@pytest.mark.slow`
4. Document any invariants being tested
5. Update this README with new findings

## Configuration

Hypothesis settings can be configured via environment variables:

```bash
# Set seed for reproducible runs
HYPOTHESIS_SEED=12345 pytest tests/fuzz/

# Disable shrinking for faster CI
HYPOTHESIS_NO_SHRINK=1 pytest tests/fuzz/

# Enable verbose hypothesis output
HYPOTHESIS_VERBOSITY=verbose pytest tests/fuzz/
```
