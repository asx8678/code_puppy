// ═══════════════════════════════════════════════════════════════════════════════
// zig_puppy_core - Message Processing Core
// ═══════════════════════════════════════════════════════════════════════════════
//
// Migration from: code_puppy_core (Rust)
// Migration date: 2025-01-14
// Migration reason: Faster compile times, smaller binaries, simpler cross-compilation
//
// This module provides:
//   - Message serialization/deserialization for LLM context windows
//   - Token estimation using tiktoken-compatible algorithms
//   - Message pruning strategies for context management
//   - Hash-based message deduplication
//
// Key differences from Rust:
//   - Uses comptime for type-level optimizations instead of generics
//   - Error handling via error unions instead of Result<T, E>
//   - Arena allocators replace complex lifetime management
//   - @export for C ABI compatibility instead of #[no_mangle] extern "C"
//
// FFI Strategy:
//   All public functions are exported with C ABI for Python cffi consumption.
//   Memory allocation follows the Zig convention: caller frees returned buffers.

const std = @import("std");
const builtin = @import("builtin");

// Module exports
pub const token_estimation = @import("token_estimation.zig");
pub const message_hashing = @import("message_hashing.zig");
pub const pruning = @import("pruning.zig");
pub const serialization = @import("serialization.zig");

// Re-export main types for ergonomic usage
pub const TokenEstimator = token_estimation.TokenEstimator;
pub const MessageHasher = message_hashing.MessageHasher;
pub const PruningStrategy = pruning.PruningStrategy;
pub const SessionSerializer = serialization.SessionSerializer;

// ═══════════════════════════════════════════════════════════════════════════════
// Version and Build Information (exported for runtime inspection)
// ═══════════════════════════════════════════════════════════════════════════════

/// Version follows semantic versioning
pub const VERSION = "0.1.0";

/// Build info for debugging
pub const BUILD_INFO = .{
    .version = VERSION,
    .zig_version = builtin.zig_version,
    .target = builtin.target,
    .mode = builtin.mode,
};

// ═══════════════════════════════════════════════════════════════════════════════
// C ABI Exports (for Python cffi)
// ═══════════════════════════════════════════════════════════════════════════════

/// Opaque handle type for C consumers (use ?*anyopaque directly for C ABI compatibility)
const PuppyCoreHandleInner = *anyopaque;

/// For use in function signatures that need optional handles
const OptionalPuppyCoreHandle = ?PuppyCoreHandleInner;

/// Error codes for C interface
pub const PuppyCoreError = enum(c_int) {
    success = 0,
    invalid_argument = -1,
    out_of_memory = -2,
    serialization_failed = -3,
    pruning_failed = -4,
};

/// Initialize the puppy_core module.
/// Returns a handle on success, null on failure.
/// Caller must call puppy_core_destroy() when done.
export fn puppy_core_create() ?*anyopaque {
    const allocator = std.heap.c_allocator;
    
    const ctx = allocator.create(CoreContext) catch return null;
    ctx.* = .{
        .allocator = allocator,
        .estimator = TokenEstimator.init(allocator),
        .hasher = MessageHasher.init(allocator),
    };
    
    return @ptrCast(ctx);
}

/// Destroy a puppy_core handle and free associated resources.
export fn puppy_core_destroy(handle: ?*anyopaque) void {
    if (handle == null) return;
    
    const ctx: *CoreContext = @ptrCast(@alignCast(handle.?));
    ctx.deinit();
    std.heap.c_allocator.destroy(ctx);
}

/// Process a batch of messages and return token counts.
/// Input: JSON array of message objects
/// Output: JSON object with per_message_tokens, total_tokens, hashes
/// Caller must free output buffer with puppy_core_free_string().
export fn puppy_core_process_messages(
    handle: ?*anyopaque,
    messages_json: [*:0]const u8,
    system_prompt: [*:0]const u8,
    output_json: *[*:0]u8,
) PuppyCoreError {
    if (handle == null) return .invalid_argument;
    if (messages_json[0] == 0) return .invalid_argument;  // Check for empty string instead of null comparison
    
    const ctx: *CoreContext = @ptrCast(@alignCast(handle.?));
    
    // TODO(code-puppy-zig-001): Implement message processing
    // This will call into token_estimation.zig and message_hashing.zig
    _ = ctx;
    _ = system_prompt;
    _ = output_json;
    
    return .success;
}

/// Free a string returned by puppy_core_* functions.
export fn puppy_core_free_string(ptr: [*c]u8) void {
    if (ptr == null) return;
    std.heap.c_allocator.free(std.mem.span(ptr));
}

// ═══════════════════════════════════════════════════════════════════════════════
// Internal Types
// ═══════════════════════════════════════════════════════════════════════════════

/// Core context holding all subsystems
const CoreContext = struct {
    allocator: std.mem.Allocator,
    estimator: TokenEstimator,
    hasher: MessageHasher,
    
    fn deinit(self: *CoreContext) void {
        self.estimator.deinit();
        self.hasher.deinit();
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "basic init/deinit" {
    const allocator = std.testing.allocator;
    
    var ctx = CoreContext{
        .allocator = allocator,
        .estimator = TokenEstimator.init(allocator),
        .hasher = MessageHasher.init(allocator),
    };
    
    ctx.deinit();
}

test "C ABI exports exist" {
    // Verify all C exports are available
    _ = puppy_core_create;
    _ = puppy_core_destroy;
    _ = puppy_core_process_messages;
    _ = puppy_core_free_string;
}
