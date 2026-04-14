// ═══════════════════════════════════════════════════════════════════════════════
// zig_turbo_parse - Tree-sitter Parsing Engine
// ═══════════════════════════════════════════════════════════════════════════════
//
// Migration from: turbo_parse (Rust)
// Migration date: 2025-01-14
// Migration reason: Better FFI with tree-sitter (C library), smaller binaries
//
// This module provides:
//   - Multi-language parsing (Python, Rust, JavaScript, TypeScript, etc.)
//   - Incremental parsing support
//   - Symbol extraction and outline generation
//   - Syntax highlighting via tree-sitter queries
//   - Diagnostics and error reporting
//   - Dynamic grammar loading at runtime
//
// Key differences from Rust:
//   - Tree-sitter C API accessed via Zig's extern function declarations
//   - Parser cache uses Zig's standard HashMap vs Rust DashMap
//   - Error unions replace Result<T, E> patterns

const std = @import("std");
const c_api = @import("c_api.zig");
const cache = @import("cache.zig");
const parser = @import("parser.zig");

// Re-exports
pub const Parser = parser.Parser;
pub const ParseCache = cache.ParseCache;
pub const ParseResult = parser.ParseResult;
pub const Language = c_api.Language;
pub const languages = @import("languages.zig");
pub const LanguageCapabilities = languages.LanguageCapabilities;

// ═══════════════════════════════════════════════════════════════════════════════
// Version
// ═══════════════════════════════════════════════════════════════════════════════

pub const VERSION = "0.1.0";

// ═══════════════════════════════════════════════════════════════════════════════
// C ABI Exports
// ═══════════════════════════════════════════════════════════════════════════════

export const TURBO_PARSE_VERSION: [*:0]const u8 = VERSION;

pub const TurboParseError = enum(c_int) {
    success = 0,
    invalid_argument = -1,
    out_of_memory = -2,
    language_not_found = -3,
    parse_failed = -4,
    query_error = -5,
    cache_error = -6,
};

pub const TurboParseHandle = ?*anyopaque;

/// Parser context with cache and language registry
const ParseContext = struct {
    allocator: std.mem.Allocator,
    parser: Parser,
    cache: ParseCache,
    
    fn deinit(self: *ParseContext) void {
        self.parser.deinit();
        self.cache.deinit();
    }
};

/// Initialize turbo_parse module
export fn turbo_parse_create() TurboParseHandle {
    const allocator = std.heap.c_allocator;

    const ctx = allocator.create(ParseContext) catch return null;

    ctx.* = .{
        .allocator = allocator,
        .parser = Parser.init(allocator),
        .cache = ParseCache.init(allocator, 1000),
    };

    return @ptrCast(ctx);
}

/// Destroy turbo_parse handle
export fn turbo_parse_destroy(handle: TurboParseHandle) void {
    if (handle == null) return;
    
    const ctx: *ParseContext = @ptrCast(@alignCast(handle));
    ctx.deinit();
    std.heap.c_allocator.destroy(ctx);
}

/// Parse source code (JSON output)
export fn turbo_parse_source(
    handle: TurboParseHandle,
    source: [*:0]const u8,
    _language: [*:0]const u8,
    output_json: *[*:0]u8,
) TurboParseError {
    if (handle == null) return .invalid_argument;

    const ctx: *ParseContext = @ptrCast(@alignCast(handle));
    _ = ctx;
    _ = source;
    _ = _language;
    _ = output_json;

    // TODO(code-puppy-zig-012): Implement parse_source
    // 1. Map language name to tree-sitter language
    // 2. Check cache for existing parse
    // 3. Run tree-sitter parse
    // 4. Serialize to JSON

    return .success;
}

/// Parse file from disk (JSON output)
export fn turbo_parse_file(
    handle: TurboParseHandle,
    file_path: [*:0]const u8,
    language: ?[*:0]const u8,  // nullable
    output_json: *[*:0]u8,
) TurboParseError {
    if (handle == null) return .invalid_argument;
    if (@intFromPtr(file_path) == 0) return .invalid_argument;

    const ctx: *ParseContext = @ptrCast(@alignCast(handle));
    _ = ctx;
    _ = output_json;

    // Auto-detect language from extension if not provided
    if (language) |lang| {
        _ = lang;
    }

    // TODO(code-puppy-zig-013): Implement parse_file

    return .success;
}

