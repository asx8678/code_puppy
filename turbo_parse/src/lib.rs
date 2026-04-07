//! Turbo Parse - High-performance parsing with tree-sitter
//!
//! This crate provides fast parsing for multiple languages.
//! It can be built either:
//! - As a Rust library (`--no-default-features` for benchmarks)
//! - As a Python extension module (`--features python`, default)

#![allow(dead_code)]

use std::sync::OnceLock;

mod batch;
mod cache;
mod diagnostics;
mod incremental;
pub mod parser;
mod registry;
mod stats;
mod symbols;
pub mod queries;

pub use batch::{parse_files_batch, BatchParseOptions, BatchParseResult};
pub use cache::{ParseCache, CacheKey, CacheValue, compute_content_hash, DEFAULT_CACHE_CAPACITY};
pub use diagnostics::{extract_diagnostics, SyntaxDiagnostics};
pub use incremental::InputEdit;
#[cfg(feature = "python")]
pub use incremental::parse_with_edits;
pub use incremental::parse_with_edits_internal;
pub use parser::{parse_file, parse_source, ParseError, ParseResult};
pub use registry::{get_language, is_language_supported, list_supported_languages, RegistryError};
pub use stats::{get_full_stats, record_parse_operation};
pub use symbols::{extract_symbols, extract_symbols_from_file, Symbol, SymbolOutline};

/// Global singleton cache instance
pub static GLOBAL_CACHE: OnceLock<ParseCache> = OnceLock::new();

/// Initialize the global parse cache
pub fn init_cache_with_capacity(capacity: usize) -> &'static ParseCache {
    GLOBAL_CACHE.get_or_init(|| ParseCache::with_capacity(capacity))
}

/// Get cache statistics
pub fn get_cache_stats() -> cache::CacheStats {
    let cache = GLOBAL_CACHE.get_or_init(ParseCache::new);
    cache.stats()
}

/// Get cache info
pub fn get_global_cache() -> Option<&'static ParseCache> {
    GLOBAL_CACHE.get()
}

/// Check if cache is initialized
pub fn is_cache_initialized() -> bool {
    GLOBAL_CACHE.get().is_some()
}

// Python bindings - only included when `python` feature is enabled
#[cfg(feature = "python")]
mod python {
    pub use super::*;
    use pyo3::prelude::*;

