// ═══════════════════════════════════════════════════════════════════════════════
// Process Management - Session Registry and Process Spawning
// ═══════════════════════════════════════════════════════════════════════════════
//
// Manages subprocess lifecycle: spawning, signal handling, output streaming,
// and PTY allocation for interactive processes.

const std = @import("std");
const protocol = @import("protocol.zig");

// ═══════════════════════════════════════════════════════════════════════════════
// Constants
// ═══════════════════════════════════════════════════════════════════════════════

const DEFAULT_KILL_TIMEOUT_MS = 5000; // 5 seconds for graceful shutdown
const SIGTERM = 15;
const SIGKILL = 9;

// ═══════════════════════════════════════════════════════════════════════════════
// Session Types
// ═══════════════════════════════════════════════════════════════════════════════

pub const SessionId = u64;

pub const ProcessState = enum {
    running,
    exited,
    killed,
    error_state,
};

pub const Session = struct {
    id: SessionId,
    pid: ?std.process.Child.Id,
    state: ProcessState,
    exit_code: ?u32,
    child: ?std.process.Child,
    pty: ?PtyHandle,

    // Output capture configuration
    capture_stdout: bool,
    capture_stderr: bool,

    // Streams for async reading
    stdout_thread: ?std.Thread,
    stderr_thread: ?std.Thread,

    // Parent pointer for notifications
    registry: ?*SessionRegistry,

    pub fn init(id: SessionId, registry: *SessionRegistry) Session {
        return .{
            .id = id,
            .pid = null,
            .state = .running,
            .exit_code = null,
            .child = null,
            .pty = null,
            .capture_stdout = true,
            .capture_stderr = true,
            .stdout_thread = null,
            .stderr_thread = null,
            .registry = registry,
        };
    }

    pub fn deinit(self: *Session, allocator: std.mem.Allocator) void {
        // Stop any running child
        if (self.child) |*child| {
            _ = self.killInternal(child, SIGKILL, allocator) catch {};
            _ = child.wait() catch {};
        }

        // Clean up PTY if allocated
        if (self.pty) |*pty| {
            pty.deinit();
        }

        // Join threads if they exist
        if (self.stdout_thread) |thread| {
            thread.join();
        }
        if (self.stderr_thread) |thread| {
            thread.join();
        }
    }

    /// Send signal to process (internal)
    fn killInternal(
        self: *Session,
        child: *std.process.Child,
        sig: u32,
        allocator: std.mem.Allocator,
    ) !void {
        switch (builtin.os.tag) {
            .windows => {
                // Windows: Use TerminateProcess
                if (child.id) |pid| {
                    _ = pid;
                    // TODO(code-puppy-019d8a): Windows process termination
                    return error.UnsupportedPlatform;
                }
            },
            else => {
                _ = self;
                _ = allocator;
                // Unix: Use posix kill
                const posix = std.posix;
                if (child.id) |pid| {
                    _ = posix.kill(pid, @intCast(sig));
                }
            },
        }
    }
};

