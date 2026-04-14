// ═══════════════════════════════════════════════════════════════════════════════
// Batch Executor - Parallel Operation Orchestration
// ═══════════════════════════════════════════════════════════════════════════════
//
// Migration from: turbo_ops/src/batch_executor.rs
//
// Coordinates parallel execution of file operations with priority-based grouping.
// Zig's async/await is cleaner than Rust's futures for this use case.

const std = @import("std");
const operations = @import("operations.zig");

// ═══════════════════════════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════════════════════════

pub const BatchConfig = struct {
    /// Maximum concurrent operations
    max_concurrency: usize = 8,
    
    /// Timeout for entire batch (ms)
    timeout_ms: u64 = 30000,
    
    /// Timeout per operation (ms)
    operation_timeout_ms: u64 = 10000,
    
    /// Group by priority (lower priority = execute earlier)
    group_by_priority: bool = true,
    
    /// Continue on individual operation failures
    continue_on_error: bool = true,
};

pub const BatchResult = struct {
    status: BatchStatus,
    success_count: usize,
    error_count: usize,
    total_count: usize,
    results: []operations.OperationResult,
    total_duration_ms: f64,
    started_at: i64,
    completed_at: i64,
    
    pub fn deinit(self: *BatchResult, allocator: std.mem.Allocator) void {
        // Free nested allocations in results
        for (self.results) |*result| {
            freeOperationResult(allocator, result);
        }
        allocator.free(self.results);
    }
};

pub const BatchStatus = enum {
    completed,
    partial,
    failed,
    timeout,
};

pub const PriorityGroup = struct {
    priority: u32,
    operations: []operations.Operation,
};

// ═══════════════════════════════════════════════════════════════════════════════
// Main Entry Points
// ═══════════════════════════════════════════════════════════════════════════════

/// Execute a batch of operations with optional parallelism
pub fn batchExecute(
    allocator: std.mem.Allocator,
    ops: []const operations.Operation,
    config: BatchConfig,
    parallel: bool,
) error{ OutOfMemory, Timeout, BatchFailed }!BatchResult {
    const started_at = std.time.milliTimestamp();
    
    var results = try allocator.alloc(operations.OperationResult, ops.len);
    errdefer allocator.free(results);
    
    if (parallel and config.group_by_priority) {
        // Group by priority and execute groups sequentially
        var arena = std.heap.ArenaAllocator.init(allocator);
        defer arena.deinit();
        
        const groups = try groupByPriority(arena.allocator(), ops);
        
        var idx: usize = 0;
        for (groups) |group| {
            // Execute group in parallel
            const group_results = try executeGroupParallel(
                allocator,
                group.operations,
                config,
            );
            
            for (group_results) |res| {
                results[idx] = res;
                idx += 1;
            }
        }
    } else if (parallel) {
        // Full parallel execution
        const parallel_results = try executeAllParallel(allocator, ops, config);
        @memcpy(results, parallel_results);
        allocator.free(parallel_results);
    } else {
        // Sequential execution
        for (ops, 0..) |op, i| {
            results[i] = executeSingle(allocator, op) catch |err| {
                if (!config.continue_on_error) {
                    return error.BatchFailed;
                }
                results[i] = .{
                    .operation_id = op.id,
                    .success = false,
                    .duration_ms = 0,
                    .data = undefined,
                    .error_message = try allocator.dupe(u8, @errorName(err)),
                };
                continue;
            };
        }
    }
    
    const completed_at = std.time.milliTimestamp();
    const duration_ms = @as(f64, @floatFromInt(completed_at - started_at));
    
    // Count successes and failures
    var success_count: usize = 0;
    var error_count: usize = 0;
    for (results) |res| {
        if (res.success) {
            success_count += 1;
        } else {
            error_count += 1;
        }
    }
    
    // Determine status
    const status = if (error_count == 0)
        BatchStatus.completed
    else if (success_count > 0)
        BatchStatus.partial
    else
        BatchStatus.failed;
    
    return BatchResult{
        .status = status,
        .success_count = success_count,
        .error_count = error_count,
        .total_count = ops.len,
        .results = results,
        .total_duration_ms = duration_ms,
        .started_at = started_at,
        .completed_at = completed_at,
    };
}

/// Execute a single operation
fn executeSingle(
    allocator: std.mem.Allocator,
    op: operations.Operation,
) operations.OperationError!operations.OperationResult {
    return switch (op.op_type) {
        .list_files => operations.executeListFiles(allocator, op.args.list_files),
        .grep => operations.executeGrep(allocator, op.args.grep),
        .read_files => operations.executeReadFiles(allocator, op.args.read_files),
        .stat => undefined,  // TODO
    };
}

