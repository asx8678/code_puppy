// ═══════════════════════════════════════════════════════════════════════════════
// Operations - Core File Operation Implementations
// ═══════════════════════════════════════════════════════════════════════════════
//
// Migration from: turbo_ops/src/operations.rs
//
// Individual file operations that can be composed into batch operations.
// Optimized for Zig's async model and memory management.

const std = @import("std");

// ═══════════════════════════════════════════════════════════════════════════════
// Operation Types
// ═══════════════════════════════════════════════════════════════════════════════

pub const OperationType = enum {
    list_files,
    grep,
    read_files,
    stat,
};

pub const Operation = struct {
    op_type: OperationType,
    id: ?[]const u8,
    priority: u32 = 100,  // Lower = higher priority
    args: OperationArgs,
};

pub const OperationArgs = union(OperationType) {
    list_files: ListFilesArgs,
    grep: GrepArgs,
    read_files: ReadFilesArgs,
    stat: StatArgs,
};

pub const ListFilesArgs = struct {
    directory: []const u8,
    recursive: bool = true,
    include_hidden: bool = false,
    max_depth: ?usize = null,
    exclude_patterns: []const []const u8 = &.{},
};

pub const GrepArgs = struct {
    pattern: []const u8,
    directory: []const u8,
    case_insensitive: bool = false,
    file_extensions: []const []const u8 = &.{},
    max_results: ?usize = null,
};

pub const ReadFilesArgs = struct {
    file_paths: []const []const u8,
    start_line: ?usize = null,  // 1-indexed
    num_lines: ?usize = null,
    include_line_numbers: bool = false,
};

pub const StatArgs = struct {
    file_path: []const u8,
};

// ═══════════════════════════════════════════════════════════════════════════════
// Operation Results
// ═══════════════════════════════════════════════════════════════════════════════

pub const OperationResult = struct {
    operation_id: ?[]const u8,
    success: bool,
    duration_ms: f64,
    data: OperationData,
    error_message: ?[]const u8 = null,
};

pub const OperationData = union(OperationType) {
    list_files: ListFilesResult,
    grep: GrepResult,
    read_files: ReadFilesResult,
    stat: StatResult,
};

pub const ListFilesResult = struct {
    files: []FileInfo,
    total_count: usize,
    directory: []const u8,
    recursive: bool,
};

pub const FileInfo = struct {
    path: []const u8,
    is_directory: bool,
    size: ?u64,
    modified_time: ?i64,
};

pub const GrepResult = struct {
    matches: []Match,
    total_matches: usize,
    pattern: []const u8,
    directory: []const u8,
    files_searched: usize,
};

pub const Match = struct {
    file_path: []const u8,
    line_number: usize,
    column: usize,
    line_content: []const u8,
    match_start: usize,
    match_end: usize,
};

pub const ReadFilesResult = struct {
    files: []FileReadResult,
    total_files: usize,
    successful_reads: usize,
};

pub const FileReadResult = struct {
    file_path: []const u8,
    content: ?[]const u8,
    num_tokens: i64,
    num_lines: usize,
    err_msg: ?[]const u8,
    success: bool,
};

pub const StatResult = struct {
    path: []const u8,
    exists: bool,
    is_file: bool,
    is_directory: bool,
    size: u64,
    modified_time: i64,
    created_time: ?i64,
};

// ═══════════════════════════════════════════════════════════════════════════════
// Operation Errors
// ═══════════════════════════════════════════════════════════════════════════════

pub const OperationError = error{
    PathNotFound,
    PermissionDenied,
    InvalidPattern,
    FileTooLarge,
    IoError,
    OutOfMemory,
    NotAFile,
    NotADirectory,
};

// ═══════════════════════════════════════════════════════════════════════════════
// list_files Implementation
// ═══════════════════════════════════════════════════════════════════════════════

