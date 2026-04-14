// ═══════════════════════════════════════════════════════════════════════════════
// Process Runner Entry Point - Erlang Port Interface
// ═══════════════════════════════════════════════════════════════════════════════
//
// Standalone executable that runs as an Erlang Port from Elixir.
// Handles framed JSON-RPC messages for process management.
//
// Usage from Elixir:
//   Port.open({:spawn_executable, "zig-out/bin/process_runner"}, [
//     :binary, :exit_status, {:packet, 0}
//   ])

const std = @import("std");
const protocol = @import("protocol.zig");
const process = @import("process.zig");

// ═══════════════════════════════════════════════════════════════════════════════
// Globals
// ═══════════════════════════════════════════════════════════════════════════════

// TODO(code-puppy-019d8a): These would need thread-safe access patterns
// for production use with output streaming callbacks
var g_sessions: ?*process.SessionRegistry = null;
var g_allocator: ?std.mem.Allocator = null;

// ═══════════════════════════════════════════════════════════════════════════════
// Main Entry Point
// ═══════════════════════════════════════════════════════════════════════════════

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa.deinit();
    const allocator = gpa.allocator();

    const stdin_file = std.fs.File.stdin();
    const stdout_file = std.fs.File.stdout();

    // Buffers for buffered I/O
    var stdin_buffer: [4096]u8 = undefined;
    var stdout_buffer: [4096]u8 = undefined;

    const stdin = stdin_file.reader(&stdin_buffer);
    const stdout = stdout_file.writer(&stdout_buffer);

    // Initialize session registry
    var sessions = process.SessionRegistry.init(allocator);
    defer sessions.deinit();

    // Store for potential output streaming access
    g_sessions = &sessions;
    g_allocator = allocator;

    std.log.info("Process runner started - awaiting commands", .{});

    // Main message loop
    while (true) {
        const msg = protocol.readMessage(stdin, allocator) catch |err| {
            if (err == protocol.ProtocolError.EndOfStream) {
                std.log.info("End of stream received, shutting down", .{});
                break;
            }
            std.log.err("Error reading message: {s}", .{@errorName(err)});
            continue;
        };
        defer allocator.free(msg);

        // Parse and handle the message
        const response = handleMessage(msg, &sessions, allocator) catch |err| {
            std.log.err("Error handling message: {s}", .{@errorName(err)});
            // Create error response
            const error_response = try protocol.createErrorResponse(
                null,
                -32603,
                @errorName(err),
                allocator,
            );
            defer protocol.freeResponse(&error_response, allocator);
            try protocol.writeResponse(stdout, error_response, allocator);
            continue;
        };

        // Send response if there is one (not for notifications)
        if (response) |resp| {
            defer protocol.freeResponse(&resp, allocator);
            try protocol.writeResponse(stdout, resp, allocator);
        }
    }

    // Cleanup all active sessions
    sessions.cleanupAll();
    g_sessions = null;
    g_allocator = null;

    std.log.info("Process runner shutdown complete", .{});
}

// ═══════════════════════════════════════════════════════════════════════════════
// Message Dispatch
// ═══════════════════════════════════════════════════════════════════════════════

fn handleMessage(
    msg_bytes: []const u8,
    sessions: *process.SessionRegistry,
    allocator: std.mem.Allocator,
) !?protocol.Response {
    // Parse the request
    var request = protocol.parseRequest(msg_bytes, allocator) catch {
        // Return parse error
        return try protocol.createErrorResponse(
            null,
            -32700, // Parse error
            "Failed to parse JSON-RPC request",
            allocator,
        );
    };
    defer protocol.freeRequest(&request, allocator);

    const method = protocol.Method.fromString(request.method);

    // Dispatch to appropriate handler
    return switch (method) {
        .ping => try handlePing(&request, allocator),
        .spawn => try handleSpawn(&request, sessions, allocator),
        .kill => try handleKill(&request, sessions, allocator),
        .write_stdin => try handleWriteStdin(&request, sessions, allocator),
        .resize_pty => try handleResizePty(&request, sessions, allocator),
        .unknown => try protocol.createErrorResponse(
            request.id,
            -32601, // Method not found
            "Unknown method",
            allocator,
        ),
    };
}

// ═══════════════════════════════════════════════════════════════════════════════
// Method Handlers
// ═══════════════════════════════════════════════════════════════════════════════

fn handlePing(request: *const protocol.Request, allocator: std.mem.Allocator) !protocol.Response {
    // Simple ping/pong for health checks
    var result = std.json.Value{ .object = std.json.ObjectMap.init(allocator) };
    errdefer result.object.deinit();
    try result.object.put("status", std.json.Value{ .string = "pong" });
    try result.object.put("timestamp", std.json.Value{ .integer = @intCast(std.time.milliTimestamp()) });

    return try protocol.createSuccessResponse(request.id, result, allocator);
}

