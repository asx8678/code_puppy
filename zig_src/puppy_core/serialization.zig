// ═══════════════════════════════════════════════════════════════════════════════
// Serialization
// ═══════════════════════════════════════════════════════════════════════════════
//
// Migration from: code_puppy_core/src/serialization.rs
//
// Handles message session serialization for caching and persistence.
// Uses a compact binary format with versioning for forward compatibility.
//
// Rust → Zig changes:
//   - bincode → custom compact binary format
//   - serde → manual zig struct serialization
//   - Zero-copy where possible with Zig's slice semantics

const std = @import("std");

// ═══════════════════════════════════════════════════════════════════════════════
// Format Constants
// ═══════════════════════════════════════════════════════════════════════════════

/// Magic bytes identifying the file format
pub const MAGIC: [4]u8 = .{ 0x5A, 0x50, 0x59, 0x01 };  // "ZPY\x01"

/// Current format version
pub const FORMAT_VERSION: u8 = 1;

/// Maximum supported message size (16MB)
pub const MAX_MESSAGE_SIZE: usize = 16 * 1024 * 1024;

// ═══════════════════════════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════════════════════════

pub const SerializedMessage = struct {
    role: []const u8,
    content: []const u8,
    metadata: ?[]const u8,
};

pub const SessionHeader = packed struct {
    magic: [4]u8,
    version: u8,
    reserved: u8 = 0,
    message_count: u16,
    flags: u16,
};

pub const SessionFlags = packed struct {
    has_tool_calls: bool = false,
    has_system_prompt: bool = false,
    compressed: bool = false,
    encrypted: bool = false,
    _padding: u12 = 0,
};

pub const SerializationError = error{
    InvalidMagic,
    UnsupportedVersion,
    MessageTooLarge,
    TruncatedData,
    InvalidUtf8,
    OutOfMemory,
};

// ═══════════════════════════════════════════════════════════════════════════════
// SessionSerializer
// ═══════════════════════════════════════════════════════════════════════════════

