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
pub const binary_protocol = @import("binary_protocol.zig");

// Type imports for cleaner code
const MessageContent = message_hashing.MessageContent;

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

/// Message part structure for parsing JSON input
const MessagePart = struct {
    content: ?[]const u8 = null,
    content_json: ?[]const u8 = null,
};

/// Message structure for parsing JSON input
const InputMessage = struct {
    role: []const u8,
    parts: []const MessagePart,
};

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
    
    // Check for empty messages_json
    const json_slice = std.mem.span(messages_json);
    if (json_slice.len == 0) return .invalid_argument;
    
    const ctx: *CoreContext = @ptrCast(@alignCast(handle.?));
    const allocator = ctx.allocator;
    
    // Parse messages JSON
    const parsed = std.json.parseFromSlice([]InputMessage, allocator, json_slice, .{
        .ignore_unknown_fields = true,
    }) catch return .invalid_argument;
    defer parsed.deinit();
    
    const messages = parsed.value;
    if (messages.len == 0) return .invalid_argument;
    
    // Allocate arrays for results
    var per_message_tokens = allocator.alloc(i64, messages.len) catch return .out_of_memory;
    defer allocator.free(per_message_tokens);
    
    var message_hashes = allocator.alloc(u64, messages.len) catch return .out_of_memory;
    defer allocator.free(message_hashes);
    
    // Process each message
    var total_tokens: i64 = 0;
    for (messages, 0..) |msg, i| {
        var msg_tokens: i64 = 0;
        
        // Accumulate tokens from all parts
        for (msg.parts) |part| {
            const content = part.content orelse part.content_json orelse "";
            msg_tokens += ctx.estimator.estimateTokens(content);
        }
        
        // Add message overhead
        msg_tokens += token_estimation.MESSAGE_OVERHEAD_TOKENS;
        
        per_message_tokens[i] = msg_tokens;
        total_tokens += msg_tokens;
        
        // Hash the message (concatenate all parts for hashing)
        const msg_content = concatenateParts(allocator, msg.parts) catch return .out_of_memory;
        defer allocator.free(msg_content);
        
        const hash_content = MessageContent{
            .role = msg.role,
            .content = msg_content,
            .metadata = null,
        };
        message_hashes[i] = ctx.hasher.hashMessage(hash_content);
    }
    
    // Calculate system prompt overhead
    const sys_prompt_slice = std.mem.span(system_prompt);
    const overhead_tokens = ctx.estimator.estimateTokens(sys_prompt_slice);
    const context_overhead = overhead_tokens + token_estimation.SYSTEM_PROMPT_OVERHEAD;
    
    // Build result JSON
    const result_json = buildResultJson(
        allocator,
        per_message_tokens,
        total_tokens,
        message_hashes,
        context_overhead,
    ) catch return .out_of_memory;
    
    // Cast from [*:0]u8 to [*:0]u8 for C ABI compatibility (result is already null-terminated)
    output_json.* = result_json;
    return .success;
}

/// Concatenate all message parts into a single string
fn concatenateParts(allocator: std.mem.Allocator, parts: []const MessagePart) error{OutOfMemory}![]u8 {
    var total_len: usize = 0;
    for (parts) |part| {
        const content = part.content orelse part.content_json orelse "";
        total_len += content.len;
    }
    
    var result = try allocator.alloc(u8, total_len);
    var offset: usize = 0;
    
    for (parts) |part| {
        const content = part.content orelse part.content_json orelse "";
        @memcpy(result[offset..][0..content.len], content);
        offset += content.len;
    }
    
    return result;
}

