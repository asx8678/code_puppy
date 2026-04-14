// ═══════════════════════════════════════════════════════════════════════════════
// Pruning
// ═══════════════════════════════════════════════════════════════════════════════
//
// Migration from: code_puppy_core/src/pruning.rs
//
// Implements message pruning strategies for managing LLM context windows:
//   - Token-based truncation
//   - Smart preservation of pending tool calls
//   - Summarization-aware splitting
//
// Zig vs Rust differences:
//   - Error unions replace Result<T, E>
//   - Slice manipulation uses Zig's more explicit bounds checking

const std = @import("std");

// ═══════════════════════════════════════════════════════════════════════════════
// PruningStrategy
// ═══════════════════════════════════════════════════════════════════════════════

pub const PruningStrategy = enum {
    /// Keep first N and last N messages, drop the middle
    fifo_with_tail,
    
    /// Keep recent messages, summarize old ones
    summarization_aware,
    
    /// Keep messages with pending tool calls
    tool_call_aware,
    
    /// Custom user-defined logic
    custom,
};

pub const PruningResult = struct {
    /// Indices of messages to keep (in original order)
    surviving_indices: []usize,
    
    /// Number of messages dropped
    dropped_count: usize,
    
    /// Whether any pending tool calls were detected
    had_pending_tool_calls: bool,
    
    /// Count of pending tool calls
    pending_tool_call_count: usize,
    
    pub fn deinit(self: *PruningResult, allocator: std.mem.Allocator) void {
        allocator.free(self.surviving_indices);
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Configuration
// ═══════════════════════════════════════════════════════════════════════════════

pub const PruningConfig = struct {
    /// Maximum tokens per message (filter threshold)
    max_tokens_per_message: i64 = 50000,
    
    /// Maximum total context window
    max_total_tokens: i64 = 200000,
    
    /// Number of messages to always keep at start
    keep_first_n: usize = 1,
    
    /// Number of messages to always keep at end
    keep_last_n: usize = 10,
    
    /// Preserve messages with pending tool calls
    preserve_tool_calls: bool = true,
    
    /// Don't drop system messages
    protect_system: bool = true,
};

pub const MessageMetadata = struct {
    role: []const u8,
    token_count: i64,
    has_pending_tool_calls: bool,
    is_system_message: bool,
};

// ═══════════════════════════════════════════════════════════════════════════════
// Main Pruning Functions
// ═══════════════════════════════════════════════════════════════════════════════

/// Prune messages based on token limits, returning indices to keep
pub fn pruneAndFilter(
    allocator: std.mem.Allocator,
    messages: []const MessageMetadata,
    per_message_tokens: []const i64,
    config: PruningConfig,
) error{OutOfMemory}!PruningResult {
    var surviving = std.ArrayList(usize).init(allocator);
    errdefer surviving.deinit();
    
    var pending_tool_count: usize = 0;
    var had_pending_tools = false;
    
    // First pass: identify messages to keep and count tool calls
    for (messages, 0..) |msg, i| {
        // Always protect system messages
        if (config.protect_system and msg.is_system_message) {
            try surviving.append(i);
            continue;
        }
        
        // Preserve pending tool calls
        if (config.preserve_tool_calls and msg.has_pending_tool_calls) {
            try surviving.append(i);
            pending_tool_count += 1;
            had_pending_tools = true;
            continue;
        }
        
        // Filter oversized messages
        if (per_message_tokens[i] > config.max_tokens_per_message) {
            continue;  // Skip this message
        }
        
        try surviving.append(i);
    }
    
    // Second pass: apply FIFO with tail preservation if still over limit
    const total_tokens = computeTotalTokens(surviving.items, per_message_tokens);
    
    if (total_tokens > config.max_total_tokens) {
        const new_surviving = try applyFifoWithTail(
            allocator,
            surviving.items,
            per_message_tokens,
            config,
            total_tokens,
        );
        surviving.deinit();
        surviving = new_surviving;
    }
    
    return PruningResult{
        .surviving_indices = try surviving.toOwnedSlice(),
        .dropped_count = messages.len - surviving.items.len,
        .had_pending_tool_calls = had_pending_tools,
        .pending_tool_call_count = pending_tool_count,
    };
}

/// Get truncation indices for removing oldest messages first
/// Returns indices to KEEP (not to drop)
pub fn truncationIndices(
    allocator: std.mem.Allocator,
    per_message_tokens: []const i64,
    protected_tokens: i64,
    second_has_thinking: bool,  // Claude thinking mode flag
) error{OutOfMemory}![]usize {
    // Simple heuristic: truncate from beginning until under limit
    var total: i64 = 0;
    for (per_message_tokens) |tokens| {
        total += tokens;
    }
    
    total += protected_tokens;
    
    // Thinking adds overhead
    if (second_has_thinking) {
        total += 1000;  // Approximate thinking overhead
    }
    
    var keep_from: usize = 0;
    var current: i64 = total;
    
    // Keep dropping from the start until under limit
    // But always keep at least 2 messages
    const max_context: i64 = 180000;  // Approximate Claude limit
    
    while (current > max_context and keep_from < per_message_tokens.len - 2) {
        current -= per_message_tokens[keep_from];
        keep_from += 1;
    }
    
    // Return indices to keep
    const result = try allocator.alloc(usize, per_message_tokens.len - keep_from);
    for (result, keep_from..) |*idx, i| {
        idx.* = i;
    }
    
    return result;
}

/// Split messages into summarize vs protect sets
pub const SplitResult = struct {
    /// Indices of messages to summarize
    summarize_indices: []usize,
    
    /// Indices of messages to protect (keep verbatim)
    protected_indices: []usize,
    
    /// Token count of protected messages
    protected_token_count: i64,
    
    pub fn deinit(self: *SplitResult, allocator: std.mem.Allocator) void {
        allocator.free(self.summarize_indices);
        allocator.free(self.protected_indices);
    }
};

pub fn splitForSummarization(
    allocator: std.mem.Allocator,
    per_message_tokens: []const i64,
    tool_call_ids_per_message: []const []const ToolCallRef,
    protected_tokens_limit: i64,
) error{OutOfMemory}!SplitResult {
    var summarize = std.ArrayList(usize).init(allocator);
    errdefer summarize.deinit();
    
    var protected = std.ArrayList(usize).init(allocator);
    errdefer protected.deinit();
    
    var current_protected_tokens: i64 = 0;
    
    // Work backwards from most recent
    var i: usize = per_message_tokens.len;
    while (i > 0) : (i -= 1) {
        const idx = i - 1;
        const tokens = per_message_tokens[idx];
        const tool_calls = tool_call_ids_per_message[idx];
        
        // If has tool calls, always protect (can't summarize tool calls)
        if (tool_calls.len > 0) {
            try protected.insert(0, idx);
            current_protected_tokens += tokens;
            continue;
        }
        
        // If still under limit, protect this message
        if (current_protected_tokens + tokens <= protected_tokens_limit) {
            try protected.insert(0, idx);
            current_protected_tokens += tokens;
        } else {
            // Summarize everything older
            try summarize.insert(0, idx);
        }
    }
    
    return SplitResult{
        .summarize_indices = try summarize.toOwnedSlice(),
        .protected_indices = try protected.toOwnedSlice(),
        .protected_token_count = current_protected_tokens,
    };
}

pub const ToolCallRef = struct {
    id: []const u8,
    name: []const u8,
};

// ═══════════════════════════════════════════════════════════════════════════════
// Helper Functions
// ═══════════════════════════════════════════════════════════════════════════════

fn computeTotalTokens(indices: []const usize, per_message_tokens: []const i64) i64 {
    var total: i64 = 0;
    for (indices) |idx| {
        if (idx < per_message_tokens.len) {
            total += per_message_tokens[idx];
        }
    }
    return total;
}

fn applyFifoWithTail(
    allocator: std.mem.Allocator,
    current_indices: []const usize,
    per_message_tokens: []const i64,
    config: PruningConfig,
    _current_total: i64,
) error{OutOfMemory}!std.ArrayList(usize) {
    _ = _current_total;  // Silences unused parameter warning
    var result = std.ArrayList(usize).init(allocator);
    errdefer result.deinit();
    
    // Determine which messages to keep
    const total_messages = current_indices.len;
    const keep_first = @min(config.keep_first_n, total_messages);
    const keep_last = @min(config.keep_last_n, total_messages);
    
    // If not enough room for both, prioritize last
    if (keep_first + keep_last > total_messages) {
        // Just keep last N
        const start = total_messages - keep_last;
        try result.appendSlice(current_indices[start..]);
    } else {
        // Keep first N and last N, drop middle
        try result.appendSlice(current_indices[0..keep_first]);
        
        // Calculate middle that needs to stay under limit
        var remaining_budget = config.max_total_tokens - 
            computeTotalTokens(current_indices[0..keep_first], per_message_tokens) -
            computeTotalTokens(current_indices[total_messages - keep_last..], per_message_tokens);
        
        // Add from the "last" section first (most recent)
        var i: usize = total_messages;
        while (i > total_messages - keep_last) : (i -= 1) {
            const idx = current_indices[i - 1];
            const tokens = per_message_tokens[idx];
            
            if (remaining_budget >= tokens) {
                // Insert at beginning of last section
                try result.append(idx);
                remaining_budget -= tokens;
            }
        }
        
        // Sort to maintain order
        std.mem.sort(usize, result.items, {}, std.sort.asc(usize));
    }
    
    return result;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "pruneAndFilter basic" {
    const allocator = std.testing.allocator;
    
    const messages = &[_]MessageMetadata{
        .{ .role = "system", .token_count = 100, .has_pending_tool_calls = false, .is_system_message = true },
        .{ .role = "user", .token_count = 50, .has_pending_tool_calls = false, .is_system_message = false },
        .{ .role = "assistant", .token_count = 1000, .has_pending_tool_calls = false, .is_system_message = false },
    };
    
    const tokens = &[_]i64{ 100, 50, 1000 };
    
    const config = PruningConfig{
        .max_tokens_per_message = 500,
        .protect_system = true,
    };
    
    var result = try pruneAndFilter(allocator, messages, tokens, config);
    defer result.deinit(allocator);
    
    // System should survive, oversized assistant should be dropped
    try std.testing.expectEqual(@as(usize, 2), result.surviving_indices.len);
    try std.testing.expectEqual(@as(usize, 0), result.surviving_indices[0]);  // system
    try std.testing.expectEqual(@as(usize, 1), result.surviving_indices[1]);  // user
}

test "truncationIndices" {
    const allocator = std.testing.allocator;
    
    const tokens = &[_]i64{ 100000, 100000, 10000 };
    
    const result = try truncationIndices(allocator, tokens, 0, false);
    defer allocator.free(result);
    
    // Should keep at least the last 2 messages
    try std.testing.expect(result.len >= 2);
}

test "splitForSummarization" {
    const allocator = std.testing.allocator;
    
    const tokens = &[_]i64{ 100, 100, 100, 100 };
    const tool_calls = &[_][]const ToolCallRef{
        &.{}, &.{}, &.{}, &.{},
    };
    
    var result = try splitForSummarization(allocator, tokens, tool_calls, 250);
    defer result.deinit(allocator);
    
    // With 250 token limit, should protect ~2 most recent, summarize older
    try std.testing.expect(result.protected_indices.len <= 3);
}
