// ═══════════════════════════════════════════════════════════════════════════════
// zig_turbo_ops - Batch File Operations
// ═══════════════════════════════════════════════════════════════════════════════
//
// Migration from: turbo_ops (Rust)
// Migration date: 2025-01-14
// Migration reason: Faster parallel execution, simpler cross-compilation
//
// This module provides:
//   - list_files: Directory listing with intelligent filtering
//   - grep: Fast parallel pattern matching
//   - read_files: Batch file reading with line-range support
//   - batch_execute: Orchestrated parallel operations
//
// Key differences from Rust:
//   - Rayon → Zig's builtin async + thread pools
//   - GIL release handled via C ABI
//   - Arena allocators for bulk operations
//   - Explicit SIMD opportunities with Zig's vector types

const std = @import("std");
const builtin = @import("builtin");

// Module imports
pub const operations = @import("operations.zig");
pub const batch_executor = @import("batch_executor.zig");

// Re-exports for cleaner API
pub const BatchResult = batch_executor.BatchResult;
pub const OperationResult = operations.OperationResult;
pub const OperationType = operations.OperationType;

// ═══════════════════════════════════════════════════════════════════════════════
// Version and Build Info
// ═══════════════════════════════════════════════════════════════════════════════

pub const VERSION = "0.1.0";

// ═══════════════════════════════════════════════════════════════════════════════
// C ABI Exports (for Python cffi)
// ═══════════════════════════════════════════════════════════════════════════════

export const TURBO_OPS_VERSION: [*:0]const u8 = VERSION;

/// Error codes for C interface
pub const TurboOpsError = enum(c_int) {
    success = 0,
    invalid_argument = -1,
    out_of_memory = -2,
    file_not_found = -3,
    permission_denied = -4,
    pattern_error = -5,
    batch_failed = -6,
};

/// Opaque handle for C consumers
pub const TurboOpsHandle = *anyopaque;

/// Context structure holding allocator and settings
const OpsContext = struct {
    allocator: std.mem.Allocator,
    thread_pool: ?*ThreadPool,
    parallel: bool,
    
    fn deinit(self: *OpsContext) void {
        if (self.thread_pool) |pool| {
            pool.deinit();
            self.allocator.destroy(pool);
        }
    }
};

/// Initialize turbo_ops module
export fn turbo_ops_create(parallel: bool) ?TurboOpsHandle {
    const allocator = std.heap.c_allocator;
    
    const ctx = allocator.create(OpsContext) catch return null;
    
    ctx.* = .{
        .allocator = allocator,
        .thread_pool = null,
        .parallel = parallel,
    };
    
    // Initialize thread pool if parallel mode requested
    if (parallel) {
        const pool = allocator.create(ThreadPool) catch {
            allocator.destroy(ctx);
            return null;
        };
        
        pool.* = ThreadPool.init(allocator, @max(1, std.Thread.getCpuCount() catch 1)) catch {
            allocator.destroy(pool);
            allocator.destroy(ctx);
            return null;
        };
        
        ctx.thread_pool = pool;
    }
    
    return @ptrCast(ctx);
}

/// Destroy turbo_ops handle
export fn turbo_ops_destroy(handle: ?TurboOpsHandle) void {
    if (handle == null) return;
    
    const ctx: *OpsContext = @ptrCast(@alignCast(handle.?));
    ctx.deinit();
    std.heap.c_allocator.destroy(ctx);
}

/// Execute a batch of operations (JSON input/output)
/// Input: JSON array of operation objects
/// Output: JSON object with results (caller frees with turbo_ops_free_string)
export fn turbo_ops_batch_execute(
    handle: ?TurboOpsHandle,
    operations_json: ?[*:0]const u8,
    parallel: bool,
    output_json: *[*:0]u8,
) TurboOpsError {
    if (handle == null) return .invalid_argument;
    if (operations_json == null) return .invalid_argument;
    
    const ctx: *OpsContext = @ptrCast(@alignCast(handle.?));
    _ = ctx;
    _ = parallel;
    _ = output_json;
    
    // TODO(code-puppy-zig-004): Parse JSON, execute batch, serialize results
    
    return .success;
}

