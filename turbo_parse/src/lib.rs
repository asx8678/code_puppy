//! Turbo Parse — High-performance parsing with tree-sitter and PyO3 bindings.
//!
//! This crate provides fast parsing, symbol extraction, and syntax highlighting
//! for multiple programming languages using tree-sitter grammars.
//!
//! # Features
//!
//! - `python` (default): Enable Python bindings via PyO3
//! - `dynamic-grammars`: Enable runtime loading of grammar libraries
//!
//! # Security Note: Dynamic Grammars
//!
//! When the `dynamic-grammars` feature is enabled, this crate can load
//! external shared libraries (.so/.dylib/.dll files). This carries security
//! implications:
//!
//! 1. **Only load libraries from trusted sources** — Dynamic libraries
//!    execute native code with the same privileges as the application.
//!
//! 2. **Path validation** — The crate includes path traversal protection,
//!    but you should still validate paths before calling `register_grammar()`.
//!
//! 3. **Allowed directories** — For production use, configure allowed
//!    directories to restrict where grammars can be loaded from.
//!
//! 4. **Library integrity** — Consider verifying checksums of grammar
//!    libraries before loading them.
//!
//! Example secure usage:
//! ```python
//! import turbo_parse
//!
//! # Only allow loading from specific directory
//! # (configure via DynamicGrammarLoader)
//!
//! # Register a grammar
//! result = turbo_parse.register_grammar("go", "/path/to/tree-sitter-go.so")
//! if result["success"]:
//!     print(f"Grammar loaded: version {result['version']}")
//! ```

use pyo3::prelude::*;
use std::sync::OnceLock;

mod batch;
mod cache;
mod diagnostics;
mod dynamic;
mod folds;
mod highlights;
mod incremental;
mod parser;
mod registry;
mod stats;
mod symbols;
pub mod queries;

use batch::{parse_files_batch as _parse_files_batch, BatchParseOptions, BatchParseResult};
use cache::{ParseCache, CacheKey, CacheValue, compute_content_hash, DEFAULT_CACHE_CAPACITY};
use diagnostics::{extract_diagnostics, SyntaxDiagnostics};
use folds::{get_folds as _get_folds, get_folds_from_file as _get_folds_from_file, FoldResult};
use highlights::{get_highlights as _get_highlights, get_highlights_from_file as _get_highlights_from_file, HighlightResult};
use incremental::{parse_with_edits, InputEdit};
use parser::{parse_file as _parse_file, parse_source as _parse_source, ParseResult};
use registry::{get_language as _get_language, is_language_supported as _is_language_supported, list_supported_languages, RegistryError, register_dynamic_grammar, is_dynamic_grammar_registered, unregister_dynamic_grammar};
use stats::{record_parse_operation, get_full_stats};
use symbols::{extract_symbols as _extract_symbols, SymbolOutline, extract_symbols_from_file as _extract_symbols_from_file};

/// Global singleton cache instance
pub static GLOBAL_CACHE: OnceLock<ParseCache> = OnceLock::new();

/// Parse source code directly with GIL release during parsing.
///
/// # Arguments
/// * `source` - The source code to parse
/// * `language` - The language identifier (e.g., "python", "rust", "javascript")
///
/// # Returns
/// Dict with:
///   - language: String - the detected/specified language
///   - tree: Dict or None - serialized tree representation
///   - parse_time_ms: f64 - time taken to parse
///   - success: bool - whether parsing succeeded
///   - errors: List[Dict] - any parse errors
///
/// # Example
/// ```python
/// import turbo_parse
/// result = turbo_parse.parse_source("def hello(): pass", "python")
/// print(result["success"])  # True
/// print(result["tree"])  # Serialized AST
/// ```
#[pyfunction]
#[pyo3(signature = (source, language))]
fn parse_source<'py>(py: Python<'py>, source: &str, language: &str) -> PyResult<Bound<'py, PyAny>> {
    // Release GIL during CPU-intensive parsing
    let result: ParseResult = py.detach(|| {
        _parse_source(source, language)
    });

    // Record metrics
    record_parse_operation(&result.language, result.parse_time_ms);

    convert_parse_result_to_py(py, &result)
}