    /// Parse source code directly with GIL release during parsing.
    #[pyfunction]
    #[pyo3(signature = (source, language))]
    fn parse_source_py<'py>(py: Python<'py>, source: &str, language: &str) -> PyResult<Bound<'py, PyAny>> {
        let result: ParseResult = py.detach(|| {
            parse_source(source, language)
        });

        record_parse_operation(&result.language, result.parse_time_ms);
        convert_parse_result_to_py(py, &result)
    }

    /// Parse a file from disk with GIL release during parsing.
    #[pyfunction]
    #[pyo3(signature = (path, language = None))]
    fn parse_file_py<'py>(py: Python<'py>, path: &str, language: Option<&str>) -> PyResult<Bound<'py, PyAny>> {
        let result: ParseResult = py.detach(|| {
            parse_file(path, language)
        });

        record_parse_operation(&result.language, result.parse_time_ms);
        convert_parse_result_to_py(py, &result)
    }

    /// Extract syntax diagnostics from source code.
    #[pyfunction]
    #[pyo3(signature = (source, language))]
    fn extract_syntax_diagnostics<'py>(py: Python<'py>, source: &str, language: &str) -> PyResult<Bound<'py, PyAny>> {
        let lang_name = language.to_lowercase();
        let normalized = match lang_name.as_str() {
            "py" => "python",
            "js" => "javascript",
            "ts" => "typescript",
            "ex" | "exs" => "elixir",
            _ => &lang_name,
        };

        let ts_language = match get_language(normalized) {
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

    /// Helper to convert serde_json::Value to Python object.
    fn convert_json_to_py<'py>(py: Python<'py>, value: &serde_json::Value) -> PyResult<Bound<'py, PyAny>> {
        let json_str = serde_json::to_string(value)
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
        let _ = GLOBAL_CACHE.get_or_init(|| ParseCache::with_capacity(cap));
        get_cache_info(py)
    }

    /// Get a value from the cache
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
    #[pyfunction]
    fn cache_remove(_py: Python<'_>, file_path: &str, content_hash: &str) -> PyResult<bool> {
        let cache = GLOBAL_CACHE.get_or_init(ParseCache::new);
        let key = CacheKey::with_hash(file_path, content_hash);
        
        match cache.remove(&key) {
            Some(_) => Ok(true),
            None => Ok(false),
        }
    }

    /// Check if an entry exists in the cache
    #[pyfunction]
    fn cache_contains(file_path: &str, content_hash: &str) -> bool {
        let cache = GLOBAL_CACHE.get_or_init(ParseCache::new);
        let key = CacheKey::with_hash(file_path, content_hash);
        cache.contains(&key)
    }

    /// Put a value into the cache
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
        
        convert_json_to_py(py, &info)
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
        
        convert_json_to_py(py, &info)
    }

    /// Check if a language is supported.
    #[pyfunction]
    fn is_language_supported_py(_py: Python<'_>, name: &str) -> bool {
        is_language_supported(name)
    }

    /// Get a tree-sitter Language by name.
    #[pyfunction]
    fn get_language_py<'py>(py: Python<'py>, name: &str) -> PyResult<Bound<'py, PyAny>> {
        match get_language(name) {
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

        convert_json_to_py(py, &info)
    }

    /// Get statistics about turbo_parse operations.
    #[pyfunction(name = "stats")]
    fn get_stats_py<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let stats = get_full_stats();
        convert_json_to_py(py, &serde_json::to_value(&stats).unwrap())
    }

    /// Parse multiple files in parallel.
    #[pyfunction]
    #[pyo3(signature = (paths, max_workers = None))]
    fn parse_files_batch_py<'py>(
        py: Python<'py>,
        paths: Vec<String>,
        max_workers: Option<usize>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let options = BatchParseOptions { max_workers, timeout_ms: None };
        
        let result: BatchParseResult = py.detach(|| {
            parse_files_batch(paths, options)
        });

        for parse_result in &result.results {
            record_parse_operation(&parse_result.language, parse_result.parse_time_ms);
        }

        let json_str = serde_json::to_string(&result)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e)))?;

        let json_module = py.import("json")?;
        let py_dict = json_module.call_method1("loads", (json_str,))?;
        Ok(py_dict)
    }

    /// Extract symbols from source code.
    #[pyfunction]
    #[pyo3(signature = (source, language))]
    fn extract_symbols_py<'py>(py: Python<'py>, source: &str, language: &str) -> PyResult<Bound<'py, PyAny>> {
        let outline: SymbolOutline = py.detach(|| {
            extract_symbols(source, language)
        });

        convert_json_to_py(py, &serde_json::to_value(&outline).unwrap())
    }

    /// Extract symbols from a file.
    #[pyfunction]
    #[pyo3(signature = (path, language = None))]
    fn extract_symbols_from_file_py<'py>(py: Python<'py>, path: &str, language: Option<&str>) -> PyResult<Bound<'py, PyAny>> {
        let outline: SymbolOutline = py.detach(|| {
            extract_symbols_from_file(path, language)
        });

        convert_json_to_py(py, &serde_json::to_value(&outline).unwrap())
    }

    /// The turbo_parse Python module.
    #[pymodule]
    fn turbo_parse(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_function(wrap_pyfunction!(health_check, m)?)?;
        m.add_function(wrap_pyfunction!(get_stats_py, m)?)?;
        m.add_function(wrap_pyfunction!(parse_file_py, m)?)?;
        m.add_function(wrap_pyfunction!(parse_source_py, m)?)?;
        m.add_function(wrap_pyfunction!(parse_files_batch_py, m)?)?;
        m.add_function(wrap_pyfunction!(extract_syntax_diagnostics, m)?)?;
        m.add_function(wrap_pyfunction!(parse_with_edits, m)?)?;
        m.add_function(wrap_pyfunction!(init_cache, m)?)?;
        m.add_function(wrap_pyfunction!(cache_get, m)?)?;
        m.add_function(wrap_pyfunction!(cache_put, m)?)?;
        m.add_function(wrap_pyfunction!(cache_remove, m)?)?;
        m.add_function(wrap_pyfunction!(cache_contains, m)?)?;
        m.add_function(wrap_pyfunction!(cache_clear, m)?)?;
        m.add_function(wrap_pyfunction!(cache_stats, m)?)?;
        m.add_function(wrap_pyfunction!(compute_hash, m)?)?;
        m.add_function(wrap_pyfunction!(get_cache_info, m)?)?;
        m.add_function(wrap_pyfunction!(is_language_supported_py, m)?)?;
        m.add_function(wrap_pyfunction!(get_language_py, m)?)?;
        m.add_function(wrap_pyfunction!(supported_languages, m)?)?;
        m.add_function(wrap_pyfunction!(extract_symbols_py, m)?)?;
        m.add_function(wrap_pyfunction!(extract_symbols_from_file_py, m)?)?;
        m.add_class::<InputEdit>()?;
        m.add("__version__", env!("CARGO_PKG_VERSION"))?;
        m.add("DEFAULT_CACHE_CAPACITY", DEFAULT_CACHE_CAPACITY)?;
        Ok(())
    }
}

// Re-export python module when feature is enabled
#[cfg(feature = "python")]
pub use python::*;