pub fn executeListFiles(
    allocator: std.mem.Allocator,
    args: ListFilesArgs,
) OperationError!OperationResult {
    var arena = std.heap.ArenaAllocator.init(allocator);
    defer arena.deinit();
    const arena_allocator = arena.allocator();
    
    var files = std.ArrayList(FileInfo).init(arena_allocator);
    
    const start_time = std.time.milliTimestamp();
    
    // Determine max depth
    const max_depth = args.max_depth orelse if (args.recursive) 255 else 1;
    
    // Walk directory
    try walkDirectory(
        arena_allocator,
        args.directory,
        &files,
        0,
        max_depth,
        args.include_hidden,
        args.exclude_patterns,
    );
    
    const duration_ms = @as(f64, @floatFromInt(std.time.milliTimestamp() - start_time));
    
    // Copy results out of arena
    var result_files = try allocator.alloc(FileInfo, files.items.len);
    errdefer allocator.free(result_files);
    
    for (files.items, 0..) |info, i| {
        result_files[i] = .{
            .path = try allocator.dupe(u8, info.path),
            .is_directory = info.is_directory,
            .size = info.size,
            .modified_time = info.modified_time,
        };
    }
    
    return OperationResult{
        .operation_id = null,
        .success = true,
        .duration_ms = duration_ms,
        .data = .{ .list_files = .{
            .files = result_files,
            .total_count = result_files.len,
            .directory = try allocator.dupe(u8, args.directory),
            .recursive = args.recursive,
        } },
    };
}

fn walkDirectory(
    allocator: std.mem.Allocator,
    path: []const u8,
    files: *std.ArrayList(FileInfo),
    current_depth: usize,
    max_depth: usize,
    include_hidden: bool,
    exclude_patterns: []const []const u8,
) OperationError!void {
    if (current_depth >= max_depth) return;
    
    var dir = std.fs.cwd().openDir(path, .{ .iterate = true }) catch |err| {
        return switch (err) {
            error.FileNotFound => error.PathNotFound,
            error.AccessDenied => error.PermissionDenied,
            else => error.IoError,
        };
    };
    defer dir.close();
    
    var iter = dir.iterate();
    while (iter.next() catch return error.IoError) |entry| {
        // Skip hidden files
        if (!include_hidden and entry.name[0] == '.') continue;
        
        // Check exclude patterns
        if (isExcluded(entry.name, exclude_patterns)) continue;
        
        const full_path = std.fs.path.join(allocator, &.{ path, entry.name }) catch return error.OutOfMemory;
        
        switch (entry.kind) {
            .file => {
                // Get file stats
                const stat = dir.statFile(entry.name) catch continue;
                
                try files.append(.{
                    .path = full_path,
                    .is_directory = false,
                    .size = @intCast(stat.size),
                    .modified_time = @intCast(stat.mtime),
                });
            },
            .directory => {
                try files.append(.{
                    .path = full_path,
                    .is_directory = true,
                    .size = null,
                    .modified_time = null,
                });
                
                // Recurse
                try walkDirectory(
                    allocator,
                    full_path,
                    files,
                    current_depth + 1,
                    max_depth,
                    include_hidden,
                    exclude_patterns,
                );
            },
            else => continue,
        }
    }
}

fn isExcluded(name: []const u8, patterns: []const []const u8) bool {
    // TODO(code-puppy-zig-009): Implement glob matching
    // For now, simple substring match
    for (patterns) |pattern| {
        if (std.mem.indexOf(u8, name, pattern) != null) {
            return true;
        }
    }
    return false;
}

// ═══════════════════════════════════════════════════════════════════════════════
// grep Implementation
// ═══════════════════════════════════════════════════════════════════════════════

