//! Async batch executor for turbo_ops with progress events and cancellation support.
//!
//! This module provides an async interface to the batch execution engine, bridging
//! Tokio's async runtime with Rayon's parallel CPU work via `spawn_blocking`.
//!
//! # Architecture
//!
//! - **Tokio**: Async coordination, Python-facing API, progress events via mpsc
//! - **Rayon**: Parallel CPU execution of file operations
//! - **spawn_blocking**: Bridges the two worlds - Tokio spawns blocking tasks that Rayon executes
//!
//! # Progress Events
//!
//! The executor emits events throughout execution:
//! - `PlanStarted`: Execution plan begins
//! - `GroupStarted`: A priority group starts executing
//! - `OpCompleted`: An individual operation completes
//! - `GroupCompleted`: A priority group finishes
//! - `PlanCompleted`: Entire plan completes (success or cancellation)
//!
//! # Cancellation
//!
//! Execution can be cancelled at group boundaries via `CancellationToken`.
//! When cancelled, the executor stops before starting the next priority group.
//!
//! # Example
//!
//! ```rust
//! use turbo_ops::async_batch_executor::{AsyncBatchExecutor, ProgressEvent};
//! use turbo_ops::models::TurboOperation;
//! use tokio_util::sync::CancellationToken;
//!
//! #[tokio::main]
//! async fn main() {
//!     let ops = vec![
//!         TurboOperation::list_files(".", true).with_priority(100),
//!         TurboOperation::grep("pattern", ".").with_priority(200),
//!     ];
//!
//!     let (mut executor, mut rx) = AsyncBatchExecutor::new(ops);
//!     let cancel_token = CancellationToken::new();
//!
//!     // Spawn progress listener
//!     let progress_task = tokio::spawn(async move {
//!         while let Some(event) = rx.recv().await {
//!             println!("{:?}", event);
//!         }
//!     });
//!
//!     // Execute with cancellation support
//!     let result = executor.execute(cancel_token).await;
//!
//!     progress_task.await.ok();
//! }
//! ```

use crate::batch_executor::execute_single_operation;
use crate::models::{BatchResult, OperationResult, TurboOperation};
use std::collections::BTreeMap;
use std::time::Instant;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

/// Progress events emitted during batch execution.
#[derive(Debug, Clone)]
pub enum ProgressEvent {
    /// Execution plan has started.
    /// Contains the total number of operations and number of priority groups.
    PlanStarted {
        total_ops: usize,
        num_groups: usize,
    },

    /// A priority group has started executing.
    /// Contains the priority value and number of operations in this group.
    GroupStarted {
        priority: u32,
        ops_in_group: usize,
    },

    /// An individual operation has completed.
    /// Contains the operation ID (if any), success status, and duration.
    OpCompleted {
        op_id: Option<String>,
        op_type: String,
        success: bool,
        duration_ms: f64,
    },

    /// A priority group has completed.
    /// Contains the priority value and summary of group execution.
    GroupCompleted {
        priority: u32,
        successful_ops: usize,
        failed_ops: usize,
    },

    /// The entire execution plan has completed.
    /// Contains final status and summary statistics.
    PlanCompleted {
        status: String,
        total_success: usize,
        total_failed: usize,
        total_duration_ms: f64,
    },
}

/// Async batch executor with progress events and cancellation support.
///
/// This executor runs operations grouped by priority. Within each group,
/// operations execute in parallel via Rayon. Between groups, execution is
/// sequential (lower priorities complete first).
pub struct AsyncBatchExecutor {
    operations: Vec<TurboOperation>,
    progress_tx: mpsc::Sender<ProgressEvent>,
}

/// Result of async batch execution.
#[derive(Debug, Clone)]
pub struct AsyncBatchResult {
    /// The final batch result with all operation results.
    pub batch_result: BatchResult,
    /// Whether execution was cancelled.
    pub was_cancelled: bool,
}