fn handleSpawn(
    request: *const protocol.Request,
    sessions: *process.SessionRegistry,
    allocator: std.mem.Allocator,
) !protocol.Response {
    // Extract spawn parameters from request
    const params = request.params orelse {
        return try protocol.createErrorResponse(
            request.id,
            -32602, // Invalid params
            "Missing params object",
            allocator,
        );
    };

    // Parse command and args from params
    const command = if (params.object.get("command")) |cmd| switch (cmd) {
        .string => |s| s,
        else => return try protocol.createErrorResponse(
            request.id,
            -32602,
            "command must be a string",
            allocator,
        ),
    } else {
        return try protocol.createErrorResponse(
            request.id,
            -32602,
            "Missing 'command' parameter",
            allocator,
        );
    };

    // Build args array
    var args_list = std.ArrayList([]const u8).init(allocator);
    defer {
        for (args_list.items) |arg| {
            allocator.free(arg);
        }
        args_list.deinit();
    }

    if (params.object.get("args")) |args_json| {
        switch (args_json) {
            .array => |arr| {
                for (arr.items) |item| {
                    switch (item) {
                        .string => |s| try args_list.append(try allocator.dupe(u8, s)),
                        else => {},
                    }
                }
            },
            else => {},
        }
    }

    // Parse optional cwd
    const cwd: ?[]const u8 = if (params.object.get("cwd")) |cwd_json| switch (cwd_json) {
        .string => |s| try allocator.dupe(u8, s),
        else => null,
    } else null;
    defer if (cwd) |c| allocator.free(c);

    // Parse optional use_pty flag
    const use_pty = if (params.object.get("use_pty")) |pty_json| switch (pty_json) {
        .bool => |b| b,
        else => false,
    } else false;

    // Create spawn options
    const options = process.SpawnOptions{
        .command = command,
        .args = args_list.items,
        .cwd = cwd,
        .use_pty = use_pty,
    };

    // Attempt to spawn (stub for now - real implementation in process.zig)
    const result = process.spawnProcess(sessions, options) catch |err| {
        return try protocol.createErrorResponse(
            request.id,
            -32000, // Server error
            @errorName(err),
            allocator,
        );
    };

    // Build success response
    var result_obj = std.json.Value{ .object = std.json.ObjectMap.init(allocator) };
    errdefer result_obj.object.deinit();
    try result_obj.object.put("session_id", std.json.Value{ .integer = @intCast(result.session.id) });
    try result_obj.object.put("pid", std.json.Value{ .integer = if (result.session.pid) |pid| @intCast(pid) else 0 });

    return try protocol.createSuccessResponse(request.id, result_obj, allocator);
}

fn handleKill(
    request: *const protocol.Request,
    sessions: *process.SessionRegistry,
    allocator: std.mem.Allocator,
) !protocol.Response {
    const params = request.params orelse {
        return try protocol.createErrorResponse(
            request.id,
            -32602,
            "Missing params object",
            allocator,
        );
    };

    // Get session ID
    const session_id = if (params.object.get("session_id")) |id_json| switch (id_json) {
        .integer => |i| @as(u64, @intCast(i)),
        .float => |f| @as(u64, @intFromFloat(f)),
        else => {
            return try protocol.createErrorResponse(
                request.id,
                -32602,
                "session_id must be a number",
                allocator,
            );
        },
    } else {
        return try protocol.createErrorResponse(
            request.id,
            -32602,
            "Missing 'session_id' parameter",
            allocator,
        );
    };

    // Find the session
    const session = sessions.getSession(session_id) orelse {
        return try protocol.createErrorResponse(
            request.id,
            -32000,
            "Session not found",
            allocator,
        );
    };

    // Parse optional force flag
    const force = if (params.object.get("force")) |force_json| switch (force_json) {
        .bool => |b| b,
        else => false,
    } else false;

    // Parse optional grace_period
    const grace_period = if (params.object.get("grace_period_ms")) |grace_json| switch (grace_json) {
        .integer => |i| @as(u32, @intCast(i)),
        .float => |f| @as(u32, @intFromFloat(f)),
        else => 5000,
    } else 5000;

    // Attempt to kill
    process.killProcess(session, .{
        .force = force,
        .grace_period_ms = grace_period,
    }) catch |err| {
        return try protocol.createErrorResponse(
            request.id,
            -32000,
            @errorName(err),
            allocator,
        );
    };

    // Build success response
    var result_obj = std.json.Value{ .object = std.json.ObjectMap.init(allocator) };
    errdefer result_obj.object.deinit();
    try result_obj.object.put("session_id", std.json.Value{ .integer = @intCast(session_id) });
    try result_obj.object.put("state", std.json.Value{ .string = @tagName(session.state) });
    if (session.exit_code) |code| {
        try result_obj.object.put("exit_code", std.json.Value{ .integer = @intCast(code) });
    }

    return try protocol.createSuccessResponse(request.id, result_obj, allocator);
}

