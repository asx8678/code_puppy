"""Fast Puppy — toggle native backend acceleration on/off at runtime.

Auto-builds native modules (code_puppy_core, turbo_parse, Elixir FileOps)
on first startup if toolchain is available.
File operations now route through NativeBackend (Elixir or Python fallback).
Persists capability preferences to puppy.cfg so they survive restarts.

bd-63: Rewritten for capability-based profiles.
bd-86: Removed turbo_ops references — file_ops now uses Elixir/Python.
bd-92: Profile-focused UX — default view is concise, profile is primary action.

Usage:
    /fast_puppy                      → show profile + capabilities (concise default)
    /fast_puppy profile [name]       → switch/show runtime profile (THE primary action)
    /fast_puppy enable [cap]         → enable capability
    /fast_puppy disable [cap]        → disable capability
    /fast_puppy status               → detailed diagnostics
    /fast_puppy build [name|--all]   → build Rust crates (advanced)

Profiles: elixir_first, rust_first, python_only
Capabilities: message_core, file_ops, repo_index, parse
"""

import logging

from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_info

# Import discovery functions from builder.py (bd-91: split from rust_builder.py)
from code_puppy.plugins.fast_puppy.builder import (
    _find_repo_root,
    get_all_crate_status,
    get_available_backends,
    CRATES,
)

# Import build functions from rust_builder.py (bd-91: new module)
from code_puppy.plugins.fast_puppy.rust_builder import (
    _has_maturin,
    _has_rust_toolchain,
    build_single_crate,
    notify_build_complete,
)

# Re-export for backward compatibility (tests)
# bd-91: Split into builder.py (discovery) and rust_builder.py (build)
# bd-92: Cleaned up - removed legacy functions
__all__ = [
    "_handle_fast_puppy",
    "_on_startup",
    "_handle_enable",
    "_handle_disable",
    "_handle_status",
    "_handle_profile",
    "get_available_backends",
]

logger = logging.getLogger(__name__)

# bd-63: New capability-based handlers


def _handle_enable(args: list[str]) -> str:
    """Enable all capabilities or a specific capability.

    Args:
        args: List of command arguments (may contain capability name).

    Returns:
        Status message string.
    """
    from code_puppy.native_backend import NativeBackend

    if not args:
        # Enable all
        # bd-90: Updated messaging to reflect Elixir-first architecture
        NativeBackend.enable_all()
        NativeBackend.save_preferences()
        return "✅ All native backends enabled (Elixir preferred)"

    # Enable specific capability
    cap = args[0].lower()
    # bd-90: Updated capability descriptions to show backend type
    cap_map = {
        "message_core": NativeBackend.Capabilities.MESSAGE_CORE,  # bd-90: Message processing (Rust)
        "file_ops": NativeBackend.Capabilities.FILE_OPS,  # bd-90: File operations (Elixir)
        "repo_index": NativeBackend.Capabilities.REPO_INDEX,  # bd-90: Repository indexing (Elixir)
        "parse": NativeBackend.Capabilities.PARSE,  # bd-90: Tree-sitter parsing (Rust)
    }
    if cap in cap_map:
        NativeBackend.enable_capability(cap_map[cap])
        NativeBackend.save_preferences()
        # bd-90: Updated messaging to reflect Elixir-first
        return f"✅ {cap} enabled"
    return (
        f"❌ Unknown capability: {cap}. Use: message_core, file_ops, repo_index, parse"
    )


def _handle_disable(args: list[str]) -> str:
    """Disable all capabilities or a specific capability.

    Args:
        args: List of command arguments (may contain capability name).

    Returns:
        Status message string.
    """
    from code_puppy.native_backend import NativeBackend

    if not args:
        # Disable all
        # bd-90: Updated messaging to reflect native backend terminology
        NativeBackend.disable_all()
        NativeBackend.save_preferences()
        return "✅ All native backends disabled (Python fallback)"

    # Disable specific capability
    cap = args[0].lower()
    # bd-90: Updated capability descriptions to show backend type
    cap_map = {
        "message_core": NativeBackend.Capabilities.MESSAGE_CORE,  # bd-90: Message processing (Rust)
        "file_ops": NativeBackend.Capabilities.FILE_OPS,  # bd-90: File operations (Elixir)
        "repo_index": NativeBackend.Capabilities.REPO_INDEX,  # bd-90: Repository indexing (Elixir)
        "parse": NativeBackend.Capabilities.PARSE,  # bd-90: Tree-sitter parsing (Rust)
    }
    if cap in cap_map:
        NativeBackend.disable_capability(cap_map[cap])
        NativeBackend.save_preferences()
        return f"✅ {cap} disabled"
    return (
        f"❌ Unknown capability: {cap}. Use: message_core, file_ops, repo_index, parse"
    )