/// PTY handle for interactive sessions
pub const PtyHandle = struct {
    master_fd: i32,
    slave_fd: ?i32,
    rows: u16,
    cols: u16,

    pub fn deinit(self: *PtyHandle) void {
        switch (builtin.os.tag) {
            .windows => {},
            else => {
                const posix = std.posix;
                if (self.slave_fd) |fd| {
                    _ = posix.close(fd);
                }
                _ = posix.close(self.master_fd);
            },
        }
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Session Registry
// ═══════════════════════════════════════════════════════════════════════════════

pub const SessionRegistry = struct {
    allocator: std.mem.Allocator,
    sessions: std.AutoHashMap(SessionId, *Session),
    next_id: std.atomic.Value(SessionId),
    lock: std.Thread.Mutex,

    pub fn init(allocator: std.mem.Allocator) SessionRegistry {
        return .{
            .allocator = allocator,
            .sessions = std.AutoHashMap(SessionId, *Session).init(allocator),
            .next_id = std.atomic.Value(SessionId).init(1),
            .lock = std.Thread.Mutex{},
        };
    }

    pub fn deinit(self: *SessionRegistry) void {
        // Clean up all active sessions
        self.cleanupAll();
        self.sessions.deinit();
    }

    /// Create a new session and register it
    pub fn createSession(self: *SessionRegistry) !*Session {
        const id = self.next_id.fetchAdd(1, .monotonic);

        const session = try self.allocator.create(Session);
        errdefer self.allocator.destroy(session);

        session.* = Session.init(id, self);

        self.lock.lock();
        defer self.lock.unlock();

        try self.sessions.put(id, session);

        return session;
    }

    /// Get a session by ID
    pub fn getSession(self: *SessionRegistry, id: SessionId) ?*Session {
        self.lock.lock();
        defer self.lock.unlock();

        return self.sessions.get(id);
    }

    /// Remove and cleanup a session
    pub fn removeSession(self: *SessionRegistry, id: SessionId) void {
        self.lock.lock();
        defer self.lock.unlock();

        if (self.sessions.fetchRemove(id)) |entry| {
            var session = entry.value;
            session.deinit(self.allocator);
            self.allocator.destroy(session);
        }
    }

    /// Cleanup all sessions
    pub fn cleanupAll(self: *SessionRegistry) void {
        self.lock.lock();
        defer self.lock.unlock();

        var iter = self.sessions.valueIterator();
        while (iter.next()) |session_ptr| {
            var session = session_ptr.*;
            session.deinit(self.allocator);
            self.allocator.destroy(session);
        }
        self.sessions.clearRetainingCapacity();
    }

    /// Get active session count
    pub fn activeCount(self: *SessionRegistry) usize {
        self.lock.lock();
        defer self.lock.unlock();
        return self.sessions.count();
    }

    /// Send exit notification for a session
    pub fn notifyExit(self: *SessionRegistry, id: SessionId, exit_code: u32) void {
        _ = self;
        _ = id;
        _ = exit_code;
        // TODO(code-puppy-019d8a): Send exit notification through protocol
        // This will need access to the output writer
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Process Spawning
// ═══════════════════════════════════════════════════════════════════════════════

const builtin = @import("builtin");

pub const SpawnOptions = struct {
    command: []const u8,
    args: []const []const u8,
    env: ?[]const [2][]const u8 = null,
    cwd: ?[]const u8 = null,
    use_pty: bool = false,
    pty_rows: u16 = 24,
    pty_cols: u16 = 80,
};

pub const SpawnResult = struct {
    session: *Session,
    // Only populated if PTY not used
    stdin_fd: ?i32,
    stdout_fd: ?i32,
    stderr_fd: ?i32,
};

/// Spawn a new process and register it in the session registry
pub fn spawnProcess(
    registry: *SessionRegistry,
    options: SpawnOptions,
) !SpawnResult {
    // Create a new session
    const session = try registry.createSession();
    errdefer registry.removeSession(session.id);

    var stdin_fd: ?i32 = null;
    var stdout_fd: ?i32 = null;
    var stderr_fd: ?i32 = null;

    if (options.use_pty) {
        // TODO(code-puppy-019d8a): PTY allocation not yet implemented
        // This requires platform-specific PTY handling (posix_openpt, etc.)
        return error.UnsupportedFeature;
    } else {
        // Standard pipe-based spawning
        const allocator = registry.allocator;

        // Build argument array
        var argv = try std.ArrayList([]const u8).initCapacity(allocator, options.args.len + 1);
        defer argv.deinit();
        try argv.append(options.command);
        try argv.appendSlice(options.args);

        // Build environment if provided
        var env_map: ?std.process.EnvMap = null;
        if (options.env) |env_vars| {
            env_map = std.process.EnvMap.init(allocator);
            for (env_vars) |pair| {
                try env_map.?.put(pair[0], pair[1]);
            }
        }
        defer if (env_map) |*em| em.deinit();

        // Spawn the child process
        var child = std.process.Child.init(argv.items, allocator);
        child.stdin_behavior = .Pipe;
        child.stdout_behavior = .Pipe;
        child.stderr_behavior = .Pipe;

        if (options.cwd) |cwd| {
            child.cwd = cwd;
        }

        if (env_map) |*em| {
            child.env_map = em;
        }

        try child.spawn();

        // Store child in session
        session.child = child;
        session.pid = child.id;

        // Extract file descriptors for caller (Unix only)
        if (builtin.os.tag != .windows) {
            if (child.stdin) |*pipe| stdin_fd = pipe.handle;
            if (child.stdout) |*pipe| stdout_fd = pipe.handle;
            if (child.stderr) |*pipe| stderr_fd = pipe.handle;
        }
    }

    return SpawnResult{
        .session = session,
        .stdin_fd = stdin_fd,
        .stdout_fd = stdout_fd,
        .stderr_fd = stderr_fd,
    };
}

// ═══════════════════════════════════════════════════════════════════════════════
// Process Control
// ═══════════════════════════════════════════════════════════════════════════════

pub const KillOptions = struct {
    grace_period_ms: u32 = DEFAULT_KILL_TIMEOUT_MS,
    force: bool = false,
};

/// Kill a process with escalation from SIGTERM to SIGKILL
pub fn killProcess(
    session: *Session,
    options: KillOptions,
) !void {
    if (session.child == null) {
        return error.NoActiveProcess;
    }

    const child = &session.child.?;

    // Try graceful termination first (unless force=true)
    if (!options.force) {
        try session.killInternal(child, SIGTERM, session.registry.?.allocator);

        // Wait for process to exit gracefully
        const wait_result = try waitWithTimeout(child, options.grace_period_ms);

        if (wait_result) {
            session.state = .exited;
            session.exit_code = @intCast(wait_result.?);
            return;
        }
    }

    // Escalate to SIGKILL
    try session.killInternal(child, SIGKILL, session.registry.?.allocator);

    // Wait for death
    const exit_code = try child.wait();
    session.state = if (options.force) .killed else .exited;
    session.exit_code = @intCast(exit_code);
}

/// Wait for child process with timeout
fn waitWithTimeout(child: *std.process.Child, timeout_ms: u32) !?u32 {
    // Poll for exit with backoff
    var elapsed: u32 = 0;
    const poll_interval = 50; // 50ms initial poll

    while (elapsed < timeout_ms) {
        const result = try std.childProcess.tryWait(child);
        if (result) |exit_code| {
            return exit_code;
        }

        std.time.sleep(poll_interval * std.time.ns_per_ms);
        elapsed += poll_interval;
    }

    return null; // Timeout
}

/// Write data to process stdin
pub fn writeStdin(session: *Session, data: []const u8) !void {
    if (session.child) |*child| {
        if (child.stdin) |*stdin_pipe| {
            try stdin_pipe.writer().writeAll(data);
        } else {
            return error.NoStdinAvailable;
        }
    } else if (session.pty) |*pty| {
        // Write to PTY master
        _ = pty;
        // TODO(code-puppy-019d8a): PTY write not yet implemented
        return error.UnsupportedFeature;
    } else {
        return error.NoActiveProcess;
    }
}

/// Resize PTY dimensions
pub fn resizePty(session: *Session, rows: u16, cols: u16) !void {
    if (session.pty) |*pty| {
        pty.rows = rows;
        pty.cols = cols;

        // Platform-specific resize
        if (builtin.os.tag != .windows) {
            const posix = std.posix;
            var ws: posix.winsize = .{
                .ws_row = rows,
                .ws_col = cols,
                .ws_xpixel = 0,
                .ws_ypixel = 0,
            };
            _ = posix.ioctl(pty.master_fd, posix.T.IOCSWINSZ, @intFromPtr(&ws));
        }
    } else {
        return error.NoPtyAllocated;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Output Streaming (Async)
// ═══════════════════════════════════════════════════════════════════════════════

pub const OutputHandler = *const fn (session_id: SessionId, stream: []const u8, is_stderr: bool) void;

/// Start async output streaming for a session
pub fn startOutputStreaming(
    session: *Session,
    handler: OutputHandler,
    allocator: std.mem.Allocator,
) !void {
    if (session.child == null) {
        return error.NoActiveProcess;
    }

    const child = &session.child.?;

    // Start stdout reader thread
    if (session.capture_stdout and child.stdout != null) {
        const stdout_ctx = try allocator.create(StreamContext);
        stdout_ctx.* = .{
            .session_id = session.id,
            .pipe = &child.stdout.?,
            .handler = handler,
            .is_stderr = false,
            .allocator = allocator,
        };

        session.stdout_thread = try std.Thread.spawn(.{}, streamReaderThread, .{stdout_ctx});
    }

    // Start stderr reader thread
    if (session.capture_stderr and child.stderr != null) {
        const stderr_ctx = try allocator.create(StreamContext);
        stderr_ctx.* = .{
            .session_id = session.id,
            .pipe = &child.stderr.?,
            .handler = handler,
            .is_stderr = true,
            .allocator = allocator,
        };

        session.stderr_thread = try std.Thread.spawn(.{}, streamReaderThread, .{stderr_ctx});
    }
}

const StreamContext = struct {
    session_id: SessionId,
    pipe: *std.process.Child.Pipe,
    handler: OutputHandler,
    is_stderr: bool,
    allocator: std.mem.Allocator,
};

fn streamReaderThread(ctx: *StreamContext) void {
    defer ctx.allocator.destroy(ctx);

    var buffer: [4096]u8 = undefined;
    const reader = ctx.pipe.reader();

    while (true) {
        const bytes_read = reader.read(&buffer) catch break;
        if (bytes_read == 0) break;

        ctx.handler(ctx.session_id, buffer[0..bytes_read], ctx.is_stderr);
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "session registry lifecycle" {
    const allocator = std.testing.allocator;

    var registry = SessionRegistry.init(allocator);
    defer registry.deinit();

    // Create session
    const session = try registry.createSession();
    try std.testing.expectEqual(@as(SessionId, 1), session.id);

    // Retrieve session
    const retrieved = registry.getSession(1);
    try std.testing.expect(retrieved != null);
    try std.testing.expectEqual(session.id, retrieved.?.id);

    // Remove session
    registry.removeSession(1);
    try std.testing.expectEqual(@as(?*Session, null), registry.getSession(1));
}

test "spawn options defaults" {
    const opts = SpawnOptions{
        .command = "echo",
        .args = &.{"hello"},
    };

    try std.testing.expectEqualStrings("echo", opts.command);
    try std.testing.expectEqual(@as(?[]const u8, null), opts.cwd);
    try std.testing.expect(!opts.use_pty);
}

test "kill options defaults" {
    const opts = KillOptions{};

    try std.testing.expectEqual(@as(u32, DEFAULT_KILL_TIMEOUT_MS), opts.grace_period_ms);
    try std.testing.expect(!opts.force);
}