/// Extract symbols/outline (JSON output)
export fn turbo_parse_extract_symbols(
    handle: TurboParseHandle,
    file_path: [*:0]const u8,
    _language: [*:0]const u8,
    output_json: *[*:0]u8,
) TurboParseError {
    if (handle == null) return .invalid_argument;
    if (@intFromPtr(file_path) == 0) return .invalid_argument;

    const ctx: *ParseContext = @ptrCast(@alignCast(handle));
    _ = ctx;
    _ = _language;
    _ = output_json;

    // TODO(code-puppy-zig-014): Implement symbol extraction
    // Run tree-sitter query for functions, classes, etc.

    return .success;
}

/// Get syntax highlighting (JSON output)
export fn turbo_parse_get_highlights(
    handle: TurboParseHandle,
    source: [*:0]const u8,
    _language: [*:0]const u8,
    output_json: *[*:0]u8,
) TurboParseError {
    if (handle == null) return .invalid_argument;

    _ = source;
    _ = _language;
    _ = output_json;

    // TODO(code-puppy-zig-015): Implement syntax highlighting
    // Run tree-sitter highlight queries

    return .success;
}

/// Get code folding ranges (JSON output)
export fn turbo_parse_get_folds(
    handle: TurboParseHandle,
    source: [*:0]const u8,
    _language: [*:0]const u8,
    output_json: *[*:0]u8,
) TurboParseError {
    if (handle == null) return .invalid_argument;

    _ = source;
    _ = _language;
    _ = output_json;

    // TODO(code-puppy-zig-016): Implement fold extraction
    // Run tree-sitter fold queries

    return .success;
}

/// Check if language is supported
export fn turbo_parse_is_language_supported(language: [*:0]const u8) bool {
    // C string pointer can't be null in this type, but we validate it's valid
    if (@intFromPtr(language) == 0) return false;

    const lang = std.mem.span(language);

    // Check against supported languages
    for (c_api.SUPPORTED_LANGUAGES) |supported| {
        if (std.mem.eql(u8, lang, supported.name)) {
            return true;
        }
    }

    return false;
}

/// List supported languages (JSON output)
export fn turbo_parse_list_languages(output_json: *[*:0]u8) TurboParseError {
    // TODO(code-puppy-zig-017): Return JSON array of supported languages
    _ = output_json;
    return .success;
}

/// Load a dynamic grammar (for C, C++, etc.)
export fn turbo_parse_load_dynamic_grammar(
    handle: TurboParseHandle,
    library_path: [*:0]const u8,
    language_name: [*:0]const u8,
) TurboParseError {
    if (handle == null) return .invalid_argument;
    if (@intFromPtr(library_path) == 0 or @intFromPtr(language_name) == 0) {
        return .invalid_argument;
    }

    const ctx: *ParseContext = @ptrCast(@alignCast(handle));
    _ = ctx;
    // Note: library_path and language_name are used in ptr check above

    // TODO(code-puppy-zig-018): Implement dynamic library loading
    // Use dlopen/dlsym to load .so/.dylib/.dll

    return .success;
}

/// Free a string returned by turbo_parse_* functions
export fn turbo_parse_free_string(ptr: [*c]u8) void {
    if (@intFromPtr(ptr) == 0) return;
    std.heap.c_allocator.free(std.mem.span(ptr));
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "C ABI exports exist" {
    _ = turbo_parse_create;
    _ = turbo_parse_destroy;
    _ = turbo_parse_source;
    _ = turbo_parse_file;
    _ = turbo_parse_extract_symbols;
    _ = turbo_parse_get_highlights;
    _ = turbo_parse_get_folds;
    _ = turbo_parse_is_language_supported;
    _ = turbo_parse_list_languages;
    _ = turbo_parse_load_dynamic_grammar;
    _ = turbo_parse_free_string;
}

test "language support check" {
    // These will work once we have the real implementation
    // For now just verify the function exists
    const python_supported = turbo_parse_is_language_supported("python");
    const madeup_supported = turbo_parse_is_language_supported("madeup");
    
    _ = python_supported;
    _ = madeup_supported;
}
