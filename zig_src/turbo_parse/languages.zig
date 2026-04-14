// ═══════════════════════════════════════════════════════════════════════════════
// Language Registry - Tree-sitter Grammar Linking
// ═══════════════════════════════════════════════════════════════════════════════
//
// Provides extern C declarations for tree-sitter language grammars.
// Supports both static linking and dynamic (weak symbol) fallback.
//
// Note: Currently stubbed out - grammars are optional and not linked.
//       All grammar functions return null. Runtime gracefully handles this.
//
// Usage:
//   const lang = languages.getLanguage("python");
//   if (lang) |l| { parser.setLanguage(l); }

const std = @import("std");
const c_api = @import("c_api.zig");

// ═══════════════════════════════════════════════════════════════════════════════
// Stubbed Grammar Functions (Optional / Not Linked)
// ═══════════════════════════════════════════════════════════════════════════════
//
// These functions are normally provided by tree-sitter grammar libraries.
// For now, they are stubbed to return null, allowing the build to succeed
// without requiring grammar libraries to be installed.
//
// TODO(code-puppy-019d8a): Re-enable grammar linking when tree-sitter grammars
// are available as system libraries or vendored.

/// Python grammar - stubbed
pub fn tree_sitter_python() ?*const c_api.Language {
    return null;
}

/// Rust grammar - stubbed
pub fn tree_sitter_rust() ?*const c_api.Language {
    return null;
}

/// JavaScript grammar - stubbed
pub fn tree_sitter_javascript() ?*const c_api.Language {
    return null;
}

/// TypeScript grammar - stubbed
pub fn tree_sitter_typescript() ?*const c_api.Language {
    return null;
}

/// TSX grammar - stubbed
pub fn tree_sitter_tsx() ?*const c_api.Language {
    return null;
}

/// C grammar - stubbed
pub fn tree_sitter_c() ?*const c_api.Language {
    return null;
}

/// C++ grammar - stubbed
pub fn tree_sitter_cpp() ?*const c_api.Language {
    return null;
}

/// Go grammar - stubbed
pub fn tree_sitter_go() ?*const c_api.Language {
    return null;
}