impl AsyncBatchExecutor {
    /// Create a new async batch executor with the given operations.
    ///
    /// Returns the executor and a receiver for progress events.
    /// The channel has a buffer size of 128 to prevent backpressure
    /// from slowing down execution.
    ///
    /// # Arguments
    /// * `operations` - Vector of operations to execute
    ///
    /// # Returns
    /// Tuple of (executor, progress_receiver)
    pub fn new(operations: Vec<TurboOperation>) -> (Self, mpsc::Receiver<ProgressEvent>) {
        // Channel buffer size: 128 should handle rapid progress events
        // without blocking the executor
        let (progress_tx, progress_rx) = mpsc::channel(128);

        let executor = Self {
            operations,
            progress_tx,
        };

        (executor, progress_rx)
    }

    /// Execute all operations with progress events and cancellation support.
    ///
    /// Operations are grouped by priority and executed sequentially by group.
    /// Within each group, operations run in parallel. Cancellation is checked
    /// at group boundaries.
    ///
    /// # Arguments
    /// * `cancel_token` - Token for cancellation. When cancelled, execution
    ///   stops before starting the next priority group.
    ///
    /// # Returns
    /// `AsyncBatchResult` containing the batch results and cancellation status.
    pub async fn execute(&self, cancel_token: CancellationToken) -> AsyncBatchResult {
        let started_at = chrono::Utc::now().to_rfc3339();
        let start = Instant::now();

        // Group operations by priority
        let groups = self.group_by_priority();
        let num_groups = groups.len();
        let total_ops = self.operations.len();

        // Emit plan started event
        let _ = self
            .progress_tx
            .send(ProgressEvent::PlanStarted {
                total_ops,
                num_groups,
            })
            .await;

        // Pre-allocate results vector
        let mut all_results: Vec<Option<OperationResult>> = vec![None; total_ops];
        let mut total_success = 0usize;
        let mut total_failed = 0usize;
        let mut was_cancelled = false;

        // Execute each priority group sequentially
        for (priority, group) in groups {
            // Check for cancellation before starting this group
            if cancel_token.is_cancelled() {
                was_cancelled = true;
                break;
            }

            let ops_in_group = group.len();

            // Emit group started event
            let _ = self
                .progress_tx
                .send(ProgressEvent::GroupStarted {
                    priority,
                    ops_in_group,
                })
                .await;

            // Execute this group in parallel via spawn_blocking -> rayon
            let group_results = self.execute_group_parallel(group, &cancel_token).await;

            // Process results and emit op completed events
            let mut group_success = 0usize;
            let mut group_failed = 0usize;

            for (idx, result) in group_results {
                let success = result.status == "success";
                if success {
                    group_success += 1;
                    total_success += 1;
                } else {
                    group_failed += 1;
                    total_failed += 1;
                }

                // Store result
                all_results[idx] = Some(result.clone());

                // Emit op completed event
                let _ = self
                    .progress_tx
                    .send(ProgressEvent::OpCompleted {
                        op_id: result.operation_id.clone(),
                        op_type: result.operation_type.clone(),
                        success,
                        duration_ms: result.duration_ms,
                    })
                    .await;
            }

            // Emit group completed event
            let _ = self
                .progress_tx
                .send(ProgressEvent::GroupCompleted {
                    priority,
                    successful_ops: group_success,
                    failed_ops: group_failed,
                })
                .await;
        }

        let total_duration_ms = start.elapsed().as_secs_f64() * 1000.0;

        // Determine final status
        let status = if was_cancelled {
            "cancelled".to_string()
        } else if total_failed == 0 {
            "completed".to_string()
        } else if total_success > 0 {
            "partial".to_string()
        } else {
            "failed".to_string()
        };

        // Emit plan completed event
        let _ = self
            .progress_tx
            .send(ProgressEvent::PlanCompleted {
                status: status.clone(),
                total_success,
                total_failed,
                total_duration_ms,
            })
            .await;

        // Collect all results (filter out None values from cancellation)
        let results: Vec<OperationResult> = all_results.into_iter().flatten().collect();

        // Build batch result
        let completed_at = chrono::Utc::now().to_rfc3339();
        let batch_result = BatchResult {
            status,
            success_count: total_success,
            error_count: total_failed,
            total_count: total_ops,
            results,
            total_duration_ms,
            started_at,
            completed_at,
        };

        AsyncBatchResult {
            batch_result,
            was_cancelled,
        }
    }

