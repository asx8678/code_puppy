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
//   - Symmetric-difference tool call mismatch detection
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
// Message/Part Types (matching Rust types::Message and types::MessagePart)
// ═══════════════════════════════════════════════════════════════════════════════

pub const MessagePart = struct {
    part_kind: []const u8,
    content: ?[]const u8 = null,
    content_json: ?[]const u8 = null,
    tool_call_id: ?[]const u8 = null,
    tool_name: ?[]const u8 = null,
    args: ?[]const u8 = null,
};

pub const Message = struct {
    kind: []const u8,
    role: ?[]const u8 = null,
    instructions: ?[]const u8 = null,
    parts: []const MessagePart,
};

// ═══════════════════════════════════════════════════════════════════════════════
// Main Pruning Functions
// ═══════════════════════════════════════════════════════════════════════════════

/// Hash a string to u64 for set operations
fn hashString(str: []const u8) u64 {
    var hasher = std.hash.XxHash64.init(0);
    hasher.update(str);
    return hasher.final();
}

/// Find mismatched tool call IDs using symmetric difference.
/// Returns a hash set of tool_call_id hashes that appear in only one of:
///   - tool-call parts (call_ids)
///   - tool-return/tool_return parts (return_ids)
fn findMismatchedToolCallIds(
    allocator: std.mem.Allocator,
    messages: []const Message,
) error{OutOfMemory}!std.AutoHashMap(u64, void) {
    var call_ids = std.AutoHashMap(u64, void).init(allocator);
    defer call_ids.deinit();
    
    var return_ids = std.AutoHashMap(u64, void).init(allocator);
    defer return_ids.deinit();
    
    // Collect all tool call IDs from messages
    for (messages) |msg| {
        for (msg.parts) |part| {
            if (part.tool_call_id) |id| {
                if (id.len == 0) continue;
                const hash = hashString(id);
                if (std.mem.eql(u8, part.part_kind, "tool-call")) {
                    try call_ids.put(hash, {});
                } else if (std.mem.eql(u8, part.part_kind, "tool-return") or 
                           std.mem.eql(u8, part.part_kind, "tool_return")) {
                    try return_ids.put(hash, {});
                }
            }
        }
    }
    
    // Symmetric difference: items in exactly one set
    var mismatched = std.AutoHashMap(u64, void).init(allocator);
    
    // Items in call_ids but not in return_ids
    var call_iter = call_ids.keyIterator();
    while (call_iter.next()) |key| {
        if (!return_ids.contains(key.*)) {
            try mismatched.put(key.*, {});
        }
    }
    
    // Items in return_ids but not in call_ids
    var ret_iter = return_ids.keyIterator();
    while (ret_iter.next()) |key| {
        if (!call_ids.contains(key.*)) {
            try mismatched.put(key.*, {});
        }
    }
    
    return mismatched;
}

/// Estimate tokens for a message part (simplified - counts characters)
fn estimateTokensForPart(part: MessagePart) i64 {
    var total: usize = 0;
    if (part.content) |c| total += c.len;
    if (part.content_json) |c| total += c.len;
    if (part.tool_name) |n| total += n.len;
    if (part.args) |a| total += a.len;
    // Rough approximation: 1 token per 4 characters
    return @intCast(total / 4 + 1);
}

/// Check if a message has any part with a mismatched tool_call_id
fn hasMismatchedToolCallId(msg: Message, mismatched: std.AutoHashMap(u64, void)) bool {
    for (msg.parts) |part| {
        if (part.tool_call_id) |id| {
            const hash = hashString(id);
            if (mismatched.contains(hash)) {
                return true;
            }
        }
    }
    return false;
}

/// Check if message is an empty thinking message (should be dropped)
fn isEmptyThinkingMessage(msg: Message) bool {
    if (msg.parts.len != 1) return false;
    const part = msg.parts[0];
    if (!std.mem.eql(u8, part.part_kind, "thinking")) return false;
    if (part.content) |c| return c.len == 0;
    return true; // null content counts as empty
}

