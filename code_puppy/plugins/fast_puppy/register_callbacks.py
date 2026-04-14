"""Fast Puppy — toggle Rust acceleration on/off at runtime.

Auto-builds all Rust modules (code_puppy_core, turbo_ops, turbo_parse)
on first startup if toolchain is available.
Persists capability preferences to puppy.cfg so they survive restarts.

bd-63: Rewritten for capability-based profiles.

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
from code_puppy.plugins.fast_puppy.builder import (
    _find_crate_dir,
    _find_repo_root,
    _has_maturin,
    _has_rust_toolchain,
    _try_auto_build,
    _try_auto_build_all,
    build_single_crate,
    get_all_crate_status,
    CRATES,
)

# Re-export for backward compatibility (tests)
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
        NativeBackend.enable_all()
        NativeBackend.save_preferences()
        return "✅ All native acceleration enabled"

    # Enable specific capability
    cap = args[0].lower()
    cap_map = {
        "message_core": NativeBackend.Capabilities.MESSAGE_CORE,
        "file_ops": NativeBackend.Capabilities.FILE_OPS,
        "repo_index": NativeBackend.Capabilities.REPO_INDEX,
        "parse": NativeBackend.Capabilities.PARSE,
    }
    if cap in cap_map:
        NativeBackend.enable_capability(cap_map[cap])
        NativeBackend.save_preferences()
        return f"✅ {cap} enabled"
    return f"❌ Unknown capability: {cap}. Use: message_core, file_ops, repo_index, parse"


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
        NativeBackend.disable_all()
        NativeBackend.save_preferences()
        return "✅ All native acceleration disabled (Python-only mode)"

    # Disable specific capability
    cap = args[0].lower()
    cap_map = {
        "message_core": NativeBackend.Capabilities.MESSAGE_CORE,
        "file_ops": NativeBackend.Capabilities.FILE_OPS,
        "repo_index": NativeBackend.Capabilities.REPO_INDEX,
        "parse": NativeBackend.Capabilities.PARSE,
    }
    if cap in cap_map:
        NativeBackend.disable_capability(cap_map[cap])
        NativeBackend.save_preferences()
        return f"✅ {cap} disabled"
    return f"❌ Unknown capability: {cap}. Use: message_core, file_ops, repo_index, parse"


def _handle_status() -> str:
    """Get detailed status for all capabilities.

    Returns:
        Formatted status string.
    """
    from code_puppy.native_backend import NativeBackend
    # bd-69: _core_bridge imports removed — NativeBackend.get_status() used instead

    lines = ["⚡ Fast Puppy Status", ""]

    # Get NativeBackend capability status
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

        lines.append(f"  {icon} {cap}: {info.configured} ({status})")

    # Legacy bridge status
    lines.append("")
    lines.append(f"  message_core bridge: {'✅' if NativeBackend.is_active(NativeBackend.Capabilities.MESSAGE_CORE) else '❌'} available, {'✅' if NativeBackend.is_message_core_active() else '💤'} enabled")

    return "\n".join(lines)


def _on_startup():
    """Auto-build Rust modules if needed, then respect user preferences."""
    try:
        # bd-63: Load capability preferences first
        from code_puppy.native_backend import NativeBackend

        NativeBackend.load_preferences()

        results = _try_auto_build_all()

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
            emit_info(
                "🐕💤 Fast Puppy: All native acceleration disabled by puppy.cfg "
                "— run /fast_puppy enable to re-enable"
            )
            return

        # Emit summary banner based on results
        active_count = sum(1 for v in results.values() if v)
        total_count = len(results)
        expected_count = len(CRATES)  # Should be 2
        if results and active_count == expected_count:
            emit_info("🐕⚡ Fast Puppy: All Rust accelerators active — zoom! zoom! 🚀")
        elif active_count > 0:
            missing = [k for k, v in results.items() if not v]
            emit_info(
                f"🐕⚡ Fast Puppy: {active_count}/{total_count} Rust accelerators active "
                f"(missing: {', '.join(missing)} — see /fast_puppy status)"
            )
        else:
            emit_info(
                "🐕 Fast Puppy: Pure Python mode "
                "(install Rust toolchain to enable acceleration)"
            )
    except Exception as e:
        logger.warning("Fast Puppy startup error: %s", e)
        emit_info(
            "🐕 Fast Puppy: startup hiccup — run /fast_puppy status for diagnostics"
        )


def _custom_help():
    return [
        ("fast_puppy", "Toggle Rust acceleration / show status"),
        ("fast_puppy build [name|--all]", "Rebuild Rust crate(s)"),
        ("fast_puppy status", "Show detailed capability status"),
        ("fast_puppy enable [cap]", "Enable all or specific capability (message_core, file_ops, repo_index, parse)"),
        ("fast_puppy disable [cap]", "Disable all or specific capability"),
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

            emit_info("🐕⚡ Fast Puppy: Building all Rust modules...")

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
                emit_info("🐕⚡ Fast Puppy: Rust acceleration is ON.")
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
                        emit_info("🐕⚡ Fast Puppy: Rust acceleration is ON.")
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

    # Default: show comprehensive status (bd-63: combined old + new status)
    from code_puppy.native_backend import NativeBackend

    # Get crate build status
    crate_statuses = get_all_crate_status()

    # Get runtime status from core bridge
    rust_status = get_rust_status()
    _ = _read_persisted_preference()  # Legacy: kept for reference but not used (bd-63 uses per-capability)

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
    emit_info("")
    if all(s["active"] for s in crate_statuses):
        emit_info("→ ALL SYSTEMS GO — full Rust acceleration active! 🚀")
    elif any(s["active"] for s in crate_statuses):
        active_count = sum(1 for s in crate_statuses if s["active"])
        emit_info(f"→ {active_count}/3 Rust accelerators active")
    else:
        if not _has_rust_toolchain():
            emit_info(
                "→ Pure Python mode — install Rust toolchain to enable acceleration"
            )
        else:
            emit_info(
                "→ Rust toolchain found but no accelerators active — run /fast_puppy build"
            )

    return True


register_callback("startup", _on_startup)
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_fast_puppy)
