// ═══════════════════════════════════════════════════════════════════════════════
// Protocol Handler - Content-Length Framed JSON-RPC for Erlang Ports
// ═══════════════════════════════════════════════════════════════════════════════
//
// Implements framed message protocol compatible with Erlang Port communication.
// Format: Content-Length: <bytes>\r\n\r\n<json_body>
//
// This follows the LSP-style framing for reliable binary-safe communication.

const std = @import("std");

// ═══════════════════════════════════════════════════════════════════════════════
// Constants
// ═══════════════════════════════════════════════════════════════════════════════

const CONTENT_LENGTH_PREFIX = "Content-Length: ";
const HEADER_SEPARATOR = "\r\n\r\n";
const MAX_MESSAGE_SIZE = 10 * 1024 * 1024; // 10MB max message size

// ═══════════════════════════════════════════════════════════════════════════════
// Error Types
// ═══════════════════════════════════════════════════════════════════════════════

pub const ProtocolError = error{
    EndOfStream,
    InvalidHeader,
    ContentLengthTooLarge,
    InvalidContentLength,
    ReadFailed,
    WriteFailed,
    OutOfMemory,
};

// ═══════════════════════════════════════════════════════════════════════════════
// Message Types
// ═══════════════════════════════════════════════════════════════════════════════

/// JSON-RPC request message from Elixir
pub const Request = struct {
    jsonrpc: []const u8 = "2.0",
    id: ?u64,
    method: []const u8,
    params: ?std.json.Value,
};

/// JSON-RPC response message to Elixir
/// Uses 'err' field internally, serializes as 'error' in JSON
pub const Response = struct {
    jsonrpc: []const u8 = "2.0",
    id: ?u64,
    result: ?std.json.Value,
    err: ?ResponseError,
};

pub const ResponseError = struct {
    code: i64,
    message: []const u8,
    data: ?std.json.Value,
};

/// Notification (one-way message, no response expected)
pub const Notification = struct {
    jsonrpc: []const u8 = "2.0",
    method: []const u8,
    params: ?std.json.Value,
};

