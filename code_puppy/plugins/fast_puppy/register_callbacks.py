"""Fast Puppy — toggle native backend acceleration on/off at runtime.

Auto-builds native modules (code_puppy_core, turbo_parse, Elixir FileOps)
on first startup if toolchain is available.
File operations now route through NativeBackend (Elixir or Python fallback).
Persists capability preferences to puppy.cfg so they survive restarts.

bd-63: Rewritten for capability-based profiles.
bd-86: Removed turbo_ops references — file_ops now uses Elixir/Python.

Usage:
    /fast_puppy                     → show current status
    /fast_puppy enable [cap]      → enable all or specific capability
    /fast_puppy disable [cap]     → disable all or specific capability
    /fast_puppy status              → detailed diagnostics
    /fast_puppy build [name|--all] → rebuild Rust crate(s)

Capabilities: message_core, file_ops, repo_index, parse
"""

import importlib
import logging

from code_puppy.callbacks import register_callback
from code_puppy.config_package import get_puppy_config
from code_puppy.messaging import emit_info

# Import builder module (may be split into builder.py for line count)
# bd-91: Added get_available_backends import
from code_puppy.plugins.fast_puppy.builder import (
    _find_crate_dir,
    _find_repo_root,
    _has_maturin,
    _has_rust_toolchain,
    _try_auto_build,
    _try_auto_build_all,
    build_single_crate,
    get_all_crate_status,
    get_available_backends,
    CRATES,
)

# Re-export for backward compatibility (tests)
# bd-91: Added get_available_backends
__all__ = [
    "_find_crate_dir",
    "_find_repo_root",
    "_has_maturin",
    "_has_rust_toolchain",
    "_try_auto_build",
    "_try_auto_build_all",
    "_handle_fast_puppy",
    "_on_startup",
    "_read_persisted_preference",
    "_write_persisted_preference",
    "_handle_enable",
    "_handle_disable",
    "_handle_status",
    "get_available_backends",
]

logger = logging.getLogger(__name__)

CONFIG_KEY = "enable_fast_puppy"

# bd-63: Capability name mapping for user commands
CAPABILITY_MAP = {
    "message_core": "message_core",
    "file_ops": "file_ops",
    "repo_index": "repo_index",
    "parse": "parse",
}


def _read_persisted_preference() -> bool | None:
    """Read the saved preference from puppy.cfg."""
    try:
        from code_puppy.config import get_value

        val = get_value(CONFIG_KEY)
        if val is None:
            return None
        return str(val).strip().lower() in {"1", "true", "yes", "on"}
    except Exception:
        return None


def _write_persisted_preference(enabled: bool) -> None:
    """Save the legacy preference to puppy.cfg (for backward compat)."""
    try:
        from code_puppy.config import set_config_value

        set_config_value(CONFIG_KEY, str(enabled).lower())
    except Exception:
        logger.warning("Failed to persist fast_puppy preference to config")


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


def _handle_status() -> str:
    """Get detailed status for all capabilities.

    Returns:
        Formatted status string.
    """
    from code_puppy.native_backend import NativeBackend
    # bd-69: _core_bridge imports removed — NativeBackend.get_status() used instead
    # bd-90: Updated to show Elixir-first architecture details
    # bd-88: Improved to show actual backend in use and actionable next steps

    # bd-88: Show backend preference and Elixir connection status
    preference = NativeBackend.get_backend_preference()
    elixir_connected = NativeBackend.is_elixir_connected()

    # bd-88: Get actual source tracking from NativeBackend
    last_sources = getattr(NativeBackend, "_last_source", {})

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


def _on_startup():
    """Detect available backends on startup, then respect user preferences."""
    # bd-91: Removed auto-build — now detects available backends instead
    try:
        # bd-63: Load capability preferences first
        from code_puppy.native_backend import NativeBackend

        NativeBackend.load_preferences()

        # bd-91: Detect available backends without building
        backend_status = get_available_backends()

        # Check if any capabilities are enabled by user
        any_enabled = any(
            NativeBackend.is_enabled(cap)
            for cap in [
                NativeBackend.Capabilities.MESSAGE_CORE,
                NativeBackend.Capabilities.FILE_OPS,
                NativeBackend.Capabilities.REPO_INDEX,
                NativeBackend.Capabilities.PARSE,
            ]
        )

        if not any_enabled:
            # bd-90: Updated messaging to use "native backends" terminology
            emit_info(
                "🐕💤 Fast Puppy: All native backends disabled by puppy.cfg "
                "— run /fast_puppy enable to re-enable"
            )
            return

        # bd-91: Emit summary banner based on detected backends
        elixir_available = backend_status.get("elixir_available", False)
        python_fallback = backend_status.get("python_fallback", True)

        if elixir_available:
            emit_info("🐕⚡ Fast Puppy: Native backend active (Elixir) 🚀")
        elif python_fallback:
            emit_info("🐕 Fast Puppy: Native backend active (Python fallback)")
        else:
            emit_info(
                "🐕 Fast Puppy: No native backends available "
                "(install Elixir or Rust to enable acceleration)"
            )
    except Exception as e:
        logger.warning("Fast Puppy startup error: %s", e)
        emit_info(
            "🐕 Fast Puppy: startup hiccup — run /fast_puppy status for diagnostics"
        )