/// Build the result JSON string
fn buildResultJson(
    allocator: std.mem.Allocator,
    per_message_tokens: []const i64,
    total_tokens: i64,
    message_hashes: []const u64,
    context_overhead: i64,
) error{OutOfMemory}![*:0]u8 {
    // Calculate buffer size needed
    // Format: {"per_message_tokens":[...],"total_message_tokens":N,"message_hashes":[...],"context_overhead_tokens":N}
    var buf_size: usize = 100; // Base size for JSON structure
    
    // Each number needs up to ~20 chars (for i64)
    buf_size += per_message_tokens.len * 25;
    buf_size += message_hashes.len * 25;
    
    var result = try allocator.alloc(u8, buf_size);
    
    var stream = std.io.fixedBufferStream(result);
    const writer = stream.writer();
    
    // Write JSON manually for efficiency and C-string compatibility
    writer.writeAll("{\"per_message_tokens\":[") catch unreachable;
    
    for (per_message_tokens, 0..) |tokens, i| {
        if (i > 0) writer.writeByte(',') catch unreachable;
        writer.print("{d}", .{tokens}) catch unreachable;
    }
    
    writer.writeAll("],\"total_message_tokens\":") catch unreachable;
    writer.print("{d}", .{total_tokens}) catch unreachable;
    
    writer.writeAll(",\"message_hashes\":[") catch unreachable;
    
    for (message_hashes, 0..) |hash, i| {
        if (i > 0) writer.writeByte(',') catch unreachable;
        // Print u64 hash as unsigned
        writer.print("{d}", .{hash}) catch unreachable;
    }
    
    writer.writeAll("],\"context_overhead_tokens\":") catch unreachable;
    writer.print("{d}", .{context_overhead}) catch unreachable;
    
    writer.writeAll("}\x00") catch unreachable;
    
    // Trim to actual size
    const actual_len = stream.getPos() catch unreachable;
    if (actual_len < buf_size) {
        result = try allocator.realloc(result, actual_len);
    }
    
    // Ensure null terminator is in place (last write was \x00)
    return @ptrCast(result.ptr);
}

/// Free a string returned by puppy_core_* functions.
export fn puppy_core_free_string(ptr: [*c]u8) void {
    if (ptr == null) return;
    std.heap.c_allocator.free(std.mem.span(ptr));
}

// ═══════════════════════════════════════════════════════════════════════════════
// Binary Protocol C ABI (Fast FFI)
// ═══════════════════════════════════════════════════════════════════════════════

/// Process messages using the binary protocol format.
/// This is significantly faster than JSON for large batches.
///
/// Input format:
///   [u32 message_count]
///   For each message:
///     [u8 role_len][role bytes]
///     [u32 parts_count]
///     For each part:
///       [u32 content_len][content bytes]
///
/// Output format:
///   [u32 count]
///   For each message:
///     [i64 tokens]
///     [u64 hash]
///   [i64 total_tokens]
///   [i64 overhead_tokens]
///
/// Caller must free output_data with puppy_core_free_bytes().
export fn puppy_core_process_messages_binary(
    handle: ?*anyopaque,
    input_data: [*]const u8,
    input_len: usize,
    system_prompt: [*:0]const u8,
    output_data: *[*]u8,
    output_len: *usize,
) PuppyCoreError {
    if (handle == null) return .invalid_argument;
    if (input_len == 0) return .invalid_argument;
    
    const ctx: *CoreContext = @ptrCast(@alignCast(handle.?));
    const allocator = ctx.allocator;
    
    // Slice the input data
    const input_slice = input_data[0..input_len];
    
    // Parse system prompt
    const sys_prompt_slice = std.mem.span(system_prompt);
    
    // Process using binary protocol
    var result = binary_protocol.processMessagesBinary(
        allocator,
        input_slice,
        sys_prompt_slice,
        &ctx.estimator,
        &ctx.hasher,
    ) catch |err| {
        return switch (err) {
            error.OutOfMemory => .out_of_memory,
            error.InvalidData => .invalid_argument,
        };
    };
    defer result.deinit(allocator);
    
    // Serialize result to binary format
    const serialized = binary_protocol.serializeResult(allocator, result) catch {
        return .out_of_memory;
    };
    
    // Return the buffer - caller must free with puppy_core_free_bytes
    output_data.* = serialized.ptr;
    output_len.* = serialized.len;
    
    return .success;
}

/// Free bytes returned by puppy_core_process_messages_binary.
/// Must be called with the same length returned in output_len.
export fn puppy_core_free_bytes(ptr: [*]u8, len: usize) void {
    if (len == 0) return;
    std.heap.c_allocator.free(ptr[0..len]);
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
    _ = puppy_core_process_messages_binary;
    _ = puppy_core_free_bytes;
}

test "concatenateParts - empty parts" {
    const allocator = std.testing.allocator;
    
    const empty_parts: []const MessagePart = &.{};
    const result = try concatenateParts(allocator, empty_parts);
    defer allocator.free(result);
    
    try std.testing.expectEqualStrings("", result);
}

