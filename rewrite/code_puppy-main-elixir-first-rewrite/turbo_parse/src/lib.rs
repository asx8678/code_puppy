//! turbo_parse - High-performance parsing with tree-sitter and PyO3 bindings
//!
//! This crate provides Python bindings for the core parsing functionality
//! found in turbo_parse_core.

use pyo3::prelude::*;

// Re-export all core modules for Rust users
pub use turbo_parse_core::{
    // Core modules
    diagnostics, folds, highlights, parser, queries, registry, symbols, types,
    // Main functions
    extract_diagnostics, extract_symbols, extract_symbols_from_file,
    get_folds, get_folds_from_file, get_highlights, get_highlights_from_file,
    get_language, is_language_supported, list_supported_languages,
    normalize_language, parse_file, parse_source,
    // Types
    Diagnostic, FoldRange, FoldResult, FoldType, HighlightCapture, HighlightResult,
    ParseError, ParseResult, QueryError, QueryType, RegistryError, Symbol, SymbolOutline,
    Severity, SyntaxDiagnostics,
};

// Re-export types from core with their original module paths
// This preserves backwards compatibility for Rust users

/// Python bindings for turbo_parse
#[pymodule]
fn turbo_parse(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Core parsing functions
    m.add_function(wrap_pyfunction!(py_parse_source, m)?)?;
    m.add_function(wrap_pyfunction!(py_parse_file, m)?)?;
    
    // Symbol extraction
    m.add_function(wrap_pyfunction!(py_extract_symbols, m)?)?;
    m.add_function(wrap_pyfunction!(py_extract_symbols_from_file, m)?)?;
    
    // Diagnostics
    m.add_function(wrap_pyfunction!(py_extract_syntax_diagnostics, m)?)?;
    
    // Folds
    m.add_function(wrap_pyfunction!(py_get_folds, m)?)?;
    m.add_function(wrap_pyfunction!(py_get_folds_from_file, m)?)?;
    
    // Highlights
    m.add_function(wrap_pyfunction!(py_get_highlights, m)?)?;
    m.add_function(wrap_pyfunction!(py_get_highlights_from_file, m)?)?;
    
    // Registry
    m.add_function(wrap_pyfunction!(py_is_language_supported, m)?)?;
    m.add_function(wrap_pyfunction!(py_supported_languages, m)?)?;
    
    Ok(())
}

/// Parse source code directly.
#[pyfunction]
#[pyo3(signature = (source, language))]
fn py_parse_source<'py>(py: Python<'py>, source: &str, language: &str) -> PyResult<Bound<'py, PyAny>> {
    let result = parse_source(source, language);
    convert_to_py_dict(py, &result)
}

/// Parse a file from disk.
#[pyfunction]
#[pyo3(signature = (path, language = None))]
fn py_parse_file<'py>(py: Python<'py>, path: &str, language: Option<&str>) -> PyResult<Bound<'py, PyAny>> {
    let result = parse_file(path, language);
    convert_to_py_dict(py, &result)
}

/// Extract symbols from source code.
#[pyfunction]
#[pyo3(signature = (source, language))]
fn py_extract_symbols<'py>(py: Python<'py>, source: &str, language: &str) -> PyResult<Bound<'py, PyAny>> {
    let result = extract_symbols(source, language);
    convert_to_py_dict(py, &result)
}

/// Extract symbols from a file.
#[pyfunction]
#[pyo3(signature = (path, language = None))]
fn py_extract_symbols_from_file<'py>(py: Python<'py>, path: &str, language: Option<&str>) -> PyResult<Bound<'py, PyAny>> {
    let result = extract_symbols_from_file(path, language);
    convert_to_py_dict(py, &result)
}

/// Extract syntax diagnostics from source code.
#[pyfunction]
#[pyo3(signature = (source, language))]
fn py_extract_syntax_diagnostics<'py>(py: Python<'py>, source: &str, language: &str) -> PyResult<Bound<'py, PyAny>> {
    let ts_language = match get_language(language) {
        Ok(lang) => lang,
        Err(_) => {
            let error_result = serde_json::json!({
                "diagnostics": [],
                "error_count": 0,
                "warning_count": 0,
                "error": format!("Unsupported language: '{}'", language),
            });
            return convert_json_to_py(py, &error_result);
        }
    };

    let diagnostics = extract_diagnostics(source, &ts_language);
    
    let result = serde_json::json!({
        "diagnostics": diagnostics.diagnostics,
        "error_count": diagnostics.error_count(),
        "warning_count": diagnostics.warning_count(),
    });
    
    convert_json_to_py(py, &result)
}

/// Get fold ranges.
#[pyfunction]
#[pyo3(signature = (source, language))]
fn py_get_folds<'py>(py: Python<'py>, source: &str, language: &str) -> PyResult<Bound<'py, PyAny>> {
    let result = get_folds(source, language);
    convert_to_py_dict(py, &result)
}

/// Get fold ranges from a file.
#[pyfunction]
#[pyo3(signature = (path, language = None))]
fn py_get_folds_from_file<'py>(py: Python<'py>, path: &str, language: Option<&str>) -> PyResult<Bound<'py, PyAny>> {
    let result = get_folds_from_file(path, language);
    convert_to_py_dict(py, &result)
}

/// Get syntax highlights.
#[pyfunction]
#[pyo3(signature = (source, language))]
fn py_get_highlights<'py>(py: Python<'py>, source: &str, language: &str) -> PyResult<Bound<'py, PyAny>> {
    let result = get_highlights(source, language);
    convert_to_py_dict(py, &result)
}

/// Get syntax highlights from a file.
#[pyfunction]
#[pyo3(signature = (path, language = None))]
fn py_get_highlights_from_file<'py>(py: Python<'py>, path: &str, language: Option<&str>) -> PyResult<Bound<'py, PyAny>> {
    let result = get_highlights_from_file(path, language);
    convert_to_py_dict(py, &result)
}

/// Check if a language is supported.
#[pyfunction]
fn py_is_language_supported(language: &str) -> bool {
    is_language_supported(language)
}

/// Get list of supported languages.
#[pyfunction]
fn py_supported_languages() -> Vec<String> {
    list_supported_languages()
}

/// Helper to convert a serializable value to a Python dict via JSON.
fn convert_to_py_dict<'py, T: serde::Serialize>(py: Python<'py>, value: &T) -> PyResult<Bound<'py, PyAny>> {
    let json_str = serde_json::to_string(value)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e)))?;

    let json_module = py.import("json")?;
    let py_dict = json_module.call_method1("loads", (json_str,))?;
    Ok(py_dict)
}

/// Helper to convert a JSON value to a Python dict.
fn convert_json_to_py<'py>(py: Python<'py>, value: &serde_json::Value) -> PyResult<Bound<'py, PyAny>> {
    let json_str = serde_json::to_string(value)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e)))?;

    let json_module = py.import("json")?;
    let py_dict = json_module.call_method1("loads", (json_str,))?;
    Ok(py_dict)
}
