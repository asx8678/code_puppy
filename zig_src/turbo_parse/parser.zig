// ═══════════════════════════════════════════════════════════════════════════════
// Parser - Tree-sitter Parse Operations
// ═══════════════════════════════════════════════════════════════════════════════
//
// Migration from: turbo_parse/src/parser.rs
//
// High-level parse operations wrapping the tree-sitter C API.
// Handles language selection, incremental parsing, and error recovery.

const std = @import("std");
const c_api = @import("c_api.zig");
const cache = @import("cache.zig");
const languages = @import("languages.zig");

// ═══════════════════════════════════════════════════════════════════════════════
// Parser Configuration
// ═══════════════════════════════════════════════════════════════════════════════

pub const ParserConfig = struct {
    timeout_micros: u64 = 1000000,  // 1 second default
    use_cache: bool = true,
    max_file_size: usize = 16 * 1024 * 1024,  // 16MB
};

pub const ParseError = error{
    LanguageNotFound,
    ParserInitFailed,
    ParseTimeout,
    FileTooLarge,
    FileNotFound,
    IoError,
    OutOfMemory,
    IncrementalEditFailed,
};

// ═══════════════════════════════════════════════════════════════════════════════
// Parse Result Types
// ═══════════════════════════════════════════════════════════════════════════════

pub const ParseResult = struct {
    language: []const u8,
    tree: ?*c_api.TSTree,  // Owned by caller
    root_node: c_api.TSNode,
    parse_time_ms: f64,
    from_cache: bool,
    success: bool,
    errors: []ParseErrorInfo,
    
    pub fn deinit(self: *ParseResult, allocator: std.mem.Allocator) void {
        allocator.free(self.language);
        if (self.tree) |t| {
            c_api.ts_tree_delete(t);
        }
        for (self.errors) |err| {
            if (err.message) |msg| allocator.free(msg);
        }
        allocator.free(self.errors);
    }
};

pub const ParseErrorInfo = struct {
    line: u32,
    column: u32,
    message: ?[]const u8,
};

// ═══════════════════════════════════════════════════════════════════════════════
// Incremental Edit Support
// ═══════════════════════════════════════════════════════════════════════════════

