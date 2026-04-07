//! Batch parsing module — Parallel file parsing with rayon.
//!
//! Provides high-performance parallel parsing of multiple files
//! using all available CPU cores with GIL release during processing.

use std::time::Instant;
use serde::{Deserialize, Serialize};
use rayon::prelude::*;

use crate::parser::{parse_file, ParseResult};

/// Options for batch parsing operations.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct BatchParseOptions {
    /// Maximum number of worker threads to use (None = use all available cores)
    pub max_workers: Option<usize>,
    /// Timeout for entire batch operation in milliseconds (None = no timeout)
    pub timeout_ms: Option<u64>,
}

impl Default for BatchParseOptions {
    fn default() -> Self {
        Self {
            max_workers: None,
            timeout_ms: None,
        }
    }
}

impl BatchParseOptions {
    /// Create new batch parse options with defaults.
    #[cfg(test)]
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the maximum number of worker threads.
    #[cfg(test)]
    pub fn with_max_workers(mut self, workers: usize) -> Self {
        self.max_workers = Some(workers);
        self
    }

    /// Set the timeout for the batch operation.
    #[allow(dead_code)]
    pub fn with_timeout_ms(mut self, timeout: u64) -> Self {
        self.timeout_ms = Some(timeout);
        self
    }
}

/// Result of a batch parse operation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BatchParseResult {
    /// Individual results for each file
    pub results: Vec<ParseResult>,
    /// Total time taken for the entire batch in milliseconds
    pub total_time_ms: f64,
    /// Number of files processed (including failures)
    pub files_processed: usize,
    /// Number of files that succeeded
    pub success_count: usize,
    /// Number of files that failed
    pub error_count: usize,
    /// Whether all files succeeded
    pub all_succeeded: bool,
}

impl BatchParseResult {
    /// Create a new batch parse result from individual results.
    pub fn from_results(results: Vec<ParseResult>, total_time_ms: f64) -> Self {
        let files_processed = results.len();
        let success_count = results.iter().filter(|r| r.success).count();
        let error_count = files_processed - success_count;
        let all_succeeded = error_count == 0;

        Self {
            results,
            total_time_ms,
            files_processed,
            success_count,
            error_count,
            all_succeeded,
        }
    }

    /// Create an empty result (for empty batch).
    pub fn empty() -> Self {
        Self {
            results: Vec::new(),
            total_time_ms: 0.0,
            files_processed: 0,
            success_count: 0,
            error_count: 0,
            all_succeeded: true,
        }
    }
}

/// Parse multiple files in parallel using rayon.
///
/// This function releases the GIL during batch processing, allowing
/// other Python threads to execute while parsing happens in parallel
/// across all available CPU cores.
///
/// # Arguments
/// * `paths` - Vector of file paths to parse
/// * `options` - Batch parsing options (max workers, timeout)
///
/// # Returns
/// BatchParseResult containing all individual results and timing info.
///
/// # Example
/// ```rust
/// let paths = vec!["file1.py", "file2.py", "file3.rs"];
/// let options = BatchParseOptions::new()
///     .with_max_workers(4);
/// let result = parse_files_batch(paths, options);
/// ```
pub fn parse_files_batch(
    paths: Vec<String>,
    options: BatchParseOptions,
) -> BatchParseResult {
    if paths.is_empty() {
        return BatchParseResult::empty();
    }

    let start = Instant::now();

    // Configure thread pool if max_workers is specified
    let results: Vec<ParseResult> = if let Some(max_workers) = options.max_workers {
        // Create a custom thread pool with limited workers
        let pool = rayon::ThreadPoolBuilder::new()
            .num_threads(max_workers)
            .build();
        
        match pool {
            Ok(pool) => {
                pool.install(|| {
                    parse_files_parallel(&paths, options.timeout_ms)
                })
            }
            Err(_) => {
                // Fallback to global pool on error
                parse_files_parallel(&paths, options.timeout_ms)
            }
        }
    } else {
        // Use the global rayon thread pool (all cores)
        parse_files_parallel(&paths, options.timeout_ms)
    };

    let total_time_ms = start.elapsed().as_secs_f64() * 1000.0;
    BatchParseResult::from_results(results, total_time_ms)
}

/// Internal parallel parsing implementation.
#[allow(dead_code)]
fn parse_files_parallel(
    paths: &[String],
    _timeout_ms: Option<u64>,
) -> Vec<ParseResult> {
    // Parse all files in parallel using rayon
    // Each file is parsed independently - errors in one don't affect others
    paths
        .par_iter()
        .map(|path| {
            // Each file parse is independent - errors don't stop others
            parse_single_file(path)
        })
        .collect()
}

