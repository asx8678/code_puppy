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

/// Code-heavy ratio: 1 token ≈ 4.5 characters for code (more tokens per char due to symbols)
pub const CODE_CHARS_PER_TOKEN: f64 = 4.5;

/// Prose ratio: 1 token ≈ 4.0 characters for natural language
pub const PROSE_CHARS_PER_TOKEN: f64 = 4.0;

/// Overhead per message in the conversation format
pub const MESSAGE_OVERHEAD_TOKENS: i64 = 4;

/// System prompt overhead
pub const SYSTEM_PROMPT_OVERHEAD: i64 = 3;

// ═══════════════════════════════════════════════════════════════════════════════
// Code Detection Constants
// ═══════════════════════════════════════════════════════════════════════════════

const CODE_INDICATORS = [_][]const u8{
    "{", "}", "(", ")", ";", "=>", "->", "fn ", "def ", "class ",
    "import ", "const ", "let ", "var ", "if ", "for ", "while ", "return ",
};

const CODE_DETECTION_RATIO: f64 = 0.30; // 30% of lines need indicators

// ═══════════════════════════════════════════════════════════════════════════════
// Helper Functions
// ═══════════════════════════════════════════════════════════════════════════════

fn lineHasCodeIndicators(line: []const u8) bool {
    for (CODE_INDICATORS) |indicator| {
        if (std.mem.indexOf(u8, line, indicator) != null) return true;
    }
    return false;
}

fn isCodeHeavy(text: []const u8) bool {
    // Sample first 2000 chars
    const sample = text[0..@min(text.len, 2000)];
    var lines_with_code: usize = 0;
    var total_lines: usize = 0;

    var iter = std.mem.splitSequence(u8, sample, "\n");
    while (iter.next()) |line| {
        total_lines += 1;
        if (lineHasCodeIndicators(line)) lines_with_code += 1;
    }

    if (total_lines == 0) return false;
    return @as(f64, @floatFromInt(lines_with_code)) / @as(f64, @floatFromInt(total_lines)) > CODE_DETECTION_RATIO;
}

fn estimateTokensWithSampling(text: []const u8) usize {
    if (text.len <= 500) {
        // Direct estimation for short texts
        const ratio = if (isCodeHeavy(text)) CODE_CHARS_PER_TOKEN else PROSE_CHARS_PER_TOKEN;
        return @max(1, @as(usize, @intFromFloat(@floor(@as(f64, @floatFromInt(text.len)) / ratio))));
    }

    // Sample ~1% of lines for large texts
    var total_chars: usize = 0;
    var sampled_lines: usize = 0;
    var total_lines: usize = 0;

    var iter = std.mem.splitSequence(u8, text, "\n");
    while (iter.next()) |line| {
        total_lines += 1;
        // Sample every ~100th line (1%)
        if (total_lines % 100 == 0) {
            total_chars += line.len;
            sampled_lines += 1;
        }
    }

    if (sampled_lines == 0) {
        // Fallback to first line
        var first_iter = std.mem.splitSequence(u8, text, "\n");
        if (first_iter.next()) |first| {
            total_chars = first.len;
            sampled_lines = 1;
        }
    }

    const avg_line_len = @as(f64, @floatFromInt(total_chars)) / @as(f64, @floatFromInt(sampled_lines));
    const estimated_total_chars = avg_line_len * @as(f64, @floatFromInt(total_lines));
    const ratio = if (isCodeHeavy(text)) CODE_CHARS_PER_TOKEN else PROSE_CHARS_PER_TOKEN;

    return @max(1, @as(usize, @intFromFloat(@floor(estimated_total_chars / ratio))));
}

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
        // Use floor to match Rust behavior, with sampling for large texts
        _ = self;
        if (text.len == 0) return 0;
        return @intCast(estimateTokensWithSampling(text));
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

    // "hello world" = 11 chars, prose ratio 4.0, expect 2 tokens (floor(11/4) = floor(2.75) = 2)
    const tokens = estimator.estimateTokens("hello world");
    try std.testing.expectEqual(@as(i64, 2), tokens);
}

test "unicode handling" {
    const allocator = std.testing.allocator;
    const estimator = TokenEstimator.init(allocator);

    // Emoji is 4 bytes but usually 1-2 tokens in practice
    // Our naive estimator counts bytes, so it may overestimate
    const tokens = estimator.estimateTokens("🐶🐕");
    try std.testing.expect(tokens > 0);
}

test "code detection - python code" {
    const python_code =
        \\def hello_world():
        \\    if True:
        \\        return "Hello"
        \\    for i in range(10):
        \\        print(i)
        \\    while x > 0:
        \\        x -= 1
        \\    class MyClass:
        \\        def __init__(self):
        \\            self.value = 0
        \\    import os
        \\    import sys
    ;

    try std.testing.expect(isCodeHeavy(python_code));
}

test "code detection - prose text" {
    const prose =
        \\This is a normal paragraph of text.
        \\It has multiple lines but no code indicators.
        \\No curly braces, parentheses, or semicolons here.
        \\Just plain old English prose for reading.
        \\The quick brown fox jumps over the lazy dog.
    ;

    try std.testing.expect(!isCodeHeavy(prose));
}

test "code detection - mixed content" {
    const mixed =
        \\Here is some explanation text.
        \\def function():
        \\    return 42
        \\More explanation here.
        \\if condition:
        \\    do_something()
        \\Final thoughts and conclusion.
    ;

    // Should detect as code-heavy (multiple code indicators)
    try std.testing.expect(isCodeHeavy(mixed));
}

test "sampling produces reasonable estimates" {
    const allocator = std.testing.allocator;
    const estimator = TokenEstimator.init(allocator);

    // Short text - direct estimation
    const short_text = "Hello world";
    const short_tokens = estimator.estimateTokens(short_text);
    // floor(11 / 4.0) = floor(2.75) = 2
    try std.testing.expectEqual(@as(i64, 2), short_tokens);

    // Long text with consistent line length - sampling should be accurate
    var long_text: [3000]u8 = undefined;
    var i: usize = 0;
    while (i < 100) : (i += 1) {
        const line_start = i * 30;
        @memset(long_text[line_start .. line_start + 28], 'a');
        long_text[line_start + 28] = '\n';
        long_text[line_start + 29] = 0;
    }
    const long_tokens = estimator.estimateTokens(long_text[0..3000]);
    // Should produce a reasonable estimate (not 0, not unreasonably high)
    try std.testing.expect(long_tokens > 0);
    try std.testing.expect(long_tokens < 1000);
}

test "very short string returns at least 1" {
    // estimateTokensWithSampling ensures minimum of 1 for non-empty strings
    const tokens = estimateTokensWithSampling("a");
    try std.testing.expectEqual(@as(usize, 1), tokens);
}

test "code heavy uses higher ratio" {
    const code = "fn main() { if true { return; } }";
    const prose = "This is just some text";

    const code_tokens = estimateTokensWithSampling(code);
    const prose_tokens = estimateTokensWithSampling(prose);

    // Both should return at least 1
    try std.testing.expect(code_tokens >= 1);
    try std.testing.expect(prose_tokens >= 1);

    // Code with 33 chars should get fewer tokens with 4.5 ratio vs prose with 4.0
    // floor(33/4.5) = 7, floor(33/4.0) = 8
    // This verifies the ratio difference is being applied
    try std.testing.expectEqual(@as(usize, 7), code_tokens);
}
