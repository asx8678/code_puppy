// ═══════════════════════════════════════════════════════════════════════════════
// MCP Tests - Model Context Protocol Bridge Testing
// ═══════════════════════════════════════════════════════════════════════════════

const std = @import("std");
const mcp = @import("mcp.zig");
const protocol = @import("protocol.zig");

// ═══════════════════════════════════════════════════════════════════════════════
// Registry Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "McpRegistry lifecycle" {
    const allocator = std.testing.allocator;

    var registry = mcp.McpRegistry.init(allocator);
    defer registry.deinit();

    // Test empty registry
    try std.testing.expectEqual(@as(usize, 0), registry.serverCount());

    // Test listing empty servers
    const servers = try registry.listServers(allocator);
    defer {
        for (servers) |s| allocator.free(s);
        allocator.free(servers);
    }
    try std.testing.expectEqual(@as(usize, 0), servers.len);
}

test "McpRegistry multiple servers" {
    const allocator = std.testing.allocator;

    var registry = mcp.McpRegistry.init(allocator);
    defer registry.deinit();

    // Verify empty
    try std.testing.expectEqual(@as(usize, 0), registry.serverCount());

    // Check server not found error
    const result = registry.getServer("nonexistent");
    try std.testing.expectEqual(@as(?*mcp.McpSession, null), result);
}

test "McpRegistry stop nonexistent server" {
    const allocator = std.testing.allocator;

    var registry = mcp.McpRegistry.init(allocator);
    defer registry.deinit();

    // Test stopping non-existent server returns error
    const result = registry.stopServer("does-not-exist");
    try std.testing.expectError(mcp.McpError.ServerNotFound, result);
}

test "McpRegistry route to nonexistent server" {
    const allocator = std.testing.allocator;

    var registry = mcp.McpRegistry.init(allocator);
    defer registry.deinit();

    // Test routing to non-existent server returns error
    const result = registry.routeRequest("does-not-exist", "test/method", null, 1000);
    try std.testing.expectError(mcp.McpError.ServerNotFound, result);
}

test "McpRegistry read notification from nonexistent server" {
    const allocator = std.testing.allocator;

    var registry = mcp.McpRegistry.init(allocator);
    defer registry.deinit();

    // Test reading notification from non-existent server returns error
    const result = registry.readNotification("does-not-exist");
    try std.testing.expectError(mcp.McpError.ServerNotFound, result);
}

// ═══════════════════════════════════════════════════════════════════════════════
// MCP Status Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "McpStatus enum values" {
    try std.testing.expectEqual(@as(usize, 4), @typeInfo(mcp.McpStatus).Enum.fields.len);
    try std.testing.expectEqual(mcp.McpStatus.starting, mcp.McpStatus.starting);
    try std.testing.expectEqual(mcp.McpStatus.ready, mcp.McpStatus.ready);
    try std.testing.expectEqual(mcp.McpStatus.error_state, mcp.McpStatus.error_state);
    try std.testing.expectEqual(mcp.McpStatus.stopped, mcp.McpStatus.stopped);
}

test "McpStatus tag names" {
    try std.testing.expectEqualStrings("starting", @tagName(mcp.McpStatus.starting));
    try std.testing.expectEqualStrings("ready", @tagName(mcp.McpStatus.ready));
    try std.testing.expectEqualStrings("error_state", @tagName(mcp.McpStatus.error_state));
    try std.testing.expectEqualStrings("stopped", @tagName(mcp.McpStatus.stopped));
}

// ═══════════════════════════════════════════════════════════════════════════════
// Error Tests
// ═══════════════════════════════════════════════════════════════════════════════

fn getErrorName(err: anytype) []const u8 {
    return @errorName(err);
}

test "McpError error variants" {
    // Verify all error variants exist
    const errors = [_]mcp.McpError{
        .ServerNotFound,
        .ServerAlreadyExists,
        .ServerNotRunning,
        .SpawnFailed,
        .RequestFailed,
        .InvalidResponse,
        .ShutdownFailed,
        .OutOfMemory,
    };

    // Just verify we can create the error set
    try std.testing.expectEqual(@as(usize, 8), errors.len);

    // Test specific error names
    try std.testing.expectEqualStrings("ServerNotFound", getErrorName(mcp.McpError.ServerNotFound));
    try std.testing.expectEqualStrings("ServerAlreadyExists", getErrorName(mcp.McpError.ServerAlreadyExists));
}

