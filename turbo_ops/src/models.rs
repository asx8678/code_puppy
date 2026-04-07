//! Data models for turbo_ops batch file operations.
//!
//! Defines the core types used across the crate:
//! - TurboOperation: Enum representing any file operation
//! - OperationResult: Result of a single operation execution
//! - BatchResult: Aggregated results from batch execution

use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

/// Types of file operations supported by turbo_ops
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum OperationType {
    #[serde(rename = "list_files")]
    ListFiles,
    #[serde(rename = "grep")]
    Grep,
    #[serde(rename = "read_files")]
    ReadFiles,
}

impl<'source, 'py> FromPyObject<'source, 'py> for OperationType {
    type Error = PyErr;

    fn extract(obj: pyo3::Borrowed<'source, 'py, PyAny>) -> PyResult<Self> {
        let s: String = obj.extract()?;
        match s.as_str() {
            "list_files" => Ok(OperationType::ListFiles),
            "grep" => Ok(OperationType::Grep),
            "read_files" => Ok(OperationType::ReadFiles),
            _ => Err(pyo3::exceptions::PyValueError::new_err(format!(
                "Unknown operation type: {}",
                s
            ))),
        }
    }
}

/// A single file operation to execute
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TurboOperation {
    /// Type of operation
    #[serde(rename = "type")]
    pub op_type: OperationType,
    /// Operation-specific arguments
    pub args: serde_json::Value,
    /// Optional operation ID for tracking
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    /// Execution priority (lower = earlier, default 100)
    #[serde(default = "default_priority")]
    pub priority: u32,
}

fn default_priority() -> u32 {
    100
}

/// Result of executing a single operation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OperationResult {
    /// Operation ID (if provided)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub operation_id: Option<String>,
    /// Operation type
    pub operation_type: String,
    /// Success or error status
    pub status: String,
    /// Result data (operation-specific)
    pub data: serde_json::Value,
    /// Error message if failed
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    /// Execution duration in milliseconds
    pub duration_ms: f64,
}

impl OperationResult {
    /// Create a successful result
    pub fn success(id: Option<String>, op_type: &str, data: serde_json::Value, duration_ms: f64) -> Self {
        Self {
            operation_id: id,
            operation_type: op_type.to_string(),
            status: "success".to_string(),
            data,
            error: None,
            duration_ms,
        }
    }

    /// Create an error result
    pub fn error(id: Option<String>, op_type: &str, error_msg: String, duration_ms: f64) -> Self {
        Self {
            operation_id: id,
            operation_type: op_type.to_string(),
            status: "error".to_string(),
            data: serde_json::Value::Null,
            error: Some(error_msg),
            duration_ms,
        }
    }

    /// Check if the operation succeeded
    pub fn is_success(&self) -> bool {
        self.status == "success"
    }
}

/// Aggregated result from batch execution
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BatchResult {
    /// Overall status: "completed", "partial", or "failed"
    pub status: String,
    /// Number of successful operations
    pub success_count: usize,
    /// Number of failed operations
    pub error_count: usize,
    /// Total number of operations
    pub total_count: usize,
    /// Individual operation results
    pub results: Vec<OperationResult>,
    /// Total execution duration in milliseconds
    pub total_duration_ms: f64,
    /// Timestamp when execution started (ISO 8601)
    pub started_at: String,
    /// Timestamp when execution completed (ISO 8601)
    pub completed_at: String,
}

impl BatchResult {
    /// Create a new BatchResult from operation results
    pub fn from_results(results: Vec<OperationResult>, total_duration_ms: f64, started_at: String) -> Self {
        let success_count = results.iter().filter(|r| r.is_success()).count();
        let error_count = results.len() - success_count;
        let status = if error_count == 0 {
            "completed"
        } else if success_count > 0 {
            "partial"
        } else {
            "failed"
        };

        Self {
            status: status.to_string(),
            success_count,
            error_count,
            total_count: results.len(),
            results,
            total_duration_ms,
            started_at,
            completed_at: chrono::Utc::now().to_rfc3339(),
        }
    }
}

/// File information for list_files results
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileInfo {
    pub path: String,
    pub name: String,
    pub is_dir: bool,
    pub size: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub modified: Option<String>,
}

/// Match information for grep results
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GrepMatch {
    pub file_path: String,
    pub line_number: usize,
    pub line_content: String,
}

/// File read result for read_files
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileReadResult {
    pub file_path: String,
    pub content: Option<String>,
    pub num_tokens: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    pub success: bool,
}

/// Calculate token count using the same logic as Code Puppy
pub fn estimate_tokens(text: &str) -> usize {
    std::cmp::max(1, (text.len() as f64 / 2.5).floor() as usize)
}
