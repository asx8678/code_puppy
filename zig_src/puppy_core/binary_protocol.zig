// ═══════════════════════════════════════════════════════════════════════════════
// Simple Binary Protocol for Fast FFI
// ═══════════════════════════════════════════════════════════════════════════════
//
// Instead of MessagePack (external dependency), we use a custom compact
// binary format that's trivial to parse and faster than JSON.
//
// Format:
//   [u32 message_count]
//   For each message:
//     [u8 role_len][role bytes]
//     [u32 parts_count]
//     For each part:
//       [u32 content_len][content bytes]
//
// Result format:
//   [u32 count]
//   For each message:
//     [i64 tokens]      // per_message_tokens
//     [u64 hash]        // message_hash
//   [i64 total_tokens]
//   [i64 overhead_tokens]

const std = @import("std");
const token_estimation = @import("token_estimation.zig");
const message_hashing = @import("message_hashing.zig");

// ═══════════════════════════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════════════════════════

pub const MessagePart = struct {
    content: []const u8,
};

pub const Message = struct {
    role: []const u8,
    parts: []const MessagePart,
};

pub const ProcessResult = struct {
    per_message_tokens: []i64,
    message_hashes: []u64,
    total_tokens: i64,
    context_overhead_tokens: i64,
    
    pub fn deinit(self: *ProcessResult, allocator: std.mem.Allocator) void {
        allocator.free(self.per_message_tokens);
        allocator.free(self.message_hashes);
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Binary Reader
// ═══════════════════════════════════════════════════════════════════════════════

pub const BinaryReader = struct {
    data: []const u8,
    pos: usize = 0,
    
    const Self = @This();
    
    /// Check if we have enough bytes remaining
    pub fn hasRemaining(self: *const Self, needed: usize) bool {
        return self.pos + needed <= self.data.len;
    }
    
    /// Read a u32 in little-endian format
    pub fn readU32(self: *Self) ?u32 {
        if (!self.hasRemaining(4)) return null;
        const val = std.mem.readInt(u32, self.data[self.pos..][0..4], .little);
        self.pos += 4;
        return val;
    }
    
    /// Read a u64 in little-endian format
    pub fn readU64(self: *Self) ?u64 {
        if (!self.hasRemaining(8)) return null;
        const val = std.mem.readInt(u64, self.data[self.pos..][0..8], .little);
        self.pos += 8;
        return val;
    }
    
    /// Read an i64 in little-endian format
    pub fn readI64(self: *Self) ?i64 {
        if (!self.hasRemaining(8)) return null;
        const val = std.mem.readInt(i64, self.data[self.pos..][0..8], .little);
        self.pos += 8;
        return val;
    }
    
    /// Read a u8
    pub fn readU8(self: *Self) ?u8 {
        if (!self.hasRemaining(1)) return null;
        const val = self.data[self.pos];
        self.pos += 1;
        return val;
    }
    
    /// Read a byte slice of given length
    pub fn readBytes(self: *Self, len: usize) ?[]const u8 {
        if (!self.hasRemaining(len)) return null;
        const slice = self.data[self.pos..][0..len];
        self.pos += len;
        return slice;
    }
    
    /// Check if we've consumed all data
    pub fn isAtEnd(self: *const Self) bool {
        return self.pos >= self.data.len;
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Binary Writer
// ═══════════════════════════════════════════════════════════════════════════════

pub const BinaryWriter = struct {
    buffer: []u8,
    pos: usize = 0,
    
    const Self = @This();
    
    /// Create a writer with pre-allocated buffer
    pub fn init(buffer: []u8) Self {
        return .{ .buffer = buffer };
    }
    
    /// Write a u32 in little-endian format
    pub fn writeU32(self: *Self, val: u32) void {
        std.mem.writeInt(u32, self.buffer[self.pos..][0..4], val, .little);
        self.pos += 4;
    }
    
    /// Write a u64 in little-endian format
    pub fn writeU64(self: *Self, val: u64) void {
        std.mem.writeInt(u64, self.buffer[self.pos..][0..8], val, .little);
        self.pos += 8;
    }
    
    /// Write an i64 in little-endian format
    pub fn writeI64(self: *Self, val: i64) void {
        std.mem.writeInt(i64, self.buffer[self.pos..][0..8], val, .little);
        self.pos += 8;
    }
    
    /// Write a u8
    pub fn writeU8(self: *Self, val: u8) void {
        self.buffer[self.pos] = val;
        self.pos += 1;
    }
    
    /// Write a byte slice (length must be written separately)
    pub fn writeBytes(self: *Self, data: []const u8) void {
        @memcpy(self.buffer[self.pos..][0..data.len], data);
        self.pos += data.len;
    }
    
    /// Get bytes written so far
    pub fn getBytesWritten(self: *Self) []const u8 {
        return self.buffer[0..self.pos];
    }
    
    /// Get current position
    pub fn getPos(self: *const Self) usize {
        return self.pos;
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Message Parsing
// ═══════════════════════════════════════════════════════════════════════════════

/// Parse messages from binary format using an arena allocator for efficiency
pub fn parseMessages(allocator: std.mem.Allocator, data: []const u8) ![]Message {
    var reader = BinaryReader{ .data = data };
    
    // Read message count
    const msg_count = reader.readU32() orelse return error.InvalidData;
    
    var messages = try allocator.alloc(Message, msg_count);
    errdefer allocator.free(messages);
    
    for (0..msg_count) |i| {
        // Read role (u8 length prefix + bytes)
        const role_len = reader.readU8() orelse return error.InvalidData;
        const role = reader.readBytes(role_len) orelse return error.InvalidData;
        messages[i].role = role;
        
        // Read parts count
        const parts_count = reader.readU32() orelse return error.InvalidData;
        var parts = try allocator.alloc(MessagePart, parts_count);
        errdefer allocator.free(parts);
        
        for (0..parts_count) |j| {
            // Read content (u32 length prefix + bytes)
            const content_len = reader.readU32() orelse return error.InvalidData;
            const content = reader.readBytes(content_len) orelse return error.InvalidData;
            parts[j].content = content;
        }
        
        messages[i].parts = parts;
    }
    
    if (!reader.isAtEnd()) {
        // Extra trailing data - could be ignored or treated as error
        // For strictness, we'll allow it but could make this configurable
    }
    
    return messages;
}

/// Calculate buffer size needed for result serialization
fn calculateResultBufferSize(msg_count: usize) usize {
    // count: u32
    // per-message: i64 tokens + u64 hash = 16 bytes each
    // total_tokens: i64
    // overhead_tokens: i64
    return 4 + (msg_count * 16) + 8 + 8;
}

/// Serialize process result to binary format
/// Caller owns the returned memory
pub fn serializeResult(
    allocator: std.mem.Allocator,
    result: ProcessResult,
) ![]u8 {
    const buf_size = calculateResultBufferSize(result.per_message_tokens.len);
    var buffer = try allocator.alloc(u8, buf_size);
    errdefer allocator.free(buffer);
    
    var writer = BinaryWriter.init(buffer);
    
    // Write count
    writer.writeU32(@intCast(result.per_message_tokens.len));
    
    // Write per-message data
    for (0..result.per_message_tokens.len) |i| {
        writer.writeI64(result.per_message_tokens[i]);
        writer.writeU64(result.message_hashes[i]);
    }
    
    // Write totals
    writer.writeI64(result.total_tokens);
    writer.writeI64(result.context_overhead_tokens);
    
    // Trim buffer to actual size (should be exact, but be safe)
    const actual_size = writer.getPos();
    if (actual_size < buf_size) {
        buffer = try allocator.realloc(buffer, actual_size);
    }
    
    return buffer;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Convenience Functions
// ═══════════════════════════════════════════════════════════════════════════════

/// Process messages directly from binary format and return binary result
/// This is the main entry point for the binary protocol FFI
pub fn processMessagesBinary(
    allocator: std.mem.Allocator,
    input_data: []const u8,
    system_prompt: []const u8,
    estimator: *token_estimation.TokenEstimator,
    hasher: *message_hashing.MessageHasher,
) !ProcessResult {
    // Create arena for parsing (efficient bulk allocation)
    var arena = std.heap.ArenaAllocator.init(allocator);
    defer arena.deinit();
    const arena_allocator = arena.allocator();
    
    // Parse messages
    const messages = try parseMessages(arena_allocator, input_data);
    
    // Allocate result arrays using the main allocator (survives arena deinit)
    var per_message_tokens = try allocator.alloc(i64, messages.len);
    errdefer allocator.free(per_message_tokens);
    
    var message_hashes = try allocator.alloc(u64, messages.len);
    errdefer allocator.free(message_hashes);
    
    var total_tokens: i64 = 0;
    
    // Process each message
    for (messages, 0..) |msg, i| {
        var msg_tokens: i64 = 0;
        
        // Accumulate tokens from all parts
        for (msg.parts) |part| {
            msg_tokens += estimator.estimateTokens(part.content);
        }
        
        // Add message overhead
        msg_tokens += token_estimation.MESSAGE_OVERHEAD_TOKENS;
        
        per_message_tokens[i] = msg_tokens;
        total_tokens += msg_tokens;
        
        // Hash the message
        // Concatenate all parts for hashing
        var content_len: usize = 0;
        for (msg.parts) |part| content_len += part.content.len;
        
        var concatenated = try arena_allocator.alloc(u8, content_len);
        var offset: usize = 0;
        for (msg.parts) |part| {
            @memcpy(concatenated[offset..][0..part.content.len], part.content);
            offset += part.content.len;
        }
        
        const hash_content = message_hashing.MessageContent{
            .role = msg.role,
            .content = concatenated,
            .metadata = null,
        };
        message_hashes[i] = hasher.hashMessage(hash_content);
    }
    
    // Calculate system prompt overhead
    const overhead_tokens = estimator.estimateTokens(system_prompt);
    const context_overhead = overhead_tokens + token_estimation.SYSTEM_PROMPT_OVERHEAD;
    
    return ProcessResult{
        .per_message_tokens = per_message_tokens,
        .message_hashes = message_hashes,
        .total_tokens = total_tokens,
        .context_overhead_tokens = context_overhead,
    };
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "BinaryReader - basic reads" {
    const data = &[_]u8{
        0x05, 0x00, 0x00, 0x00, // u32: 5
        0xAB, // u8: 171
        0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, // i64: 1
    };
    
    var reader = BinaryReader{ .data = data };
    
    try std.testing.expectEqual(@as(u32, 5), reader.readU32().?);
    try std.testing.expectEqual(@as(u8, 171), reader.readU8().?);
    try std.testing.expectEqual(@as(i64, 1), reader.readI64().?);
    try std.testing.expect(reader.isAtEnd());
}

test "BinaryReader - bounds checking" {
    const data = &[_]u8{ 0x01, 0x02 };
    var reader = BinaryReader{ .data = data };
    
    // Reading u32 when only 2 bytes should fail
    try std.testing.expect(reader.readU32() == null);
}

test "BinaryWriter - basic writes" {
    var buffer: [32]u8 = undefined;
    var writer = BinaryWriter.init(&buffer);
    
    writer.writeU32(42);
    writer.writeU8(255);
    writer.writeI64(-100);
    
    const written = writer.getBytesWritten();
    try std.testing.expectEqual(@as(usize, 13), written.len); // 4 + 1 + 8
    
    // Verify bytes
    try std.testing.expectEqual(@as(u32, 42), std.mem.readInt(u32, written[0..4], .little));
    try std.testing.expectEqual(@as(u8, 255), written[4]);
    try std.testing.expectEqual(@as(i64, -100), std.mem.readInt(i64, written[5..13], .little));
}

test "parseMessages - single message" {
    const allocator = std.testing.allocator;
    
    // Build input: 1 message, role "user" (4 bytes), 1 part, content "Hello" (5 bytes)
    const input = &[_]u8{
        0x01, 0x00, 0x00, 0x00, // count: 1
        0x04, // role_len: 4
        'u', 's', 'e', 'r', // role: "user"
        0x01, 0x00, 0x00, 0x00, // parts_count: 1
        0x05, 0x00, 0x00, 0x00, // content_len: 5
        'H', 'e', 'l', 'l', 'o', // content: "Hello"
    };
    
    var arena = std.heap.ArenaAllocator.init(allocator);
    defer arena.deinit();
    
    const messages = try parseMessages(arena.allocator(), input);
    
    try std.testing.expectEqual(@as(usize, 1), messages.len);
    try std.testing.expectEqualStrings("user", messages[0].role);
    try std.testing.expectEqual(@as(usize, 1), messages[0].parts.len);
    try std.testing.expectEqualStrings("Hello", messages[0].parts[0].content);
}

test "parseMessages - multiple messages" {
    const allocator = std.testing.allocator;
    
    // Build input: 2 messages
    const input = &[_]u8{
        0x02, 0x00, 0x00, 0x00, // count: 2
        // Message 1
        0x04, // role_len: 4
        'u', 's', 'e', 'r', // role: "user"
        0x01, 0x00, 0x00, 0x00, // parts_count: 1
        0x02, 0x00, 0x00, 0x00, // content_len: 2
        'H', 'i', // content: "Hi"
        // Message 2
        0x09, // role_len: 9
        'a', 's', 's', 'i', 's', 't', 'a', 'n', 't', // role: "assistant"
        0x01, 0x00, 0x00, 0x00, // parts_count: 1
        0x03, 0x00, 0x00, 0x00, // content_len: 3
        'B', 'y', 'e', // content: "Bye"
    };
    
    var arena = std.heap.ArenaAllocator.init(allocator);
    defer arena.deinit();
    
    const messages = try parseMessages(arena.allocator(), input);
    
    try std.testing.expectEqual(@as(usize, 2), messages.len);
    try std.testing.expectEqualStrings("user", messages[0].role);
    try std.testing.expectEqualStrings("assistant", messages[1].role);
}

test "serializeResult - roundtrip" {
    const allocator = std.testing.allocator;
    
    const per_message_tokens = &[_]i64{ 10, 20, 30 };
    const message_hashes = &[_]u64{ 123, 456, 789 };
    
    const result = ProcessResult{
        .per_message_tokens = @constCast(per_message_tokens),
        .message_hashes = @constCast(message_hashes),
        .total_tokens = 60,
        .context_overhead_tokens = 50,
    };
    
    const serialized = try serializeResult(allocator, result);
    defer allocator.free(serialized);
    
    // Verify format
    var reader = BinaryReader{ .data = serialized };
    
    try std.testing.expectEqual(@as(u32, 3), reader.readU32().?);
    
    try std.testing.expectEqual(@as(i64, 10), reader.readI64().?);
    try std.testing.expectEqual(@as(u64, 123), reader.readU64().?);
    
    try std.testing.expectEqual(@as(i64, 20), reader.readI64().?);
    try std.testing.expectEqual(@as(u64, 456), reader.readU64().?);
    
    try std.testing.expectEqual(@as(i64, 30), reader.readI64().?);
    try std.testing.expectEqual(@as(u64, 789), reader.readU64().?);
    
    try std.testing.expectEqual(@as(i64, 60), reader.readI64().?);
    try std.testing.expectEqual(@as(i64, 50), reader.readI64().?);
    
    try std.testing.expect(reader.isAtEnd());
}

test "processMessagesBinary - integration" {
    const allocator = std.testing.allocator;
    
    // Build input: 1 message with "Hello world" content (~2.75 tokens -> floor = 2)
    const input = &[_]u8{
        0x01, 0x00, 0x00, 0x00, // count: 1
        0x04, // role_len: 4
        'u', 's', 'e', 'r', // role: "user"
        0x01, 0x00, 0x00, 0x00, // parts_count: 1
        0x0B, 0x00, 0x00, 0x00, // content_len: 11 ("Hello world")
        'H', 'e', 'l', 'l', 'o', ' ', 'w', 'o', 'r', 'l', 'd',
    };
    
    var estimator = token_estimation.TokenEstimator.init(allocator);
    defer estimator.deinit();
    
    var hasher = message_hashing.MessageHasher.init(allocator);
    defer hasher.deinit();
    
    var result = try processMessagesBinary(
        allocator,
        input,
        "You are helpful.",
        &estimator,
        &hasher,
    );
    defer result.deinit(allocator);
    
    // Check results
    try std.testing.expectEqual(@as(usize, 1), result.per_message_tokens.len);
    // 11 chars / 4.0 = 2.75 -> 2 tokens + 4 overhead = 6
    try std.testing.expectEqual(@as(i64, 6), result.per_message_tokens[0]);
    try std.testing.expect(result.total_tokens >= 1);
    try std.testing.expect(result.context_overhead_tokens >= 0);
}

test "processMessagesBinary - empty input fails" {
    const allocator = std.testing.allocator;
    
    const input = &[_]u8{};
    
    var estimator = token_estimation.TokenEstimator.init(allocator);
    defer estimator.deinit();
    
    var hasher = message_hashing.MessageHasher.init(allocator);
    defer hasher.deinit();
    
    const result = processMessagesBinary(
        allocator,
        input,
        "",
        &estimator,
        &hasher,
    );
    
    try std.testing.expectError(error.InvalidData, result);
}