test "concatenateParts - single part" {
    const allocator = std.testing.allocator;
    
    const parts = &[_]MessagePart{
        .{ .content = "Hello", .content_json = null },
    };
    const result = try concatenateParts(allocator, parts);
    defer allocator.free(result);
    
    try std.testing.expectEqualStrings("Hello", result);
}

test "concatenateParts - multiple parts" {
    const allocator = std.testing.allocator;
    
    const parts = &[_]MessagePart{
        .{ .content = "Hello ", .content_json = null },
        .{ .content = null, .content_json = "World" },
        .{ .content = "!", .content_json = null },
    };
    const result = try concatenateParts(allocator, parts);
    defer allocator.free(result);
    
    try std.testing.expectEqualStrings("Hello World!", result);
}

test "buildResultJson - basic output" {
    const allocator = std.testing.allocator;
    
    const per_message_tokens = &[_]i64{ 10, 20, 30 };
    const total_tokens: i64 = 60;
    const message_hashes = &[_]u64{ 123, 456, 789 };
    const context_overhead: i64 = 50;
    
    const result = try buildResultJson(
        allocator,
        per_message_tokens,
        total_tokens,
        message_hashes,
        context_overhead,
    );
    defer allocator.free(std.mem.span(result));
    
    // Verify result is valid JSON
    const result_slice = std.mem.span(result);
    try std.testing.expect(result_slice.len > 0);
    try std.testing.expect(std.mem.endsWith(u8, result_slice, "}"));
    
    // Verify all expected fields are present
    try std.testing.expect(std.mem.indexOf(u8, result_slice, "per_message_tokens") != null);
    try std.testing.expect(std.mem.indexOf(u8, result_slice, "total_message_tokens") != null);
    try std.testing.expect(std.mem.indexOf(u8, result_slice, "message_hashes") != null);
    try std.testing.expect(std.mem.indexOf(u8, result_slice, "context_overhead_tokens") != null);
}

test "puppy_core_process_messages - basic flow" {
    const allocator = std.testing.allocator;
    
    // Create context
    var ctx = CoreContext{
        .allocator = allocator,
        .estimator = TokenEstimator.init(allocator),
        .hasher = MessageHasher.init(allocator),
    };
    defer ctx.deinit();
    
    // Test with valid input
    const messages_json = 
        \\[{"role":"user","parts":[{"content":"Hello world"}]}]
    ;
    const system_prompt = "You are helpful.";
    
    var output: [*:0]u8 = undefined;
    const result = puppy_core_process_messages(
        @ptrCast(&ctx),
        messages_json,
        system_prompt,
        &output,
    );
    
    try std.testing.expectEqual(PuppyCoreError.success, result);
    
    // Free the output
    defer allocator.free(std.mem.span(output));
    
    const output_slice = std.mem.span(output);
    try std.testing.expect(output_slice.len > 0);
    // Verify JSON structure
    try std.testing.expect(std.mem.startsWith(u8, output_slice, "{"));
    try std.testing.expect(std.mem.endsWith(u8, output_slice, "}"));
}

test "puppy_core_process_messages - null handle returns error" {
    var output: [*:0]u8 = undefined;
    const result = puppy_core_process_messages(
        null,
        "[]",
        "",
        &output,
    );
    
    try std.testing.expectEqual(PuppyCoreError.invalid_argument, result);
}

test "puppy_core_process_messages - empty messages returns error" {
    const allocator = std.testing.allocator;
    
    var ctx = CoreContext{
        .allocator = allocator,
        .estimator = TokenEstimator.init(allocator),
        .hasher = MessageHasher.init(allocator),
    };
    defer ctx.deinit();
    
    var output: [*:0]u8 = undefined;
    const result = puppy_core_process_messages(
        @ptrCast(&ctx),
        "[]",
        "",
        &output,
    );
    
    try std.testing.expectEqual(PuppyCoreError.invalid_argument, result);
}

test "puppy_core_process_messages - invalid JSON returns error" {
    const allocator = std.testing.allocator;
    
    var ctx = CoreContext{
        .allocator = allocator,
        .estimator = TokenEstimator.init(allocator),
        .hasher = MessageHasher.init(allocator),
    };
    defer ctx.deinit();
    
    var output: [*:0]u8 = undefined;
    const result = puppy_core_process_messages(
        @ptrCast(&ctx),
        "not valid json",
        "",
        &output,
    );
    
    try std.testing.expectEqual(PuppyCoreError.invalid_argument, result);
}
