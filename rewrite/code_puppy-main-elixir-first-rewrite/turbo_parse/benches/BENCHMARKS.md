# Turbo Parse Benchmarks

This directory contains Criterion benchmarks for measuring parsing performance across different file sizes and languages.

## Quick Start

```bash
# Run all benchmarks
cargo bench

# Run specific benchmark group
cargo bench python_parse
cargo bench rust_parse
cargo bench javascript_parse

# Generate HTML report (saved to target/criterion/)
cargo bench -- --report=html
```

## Performance Goals

Our target performance for cold parsing on an Apple M1 MacBook Pro:

| File Size | Python | Rust | JavaScript |
|-----------|--------|------|------------|
| 1k LOC    | < 5ms  | < 5ms | < 5ms |
| 10k LOC   | < 30ms | < 30ms | < 30ms |
| 100k LOC  | < 250ms| < 250ms| < 250ms |

> **Note:** These are cold parse times without caching. Subsequent parses of the same file (with caching enabled) will be significantly faster.

## Benchmark Structure

### Test Fixtures

Generated test files of various sizes:

```
fixtures/
├── python/
│   ├── sample_1k.py      # ~1,000 lines
│   ├── sample_10k.py     # ~10,000 lines
│   └── sample_100k.py    # ~100,000 lines
├── rust/
│   ├── sample_1k.rs
│   ├── sample_10k.rs
│   └── sample_100k.rs
└── javascript/
    ├── sample_1k.js
    ├── sample_10k.js
    └── sample_100k.js
```

Fixture files contain realistic code including:
- Functions and methods
- Classes and structs
- Imports and use statements
- Type annotations and generics
- Comments and documentation

### Benchmark Groups

1. **python_parse** - Python file parsing benchmarks
2. **rust_parse** - Rust file parsing benchmarks  
3. **javascript_parse** - JavaScript file parsing benchmarks
4. **language_comparison_10k** - Cross-language comparison at 10k LOC

## Regression Detection

### Automated Checks

Run the regression detection script to compare against baseline:

```bash
# Check for regressions (uses baseline.json)
cd turbo_parse/benches
python3 check_regression.py

# Set custom threshold (default: 15%)
python3 check_regression.py --threshold 10

# Save current results as new baseline
python3 check_regression.py --save-baseline

# Save results to custom file
python3 check_regression.py --output results.json

# Create baseline template
python3 check_regression.py --create-baseline
```

### CI Integration

Add to your CI pipeline:

```yaml
# .github/workflows/benchmark.yml
name: Benchmark

on: [push, pull_request]

jobs:
  benchmark:
    runs-on: macos-latest  # Use consistent hardware
    steps:
      - uses: actions/checkout@v4
      
      - name: Install Rust
        uses: dtolnay/rust-action@stable
      
      - name: Run benchmarks
        run: cargo bench
      
      - name: Check for regressions
        run: |
          cd turbo_parse/benches
          python3 check_regression.py --threshold 15
```

### Updating Baseline

When intentional performance changes are made:

1. Run benchmarks: `cargo bench`
2. Save new baseline: `python3 check_regression.py --save-baseline`
3. Commit updated `baseline.json`

## Understanding Results

### Console Output

```
python_parse/1k_loc/cold_parse
    time:   [3.4567 ms 3.5123 ms 3.5789 ms]
    change: [-2.3% -1.2% -0.1%] (p = 0.02 < 0.05)
    Performance has improved.
```

### HTML Reports

After running benchmarks, open `target/criterion/report/index.html` for:
- Interactive graphs
- Performance history
- Statistical analysis

## Reproducibility

For consistent benchmark results:

1. **Close other applications** - Background processes affect timing
2. **Use same hardware** - M1 vs Intel times will differ significantly
3. **Run multiple times** - Use median of 3+ runs
4. **Check thermals** - Thermal throttling can slow results
5. **Disable power save** - Use AC power on laptops

## Fixture Regeneration

If you need to regenerate test fixtures:

```bash
cd turbo_parse/benches/fixtures
python3 generate_all.py
```

This will recreate all sample files with new random variations.

## Troubleshooting

### Benchmarks fail to compile

```bash
# Ensure you have the rlib crate type
grep crate-type Cargo.toml  # Should show ["cdylib", "rlib"]

# Clean and rebuild
cargo clean
cargo bench --no-run
```

### Fixtures not found

```bash
# Regenerate fixtures
cd benches/fixtures
python3 generate_all.py
```

### Slow benchmark times

- Ensure you're running in release mode (criterion does this automatically)
- Check that no debug assertions are enabled
- Verify LTO is enabled in Cargo.toml

## Advanced Usage

### Custom Benchmark Filters

```bash
# Only run Python benchmarks
cargo bench python

# Exclude 100k benchmarks (faster feedback)
cargo bench -- --skip 100k

# Run specific test
cargo bench 'python_parse/10k'
```

### Profiling Integration

```bash
# Build with debug symbols
cargo bench --no-run

# Profile with samply (macOS)
samply record target/release/deps/parse_bench-*

# Profile with perf (Linux)
perf record -g target/release/deps/parse_bench-*
perf report
```

## Contributing

When adding new benchmarks:

1. Add fixture generators to `fixtures/generate_*.py`
2. Add benchmark functions to `parse_bench.rs`
3. Update this documentation
4. Update `baseline.json` with target goals
5. Run full benchmark suite before submitting PR

## See Also

- [Criterion Documentation](https://bheisler.github.io/criterion.rs/book/)
- [turbo_parse README](../README.md)
- [Performance Tuning Guide](../speed_rust.md)