def _handle_profile(args: list[str]) -> str:
    """Handle runtime profile switching and display.

    bd-89: Runtime profile handler for persistence.

    Args:
        args: List of command arguments. If empty, shows current profile.
            If contains a profile name, sets it as the active profile.

    Returns:
        Status message string.
    """
    from code_puppy.native_backend import NativeBackend, BackendPreference

    valid_profiles = {
        "elixir_first": BackendPreference.ELIXIR_FIRST,
        "rust_first": BackendPreference.RUST_FIRST,
        "python_only": BackendPreference.PYTHON_ONLY,
    }

    if not args:
        # Show current profile
        current = NativeBackend.get_backend_preference()
        return f"Current profile: {current.value}\nValid profiles: elixir_first, rust_first, python_only"

    # Set profile
    profile_name = args[0].lower()
    if profile_name in valid_profiles:
        NativeBackend.set_backend_preference(profile_name)
        NativeBackend.save_preferences()
        return f"✅ Profile set to: {profile_name} (persisted to config)"

    return (
        f"❌ Unknown profile: {profile_name}. "
        f"Use: elixir_first, rust_first (legacy), python_only"
    )


def _handle_default_view() -> str:
    """Concise default view showing profile and capability matrix.

    bd-92: Phase 3 - profile-focused UX.
    """
    from code_puppy.native_backend import NativeBackend

    lines = []

    # Current profile (prominent)
    profile = NativeBackend.get_backend_preference()
    lines.append(f"⚡ Profile: {profile.value}")
    lines.append("")

    # Capability matrix (compact)
    cap_status = NativeBackend.get_status()
    lines.append("Capabilities:")
    for cap, info in cap_status.items():
        icon = "✅" if info.active else ("💤" if info.status == "disabled" else "❌")
        lines.append(f"  {icon} {cap}")

    # Quick actions hint
    lines.append("")
    lines.append("Commands: /fast_puppy profile | enable | disable | status | build")

    return "\n".join(lines)