fn handleWriteStdin(
    request: *const protocol.Request,
    sessions: *process.SessionRegistry,
    allocator: std.mem.Allocator,
) !protocol.Response {
    const params = request.params orelse {
        return try protocol.createErrorResponse(
            request.id,
            -32602,
            "Missing params object",
            allocator,
        );
    };

    // Get session ID
    const session_id = if (params.object.get("session_id")) |id_json| switch (id_json) {
        .integer => |i| @as(u64, @intCast(i)),
        .float => |f| @as(u64, @intFromFloat(f)),
        else => {
            return try protocol.createErrorResponse(
                request.id,
                -32602,
                "session_id must be a number",
                allocator,
            );
        },
    } else {
        return try protocol.createErrorResponse(
            request.id,
            -32602,
            "Missing 'session_id' parameter",
            allocator,
        );
    };

    // Get data to write
    const data = if (params.object.get("data")) |data_json| switch (data_json) {
        .string => |s| s,
        else => {
            return try protocol.createErrorResponse(
                request.id,
                -32602,
                "data must be a string",
                allocator,
            );
        },
    } else {
        return try protocol.createErrorResponse(
            request.id,
            -32602,
            "Missing 'data' parameter",
            allocator,
        );
    };

    // Find session and write
    const session = sessions.getSession(session_id) orelse {
        return try protocol.createErrorResponse(
            request.id,
            -32000,
            "Session not found",
            allocator,
        );
    };

    process.writeStdin(session, data) catch |err| {
        return try protocol.createErrorResponse(
            request.id,
            -32000,
            @errorName(err),
            allocator,
        );
    };

    // Success - return empty result
    var result_obj = std.json.Value{ .object = std.json.ObjectMap.init(allocator) };
    errdefer result_obj.object.deinit();
    try result_obj.object.put("bytes_written", std.json.Value{ .integer = @intCast(data.len) });

    return try protocol.createSuccessResponse(request.id, result_obj, allocator);
}

fn handleResizePty(
    request: *const protocol.Request,
    sessions: *process.SessionRegistry,
    allocator: std.mem.Allocator,
) !protocol.Response {
    const params = request.params orelse {
        return try protocol.createErrorResponse(
            request.id,
            -32602,
            "Missing params object",
            allocator,
        );
    };

    // Get session ID
    const session_id = if (params.object.get("session_id")) |id_json| switch (id_json) {
        .integer => |i| @as(u64, @intCast(i)),
        .float => |f| @as(u64, @intFromFloat(f)),
        else => {
            return try protocol.createErrorResponse(
                request.id,
                -32602,
                "session_id must be a number",
                allocator,
            );
        },
    } else {
        return try protocol.createErrorResponse(
            request.id,
            -32602,
            "Missing 'session_id' parameter",
            allocator,
        );
    };

    // Get dimensions
    const rows = if (params.object.get("rows")) |rows_json| switch (rows_json) {
        .integer => |i| @as(u16, @intCast(i)),
        .float => |f| @as(u16, @intFromFloat(f)),
        else => {
            return try protocol.createErrorResponse(
                request.id,
                -32602,
                "rows must be a number",
                allocator,
            );
        },
    } else {
        return try protocol.createErrorResponse(
            request.id,
            -32602,
            "Missing 'rows' parameter",
            allocator,
        );
    };

    const cols = if (params.object.get("cols")) |cols_json| switch (cols_json) {
        .integer => |i| @as(u16, @intCast(i)),
        .float => |f| @as(u16, @intFromFloat(f)),
        else => {
            return try protocol.createErrorResponse(
                request.id,
                -32602,
                "cols must be a number",
                allocator,
            );
        },
    } else {
        return try protocol.createErrorResponse(
            request.id,
            -32602,
            "Missing 'cols' parameter",
            allocator,
        );
    };

    // Find session and resize
    const session = sessions.getSession(session_id) orelse {
        return try protocol.createErrorResponse(
            request.id,
            -32000,
            "Session not found",
            allocator,
        );
    };

    process.resizePty(session, rows, cols) catch |err| {
        return try protocol.createErrorResponse(
            request.id,
            -32000,
            @errorName(err),
            allocator,
        );
    };

    // Success
    var result_obj = std.json.Value{ .object = std.json.ObjectMap.init(allocator) };
    errdefer result_obj.object.deinit();
    try result_obj.object.put("rows", std.json.Value{ .integer = rows });
    try result_obj.object.put("cols", std.json.Value{ .integer = cols });

    return try protocol.createSuccessResponse(request.id, result_obj, allocator);
}
