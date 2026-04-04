//! Turbo Ops — High-performance batch file operations with PyO3 bindings.
//!
//! This crate provides Rust-native implementations of common file operations
//! (list_files, grep, read_files) with batch orchestration and parallel execution.
//!
//! # Python Usage (Synchronous)
//!
//! ```python
//! import turbo_ops
//! import json
//!
//! # Create operations
//! ops = [
//!     {"type": "list_files", "args": {"directory": ".", "recursive": True}, "id": "op1"},
//!     {"type": "grep", "args": {"search_string": "def ", "directory": "."}, "id": "op2"},
//! ]
//!
//! # Execute batch (parallel by default)
//! result = turbo_ops.batch_execute_ops(ops)
//! print(json.dumps(result, indent=2))
//! ```
//!
//! # Python Usage (Async)
//!
//! ```python
//! import turbo_ops
//! import asyncio
//!
//! async def main():
//!     ops = [
//!         {"type": "list_files", "args": {"directory": ".", "recursive": True}, "id": "op1"},
//!         {"type": "grep", "args": {"search_string": "def ", "directory": "."}, "id": "op2"},
//!     ]
//!
//!     # Execute batch asynchronously
//!     result = await turbo_ops.async_batch_execute_ops(ops)
//!     print(result)  # Already a dict, no json.loads needed!
//!
//! asyncio.run(main())
//! ```

use pyo3::prelude::*;
use pyo3::types::PyDict;

mod async_batch_executor;
mod batch_executor;
mod models;
mod operations;

use async_batch_executor::execute_async_batch;
use batch_executor::{batch_execute, batch_execute_grouped};
use models::{BatchResult, TurboOperation};

/// Execute a batch of file operations asynchronously.
///
/// This is an async version of `batch_execute_ops` that returns a Python
/// awaitable (coroutine). It uses Tokio for async execution and Rayon for
/// parallel CPU work within the async runtime.
///
/// # Arguments
/// * `operations` - List of operation dicts with keys:
///   - type: "list_files", "grep", or "read_files"
///   - args: operation-specific arguments
///   - id (optional): operation identifier
///   - priority (optional): execution priority (lower = earlier, default 100)
///
/// # Returns
/// A Python coroutine that, when awaited, returns a dict with batch execution results:
/// - status: "completed", "partial", or "failed"
/// - success_count, error_count, total_count
/// - results: list of individual operation results
/// - total_duration_ms
/// - started_at, completed_at (ISO 8601 timestamps)
///
/// # Python Usage
/// ```python
/// import turbo_ops
/// import asyncio
///
/// ops = [
///     {"type": "list_files", "args": {"directory": ".", "recursive": True}, "id": "op1"},
///     {"type": "grep", "args": {"search_string": "def ", "directory": "."}, "id": "op2"},
/// ]
///
/// # Execute batch asynchronously
/// result = await turbo_ops.async_batch_execute_ops(ops)
/// ```
#[pyfunction]
fn async_batch_execute_ops<'py>(
    py: Python<'py>,
    operations: Vec<Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyAny>> {
    // Convert Python dicts to TurboOperation structs
    let ops: Vec<TurboOperation> = operations
        .iter()
        .map(|obj| convert_py_op_to_rust(py, obj))
        .collect::<PyResult<Vec<_>>>()?;

    // Use pyo3_async_runtimes to convert Rust future to Python coroutine
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        // Execute the batch asynchronously
        let async_result = execute_async_batch(ops).await;
        
        // Serialize the batch result to JSON string
        let json_str = serde_json::to_string(&async_result.batch_result)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e)))?;
        
        // Use Python::attach to access Python's GIL and convert to dict
        let py_obj = Python::attach(|py| {
            let json_module = py.import("json")?;
            let py_dict = json_module.call_method1("loads", (json_str,))?;
            Ok::<_, PyErr>(py_dict.unbind())
        }).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Python conversion error: {}", e)))?;
        
        Ok(py_obj)
    })
}

