use pyo3::prelude::*;

mod registry;

use registry::{get_language as _get_language, is_language_supported as _is_language_supported, list_supported_languages, RegistryError};

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
#[pyfunction]
fn health_check<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
    let info = serde_json::json!({
        "available": true,
        "version": env!("CARGO_PKG_VERSION"),
    });

    let json_str = serde_json::to_string(&info)
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

/// The turbo_parse Python module.
#[pymodule]
fn turbo_parse(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(health_check, m)?)?;
    m.add_function(wrap_pyfunction!(is_language_supported, m)?)?;
    m.add_function(wrap_pyfunction!(get_language, m)?)?;
    m.add_function(wrap_pyfunction!(supported_languages, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