/// Parse a file from disk with GIL release during parsing.
///
/// # Arguments
/// * `path` - Path to the file
/// * `language` - Optional language override (detected from extension if not provided)
///   Supported extensions: .py, .rs, .js, .jsx, .ts, .tsx, .ex, .exs
///
/// # Returns
/// Dict with:
///   - language: String - the detected/specified language
///   - tree: Dict or None - serialized tree representation
///   - parse_time_ms: f64 - time taken to parse
///   - success: bool - whether parsing succeeded
///   - errors: List[Dict] - any parse errors
///
/// # Example
/// ```python
/// import turbo_parse
/// result = turbo_parse.parse_file("test.py")
/// print(result["success"])  # True
/// print(result["language"])  # "python"
/// ```
#[pyfunction]
#[pyo3(signature = (path, language = None))]
fn parse_file<'py>(py: Python<'py>, path: &str, language: Option<&str>) -> PyResult<Bound<'py, PyAny>> {
    // Release GIL during file I/O and CPU-intensive parsing
    let result: ParseResult = py.detach(|| {
        _parse_file(path, language)
    });

    // Record metrics
    record_parse_operation(&result.language, result.parse_time_ms);

    convert_parse_result_to_py(py, &result)
}

/// Extract syntax diagnostics from source code.
///
/// Walks the tree-sitter tree and finds ERROR and MISSING nodes,
/// returning detailed diagnostics with position information.
///
/// # Arguments
/// * `source` - The source code to analyze
/// * `language` - The language identifier (e.g., "python", "rust", "javascript")
///
/// # Returns
/// Dict with:
///   - diagnostics: List[Dict] - list of diagnostic objects
///   - error_count: int - number of error-level diagnostics
///   - warning_count: int - number of warning-level diagnostics
///
/// Each diagnostic contains:
///   - message: str - human-readable error message
///   - severity: str - "error" or "warning"
///   - line: int - line number (1-indexed)
///   - column: int - column number (0-indexed)
///   - offset: int - byte offset in source
///   - length: int - length of error region in bytes
///   - node_kind: str - the kind of node that caused the error
#[pyfunction]
#[pyo3(signature = (source, language))]
fn extract_syntax_diagnostics<'py>(py: Python<'py>, source: &str, language: &str) -> PyResult<Bound<'py, PyAny>> {
    // Normalize language name
    let lang_name = language.to_lowercase();
    let normalized = match lang_name.as_str() {
        "py" => "python",
        "js" => "javascript",
        "ts" => "typescript",
        "ex" | "exs" => "elixir",
        _ => &lang_name,
    };

    // Get the tree-sitter language
    let ts_language = match _get_language(normalized) {
        Ok(lang) => lang,
        Err(RegistryError::UnsupportedLanguage(_)) => {
            let error_info = serde_json::json!({
                "diagnostics": [],
                "error_count": 0,
                "warning_count": 0,
                "error": format!("Unsupported language: '{}'", language),
            });
            return convert_json_to_py(py, &error_info);
        }
        Err(e) => {
            return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()));
        }
    };

    // Run diagnostics extraction with GIL released
    let diagnostics: SyntaxDiagnostics = py.detach(|| {
        extract_diagnostics(source, ts_language)
    });

    let result = serde_json::json!({
        "diagnostics": diagnostics.diagnostics,
        "error_count": diagnostics.error_count(),
        "warning_count": diagnostics.warning_count(),
        "language": normalized,
    });

    convert_json_to_py(py, &result)
}

/// Helper to convert ParseResult to Python dict.
fn convert_parse_result_to_py<'py>(py: Python<'py>, result: &ParseResult) -> PyResult<Bound<'py, PyAny>> {
    let json_str = serde_json::to_string(result)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e)))?;

    let json_module = py.import("json")?;
    let py_dict = json_module.call_method1("loads", (json_str,))?;
    Ok(py_dict)
}

/// Initialize the global parse cache
#[pyfunction]
#[pyo3(signature = (capacity = None))]
fn init_cache<'py>(py: Python<'py>, capacity: Option<usize>) -> PyResult<Bound<'py, PyAny>> {
    let cap = capacity.unwrap_or(DEFAULT_CACHE_CAPACITY);
    
    // Note: We can't reinitialize OnceLock, so this is idempotent
    let _ = GLOBAL_CACHE.get_or_init(|| ParseCache::with_capacity(cap));
    
    get_cache_info(py)
}

