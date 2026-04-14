// ═══════════════════════════════════════════════════════════════════════════════
// MCP Stdio Bridge - Model Context Protocol Server Communication
// ═══════════════════════════════════════════════════════════════════════════════
//
// Implements MCP server management via JSON-RPC over stdio. Handles process
// spawning, message framing, health tracking, and graceful shutdown.

const std = @import("std");
const protocol = @import("protocol.zig");

// ═══════════════════════════════════════════════════════════════════════════════
// Constants
// ═══════════════════════════════════════════════════════════════════════════════

const DEFAULT_KILL_TIMEOUT_MS = 5000;
const SIGTERM = 15;
const SIGKILL = 9;
const MCP_JSONRPC_VERSION = "2.0";

// ═══════════════════════════════════════════════════════════════════════════════
// Error Types
// ═══════════════════════════════════════════════════════════════════════════════

pub const McpError = error{
    ServerNotFound,
    ServerAlreadyExists,
    ServerNotRunning,
    SpawnFailed,
    RequestFailed,
    InvalidResponse,
    ShutdownFailed,
    OutOfMemory,
};

// ═══════════════════════════════════════════════════════════════════════════════
// MCP Session
// ═══════════════════════════════════════════════════════════════════════════════

pub const McpStatus = enum {
    starting,
    ready,
    error_state,
    stopped,
};