pub const InputEdit = struct {
    start_byte: u32,
    old_end_byte: u32,
    new_end_byte: u32,
    start_line: u32,
    start_column: u32,
    old_end_line: u32,
    old_end_column: u32,
    new_end_line: u32,
    new_end_column: u32,
    
    /// Convert to tree-sitter TSInputEdit
    pub fn toTSInputEdit(self: @This()) c_api.TSInputEdit {
        return .{
            .start_byte = self.start_byte,
            .old_end_byte = self.old_end_byte,
            .new_end_byte = self.new_end_byte,
            .start_point = .{
                .row = self.start_line,
                .column = self.start_column,
            },
            .old_end_point = .{
                .row = self.old_end_line,
                .column = self.old_end_column,
            },
            .new_end_point = .{
                .row = self.new_end_line,
                .column = self.new_end_column,
            },
        };
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Parser
// ═══════════════════════════════════════════════════════════════════════════════

pub const Parser = struct {
    allocator: std.mem.Allocator,
    config: ParserConfig,
    cached_parsers: std.StringHashMap(*c_api.TSParser),
    
    const Self = @This();
    
    pub fn init(allocator: std.mem.Allocator) Self {
        return .{
            .allocator = allocator,
            .config = .{},
            .cached_parsers = std.StringHashMap(*c_api.TSParser).init(allocator),
        };
    }
    
    pub fn initWithConfig(allocator: std.mem.Allocator, config: ParserConfig) Self {
        return .{
            .allocator = allocator,
            .config = config,
            .cached_parsers = std.StringHashMap(*c_api.TSParser).init(allocator),
        };
    }
    
    pub fn deinit(self: *Self) void {
        var iter = self.cached_parsers.valueIterator();
        while (iter.next()) |parser| {
            c_api.ts_parser_delete(parser.*);
        }
        self.cached_parsers.deinit();
    }
    
    /// Parse source code directly
    pub fn parseSource(
        self: *Self,
        source: []const u8,
        language: []const u8,
        maybe_cache: ?*cache.ParseCache,
    ) ParseError!ParseResult {
        const start_time = std.time.milliTimestamp();
        
        // Check cache first
        if (self.config.use_cache) {
            if (maybe_cache) |c| {
                const key = cache.CacheKey{
                    .content_hash = cache.ParseCache.computeContentHash(source),
                    .language = language,
                };
                
                if (c.get(key)) |cached| {
                    return ParseResult{
                        .language = try self.allocator.dupe(u8, language),
                        .tree = cached.tree,
                        .root_node = c_api.ts_tree_root_node(cached.tree),
                        .parse_time_ms = 0.0,
                        .from_cache = true,
                        .success = true,
                        .errors = try self.allocator.alloc(ParseErrorInfo, 0),
                    };
                }
            }
        }
        
        // Get or create parser for language
        const parser = try self.getOrCreateParser(language);
        
        // Set timeout
        c_api.ts_parser_set_timeout_micros(parser, self.config.timeout_micros);
        
        // Parse
        const tree = c_api.ts_parser_parse_string(parser, null, source.ptr, @intCast(source.len));
        
        if (tree == null) {
            return error.ParseTimeout;
        }
        
        const duration_ms = @as(f64, @floatFromInt(std.time.milliTimestamp() - start_time));
        const root = c_api.ts_tree_root_node(tree);
        
        // Extract errors
        const errors = try self.extractParseErrors(tree, source);
        
        // Cache result
        if (self.config.use_cache) {
            if (maybe_cache) |c| {
                const key = cache.CacheKey{
                    .content_hash = cache.ParseCache.computeContentHash(source),
                    .language = try self.allocator.dupe(u8, language),
                };
                
                // Copy tree for cache
                const cached_tree = c_api.ts_tree_copy(tree);
                c.put(key, cached_tree, language) catch |err| {
                    // Cache failure shouldn't fail parse
                    c_api.ts_tree_delete(cached_tree);
                    _ = err;
                };
            }
        }
        
        return ParseResult{
            .language = try self.allocator.dupe(u8, language),
            .tree = tree,
            .root_node = root,
            .parse_time_ms = duration_ms,
            .from_cache = false,
            .success = c_api.ts_node_has_error(root) == false,
            .errors = errors,
        };
    }
    
    /// Parse file from disk
    pub fn parseFile(
        self: *Self,
        file_path: []const u8,
        maybe_language: ?[]const u8,
        maybe_cache: ?*cache.ParseCache,
    ) ParseError!ParseResult {
        // Detect language if not provided
        const language = if (maybe_language) |l| l else blk: {
            if (c_api.detectLanguage(file_path)) |lang| {
                break :blk lang;
            }
            return error.LanguageNotFound;
        };
        
        // Read file
        const source = std.fs.cwd().readFileAlloc(
            self.allocator,
            file_path,
            self.config.max_file_size,
        ) catch |err| return switch (err) {
            error.FileNotFound => error.FileNotFound,
            error.AccessDenied => error.IoError,
            error.FileTooBig => error.FileTooLarge,
            else => error.IoError,
        };
        defer self.allocator.free(source);
        
        return self.parseSource(source, language, maybe_cache);
    }
    
    /// Parse incrementally with edit information
    pub fn parseIncremental(
        self: *Self,
        old_tree: *c_api.TSTree,
        edited_source: []const u8,
        edit: InputEdit,
        language: []const u8,
    ) ParseError!ParseResult {
        const start_time = std.time.milliTimestamp();
        
        // Get parser
        const parser = try self.getOrCreateParser(language);
        c_api.ts_parser_set_timeout_micros(parser, self.config.timeout_micros);
        
        // Edit the old tree
        var ts_edit = edit.toTSInputEdit();
        c_api.ts_tree_edit(old_tree, &ts_edit);
        
        // Re-parse
        const tree = c_api.ts_parser_parse_string(parser, old_tree, edited_source.ptr, @intCast(edited_source.len));
        
        if (tree == null) {
            return error.ParseTimeout;
        }
        
        const duration_ms = @as(f64, @floatFromInt(std.time.milliTimestamp() - start_time));
        const root = c_api.ts_tree_root_node(tree);
        const errors = try self.extractParseErrors(tree, edited_source);
        
        return ParseResult{
            .language = try self.allocator.dupe(u8, language),
            .tree = tree,
            .root_node = root,
            .parse_time_ms = duration_ms,
            .from_cache = false,
            .success = c_api.ts_node_has_error(root) == false,
            .errors = errors,
        };
    }
    
    /// Get or create a parser for a specific language
    fn getOrCreateParser(self: *Self, language: []const u8) ParseError!*c_api.TSParser {
        // Check cache
        if (self.cached_parsers.get(language)) |parser| {
            return parser;
        }
        
        // Create new parser
        const parser = c_api.ts_parser_new();
        if (parser == null) {
            return error.ParserInitFailed;
        }
        
        // Set language (this is where we'd load the actual tree-sitter language)
        // TODO(code-puppy-zig-020): Load actual tree-sitter language functions
        // For now this is a placeholder
        const lang_ptr = getTreeSitterLanguage(language);
        if (lang_ptr == null) {
            c_api.ts_parser_delete(parser);
            return error.LanguageNotFound;
        }
        
        const success = c_api.ts_parser_set_language(parser, lang_ptr);
        if (!success) {
            c_api.ts_parser_delete(parser);
            return error.LanguageNotFound;
        }
        
        // Cache it
        try self.cached_parsers.put(
            try self.allocator.dupe(u8, language),
            parser,
        );
        
        return parser;
    }
    
    /// Extract parse errors from tree
    fn extractParseErrors(
        self: *Self,
        tree: *c_api.TSTree,
        source: []const u8,
    ) error{OutOfMemory}![]ParseErrorInfo {
        var errors = std.ArrayList(ParseErrorInfo).init(self.allocator);
        defer errors.deinit();
        
        const root = c_api.ts_tree_root_node(tree);
        
        // Walk tree looking for ERROR nodes
        try self.collectErrors(root, source, &errors);
        
        return try errors.toOwnedSlice();
    }
    
    fn collectErrors(
        self: *Self,
        node: c_api.TSNode,
        source: []const u8,
        errors: *std.ArrayList(ParseErrorInfo),
    ) error{OutOfMemory}!void {
        const type_name = c_api.ts_node_type(node);
        const is_error_node = std.mem.eql(u8, std.mem.span(type_name), "ERROR");
        
        if (is_error_node) {
            const start = c_api.ts_node_start_point(node);
            
            // Extract message from source context
            const start_byte = c_api.ts_node_start_byte(node);
            const end_byte = c_api.ts_node_end_byte(node);
            const error_text = source[start_byte..end_byte];
            
            const msg = if (error_text.len > 0) 
                try std.fmt.allocPrint(self.allocator, "Unexpected: {s}", .{error_text[0..@min(error_text.len, 50)]})
            else 
                null;
            
            try errors.append(.{
                .line = start.row,
                .column = start.column,
                .message = msg,
            });
        }
        
        // Recurse to children
        const child_count = c_api.ts_node_child_count(node);
        var i: u32 = 0;
        while (i < child_count) : (i += 1) {
            try self.collectErrors(c_api.ts_node_child(node, i), source, errors);
        }
    }
};

/// Get tree-sitter language pointer by name
/// Delegates to the language registry for grammar resolution
fn getTreeSitterLanguage(language: []const u8) ?*const c_api.Language {
    // Use the language registry to look up the grammar
    return languages.getLanguage(language);
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "input edit conversion" {
    const edit = InputEdit{
        .start_byte = 10,
        .old_end_byte = 20,
        .new_end_byte = 25,
        .start_line = 1,
        .start_column = 10,
        .old_end_line = 1,
        .old_end_column = 20,
        .new_end_line = 1,
        .new_end_column = 25,
    };
    
    const ts_edit = edit.toTSInputEdit();
    
    try std.testing.expectEqual(@as(u32, 10), ts_edit.start_byte);
    try std.testing.expectEqual(@as(u32, 1), ts_edit.start_point.row);
}