/// Get a value from the cache
///
/// Args:
///   file_path: Path to the file
///   content_hash: SHA256 hash of the content
///
/// Returns:
///   Dict with the cached value if found, None otherwise
#[pyfunction]
fn cache_get<'py>(py: Python<'py>, file_path: &str, content_hash: &str) -> PyResult<Option<Bound<'py, PyAny>>> {
    let cache = GLOBAL_CACHE.get_or_init(ParseCache::new);
    let key = CacheKey::with_hash(file_path, content_hash);
    
    match cache.get(&key) {
        Some(value) => {
            let json_str = serde_json::to_string(&value)
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e)))?;
            let json_module = py.import("json")?;
            let py_dict = json_module.call_method1("loads", (json_str,))?;
            Ok(Some(py_dict))
        }
        None => Ok(None),
    }
}

/// Remove a specific entry from the cache
///
/// Args:
///   file_path: Path to the file
///   content_hash: SHA256 hash of the content
///
/// Returns:
///   True if an entry was removed, False if not found
#[pyfunction]
fn cache_remove(_py: Python<'_>, file_path: &str, content_hash: &str) -> PyResult<bool> {
    let cache = GLOBAL_CACHE.get_or_init(ParseCache::new);
    let key = CacheKey::with_hash(file_path, content_hash);
    
    match cache.remove(&key) {
        Some(_) => Ok(true),
        None => Ok(false),
    }
}

/// Check if an entry exists in the cache (without updating LRU order)
///
/// Args:
///   file_path: Path to the file
///   content_hash: SHA256 hash of the content
///
/// Returns:
///   True if entry exists, False otherwise
#[pyfunction]
fn cache_contains(file_path: &str, content_hash: &str) -> bool {
    let cache = GLOBAL_CACHE.get_or_init(ParseCache::new);
    let key = CacheKey::with_hash(file_path, content_hash);
    cache.contains(&key)
}

/// Put a value into the cache
///
/// Args:
///   file_path: Path to the file
///   content_hash: SHA256 hash of the content
///   tree_data: Serialized tree data (JSON)
///   language: Language identifier (e.g., "python", "rust")
///
/// Returns:
///   True if an entry was evicted due to cache being full
#[pyfunction]
fn cache_put<'py>(
    py: Python<'py>,
    file_path: &str,
    content_hash: &str,
    tree_data: Bound<'py, PyAny>,
    language: &str,
) -> PyResult<bool> {
    let cache = GLOBAL_CACHE.get_or_init(ParseCache::new);
    let key = CacheKey::with_hash(file_path, content_hash);
    
    // Convert Python object to JSON
    let json_module = py.import("json")?;
    let json_str: String = json_module.call_method1("dumps", (tree_data,))?.extract()?;
    let tree_json: serde_json::Value = serde_json::from_str(&json_str)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("Invalid JSON: {}", e)))?;
    
    let value = CacheValue::new(tree_json, language);
    Ok(cache.put(key, value))
}

/// Clear all entries from the cache
#[pyfunction]
fn cache_clear() {
    if let Some(cache) = GLOBAL_CACHE.get() {
        cache.clear();
    }
}

/// Get cache statistics
///
/// Returns:
///   Dict with size, capacity, hits, misses, evictions, hit_ratio
#[pyfunction]
fn cache_stats<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
    let cache = GLOBAL_CACHE.get_or_init(ParseCache::new);
    let stats = cache.stats();
    
    let info = serde_json::json!({
        "size": stats.size,
        "capacity": stats.capacity,
        "hits": stats.hits,
        "misses": stats.misses,
        "evictions": stats.evictions,
        "hit_ratio": stats.hit_ratio(),
    });
    
    let json_str = serde_json::to_string(&info)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e)))?;
    
    let json_module = py.import("json")?;
    let py_dict = json_module.call_method1("loads", (json_str,))?;
    Ok(py_dict)
}

/// Compute SHA256 hash of content
#[pyfunction]
fn compute_hash(content: &str) -> String {
    compute_content_hash(content)
}

/// Get cache info and status
#[pyfunction]
fn get_cache_info<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
    let cache = GLOBAL_CACHE.get_or_init(ParseCache::new);
    let stats = cache.stats();
    
    let info = serde_json::json!({
        "initialized": true,
        "size": cache.len(),
        "capacity": cache.capacity(),
        "is_empty": cache.is_empty(),
        "stats": {
            "hits": stats.hits,
            "misses": stats.misses,
            "evictions": stats.evictions,
            "hit_ratio": stats.hit_ratio(),
        }
    });
    
    let json_str = serde_json::to_string(&info)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e)))?;
    
    let json_module = py.import("json")?;
    let py_dict = json_module.call_method1("loads", (json_str,))?;
    Ok(py_dict)
}