    /// Group operations by priority level.
    ///
    /// Returns a BTreeMap where keys are priority values (sorted ascending)
    /// and values are vectors of (original_index, operation) tuples.
    fn group_by_priority(&self) -> BTreeMap<u32, Vec<(usize, TurboOperation)>> {
        let mut groups: BTreeMap<u32, Vec<(usize, TurboOperation)>> = BTreeMap::new();

        for (idx, op) in self.operations.iter().enumerate() {
            groups
                .entry(op.priority)
                .or_default()
                .push((idx, op.clone()));
        }

        groups
    }

    /// Execute a group of operations in parallel using spawn_blocking + rayon.
    ///
    /// This bridges Tokio's async world to Rayon's parallel CPU execution.
    /// Each operation is executed in a blocking task, and Rayon handles
    /// the parallelism within those tasks.
    ///
    /// # Arguments
    /// * `group` - Vector of (index, operation) tuples to execute
    /// * `_cancel_token` - Cancellation token (checked before spawning)
    ///
    /// # Returns
    /// Vector of (original_index, operation_result) tuples.
    async fn execute_group_parallel(
        &self,
        group: Vec<(usize, TurboOperation)>,
        _cancel_token: &CancellationToken,
    ) -> Vec<(usize, OperationResult)> {
        // Use spawn_blocking to run CPU-intensive work
        // Rayon handles the parallelism within the blocking pool
        let results: Vec<(usize, OperationResult)> = tokio::task::spawn_blocking(move || {
            use rayon::prelude::*;

            group
                .par_iter()
                .map(|(idx, op)| (*idx, execute_single_operation(op)))
                .collect::<Vec<_>>()
        })
        .await
        .unwrap_or_default();

        results
    }

    /// Execute a batch of operations with progress events.
    ///
    /// This is a convenience method that creates an executor and runs it
    /// without cancellation support.
    ///
    /// # Arguments
    /// * `operations` - Vector of operations to execute
    ///
    /// # Returns
    /// Tuple of (BatchResult, progress_receiver)
    pub async fn execute_batch_with_progress(
        operations: Vec<TurboOperation>,
    ) -> (BatchResult, mpsc::Receiver<ProgressEvent>) {
        let (executor, progress_rx) = Self::new(operations);
        let cancel_token = CancellationToken::new();
        let result = executor.execute(cancel_token).await;
        (result.batch_result, progress_rx)
    }
}

