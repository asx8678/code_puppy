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
    const exe = b.addExecutable(.{
        .name = "process_runner",
        .root_source_file = b.path("main.zig"),
        .target = target,
        .optimize = optimize,
    });

    // Link against C library for POSIX APIs
    exe.linkLibC();

    // Add module imports
    exe.root_module.addImport("protocol", b.createModule(.{
        .root_source_file = b.path("protocol.zig"),
    }));
    exe.root_module.addImport("process", b.createModule(.{
        .root_source_file = b.path("process.zig"),
    }));

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

    // Test step - runs all module tests
    const test_protocol = b.addTest(.{
        .root_source_file = b.path("protocol.zig"),
        .target = target,
        .optimize = optimize,
    });

    const test_process = b.addTest(.{
        .root_source_file = b.path("process.zig"),
        .target = target,
        .optimize = optimize,
    });
    test_process.root_module.addImport("protocol", b.createModule(.{
        .root_source_file = b.path("protocol.zig"),
    }));

    const test_main = b.addTest(.{
        .root_source_file = b.path("main.zig"),
        .target = target,
        .optimize = optimize,
    });
    test_main.root_module.addImport("protocol", b.createModule(.{
        .root_source_file = b.path("protocol.zig"),
    }));
    test_main.root_module.addImport("process", b.createModule(.{
        .root_source_file = b.path("process.zig"),
    }));

    const run_protocol_tests = b.addRunArtifact(test_protocol);
    const run_process_tests = b.addRunArtifact(test_process);
    const run_main_tests = b.addRunArtifact(test_main);

    const test_step = b.step("test", "Run all process_runner tests");
    test_step.dependOn(&run_protocol_tests.step);
    test_step.dependOn(&run_process_tests.step);
    test_step.dependOn(&run_main_tests.step);

    // Clean step
    const clean_step = b.step("clean", "Remove build artifacts");
    const clean_cmd = b.addSystemCommand(&.{ "rm", "-rf", "zig-out", ".zig-cache" });
    clean_step.dependOn(&clean_cmd.step);
}