/// Check if a language is supported.
///
/// Returns true if the language is supported, false otherwise.
#[pyfunction]
#[pyo3(signature = (name))]
fn is_language_supported(_py: Python<'_>, name: &str) -> bool {
    _is_language_supported(name)
}

/// Get a tree-sitter Language by name.
///
/// Supported languages:
///   - "python", "py"
///   - "rust"
///   - "javascript", "js"
///   - "typescript", "ts"
///   - "tsx"
///   - "elixir", "ex"
///
/// Returns a dict with:
///   name: the language name (normalized)
///   version: the tree-sitter language version
///   supported: true
///
/// Raises RuntimeError if the language is not supported.
#[pyfunction]
#[pyo3(signature = (name))]
fn get_language<'py>(py: Python<'py>, name: &str) -> PyResult<Bound<'py, PyAny>> {
    match _get_language(name) {
        Ok(lang) => {
            let info = serde_json::json!({
                "name": name.to_lowercase(),
                "version": lang.version(),
                "supported": true,
            });
            convert_json_to_py(py, &info)
        }
        Err(RegistryError::UnsupportedLanguage(lang)) => {
            let info = serde_json::json!({
                "name": lang,
                "supported": false,
                "error": format!("Unsupported language: '{}'", lang),
            });
            convert_json_to_py(py, &info)
        }
        Err(e) => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string())),
    }
}

/// Get a list of all supported language names.
///
/// Returns a list of strings with supported language names.
#[pyfunction]
fn supported_languages<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
    let langs = list_supported_languages();
    let info = serde_json::json!({
        "languages": langs,
        "count": langs.len(),
    });
    convert_json_to_py(py, &info)
}

/// Check if the turbo_parse module is available and healthy.
///
/// Returns a dict with module info including:
///   available: always true (if this function is callable)
///   version: crate version
///   languages: list of supported language names
///   cache_available: whether the cache is initialized
#[pyfunction]
fn health_check<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
    let cache_initialized = GLOBAL_CACHE.get().is_some();
    let langs = list_supported_languages();
    
    let info = serde_json::json!({
        "available": true,
        "version": env!("CARGO_PKG_VERSION"),
        "languages": langs,
        "cache_available": cache_initialized,
    });

    let json_str = serde_json::to_string(&info)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e)))?;

    let json_module = py.import("json")?;
    let py_dict = json_module.call_method1("loads", (json_str,))?;
    Ok(py_dict)
}

/// Get statistics about turbo_parse operations.
///
/// Returns a dict with:
///   total_parses: u64 - count of parse operations
///   cache_hits: u64 - number of cache hits
///   cache_misses: u64 - number of cache misses
///   cache_evictions: u64 - number of cache evictions
///   cache_hit_ratio: f64 - cache hit ratio (0.0 to 1.0)
///   average_parse_time_ms: f64 - average parse time in milliseconds
///   languages_used: dict - per-language usage histogram
#[pyfunction(name = "stats")]
fn get_stats_py<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
    let stats = get_full_stats();
    
    let json_str = serde_json::to_string(&stats)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e)))?;

    let json_module = py.import("json")?;
    let py_dict = json_module.call_method1("loads", (json_str,))?;
    Ok(py_dict)
}

/// Parse multiple files in parallel using all available CPU cores.
///
/// This function releases the GIL during parsing, allowing other
/// Python threads to execute while parsing happens in parallel.
///
/// # Arguments
/// * `paths` - List of file paths to parse (Python list of strings)
/// * `max_workers` - Optional maximum number of worker threads (default: all cores)
///
/// # Returns
/// Dict with:
///   - results: List[Dict] - individual parse results for each file
///   - total_time_ms: float - time taken for entire batch
///   - files_processed: int - number of files processed
///   - success_count: int - number of files successfully parsed
///   - error_count: int - number of files that failed
///   - all_succeeded: bool - true if all files succeeded
///
/// Each result in the results list contains:
///   - language: str - detected language
///   - tree: dict or None - serialized AST
///   - parse_time_ms: float - individual file parse time
///   - success: bool - whether this file succeeded
///   - errors: list - any parse errors for this file
///
/// # Example
/// ```python
/// import turbo_parse
/// paths = ["file1.py", "file2.rs", "file3.js"]
/// result = turbo_parse.parse_files_batch(paths, max_workers=4)
/// print(f"Processed {result['files_processed']} files in {result['total_time_ms']}ms")
/// for r in result['results']:
///     print(f"  {r['language']}: success={r['success']}")
/// ```
#[pyfunction]
#[pyo3(signature = (paths, max_workers = None))]
fn parse_files_batch<'py>(
    py: Python<'py>,
    paths: Vec<String>,
    max_workers: Option<usize>,
) -> PyResult<Bound<'py, PyAny>> {
    let options = BatchParseOptions { max_workers, timeout_ms: None };
    
    // Release GIL during CPU-intensive batch parsing
    let result: BatchParseResult = py.detach(|| {
        _parse_files_batch(paths, options)
    });

    // Record metrics for each individual result
    for parse_result in &result.results {
        record_parse_operation(&parse_result.language, parse_result.parse_time_ms);
    }

    convert_batch_result_to_py(py, &result)
}