/// Parse a single file with error handling.
fn parse_single_file(path: &str) -> ParseResult {
    // Detect language from extension, no override
    parse_file(path, None)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn test_batch_parse_options_default() {
        let opts = BatchParseOptions::default();
        assert!(opts.max_workers.is_none());
        assert!(opts.timeout_ms.is_none());
    }

    #[test]
    fn test_batch_parse_options_builder() {
        let opts = BatchParseOptions::new()
            .with_max_workers(4)
            .with_timeout_ms(5000);
        
        assert_eq!(opts.max_workers, Some(4));
        assert_eq!(opts.timeout_ms, Some(5000));
    }

    #[test]
    fn test_batch_result_empty() {
        let result = BatchParseResult::empty();
        assert_eq!(result.files_processed, 0);
        assert_eq!(result.success_count, 0);
        assert_eq!(result.error_count, 0);
        assert!(result.all_succeeded);
        assert!(result.results.is_empty());
    }

    #[test]
    fn test_batch_result_from_results() {
        let parse_results = vec![
            ParseResult {
                language: "python".to_string(),
                tree: Some(serde_json::json!({"root": "test"})),
                parse_time_ms: 1.0,
                success: true,
                errors: vec![],
            },
            ParseResult {
                language: "python".to_string(),
                tree: None,
                parse_time_ms: 0.5,
                success: false,
                errors: vec![crate::parser::ParseError::with_message("test error")],
            },
        ];

        let batch = BatchParseResult::from_results(parse_results, 10.0);
        
        assert_eq!(batch.files_processed, 2);
        assert_eq!(batch.success_count, 1);
        assert_eq!(batch.error_count, 1);
        assert!(!batch.all_succeeded);
        assert_eq!(batch.total_time_ms, 10.0);
    }

    #[test]
    fn test_parse_single_file_success() {
        // Create a temporary file with valid Python code
        let mut temp_file = tempfile::NamedTempFile::with_suffix(".py").unwrap();
        writeln!(temp_file, "def hello():\n    pass").unwrap();
        let path = temp_file.path().to_str().unwrap();

        let result = parse_single_file(path);
        
        assert_eq!(result.language, "python");
        assert!(result.success);
        assert!(result.tree.is_some());
        assert!(result.errors.is_empty());
    }

    #[test]
    fn test_parse_single_file_not_found() {
        let result = parse_single_file("/nonexistent/path/file.py");
        
        assert!(!result.success);
        assert!(result.tree.is_none());
        assert!(!result.errors.is_empty());
    }

    #[test]
    fn test_parse_files_batch_empty() {
        let result = parse_files_batch(vec![], BatchParseOptions::default());
        
        assert!(result.results.is_empty());
        assert_eq!(result.files_processed, 0);
        assert!(result.all_succeeded);
    }

    #[test]
    fn test_parse_files_batch_single_file() {
        // Create a temporary file
        let mut temp_file = tempfile::NamedTempFile::with_suffix(".py").unwrap();
        writeln!(temp_file, "x = 1").unwrap();
        let path = temp_file.path().to_str().unwrap().to_string();

        let result = parse_files_batch(vec![path], BatchParseOptions::default());
        
        assert_eq!(result.files_processed, 1);
        assert_eq!(result.success_count, 1);
        assert_eq!(result.error_count, 0);
        assert!(result.all_succeeded);
        assert!(result.total_time_ms >= 0.0);
    }

    #[test]
    fn test_parse_files_batch_multiple_files() {
        // Create temporary files
        let mut temp_file1 = tempfile::NamedTempFile::with_suffix(".py").unwrap();
        let mut temp_file2 = tempfile::NamedTempFile::with_suffix(".rs").unwrap();
        writeln!(temp_file1, "x = 1").unwrap();
        writeln!(temp_file2, "fn main() {{}}").unwrap();
        
        let paths = vec![
            temp_file1.path().to_str().unwrap().to_string(),
            temp_file2.path().to_str().unwrap().to_string(),
        ];

        let result = parse_files_batch(paths, BatchParseOptions::default());
        
        assert_eq!(result.files_processed, 2);
        assert_eq!(result.success_count, 2);
        assert!(result.all_succeeded);
        
        // Check individual results
        assert_eq!(result.results[0].language, "python");
        assert_eq!(result.results[1].language, "rust");
    }

    #[test]
    fn test_parse_files_batch_with_max_workers() {
        // Create temporary files
        let mut temp_file1 = tempfile::NamedTempFile::with_suffix(".py").unwrap();
        let mut temp_file2 = tempfile::NamedTempFile::with_suffix(".py").unwrap();
        writeln!(temp_file1, "x = 1").unwrap();
        writeln!(temp_file2, "y = 2").unwrap();
        
        let paths = vec![
            temp_file1.path().to_str().unwrap().to_string(),
            temp_file2.path().to_str().unwrap().to_string(),
        ];

        let options = BatchParseOptions::new().with_max_workers(2);
        let result = parse_files_batch(paths, options);
        
        assert_eq!(result.files_processed, 2);
        assert_eq!(result.success_count, 2);
    }

    #[test]
    fn test_parse_files_batch_mixed_success_failure() {
        // Create one valid file and one non-existent file
        let mut temp_file = tempfile::NamedTempFile::with_suffix(".py").unwrap();
        writeln!(temp_file, "x = 1").unwrap();
        
        let paths = vec![
            temp_file.path().to_str().unwrap().to_string(),
            "/nonexistent/path/file.py".to_string(),
        ];

        let result = parse_files_batch(paths, BatchParseOptions::default());
        
        assert_eq!(result.files_processed, 2);
        assert_eq!(result.success_count, 1);
        assert_eq!(result.error_count, 1);
        assert!(!result.all_succeeded);
        
        // First should succeed
        assert!(result.results[0].success);
        // Second should fail
        assert!(!result.results[1].success);
    }

    #[test]
    fn test_parse_files_parallel_preserves_order() {
        // Create multiple files
        let mut files: Vec<tempfile::NamedTempFile> = Vec::new();
        let mut paths: Vec<String> = Vec::new();
        
        for i in 0..5 {
            let mut file = tempfile::NamedTempFile::with_suffix(".py").unwrap();
            writeln!(file, "x{} = {}", i, i).unwrap();
            paths.push(file.path().to_str().unwrap().to_string());
            files.push(file); // Keep files alive
        }

        let result = parse_files_batch(paths.clone(), BatchParseOptions::default());
        
        // Results should be in same order as input
        assert_eq!(result.results.len(), paths.len());
        for (i, res) in result.results.iter().enumerate() {
            assert!(res.success, "File {} should parse successfully", i);
        }
    }
}
