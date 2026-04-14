// ═══════════════════════════════════════════════════════════════════════════════
// Tree-sitter C API Bindings
// ═══════════════════════════════════════════════════════════════════════════════
//
// Zig extern declarations for tree-sitter C library.
// Mirrors the tree-sitter C API with Zig-friendly types where possible.

const std = @import("std");

// ═══════════════════════════════════════════════════════════════════════════════
// Supported Languages
// ═══════════════════════════════════════════════════════════════════════════════

pub const SupportedLanguage = struct {
    name: []const u8,
    extensions: []const []const u8,
    tree_sitter_language_fn: ?[]const u8,  // Function name in C library
};

/// Built-in supported languages (via tree-sitter)
pub const SUPPORTED_LANGUAGES = &[_]SupportedLanguage{
    .{
        .name = "python",
        .extensions = &.{ ".py" },
        .tree_sitter_language_fn = "tree_sitter_python",
    },
    .{
        .name = "javascript",
        .extensions = &.{ ".js", ".mjs", ".cjs" },
        .tree_sitter_language_fn = "tree_sitter_javascript",
    },
    .{
        .name = "typescript",
        .extensions = &.{ ".ts" },
        .tree_sitter_language_fn = "tree_sitter_typescript",
    },
    .{
        .name = "tsx",
        .extensions = &.{ ".tsx" },
        .tree_sitter_language_fn = "tree_sitter_tsx",
    },
    .{
        .name = "rust",
        .extensions = &.{ ".rs" },
        .tree_sitter_language_fn = "tree_sitter_rust",
    },
    .{
        .name = "go",
        .extensions = &.{ ".go" },
        .tree_sitter_language_fn = "tree_sitter_go",
    },
    .{
        .name = "c",
        .extensions = &.{ ".c", ".h" },
        .tree_sitter_language_fn = "tree_sitter_c",
    },
    .{
        .name = "cpp",
        .extensions = &.{ ".cpp", ".cc", ".cxx", ".hpp" },
        .tree_sitter_language_fn = "tree_sitter_cpp",
    },
    .{
        .name = "zig",
        .extensions = &.{ ".zig" },
        .tree_sitter_language_fn = "tree_sitter_zig",
    },
    .{
        .name = "elixir",
        .extensions = &.{ ".ex", ".exs" },
        .tree_sitter_language_fn = "tree_sitter_elixir",
    },
    .{
        .name = "json",
        .extensions = &.{ ".json" },
        .tree_sitter_language_fn = "tree_sitter_json",
    },
    .{
        .name = "markdown",
        .extensions = &.{ ".md", ".markdown" },
        .tree_sitter_language_fn = "tree_sitter_markdown",
    },
    .{
        .name = "toml",
        .extensions = &.{ ".toml" },
        .tree_sitter_language_fn = "tree_sitter_toml",
    },
};