pub const SessionSerializer = struct {
    allocator: std.mem.Allocator,
    
    const Self = @This();
    
    pub fn init(allocator: std.mem.Allocator) Self {
        return .{ .allocator = allocator };
    }
    
    pub fn deinit(self: *Self) void {
        _ = self;
    }
    
    /// Serialize a full session to a binary format
    pub fn serializeSession(
        self: *const Self,
        messages: []const SerializedMessage,
    ) SerializationError![]u8 {
        // Calculate total size
        var total_size: usize = @sizeOf(SessionHeader);
        
        for (messages) |msg| {
            total_size += @sizeOf(u32) * 3;  // Length prefixes
            total_size += msg.role.len;
            total_size += msg.content.len;
            total_size += if (msg.metadata) |m| m.len else 0;
        }
        
        if (total_size > MAX_MESSAGE_SIZE * messages.len) {
            return error.MessageTooLarge;
        }
        
        var result = try self.allocator.alloc(u8, total_size);
        errdefer self.allocator.free(result);
        
        var stream = std.io.fixedBufferStream(result);
        const writer = stream.writer();
        
        // Write header
        const header = SessionHeader{
            .magic = MAGIC,
            .version = FORMAT_VERSION,
            .message_count = @intCast(messages.len),
            .flags = 0,  // TODO: set actual flags
        };
        
        try writer.writeAll(&header.magic);
        try writer.writeByte(header.version);
        try writer.writeByte(header.reserved);
        try writer.writeInt(u16, header.message_count, .little);
        try writer.writeInt(u16, header.flags, .little);
        
        // Write messages
        for (messages) |msg| {
            // Role
            try writer.writeInt(u32, @intCast(msg.role.len), .little);
            try writer.writeAll(msg.role);
            
            // Content
            try writer.writeInt(u32, @intCast(msg.content.len), .little);
            try writer.writeAll(msg.content);
            
            // Metadata (nullable)
            if (msg.metadata) |meta| {
                try writer.writeInt(u32, @intCast(meta.len), .little);
                try writer.writeAll(meta);
            } else {
                try writer.writeInt(u32, 0xFFFFFFFF, .little);  // Null marker
            }
        }
        
        // Trim to actual written size
        const actual_len = stream.getPos() catch unreachable;
        if (actual_len < total_size) {
            result = try self.allocator.realloc(result, actual_len);
        }
        
        return result;
    }
    
    /// Deserialize a session from binary format
    pub fn deserializeSession(
        self: *const Self,
        data: []const u8,
    ) SerializationError![]SerializedMessage {
        if (data.len < @sizeOf(SessionHeader)) {
            return error.TruncatedData;
        }
        
        var stream = std.io.fixedBufferStream(data);
        const reader = stream.reader();
        
        // Read header
        var magic: [4]u8 = undefined;
        try reader.readNoEof(&magic);
        
        if (!std.mem.eql(u8, &magic, &MAGIC)) {
            return error.InvalidMagic;
        }
        
        const version = try reader.readByte();
        if (version != FORMAT_VERSION) {
            return error.UnsupportedVersion;
        }
        
        _ = try reader.readByte();  // reserved
        const message_count = try reader.readInt(u16, .little);
        _ = try reader.readInt(u16, .little);  // flags
        
        // Allocate arena for all message data
        var arena = std.heap.ArenaAllocator.init(self.allocator);
        defer arena.deinit();
        
        var messages = std.ArrayList(SerializedMessage).init(self.allocator);
        errdefer {
            for (messages.items) |*msg| {
                self.allocator.free(msg.role);
                self.allocator.free(msg.content);
                if (msg.metadata) |m| self.allocator.free(m);
            }
            messages.deinit();
        }
        
        var i: usize = 0;
        while (i < message_count) : (i += 1) {
            // Role
            const role_len = try reader.readInt(u32, .little);
            const role = try self.readSizedString(&reader, role_len);
            
            // Content
            const content_len = try reader.readInt(u32, .little);
            const content = try self.readSizedString(&reader, content_len);
            
            // Metadata
            const meta_len = try reader.readInt(u32, .little);
            const metadata = if (meta_len == 0xFFFFFFFF) null else try self.readSizedString(&reader, meta_len);
            
            try messages.append(.{
                .role = role,
                .content = content,
                .metadata = metadata,
            });
        }
        
        return try messages.toOwnedSlice();
    }
    
    /// Serialize incrementally - append new messages to existing data
    pub fn serializeSessionIncremental(
        self: *const Self,
        new_messages: []const SerializedMessage,
        existing_data: ?[]const u8,
    ) SerializationError![]u8 {
        if (existing_data == null) {
            return self.serializeSession(new_messages);
        }
        
        // Deserialize existing, append new, reserialize
        const existing = try self.deserializeSession(existing_data.?);
        defer {
            for (existing) |*msg| {
                self.allocator.free(msg.role);
                self.allocator.free(msg.content);
                if (msg.metadata) |m| self.allocator.free(m);
            }
            self.allocator.free(existing);
        }
        
        var combined = try self.allocator.alloc(SerializedMessage, existing.len + new_messages.len);
        defer self.allocator.free(combined);
        
        // Deep copy existing
        for (existing, 0..) |msg, i| {
            combined[i] = try self.copyMessage(msg);
        }
        
        // Deep copy new
        for (new_messages, existing.len..) |msg, i| {
            combined[i] = try self.copyMessage(msg);
        }
        
        return self.serializeSession(combined);
    }
    
    // Helper to read a length-prefixed string
    fn readSizedString(
        self: *const Self,
        reader: anytype,
        len: u32,
    ) (SerializationError || @TypeOf(reader).Error)![]u8 {
        if (len > MAX_MESSAGE_SIZE) {
            return error.MessageTooLarge;
        }
        
        const result = try self.allocator.alloc(u8, len);
        errdefer self.allocator.free(result);
        
        try reader.readNoEof(result);
        
        // Validate UTF-8
        if (!std.unicode.utf8ValidateSlice(result)) {
            return error.InvalidUtf8;
        }
        
        return result;
    }
    
    fn copyMessage(self: *const Self, msg: SerializedMessage) error{OutOfMemory}!SerializedMessage {
        const role = try self.allocator.dupe(u8, msg.role);
        errdefer self.allocator.free(role);
        
        const content = try self.allocator.dupe(u8, msg.content);
        errdefer self.allocator.free(content);
        
        const metadata = if (msg.metadata) |m| try self.allocator.dupe(u8, m) else null;
        
        return .{
            .role = role,
            .content = content,
            .metadata = metadata,
        };
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// C ABI Exports
// ═══════════════════════════════════════════════════════════════════════════════

const CSerializedMessage = extern struct {
    role_ptr: [*c]const u8,
    role_len: usize,
    content_ptr: [*c]const u8,
    content_len: usize,
    metadata_ptr: [*c]const u8,
    metadata_len: usize,
    has_metadata: bool,
};

export fn puppy_serialize_session(
    messages_ptr: [*c]const CSerializedMessage,
    message_count: usize,
    out_data: *[*c]u8,
    out_len: *usize,
) c_int {
    // TODO(code-puppy-zig-003): Implement C ABI wrapper
    // Convert C messages → Zig messages → serialize → return buffer
    _ = messages_ptr;
    _ = message_count;
    _ = out_data;
    _ = out_len;
    return 0;  // Success
}

export fn puppy_free_serialized_data(data: [*c]u8) void {
    std.heap.c_allocator.free(std.mem.span(data));
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "roundtrip serialization" {
    const allocator = std.testing.allocator;
    
    const messages = &[_]SerializedMessage{
        .{ .role = "system", .content = "You are helpful.", .metadata = null },
        .{ .role = "user", .content = "Hello!", .metadata = "{\"id\": 1}" },
    };
    
    const serializer = SessionSerializer.init(allocator);
    
    // Serialize
    const data = try serializer.serializeSession(messages);
    defer allocator.free(data);
    
    // Deserialize
    const decoded = try serializer.deserializeSession(data);
    defer {
        for (decoded) |*msg| {
            allocator.free(msg.role);
            allocator.free(msg.content);
            if (msg.metadata) |m| allocator.free(m);
        }
        allocator.free(decoded);
    }
    
    // Verify
    try std.testing.expectEqual(@as(usize, 2), decoded.len);
    try std.testing.expectEqualStrings("system", decoded[0].role);
    try std.testing.expectEqualStrings("Hello!", decoded[1].content);
    try std.testing.expect(decoded[1].metadata != null);
}

test "incremental serialization" {
    const allocator = std.testing.allocator;
    
    const initial = &[_]SerializedMessage{
        .{ .role = "system", .content = "Setup", .metadata = null },
    };
    
    const new_messages = &[_]SerializedMessage{
        .{ .role = "user", .content = "Query", .metadata = null },
    };
    
    const serializer = SessionSerializer.init(allocator);
    
    // First serialize
    const data1 = try serializer.serializeSession(initial);
    defer allocator.free(data1);
    
    // Incremental append
    const data2 = try serializer.serializeSessionIncremental(new_messages, data1);
    defer allocator.free(data2);
    
    // Verify
    const decoded = try serializer.deserializeSession(data2);
    defer {
        for (decoded) |*msg| {
            allocator.free(msg.role);
            allocator.free(msg.content);
        }
        allocator.free(decoded);
    }
    
    try std.testing.expectEqual(@as(usize, 2), decoded.len);
}

test "invalid magic detection" {
    const allocator = std.testing.allocator;
    const serializer = SessionSerializer.init(allocator);
    
    const bad_data = &[_]u8{ 0x00, 0x00, 0x00, 0x00 };  // Wrong magic
    
    const result = serializer.deserializeSession(bad_data);
    try std.testing.expectError(error.InvalidMagic, result);
}
