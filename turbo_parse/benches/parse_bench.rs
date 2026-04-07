//! Criterion benchmarks for turbo_parse
//!
//! Benchmarks parsing performance for various file sizes:
//! - 1k LOC: Target < 5ms
//! - 10k LOC: Target < 30ms
//! - 100k LOC: Target < 250ms

use criterion::{black_box, criterion_group, criterion_main, BenchmarkId, Criterion, SamplingMode};
use std::fs;
use std::path::PathBuf;
use std::time::Duration;

// Use the internal parser directly
use turbo_parse::parser::parse_source;

/// Load fixture file content
fn load_fixture(lang: &str, size: &str) -> String {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let fixture_path = manifest_dir
        .join("benches")
        .join("fixtures")
        .join(lang)
        .join(format!("sample_{}.{}" , size, match lang {
            "python" => "py",
            "rust" => "rs",
            "javascript" => "js",
            _ => panic!("Unknown language: {}", lang),
        }));
    
    fs::read_to_string(&fixture_path)
        .unwrap_or_else(|e| panic!(
            "Failed to load fixture {:?}: {}",
            fixture_path, e
        ))
}

/// Benchmark group for Python parsing
fn bench_python(c: &mut Criterion) {
    let mut group = c.benchmark_group("python_parse");
    group.measurement_time(Duration::from_secs(5));
    group.sample_size(100);
    
    // Load fixtures once
    let source_1k = load_fixture("python", "1k");
    let source_10k = load_fixture("python", "10k");
    let source_100k = load_fixture("python", "100k");
    
    // 1k LOC benchmark - target < 5ms
    group.bench_with_input(
        BenchmarkId::new("1k_loc", "cold_parse"),
        &source_1k,
        |b, source| {
            b.iter(|| {
                let result = parse_source(black_box(source), black_box("python"));
                black_box(result)
            });
        },
    );
    
    // 10k LOC benchmark - target < 30ms
    group.bench_with_input(
        BenchmarkId::new("10k_loc", "cold_parse"),
        &source_10k,
        |b, source| {
            b.iter(|| {
                let result = parse_source(black_box(source), black_box("python"));
                black_box(result)
            });
        },
    );
    
    // 100k LOC benchmark - target < 250ms
    // Use flat sampling mode for longer-running benchmarks
    group.sampling_mode(SamplingMode::Flat);
    group.measurement_time(Duration::from_secs(10));
    group.sample_size(30);
    
    group.bench_with_input(
        BenchmarkId::new("100k_loc", "cold_parse"),
        &source_100k,
        |b, source| {
            b.iter(|| {
                let result = parse_source(black_box(source), black_box("python"));
                black_box(result)
            });
        },
    );
    
    group.finish();
}

/// Benchmark group for Rust parsing
fn bench_rust(c: &mut Criterion) {
    let mut group = c.benchmark_group("rust_parse");
    group.measurement_time(Duration::from_secs(5));
    group.sample_size(100);
    
    // Load fixtures once
    let source_1k = load_fixture("rust", "1k");
    let source_10k = load_fixture("rust", "10k");
    let source_100k = load_fixture("rust", "100k");
    
    // 1k LOC benchmark - target < 5ms
    group.bench_with_input(
        BenchmarkId::new("1k_loc", "cold_parse"),
        &source_1k,
        |b, source| {
            b.iter(|| {
                let result = parse_source(black_box(source), black_box("rust"));
                black_box(result)
            });
        },
    );
    
    // 10k LOC benchmark - target < 30ms
    group.bench_with_input(
        BenchmarkId::new("10k_loc", "cold_parse"),
        &source_10k,
        |b, source| {
            b.iter(|| {
                let result = parse_source(black_box(source), black_box("rust"));
                black_box(result)
            });
        },
    );
    
    // 100k LOC benchmark - target < 250ms
    group.sampling_mode(SamplingMode::Flat);
    group.measurement_time(Duration::from_secs(10));
    group.sample_size(30);
    
    group.bench_with_input(
        BenchmarkId::new("100k_loc", "cold_parse"),
        &source_100k,
        |b, source| {
            b.iter(|| {
                let result = parse_source(black_box(source), black_box("rust"));
                black_box(result)
            });
        },
    );
    
    group.finish();
}

/// Benchmark group for JavaScript parsing
fn bench_javascript(c: &mut Criterion) {
    let mut group = c.benchmark_group("javascript_parse");
    group.measurement_time(Duration::from_secs(5));
    group.sample_size(100);
    
    // Load fixtures once
    let source_1k = load_fixture("javascript", "1k");
    let source_10k = load_fixture("javascript", "10k");
    let source_100k = load_fixture("javascript", "100k");
    
    // 1k LOC benchmark - target < 5ms
    group.bench_with_input(
        BenchmarkId::new("1k_loc", "cold_parse"),
        &source_1k,
        |b, source| {
            b.iter(|| {
                let result = parse_source(black_box(source), black_box("javascript"));
                black_box(result)
            });
        },
    );
    
    // 10k LOC benchmark - target < 30ms
    group.bench_with_input(
        BenchmarkId::new("10k_loc", "cold_parse"),
        &source_10k,
        |b, source| {
            b.iter(|| {
                let result = parse_source(black_box(source), black_box("javascript"));
                black_box(result)
            });
        },
    );
    
    // 100k LOC benchmark - target < 250ms
    group.sampling_mode(SamplingMode::Flat);
    group.measurement_time(Duration::from_secs(10));
    group.sample_size(30);
    
    group.bench_with_input(
        BenchmarkId::new("100k_loc", "cold_parse"),
        &source_100k,
        |b, source| {
            b.iter(|| {
                let result = parse_source(black_box(source), black_box("javascript"));
                black_box(result)
            });
        },
    );
    
    group.finish();
}

/// Comparison benchmark across all languages at 10k LOC
fn bench_comparison(c: &mut Criterion) {
    let mut group = c.benchmark_group("language_comparison_10k");
    group.measurement_time(Duration::from_secs(5));
    group.sample_size(100);
    
    let py_10k = load_fixture("python", "10k");
    let rs_10k = load_fixture("rust", "10k");
    let js_10k = load_fixture("javascript", "10k");
    
    group.bench_with_input(
        BenchmarkId::new("language", "python"),
        &py_10k,
        |b, source| {
            b.iter(|| {
                black_box(parse_source(black_box(source), black_box("python")))
            });
        },
    );
    
    group.bench_with_input(
        BenchmarkId::new("language", "rust"),
        &rs_10k,
        |b, source| {
            b.iter(|| {
                black_box(parse_source(black_box(source), black_box("rust")))
            });
        },
    );
    
    group.bench_with_input(
        BenchmarkId::new("language", "javascript"),
        &js_10k,
        |b, source| {
            b.iter(|| {
                black_box(parse_source(black_box(source), black_box("javascript")))
            });
        },
    );
    
    group.finish();
}

criterion_group!(benches, bench_python, bench_rust, bench_javascript, bench_comparison);
criterion_main!(benches);