/// Helper to convert BatchParseResult to Python dict.
fn convert_batch_result_to_py<'py>(py: Python<'py>, result: &BatchParseResult) -> PyResult<Bound<'py, PyAny>> {
    let json_str = serde_json::to_string(result)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e)))?;

    let json_module = py.import("json")?;
    let py_dict = json_module.call_method1("loads", (json_str,))?;
    Ok(py_dict)
}

/// Helper to convert serde_json::Value to Python object.
fn convert_json_to_py<'py>(py: Python<'py>, value: &serde_json::Value) -> PyResult<Bound<'py, PyAny>> {
    let json_str = serde_json::to_string(value)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e)))?;

    let json_module = py.import("json")?;
    let py_dict = json_module.call_method1("loads", (json_str,))?;
    Ok(py_dict)
}

/// Extract symbols from source code.
///
/// # Arguments
/// * `source` - The source code to analyze
/// * `language` - The language identifier (e.g., "python", "rust")
///
/// # Returns
/// Dict with:
///   - language: String - the detected/specified language
///   - symbols: List[Dict] - list of symbols with name, kind, position info
///   - extraction_time_ms: f64 - time taken to extract
///   - success: bool - whether extraction succeeded
///   - errors: List[str] - any extraction errors
///
/// # Example
/// ```python
/// import turbo_parse
/// result = turbo_parse.extract_symbols("def hello(): pass", "python")
/// print(result["symbols"])  # [{"name": "hello", "kind": "function", ...}]
/// ```
#[pyfunction]
#[pyo3(signature = (source, language))]
fn extract_symbols<'py>(py: Python<'py>, source: &str, language: &str) -> PyResult<Bound<'py, PyAny>> {
    // Release GIL during CPU-intensive symbol extraction
    let outline: SymbolOutline = py.detach(|| {
        _extract_symbols(source, language)
    });

    convert_json_to_py(py, &serde_json::to_value(&outline).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e))
    })?)
}

/// Extract symbols from a file.
///
/// # Arguments
/// * `path` - Path to the file
/// * `language` - Optional language override (detected from extension if not provided)
///   Supported extensions: .py, .rs, .js, .jsx, .ts, .tsx, .ex, .exs
///
/// # Returns
/// Dict with:
///   - language: String - the detected/specified language
///   - symbols: List[Dict] - list of symbols with name, kind, position info
///   - extraction_time_ms: f64 - time taken to extract
///   - success: bool - whether extraction succeeded
///   - errors: List[str] - any extraction errors
///
/// # Example
/// ```python
/// import turbo_parse
/// result = turbo_parse.extract_symbols_from_file("test.py")
/// print(result["symbols"])  # [{"name": "...", "kind": "...", ...}]
/// ```
#[pyfunction]
#[pyo3(signature = (path, language = None))]
fn extract_symbols_from_file<'py>(py: Python<'py>, path: &str, language: Option<&str>) -> PyResult<Bound<'py, PyAny>> {
    // Release GIL during file I/O and CPU-intensive symbol extraction
    let outline: SymbolOutline = py.detach(|| {
        _extract_symbols_from_file(path, language)
    });

    convert_json_to_py(py, &serde_json::to_value(&outline).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e))
    })?)
}