/// Method enumeration for validated dispatch
pub const Method = enum {
    spawn,
    kill,
    write_stdin,
    resize_pty,
    ping,
    unknown,

    pub fn fromString(str: []const u8) Method {
        if (std.mem.eql(u8, str, "spawn")) return .spawn;
        if (std.mem.eql(u8, str, "kill")) return .kill;
        if (std.mem.eql(u8, str, "write_stdin")) return .write_stdin;
        if (std.mem.eql(u8, str, "resize_pty")) return .resize_pty;
        if (std.mem.eql(u8, str, "ping")) return .ping;
        return .unknown;
    }

    pub fn toString(self: Method) []const u8 {
        return switch (self) {
            .spawn => "spawn",
            .kill => "kill",
            .write_stdin => "write_stdin",
            .resize_pty => "resize_pty",
            .ping => "ping",
            .unknown => "unknown",
        };
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Reading Messages
// ═══════════════════════════════════════════════════════════════════════════════

/// Read a framed message from stdin
/// Caller owns returned memory and must free it with allocator.free()
pub fn readMessage(reader: anytype, allocator: std.mem.Allocator) ProtocolError![]u8 {
    // Read the Content-Length header line
    const content_length = try readContentLength(reader, allocator);

    // Read the header separator (\r\n\r\n)
    try readHeaderSeparator(reader);

    // Read the body
    if (content_length > MAX_MESSAGE_SIZE) {
        return ProtocolError.ContentLengthTooLarge;
    }

    const body = try allocator.alloc(u8, content_length);
    errdefer allocator.free(body);

    const bytes_read = reader.readAll(body) catch return ProtocolError.ReadFailed;
    if (bytes_read != content_length) {
        return ProtocolError.ReadFailed;
    }

    return body;
}

/// Read and parse the Content-Length header
fn readContentLength(reader: anytype, allocator: std.mem.Allocator) ProtocolError!usize {
    var header_buf: [256]u8 = undefined;
    var header_len: usize = 0;

    // Read until we find \r\n
    while (header_len < header_buf.len) {
        const byte = reader.readByte() catch |err| {
            if (err == error.EndOfStream) return ProtocolError.EndOfStream;
            return ProtocolError.ReadFailed;
        };

        if (byte == '\r') {
            // Check for \n
            const next = reader.readByte() catch |err| {
                if (err == error.EndOfStream) return ProtocolError.EndOfStream;
                return ProtocolError.ReadFailed;
            };
            if (next == '\n') break;
            return ProtocolError.InvalidHeader;
        }

        header_buf[header_len] = byte;
        header_len += 1;
    }

    if (header_len >= header_buf.len) {
        return ProtocolError.InvalidHeader;
    }

    // Parse "Content-Length: <number>"
    const header_line = header_buf[0..header_len];

    if (!std.mem.startsWith(u8, header_line, CONTENT_LENGTH_PREFIX)) {
        return ProtocolError.InvalidHeader;
    }

    const num_start = CONTENT_LENGTH_PREFIX.len;
    const num_str = std.mem.trim(u8, header_line[num_start..], " ");

    const content_length = std.fmt.parseInt(usize, num_str, 10) catch {
        return ProtocolError.InvalidContentLength;
    };

    // Cleanup any temporary allocations
    _ = allocator;

    return content_length;
}

/// Read and verify the header separator (\r\n\r\n)
fn readHeaderSeparator(reader: anytype) ProtocolError!void {
    var sep_buf: [2]u8 = undefined;

    // First \r\n after Content-Length line was already consumed
    // Now we need just \r\n for the empty line

    const bytes_read = reader.readAll(&sep_buf) catch return ProtocolError.ReadFailed;
    if (bytes_read != 2 or sep_buf[0] != '\r' or sep_buf[1] != '\n') {
        return ProtocolError.InvalidHeader;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Writing Messages
// ═══════════════════════════════════════════════════════════════════════════════

/// Write a framed message to stdout
/// Does not take ownership of message - caller retains it
pub fn writeMessage(writer: anytype, message: []const u8) ProtocolError!void {
    // Write header
    writer.print("Content-Length: {d}\r\n\r\n", .{message.len}) catch {
        return ProtocolError.WriteFailed;
    };

    // Write body
    writer.writeAll(message) catch {
        return ProtocolError.WriteFailed;
    };

    // Ensure flush
    writer.context.flush() catch {
        return ProtocolError.WriteFailed;
    };
}

/// JSON-RPC response output format for serialization
const ResponseOutput = struct {
    jsonrpc: []const u8 = "2.0",
    id: ?u64,
    result: ?std.json.Value,
    @"error": ?ResponseError,
};

/// Serialize a response and write it
pub fn writeResponse(
    writer: anytype,
    response: Response,
    allocator: std.mem.Allocator,
) ProtocolError!void {
    // Map internal Response (with 'err' field) to output format (with 'error' field)
    const output = ResponseOutput{
        .jsonrpc = response.jsonrpc,
        .id = response.id,
        .result = response.result,
        .@"error" = response.err,
    };

    const json_str = std.json.stringifyAlloc(allocator, output, .{
        .emit_null_optional_fields = false,
    }) catch return ProtocolError.OutOfMemory;
    defer allocator.free(json_str);

    try writeMessage(writer, json_str);
}

/// Serialize a notification and write it
pub fn writeNotification(
    writer: anytype,
    notification: Notification,
    allocator: std.mem.Allocator,
) ProtocolError!void {
    const json_str = std.json.stringifyAlloc(allocator, notification, .{
        .emit_null_optional_fields = false,
    }) catch return ProtocolError.OutOfMemory;
    defer allocator.free(json_str);

    try writeMessage(writer, json_str);
}

// ═══════════════════════════════════════════════════════════════════════════════
// JSON Parsing Helpers
// ═══════════════════════════════════════════════════════════════════════════════

/// Parse a request from JSON bytes
pub fn parseRequest(json_bytes: []const u8, allocator: std.mem.Allocator) ProtocolError!Request {
    const parsed = std.json.parseFromSlice(Request, allocator, json_bytes, .{
        .ignore_unknown_fields = true,
    }) catch |err| {
        std.log.warn("Failed to parse request: {s}", .{@errorName(err)});
        return ProtocolError.InvalidHeader;
    };
    defer parsed.deinit();

    // Copy to heap so caller owns the memory
    return Request{
        .jsonrpc = try allocator.dupe(u8, parsed.value.jsonrpc),
        .id = parsed.value.id,
        .method = try allocator.dupe(u8, parsed.value.method),
        .params = if (parsed.value.params) |p| try p.clone(allocator) else null,
    };
}

/// Free a parsed request
pub fn freeRequest(request: *Request, allocator: std.mem.Allocator) void {
    allocator.free(request.jsonrpc);
    allocator.free(request.method);
    if (request.params) |*p| p.deinit();
}

/// Create a success response
pub fn createSuccessResponse(id: ?u64, result: std.json.Value, allocator: std.mem.Allocator) ProtocolError!Response {
    return Response{
        .jsonrpc = "2.0",
        .id = id,
        .result = try result.clone(allocator),
        .err = null,
    };
}

/// Create an error response
pub fn createErrorResponse(id: ?u64, code: i64, message: []const u8, allocator: std.mem.Allocator) ProtocolError!Response {
    const err_struct = ResponseError{
        .code = code,
        .message = try allocator.dupe(u8, message),
        .data = null,
    };

    return Response{
        .jsonrpc = "2.0",
        .id = id,
        .result = null,
        .err = err_struct,
    };
}

/// Free a response
pub fn freeResponse(response: *Response, allocator: std.mem.Allocator) void {
    if (response.result) |*r| r.deinit();
    if (response.err) |*e| {
        allocator.free(e.message);
        if (e.data) |*d| d.deinit();
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "method enum conversion" {
    try std.testing.expectEqual(Method.spawn, Method.fromString("spawn"));
    try std.testing.expectEqual(Method.kill, Method.fromString("kill"));
    try std.testing.expectEqual(Method.ping, Method.fromString("ping"));
    try std.testing.expectEqual(Method.unknown, Method.fromString("invalid"));

    try std.testing.expectEqualStrings("spawn", Method.spawn.toString());
    try std.testing.expectEqualStrings("ping", Method.ping.toString());
}

test "read and write message roundtrip" {
    const allocator = std.testing.allocator;

    // Create a test message
    const test_message = "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"ping\"}";

    // Write to a buffer
    var buffer: [1024]u8 = undefined;
    var fbs = std.io.fixedBufferStream(&buffer);
    const writer = fbs.writer();

    try writeMessage(writer, test_message);

    // Read back from buffer
    fbs.pos = 0;
    const reader = fbs.reader();

    const msg = try readMessage(reader, allocator);
    defer allocator.free(msg);

    try std.testing.expectEqualStrings(test_message, msg);
}

test "parse request" {
    const allocator = std.testing.allocator;
    const json = "{\"jsonrpc\":\"2.0\",\"id\":42,\"method\":\"spawn\",\"params\":{\"cmd\":\"echo\"}}";

    var request = try parseRequest(json, allocator);
    defer freeRequest(&request, allocator);

    try std.testing.expectEqual(@as(?u64, 42), request.id);
    try std.testing.expectEqualStrings("spawn", request.method);
    try std.testing.expect(request.params != null);
}

test "create and serialize response" {
    const allocator = std.testing.allocator;

    // Create a success response with a JSON value
    var result_value = std.json.Value{ .object = std.json.ObjectMap.init(allocator) };
    defer result_value.object.deinit();
    try result_value.object.put("status", std.json.Value{ .string = "ok" });

    var response = try createSuccessResponse(1, result_value, allocator);
    defer freeResponse(&response, allocator);

    try std.testing.expectEqual(@as(?u64, 1), response.id);
    try std.testing.expect(response.result != null);
    try std.testing.expect(response.err == null);
}
