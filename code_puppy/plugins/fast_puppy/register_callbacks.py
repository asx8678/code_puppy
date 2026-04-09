"""Fast Puppy — toggle Rust acceleration on/off at runtime.

Auto-builds all Rust modules (code_puppy_core, turbo_ops, turbo_parse)
on first startup if toolchain is available.
Persists the setting to puppy.cfg so it survives restarts.

Usage:
    /fast_puppy           → show current status
    /fast_puppy enable    → turn Rust acceleration ON  (saved to puppy.cfg)
    /fast_puppy disable   → turn Rust acceleration OFF (saved to puppy.cfg)
    /fast_puppy status    → detailed diagnostics
    /fast_puppy build     → force rebuild the Rust module
"""

from __future__ import annotations

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
]

logger = logging.getLogger(__name__)

CONFIG_KEY = "enable_fast_puppy"


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
    """Save the preference to puppy.cfg."""
    try:
        from code_puppy.config import set_config_value

        set_config_value(CONFIG_KEY, str(enabled).lower())
    except Exception:
        logger.warning("Failed to persist fast_puppy preference to config")


def _on_startup():
    """Auto-build Rust modules if needed, then respect user preference."""
    try:
        results = _try_auto_build_all()

        from code_puppy._core_bridge import (
            set_rust_enabled,
        )

        saved = _read_persisted_preference()
        if saved is False:
            # Respect explicit user opt-out
            set_rust_enabled(False)
            emit_info(
                "🐕💤 Fast Puppy: Rust acceleration disabled by puppy.cfg "
                "— run /fast_puppy enable to re-enable"
            )
            return

        # Default: enable
        set_rust_enabled(True)
        if saved is None:
            # First run — persist default
            _write_persisted_preference(True)

        # Emit summary banner based on results
        active_count = sum(1 for v in results.values() if v)
        total_count = len(results)
        if active_count == total_count:
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
        ("fast_puppy status", "Show detailed status for all 3 Rust crates"),
        ("fast_puppy enable", "Enable Rust message-processing acceleration"),
        ("fast_puppy disable", "Disable Rust message-processing acceleration"),
    ]


def _handle_fast_puppy(command: str, name: str):
    if name != "fast_puppy":
        return None

    from code_puppy._core_bridge import (
        RUST_AVAILABLE,
        get_rust_status,
        set_rust_enabled,
    )

    parts = command.strip().split()
    subcommand = parts[1] if len(parts) > 1 else "status"

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

    if subcommand == "enable":
        if not RUST_AVAILABLE:
            # Try to build first
            results = _try_auto_build_all()
            if results.get("code_puppy_core", False):
                import code_puppy._core_bridge as bridge

                importlib.reload(bridge)
                if bridge.RUST_AVAILABLE:
                    bridge.set_rust_enabled(True)
                    _write_persisted_preference(True)
                    emit_info(
                        "🐕⚡ Fast Puppy: Rust module built and ENABLED — zoom zoom!\n"
                        "   Saved to puppy.cfg — will stay enabled across restarts."
                    )
                    return True
            emit_info(
                "🐕 Fast Puppy: Could not build Rust module\n"
                "   Need: Rust toolchain (rustc) + maturin\n"
                "   Install Rust: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh\n"
                "   Then retry: /fast_puppy enable"
            )
            return True
        set_rust_enabled(True)
        _write_persisted_preference(True)
        emit_info(
            "🐕⚡ Fast Puppy: Rust acceleration ENABLED — zoom zoom!\n"
            "   Saved to puppy.cfg — will stay enabled across restarts."
        )
        return True

    if subcommand == "disable":
        set_rust_enabled(False)
        _write_persisted_preference(False)
        emit_info(
            "🐕 Fast Puppy: Rust acceleration DISABLED — pure Python mode\n"
            "   Saved to puppy.cfg — will stay disabled across restarts."
        )
        return True

    # status (default)
    # Get comprehensive status for all crates
    crate_statuses = get_all_crate_status()

    # Get runtime status from core bridge
    rust_status = get_rust_status()
    saved = _read_persisted_preference()

    # Check config values for status display
    try:
        cfg = get_puppy_config()
        disable_autobuild = cfg.rust_autobuild_disabled
    except Exception:
        disable_autobuild = False

    repo_root = _find_repo_root()

    # Header
    emit_info("🐕⚡ Fast Puppy Status:")

    # Per-crate status
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
    emit_info(
        f"   {'Rust toolchain:':16} {'✅ rustc found' if _has_rust_toolchain() else '❌ not found'}"
    )
    emit_info(f"   {'maturin:':16} {'✅ found' if _has_maturin() else '❌ not found'}")
    emit_info(
        f"   {'Crate source:':16} {'✅ workspace found at ' + str(repo_root) if repo_root else '❌ not found'}"
    )

    # Runtime status for code_puppy_core (message processing)
    emit_info(
        f"   {'User enabled:':16} {'✅ (code_puppy_core toggle)' if rust_status['enabled'] else '❌ disabled'}"
    )

    # Config file values
    saved_str = str(saved).lower() if saved is not None else "<not set>"
    disable_str = "true" if disable_autobuild else "<not set>"
    emit_info(
        f"   {'puppy.cfg:':16} enable_fast_puppy={saved_str}, disable_rust_autobuild={disable_str}"
    )

    # Summary line
    if all(s["active"] for s in crate_statuses):
        emit_info("   → ALL SYSTEMS GO — full Rust acceleration active! 🚀")
    elif any(s["active"] for s in crate_statuses):
        active_count = sum(1 for s in crate_statuses if s["active"])
        emit_info(f"   → {active_count}/3 Rust accelerators active (see details above)")
    else:
        if not _has_rust_toolchain():
            emit_info(
                "   → Pure Python mode — install Rust toolchain to enable acceleration"
            )
        else:
            emit_info(
                "   → Rust toolchain found but no accelerators active — run /fast_puppy build"
            )

    return True


register_callback("startup", _on_startup)
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_fast_puppy)
