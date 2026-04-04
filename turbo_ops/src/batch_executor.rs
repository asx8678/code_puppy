//! Batch orchestration for turbo_ops.
//!
//! Provides parallel execution of file operations using rayon.
//! Operations are executed in priority order within their parallel groups.

use crate::models::{BatchResult, OperationResult, TurboOperation};
use crate::operations::{execute_grep, execute_list_files, execute_read_files};
use rayon::prelude::*;
use std::time::Instant;

/// Execute a single operation and return its result
pub fn execute_single_operation(op: &TurboOperation) -> OperationResult {
    let start = Instant::now();
    let op_type_str = match op.op_type {
        crate::models::OperationType::ListFiles => "list_files",
        crate::models::OperationType::Grep => "grep",
        crate::models::OperationType::ReadFiles => "read_files",
    };

    let result = match op.op_type {
        crate::models::OperationType::ListFiles => execute_list_files(&op.args),
        crate::models::OperationType::Grep => execute_grep(&op.args),
        crate::models::OperationType::ReadFiles => execute_read_files(&op.args),
    };

    let duration_ms = start.elapsed().as_secs_f64() * 1000.0;

    match result {
        Ok(data) => OperationResult::success(op.id.clone(), op_type_str, data, duration_ms),
        Err(err) => OperationResult::error(op.id.clone(), op_type_str, err, duration_ms),
    }
}

/// Execute a batch of operations sequentially
///
/// Operations are executed in order, respecting their priorities.
/// Lower priority values execute first.
pub fn execute_batch_sequential(operations: &[TurboOperation]) -> Vec<OperationResult> {
    // Sort by priority
    let mut sorted_ops: Vec<_> = operations.iter().collect();
    sorted_ops.sort_by_key(|op| op.priority);

    sorted_ops
        .iter()
        .map(|op| execute_single_operation(op))
        .collect()
}

/// Execute a batch of operations in parallel
///
/// All operations are executed in parallel using rayon.
/// Results maintain the same order as the input operations.
pub fn execute_batch_parallel(operations: &[TurboOperation]) -> Vec<OperationResult> {
    if operations.is_empty() {
        return Vec::new();
    }

    // For parallel execution, we don't sort - we execute everything at once
    // This is appropriate when operations are independent
    operations
        .par_iter()
        .map(execute_single_operation)
        .collect()
}

/// Execute a batch of operations with smart grouping
///
/// Operations are grouped by priority levels and executed in order:
/// - Within each priority group, operations run in parallel
/// - Between groups, execution is sequential (lower priorities first)
///
/// This balances parallelism with dependency ordering.
pub fn execute_batch_grouped(operations: &[TurboOperation]) -> Vec<OperationResult> {
    if operations.is_empty() {
        return Vec::new();
    }

    // Group operations by priority
    use std::collections::BTreeMap;
    let mut groups: BTreeMap<u32, Vec<(usize, &TurboOperation)>> = BTreeMap::new();

    for (idx, op) in operations.iter().enumerate() {
        groups.entry(op.priority).or_default().push((idx, op));
    }

    // Pre-allocate results vector with correct size
    let mut results: Vec<Option<OperationResult>> = vec![None; operations.len()];

    // Execute groups in priority order
    for (_priority, group) in groups {
        // Execute this priority group in parallel
        let group_results: Vec<(usize, OperationResult)> = group
            .par_iter()
            .map(|(idx, op)| (*idx, execute_single_operation(op)))
            .collect();

        // Place results in correct positions
        for (idx, result) in group_results {
            results[idx] = Some(result);
        }
    }

    // Unwrap all results (they should all be Some at this point)
    results.into_iter().flatten().collect()
}

/// Execute a batch of operations and return a complete BatchResult
///
/// # Arguments
/// * `operations` - Vector of operations to execute
/// * `parallel` - If true, use parallel execution; otherwise sequential
///
/// # Returns
/// A BatchResult containing all operation results and metadata
pub fn batch_execute(
    operations: Vec<TurboOperation>,
    parallel: bool,
) -> BatchResult {
    let started_at = chrono::Utc::now().to_rfc3339();
    let start = Instant::now();

    let results = if parallel {
        execute_batch_parallel(&operations)
    } else {
        execute_batch_sequential(&operations)
    };

    let total_duration_ms = start.elapsed().as_secs_f64() * 1000.0;

    BatchResult::from_results(results, total_duration_ms, started_at)
}

