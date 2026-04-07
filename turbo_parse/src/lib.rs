use pyo3::prelude::*;
use std::sync::OnceLock;

mod batch;
mod cache;
mod diagnostics;
mod folds;
mod highlights;
mod incremental;
mod injection;
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
use injection::{get_injections as _get_injections, get_injections_from_file as _get_injections_from_file, parse_injections, InjectionRange, InjectionResult, ParsedInjectionResult};
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

/// Detect language injections in source code.
///
/// Identifies regions of embedded languages within the source code,
/// such as SQL in Python strings or HTML in template literals.
///
/// # Arguments
/// * `source` - The source code to analyze
/// * `parent_language` - The language identifier of the host code (e.g., "python", "elixir")
///
/// # Returns
/// Dict with:
///   - parent_language: String - the language of the host code
///   - injections: List[Dict] - list of detected injection ranges
///   - detection_time_ms: f64 - time taken to detect injections
///   - success: bool - whether detection succeeded
///   - errors: List[str] - any errors encountered
///
/// Each injection contains:
///   - parent_language: str - the host language
///   - injected_language: str - the detected embedded language (e.g., "sql", "html")
///   - start_byte: int - starting byte position (0-indexed)
///   - end_byte: int - ending byte position (0-indexed, exclusive)
///   - content: str - the actual content of the injection
///   - node_kind: str - the AST node kind that triggered detection
///
/// # Example
/// ```python
/// import turbo_parse
/// source = '''
/// query = """
/// SELECT * FROM users WHERE id = %s
/// """
/// cursor.execute(query)
/// '''
/// result = turbo_parse.get_injections(source, "python")
/// for injection in result["injections"]:
///     print(f"Found {injection['injected_language']} at bytes {injection['start_byte']}-{injection['end_byte']}")
/// ```
#[pyfunction]
#[pyo3(signature = (source, parent_language))]
fn get_injections<'py>(py: Python<'py>, source: &str, parent_language: &str) -> PyResult<Bound<'py, PyAny>> {
    // Release GIL during CPU-intensive detection
    let result: InjectionResult = py.detach(|| {
        _get_injections(source, parent_language)
    });

    convert_json_to_py(py, &serde_json::to_value(&result).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e))
    })?)
}

/// Detect language injections from a file.
///
/// # Arguments
/// * `path` - Path to the file
/// * `language` - Optional language override (detected from extension if not provided)
///
/// # Returns
/// Dict with injection detection results (same format as get_injections).
///
/// # Example
/// ```python
/// import turbo_parse
/// result = turbo_parse.get_injections_from_file("app.py")
/// print(f"Found {len(result['injections'])} embedded language regions")
/// ```
#[pyfunction]
#[pyo3(signature = (path, language = None))]
fn get_injections_from_file<'py>(py: Python<'py>, path: &str, language: Option<&str>) -> PyResult<Bound<'py, PyAny>> {
    // Release GIL during file I/O and CPU-intensive detection
    let result: InjectionResult = py.detach(|| {
        _get_injections_from_file(path, language)
    });

    convert_json_to_py(py, &serde_json::to_value(&result).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e))
    })?)
}

/// Parse detected injections with their respective grammars.
///
/// Takes injection detection results and parses each embedded language
/// with its appropriate tree-sitter grammar, returning ASTs for each.
///
/// # Arguments
/// * `injection_result` - The result from get_injections (Python dict)
///
/// # Returns
/// Dict with:
///   - parent_language: String - the host language
///   - parsed_injections: List[Dict] - parsed injections with ASTs
///   - total_time_ms: f64 - time taken for the entire operation
///   - all_succeeded: bool - whether all injections parsed successfully
///   - language_counts: Dict[str, int] - count of injections by language
///
/// Each parsed injection contains:
///   - range: Dict - the injection range information
///   - tree: Dict or None - the parsed AST
///   - parse_success: bool - whether parsing succeeded
///   - parse_errors: List[str] - any parse errors
///   - parse_time_ms: f64 - time taken to parse
///
/// # Example
/// ```python
/// import turbo_parse
/// source = "query = '''SELECT * FROM users'''"
/// detection = turbo_parse.get_injections(source, "python")
/// parsed = turbo_parse.parse_injections(detection)
/// for inj in parsed["parsed_injections"]:
///     if inj["parse_success"]:
///         print(f"Parsed {inj['range']['injected_language']} successfully")
/// ```
#[pyfunction]
fn parse_injections_py<'py>(py: Python<'py>, injection_result: Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    // Convert Python dict to InjectionResult
    let json_module = py.import("json")?;
    let json_str: String = json_module.call_method1("dumps", (injection_result,))?.extract()?;
    let result: InjectionResult = serde_json::from_str(&json_str)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("Invalid injection result: {}", e)))?;

    // Parse injections with GIL released
    let parsed: ParsedInjectionResult = py.detach(|| {
        parse_injections(&result)
    });

    convert_json_to_py(py, &serde_json::to_value(&parsed).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e))
    })?)
}

/// Helper to convert serde_json::Value to Python object.
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
    // Injection detection functions
    m.add_function(wrap_pyfunction!(get_injections, m)?)?;
    m.add_function(wrap_pyfunction!(get_injections_from_file, m)?)?;
    m.add_function(wrap_pyfunction!(parse_injections_py, m)?)?;
    // Add pyclass types
    m.add_class::<InputEdit>()?;
    m.add_class::<InjectionRange>()?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add("DEFAULT_CACHE_CAPACITY", DEFAULT_CACHE_CAPACITY)?;
    Ok(())
}