// ═══════════════════════════════════════════════════════════════════════════════
// Grouping and Parallelism
// ═══════════════════════════════════════════════════════════════════════════════

fn groupByPriority(
    allocator: std.mem.Allocator,
    ops: []const operations.Operation,
) error{OutOfMemory}![]PriorityGroup {
    // Sort operations by priority
    var sorted = try allocator.dupe(operations.Operation, ops);
    defer allocator.free(sorted);
    
    std.sort.block(operations.Operation, sorted, {}, struct {
        fn lessThan(ctx: void, a: operations.Operation, b: operations.Operation) bool {
            _ = ctx;
            return a.priority < b.priority;
        }
    }.lessThan);
    
    // Group by unique priorities
    var groups = std.ArrayList(PriorityGroup).init(allocator);
    defer groups.deinit();
    
    var current_priority: ?u32 = null;
    var group_start: usize = 0;
    
    for (sorted, 0..) |op, i| {
        if (current_priority == null or op.priority != current_priority.?) {
            if (current_priority != null) {
                try groups.append(.{
                    .priority = current_priority.?,
                    .operations = try allocator.dupe(operations.Operation, sorted[group_start..i]),
                });
            }
            current_priority = op.priority;
            group_start = i;
        }
    }
    
    // Add final group
    if (current_priority != null) {
        try groups.append(.{
            .priority = current_priority.?,
            .operations = try allocator.dupe(operations.Operation, sorted[group_start..]),
        });
    }
    
    return try groups.toOwnedSlice();
}

fn executeGroupParallel(
    allocator: std.mem.Allocator,
    ops: []const operations.Operation,
    config: BatchConfig,
) error{ OutOfMemory, Timeout }![]operations.OperationResult {
    var results = try allocator.alloc(operations.OperationResult, ops.len);
    errdefer allocator.free(results);
    
    // TODO(code-puppy-zig-011): Implement proper work-stealing thread pool
    // For now, this uses a simple thread-per-operation approach (limited)
    
    // TODO(code-puppy-zig-011): Implement proper work-stealing thread pool
    // For now, process sequentially to maintain correctness
    _ = config;  // Will be used when threading is implemented
    
    for (0..ops.len) |i| {
        results[i] = executeSingle(allocator, ops[i]) catch |err| {
            results[i] = .{
                .operation_id = ops[i].id,
                .success = false,
                .duration_ms = 0,
                .data = undefined,
                .error_message = try allocator.dupe(u8, @errorName(err)),
            };
        };
    }
    
    return results;
}

fn executeAllParallel(
    allocator: std.mem.Allocator,
    ops: []const operations.Operation,
    config: BatchConfig,
) error{ OutOfMemory, Timeout }![]operations.OperationResult {
    // Delegates to group execution (single group)
    return executeGroupParallel(allocator, ops, config);
}

// ═══════════════════════════════════════════════════════════════════════════════
// Memory Management
// ═══════════════════════════════════════════════════════════════════════════════

fn freeOperationResult(allocator: std.mem.Allocator, result: *operations.OperationResult) void {
    if (result.operation_id) |id| allocator.free(id);
    if (result.error_message) |msg| allocator.free(msg);
    
    switch (result.op_type) {
        .list_files => {
            const r = result.data.list_files;
            for (r.files) |f| allocator.free(f.path);
            allocator.free(r.files);
            allocator.free(r.directory);
        },
        .grep => {
            const r = result.data.grep;
            for (r.matches) |m| {
                allocator.free(m.file_path);
                allocator.free(m.line_content);
            }
            allocator.free(r.matches);
            allocator.free(r.pattern);
            allocator.free(r.directory);
        },
        .read_files => {
            const r = result.data.read_files;
            for (r.files) |f| {
                allocator.free(f.file_path);
                if (f.content) |c| allocator.free(c);
                if (f.err_msg) |e| allocator.free(e);
            }
            allocator.free(r.files);
        },
        .stat => {},  // TODO
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "groupByPriority" {
    const allocator = std.testing.allocator;
    
    const ops = &[_]operations.Operation{
        .{ .op_type = .list_files, .id = "op1", .priority = 100, .args = undefined },
        .{ .op_type = .grep, .id = "op2", .priority = 50, .args = undefined },
        .{ .op_type = .read_files, .id = "op3", .priority = 100, .args = undefined },
    };
    
    const groups = try groupByPriority(allocator, ops);
    defer {
        for (groups) |g| allocator.free(g.operations);
        allocator.free(groups);
    }
    
    try std.testing.expectEqual(@as(usize, 2), groups.len);
    try std.testing.expectEqual(@as(u32, 50), groups[0].priority);
    try std.testing.expectEqual(@as(u32, 100), groups[1].priority);
}