pub fn executeGrep(
    allocator: std.mem.Allocator,
    args: GrepArgs,
) OperationError!OperationResult {
    var arena = std.heap.ArenaAllocator.init(allocator);
    defer arena.deinit();
    const arena_allocator = arena.allocator();
    
    var matches = std.ArrayList(Match).init(arena_allocator);
    var files_searched: usize = 0;
    
    const start_time = std.time.milliTimestamp();
    
    // Compile pattern
    // TODO(code-puppy-zig-010): Add proper regex support
    // For now, literal string matching
    _ = args.case_insensitive;
    
    // Find files to search
    var files = std.ArrayList(FileInfo).init(arena_allocator);
    try walkDirectory(
        arena_allocator,
        args.directory,
        &files,
        0,
        255,
        false,
        &.{},
    );
    
    // Search each file
    for (files.items) |file| {
        if (file.is_directory) continue;
        
        // Filter by extension if specified
        if (args.file_extensions.len > 0) {
            const ext = std.fs.path.extension(file.path);
            var found = false;
            for (args.file_extensions) |wanted| {
                if (std.mem.eql(u8, ext, wanted)) {
                    found = true;
                    break;
                }
            }
            if (!found) continue;
        }
        
        files_searched += 1;
        
        try searchFile(arena_allocator, file.path, args.pattern, &matches);
        
        // Check result limit
        if (args.max_results) |max| {
            if (matches.items.len >= max) break;
        }
    }
    
    const duration_ms = @as(f64, @floatFromInt(std.time.milliTimestamp() - start_time));
    
    // Copy results
    var result_matches = try allocator.alloc(Match, matches.items.len);
    errdefer allocator.free(result_matches);
    
    for (matches.items, 0..) |m, i| {
        result_matches[i] = .{
            .file_path = try allocator.dupe(u8, m.file_path),
            .line_number = m.line_number,
            .column = m.column,
            .line_content = try allocator.dupe(u8, m.line_content),
            .match_start = m.match_start,
            .match_end = m.match_end,
        };
    }
    
    return OperationResult{
        .operation_id = null,
        .success = true,
        .duration_ms = duration_ms,
        .data = .{ .grep = .{
            .matches = result_matches,
            .total_matches = result_matches.len,
            .pattern = try allocator.dupe(u8, args.pattern),
            .directory = try allocator.dupe(u8, args.directory),
            .files_searched = files_searched,
        } },
    };
}