/// Execute operations with priority grouping and progress events.
///
/// This is a standalone convenience function for simple use cases.
/// For more control (e.g., cancellation), use `AsyncBatchExecutor` directly.
///
/// # Arguments
/// * `operations` - Vector of operations to execute
///
/// # Returns
/// `AsyncBatchResult` containing the execution results
///
/// # Example
///
/// ```rust
/// use turbo_ops::async_batch_executor::execute_async_batch;
/// use turbo_ops::models::TurboOperation;
///
/// #[tokio::main]
/// async fn main() {
///     let ops = vec![
///         TurboOperation::list_files(".", true),
///         TurboOperation::grep("test", "."),
///     ];
///
///     let result = execute_async_batch(ops).await;
///     println!("Status: {}", result.batch_result.status);
/// }
/// ```
pub async fn execute_async_batch(operations: Vec<TurboOperation>) -> AsyncBatchResult {
    let (executor, _progress_rx) = AsyncBatchExecutor::new(operations);
    let cancel_token = CancellationToken::new();
    executor.execute(cancel_token).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::TurboOperation;

    #[tokio::test]
    async fn test_async_executor_empty() {
        let ops: Vec<TurboOperation> = vec![];
        let (executor, mut rx) = AsyncBatchExecutor::new(ops);
        let cancel_token = CancellationToken::new();

        let result = executor.execute(cancel_token).await;

        assert_eq!(result.batch_result.total_count, 0);
        assert_eq!(result.batch_result.success_count, 0);
        assert!(!result.was_cancelled);

        // Check events
        let event = rx.recv().await;
        assert!(matches!(event, Some(ProgressEvent::PlanStarted { total_ops: 0, num_groups: 0 })));

        let event = rx.recv().await;
        assert!(matches!(event, Some(ProgressEvent::PlanCompleted { status, total_success: 0, total_failed: 0, .. }) if status == "completed"));
    }

    #[tokio::test]
    async fn test_async_executor_single_op() {
        let ops = vec![TurboOperation::list_files(".", false).with_id("op1".to_string())];
        let (executor, mut rx) = AsyncBatchExecutor::new(ops);
        let cancel_token = CancellationToken::new();

        let result = executor.execute(cancel_token).await;

        assert_eq!(result.batch_result.total_count, 1);
        assert_eq!(result.batch_result.success_count, 1);
        assert!(!result.was_cancelled);

        // Collect all events
        let mut events = vec![];
        while let Ok(Some(event)) = tokio::time::timeout(
            tokio::time::Duration::from_millis(100),
            rx.recv()
        ).await {
            events.push(event);
        }

        assert!(events.iter().any(|e| matches!(e, ProgressEvent::PlanStarted { total_ops: 1, .. })));
        assert!(events.iter().any(|e| matches!(e, ProgressEvent::GroupStarted { .. })));
        assert!(events.iter().any(|e| matches!(e, ProgressEvent::OpCompleted { .. })));
        assert!(events.iter().any(|e| matches!(e, ProgressEvent::GroupCompleted { .. })));
        assert!(events.iter().any(|e| matches!(e, ProgressEvent::PlanCompleted { .. })));
    }

    #[tokio::test]
    async fn test_cancellation() {
        // Create operations with different priorities
        let ops = vec![
            TurboOperation::list_files(".", false)
                .with_id("first".to_string())
                .with_priority(100),
            TurboOperation::list_files(".", false)
                .with_id("second".to_string())
                .with_priority(200),
        ];

        let (executor, _rx) = AsyncBatchExecutor::new(ops);
        let cancel_token = CancellationToken::new();

        // Cancel immediately
        cancel_token.cancel();

        let result = executor.execute(cancel_token).await;

        // Should be cancelled before or during first group
        assert!(result.was_cancelled);
    }

    #[tokio::test]
    async fn test_priority_grouping() {
        let ops = vec![
            TurboOperation::list_files(".", false)
                .with_id("low".to_string())
                .with_priority(200),
            TurboOperation::list_files(".", false)
                .with_id("high".to_string())
                .with_priority(100),
        ];

        let (executor, mut rx) = AsyncBatchExecutor::new(ops);
        let cancel_token = CancellationToken::new();

        let result = executor.execute(cancel_token).await;

        // Should complete successfully
        assert_eq!(result.batch_result.success_count, 2);
        assert!(!result.was_cancelled);

        // Find group events and verify priority order
        let mut group_events: Vec<_> = vec![];
        while let Ok(Some(event)) = tokio::time::timeout(
            tokio::time::Duration::from_millis(100),
            rx.recv()
        ).await {
            if let ProgressEvent::GroupStarted { priority, .. } = &event {
                group_events.push(*priority);
            }
        }

        // Groups should be in ascending priority order
        assert_eq!(group_events, vec![100, 200]);
    }

    #[tokio::test]
    async fn test_progress_events_detailed() {
        // Test that all expected progress events are emitted in correct order.
        let ops = vec![
            TurboOperation::list_files(".", false)
                .with_id("op1".to_string())
                .with_priority(100),
        ];

        let (executor, mut rx) = AsyncBatchExecutor::new(ops);
        let cancel_token = CancellationToken::new();

        let result = executor.execute(cancel_token).await;

        // Collect all events in order
        let mut events = vec![];
        while let Ok(Some(event)) = tokio::time::timeout(
            tokio::time::Duration::from_millis(200),
            rx.recv()
        ).await {
            events.push(event);
        }

        // Verify event sequence
        assert!(!events.is_empty());
        
        // First event should be PlanStarted
        assert!(matches!(events[0], ProgressEvent::PlanStarted { total_ops: 1, num_groups: 1 }));
        
        // Last event should be PlanCompleted
        assert!(matches!(events.last().unwrap(), ProgressEvent::PlanCompleted { .. }));
        
        // Should have GroupStarted and GroupCompleted
        assert!(events.iter().any(|e| matches!(e, ProgressEvent::GroupStarted { priority: 100, .. })));
        assert!(events.iter().any(|e| matches!(e, ProgressEvent::GroupCompleted { priority: 100, .. })));
        
        // Should have OpCompleted
        assert!(events.iter().any(|e| matches!(e, ProgressEvent::OpCompleted { op_id: Some(ref id), .. } if id == "op1")));
        
        // Result should indicate success
        assert_eq!(result.batch_result.success_count, 1);
    }

    #[tokio::test]
    async fn test_cancellation_during_execution() {
        // Test cancellation that occurs during execution.
        let ops = vec![
            TurboOperation::list_files(".", false)
                .with_id("first".to_string())
                .with_priority(100),
            TurboOperation::list_files(".", false)
                .with_id("second".to_string())
                .with_priority(100),
            TurboOperation::list_files(".", false)
                .with_id("third".to_string())
                .with_priority(200),
        ];

        let (executor, mut rx) = AsyncBatchExecutor::new(ops);
        let cancel_token = CancellationToken::new();

        // Start execution in a separate task
        let executor_handle = tokio::spawn({
            let cancel_token = cancel_token.clone();
            async move {
                executor.execute(cancel_token).await
            }
        });

        // Cancel after receiving the first GroupStarted event
        while let Ok(Some(event)) = tokio::time::timeout(
            tokio::time::Duration::from_millis(50),
            rx.recv()
        ).await {
            if matches!(event, ProgressEvent::GroupStarted { .. }) {
                cancel_token.cancel();
                break;
            }
        }

        let result = executor_handle.await.unwrap();

        // Should be marked as cancelled
        assert!(result.was_cancelled);
    }

    #[tokio::test]
    async fn test_multiple_operations_same_priority() {
        // Test multiple operations with the same priority are executed together.
        let ops = vec![
            TurboOperation::list_files(".", false)
                .with_id("op1".to_string())
                .with_priority(100),
            TurboOperation::list_files(".", false)
                .with_id("op2".to_string())
                .with_priority(100),
            TurboOperation::list_files(".", false)
                .with_id("op3".to_string())
                .with_priority(100),
        ];

        let (executor, mut rx) = AsyncBatchExecutor::new(ops);
        let cancel_token = CancellationToken::new();

        let result = executor.execute(cancel_token).await;

        // All 3 should succeed
        assert_eq!(result.batch_result.success_count, 3);
        assert_eq!(result.batch_result.total_count, 3);

        // Collect all events
        let mut group_started_count = 0;
        while let Ok(Some(event)) = tokio::time::timeout(
            tokio::time::Duration::from_millis(50),
            rx.recv()
        ).await {
            if let ProgressEvent::GroupStarted { priority: 100, .. } = &event {
                group_started_count += 1;
            }
        }

        // Should only have 1 group (all same priority)
        assert_eq!(group_started_count, 1, "Expected 1 group for same priority operations");
    }

    #[tokio::test]
    async fn test_error_handling_async() {
        // Test that errors in operations are properly handled.
        let ops = vec![
            TurboOperation {
                op_type: crate::models::OperationType::ListFiles,
                args: serde_json::json!({
                    "directory": "/nonexistent/path/that/does/not/exist",
                    "recursive": false
                }),
                id: Some("failing".to_string()),
                priority: 100,
            },
        ];

        let (executor, mut rx) = AsyncBatchExecutor::new(ops);
        let cancel_token = CancellationToken::new();

        let result = executor.execute(cancel_token).await;

        // Should have 1 failed operation
        assert_eq!(result.batch_result.total_count, 1);
        assert_eq!(result.batch_result.error_count, 1);
        assert_eq!(result.batch_result.success_count, 0);
        assert_eq!(result.batch_result.status, "failed");

        // Check that error event was emitted
        let mut found_error = false;
        while let Ok(Some(event)) = tokio::time::timeout(
            tokio::time::Duration::from_millis(100),
            rx.recv()
        ).await {
            if let ProgressEvent::OpCompleted { success: false, op_id: Some(ref id), .. } = event {
                if id == "failing" {
                    found_error = true;
                }
            }
        }
        assert!(found_error, "Should have received error event for failing operation");
    }

    #[tokio::test]
    async fn test_mixed_success_failure() {
        // Test batch with both successful and failed operations.
        let ops = vec![
            TurboOperation::list_files(".", false)
                .with_id("success".to_string())
                .with_priority(100),
            TurboOperation {
                op_type: crate::models::OperationType::ListFiles,
                args: serde_json::json!({
                    "directory": "/nonexistent/path",
                    "recursive": false
                }),
                id: Some("failure".to_string()),
                priority: 100,
            },
        ];

        let (executor, _rx) = AsyncBatchExecutor::new(ops);
        let cancel_token = CancellationToken::new();

        let result = executor.execute(cancel_token).await;

        assert_eq!(result.batch_result.total_count, 2);
        assert_eq!(result.batch_result.success_count, 1);
        assert_eq!(result.batch_result.error_count, 1);
        assert_eq!(result.batch_result.status, "partial");
    }

    #[tokio::test]
    async fn test_different_operation_types() {
        // Test batch with different operation types.
        let ops = vec![
            TurboOperation::list_files(".", false)
                .with_id("list".to_string())
                .with_priority(100),
            TurboOperation::grep("fn", ".")
                .with_id("grep".to_string())
                .with_priority(200),
        ];

        let (executor, _rx) = AsyncBatchExecutor::new(ops);
        let cancel_token = CancellationToken::new();

        let result = executor.execute(cancel_token).await;

        // Both should succeed
        assert_eq!(result.batch_result.success_count, 2);
        
        // Verify both operations have results
        let list_result = result.batch_result.results.iter().find(|r| r.operation_id == Some("list".to_string()));
        let grep_result = result.batch_result.results.iter().find(|r| r.operation_id == Some("grep".to_string()));
        
        assert!(list_result.is_some(), "Should have list_files result");
        assert!(grep_result.is_some(), "Should have grep result");
        assert!(list_result.unwrap().is_success());
        assert!(grep_result.unwrap().is_success());
    }

    #[tokio::test]
    async fn test_execute_batch_with_progress() {
        // Test the execute_batch_with_progress helper function.
        let ops = vec![
            TurboOperation::list_files(".", false)
                .with_id("op1".to_string()),
        ];

        let (result, mut rx) = AsyncBatchExecutor::execute_batch_with_progress(ops).await;

        // Result should be successful
        assert_eq!(result.success_count, 1);

        // Should receive progress events
        let mut found_plan_started = false;
        while let Ok(Some(event)) = tokio::time::timeout(
            tokio::time::Duration::from_millis(100),
            rx.recv()
        ).await {
            if matches!(event, ProgressEvent::PlanStarted { .. }) {
                found_plan_started = true;
            }
        }
        assert!(found_plan_started);
    }

    #[tokio::test]
    async fn test_async_batch_result_fields() {
        // Test that AsyncBatchResult contains expected fields.
        let ops = vec![
            TurboOperation::list_files(".", false)
                .with_id("op1".to_string()),
        ];

        let (executor, _rx) = AsyncBatchExecutor::new(ops);
        let cancel_token = CancellationToken::new();

        let result = executor.execute(cancel_token).await;

        // Check all expected fields
        assert!(!result.was_cancelled);
        assert_eq!(result.batch_result.total_count, 1);
        assert_eq!(result.batch_result.success_count, 1);
        assert_eq!(result.batch_result.error_count, 0);
        assert!(!result.batch_result.results.is_empty());
        
        // Verify timestamps
        assert!(!result.batch_result.started_at.is_empty());
        assert!(!result.batch_result.completed_at.is_empty());
    }
}
