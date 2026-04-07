use pyo3::prelude::*;
use std::sync::OnceLock;

mod batch;
mod cache;
mod diagnostics;
mod parser;
mod registry;
mod stats;
mod symbols;

use batch::{parse_files_batch as _parse_files_batch, BatchParseOptions, BatchParseResult};
use cache::{ParseCache, CacheKey, CacheValue, compute_content_hash, DEFAULT_CACHE_CAPACITY};
use diagnostics::{extract_diagnostics, SyntaxDiagnostics};
use parser::{parse_file as _parse_file, parse_source as _parse_source, ParseResult};
use registry::{get_language as _get_language, is_language_supported as _is_language_supported, list_supported_languages, RegistryError};
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

/// The turbo_parse Python module.
#[pymodule]
fn turbo_parse(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(health_check, m)?)?;
    m.add_function(wrap_pyfunction!(get_stats_py, m)?)?;
    m.add_function(wrap_pyfunction!(parse_file, m)?)?;
    m.add_function(wrap_pyfunction!(parse_source, m)?)?;
    m.add_function(wrap_pyfunction!(parse_files_batch, m)?)?;
    m.add_function(wrap_pyfunction!(extract_syntax_diagnostics, m)?)?;
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
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add("DEFAULT_CACHE_CAPACITY", DEFAULT_CACHE_CAPACITY)?;
    Ok(())
}
