// ═══════════════════════════════════════════════════════════════════════════════
// Dynamic Grammar Loading
// ═══════════════════════════════════════════════════════════════════════════════
//
// Migration from: turbo_parse/src/dynamic.rs
//
// Enables loading tree-sitter grammar libraries at runtime via dlopen/dlsym.
// Supports .so (Linux), .dylib (macOS), and .dll (Windows).
//
// Security considerations:
//   - Libraries are loaded from a configurable path
//   - Version checking ensures compatibility
//   - Libraries must export the expected symbol names
//
// Zig vs Rust differences:
//   - dlopen via libc vs Rust's libloading crate
//   - Zig's std.DynLib provides abstraction

const std = @import("std");
const c_api = @import("c_api.zig");

// ═══════════════════════════════════════════════════════════════════════════════
// Platform Abstraction
// ═══════════════════════════════════════════════════════════════════════════════

pub const LibExtension = switch (builtin.target.os.tag) {
    .linux => ".so",
    .macos => ".dylib",
    .windows => ".dll",
    else => ".so",
};

const DynLib = switch (builtin.target.os.tag) {
    .windows => std.DynLib,
    else => struct {
        handle: ?*anyopaque,
        
        const Self = @This();
        
        pub fn open(path: []const u8) !Self {
            const c_path = try std.cstr.addNullByte(std.heap.c_allocator, path);
            defer std.heap.c_allocator.free(c_path);
            
            const handle = std.c.dlopen(c_path.ptr, std.c.RTLD.LAZY | std.c.RTLD.LOCAL);
            if (handle == null) return error.LibraryLoadFailed;
            
            return .{ .handle = handle };
        }
        
        pub fn close(self: *Self) void {
            if (self.handle) |h| {
                _ = std.c.dlclose(h);
                self.handle = null;
            }
        }
        
        pub fn lookup(self: *const Self, name: []const u8) ?*anyopaque {
            const c_name = std.cstr.addNullByte(std.heap.c_allocator, name) catch return null;
            defer std.heap.c_allocator.free(c_name);
            
            return std.c.dlsym(self.handle.?, c_name.ptr);
        }
    },
};

const builtin = @import("builtin");

// ═══════════════════════════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════════════════════════

pub const DynamicGrammar = struct {
    name: []const u8,
    library_path: []const u8,
    handle: DynLib,
    language_fn: c_api.TSLanguageFn,
    language: *const c_api.Language,
    
    pub fn deinit(self: *DynamicGrammar) void {
        self.handle.close();
    }
};