/// Prune messages based on token limits and tool call mismatch detection.
/// This is the core implementation matching Rust's prune_and_filter_core.
pub fn pruneAndFilterMessages(
    allocator: std.mem.Allocator,
    messages: []const Message,
    max_tokens_per_message: i64,
) error{OutOfMemory}!PruningResult {
    // Find mismatched tool call IDs
    var mismatched = try findMismatchedToolCallIds(allocator, messages);
    defer mismatched.deinit();
    
    var surviving: std.ArrayList(usize) = .empty;
    defer surviving.deinit(allocator);
    
    var pending_tool_count: usize = 0;
    var had_pending_tools = false;
    
    // First pass: identify messages to keep
    for (messages, 0..) |msg, i| {
        // Skip messages with mismatched tool call IDs
        if (hasMismatchedToolCallId(msg, mismatched)) {
            continue;
        }
        
        // Calculate tokens for this message
        var tokens: i64 = 0;
        for (msg.parts) |part| {
            tokens += estimateTokensForPart(part);
        }
        
        // Filter oversized messages
        if (tokens > max_tokens_per_message) {
            continue;
        }
        
        // Drop empty thinking messages
        if (isEmptyThinkingMessage(msg)) {
            continue;
        }
        
        try surviving.append(allocator, i);
    }
    
    // Count pending tool calls (calls without returns)
    for (messages) |msg| {
        for (msg.parts) |part| {
            if (std.mem.eql(u8, part.part_kind, "tool-call")) {
                if (part.tool_call_id) |id| {
                    const hash = hashString(id);
                    // If this ID is in mismatched, it's a pending call
                    if (mismatched.contains(hash)) {
                        pending_tool_count += 1;
                        had_pending_tools = true;
                    }
                }
            }
        }
    }
    
    return PruningResult{
        .surviving_indices = try surviving.toOwnedSlice(allocator),
        .dropped_count = messages.len - surviving.items.len,
        .had_pending_tool_calls = had_pending_tools,
        .pending_tool_call_count = pending_tool_count,
    };
}

/// Legacy pruneAndFilter using MessageMetadata (for backward compatibility)
pub fn pruneAndFilter(
    allocator: std.mem.Allocator,
    messages: []const MessageMetadata,
    per_message_tokens: []const i64,
    config: PruningConfig,
) error{OutOfMemory}!PruningResult {
    var surviving: std.ArrayList(usize) = .empty;
    defer surviving.deinit(allocator);
    
    var pending_tool_count: usize = 0;
    var had_pending_tools = false;
    
    // First pass: identify messages to keep and count tool calls
    for (messages, 0..) |msg, i| {
        // Always protect system messages
        if (config.protect_system and msg.is_system_message) {
            try surviving.append(allocator, i);
            continue;
        }
        
        // Preserve pending tool calls
        if (config.preserve_tool_calls and msg.has_pending_tool_calls) {
            try surviving.append(allocator, i);
            pending_tool_count += 1;
            had_pending_tools = true;
            continue;
        }
        
        // Filter oversized messages
        if (per_message_tokens[i] > config.max_tokens_per_message) {
            continue;  // Skip this message
        }
        
        try surviving.append(allocator, i);
    }
    
    // Second pass: apply FIFO with tail preservation if still over limit
    const total_tokens = computeTotalTokens(surviving.items, per_message_tokens);
    
    var surviving_slice = try surviving.toOwnedSlice(allocator);
    
    if (total_tokens > config.max_total_tokens) {
        allocator.free(surviving_slice);
        surviving_slice = try applyFifoWithTail(
            allocator,
            surviving_slice,
            per_message_tokens,
            config,
            total_tokens,
        );
    }
    
    return PruningResult{
        .surviving_indices = surviving_slice,
        .dropped_count = messages.len - surviving_slice.len,
        .had_pending_tool_calls = had_pending_tools,
        .pending_tool_call_count = pending_tool_count,
    };
}

