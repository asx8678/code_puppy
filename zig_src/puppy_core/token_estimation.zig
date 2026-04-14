// ═══════════════════════════════════════════════════════════════════════════════
// Token Estimation
// ═══════════════════════════════════════════════════════════════════════════════
//
// Migration from: code_puppy_core/src/token_estimation.rs
//
// Provides tiktoken-compatible token counting for LLM message processing.
// Uses a simplified approximation algorithm that balances accuracy vs speed.
//
// Zig advantages over Rust:
//   - comptime regex compilation (if using regex)
//   - SIMD vectorization opportunities for text scanning
//   - Arena allocation patterns for batch processing

const std = @import("std");

/// Default approximation ratio: 1 token ≈ 4 characters for English text
/// This is a simplified heuristic; tiktoken is more accurate but slower.
pub const DEFAULT_CHARS_PER_TOKEN: f32 = 4.0;

/// Overhead per message in the conversation format
pub const MESSAGE_OVERHEAD_TOKENS: i64 = 4;

/// System prompt overhead
pub const SYSTEM_PROMPT_OVERHEAD: i64 = 3;

// ═══════════════════════════════════════════════════════════════════════════════
// TokenEstimator
// ═══════════════════════════════════════════════════════════════════════════════

pub const TokenEstimator = struct {
    allocator: std.mem.Allocator,
    chars_per_token: f32,
    
    const Self = @This();
    
    /// Initialize with default settings
    pub fn init(allocator: std.mem.Allocator) Self {
        return .{
            .allocator = allocator,
            .chars_per_token = DEFAULT_CHARS_PER_TOKEN,
        };
    }
    
    /// Clean up resources
    pub fn deinit(self: *Self) void {
        _ = self;
        // No dynamic allocation yet
    }
    
    /// Estimate token count for a single string
    pub fn estimateTokens(self: *const Self, text: []const u8) i64 {
        // Simple estimation: ceiling(char_count / chars_per_token)
        const char_count: f32 = @floatFromInt(text.len);
        const tokens = @ceil(char_count / self.chars_per_token);
        return @intFromFloat(tokens);
    }
    
    /// Estimate with GPT-4 tokenization heuristic (more accurate)
    /// Counts spaces as 0.25 tokens, punctuation adjustments, etc.
    pub fn estimateTokensGpt4(self: *const Self, text: []const u8) i64 {
        // TODO(code-puppy-zig-002): Implement more sophisticated estimation
        // Based on cl100k_base tokenization patterns
        // Count words, punctuation, code segments differently
        return self.estimateTokens(text);
    }
    
    /// Process a batch of messages and return per-message token counts
    pub fn processMessageBatch(
        self: *const Self,
        messages: []const Message,
        tool_definitions: []const ToolDefinition,
        system_prompt: ?[]const u8,
    ) error{OutOfMemory}!ProcessResult {
        var arena = std.heap.ArenaAllocator.init(self.allocator);
        defer arena.deinit();
        const arena_allocator = arena.allocator();
        
        var per_message_tokens = try arena_allocator.alloc(i64, messages.len);
        var message_hashes = try arena_allocator.alloc(i64, messages.len);
        
        var total_tokens: i64 = 0;
        
        // Calculate tool definition overhead
        var tool_overhead: i64 = 0;
        for (tool_definitions) |tool| {
            tool_overhead += self.estimateTokens(tool.json_schema);
        }
        
        // System prompt overhead
        var context_overhead: i64 = SYSTEM_PROMPT_OVERHEAD + tool_overhead;
        if (system_prompt) |prompt| {
            context_overhead += self.estimateTokens(prompt);
        }
        
        // Process each message
        for (messages, 0..) |msg, i| {
            const content_tokens = self.estimateTokens(msg.content);
            const msg_total = content_tokens + MESSAGE_OVERHEAD_TOKENS;
            
            per_message_tokens[i] = msg_total;
            total_tokens += msg_total;
            
            // Simple hash for deduplication
            message_hashes[i] = hashMessage(msg);
        }
        
        // Copy results out of arena
        const result_per_message = try self.allocator.alloc(i64, messages.len);
        const result_hashes = try self.allocator.alloc(i64, messages.len);
        
        @memcpy(result_per_message, per_message_tokens);
        @memcpy(result_hashes, message_hashes);
        
        return ProcessResult{
            .per_message_tokens = result_per_message,
            .total_message_tokens = total_tokens,
            .context_overhead_tokens = context_overhead,
            .message_hashes = result_hashes,
        };
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════════════════════════

pub const Message = struct {
    role: []const u8,  // "system", "user", "assistant", "tool"
    content: []const u8,
    tool_calls: ?[]const ToolCall = null,
    tool_call_id: ?[]const u8 = null,
};

pub const ToolCall = struct {
    id: []const u8,
    name: []const u8,
    arguments: []const u8,
};

pub const ToolDefinition = struct {
    name: []const u8,
    description: []const u8,
    json_schema: []const u8,  // JSON string
};

pub const ProcessResult = struct {
    per_message_tokens: []i64,
    total_message_tokens: i64,
    context_overhead_tokens: i64,
    message_hashes: []i64,
    
    pub fn deinit(self: *ProcessResult, allocator: std.mem.Allocator) void {
        allocator.free(self.per_message_tokens);
        allocator.free(self.message_hashes);
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Helper Functions
// ═══════════════════════════════════════════════════════════════════════════════

fn hashMessage(msg: Message) i64 {
    // Simple FNV-1a hash of role + content
    const FNV_32_PRIME: u32 = 0x01000193;
    const FNV_32_OFFSET: u32 = 0x811c9dc5;
    
    var hash: u32 = FNV_32_OFFSET;
    
    for (msg.role) |byte| {
        hash ^= byte;
        hash *= FNV_32_PRIME;
    }
    
    for (msg.content) |byte| {
        hash ^= byte;
        hash *= FNV_32_PRIME;
    }
    
    return @intCast(hash);
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "basic token estimation" {
    const allocator = std.testing.allocator;
    const estimator = TokenEstimator.init(allocator);
    
    // "hello world" = 11 chars, expect 3 tokens (ceil(11/4))
    const tokens = estimator.estimateTokens("hello world");
    try std.testing.expectEqual(@as(i64, 3), tokens);
}

test "empty string returns 0" {
    const allocator = std.testing.allocator;
    const estimator = TokenEstimator.init(allocator);
    
    const tokens = estimator.estimateTokens("");
    try std.testing.expectEqual(@as(i64, 0), tokens);
}

test "unicode handling" {
    const allocator = std.testing.allocator;
    const estimator = TokenEstimator.init(allocator);
    
    // Emoji is 4 bytes but usually 1-2 tokens in practice
    // Our naive estimator counts bytes, so it may overestimate
    const tokens = estimator.estimateTokens("🐶🐕");
    try std.testing.expect(tokens > 0);
}