/// Execute a batch of operations with priority grouping
///
/// This provides the best balance: operations at the same priority
/// run in parallel, but lower priorities complete before higher ones.
pub fn batch_execute_grouped(operations: Vec<TurboOperation>) -> BatchResult {
    let started_at = chrono::Utc::now().to_rfc3339();
    let start = Instant::now();

    let results = execute_batch_grouped(&operations);
    let total_duration_ms = start.elapsed().as_secs_f64() * 1000.0;

    BatchResult::from_results(results, total_duration_ms, started_at)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::OperationType;

    #[test]
    fn test_empty_batch() {
        let ops: Vec<TurboOperation> = vec![];
        let result = batch_execute(ops, false);
        assert_eq!(result.total_count, 0);
        assert_eq!(result.success_count, 0);
        assert_eq!(result.error_count, 0);
    }

    #[test]
    fn test_sequential_execution() {
        let ops = vec![
            TurboOperation::list_files(".", false).with_id("op1".to_string()),
            TurboOperation::list_files(".", false).with_id("op2".to_string()),
        ];
        let result = batch_execute(ops, false);
        assert_eq!(result.total_count, 2);
        assert_eq!(result.success_count, 2);
        assert_eq!(result.error_count, 0);
        assert_eq!(result.results.len(), 2);
    }

    #[test]
    fn test_parallel_execution() {
        let ops = vec![
            TurboOperation::list_files(".", false).with_id("op1".to_string()),
            TurboOperation::list_files(".", false).with_id("op2".to_string()),
        ];
        let result = batch_execute(ops, true);
        assert_eq!(result.total_count, 2);
        assert_eq!(result.success_count, 2);
        assert_eq!(result.error_count, 0);
    }

    #[test]
    fn test_priority_ordering() {
        // Create operations with different priorities
        let ops = vec![
            TurboOperation::list_files(".", false)
                .with_id("third".to_string())
                .with_priority(300),
            TurboOperation::list_files(".", false)
                .with_id("first".to_string())
                .with_priority(100),
            TurboOperation::list_files(".", false)
                .with_id("second".to_string())
                .with_priority(200),
        ];

        let results = execute_batch_sequential(&ops);
        
        // Check that results are in priority order
        assert_eq!(results[0].operation_id, Some("first".to_string()));
        assert_eq!(results[1].operation_id, Some("second".to_string()));
        assert_eq!(results[2].operation_id, Some("third".to_string()));
    }

    #[test]
    fn test_error_handling() {
        // Create an operation that will fail
        let ops = vec![
            TurboOperation {
                op_type: OperationType::ListFiles,
                args: serde_json::json!({
                    "directory": "/nonexistent/path/that/does/not/exist",
                    "recursive": false
                }),
                id: Some("failing".to_string()),
                priority: 100,
            },
        ];

        let result = batch_execute(ops, false);
        assert_eq!(result.total_count, 1);
        assert_eq!(result.success_count, 0);
        assert_eq!(result.error_count, 1);
        assert_eq!(result.status, "failed");
    }

    #[test]
    fn test_mixed_success_failure() {
        let ops = vec![
            TurboOperation::list_files(".", false)
                .with_id("success".to_string()),
            TurboOperation {
                op_type: OperationType::ListFiles,
                args: serde_json::json!({
                    "directory": "/nonexistent/path",
                    "recursive": false
                }),
                id: Some("failure".to_string()),
                priority: 100,
            },
        ];

        let result = batch_execute(ops, false);
        assert_eq!(result.total_count, 2);
        assert_eq!(result.success_count, 1);
        assert_eq!(result.error_count, 1);
        assert_eq!(result.status, "partial");
    }

    #[test]
    fn test_batch_result_from_results() {
        let results = vec![
            OperationResult::success(
                Some("op1".to_string()),
                "list_files",
                serde_json::json!({"files": []}),
                1.0,
            ),
            OperationResult::error(
                Some("op2".to_string()),
                "grep",
                "Pattern not found".to_string(),
                0.5,
            ),
        ];

        let batch = BatchResult::from_results(results, 1.5, chrono::Utc::now().to_rfc3339());
        assert_eq!(batch.total_count, 2);
        assert_eq!(batch.success_count, 1);
        assert_eq!(batch.error_count, 1);
        assert_eq!(batch.status, "partial");
    }
}