/// Get truncation indices for removing oldest messages first.
/// Returns indices to KEEP (not to drop).
/// 
/// Matching Rust's truncation_indices_impl:
/// 1. Always keeps index 0
/// 2. If second_has_thinking is true, keeps index 1
/// 3. Walks backwards from end, adding messages until budget exhausted
pub fn truncationIndices(
    allocator: std.mem.Allocator,
    per_message_tokens: []const i64,
    protected_tokens: i64,
    second_has_thinking: bool,  // Claude thinking mode flag
) error{OutOfMemory}![]usize {
    if (per_message_tokens.len == 0) {
        return &[_]usize{};
    }
    
    var result: std.ArrayList(usize) = .empty;
    defer result.deinit(allocator);
    
    // Always keep first message
    try result.append(allocator, 0);
    var used_tokens: i64 = per_message_tokens[0];
    
    // Optionally keep second message if it has thinking
    const start_idx: usize = if (second_has_thinking and per_message_tokens.len > 1) blk: {
        try result.append(allocator, 1);
        used_tokens += per_message_tokens[1];
        break :blk 2;
    } else 1;
    
    // Walk backwards from end, filling budget
    var idx: usize = per_message_tokens.len;
    while (idx > start_idx) {
        idx -= 1;
        if (used_tokens + per_message_tokens[idx] <= protected_tokens) {
            try result.append(allocator, idx);
            used_tokens += per_message_tokens[idx];
        } else {
            break;
        }
    }
    
    // Sort indices ascending
    std.mem.sort(usize, result.items, {}, std.sort.asc(usize));
    
    return try result.toOwnedSlice(allocator);
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

/// Extract tool call IDs with their kinds from messages for pair boundary adjustment.
fn extractToolCallIdsWithKinds(
    allocator: std.mem.Allocator,
    msgs: []const Message,
) error{OutOfMemory}![][]const ToolCallIdWithKind {
    var result = try allocator.alloc([]const ToolCallIdWithKind, msgs.len);
    errdefer {
        for (result) |slice| allocator.free(slice);
        allocator.free(result);
    }
    
    for (msgs, 0..) |msg, i| {
        var list: std.ArrayList(ToolCallIdWithKind) = .empty;
        defer list.deinit(allocator);
        
        for (msg.parts) |part| {
            const is_tool_related = std.mem.eql(u8, part.part_kind, "tool-call") or
                std.mem.eql(u8, part.part_kind, "tool-return") or
                std.mem.eql(u8, part.part_kind, "tool_return");
            
            if (is_tool_related) {
                if (part.tool_call_id) |id| {
                    try list.append(allocator, .{
                        .id = id,
                        .kind = part.part_kind,
                    });
                }
            }
        }
        
        result[i] = try list.toOwnedSlice(allocator);
    }
    
    return result;
}

/// Free the result of extractToolCallIdsWithKinds
fn freeToolCallIdsWithKinds(
    allocator: std.mem.Allocator,
    tool_calls: [][]const ToolCallIdWithKind,
) void {
    for (tool_calls) |slice| allocator.free(slice);
    allocator.free(tool_calls);
}

/// Adjust split boundary to keep tool-call/return pairs together.
/// If a tool-return is in the protected zone, its matching tool-call must also be protected.
fn adjustSplitBoundaryForToolPairs(
    initial_adj: usize,
    tool_call_ids_per_message: []const []const ToolCallIdWithKind,
) usize {
    if (initial_adj <= 1 or tool_call_ids_per_message.len == 0) {
        return initial_adj;
    }
    
    // Collect return IDs from protected zone
    var ret_ids = std.AutoHashMap(u64, void).init(std.heap.page_allocator);
    defer ret_ids.deinit();
    
    for (tool_call_ids_per_message[initial_adj..]) |tool_calls| {
        for (tool_calls) |tc| {
            if (std.mem.eql(u8, tc.kind, "tool-return") or 
                std.mem.eql(u8, tc.kind, "tool_return")) {
                // Ignore errors - page_allocator shouldn't fail
                ret_ids.put(hashString(tc.id), {}) catch {};
            }
        }
    }
    
    // Walk backwards and extend boundary if we find matching tool-calls
    var adj = initial_adj;
    var i: usize = initial_adj;
    while (i > 1) {
        i -= 1;
        if (i >= tool_call_ids_per_message.len) continue;
        
        var has_matching_call = false;
        for (tool_call_ids_per_message[i]) |tc| {
            if (std.mem.eql(u8, tc.kind, "tool-call") or 
                std.mem.eql(u8, tc.kind, "tool_call")) {
                if (ret_ids.contains(hashString(tc.id))) {
                    has_matching_call = true;
                    break;
                }
            }
        }
        
        if (has_matching_call) {
            // Extend boundary to include this message
            adj = i;
            // Also add its returns to the set for further backward checking
            for (tool_call_ids_per_message[i]) |tc| {
                if (std.mem.eql(u8, tc.kind, "tool-return") or 
                    std.mem.eql(u8, tc.kind, "tool_return")) {
                    ret_ids.put(hashString(tc.id), {}) catch {};
                }
            }
        } else {
            break;
        }
    }
    
    return adj;
}

/// Core implementation with Message-based tool call extraction.
pub fn splitForSummarizationCore(
    allocator: std.mem.Allocator,
    per_message_tokens: []const i64,
    msgs: []const Message,
    protected_tokens_limit: i64,
) error{OutOfMemory}!SplitResult {
    if (per_message_tokens.len <= 1) {
        const protected_indices = try allocator.alloc(usize, per_message_tokens.len);
        for (protected_indices, 0..) |*idx, j| {
            idx.* = j;
        }
        var total_tokens: i64 = 0;
        for (per_message_tokens) |t| total_tokens += t;
        
        return SplitResult{
            .summarize_indices = &[_]usize{},
            .protected_indices = protected_indices,
            .protected_token_count = total_tokens,
        };
    }
    
    // Extract tool call IDs from messages
    const tool_call_ids_per_message = try extractToolCallIdsWithKinds(allocator, msgs);
    defer freeToolCallIdsWithKinds(allocator, tool_call_ids_per_message);
    
    var prot_tok: i64 = per_message_tokens[0];
    var prot_tail: std.ArrayList(usize) = .empty;
    defer prot_tail.deinit(allocator);
    
    // Work backwards from most recent, filling protected zone
    var idx: usize = per_message_tokens.len;
    while (idx > 1) {
        idx -= 1;
        if (prot_tok + per_message_tokens[idx] > protected_tokens_limit) {
            break;
        }
        try prot_tail.append(allocator, idx);
        prot_tok += per_message_tokens[idx];
    }
    
    std.mem.sort(usize, prot_tail.items, {}, std.sort.asc(usize));
    
    // Calculate initial boundary
    const prot_start = if (prot_tail.items.len > 0) 
        prot_tail.items[0] 
    else 
        per_message_tokens.len;
    
    // Adjust boundary to keep tool-call/return pairs together
    const adj = adjustSplitBoundaryForToolPairs(prot_start, tool_call_ids_per_message);
    
    // Build result indices
    const summarize = try allocator.alloc(usize, if (adj > 1) adj - 1 else 0);
    for (summarize, 0..) |*out_idx, j| {
        out_idx.* = j + 1;  // Start from 1, skip system message at 0
    }
    
    var protected: std.ArrayList(usize) = .empty;
    errdefer protected.deinit(allocator);
    try protected.append(allocator, 0);  // Always protect first message
    for (adj..per_message_tokens.len) |pidx| {
        try protected.append(allocator, pidx);
    }
    
    // Calculate protected token count
    var protected_token_count: i64 = 0;
    for (protected.items) |pidx| {
        protected_token_count += per_message_tokens[pidx];
    }
    
    return SplitResult{
        .summarize_indices = summarize,
        .protected_indices = try protected.toOwnedSlice(allocator),
        .protected_token_count = protected_token_count,
    };
}

/// Legacy splitForSummarization using pre-extracted tool_call_ids (backward-compatible)
pub fn splitForSummarization(
    allocator: std.mem.Allocator,
    per_message_tokens: []const i64,
    tool_call_ids_per_message: []const []const ToolCallRef,
    protected_tokens_limit: i64,
) error{OutOfMemory}!SplitResult {
    var summarize: std.ArrayList(usize) = .empty;
    defer summarize.deinit(allocator);
    
    var protected: std.ArrayList(usize) = .empty;
    defer protected.deinit(allocator);
    
    var current_protected_tokens: i64 = 0;
    
    // Work backwards from most recent
    var idx: usize = per_message_tokens.len;
    while (idx > 0) {
        idx -= 1;
        const tokens = per_message_tokens[idx];
        const tool_calls = tool_call_ids_per_message[idx];
        
        // If has tool calls, always protect (can't summarize tool calls)
        if (tool_calls.len > 0) {
            try protected.insert(allocator, 0, idx);
            current_protected_tokens += tokens;
            continue;
        }
        
        // If still under limit, protect this message
        if (current_protected_tokens + tokens <= protected_tokens_limit) {
            try protected.insert(allocator, 0, idx);
            current_protected_tokens += tokens;
        } else {
            // Summarize everything older
            try summarize.insert(allocator, 0, idx);
        }
    }
    
    return SplitResult{
        .summarize_indices = try summarize.toOwnedSlice(allocator),
        .protected_indices = try protected.toOwnedSlice(allocator),
        .protected_token_count = current_protected_tokens,
    };
}

pub const ToolCallRef = struct {
    id: []const u8,
    name: []const u8,
};

/// Tool call ID with its kind for pair boundary adjustment
pub const ToolCallIdWithKind = struct {
    id: []const u8,
    kind: []const u8,
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
) error{OutOfMemory}![]usize {
    _ = _current_total;  // Silences unused parameter warning
    
    // Determine which messages to keep
    const total_messages = current_indices.len;
    const keep_first = @min(config.keep_first_n, total_messages);
    const keep_last = @min(config.keep_last_n, total_messages);
    
    // If not enough room for both, prioritize last
    if (keep_first + keep_last > total_messages) {
        // Just keep last N
        const start = total_messages - keep_last;
        return try allocator.dupe(usize, current_indices[start..]);
    }
    
    var result: std.ArrayList(usize) = .empty;
    defer result.deinit(allocator);
    
    // Keep first N and last N, drop middle
    try result.appendSlice(allocator, current_indices[0..keep_first]);
    
    // Calculate middle that needs to stay under limit
    var remaining_budget = config.max_total_tokens - 
        computeTotalTokens(current_indices[0..keep_first], per_message_tokens) -
        computeTotalTokens(current_indices[total_messages - keep_last..], per_message_tokens);
    
    // Add from the "last" section first (most recent)
    var idx: usize = total_messages;
    while (idx > total_messages - keep_last) : (idx -= 1) {
        const i = current_indices[idx - 1];
        const tokens = per_message_tokens[i];
        
        if (remaining_budget >= tokens) {
            // Insert at beginning of last section
            try result.append(allocator, i);
            remaining_budget -= tokens;
        }
    }
    
    // Sort to maintain order
    std.mem.sort(usize, result.items, {}, std.sort.asc(usize));
    
    return try result.toOwnedSlice(allocator);
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

test "truncationIndices keeps first message" {
    const allocator = std.testing.allocator;
    
    const tokens = &[_]i64{ 100, 200, 300, 400, 500 };
    
    const result = try truncationIndices(allocator, tokens, 600, false);
    defer allocator.free(result);
    
    // Always keeps first message
    try std.testing.expectEqual(@as(usize, 0), result[0]);
    // Should include some tail messages
    try std.testing.expect(std.mem.indexOf(usize, result, &[_]usize{4}) != null);
}

test "truncationIndices keeps second message with thinking" {
    const allocator = std.testing.allocator;
    
    const tokens = &[_]i64{ 100, 200, 300, 400 };
    
    const result = try truncationIndices(allocator, tokens, 500, true);
    defer allocator.free(result);
    
    // With thinking=true, should keep messages 0 and 1
    try std.testing.expect(std.mem.indexOf(usize, result, &[_]usize{0}) != null);
    try std.testing.expect(std.mem.indexOf(usize, result, &[_]usize{1}) != null);
}

test "truncationIndices empty input" {
    const allocator = std.testing.allocator;
    
    const result = try truncationIndices(allocator, &[_]i64{}, 1000, false);
    defer allocator.free(result);
    
    try std.testing.expectEqual(@as(usize, 0), result.len);
}

test "truncationIndices respects budget" {
    const allocator = std.testing.allocator;
    
    // Total = 600, budget = 400
    // Keeps first (100), then walks from back trying to fit more
    const tokens = &[_]i64{ 100, 200, 300 };
    
    const result = try truncationIndices(allocator, tokens, 400, false);
    defer allocator.free(result);
    
    // With 400 budget: keeps first (100) + message 2 (300) = 400
    // Can't fit message 1 (200) because 400 + 200 > 400
    // So keeps messages 0 and 2
    try std.testing.expectEqual(@as(usize, 2), result.len);
    try std.testing.expectEqual(@as(usize, 0), result[0]);  // first
    try std.testing.expectEqual(@as(usize, 2), result[1]);  // last
}

test "splitForSummarization legacy" {
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

test "splitForSummarizationCore protects tool calls" {
    const allocator = std.testing.allocator;
    
    // Setup: message 0 (system), messages 1-2 have tool calls, message 3 (user)
    const tokens = &[_]i64{ 50, 100, 100, 50 };
    
    const msgs = &[_]Message{
        .{ .kind = "request", .role = "system", .parts = &[_]MessagePart{
            .{ .part_kind = "text", .content = "System prompt" },
        }},
        .{ .kind = "request", .role = "assistant", .parts = &[_]MessagePart{
            .{ .part_kind = "tool-call", .tool_call_id = "call_1", .tool_name = "foo" },
        }},
        .{ .kind = "request", .role = "user", .parts = &[_]MessagePart{
            .{ .part_kind = "tool-return", .tool_call_id = "call_1", .content = "result" },
        }},
        .{ .kind = "request", .role = "user", .parts = &[_]MessagePart{
            .{ .part_kind = "text", .content = "Hello" },
        }},
    };
    
    var result = try splitForSummarizationCore(allocator, tokens, msgs, 300);
    defer result.deinit(allocator);
    
    // Messages with tool calls should be protected
    // Also boundary adjustment should keep pairs together
    try std.testing.expect(std.mem.indexOf(usize, result.protected_indices, &[_]usize{0}) != null);
}

test "splitForSummarizationCore boundary adjustment" {
    const allocator = std.testing.allocator;
    
    // Setup: tool-return is in protected zone, tool-call is in summarize zone
    // Boundary should be extended to include the tool-call
    const tokens = &[_]i64{ 50, 100, 100, 50, 50 };
    
    const msgs = &[_]Message{
        .{ .kind = "request", .role = "system", .parts = &[_]MessagePart{
            .{ .part_kind = "text", .content = "System" },
        }},
        .{ .kind = "request", .role = "assistant", .parts = &[_]MessagePart{
            .{ .part_kind = "text", .content = "Some response" },
        }},
        .{ .kind = "request", .role = "assistant", .parts = &[_]MessagePart{
            .{ .part_kind = "tool-call", .tool_call_id = "call_1", .tool_name = "foo" },
        }},
        .{ .kind = "request", .role = "user", .parts = &[_]MessagePart{
            .{ .part_kind = "tool-return", .tool_call_id = "call_1", .content = "result" },
        }},
        .{ .kind = "request", .role = "user", .parts = &[_]MessagePart{
            .{ .part_kind = "text", .content = "Follow up" },
        }},
    };
    
    // With limit 200: system (50) + tool-return (100) + follow up (50) = 200
    // But tool-call should be pulled in to keep the pair together
    var result = try splitForSummarizationCore(allocator, tokens, msgs, 200);
    defer result.deinit(allocator);
    
    // Index 2 (tool-call) should be in protected, not summarize
    try std.testing.expect(std.mem.indexOf(usize, result.protected_indices, &[_]usize{2}) != null);
    // Index 1 should be in summarize zone
    try std.testing.expect(std.mem.indexOf(usize, result.summarize_indices, &[_]usize{1}) != null);
}

test "findMismatchedToolCallIds detects orphaned returns" {
    const allocator = std.testing.allocator;
    
    const msgs = &[_]Message{
        .{ .kind = "request", .role = "assistant", .parts = &[_]MessagePart{
            .{ .part_kind = "tool-call", .tool_call_id = "call_1", .tool_name = "foo" },
        }},
        .{ .kind = "request", .role = "user", .parts = &[_]MessagePart{
            .{ .part_kind = "tool-return", .tool_call_id = "call_2", .content = "orphan" },
        }},
    };
    
    var mismatched = try findMismatchedToolCallIds(allocator, msgs);
    defer mismatched.deinit();
    
    // Both call_1 (no return) and call_2 (no call) should be mismatched
    try std.testing.expectEqual(@as(usize, 2), mismatched.count());
}

test "findMismatchedToolCallIds allows matched pairs" {
    const allocator = std.testing.allocator;
    
    const msgs = &[_]Message{
        .{ .kind = "request", .role = "assistant", .parts = &[_]MessagePart{
            .{ .part_kind = "tool-call", .tool_call_id = "call_1", .tool_name = "foo" },
        }},
        .{ .kind = "request", .role = "user", .parts = &[_]MessagePart{
            .{ .part_kind = "tool-return", .tool_call_id = "call_1", .content = "result" },
        }},
    };
    
    var mismatched = try findMismatchedToolCallIds(allocator, msgs);
    defer mismatched.deinit();
    
    // Matched pair - no mismatches
    try std.testing.expectEqual(@as(usize, 0), mismatched.count());
}

test "pruneAndFilterMessages drops mismatched" {
    const allocator = std.testing.allocator;
    
    const msgs = &[_]Message{
        .{ .kind = "request", .role = "system", .parts = &[_]MessagePart{
            .{ .part_kind = "text", .content = "System" },
        }},
        .{ .kind = "request", .role = "assistant", .parts = &[_]MessagePart{
            .{ .part_kind = "tool-call", .tool_call_id = "orphan_call", .tool_name = "foo" },
        }},
        .{ .kind = "request", .role = "user", .parts = &[_]MessagePart{
            .{ .part_kind = "text", .content = "Hello" },
        }},
    };
    
    var result = try pruneAndFilterMessages(allocator, msgs, 50000);
    defer result.deinit(allocator);
    
    // Message with orphan tool-call should be dropped
    try std.testing.expectEqual(@as(usize, 2), result.surviving_indices.len);
    try std.testing.expectEqual(@as(usize, 0), result.surviving_indices[0]);  // system
    try std.testing.expectEqual(@as(usize, 2), result.surviving_indices[1]);  // user (index 2)
    try std.testing.expect(result.had_pending_tool_calls);
    try std.testing.expectEqual(@as(usize, 1), result.pending_tool_call_count);
}

test "pruneAndFilterMessages drops empty thinking" {
    const allocator = std.testing.allocator;
    
    const msgs = &[_]Message{
        .{ .kind = "request", .role = "system", .parts = &[_]MessagePart{
            .{ .part_kind = "text", .content = "System" },
        }},
        .{ .kind = "request", .role = "assistant", .parts = &[_]MessagePart{
            .{ .part_kind = "thinking", .content = "" },
        }},
        .{ .kind = "request", .role = "user", .parts = &[_]MessagePart{
            .{ .part_kind = "text", .content = "Hello" },
        }},
    };
    
    var result = try pruneAndFilterMessages(allocator, msgs, 50000);
    defer result.deinit(allocator);
    
    // Empty thinking message should be dropped
    try std.testing.expectEqual(@as(usize, 2), result.surviving_indices.len);
}