def _handle_status() -> str:
    """Get detailed status for all capabilities including infrastructure.

    bd-92: Full diagnostics with crate status, toolchain, and infrastructure.

    Returns:
        Formatted status string.
    """
    from code_puppy.native_backend import NativeBackend
    # bd-69: _core_bridge imports removed — NativeBackend.get_status() used instead
    # bd-90: Updated to show Elixir-first architecture details
    # bd-88: Improved to show actual backend in use and actionable next steps
    # bd-92: Full diagnostics merged from old default view

    # bd-88: Show backend preference and Elixir connection status
    preference = NativeBackend.get_backend_preference()
    elixir_connected = NativeBackend.is_elixir_connected()

    # bd-88: Get actual source tracking from NativeBackend
    last_sources = getattr(NativeBackend, "_last_source", {})

    # Get crate build status (bd-92: merged from old default view)
    crate_statuses = get_all_crate_status()
    repo_root = _find_repo_root()

    lines = ["⚡ Fast Puppy Status", ""]

    # bd-88: Show backend preference prominently
    lines.append(f"  Backend preference: {preference.value}")
    lines.append(
        f"  Elixir connection: {'✅ connected' if elixir_connected else '❌ not connected'}"
    )
    # bd-88: Always show Python fallback as available
    lines.append("  Python fallback: ✅ always available")
    lines.append("")

    # Get NativeBackend capability status
    cap_status = NativeBackend.get_status()

    # bd-88: Group capabilities by backend type with actual usage
    lines.append("  Capabilities by configured backend (→ shows actual in use):")
    lines.append("")

    # bd-88: Elixir-backed capabilities with actual source
    lines.append("  📁 Elixir backends:")
    elixir_caps = ["file_ops", "repo_index"]
    for cap in elixir_caps:
        if cap in cap_status:
            info = cap_status[cap]
            actual = last_sources.get(cap, info.configured if info.active else "python")
            if info.active:
                icon = "✅"
                status = "active"
            elif info.status == "disabled":
                icon = "💤"
                status = "disabled"
            else:
                icon = "❌"
                status = "unavailable"
            # bd-88: Show configured → actual backend
            source_arrow = f"→ {actual}" if actual != info.configured else ""
            lines.append(
                f"    {icon} {cap}: {info.configured} {source_arrow} ({status})"
            )

    # bd-88: Rust-backed capabilities with actual source
    lines.append("")
    lines.append("  🦀 Rust backends:")
    rust_caps = ["message_core", "parse"]
    for cap in rust_caps:
        if cap in cap_status:
            info = cap_status[cap]
            actual = last_sources.get(cap, info.configured if info.active else "python")
            if info.active:
                icon = "✅"
                status = "active"
            elif info.status == "disabled":
                icon = "💤"
                status = "disabled"
            else:
                icon = "❌"
                status = "unavailable"
            # bd-88: Show configured → actual backend
            source_arrow = f"→ {actual}" if actual != info.configured else ""
            lines.append(
                f"    {icon} {cap}: {info.configured} {source_arrow} ({status})"
            )

    # bd-92: Infrastructure section (merged from old default view)
    lines.append("")
    lines.append("  Infrastructure:")
    lines.append(
        f"    {'Rust toolchain:':16} {'✅ rustc found' if _has_rust_toolchain() else '❌ not found'}"
    )
    lines.append(f"    {'maturin:':16} {'✅ found' if _has_maturin() else '❌ not found'}")
    lines.append(
        f"    {'Crate source:':16} {'✅ workspace found at ' + str(repo_root) if repo_root else '❌ not found'}"
    )

    # bd-92: Crate build status (merged from old default view)
    lines.append("")
    lines.append("  Crate Build Status:")
    for status in crate_statuses:
        name = status["name"]
        if status["active"]:
            state = "✅ installed, fresh, active"
        elif status["installed"] and status["fresh"]:
            state = "✅ installed, fresh"
        elif status["installed"] and not status["fresh"]:
            state = (
                "⚠️  installed, STALE (src newer than binary) → run /fast_puppy build "
                + name
            )
        elif status["crate_dir_found"]:
            state = "❌ not installed (run /fast_puppy build " + name + ")"
        else:
            state = "❌ crate dir not found"

        # Pad names for alignment
        name_padded = f"{name}:"
        lines.append(f"    {name_padded:16} {state}")

    # bd-88: Add actionable suggestions
    lines.append("")
    lines.append("  💡 Next steps:")

    # Check if any capabilities are unavailable but enabled
    unavailable_enabled = []
    for cap, info in cap_status.items():
        if info.status == "unavailable" and NativeBackend.is_enabled(cap):
            unavailable_enabled.append(cap)

    if unavailable_enabled:
        lines.append(
            f"    • Enable: /fast_puppy enable {', '.join(unavailable_enabled)}"
        )

    # Check if Elixir is not connected but preference is elixir_first
    if preference.value == "elixir_first" and not elixir_connected:
        lines.append("    • Start Elixir backend for acceleration: mix run --no-halt")

    # Suggest checking profile if rust_first is set
    if preference.value == "rust_first":
        lines.append(
            "    • Consider switching to elixir_first: /fast_puppy profile elixir_first"
        )

    # Always show the build suggestion
    rust_unavailable = any(
        cap_status[cap].status == "unavailable"
        for cap in ["message_core", "parse"]
        if cap in cap_status
    )
    if rust_unavailable:
        lines.append("    • Build Rust crates: /fast_puppy build --all")

    # Legacy bridge status
    lines.append("")
    lines.append(
        f"  message_core bridge: {'✅' if NativeBackend.is_active(NativeBackend.Capabilities.MESSAGE_CORE) else '❌'} available, {'✅' if NativeBackend.is_message_core_active() else '💤'} enabled"
    )

    return "\n".join(lines)


def _emit_startup_banner(backend_status: dict, profile) -> None:
    """Emit a concise startup banner based on available backends.

    bd-92: New helper for clean startup messaging.
    """

    elixir = backend_status.get("elixir_available", False)
    rust = backend_status.get("rust_installed", False)

    profile_name = profile.value if hasattr(profile, 'value') else str(profile)

    if elixir and rust:
        emit_info(f"🐕⚡ Fast Puppy: {profile_name} profile | Elixir ✅ Rust ✅")
    elif elixir:
        emit_info(f"🐕⚡ Fast Puppy: {profile_name} profile | Elixir ✅")
    elif rust:
        emit_info(f"🐕⚡ Fast Puppy: {profile_name} profile | Rust ✅")
    else:
        emit_info("🐕 Fast Puppy: Python fallback (no native backends)")


def _on_startup():
    """Detect available backends on startup and show status banner.

    bd-92: Phase 3 rewrite - pure discovery, no builds, no reloads.
    """
    try:
        from code_puppy.native_backend import NativeBackend

        # 1. Load user preferences from config
        NativeBackend.load_preferences()

        # 2. Detect available backends (discovery only, no builds)
        backend_status = get_available_backends()

        # 3. Get current profile for display
        profile = NativeBackend.get_backend_preference()

        # 4. Emit concise status banner
        _emit_startup_banner(backend_status, profile)

    except Exception as e:
        logger.warning("Fast Puppy startup error: %s", e)
        emit_info("🐕 Fast Puppy: startup error — run /fast_puppy status for details")