fn searchFile(
    allocator: std.mem.Allocator,
    file_path: []const u8,
    pattern: []const u8,
    matches: *std.ArrayList(Match),
) !void {
    const content = std.fs.cwd().readFileAlloc(allocator, file_path, 16 * 1024 * 1024) catch return;
    defer allocator.free(content);
    
    var line_number: usize = 1;
    var line_start: usize = 0;
    
    var i: usize = 0;
    while (i < content.len) : (i += 1) {
        if (content[i] == '\n') {
            const line = content[line_start..i];
            
            // Check for pattern in this line
            if (std.mem.indexOf(u8, line, pattern)) |pos| {
                // Found match
                const match_end = @min(line.len, pos + pattern.len + 50);
                const truncated = if (line.len > 100) line[0..match_end] else line;
                
                try matches.append(.{
                    .file_path = try allocator.dupe(u8, file_path),
                    .line_number = line_number,
                    .column = pos + 1,
                    .line_content = try allocator.dupe(u8, truncated),
                    .match_start = pos,
                    .match_end = pos + pattern.len,
                });
            }
            
            line_number += 1;
            line_start = i + 1;
        }
    }
    
    // Process final line if no trailing newline
    if (line_start < content.len) {
        const line = content[line_start..];
        if (std.mem.indexOf(u8, line, pattern)) |pos| {
            try matches.append(.{
                .file_path = try allocator.dupe(u8, file_path),
                .line_number = line_number,
                .column = pos + 1,
                .line_content = try allocator.dupe(u8, line),
                .match_start = pos,
                .match_end = pos + pattern.len,
            });
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// read_files Implementation
// ═══════════════════════════════════════════════════════════════════════════════

pub fn executeReadFiles(
    allocator: std.mem.Allocator,
    args: ReadFilesArgs,
) OperationError!OperationResult {
    const start_time = std.time.milliTimestamp();
    
    var results = try allocator.alloc(FileReadResult, args.file_paths.len);
    errdefer allocator.free(results);
    
    var successful_reads: usize = 0;
    
    for (args.file_paths, 0..) |path, i| {
        results[i] = readSingleFile(
            allocator,
            path,
            args.start_line,
            args.num_lines,
            args.include_line_numbers,
        ) catch |err| {
            successful_reads += 0;
            results[i] = .{
                .file_path = path,
                .content = null,
                .num_tokens = 0,
                .num_lines = 0,
                .err_msg = switch (err) {
                    error.FileNotFound => try allocator.dupe(u8, "File not found"),
                    error.AccessDenied => try allocator.dupe(u8, "Permission denied"),
                    error.FileTooLarge => try allocator.dupe(u8, "File too large"),
                    else => try allocator.dupe(u8, "Read error"),
                },
                .success = false,
            };
            continue;
        };
        successful_reads += 1;
    }
    
    const duration_ms = @as(f64, @floatFromInt(std.time.milliTimestamp() - start_time));
    
    return OperationResult{
        .operation_id = null,
        .success = true,
        .duration_ms = duration_ms,
        .data = .{ .read_files = .{
            .files = results,
            .total_files = args.file_paths.len,
            .successful_reads = successful_reads,
        } },
    };
}

fn readSingleFile(
    allocator: std.mem.Allocator,
    path: []const u8,
    maybe_start: ?usize,
    maybe_num: ?usize,
    include_line_numbers: bool,
) !FileReadResult {
    const content = try std.fs.cwd().readFileAlloc(allocator, path, 16 * 1024 * 1024);
    defer allocator.free(content);
    
    // Count lines
    var line_count: usize = 1;
    for (content) |c| {
        if (c == '\n') line_count += 1;
    }
    
    // Calculate line range
    const start_line = if (maybe_start) |s| @max(1, s) else 1;
    const start_byte = findLineStart(content, start_line);
    
    var end_byte: usize = content.len;
    if (maybe_num) |n| {
        const end_line = start_line + n;
        end_byte = findLineStart(content, end_line);
    }
    
    const range = content[start_byte..end_byte];
    
    // Estimate tokens (simplified)
    const num_tokens = @as(i64, @intFromFloat(std.math.ceil(@as(f64, @floatFromInt(range.len)) / 4.0)));
    
    // Format output
    var result: []u8 = undefined;
    if (include_line_numbers) {
        // Add line number prefixes
        var builder = std.ArrayList(u8).init(allocator);
        defer builder.deinit();
        
        var current_line = start_line;
        var line_start: usize = 0;
        
        while (line_start < range.len) {
            const line_prefix = try std.fmt.allocPrint(allocator, "{d:5} | ", .{current_line});
            defer allocator.free(line_prefix);
            try builder.appendSlice(line_prefix);
            
            // Find line end
            var line_end = line_start;
            while (line_end < range.len and range[line_end] != '\n') {
                line_end += 1;
            }
            
            try builder.appendSlice(range[line_start..line_end]);
            if (line_end < range.len) {
                try builder.append('\n');
                line_end += 1;  // Skip \n
            }
            
            current_line += 1;
            line_start = line_end;
        }
        
        result = try builder.toOwnedSlice();
    } else {
        result = try allocator.dupe(u8, range);
    }
    
    return FileReadResult{
        .file_path = try allocator.dupe(u8, path),
        .content = result,
        .num_tokens = num_tokens,
        .num_lines = line_count,
        .err_msg = null,
        .success = true,
    };
}

fn findLineStart(content: []const u8, target_line: usize) usize {
    if (target_line == 1) return 0;
    
    var current_line: usize = 1;
    var pos: usize = 0;
    
    while (pos < content.len) {
        if (content[pos] == '\n') {
            current_line += 1;
            if (current_line == target_line) {
                return pos + 1;
            }
        }
        pos += 1;
    }
    
    return content.len;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "findLineStart basic" {
    const content = "line1\nline2\nline3";
    
    try std.testing.expectEqual(@as(usize, 0), findLineStart(content, 1));
    try std.testing.expectEqual(@as(usize, 6), findLineStart(content, 2));
    try std.testing.expectEqual(@as(usize, 12), findLineStart(content, 3));
}