/// Extract fold ranges from source code.
///
/// # Arguments
/// * `source` - The source code to analyze
/// * `language` - The language identifier (e.g., "python", "rust")
///
/// # Returns
/// Dict with:
///   - language: String - the detected/specified language
///   - folds: List[Dict] - list of fold ranges with start_line, end_line, fold_type
///   - extraction_time_ms: f64 - time taken to extract
///   - success: bool - whether extraction succeeded
///   - errors: List[str] - any extraction errors
///
/// Each fold contains:
///   - start_line: int - starting line (1-indexed)
///   - end_line: int - ending line (1-indexed)
///   - fold_type: str - type of fold ("function", "class", "conditional", "loop", "block", "import", "generic")
///
/// # Example
/// ```python
/// import turbo_parse
/// source = """
/// def hello():
///     pass
/// 
/// class MyClass:
///     def method(self):
///         pass
/// """
/// result = turbo_parse.get_folds(source, "python")
/// for fold in result["folds"]:
///     print(f"{fold['fold_type']}: lines {fold['start_line']}-{fold['end_line']}")
/// ```
#[pyfunction]
#[pyo3(signature = (source, language))]
fn get_folds<'py>(py: Python<'py>, source: &str, language: &str) -> PyResult<Bound<'py, PyAny>> {
    // Release GIL during CPU-intensive fold extraction
    let result: FoldResult = py.detach(|| {
        _get_folds(source, language)
    });

    convert_json_to_py(py, &serde_json::to_value(&result).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e))
    })?)
}

/// Extract fold ranges from a file.
///
/// # Arguments
/// * `path` - Path to the file
/// * `language` - Optional language override (detected from extension if not provided)
///
/// # Returns
/// Dict with:
///   - language: String - the detected/specified language
///   - folds: List[Dict] - list of fold ranges
///   - extraction_time_ms: f64 - time taken to extract
///   - success: bool - whether extraction succeeded
///   - errors: List[str] - any extraction errors
///
/// # Example
/// ```python
/// import turbo_parse
/// result = turbo_parse.get_folds_from_file("test.py")
/// print(f"Found {len(result['folds'])} foldable regions")
/// ```
#[pyfunction]
#[pyo3(signature = (path, language = None))]
fn get_folds_from_file<'py>(py: Python<'py>, path: &str, language: Option<&str>) -> PyResult<Bound<'py, PyAny>> {
    // Release GIL during file I/O and CPU-intensive fold extraction
    let result: FoldResult = py.detach(|| {
        _get_folds_from_file(path, language)
    });

    convert_json_to_py(py, &serde_json::to_value(&result).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e))
    })?)
}

/// Extract syntax highlights from source code.
///
/// # Arguments
/// * `source` - The source code to analyze
/// * `language` - The language identifier (e.g., "python", "rust", "javascript")
///
/// # Returns
/// Dict with:
///   - language: String - the detected/specified language
///   - captures: List[Dict] - list of highlight captures with start_byte, end_byte, capture_name
///   - extraction_time_ms: f64 - time taken to extract
///   - success: bool - whether extraction succeeded
///   - errors: List[str] - any extraction errors
///
/// Each capture contains:
///   - start_byte: int - starting byte position (0-indexed)
///   - end_byte: int - ending byte position (0-indexed, exclusive)
///   - capture_name: str - capture name following Helix conventions (e.g., "keyword", "string")
///
/// # Example
/// ```python
/// import turbo_parse
/// source = "def hello(): pass"
/// result = turbo_parse.get_highlights(source, "python")
/// for cap in result["captures"]:
///     print(f"{cap['capture_name']}: bytes {cap['start_byte']}-{cap['end_byte']}")
/// ```
#[pyfunction]
#[pyo3(signature = (source, language))]
fn get_highlights<'py>(py: Python<'py>, source: &str, language: &str) -> PyResult<Bound<'py, PyAny>> {
    // Release GIL during CPU-intensive highlight extraction
    let result: HighlightResult = py.detach(|| {
        _get_highlights(source, language)
    });

    convert_json_to_py(py, &serde_json::to_value(&result).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e))
    })?)
}

/// Extract syntax highlights from a file.
///
/// # Arguments
/// * `path` - Path to the file
/// * `language` - Optional language override (detected from extension if not provided)
///
/// # Returns
/// Dict with:
///   - language: String - the detected/specified language
///   - captures: List[Dict] - list of highlight captures
///   - extraction_time_ms: f64 - time taken to extract
///   - success: bool - whether extraction succeeded
///   - errors: List[str] - any extraction errors
///
/// # Example
/// ```python
/// import turbo_parse
/// result = turbo_parse.get_highlights_from_file("test.py")
/// print(f"Found {len(result['captures'])} highlight captures")
/// ```
#[pyfunction]
#[pyo3(signature = (path, language = None))]
fn get_highlights_from_file<'py>(py: Python<'py>, path: &str, language: Option<&str>) -> PyResult<Bound<'py, PyAny>> {
    // Release GIL during file I/O and CPU-intensive highlight extraction
    let result: HighlightResult = py.detach(|| {
        _get_highlights_from_file(path, language)
    });

    convert_json_to_py(py, &serde_json::to_value(&result).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e))
    })?)
}