def _custom_help():
    # bd-92: Profile-focused help - profile is THE primary action
    return [
        ("fast_puppy", "Show current profile and capability status"),
        ("fast_puppy profile [name]", "Switch profile: elixir_first, rust_first, python_only"),
        ("fast_puppy enable [cap]", "Enable capability: message_core, file_ops, repo_index, parse"),
        ("fast_puppy disable [cap]", "Disable capability (fallback to Python)"),
        ("fast_puppy status", "Detailed diagnostics with infrastructure info"),
        ("fast_puppy build [--all|name]", "Build Rust crates (advanced)"),
    ]


def _handle_fast_puppy(command: str, name: str):
    if name != "fast_puppy":
        return None


    parts = command.strip().split()
    subcommand = parts[1] if len(parts) > 1 else ""
    args = parts[2:] if len(parts) > 2 else []

    known_subcommands = {"profile", "enable", "disable", "status", "build"}

    # Default: show concise view
    if subcommand in ("", None) or subcommand not in known_subcommands:
        result = _handle_default_view()
        emit_info(result)
        return True

    if subcommand == "build":
        # Parse crate name or --all
        crate_name = None
        if len(parts) > 2:
            crate_name = parts[2]

        if crate_name is None or crate_name == "--all":
            # Build all crates
            if not _has_rust_toolchain():
                emit_info(
                    "🐕 Fast Puppy: Rust toolchain not found\n"
                    "   Install: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
                )
                return True

            repo_root = _find_repo_root()
            if repo_root is None:
                emit_info("🐕 Fast Puppy: Workspace not found (no Cargo.toml)")
                return True

            emit_info("🐕⚡ Fast Puppy: Building all native Rust modules...")  # bd-88

            # bd-91: Build each crate individually (no auto-build, explicit only)
            results: dict[str, bool] = {}
            for crate_spec in CRATES:
                crate_name = crate_spec["name"]
                success = build_single_crate(crate_name)
                results[crate_name] = success

            active_count = sum(1 for v in results.values() if v)
            total_count = len(CRATES)

            if active_count == total_count:
                emit_info(
                    f"🐕⚡ Fast Puppy: All {total_count} modules built successfully!"
                )
            else:
                emit_info(f"🐕 Fast Puppy: {active_count}/{total_count} modules built:")
                for crate_spec in CRATES:
                    name = crate_spec["name"]
                    status = "✅" if results.get(name, False) else "❌"
                    emit_info(f"   {status} {name}")

            # bd-91: Notify that restart may be needed for changes to take effect
            if active_count > 0:
                emit_info("")
                emit_info(
                    "💡 Note: Restart code-puppy to activate newly built crates"
                )

            # bd-91: No runtime reload - require restart
            # The old importlib.reload() approach is deprecated for safety
            if results.get("code_puppy_core", False):
                emit_info(
                    "🐕⚡ Fast Puppy: code_puppy_core built. Restart to enable native backend."
                )
            return True
        else:
            # Build single crate
            valid_names = [spec["name"] for spec in CRATES]
            if crate_name not in valid_names:
                emit_info(f"🐕 Fast Puppy: Unknown crate '{crate_name}'")
                emit_info(f"   Valid crates: {', '.join(valid_names)}")
                return True

            if not _has_rust_toolchain():
                emit_info(
                    "🐕 Fast Puppy: Rust toolchain not found\n"
                    "   Install: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
                )
                return True

            emit_info(f"🐕⚡ Fast Puppy: Building {crate_name}...")
            success = build_single_crate(crate_name)

            if success:
                # bd-91: Use notify_build_complete instead of runtime reload
                emit_info(f"🐕⚡ Fast Puppy: ✅ {crate_name} built successfully!")
                emit_info(notify_build_complete(crate_name))
            else:
                emit_info(f"🐕 Fast Puppy: ❌ {crate_name} build failed")
            return True

    # bd-63: Use capability-based handlers for enable/disable/status
    if subcommand == "enable":
        result = _handle_enable(args)
        emit_info(result)
        return True

    if subcommand == "disable":
        result = _handle_disable(args)
        emit_info(result)
        return True

    if subcommand == "status":
        result = _handle_status()
        emit_info(result)
        return True

    # bd-89: Runtime profile subcommand
    if subcommand == "profile":
        result = _handle_profile(args)
        emit_info(result)
        return True

    # bd-92: Should not reach here due to known_subcommands check above
    result = _handle_default_view()
    emit_info(result)
    return True


register_callback("startup", _on_startup)
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_fast_puppy)