def _custom_help():
    # bd-90: Updated help text to reflect Elixir-first architecture
    # bd-88: Enhanced help text with clearer descriptions and profile command
    return [
        (
            "fast_puppy",
            "Show current status with backend preferences and active sources",
        ),
        ("fast_puppy status", "Detailed diagnostics with actionable next steps"),
        (
            "fast_puppy enable [cap]",
            "Enable all native backends or specific: message_core, file_ops, repo_index, parse",
        ),
        (
            "fast_puppy disable [cap]",
            "Disable all native backends or specific (fallback to Python)",
        ),
        (
            "fast_puppy profile",
            "Show current backend preference profile",
        ),
        (
            "fast_puppy profile elixir_first",
            "Set Elixir as preferred backend (faster for file ops)",
        ),
        (
            "fast_puppy profile python_only",
            "Use only Python implementations (no native acceleration)",
        ),
        (
            "fast_puppy build [name|--all]",
            "Rebuild native Rust crates (code_puppy_core, turbo_parse)",
        ),
    ]


def _handle_fast_puppy(command: str, name: str):
    if name != "fast_puppy":
        return None

    from code_puppy._core_bridge import (
        get_rust_status,
        set_rust_enabled,
    )

    parts = command.strip().split()
    subcommand = parts[1] if len(parts) > 1 else "status"
    args = parts[2:] if len(parts) > 2 else []

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

            results = _try_auto_build_all()
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

            # Reload status and enable
            if results.get("code_puppy_core", False):
                import code_puppy._core_bridge as bridge

                importlib.reload(bridge)
                set_rust_enabled(True)
                _write_persisted_preference(True)
                emit_info(
                    "🐕⚡ Fast Puppy: Native backend is ON."
                )  # bd-88: Updated terminology
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
                emit_info(f"🐕⚡ Fast Puppy: ✅ {crate_name} built successfully!")
                # If we built code_puppy_core, enable it
                if crate_name == "code_puppy_core":
                    import code_puppy._core_bridge as bridge

                    importlib.reload(bridge)
                    if bridge.RUST_AVAILABLE:
                        bridge.set_rust_enabled(True)
                        _write_persisted_preference(True)
                        emit_info(
                            "🐕⚡ Fast Puppy: Native backend is ON."
                        )  # bd-88: Updated terminology
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

    # Default: show comprehensive status (bd-63: combined old + new status)
    from code_puppy.native_backend import NativeBackend

    # Get crate build status
    crate_statuses = get_all_crate_status()

    # Get runtime status from core bridge
    rust_status = get_rust_status()
    _ = (
        _read_persisted_preference()
    )  # Legacy: kept for reference but not used (bd-63 uses per-capability)

    # Check config values for status display
    try:
        cfg = get_puppy_config()
        _ = cfg.rust_autobuild_disabled  # Kept for future use
    except Exception:
        pass

    repo_root = _find_repo_root()

    # Header
    emit_info("🐕⚡ Fast Puppy Status:")
    emit_info("")

    # bd-63: New capability status section
    emit_info("Capabilities (bd-63):")
    cap_status = NativeBackend.get_status()
    for cap, info in cap_status.items():
        if info.active:
            icon = "✅"
            status = "active"
        elif info.status == "disabled":
            icon = "💤"
            status = "disabled"
        else:
            icon = "❌"
            status = "unavailable"

        # Show capability + config source + user preference
        enabled_str = "enabled" if NativeBackend.is_enabled(cap) else "disabled"
        emit_info(f"   {icon} {cap}: {info.configured} ({status}, user: {enabled_str})")

    emit_info("")

    # Per-crate build status
    emit_info("Crate Build Status:")
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
        emit_info(f"   {name_padded:16} {state}")

    # Toolchain and infrastructure
    emit_info("")
    emit_info("Infrastructure:")
    emit_info(
        f"   {'Rust toolchain:':16} {'✅ rustc found' if _has_rust_toolchain() else '❌ not found'}"
    )
    emit_info(f"   {'maturin:':16} {'✅ found' if _has_maturin() else '❌ not found'}")
    emit_info(
        f"   {'Crate source:':16} {'✅ workspace found at ' + str(repo_root) if repo_root else '❌ not found'}"
    )

    # Legacy bridge status for backward compatibility
    emit_info("")
    emit_info("Legacy bridge:")
    emit_info(
        f"   {'code_puppy_core:':16} {'✅ available' if rust_status['installed'] else '❌ not installed'}, {'✅ enabled' if rust_status['enabled'] else '💤 disabled'}"
    )

    # Summary line
    # bd-90: Updated summary to use "Native backends" terminology
    emit_info("")
    if all(s["active"] for s in crate_statuses):
        emit_info("→ ALL SYSTEMS GO — full native backend acceleration active! 🚀")
    elif any(s["active"] for s in crate_statuses):
        active_count = sum(1 for s in crate_statuses if s["active"])
        emit_info(f"→ {active_count}/3 native backends active")
    else:
        if not _has_rust_toolchain():
            emit_info(
                "→ Pure Python mode — install Elixir or Rust to enable native acceleration"  # bd-88
            )
        else:
            emit_info(
                "→ Toolchain found but no native backends active — run /fast_puppy build"
            )

    return True


register_callback("startup", _on_startup)
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_fast_puppy)