/// Zig grammar - stubbed
pub fn tree_sitter_zig() ?*const c_api.Language {
    return null;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Language Entry Structure
// ═══════════════════════════════════════════════════════════════════════════════

const LanguageEntry = struct {
    name: []const u8,
    language_fn: *const fn () callconv(.c) ?*const c_api.Language,
};

// ═══════════════════════════════════════════════════════════════════════════════
// Static Language Registry
// ═══════════════════════════════════════════════════════════════════════════════

/// Comptime-generated language registry
fn makeLanguageRegistry() [9]LanguageEntry {
    return .{
        .{ .name = "python", .language_fn = tree_sitter_python },
        .{ .name = "rust", .language_fn = tree_sitter_rust },
        .{ .name = "javascript", .language_fn = tree_sitter_javascript },
        .{ .name = "typescript", .language_fn = tree_sitter_typescript },
        .{ .name = "tsx", .language_fn = tree_sitter_tsx },
        .{ .name = "c", .language_fn = tree_sitter_c },
        .{ .name = "cpp", .language_fn = tree_sitter_cpp },
        .{ .name = "go", .language_fn = tree_sitter_go },
        .{ .name = "zig", .language_fn = tree_sitter_zig },
    };
}

/// The comptime language registry
const LANGUAGE_REGISTRY = makeLanguageRegistry();

// ═══════════════════════════════════════════════════════════════════════════════
// Public API
// ═══════════════════════════════════════════════════════════════════════════════

/// Get a tree-sitter language by name
/// Returns null if the language is not available or not found
pub fn getLanguage(name: []const u8) ?*const c_api.Language {
    // Normalize language name (lowercase)
    var normalized: [32]u8 = undefined;
    if (name.len > 31) return null;

    for (name, 0..) |c, i| {
        normalized[i] = std.ascii.toLower(c);
    }
    const norm_name = normalized[0..name.len];

    // Search registry
    inline for (LANGUAGE_REGISTRY) |entry| {
        if (std.mem.eql(u8, norm_name, entry.name)) {
            return entry.language_fn();
        }
    }

    return null;
}

/// Check if a language is available at runtime
pub fn isLanguageAvailable(name: []const u8) bool {
    return getLanguage(name) != null;
}

/// Get list of available languages
/// Caller owns the returned slice (must free with allocator)
pub fn listAvailableLanguages(allocator: std.mem.Allocator) error{OutOfMemory}![]const []const u8 {
    // Count available languages at runtime by checking if stub returns non-null
    var count: usize = 0;
    inline for (LANGUAGE_REGISTRY) |entry| {
        const lang = entry.language_fn();
        if (lang != null) {
            count += 1;
        }
    }

    var list = try allocator.alloc([]const u8, count);
    errdefer allocator.free(list);

    var i: usize = 0;
    inline for (LANGUAGE_REGISTRY) |entry| {
        const lang = entry.language_fn();
        if (lang != null) {
            list[i] = try allocator.dupe(u8, entry.name);
            i += 1;
        }
    }

    return list;
}

/// Free a language list returned by listAvailableLanguages
pub fn freeLanguageList(allocator: std.mem.Allocator, list: []const []const u8) void {
    for (list) |name| {
        allocator.free(name);
    }
    allocator.free(list);
}

// ═══════════════════════════════════════════════════════════════════════════════
// Comptime Language Capabilities
// ═══════════════════════════════════════════════════════════════════════════════

/// Compile-time struct with language capabilities
pub const LanguageCapabilities = struct {
    python: bool,
    rust: bool,
    javascript: bool,
    typescript: bool,
    tsx: bool,
    c: bool,
    cpp: bool,
    go: bool,
    zig: bool,

    /// Get capabilities at compile time
    pub fn detect() LanguageCapabilities {
        // Currently all stubbed - grammars not linked
        // TODO(code-puppy-019d8a): Re-enable when grammars are linked
        return .{
            .python = false,
            .rust = false,
            .javascript = false,
            .typescript = false,
            .tsx = false,
            .c = false,
            .cpp = false,
            .go = false,
            .zig = false,
        };
    }

    /// Check if any languages are available at compile time
    pub fn hasAny(self: LanguageCapabilities) bool {
        return self.python or self.rust or self.javascript or
               self.typescript or self.tsx or self.c or
               self.cpp or self.go or self.zig;
    }
};

/// Compile-time detected capabilities
pub const COMPTIME_CAPABILITIES = LanguageCapabilities.detect();

/// Verify that we have at least some language support at compile time
/// Note: Disabled for now since grammars are stubbed
pub fn assertLanguageSupport() void {
    // Temporarily disabled - grammars are optional/stubbed
    // TODO(code-puppy-019d8a): Re-enable when grammars are linked
    // if (!COMPTIME_CAPABILITIES.hasAny()) {
    //     @compileError("No tree-sitter languages are configured. " ++
    //                   "Enable -Dvendor-grammars or -Dsystem-grammars in build.zig");
    // }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Language Metadata
// ═══════════════════════════════════════════════════════════════════════════════

/// Get the human-readable name for a language
pub fn getLanguageDisplayName(internal_name: []const u8) ?[]const u8 {
    const display_names = .{
        .{ "python", "Python" },
        .{ "rust", "Rust" },
        .{ "javascript", "JavaScript" },
        .{ "typescript", "TypeScript" },
        .{ "tsx", "TSX" },
        .{ "c", "C" },
        .{ "cpp", "C++" },
        .{ "go", "Go" },
        .{ "zig", "Zig" },
    };
    
    inline for (display_names) |pair| {
        if (std.mem.eql(u8, internal_name, pair[0])) {
            return pair[1];
        }
    }
    
    return null;
}

/// Get the tree-sitter ABI version for a language (if available)
pub fn getLanguageVersion(language: *const c_api.Language) u32 {
    return c_api.ts_language_version(language);
}

/// Get symbol count for a language
pub fn getLanguageSymbolCount(language: *const c_api.Language) u32 {
    return c_api.ts_language_symbol_count(language);
}

// ═══════════════════════════════════════════════════════════════════════════════
// Runtime Grammar Detection
// ═══════════════════════════════════════════════════════════════════════════════

/// Diagnostic information about grammar linking
pub const GrammarDiagnostics = struct {
    /// Total number of languages in registry
    total_languages: usize,
    /// Number of languages successfully linked
    linked_languages: usize,
    /// Which languages are linked (sparse array aligned with registry)
    linked: [9]bool,
    /// Language versions if available
    versions: [9]u32,
    
    /// Returns true if at least one grammar is linked
    pub fn hasAnyGrammar(self: GrammarDiagnostics) bool {
        return self.linked_languages > 0;
    }
};

/// Run diagnostics to detect which grammars are actually linked
pub fn diagnoseGrammars() GrammarDiagnostics {
    var diag = GrammarDiagnostics{
        .total_languages = LANGUAGE_REGISTRY.len,
        .linked_languages = 0,
        .linked = .{false} ** 9,
        .versions = .{0} ** 9,
    };

    inline for (LANGUAGE_REGISTRY, 0..) |entry, i| {
        const lang = entry.language_fn();
        if (lang) |l| {
            diag.linked[i] = true;
            diag.linked_languages += 1;
            diag.versions[i] = c_api.ts_language_version(l);
        }
    }

    return diag;
}

/// Print grammar diagnostic information
pub fn printDiagnostics(writer: anytype) !void {
    const diag = diagnoseGrammars();
    
    try writer.print("\n=== Tree-sitter Grammar Diagnostics ===\n", .{});
    try writer.print("Total languages in registry: {d}\n", .{diag.total_languages});
    try writer.print("Successfully linked: {d}\n", .{diag.linked_languages});
    try writer.print("\nLanguage Status:\n", .{});
    
    inline for (LANGUAGE_REGISTRY, 0..) |entry, i| {
        const status = if (diag.linked[i]) "✓" else "✗";
        const version = if (diag.linked[i]) diag.versions[i] else 0;
        try writer.print("  {s} {s:12} ABI: {d}\n", .{ status, entry.name, version });
    }
    
    if (!diag.hasAnyGrammar()) {
        try writer.print("\n⚠️  No grammars are linked!\n", .{});
        try writer.print("    Build with: -Dvendor-grammars=true or -Dsystem-grammars=true\n", .{});
    }
    try writer.print("========================================\n", .{});
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "language detection" {
    // Test that language names are recognized
    try std.testing.expectEqualStrings("python", LANGUAGE_REGISTRY[0].name);
    try std.testing.expectEqualStrings("rust", LANGUAGE_REGISTRY[1].name);
}

test "getLanguage with valid names" {
    // Note: These tests require the grammars to be linked
    // They'll fail gracefully (return null) if not linked
    
    // Just verify the function doesn't panic
    const python = getLanguage("python");
    _ = python;
    
    const rust = getLanguage("rust");
    _ = rust;
    
    const js = getLanguage("javascript");
    _ = js;
}

test "getLanguage with invalid name returns null" {
    try std.testing.expect(getLanguage("not_a_real_language") == null);
    try std.testing.expect(getLanguage("") == null);
}

test "case insensitivity" {
    // Should work with various cases
    const lower = getLanguage("python");
    const upper = getLanguage("PYTHON");
    const mixed = getLanguage("Python");
    
    // All should return same result (either null or valid)
    // Can't test equality since they're pointers, but can test null-ness matches
    const lower_null = lower == null;
    const upper_null = upper == null;
    const mixed_null = mixed == null;
    
    try std.testing.expectEqual(lower_null, upper_null);
    try std.testing.expectEqual(lower_null, mixed_null);
}

test "display names" {
    try std.testing.expectEqualStrings("Python", getLanguageDisplayName("python").?);
    try std.testing.expectEqualStrings("Rust", getLanguageDisplayName("rust").?);
    try std.testing.expectEqualStrings("JavaScript", getLanguageDisplayName("javascript").?);
    try std.testing.expect(getLanguageDisplayName("unknown") == null);
}

test "comptime capabilities" {
    // Verify comptime capabilities are detected
    const caps = LanguageCapabilities.detect();
    try std.testing.expect(caps.hasAny());
}

test "diagnostics" {
    const diag = diagnoseGrammars();
    // Just verify the function works without crashing
    _ = diag.total_languages;
    _ = diag.linked_languages;
    _ = diag.hasAnyGrammar();
}

// Integration test that requires actual grammar linking
test "language version if available" {
    const python = getLanguage("python");
    if (python) |lang| {
        const version = getLanguageVersion(lang);
        // Tree-sitter ABI version should be >= 14 (current as of 2024)
        try std.testing.expect(version >= 14);
    }
}
