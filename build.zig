// ═══════════════════════════════════════════════════════════════════════════════
// Code-Puppy Zig Build System (Simplified for Zig 0.15.2)
// ═══════════════════════════════════════════════════════════════════════════════
//
// Builds 3 shared libraries for the native target:
//   - zig_puppy_core (message serialization, pruning, hashing)
//   - zig_turbo_ops  (batch file operations)
//   - zig_turbo_parse (tree-sitter parsing)
//
// Requirements:
//   - Zig 0.15.2+
//
// Usage:
//   zig build                    # Build all shared libraries
//   zig build -Doptimize=ReleaseFast  # Optimized build
//   zig build test               # Run all tests
//   zig build clean              # Clean build artifacts

const std = @import("std");

// ═══════════════════════════════════════════════════════════════════════════════
// Grammar Configuration
// ═══════════════════════════════════════════════════════════════════════════════

const GrammarConfig = struct {
    name: []const u8,
    lib_name: []const u8,
    vendor_path: ?[]const u8,
    system_libs: []const []const u8,
};

const GRAMMARS = [_]GrammarConfig{
    .{
        .name = "python",
        .lib_name = "tree-sitter-python",
        .vendor_path = "vendor/tree-sitter-python",
        .system_libs = &.{"tree-sitter-python", "tree_sitter_python"},
    },
    .{
        .name = "rust",
        .lib_name = "tree-sitter-rust",
        .vendor_path = "vendor/tree-sitter-rust",
        .system_libs = &.{"tree-sitter-rust", "tree_sitter_rust"},
    },
    .{
        .name = "javascript",
        .lib_name = "tree-sitter-javascript",
        .vendor_path = "vendor/tree-sitter-javascript",
        .system_libs = &.{"tree-sitter-javascript", "tree_sitter_javascript"},
    },
    .{
        .name = "typescript",
        .lib_name = "tree-sitter-typescript",
        .vendor_path = "vendor/tree-sitter-typescript",
        .system_libs = &.{"tree-sitter-typescript", "tree_sitter_typescript"},
    },
    .{
        .name = "tsx",
        .lib_name = "tree-sitter-tsx",
        .vendor_path = null,
        .system_libs = &.{"tree-sitter-tsx", "tree_sitter_tsx"},
    },
    .{
        .name = "c",
        .lib_name = "tree-sitter-c",
        .vendor_path = "vendor/tree-sitter-c",
        .system_libs = &.{"tree-sitter-c", "tree_sitter_c"},
    },
    .{
        .name = "cpp",
        .lib_name = "tree-sitter-cpp",
        .vendor_path = "vendor/tree-sitter-cpp",
        .system_libs = &.{"tree-sitter-cpp", "tree_sitter_cpp"},
    },
    .{
        .name = "go",
        .lib_name = "tree-sitter-go",
        .vendor_path = "vendor/tree-sitter-go",
        .system_libs = &.{"tree-sitter-go", "tree_sitter_go"},
    },
    .{
        .name = "zig",
        .lib_name = "tree-sitter-zig",
        .vendor_path = "vendor/tree-sitter-zig",
        .system_libs = &.{"tree-sitter-zig", "tree_sitter_zig"},
    },
};

// ═══════════════════════════════════════════════════════════════════════════════
// Module Configuration
// ═══════════════════════════════════════════════════════════════════════════════

const ModuleConfig = struct {
    name: []const u8,
    root_source: []const u8,
    c_source_files: []const []const u8 = &.{},
    include_paths: []const []const u8 = &.{},
    link_libs: []const []const u8 = &.{},
    exports_c_abi: bool = true,
};

const MODULES = [_]ModuleConfig{
    .{
        .name = "zig_puppy_core",
        .root_source = "zig_src/puppy_core/lib.zig",
        .exports_c_abi = true,
        .link_libs = &.{"c"},
    },
    .{
        .name = "zig_turbo_ops",
        .root_source = "zig_src/turbo_ops/lib.zig",
        .exports_c_abi = true,
        .link_libs = &.{"c"},
    },
    .{
        .name = "zig_turbo_parse",
        .root_source = "zig_src/turbo_parse/lib.zig",
        .exports_c_abi = true,
        .include_paths = &.{"vendor/tree-sitter/include"},
        .link_libs = &.{"c", "tree-sitter"},
    },
};

// ═══════════════════════════════════════════════════════════════════════════════
// Build Entry Point
// ═══════════════════════════════════════════════════════════════════════════════

