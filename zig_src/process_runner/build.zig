// ═══════════════════════════════════════════════════════════════════════════════
// Process Runner Build Configuration
// ═══════════════════════════════════════════════════════════════════════════════
//
// Builds the standalone process_runner executable for use as an Erlang Port.

const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{
        .preferred_optimize_mode = .ReleaseSafe,
    });

    // Build the executable
    const exe_mod = b.createModule(.{
        .root_source_file = b.path("main.zig"),
        .target = target,
        .optimize = optimize,
    });
    
    const exe = b.addExecutable(.{
        .name = "process_runner",
        .root_module = exe_mod,
    });

    // Link against C library for POSIX APIs
    exe.linkLibC();

    // Create modules
    const protocol_mod = b.createModule(.{
        .root_source_file = b.path("protocol.zig"),
    });
    const process_mod = b.createModule(.{
        .root_source_file = b.path("process.zig"),
    });
    const mcp_mod = b.createModule(.{
        .root_source_file = b.path("mcp.zig"),
    });
    
    // Add module imports
    exe_mod.addImport("protocol", protocol_mod);
    exe_mod.addImport("process", process_mod);
    exe_mod.addImport("mcp", mcp_mod);
    
    // Set up inter-module dependencies
    process_mod.addImport("protocol", protocol_mod);
    mcp_mod.addImport("protocol", protocol_mod);

    // Install the executable
    b.installArtifact(exe);

    // Run step
    const run_cmd = b.addRunArtifact(exe);
    run_cmd.step.dependOn(b.getInstallStep());
    if (b.args) |args| {
        run_cmd.addArgs(args);
    }

    const run_step = b.step("run", "Run the process runner");
    run_step.dependOn(&run_cmd.step);

    // Test modules
    const test_protocol_mod = b.createModule(.{
        .root_source_file = b.path("protocol.zig"),
        .target = target,
        .optimize = optimize,
    });

    const test_process_mod = b.createModule(.{
        .root_source_file = b.path("process.zig"),
        .target = target,
        .optimize = optimize,
    });
    test_process_mod.addImport("protocol", protocol_mod);

    const test_main_mod = b.createModule(.{
        .root_source_file = b.path("main.zig"),
        .target = target,
        .optimize = optimize,
    });
    test_main_mod.addImport("protocol", protocol_mod);
    test_main_mod.addImport("process", process_mod);
    test_main_mod.addImport("mcp", mcp_mod);

    // MCP test modules
    const test_mcp_mod = b.createModule(.{
        .root_source_file = b.path("mcp.zig"),
        .target = target,
        .optimize = optimize,
    });
    test_mcp_mod.addImport("protocol", protocol_mod);

    const test_mcp_full_mod = b.createModule(.{
        .root_source_file = b.path("test_mcp.zig"),
        .target = target,
        .optimize = optimize,
    });
    test_mcp_full_mod.addImport("mcp", mcp_mod);
    test_mcp_full_mod.addImport("protocol", protocol_mod);

    // Test step - runs all module tests
    const test_protocol = b.addTest(.{
        .root_module = test_protocol_mod,
    });
    const test_process = b.addTest(.{
        .root_module = test_process_mod,
    });
    const test_main = b.addTest(.{
        .root_module = test_main_mod,
    });
    const test_mcp = b.addTest(.{
        .root_module = test_mcp_mod,
    });
    const test_mcp_full = b.addTest(.{
        .root_module = test_mcp_full_mod,
    });

    const run_protocol_tests = b.addRunArtifact(test_protocol);
    const run_process_tests = b.addRunArtifact(test_process);
    const run_main_tests = b.addRunArtifact(test_main);
    const run_mcp_tests = b.addRunArtifact(test_mcp);
    const run_mcp_full_tests = b.addRunArtifact(test_mcp_full);

    const test_step = b.step("test", "Run all process_runner tests");
    test_step.dependOn(&run_protocol_tests.step);
    test_step.dependOn(&run_process_tests.step);
    test_step.dependOn(&run_main_tests.step);
    test_step.dependOn(&run_mcp_tests.step);
    test_step.dependOn(&run_mcp_full_tests.step);

    // Clean step
    const clean_step = b.step("clean", "Remove build artifacts");
    const clean_cmd = b.addSystemCommand(&.{ "rm", "-rf", "zig-out", ".zig-cache" });
    clean_step.dependOn(&clean_cmd.step);
}