pub const GrammarRegistry = struct {
    allocator: std.mem.Allocator,
    grammars: std.StringHashMap(DynamicGrammar),
    
    const Self = @This();
    
    pub fn init(allocator: std.mem.Allocator) Self {
        return .{
            .allocator = allocator,
            .grammars = std.StringHashMap(DynamicGrammar).init(allocator),
        };
    }
    
    pub fn deinit(self: *Self) void {
        var iter = self.grammars.valueIterator();
        while (iter.next()) |grammar| {
            grammar.deinit();
            self.allocator.free(grammar.name);
            self.allocator.free(grammar.library_path);
        }
        self.grammars.deinit();
    }
    
    /// Load a grammar from a shared library
    pub fn loadGrammar(
        self: *Self,
        library_path: []const u8,
        name: []const u8,
    ) error{ 
        LibraryNotFound, 
        SymbolNotFound, 
        VersionMismatch,
        AlreadyLoaded,
        OutOfMemory,
    }!void {
        // Check if already loaded
        if (self.grammars.contains(name)) {
            return error.AlreadyLoaded;
        }
        
        // Open library
        const path_with_ext = if (std.mem.endsWith(u8, library_path, LibExtension))
            library_path
        else
            try std.fmt.allocPrint(self.allocator, "{s}{s}", .{ library_path, LibExtension });
        defer if (path_with_ext.ptr != library_path.ptr) self.allocator.free(path_with_ext);
        
        var handle = try DynLib.open(path_with_ext);
        errdefer handle.close();
        
        // Lookup tree_sitter_<name> symbol
        const symbol_name = try std.fmt.allocPrintZ(
            self.allocator,
            "tree_sitter_{s}",
            .{name},
        );
        defer self.allocator.free(symbol_name);
        
        const sym = handle.lookup(symbol_name) orelse return error.SymbolNotFound;
        const lang_fn: c_api.TSLanguageFn = @ptrCast(sym);
        
        // Get language pointer
        const lang = lang_fn();
        
        // Verify version compatibility
        const version = c_api.ts_language_version(lang);
        if (version < c_api.TREE_SITTER_MIN_COMPATIBLE_VERSION) {
            return error.VersionMismatch;
        }
        
        // Store grammar
        const owned_name = try self.allocator.dupe(u8, name);
        errdefer self.allocator.free(owned_name);
        
        const owned_path = try self.allocator.dupe(u8, path_with_ext);
        errdefer self.allocator.free(owned_path);
        
        try self.grammars.put(owned_name, .{
            .name = owned_name,
            .library_path = owned_path,
            .handle = handle,
            .language_fn = lang_fn,
            .language = lang,
        });
    }
    
    /// Get loaded language by name
    pub fn getLanguage(self: *const Self, name: []const u8) ?*const c_api.Language {
        if (self.grammars.get(name)) |grammar| {
            return grammar.language;
        }
        return null;
    }
    
    /// Check if a grammar is loaded
    pub fn isLoaded(self: *const Self, name: []const u8) bool {
        return self.grammars.contains(name);
    }
    
    /// Unload a grammar
    pub fn unloadGrammar(self: *Self, name: []const u8) void {
        if (self.grammars.fetchRemove(name)) |kv| {
            var grammar = kv.value;
            grammar.deinit();
            self.allocator.free(grammar.name);
            self.allocator.free(grammar.library_path);
        }
    }
    
    /// List loaded grammars
    pub fn listGrammars(self: *Self) error{OutOfMemory}![]const []const u8 {
        var names = try self.allocator.alloc([]const u8, self.grammars.count());
        errdefer self.allocator.free(names);
        
        var i: usize = 0;
        var iter = self.grammars.keyIterator();
        while (iter.next()) |key| : (i += 1) {
            names[i] = key.*;
        }
        
        return names;
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// C ABI Exports
// ═══════════════════════════════════════════════════════════════════════════════

export fn turbo_parse_load_grammar(
    registry: *anyopaque,
    library_path: [*:0]const u8,
    language_name: [*:0]const u8,
) c_int {
    if (registry == null or library_path == null or language_name == null) return -1;
    
    const reg: *GrammarRegistry = @ptrCast(@alignCast(registry));
    
    reg.loadGrammar(
        std.mem.span(library_path),
        std.mem.span(language_name),
    ) catch |err| return switch (err) {
        error.LibraryNotFound => -2,
        error.SymbolNotFound => -3,
        error.VersionMismatch => -4,
        error.AlreadyLoaded => -5,
        else => -1,
    };
    
    return 0;  // Success
}

export fn turbo_parse_unload_grammar(
    registry: *anyopaque,
    language_name: [*:0]const u8,
) void {
    if (registry == null or language_name == null) return;
    
    const reg: *GrammarRegistry = @ptrCast(@alignCast(registry));
    reg.unloadGrammar(std.mem.span(language_name));
}

export fn turbo_parse_is_grammar_loaded(
    registry: *anyopaque,
    language_name: [*:0]const u8,
) bool {
    if (registry == null or language_name == null) return false;
    
    const reg: *GrammarRegistry = @ptrCast(@alignCast(registry));
    return reg.isLoaded(std.mem.span(language_name));
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "grammar registry init/deinit" {
    const allocator = std.testing.allocator;
    
    var registry = GrammarRegistry.init(allocator);
    defer registry.deinit();
    
    try std.testing.expect(!registry.isLoaded("test"));
}

// Note: Can't test actual loading without a real .so file
// Integration tests would cover this