pub fn build(b: *std.Build) void {
    // Build options
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{
        .preferred_optimize_mode = .ReleaseFast,
    });
    const strip_symbols = b.option(bool, "strip", "Strip debug symbols for smaller binaries") orelse false;

    // Grammar linking options
    const vendor_grammars = b.option(bool, "vendor-grammars", "Build tree-sitter grammars from vendored sources") orelse false;
    const system_grammars = b.option(bool, "system-grammars", "Use system-installed tree-sitter grammars") orelse true;

    // Module selection (build all by default, or specify one)
    const single_module = b.option([]const u8, "module", "Build only this module (puppy_core, turbo_ops, turbo_parse)");

    // ═════════════════════════════════════════════════════════════════════════
    // Build Grammar Libraries (if vendoring)
    // ═════════════════════════════════════════════════════════════════════════

    var grammar_libs = std.array_list.Managed(*std.Build.Step.Compile).init(b.allocator);
    defer grammar_libs.deinit();

    if (vendor_grammars) {
        for (GRAMMARS) |grammar| {
            if (grammar.vendor_path) |path| {
                const grammar_lib = buildVendorGrammar(b, grammar, target, optimize, path);
                grammar_libs.append(grammar_lib) catch @panic("OOM");
            }
        }
    }

    // ═════════════════════════════════════════════════════════════════════════
    // Build Modules
    // ═════════════════════════════════════════════════════════════════════════

    var built_count: usize = 0;

    for (MODULES) |mod_config| {
        // Skip if building single module and this isn't it
        if (single_module) |name| {
            if (!std.mem.eql(u8, mod_config.name, name)) continue;
        }

        buildModule(b, mod_config, target, optimize, strip_symbols, vendor_grammars, system_grammars, grammar_libs.items);
        built_count += 1;
    }

    // ═════════════════════════════════════════════════════════════════════════
    // Build Steps
    // ═════════════════════════════════════════════════════════════════════════

    // Test step
    const test_step = b.step("test", "Run all module tests");

    for (MODULES) |mod_config| {
        if (single_module) |name| {
            if (!std.mem.eql(u8, mod_config.name, name)) continue;
        }

        const test_mod = b.createModule(.{
            .root_source_file = b.path(mod_config.root_source),
            .target = target,
            .optimize = optimize,
        });
        addModuleDependencies(b, test_mod, mod_config, vendor_grammars, system_grammars, grammar_libs.items);

        const test_artifact = b.addTest(.{
            .root_module = test_mod,
            .name = b.fmt("{s}_test", .{mod_config.name}),
        });

        test_step.dependOn(&b.addRunArtifact(test_artifact).step);
    }

    // Clean step
    const clean_step = b.step("clean", "Remove build artifacts");
    const clean_cmd = b.addSystemCommand(&.{ "rm", "-rf", "zig-out", ".zig-cache" });
    clean_step.dependOn(&clean_cmd.step);

    // Documentation step
    const docs_step = b.step("docs", "Generate module documentation");

    for (MODULES) |mod_config| {
        if (single_module) |name| {
            if (!std.mem.eql(u8, mod_config.name, name)) continue;
        }

        const lib = b.addLibrary(.{
            .name = b.fmt("{s}_docs", .{mod_config.name}),
            .root_module = b.createModule(.{
                .root_source_file = b.path(mod_config.root_source),
                .target = target,
                .optimize = optimize,
            }),
            .linkage = .static,
        });

        addModuleDependencies(b, lib.root_module, mod_config, vendor_grammars, system_grammars, grammar_libs.items);

        const install_docs = b.addInstallDirectory(.{
            .source_dir = lib.getEmittedDocs(),
            .install_dir = .prefix,
            .install_subdir = b.fmt("docs/{s}", .{mod_config.name}),
        });
        docs_step.dependOn(&install_docs.step);
    }

    // Report what we're building
    if (built_count == 0) {
        std.log.warn("No modules selected for building", .{});
    } else {
        std.log.info("Building {d} module(s) for target: {s}", .{
            built_count,
            @tagName(target.result.cpu.arch),
        });
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Module Building
// ═══════════════════════════════════════════════════════════════════════════════

/// Build a vendored tree-sitter grammar as a static library
fn buildVendorGrammar(
    b: *std.Build,
    grammar: GrammarConfig,
    target: std.Build.ResolvedTarget,
    optimize: std.builtin.OptimizeMode,
    vendor_path: []const u8,
) *std.Build.Step.Compile {
    const lib = b.addLibrary(.{
        .name = grammar.lib_name,
        .root_module = b.createModule(.{
            .target = target,
            .optimize = optimize,
        }),
        .linkage = .static,
    });

    // Add the parser.c source file from the vendor directory
    const parser_c = b.pathJoin(&.{ vendor_path, "src", "parser.c" });
    lib.addCSourceFile(.{
        .file = b.path(parser_c),
        .flags = &.{
            "-O2",
            "-std=c11",
            "-fPIC",
            "-I", b.pathJoin(&.{ vendor_path, "src" }),
        },
    });

    // Some grammars have scanner.c (external scanner)
    const scanner_c = b.pathJoin(&.{ vendor_path, "src", "scanner.c" });
    const scanner_exists = std.fs.cwd().access(scanner_c, .{});
    if (scanner_exists) {
        lib.addCSourceFile(.{
            .file = b.path(scanner_c),
            .flags = &.{
                "-O2",
                "-std=c11",
                "-fPIC",
                "-I", b.pathJoin(&.{ vendor_path, "src" }),
            },
        });
    } else |_| {
        // Scanner doesn't exist, that's fine
    }

    // Zig 0.15: Use linkLibC() method instead of link_libc field
    lib.linkLibC();
    lib.addIncludePath(b.path(b.pathJoin(&.{ vendor_path, "src" })));

    return lib;
}

fn buildModule(
    b: *std.Build,
    config: ModuleConfig,
    target: std.Build.ResolvedTarget,
    optimize: std.builtin.OptimizeMode,
    strip: bool,
    vendor_grammars: bool,
    system_grammars: bool,
    grammar_libs: []const *std.Build.Step.Compile,
) void {
    // Create the shared library for Python cffi
    const lib = b.addLibrary(.{
        .name = config.name,
        .root_module = b.createModule(.{
            .root_source_file = b.path(config.root_source),
            .target = target,
            .optimize = optimize,
        }),
        .linkage = .dynamic,
    });

    // Zig 0.15: strip is set via options or module, not directly on lib
    // Using the preferred pattern for Zig 0.15
    if (strip) {
        lib.root_module.strip = true;
    }

    lib.root_module.pic = true;
    lib.bundle_compiler_rt = true;

    // Add dependencies
    addModuleDependencies(b, lib.root_module, config, vendor_grammars, system_grammars, grammar_libs);

    // C ABI exports for Python cffi
    if (config.exports_c_abi) {
        lib.root_module.addCMacro("ZIG_C_ABI_EXPORT", "1");
    }

    // Version information
    lib.root_module.addCMacro("ZIG_PUPPY_VERSION", "\"0.1.0\"");
    lib.root_module.addCMacro("ZIG_PUPPY_BUILD_DATE", "\"2025-01-14\"");

    // Install to lib/ directory
    const install_lib = b.addInstallArtifact(lib, .{
        .dest_dir = .{ .override = .lib },
    });

    // Create a module step for this specific library
    const module_step = b.step(b.fmt("{s}", .{config.name}), b.fmt("Build {s} shared library", .{config.name}));
    module_step.dependOn(&install_lib.step);

    // Also add to default step
    b.getInstallStep().dependOn(&install_lib.step);
}

fn addModuleDependencies(
    b: *std.Build,
    module: *std.Build.Module,
    config: ModuleConfig,
    vendor_grammars: bool,
    system_grammars: bool,
    grammar_libs: []const *std.Build.Step.Compile,
) void {
    _ = vendor_grammars;
    _ = system_grammars;
    _ = grammar_libs;

    // Link against C library - Zig 0.15 uses linkSystemLibrary with "c"
    for (config.link_libs) |lib_name| {
        if (std.mem.eql(u8, lib_name, "c")) {
            // Zig 0.15: Use linkSystemLibrary("c", .{}) instead of link_libc field
            module.linkSystemLibrary("c", .{});
        } else {
            // System library
            module.linkSystemLibrary(lib_name, .{});
        }
    }

    // Add include paths
    for (config.include_paths) |include_path| {
        module.addIncludePath(b.path(include_path));
    }

    // Add C source files if any
    for (config.c_source_files) |c_file| {
        module.addCSourceFile(.{ .file = b.path(c_file), .flags = &.{"-O2"} });
    }

    // Note: Grammar linking disabled - grammars are stubbed to return null.
    // This allows turbo_parse to build without requiring grammar libraries.
    // TODO(code-puppy-019d8a): Re-enable grammar linking when available.
    if (std.mem.eql(u8, config.name, "zig_turbo_parse")) {
        // Define stub mode macro for C code (if any)
        module.addCMacro("TREE_SITTER_GRAMMARS_STUBBED", "1");
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Utility Functions (available via build.zig import)
// ═══════════════════════════════════════════════════════════════════════════════

/// Get the shared library extension for a target
pub fn getSharedLibExtension(target: std.Target) []const u8 {
    return target.os.tag.sharedLibSuffix();
}

/// Get the platform name for a target (used in artifact naming)
pub fn getTargetName(target: std.Target) []const u8 {
    return switch (target.os.tag) {
        .linux => switch (target.cpu.arch) {
            .x86_64 => "linux-x86_64",
            .aarch64 => "linux-aarch64",
            else => "linux-unknown",
        },
        .macos => switch (target.cpu.arch) {
            .x86_64 => "macos-x86_64",
            .aarch64 => "macos-arm64",
            else => "macos-unknown",
        },
        .windows => switch (target.cpu.arch) {
            .x86_64 => "windows-x86_64",
            else => "windows-unknown",
        },
        else => "unknown",
    };
}