/// Execute a batch of file operations.
///
/// This is the main entry point for Python. Accepts a list of operations
/// and executes them in parallel using rayon.
///
/// # Arguments
/// * `operations` - List of operation dicts with keys:
///   - type: "list_files", "grep", or "read_files"
///   - args: operation-specific arguments
///   - id (optional): operation identifier
///   - priority (optional): execution priority (lower = earlier, default 100)
/// * `parallel` - If true (default), execute operations in parallel.
///   If false, execute sequentially.
///
/// # Returns
/// Dict with batch execution results including:
/// - status: "completed", "partial", or "failed"
/// - success_count, error_count, total_count
/// - results: list of individual operation results
/// - total_duration_ms
/// - started_at, completed_at (ISO 8601 timestamps)
#[pyfunction]
#[pyo3(signature = (operations, parallel = true))]
fn batch_execute_ops<'py>(
    py: Python<'py>,
    operations: Vec<Bound<'py, PyAny>>,
    parallel: bool,
) -> PyResult<Bound<'py, PyAny>> {
    // Convert Python dicts to TurboOperation structs
    let ops: Vec<TurboOperation> = operations
        .iter()
        .map(|obj| convert_py_op_to_rust(py, obj))
        .collect::<PyResult<Vec<_>>>()?;

    // Execute batch
    let result = batch_execute(ops, parallel);

    // Convert result back to Python dict
    convert_batch_result_to_py(py, &result)
}

/// Execute a batch of file operations with priority-based grouping.
///
/// Operations are grouped by priority level. Within each priority group,
/// operations run in parallel. Between groups, execution is sequential
/// (lower priorities complete before higher ones).
///
/// This provides the best balance of parallelism and ordering.
#[pyfunction]
#[pyo3(signature = (operations))]
fn batch_execute_grouped_ops<'py>(
    py: Python<'py>,
    operations: Vec<Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyAny>> {
    let ops: Vec<TurboOperation> = operations
        .iter()
        .map(|obj| convert_py_op_to_rust(py, obj))
        .collect::<PyResult<Vec<_>>>()?;

    let result = batch_execute_grouped(ops);

    convert_batch_result_to_py(py, &result)
}

/// Execute a single list_files operation.
///
/// Args:
///   directory: Path to directory (default: ".")
///   recursive: Whether to list recursively (default: true)
///
/// Returns dict with:
///   files: list of file info dicts
///   total_count: number of files
///   directory: the directory path
///   recursive: whether listing was recursive
#[pyfunction]
#[pyo3(signature = (directory = ".", recursive = true))]
fn list_files<'py>(py: Python<'py>, directory: &str, recursive: bool) -> PyResult<Bound<'py, PyAny>> {
    let args = serde_json::json!({
        "directory": directory,
        "recursive": recursive
    });

    match operations::execute_list_files(&args) {
        Ok(data) => convert_json_to_py(py, &data),
        Err(e) => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e)),
    }
}

/// Execute a single grep operation.
///
/// Args:
///   search_string: Pattern to search for (supports (?i) for case-insensitive)
///   directory: Directory to search in (default: ".")
///
/// Returns dict with:
///   matches: list of match dicts with file_path, line_number, line_content
///   total_matches: number of matches found
///   search_string: the search pattern
///   directory: the directory searched
#[pyfunction]
#[pyo3(signature = (search_string, directory = "."))]
fn grep<'py>(py: Python<'py>, search_string: &str, directory: &str) -> PyResult<Bound<'py, PyAny>> {
    let args = serde_json::json!({
        "search_string": search_string,
        "directory": directory
    });

    match operations::execute_grep(&args) {
        Ok(data) => convert_json_to_py(py, &data),
        Err(e) => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e)),
    }
}

/// Execute a single read_files operation.
///
/// Args:
///   file_paths: List of file paths to read
///   start_line: Optional starting line number (1-indexed)
///   num_lines: Optional number of lines to read
///
/// Returns dict with:
///   files: list of file read results
///   total_files: number of files attempted
///   successful_reads: number of successfully read files
#[pyfunction]
#[pyo3(signature = (file_paths, start_line = None, num_lines = None))]
fn read_files<'py>(
    py: Python<'py>,
    file_paths: Vec<String>,
    start_line: Option<usize>,
    num_lines: Option<usize>,
) -> PyResult<Bound<'py, PyAny>> {
    let args = serde_json::json!({
        "file_paths": file_paths,
        "start_line": start_line,
        "num_lines": num_lines
    });

    match operations::execute_read_files(&args) {
        Ok(data) => convert_json_to_py(py, &data),
        Err(e) => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e)),
    }
}

