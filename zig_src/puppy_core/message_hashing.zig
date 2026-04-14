// ═══════════════════════════════════════════════════════════════════════════════
// Message Hashing
// ═══════════════════════════════════════════════════════════════════════════════
//
// Migration from: code_puppy_core/src/message_hashing.rs
//
// Provides hash-based message deduplication and integrity checking.
// Uses xxHash for speed with good collision resistance.
//
// Rust → Zig changes:
//   - xxhash-rust crate → vendor or Zig implementation
//   - DefaultHasher pattern → explicit hasher choice

const std = @import("std");

// ═══════════════════════════════════════════════════════════════════════════════
// MessageHasher
// ═══════════════════════════════════════════════════════════════════════════════

pub const MessageHasher = struct {
    allocator: std.mem.Allocator,
    seed: u64,
    
    const Self = @This();
    
    pub fn init(allocator: std.mem.Allocator) Self {
        return .{
            .allocator = allocator,
            .seed = 0,  // Default seed
        };
    }
    
    pub fn initWithSeed(allocator: std.mem.Allocator, seed: u64) Self {
        return .{
            .allocator = allocator,
            .seed = seed,
        };
    }
    
    pub fn deinit(self: *Self) void {
        _ = self;
        // No heap resources
    }
    
    /// Compute hash for a single message
    pub fn hashMessage(self: *const Self, msg: MessageContent) u64 {
        return hashMessageContent(self.seed, msg);
    }
    
    /// Compute hash for a batch of messages
    pub fn hashMessageBatch(
        self: *const Self,
        messages: []const MessageContent,
    ) error{OutOfMemory}![]u64 {
        var result = try self.allocator.alloc(u64, messages.len);
        errdefer self.allocator.free(result);
        
        for (messages, 0..) |msg, i| {
            result[i] = hashMessageContent(self.seed, msg);
        }
        
        return result;
    }
    
    /// Compute incremental session hash
    /// Useful for detecting if session state has changed
    pub fn computeSessionHash(
        self: *const Self,
        message_hashes: []const u64,
    ) u64 {
        var state = XxHash64.init(self.seed);
        
        for (message_hashes) |hash| {
            const hash_bytes: [8]u8 = @bitCast(hash);
            state.update(&hash_bytes);
        }
        
        return state.final();
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════════════════════════

pub const MessageContent = struct {
    role: []const u8,
    content: []const u8,
    metadata: ?[]const u8 = null,  // Optional extra data
};

// ═══════════════════════════════════════════════════════════════════════════════
// xxHash64 Implementation (simplified, Zig-native)
// ═══════════════════════════════════════════════════════════════════════════════
//
// xxHash is an extremely fast non-cryptographic hash algorithm.
// This is a minimal Zig implementation for self-containment.

const PRIME64_1: u64 = 0x9E3779B185EBCA87;
const PRIME64_2: u64 = 0xC2B2AE3D27D4EB4F;
const PRIME64_3: u64 = 0x165667B19E3779F9;
const PRIME64_4: u64 = 0x85EBCA77C2B2AE63;
const PRIME64_5: u64 = 0x27D4EB2F165667C5;

pub const XxHash64 = struct {
    acc1: u64,
    acc2: u64,
    acc3: u64,
    acc4: u64,
    seed: u64,
    buf: [32]u8 = undefined,
    buf_len: usize = 0,
    total_len: u64 = 0,
    
    const Self = @This();
    
    pub fn init(seed: u64) Self {
        const acc1 = seed +% PRIME64_1 +% PRIME64_2;
        const acc2 = seed +% PRIME64_2;
        const acc3 = seed +% 0;
        const acc4 = seed -% PRIME64_1;
        
        return .{
            .acc1 = acc1,
            .acc2 = acc2,
            .acc3 = acc3,
            .acc4 = acc4,
            .seed = seed,
        };
    }
    
    pub fn update(self: *Self, data: []const u8) void {
        self.total_len += data.len;
        
        var i: usize = 0;
        
        // Process any buffered data first
        if (self.buf_len > 0) {
            const to_fill = @min(32 - self.buf_len, data.len);
            @memcpy(self.buf[self.buf_len..][0..to_fill], data[0..to_fill]);
            self.buf_len += to_fill;
            i += to_fill;
            
            if (self.buf_len == 32) {
                self.processStripes(&self.buf);
                self.buf_len = 0;
            }
        }
        
        // Process stripes directly from input
        while (i + 32 <= data.len) : (i += 32) {
            self.processStripes(data[i..][0..32]);
        }
        
        // Buffer remainder
        if (i < data.len) {
            const remaining = data.len - i;
            @memcpy(self.buf[0..remaining], data[i..]);
            self.buf_len = remaining;
        }
    }
    
    pub fn final(self: *Self) u64 {
        var result: u64 = undefined;
        
        if (self.total_len >= 32) {
            result = std.math.rotl(u64, self.acc1, 1) +%
                    std.math.rotl(u64, self.acc2, 7) +%
                    std.math.rotl(u64, self.acc3, 12) +%
                    std.math.rotl(u64, self.acc4, 18);
            
            // Secret merge (simplified)
            result = result *% PRIME64_5;
        } else {
            result = self.seed +% PRIME64_5;
        }
        
        result += self.total_len;
        
        // Process remaining bytes
        var i: usize = 0;
        while (i + 8 <= self.buf_len) : (i += 8) {
            const val = std.mem.readInt(u64, self.buf[i..][0..8], .little);
            result ^= round(0, val);
            result = std.math.rotl(u64, result, 27) *% PRIME64_1;
            result +%= PRIME64_4;
        }
        
        while (i + 4 <= self.buf_len) : (i += 4) {
            const val = @as(u64, std.mem.readInt(u32, self.buf[i..][0..4], .little));
            result ^= val *% PRIME64_1;
            result = std.math.rotl(u64, result, 23) *% PRIME64_2;
            result +%= PRIME64_3;
        }
        
        while (i < self.buf_len) : (i += 1) {
            result ^= @as(u64, self.buf[i]) *% PRIME64_5;
            result = std.math.rotl(u64, result, 11) *% PRIME64_1;
        }
        
        // Finalization mix
        result ^= result >> 33;
        result *%= PRIME64_2;
        result ^= result >> 29;
        result *%= PRIME64_3;
        result ^= result >> 32;
        
        return result;
    }
    
    fn processStripes(self: *Self, stripe: *const [32]u8) void {
        const s1 = std.mem.readInt(u64, stripe[0..8], .little);
        const s2 = std.mem.readInt(u64, stripe[8..16], .little);
        const s3 = std.mem.readInt(u64, stripe[16..24], .little);
        const s4 = std.mem.readInt(u64, stripe[24..32], .little);
        
        self.acc1 = round(self.acc1, s1);
        self.acc2 = round(self.acc2, s2);
        self.acc3 = round(self.acc3, s3);
        self.acc4 = round(self.acc4, s4);
    }
    
    fn round(acc: u64, val: u64) u64 {
        var result = acc +% val *% PRIME64_2;
        result = std.math.rotl(u64, result, 31);
        result *%= PRIME64_1;
        return result;
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Hash Functions
// ═══════════════════════════════════════════════════════════════════════════════

fn hashMessageContent(seed: u64, msg: MessageContent) u64 {
    var state = XxHash64.init(seed);
    
    state.update(msg.role);
    state.update(msg.content);
    if (msg.metadata) |meta| {
        state.update(meta);
    }
    
    return state.final();
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "XxHash64 basic" {
    var hasher = XxHash64.init(0);
    hasher.update("hello");
    const hash = hasher.final();
    
    // Just verify it produces a value
    try std.testing.expect(hash != 0);
}

test "XxHash64 consistent" {
    var hasher1 = XxHash64.init(123);
    hasher1.update("test data");
    
    var hasher2 = XxHash64.init(123);
    hasher2.update("test data");
    
    try std.testing.expectEqual(hasher1.final(), hasher2.final());
}

test "MessageHasher hashMessage" {
    const allocator = std.testing.allocator;
    var hasher = MessageHasher.init(allocator);
    defer hasher.deinit();
    
    const msg = MessageContent{
        .role = "user",
        .content = "Hello, world!",
    };
    
    const hash1 = hasher.hashMessage(msg);
    const hash2 = hasher.hashMessage(msg);
    
    try std.testing.expectEqual(hash1, hash2);
}