pub const McpSession = struct {
    id: []const u8,
    command: []const u8,
    process: ?std.process.Child,
    stdin_file: ?std.fs.File,
    stdout_file: ?std.fs.File,
    stderr_file: ?std.fs.File,
    status: McpStatus,
    allocator: std.mem.Allocator,
    request_id_counter: std.atomic.Value(u64),

    // Threading
    stdout_thread: ?std.Thread,
    stderr_thread: ?std.Thread,
    notification_mutex: std.Thread.Mutex,
    pending_notifications: std.ArrayList(protocol.Notification),

    // Response tracking for synchronous requests
    response_mutex: std.Thread.Mutex,
    pending_responses: std.AutoHashMap(u64, []const u8),

    pub fn init(
        allocator: std.mem.Allocator,
        id: []const u8,
        command: []const u8,
        args: []const []const u8,
    ) !*McpSession {
        const session = try allocator.create(McpSession);
        errdefer allocator.destroy(session);

        // Copy id and command strings
        const id_copy = try allocator.dupe(u8, id);
        errdefer allocator.free(id_copy);

        const cmd_copy = try allocator.dupe(u8, command);
        errdefer allocator.free(cmd_copy);

        session.* = .{
            .id = id_copy,
            .command = cmd_copy,
            .process = null,
            .stdin_file = null,
            .stdout_file = null,
            .stderr_file = null,
            .status = .starting,
            .allocator = allocator,
            .request_id_counter = std.atomic.Value(u64).init(1),
            .stdout_thread = null,
            .stderr_thread = null,
            .notification_mutex = .{},
            .pending_notifications = std.ArrayList(protocol.Notification).init(allocator),
            .response_mutex = .{},
            .pending_responses = std.AutoHashMap(u64, []const u8).init(allocator),
        };

        // Spawn the MCP server process
        try session.spawnProcess(command, args);
        session.status = .ready;

        // Start reader threads
        try session.startReaderThreads();

        return session;
    }

    fn spawnProcess(self: *McpSession, command: []const u8, args: []const []const u8) !void {
        const allocator = self.allocator;

        // Build argument array
        var argv = try std.ArrayList([]const u8).initCapacity(allocator, args.len + 1);
        defer argv.deinit();
        try argv.append(command);
        for (args) |arg| {
            try argv.append(arg);
        }

        // Spawn process with pipes
        var child = std.process.Child.init(argv.items, allocator);
        child.stdin_behavior = .Pipe;
        child.stdout_behavior = .Pipe;
        child.stderr_behavior = .Pipe;

        try child.spawn();

        self.process = child;
        self.stdin_file = child.stdin;
        self.stdout_file = child.stdout;
        self.stderr_file = child.stderr;
    }

    fn startReaderThreads(self: *McpSession) !void {
        // Start stdout reader for JSON-RPC responses
        if (self.stdout_file) |file| {
            const ctx = try self.allocator.create(StdoutContext);
            ctx.* = .{
                .session = self,
                .file = file,
                .allocator = self.allocator,
            };
            self.stdout_thread = try std.Thread.spawn(.{}, stdoutReaderThread, .{ctx});
        }

        // Start stderr reader for logging
        if (self.stderr_file) |file| {
            const ctx = try self.allocator.create(StderrContext);
            ctx.* = .{
                .session_id = self.id,
                .file = file,
                .allocator = self.allocator,
            };
            self.stderr_thread = try std.Thread.spawn(.{}, stderrReaderThread, .{ctx});
        }
    }

    pub fn sendRequest(
        self: *McpSession,
        method: []const u8,
        params: ?std.json.Value,
        timeout_ms: u32,
    ) ![]const u8 {
        if (self.status != .ready) {
            return McpError.ServerNotRunning;
        }

        const request_id = self.request_id_counter.fetchAdd(1, .monotonic);

        // Build JSON-RPC request
        var request_obj = std.json.ObjectMap.init(self.allocator);
        defer request_obj.deinit();

        try request_obj.put("jsonrpc", std.json.Value{ .string = MCP_JSONRPC_VERSION });
        try request_obj.put("id", std.json.Value{ .integer = @intCast(request_id) });
        try request_obj.put("method", std.json.Value{ .string = method });
        if (params) |p| {
            try request_obj.put("params", p);
        }

        const request_value = std.json.Value{ .object = request_obj };
        const json_str = try std.json.stringifyAlloc(self.allocator, request_value, .{});
        defer self.allocator.free(json_str);

        // Send the request
        try self.writeMessage(json_str);

        // Wait for response with timeout
        return try self.waitForResponse(request_id, timeout_ms);
    }

    fn writeMessage(self: *McpSession, message: []const u8) !void {
        if (self.stdin_file) |file| {
            // MCP uses LSP-style Content-Length framing
            try file.writer().print("Content-Length: {d}\r\n\r\n", .{message.len});
            try file.writer().writeAll(message);
        } else {
            return McpError.ServerNotRunning;
        }
    }

    fn waitForResponse(self: *McpSession, request_id: u64, timeout_ms: u32) ![]const u8 {
        const start_time = std.time.milliTimestamp();

        while (true) {
            const elapsed = @as(u32, @intCast(std.time.milliTimestamp() - start_time));
            if (elapsed >= timeout_ms) {
                self.response_mutex.lock();
                _ = self.pending_responses.remove(request_id);
                self.response_mutex.unlock();
                return McpError.RequestFailed;
            }

            self.response_mutex.lock();
            if (self.pending_responses.fetchRemove(request_id)) |entry| {
                self.response_mutex.unlock();
                return entry.value;
            }
            self.response_mutex.unlock();

            std.time.sleep(10 * std.time.ns_per_ms); // 10ms poll interval
        }
    }

    fn handleResponse(self: *McpSession, response_bytes: []const u8) !void {
        // Parse to extract id
        const parsed = try std.json.parseFromSlice(std.json.Value, self.allocator, response_bytes, .{});
        defer parsed.deinit();

        const id_value = parsed.value.object.get("id") orelse {
            // No id = notification, store for later retrieval
            self.notification_mutex.lock();
            defer self.notification_mutex.unlock();

            const notification = try self.allocator.dupe(u8, response_bytes);
            try self.pending_notifications.append(protocol.Notification{
                .method = "mcp/notification",
                .params = std.json.Value{ .string = notification },
            });
            return;
        };

        const request_id: u64 = switch (id_value) {
            .integer => |i| @intCast(i),
            .float => |f| @intFromFloat(f),
            else => return,
        };

        // Store response
        const response_copy = try self.allocator.dupe(u8, response_bytes);

        self.response_mutex.lock();
        defer self.response_mutex.unlock();

        try self.pending_responses.put(request_id, response_copy);
    }

    pub fn readNotification(self: *McpSession) !?protocol.Notification {
        self.notification_mutex.lock();
        defer self.notification_mutex.unlock();

        if (self.pending_notifications.items.len > 0) {
            return self.pending_notifications.orderedRemove(0);
        }

        return null;
    }

    pub fn shutdown(self: *McpSession) void {
        if (self.status == .stopped) return;

        self.status = .stopped;

        // Try graceful shutdown first
        if (self.process) |*child| {
            // Send initialize/shutdown if needed, then kill
            _ = self.killProcess(child, SIGTERM);

            // Wait with timeout
            var elapsed: u32 = 0;
            while (elapsed < DEFAULT_KILL_TIMEOUT_MS) {
                const result = std.childProcess.tryWait(child) catch null;
                if (result != null) break;
                std.time.sleep(50 * std.time.ns_per_ms);
                elapsed += 50;
            }

            // Escalate to SIGKILL if still running
            if (elapsed >= DEFAULT_KILL_TIMEOUT_MS) {
                _ = self.killProcess(child, SIGKILL);
                _ = child.wait() catch {};
            }
        }

        // Close file handles
        if (self.stdin_file) |file| {
            file.close();
        }
        if (self.stdout_file) |file| {
            file.close();
        }
        if (self.stderr_file) |file| {
            file.close();
        }
    }

    fn killProcess(self: *McpSession, child: *std.process.Child, sig: u32) !void {
        _ = self;
        const builtin = @import("builtin");

        switch (builtin.os.tag) {
            .windows => {
                // Windows: not implemented yet
                return error.UnsupportedPlatform;
            },
            else => {
                if (child.id) |pid| {
                    _ = std.posix.kill(pid, @intCast(sig));
                }
            },
        }
    }

    pub fn deinit(self: *McpSession) void {
        self.shutdown();

        // Join threads
        if (self.stdout_thread) |thread| {
            thread.join();
        }
        if (self.stderr_thread) |thread| {
            thread.join();
        }

        // Clean up strings
        self.allocator.free(self.id);
        self.allocator.free(self.command);

        // Clean up pending responses
        var response_iter = self.pending_responses.valueIterator();
        while (response_iter.next()) |response_ptr| {
            self.allocator.free(response_ptr.*);
        }
        self.pending_responses.deinit();

        // Clean up pending notifications
        for (self.pending_notifications.items) |*notif| {
            if (notif.params) |*p| p.deinit();
        }
        self.pending_notifications.deinit();

        self.allocator.destroy(self);
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Thread Contexts
// ═══════════════════════════════════════════════════════════════════════════════

const StdoutContext = struct {
    session: *McpSession,
    file: std.fs.File,
    allocator: std.mem.Allocator,
};

const StderrContext = struct {
    session_id: []const u8,
    file: std.fs.File,
    allocator: std.mem.Allocator,
};

fn stdoutReaderThread(ctx: *StdoutContext) void {
    defer ctx.allocator.destroy(ctx);

    var buffer: [4096]u8 = undefined;
    var message_buffer = std.ArrayList(u8).init(ctx.allocator);
    defer message_buffer.deinit();

    const reader = ctx.file.reader();
    var content_length: ?usize = null;
    var header_complete = false;

    while (true) {
        const bytes_read = reader.read(&buffer) catch break;
        if (bytes_read == 0) break;

        try message_buffer.appendSlice(buffer[0..bytes_read]);

        // Parse headers and body
        while (true) {
            const data = message_buffer.items;

            // Looking for Content-Length header
            if (content_length == null) {
                const prefix = "Content-Length: ";
                if (std.mem.indexOf(u8, data, prefix)) |start| {
                    const num_start = start + prefix.len;
                    if (std.mem.indexOf(u8, data[num_start..], "\r\n")) |end| {
                        const num_str = std.mem.trim(u8, data[num_start .. num_start + end], " ");
                        content_length = std.fmt.parseInt(usize, num_str, 10) catch null;
                    }
                }
            }

            // Looking for header/body separator
            if (!header_complete) {
                if (std.mem.indexOf(u8, data, "\r\n\r\n")) |sep_end| {
                    header_complete = true;
                    // Remove processed headers from buffer
                    const remaining = data[sep_end + 4 ..];
                    message_buffer.clearRetainingCapacity();
                    try message_buffer.appendSlice(remaining);
                    continue;
                }
            }

            // Process complete message
            if (header_complete and content_length != null) {
                if (message_buffer.items.len >= content_length.?) {
                    const msg = message_buffer.items[0..content_length.?];
                    ctx.session.handleResponse(msg) catch {};

                    // Remove processed message
                    const remaining = message_buffer.items[content_length.?..];
                    message_buffer.clearRetainingCapacity();
                    try message_buffer.appendSlice(remaining);

                    // Reset for next message
                    content_length = null;
                    header_complete = false;
                    continue;
                }
            }

            break;
        }
    }
}

fn stderrReaderThread(ctx: *StderrContext) void {
    defer ctx.allocator.destroy(ctx);

    var buffer: [4096]u8 = undefined;
    const reader = ctx.file.reader();

    while (true) {
        const bytes_read = reader.read(&buffer) catch break;
        if (bytes_read == 0) break;

        // Log stderr output
        std.log.info("MCP server {s} stderr: {s}", .{ ctx.session_id, buffer[0..bytes_read] });
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// MCP Registry
// ═══════════════════════════════════════════════════════════════════════════════

pub const McpRegistry = struct {
    sessions: std.StringHashMap(*McpSession),
    allocator: std.mem.Allocator,
    mutex: std.Thread.Mutex,

    pub fn init(allocator: std.mem.Allocator) McpRegistry {
        return .{
            .sessions = std.StringHashMap(*McpSession).init(allocator),
            .allocator = allocator,
            .mutex = .{},
        };
    }

    pub fn deinit(self: *McpRegistry) void {
        // Stop all servers
        var iter = self.sessions.valueIterator();
        while (iter.next()) |session_ptr| {
            session_ptr.*.deinit();
        }
        self.sessions.deinit();
    }

    pub fn startServer(
        self: *McpRegistry,
        id: []const u8,
        command: []const u8,
        args: []const []const u8,
    ) !void {
        self.mutex.lock();
        defer self.mutex.unlock();

        // Check if server already exists
        if (self.sessions.contains(id)) {
            return McpError.ServerAlreadyExists;
        }

        // Create new session
        const session = try McpSession.init(self.allocator, id, command, args);
        errdefer session.deinit();

        try self.sessions.put(try self.allocator.dupe(u8, id), session);
    }

    pub fn stopServer(self: *McpRegistry, id: []const u8) !void {
        self.mutex.lock();
        defer self.mutex.unlock();

        if (self.sessions.fetchRemove(id)) |entry| {
            entry.value.deinit();
            self.allocator.free(entry.key);
        } else {
            return McpError.ServerNotFound;
        }
    }

    pub fn getServer(self: *McpRegistry, id: []const u8) ?*McpSession {
        self.mutex.lock();
        defer self.mutex.unlock();

        return self.sessions.get(id);
    }

    pub fn routeRequest(
        self: *McpRegistry,
        server_id: []const u8,
        method: []const u8,
        params: ?std.json.Value,
        timeout_ms: u32,
    ) ![]const u8 {
        const session = self.getServer(server_id) orelse {
            return McpError.ServerNotFound;
        };

        return try session.sendRequest(method, params, timeout_ms);
    }

    pub fn listServers(self: *McpRegistry, allocator: std.mem.Allocator) ![][]const u8 {
        self.mutex.lock();
        defer self.mutex.unlock();

        var list = try std.ArrayList([]const u8).initCapacity(allocator, self.sessions.count());

        var iter = self.sessions.keyIterator();
        while (iter.next()) |key_ptr| {
            try list.append(try allocator.dupe(u8, key_ptr.*));
        }

        return list.toOwnedSlice();
    }

    pub fn readNotification(self: *McpRegistry, server_id: []const u8) !?protocol.Notification {
        const session = self.getServer(server_id) orelse {
            return McpError.ServerNotFound;
        };

        return try session.readNotification();
    }

    pub fn serverCount(self: *McpRegistry) usize {
        self.mutex.lock();
        defer self.mutex.unlock();
        return self.sessions.count();
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "McpRegistry lifecycle" {
    const allocator = std.testing.allocator;

    var registry = McpRegistry.init(allocator);
    defer registry.deinit();

    // Start a server (using echo as mock)
    // Note: In real tests, use a proper MCP mock server
    // This test assumes an MCP server exists at /bin/echo

    // For now, just verify registry structure
    try std.testing.expectEqual(@as(usize, 0), registry.serverCount());
}

test "McpStatus enum" {
    try std.testing.expectEqual(@as(usize, 4), @typeInfo(McpStatus).Enum.fields.len);
    try std.testing.expectEqual(McpStatus.starting, McpStatus.starting);
    try std.testing.expectEqual(McpStatus.ready, McpStatus.ready);
}

test "McpError error set" {
    const err = McpError.ServerNotFound;
    _ = err;
}