/// Register a dynamic grammar library at runtime.
///
/// This function loads a tree-sitter grammar from a shared library
/// (.so/.dylib/.dll file) and makes it available for parsing.
///
/// # Security Warning
/// Only load libraries from trusted sources. Dynamic libraries execute
/// native code with the same privileges as the application.
///
/// # Arguments
/// * `name` - The grammar name (e.g., "go", "ruby", "c")
/// * `library_path` - Path to the compiled grammar library
///
/// # Returns
/// Dict with:
///   - success: bool - whether registration succeeded
///   - name: str - the grammar name
///   - version: int - tree-sitter language version (if successful)
///   - error: str or None - error message if failed
///
/// # Example
/// ```python
/// import turbo_parse
///
/// result = turbo_parse.register_grammar("go", "/usr/local/lib/tree-sitter-go.so")
/// if result["success"]:
///     print(f"Loaded grammar version {result['version']}")
/// else:
///     print(f"Error: {result['error']}")
/// ```
#[pyfunction]
#[pyo3(signature = (name, library_path))]
fn register_grammar<'py>(py: Python<'py>, name: &str, library_path: &str) -> PyResult<Bound<'py, PyAny>> {
    use crate::registry::register_dynamic_grammar;
    
    // Release GIL during library loading
    let result = py.detach(|| {
        register_dynamic_grammar(name, library_path)
    });
    
    match result {
        Ok(()) => {
            // Try to get version info
            let version = _get_language(name)
                .map(|lang| lang.version())
                .unwrap_or(0);
            
            let info = serde_json::json!({
                "success": true,
                "name": name,
                "version": version,
                "error": serde_json::Value::Null,
            });
            convert_json_to_py(py, &info)
        }
        Err(e) => {
            let info = serde_json::json!({
                "success": false,
                "name": name,
                "version": serde_json::Value::Null,
                "error": e.to_string(),
            });
            convert_json_to_py(py, &info)
        }
    }
}

/// Unregister a dynamic grammar.
///
/// Removes a previously registered grammar from the registry.
///
/// # Arguments
/// * `name` - The grammar name to unregister
///
/// # Returns
/// True if the grammar was removed, False if it wasn't registered
#[pyfunction]
#[pyo3(signature = (name))]
fn unregister_grammar(_py: Python<'_>, name: &str) -> bool {
    unregister_dynamic_grammar(name)
}

/// Check if a grammar is registered (including dynamic grammars).
///
/// # Arguments
/// * `name` - The grammar name to check
///
/// # Returns
/// True if the grammar is registered (built-in or dynamic), False otherwise
#[pyfunction]
#[pyo3(signature = (name))]
fn is_grammar_registered(_py: Python<'_>, name: &str) -> bool {
    // Check built-in
    if _is_language_supported(name) {
        return true;
    }
    // Check dynamic
    is_dynamic_grammar_registered(name)
}

/// List all registered grammars with their types.
///
/// Returns a list of dictionaries with grammar information:
///   - name: str - the grammar name
///   - type: str - "built-in" or "dynamic"
///   - version: int - language version
#[pyfunction]
fn list_registered_grammars<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
    use crate::dynamic::list_dynamic_grammars;
    
    let mut grammars = Vec::new();
    
    // Add built-in grammars
    for name in list_supported_languages() {
        if let Ok(lang) = _get_language(&name) {
            grammars.push(serde_json::json!({
                "name": name,
                "type": "built-in",
                "version": lang.version(),
            }));
        }
    }
    
    // Add dynamic grammars
    let dynamic = list_dynamic_grammars();
    for info in dynamic {
        grammars.push(serde_json::json!({
            "name": info.name,
            "type": "dynamic",
            "version": info.version,
        }));
    }
    
    let result = serde_json::json!({
        "grammars": grammars,
        "total_count": grammars.len(),
        "built_in_count": grammars.iter().filter(|g| g["type"] == "built-in").count(),
        "dynamic_count": grammars.iter().filter(|g| g["type"] == "dynamic").count(),
    });
    
    convert_json_to_py(py, &result)
}