/// List files in directory (JSON output)
export fn turbo_ops_list_files(
    handle: ?TurboOpsHandle,
    directory: ?[*:0]const u8,
    recursive: bool,
    output_json: *[*:0]u8,
) TurboOpsError {
    if (handle == null) return .invalid_argument;
    if (directory == null) return .invalid_argument;
    
    const ctx: *OpsContext = @ptrCast(@alignCast(handle.?));
    _ = ctx;
    _ = recursive;
    _ = output_json;
    
    // TODO(code-puppy-zig-005): Implement list_files
    
    return .success;
}

/// Execute grep search (JSON output)
export fn turbo_ops_grep(
    handle: ?TurboOpsHandle,
    pattern: ?[*:0]const u8,
    _directory: ?[*:0]const u8,
    output_json: *[*:0]u8,
) TurboOpsError {
    if (handle == null) return .invalid_argument;
    if (pattern == null) return .invalid_argument;
    
    const ctx: *OpsContext = @ptrCast(@alignCast(handle.?));
    _ = ctx;
    _ = output_json;
    _ = _directory;
    
    // TODO(code-puppy-zig-006): Implement grep with regex support
    
    return .success;
}

/// Read files (JSON output)
export fn turbo_ops_read_files(
    handle: ?TurboOpsHandle,
    file_paths_json: ?[*:0]const u8,
    start_line: c_int,
    num_lines: c_int,
    output_json: *[*:0]u8,
) TurboOpsError {
    if (handle == null) return .invalid_argument;
    if (file_paths_json == null) return .invalid_argument;
    
    const ctx: *OpsContext = @ptrCast(@alignCast(handle.?));
    _ = ctx;
    _ = output_json;
    
    // Parse start_line and num_lines (negative means "all")
    const maybe_start: ?usize = if (start_line > 0) @intCast(start_line) else null;
    const maybe_num: ?usize = if (num_lines > 0) @intCast(num_lines) else null;
    _ = maybe_start;
    _ = maybe_num;
    
    // TODO(code-puppy-zig-007): Implement batch file reading
    
    return .success;
}

/// Free a string returned by turbo_ops_* functions
export fn turbo_ops_free_string(ptr: [*c]u8) void {
    if (ptr == null) return;
    std.heap.c_allocator.free(std.mem.span(ptr));
}

// ═══════════════════════════════════════════════════════════════════════════════
// Simple Thread Pool (basic implementation)
// ═══════════════════════════════════════════════════════════════════════════════
//
// Zig's std.Thread doesn't have a built-in thread pool, so we roll our own
// minimal one. In production, consider using zig's std.event.Loop for async I/O.

const ThreadPool = struct {
    allocator: std.mem.Allocator,
    threads: []std.Thread,
    shutdown: bool,
    
    const Self = @This();
    
    fn init(allocator: std.mem.Allocator, thread_count: usize) !Self {
        const threads = try allocator.alloc(std.Thread, thread_count);
        errdefer allocator.free(threads);
        
        return .{
            .allocator = allocator,
            .threads = threads,
            .shutdown = false,
        };
    }
    
    fn deinit(self: *Self) void {
        self.shutdown = true;
        
        // In a real implementation, signal threads to shut down
        // and wait for them
        
        self.allocator.free(self.threads);
    }
    
    fn execute(self: *Self, comptime T: type, tasks: []T, worker_fn: *const fn (*T) void) void {
        _ = self;
        _ = tasks;
        _ = worker_fn;
        // TODO(code-puppy-zig-008): Proper thread pool with work stealing
        // For now, this is a stub - actual implementation would use
        // std.Thread.SpawnConfig and work distribution
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "C ABI exports exist" {
    _ = turbo_ops_create;
    _ = turbo_ops_destroy;
    _ = turbo_ops_batch_execute;
    _ = turbo_ops_list_files;
    _ = turbo_ops_grep;
    _ = turbo_ops_read_files;
    _ = turbo_ops_free_string;
}

test "version constant" {
    try std.testing.expect(@TypeOf(TURBO_OPS_VERSION) == [*:0]const u8);
}