/// Check if the turbo_ops module is available and healthy.
///
/// Returns a dict with module info including:
///   available: always true (if this function is callable)
///   version: crate version
///   rayon_threads: number of rayon worker threads
#[pyfunction]
fn health_check<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
    let pool = rayon::ThreadPoolBuilder::new().build();
    let num_threads = pool.as_ref().map(|p| p.current_num_threads()).unwrap_or(1);

    let info = serde_json::json!({
        "available": true,
        "version": env!("CARGO_PKG_VERSION"),
        "rayon_threads": num_threads,
    });

    convert_json_to_py(py, &info)
}

// Helper functions for Python conversion

fn convert_py_op_to_rust(py: Python, obj: &Bound<'_, PyAny>) -> PyResult<TurboOperation> {
    // Try to extract as a dict
    let dict = obj.cast::<PyDict>()?;

    // Get operation type
    let type_obj = dict.get_item("type")?.ok_or_else(|| {
        PyErr::new::<pyo3::exceptions::PyValueError, _>("Operation must have a 'type' field")
    })?;
    let op_type_str: String = type_obj.extract()?;
    let op_type = match op_type_str.as_str() {
        "list_files" => models::OperationType::ListFiles,
        "grep" => models::OperationType::Grep,
        "read_files" => models::OperationType::ReadFiles,
        _ => {
            return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                "Unknown operation type: {}",
                op_type_str
            )))
        }
    };

    // Get args (required)
    let args_obj = dict.get_item("args")?.ok_or_else(|| {
        PyErr::new::<pyo3::exceptions::PyValueError, _>("Operation must have an 'args' field")
    })?;
    let args_json: String = py.import("json")?.call_method1("dumps", (args_obj,))?.extract()?;
    let args: serde_json::Value = serde_json::from_str(&args_json)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("Invalid args: {}", e)))?;

    // Get optional id
    let id = dict
        .get_item("id")?
        .and_then(|obj| obj.extract::<String>().ok());

    // Get optional priority (default 100)
    let priority = dict
        .get_item("priority")?
        .and_then(|obj| obj.extract::<u32>().ok())
        .unwrap_or(100);

    Ok(TurboOperation {
        op_type,
        args,
        id,
        priority,
    })
}

fn convert_batch_result_to_py<'py>(py: Python<'py>, result: &BatchResult) -> PyResult<Bound<'py, PyAny>> {
    let json_str = serde_json::to_string(result)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e)))?;

    let json_module = py.import("json")?;
    let py_dict = json_module.call_method1("loads", (json_str,))?;
    Ok(py_dict)
}

fn convert_json_to_py<'py>(py: Python<'py>, value: &serde_json::Value) -> PyResult<Bound<'py, PyAny>> {
    let json_str = serde_json::to_string(value)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e)))?;

    let json_module = py.import("json")?;
    let py_dict = json_module.call_method1("loads", (json_str,))?;
    Ok(py_dict)
}

/// The turbo_ops Python module.
#[pymodule]
fn turbo_ops(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(async_batch_execute_ops, m)?)?;
    m.add_function(wrap_pyfunction!(batch_execute_ops, m)?)?;
    m.add_function(wrap_pyfunction!(batch_execute_grouped_ops, m)?)?;
    m.add_function(wrap_pyfunction!(list_files, m)?)?;
    m.add_function(wrap_pyfunction!(grep, m)?)?;
    m.add_function(wrap_pyfunction!(read_files, m)?)?;
    m.add_function(wrap_pyfunction!(health_check, m)?)?;

    // Add version info
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_turbo_operation_creation() {
        let op = TurboOperation::list_files("/tmp", true);
        assert!(matches!(op.op_type, models::OperationType::ListFiles));
        assert_eq!(op.id, None);
        assert_eq!(op.priority, 100);
    }

    #[test]
    fn test_turbo_operation_with_id_and_priority() {
        let op = TurboOperation::grep("pattern", "/tmp")
            .with_id("my-op".to_string())
            .with_priority(50);

        assert_eq!(op.id, Some("my-op".to_string()));
        assert_eq!(op.priority, 50);
    }

    #[test]
    fn test_turbo_operation_read_files() {
        let paths = vec!["file1.txt".to_string(), "file2.txt".to_string()];
        let op = TurboOperation::read_files(paths.clone(), Some(10), Some(5));

        assert!(matches!(op.op_type, models::OperationType::ReadFiles));
        assert_eq!(op.args["file_paths"], serde_json::json!(paths));
        assert_eq!(op.args["start_line"], serde_json::json!(10));
        assert_eq!(op.args["num_lines"], serde_json::json!(5));
    }
}