/// Check if dynamic grammar loading is enabled.
///
/// Returns True if the `dynamic-grammars` feature was compiled in,
/// False otherwise.
#[pyfunction]
fn dynamic_grammars_enabled() -> bool {
    cfg!(feature = "dynamic-grammars")
}

/// Get information about dynamic grammar loading status.
///
/// Returns a dict with:
///   - enabled: bool - whether the feature is enabled
///   - platform: str - the current platform (linux, macos, windows)
///   - library_extension: str - the expected file extension (.so, .dylib, .dll)
///   - loaded_count: int - number of dynamic grammars currently loaded
#[pyfunction]
fn dynamic_grammar_info<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
    use crate::dynamic::{global_loader, DYLIB_EXTENSION};
    
    let loader = global_loader();
    let loaded = loader.list_loaded();
    
    let platform = if cfg!(target_os = "linux") {
        "linux"
    } else if cfg!(target_os = "macos") {
        "macos"
    } else if cfg!(target_os = "windows") {
        "windows"
    } else {
        "unknown"
    };
    
    let result = serde_json::json!({
        "enabled": cfg!(feature = "dynamic-grammars"),
        "platform": platform,
        "library_extension": DYLIB_EXTENSION,
        "loaded_count": loaded.len(),
        "loaded_grammars": loaded.iter().map(|g| {
            serde_json::json!({
                "name": g.name,
                "path": g.library_path.to_string_lossy().to_string(),
                "version": g.version,
                "has_external_scanner": g.has_external_scanner,
            })
        }).collect::<Vec<_>>(),
    });
    
    convert_json_to_py(py, &result)
}

/// The turbo_parse Python module.
#[pymodule]
fn turbo_parse(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(health_check, m)?)?;
    m.add_function(wrap_pyfunction!(get_stats_py, m)?)?;
    m.add_function(wrap_pyfunction!(parse_file, m)?)?;
    m.add_function(wrap_pyfunction!(parse_source, m)?)?;
    m.add_function(wrap_pyfunction!(parse_files_batch, m)?)?;
    m.add_function(wrap_pyfunction!(extract_syntax_diagnostics, m)?)?;
    m.add_function(wrap_pyfunction!(parse_with_edits, m)?)?;
    // Cache functions from main
    // Symbol extraction functions added
    m.add_function(wrap_pyfunction!(init_cache, m)?)?;
    m.add_function(wrap_pyfunction!(cache_get, m)?)?;
    m.add_function(wrap_pyfunction!(cache_put, m)?)?;
    m.add_function(wrap_pyfunction!(cache_remove, m)?)?;
    m.add_function(wrap_pyfunction!(cache_contains, m)?)?;
    m.add_function(wrap_pyfunction!(cache_clear, m)?)?;
    m.add_function(wrap_pyfunction!(cache_stats, m)?)?;
    m.add_function(wrap_pyfunction!(compute_hash, m)?)?;
    m.add_function(wrap_pyfunction!(get_cache_info, m)?)?;
    // Language registry functions
    m.add_function(wrap_pyfunction!(is_language_supported, m)?)?;
    m.add_function(wrap_pyfunction!(get_language, m)?)?;
    m.add_function(wrap_pyfunction!(supported_languages, m)?)?;
    // Symbol extraction functions
    m.add_function(wrap_pyfunction!(extract_symbols, m)?)?;
    m.add_function(wrap_pyfunction!(extract_symbols_from_file, m)?)?;
    // Fold extraction functions
    m.add_function(wrap_pyfunction!(get_folds, m)?)?;
    m.add_function(wrap_pyfunction!(get_folds_from_file, m)?)?;
    // Highlight extraction functions
    m.add_function(wrap_pyfunction!(get_highlights, m)?)?;
    m.add_function(wrap_pyfunction!(get_highlights_from_file, m)?)?;
    // Dynamic grammar functions
    m.add_function(wrap_pyfunction!(register_grammar, m)?)?;
    m.add_function(wrap_pyfunction!(unregister_grammar, m)?)?;
    m.add_function(wrap_pyfunction!(is_grammar_registered, m)?)?;
    m.add_function(wrap_pyfunction!(list_registered_grammars, m)?)?;
    m.add_function(wrap_pyfunction!(dynamic_grammars_enabled, m)?)?;
    m.add_function(wrap_pyfunction!(dynamic_grammar_info, m)?)?;
    // Add pyclass types
    m.add_class::<InputEdit>()?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add("DEFAULT_CACHE_CAPACITY", DEFAULT_CACHE_CAPACITY)?;
    Ok(())
}