/// Detect language from file extension
pub fn detectLanguage(file_path: []const u8) ?[]const u8 {
    const ext = std.fs.path.extension(file_path);
    
    for (SUPPORTED_LANGUAGES) |lang| {
        for (lang.extensions) |lang_ext| {
            if (std.mem.eql(u8, ext, lang_ext)) {
                return lang.name;
            }
        }
    }
    
    return null;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Opaque C Types
// ═══════════════════════════════════════════════════════════════════════════════

/// Opaque tree-sitter language pointer
pub const Language = opaque {};

/// Opaque parser pointer
pub const TSParser = opaque {};

/// Opaque tree pointer
pub const TSTree = opaque {};

/// Opaque query pointer
pub const TSQuery = opaque {};

/// Opaque query cursor pointer
pub const TSQueryCursor = opaque {};

/// Opaque tree cursor pointer
pub const TSTreeCursor = extern struct {
    tree: ?*const anyopaque,
    id: ?*const anyopaque,
    context: [2]u32,
};

// ═══════════════════════════════════════════════════════════════════════════════
// Enums
// ═══════════════════════════════════════════════════════════════════════════════

pub const TSInputEncoding = enum(c_uint) {
    utf8 = 0,
    utf16 = 1,
    utf16_be = 2,
};

pub const TSSymbolType = enum(c_uint) {
    regular = 0,
    anonymous = 1,
    auxiliary = 2,
};

pub const TSLogType = enum(c_uint) {
    parse = 0,
    lex = 1,
};

pub const TSQueryError = enum(c_uint) {
    none = 0,
    syntax = 1,
    node_type = 2,
    field = 3,
    capture = 4,
    structure = 5,
};

// ═══════════════════════════════════════════════════════════════════════════════
// C Structs
// ═══════════════════════════════════════════════════════════════════════════════

pub const TSPoint = extern struct {
    row: u32,
    column: u32,
};

pub const TSRange = extern struct {
    start_point: TSPoint,
    end_point: TSPoint,
    start_byte: u32,
    end_byte: u32,
};

pub const TSInput = extern struct {
    payload: ?*anyopaque,
    read: ?*const fn (
        payload: ?*anyopaque,
        byte_offset: u32,
        position: TSPoint,
        bytes_read: *u32,
    ) callconv(.C) [*c]const u8,
    encoding: TSInputEncoding,
};

pub const TSLanguageMetadata = extern struct {
    major_version: u16,
    minor_version: u16,
    patch_version: u16,
};

pub const TSLanguageFn = *const fn () callconv(std.builtin.CallingConvention.c) *const Language;

// ═══════════════════════════════════════════════════════════════════════════════
// Extern Function Declarations
// ═══════════════════════════════════════════════════════════════════════════════

// Parser functions
pub extern "c" fn ts_parser_new() ?*TSParser;
pub extern "c" fn ts_parser_delete(parser: ?*TSParser) void;
pub extern "c" fn ts_parser_set_language(parser: *TSParser, language: *const Language) bool;
pub extern "c" fn ts_parser_language(parser: *TSParser) ?*const Language;
pub extern "c" fn ts_parser_parse(
    parser: *TSParser,
    old_tree: ?*const TSTree,
    input: TSInput,
) ?*TSTree;
pub extern "c" fn ts_parser_parse_string(
    parser: *TSParser,
    old_tree: ?*const TSTree,
    string: [*c]const u8,
    length: u32,
) ?*TSTree;
pub extern "c" fn ts_parser_parse_string_encoding(
    parser: *TSParser,
    old_tree: ?*const TSTree,
    string: [*c]const u8,
    length: u32,
    encoding: TSInputEncoding,
) ?*TSTree;
pub extern "c" fn ts_parser_reset(parser: *TSParser) void;
pub extern "c" fn ts_parser_set_timeout_micros(parser: *TSParser, timeout: u64) void;
pub extern "c" fn ts_parser_timeout_micros(parser: *TSParser) u64;

// Tree functions
pub extern "c" fn ts_tree_delete(tree: ?*TSTree) void;
pub extern "c" fn ts_tree_copy(tree: *const TSTree) *TSTree;
pub extern "c" fn ts_tree_root_node(tree: *const TSTree) TSNode;
pub extern "c" fn ts_tree_edit(tree: *TSTree, edit: *const TSInputEdit) void;
pub extern "c" fn ts_tree_get_changed_ranges(
    old_tree: *const TSTree,
    new_tree: *const TSTree,
    count: *u32,
) [*c]TSRange;
pub extern "c" fn ts_tree_language(tree: *const TSTree) ?*const Language;

// Node functions
pub const TSNode = extern struct {
    context: [4]u32,
    id: ?*const anyopaque,
    tree: ?*const TSTree,
};

pub extern "c" fn ts_node_type(node: TSNode) [*c]const u8;
pub extern "c" fn ts_node_symbol(node: TSNode) u16;
pub extern "c" fn ts_node_start_byte(node: TSNode) u32;
pub extern "c" fn ts_node_end_byte(node: TSNode) u32;
pub extern "c" fn ts_node_start_point(node: TSNode) TSPoint;
pub extern "c" fn ts_node_end_point(node: TSNode) TSPoint;
pub extern "c" fn ts_node_string(node: TSNode) [*c]u8;
pub extern "c" fn ts_node_is_null(node: TSNode) bool;
pub extern "c" fn ts_node_is_named(node: TSNode) bool;
pub extern "c" fn ts_node_is_missing(node: TSNode) bool;
pub extern "c" fn ts_node_is_extra(node: TSNode) bool;
pub extern "c" fn ts_node_has_changes(node: TSNode) bool;
pub extern "c" fn ts_node_has_error(node: TSNode) bool;
pub extern "c" fn ts_node_eq(a: TSNode, b: TSNode) bool;
pub extern "c" fn ts_node_parent(node: TSNode) TSNode;
pub extern "c" fn ts_node_child(node: TSNode, index: u32) TSNode;
pub extern "c" fn ts_node_child_count(node: TSNode) u32;
pub extern "c" fn ts_node_named_child(node: TSNode, index: u32) TSNode;
pub extern "c" fn ts_node_named_child_count(node: TSNode) u32;
pub extern "c" fn ts_node_next_sibling(node: TSNode) TSNode;
pub extern "c" fn ts_node_prev_sibling(node: TSNode) TSNode;
pub extern "c" fn ts_node_next_named_sibling(node: TSNode) TSNode;
pub extern "c" fn ts_node_prev_named_sibling(node: TSNode) TSNode;
pub extern "c" fn ts_node_first_child_for_byte(node: TSNode, byte: u32) TSNode;
pub extern "c" fn ts_node_first_named_child_for_byte(node: TSNode, byte: u32) TSNode;
pub extern "c" fn ts_node_descendant_for_byte_range(node: TSNode, start: u32, end: u32) TSNode;
pub extern "c" fn ts_node_descendant_for_point_range(node: TSNode, start: TSPoint, end: TSPoint) TSNode;
pub extern "c" fn ts_node_edit(node: *TSNode, edit: *const TSInputEdit) void;

// Tree cursor functions
pub extern "c" fn ts_tree_cursor_new(node: TSNode) TSTreeCursor;
pub extern "c" fn ts_tree_cursor_delete(cursor: *TSTreeCursor) void;
pub extern "c" fn ts_tree_cursor_reset(cursor: *TSTreeCursor, node: TSNode) void;
pub extern "c" fn ts_tree_cursor_current_node(cursor: *TSTreeCursor) TSNode;
pub extern "c" fn ts_tree_cursor_current_field_name(cursor: *const TSTreeCursor) [*c]const u8;
pub extern "c" fn ts_tree_cursor_current_field_id(cursor: *const TSTreeCursor) ?*anyopaque;
pub extern "c" fn ts_tree_cursor_goto_parent(cursor: *TSTreeCursor) bool;
pub extern "c" fn ts_tree_cursor_goto_next_sibling(cursor: *TSTreeCursor) bool;
pub extern "c" fn ts_tree_cursor_goto_first_child(cursor: *TSTreeCursor) bool;
pub extern "c" fn ts_tree_cursor_goto_first_child_for_byte(cursor: *TSTreeCursor, byte: u32) i64;
pub extern "c" fn ts_tree_cursor_copy(cursor: *const TSTreeCursor) TSTreeCursor;

// Language functions
pub extern "c" fn ts_language_symbol_count(language: *const Language) u32;
pub extern "c" fn ts_language_symbol_name(language: *const Language, symbol: u16) [*c]const u8;
pub extern "c" fn ts_language_symbol_for_name(
    language: *const Language,
    name: [*c]const u8,
    length: u32,
    is_named: bool,
) u16;
pub extern "c" fn ts_language_field_count(language: *const Language) u32;
pub extern "c" fn ts_language_field_name_for_id(language: *const Language, id: u16) [*c]const u8;
pub extern "c" fn ts_language_field_id_for_name(
    language: *const Language,
    name: [*c]const u8,
    length: u32,
) u16;
pub extern "c" fn ts_language_symbol_type(language: *const Language, symbol: u16) TSSymbolType;
pub extern "c" fn ts_language_version(language: *const Language) u32;
pub extern "c" fn ts_language_metadata(language: *const Language) ?*const TSLanguageMetadata;

// Query functions
pub extern "c" fn ts_query_new(
    language: *const Language,
    source: [*c]const u8,
    source_len: u32,
    error_offset: *u32,
    error_type: *TSQueryError,
) ?*TSQuery;
pub extern "c" fn ts_query_delete(query: ?*TSQuery) void;
pub extern "c" fn ts_query_pattern_count(query: *const TSQuery) u32;
pub extern "c" fn ts_query_capture_count(query: *const TSQuery) u32;
pub extern "c" fn ts_query_string_count(query: *const TSQuery) u32;
pub extern "c" fn ts_query_start_byte_for_pattern(query: *const TSQuery, index: u32) u32;
pub extern "c" fn ts_query_end_byte_for_pattern(query: *const TSQuery, index: u32) u32;
pub extern "c" fn ts_query_predicates_for_pattern(
    query: *const TSQuery,
    index: u32,
    length: *u32,
) [*c]const TSQueryPredicateStep;
pub extern "c" fn ts_query_is_pattern_rooted(query: *const TSQuery, index: u32) bool;
pub extern "c" fn ts_query_is_pattern_non_local(query: *const TSQuery, index: u32) bool;
pub extern "c" fn ts_query_is_pattern_guaranteed_at_step(query: *const TSQuery, byte_offset: u32) bool;
pub extern "c" fn ts_query_capture_name_for_id(
    query: *const TSQuery,
    id: u32,
    length: *u32,
) [*c]const u8;
pub extern "c" fn ts_query_capture_quantifier_for_id(
    query: *const TSQuery,
    pattern_index: u32,
    capture_index: u32,
) TSQuantifier;
pub extern "c" fn ts_query_string_value_for_id(
    query: *const TSQuery,
    id: u32,
    length: *u32,
) [*c]const u8;
pub extern "c" fn ts_query_disable_capture(query: *TSQuery, name: [*c]const u8, length: u32) void;
pub extern "c" fn ts_query_disable_pattern(query: *TSQuery, index: u32) void;

pub const TSQueryPredicateStep = extern struct {
    type: TSQueryPredicateStepType,
    value_id: u32,
};

pub const TSQueryPredicateStepType = enum(c_uint) {
    done = 0,
    capture = 1,
    string = 2,
};

pub const TSQuantifier = enum(c_uint) {
    zero = 0,
    zero_or_one = 1,
    zero_or_more = 2,
    one = 3,
    one_or_more = 4,
};

// Query cursor functions
pub extern "c" fn ts_query_cursor_new() ?*TSQueryCursor;
pub extern "c" fn ts_query_cursor_delete(cursor: ?*TSQueryCursor) void;
pub extern "c" fn ts_query_cursor_exec(cursor: *TSQueryCursor, query: *const TSQuery, node: TSNode) void;
pub extern "c" fn ts_query_cursor_did_exceed_match_limit(cursor: *const TSQueryCursor) bool;
pub extern "c" fn ts_query_cursor_set_match_limit(cursor: *TSQueryCursor, limit: u32) void;
pub extern "c" fn ts_query_cursor_match_limit(cursor: *const TSQueryCursor) u32;
pub extern "c" fn ts_query_cursor_set_byte_range(cursor: *TSQueryCursor, start: u32, end: u32) void;
pub extern "c" fn ts_query_cursor_set_point_range(cursor: *TSQueryCursor, start: TSPoint, end: TSPoint) void;
pub extern "c" fn ts_query_cursor_next_match(cursor: *TSQueryCursor, match: *TSQueryMatch) bool;
pub extern "c" fn ts_query_cursor_remove_match(cursor: *TSQueryCursor, index: u32) void;
pub extern "c" fn ts_query_cursor_next_capture(
    cursor: *TSQueryCursor,
    match: *TSQueryMatch,
    capture_index: *u32,
) bool;

pub const TSQueryMatch = extern struct {
    id: u32,
    pattern_index: u16,
    capture_count: u16,
    captures: [*c]TSQueryCapture,
};

pub const TSQueryCapture = extern struct {
    node: TSNode,
    index: u32,
};

// Query predicate functions
pub extern "c" fn ts_query_cursor_set_predicate_func(
    cursor: *TSQueryCursor,
    payload: ?*anyopaque,
    predicate: TSQueryPredicateFunc,
) void;

pub const TSQueryPredicateFunc = ?*const fn (
    payload: ?*anyopaque,
    predicate_steps: [*c]const TSQueryPredicateStep,
    step_count: u32,
    match: *TSQueryMatch,
    capture_count: u32,
) callconv(.C) bool;

// Input edit structure (for incremental parsing)
pub const TSInputEdit = extern struct {
    start_byte: u32,
    old_end_byte: u32,
    new_end_byte: u32,
    start_point: TSPoint,
    old_end_point: TSPoint,
    new_end_point: TSPoint,
};

// ═══════════════════════════════════════════════════════════════════════════════
// Zig-friendly Wrappers
// ═══════════════════════════════════════════════════════════════════════════════

pub const Parser = struct {
    raw: ?*TSParser,
    
    const Self = @This();
    
    pub fn init() error{OutOfMemory}!Self {
        const raw = ts_parser_new();
        if (raw == null) return error.OutOfMemory;
        return .{ .raw = raw };
    }
    
    pub fn deinit(self: *Self) void {
        if (self.raw) |p| {
            ts_parser_delete(p);
            self.raw = null;
        }
    }
    
    pub fn setLanguage(self: *Self, language: *const Language) bool {
        if (self.raw) |p| {
            return ts_parser_set_language(p, language);
        }
        return false;
    }
    
    pub fn parseString(self: *Self, source: []const u8) ?*TSTree {
        if (self.raw) |p| {
            return ts_parser_parse_string(p, null, source.ptr, @intCast(source.len));
        }
        return null;
    }
    
    pub fn parseStringIncremental(
        self: *Self,
        old_tree: ?*const TSTree,
        source: []const u8,
    ) ?*TSTree {
        if (self.raw) |p| {
            return ts_parser_parse_string(p, old_tree, source.ptr, @intCast(source.len));
        }
        return null;
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "language detection" {
    try std.testing.expectEqualStrings("python", detectLanguage("test.py").?);
    try std.testing.expectEqualStrings("javascript", detectLanguage("test.js").?);
    try std.testing.expectEqualStrings("rust", detectLanguage("test.rs").?);
    try std.testing.expect(detectLanguage("test.unknown") == null);
}