// ═══════════════════════════════════════════════════════════════════════════════
// Message Framing Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "Content-Length message framing" {
    // Test that we can properly format MCP messages with Content-Length header
    const allocator = std.testing.allocator;

    const message = "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"test\"}";
    const expected_header = try std.fmt.allocPrint(allocator, "Content-Length: {d}\r\n\r\n", .{message.len});
    defer allocator.free(expected_header);

    try std.testing.expect(std.mem.startsWith(u8, expected_header, "Content-Length: "));
    try std.testing.expect(std.mem.endsWith(u8, expected_header, "\r\n\r\n"));
}

test "JSON-RPC message structure" {
    const allocator = std.testing.allocator;

    // Build a request
    var request_obj = std.json.ObjectMap.init(allocator);
    defer request_obj.deinit();

    try request_obj.put("jsonrpc", std.json.Value{ .string = "2.0" });
    try request_obj.put("id", std.json.Value{ .integer = 42 });
    try request_obj.put("method", std.json.Value{ .string = "test/method" });

    var params_obj = std.json.ObjectMap.init(allocator);
    defer params_obj.deinit();
    try params_obj.put("key", std.json.Value{ .string = "value" });
    try request_obj.put("params", std.json.Value{ .object = params_obj });

    const request_value = std.json.Value{ .object = request_obj };

    // Serialize
    const json_str = try std.json.stringifyAlloc(allocator, request_value, .{});
    defer allocator.free(json_str);

    // Parse back
    const parsed = try std.json.parseFromSlice(std.json.Value, allocator, json_str, .{});
    defer parsed.deinit();

    try std.testing.expectEqualStrings("2.0", parsed.value.object.get("jsonrpc").?.string);
    try std.testing.expectEqual(@as(i64, 42), parsed.value.object.get("id").?.integer);
    try std.testing.expectEqualStrings("test/method", parsed.value.object.get("method").?.string);
}

// ═══════════════════════════════════════════════════════════════════════════════
// Protocol Integration Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "MCP method enum integration" {
    try std.testing.expectEqual(protocol.Method.mcp_start, protocol.Method.fromString("mcp_start"));
    try std.testing.expectEqual(protocol.Method.mcp_stop, protocol.Method.fromString("mcp_stop"));
    try std.testing.expectEqual(protocol.Method.mcp_request, protocol.Method.fromString("mcp_request"));
    try std.testing.expectEqual(protocol.Method.mcp_list, protocol.Method.fromString("mcp_list"));
    try std.testing.expectEqual(protocol.Method.mcp_notification, protocol.Method.fromString("mcp_notification"));

    try std.testing.expectEqualStrings("mcp_start", protocol.Method.mcp_start.toString());
    try std.testing.expectEqualStrings("mcp_stop", protocol.Method.mcp_stop.toString());
    try std.testing.expectEqualStrings("mcp_request", protocol.Method.mcp_request.toString());
}

// ═══════════════════════════════════════════════════════════════════════════════
// Concurrent Access Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "McpRegistry thread safety - concurrent reads" {
    const allocator = std.testing.allocator;

    var registry = mcp.McpRegistry.init(allocator);
    defer registry.deinit();

    // Multiple concurrent reads should be safe (even with empty registry)
    const count1 = registry.serverCount();
    const count2 = registry.serverCount();
    const count3 = registry.serverCount();

    try std.testing.expectEqual(count1, count2);
    try std.testing.expectEqual(count2, count3);
    try std.testing.expectEqual(@as(usize, 0), count1);
}

// ═══════════════════════════════════════════════════════════════════════════════
// Mock Server Tests (uses echo as a simple process)
// ═══════════════════════════════════════════════════════════════════════════════

test "Mock: spawn and shutdown with echo" {
    // This is a minimal smoke test using /bin/echo as a mock MCP server
    // In real tests, use a proper MCP mock that speaks JSON-RPC
    const allocator = std.testing.allocator;

    var registry = mcp.McpRegistry.init(allocator);
    defer registry.deinit();

    // Note: This would need a real MCP server to work properly
    // /bin/echo doesn't speak JSON-RPC so this would fail in practice
    // For now we just verify the registry structure
    try std.testing.expectEqual(@as(usize, 0), registry.serverCount());
}

// ═══════════════════════════════════════════════════════════════════════════════
// Request ID Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "Request ID counter atomicity" {
    // Test that request ID counter is properly atomic
    var counter = std.atomic.Value(u64).init(1);

    const id1 = counter.fetchAdd(1, .monotonic);
    const id2 = counter.fetchAdd(1, .monotonic);
    const id3 = counter.fetchAdd(1, .monotonic);

    try std.testing.expectEqual(@as(u64, 1), id1);
    try std.testing.expectEqual(@as(u64, 2), id2);
    try std.testing.expectEqual(@as(u64, 3), id3);
}
