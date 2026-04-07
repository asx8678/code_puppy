use pyo3::prelude::*;
use std::sync::OnceLock;

mod cache;

use cache::{ParseCache, CacheKey, CacheValue, compute_content_hash, DEFAULT_CACHE_CAPACITY};

/// Global singleton cache instance
static GLOBAL_CACHE: OnceLock<ParseCache> = OnceLock::new();

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

/// Check if the turbo_parse module is available and healthy.
///
/// Returns a dict with module info including:
///   available: always true (if this function is callable)
///   version: crate version
///   cache_available: whether the cache is initialized
#[pyfunction]
fn health_check<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
    let cache_initialized = GLOBAL_CACHE.get().is_some();
    
    let info = serde_json::json!({
        "available": true,
        "version": env!("CARGO_PKG_VERSION"),
        "cache_available": cache_initialized,
    });

    let json_str = serde_json::to_string(&info)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e)))?;

    let json_module = py.import("json")?;
    let py_dict = json_module.call_method1("loads", (json_str,))?;
    Ok(py_dict)
}

/// The turbo_parse Python module.
#[pymodule]
fn turbo_parse(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(health_check, m)?)?;
    m.add_function(wrap_pyfunction!(init_cache, m)?)?;
    m.add_function(wrap_pyfunction!(cache_get, m)?)?;
    m.add_function(wrap_pyfunction!(cache_put, m)?)?;
    m.add_function(wrap_pyfunction!(cache_clear, m)?)?;
    m.add_function(wrap_pyfunction!(cache_stats, m)?)?;
    m.add_function(wrap_pyfunction!(compute_hash, m)?)?;
    m.add_function(wrap_pyfunction!(get_cache_info, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add("DEFAULT_CACHE_CAPACITY", DEFAULT_CACHE_CAPACITY)?;
    Ok(())
}
