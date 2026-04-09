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
import shutil  # Re-export for test compatibility
import subprocess  # Re-export for test compatibility

from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_info

# Import builder module (may be split into builder.py for line count)
from code_puppy.plugins.fast_puppy.builder import (
    _find_crate_dir,
    _find_repo_root,
    _has_maturin,
    _has_rust_toolchain,
    _try_auto_build,
    _try_auto_build_all,
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
    """Auto-build Rust modules if needed, then force Rust enabled."""
    try:
        _ = _read_persisted_preference()  # Read but don't use (force enable)

        # Build all crates
        results = _try_auto_build_all()

        # Import bridge after potential builds
        from code_puppy._core_bridge import (
            RUST_AVAILABLE,
            is_rust_enabled,
            set_rust_enabled,
        )

        # Force Rust enabled after successful build
        set_rust_enabled(True)
        _write_persisted_preference(True)

        # Emit summary banner
        if len(results) == 3 and all(results.values()):
            emit_info("🐕⚡ Fast Puppy: All Rust accelerators active — zoom! zoom! 🚀")
        elif results:
            active_count = sum(1 for v in results.values() if v)
            total_count = len(CRATES)
            emit_info(f"🐕⚡ Fast Puppy: {active_count}/{total_count} Rust accelerators active")
            for crate_spec in CRATES:
                name = crate_spec["name"]
                status = "✅" if results.get(name, False) else "❌"
                emit_info(f"   {status} {name}")
        else:
            # No results = no toolchain or disabled
            if not _has_rust_toolchain():
                emit_info("🐕 Fast Puppy: Pure Python mode (Rust toolchain unavailable)")
            else:
                emit_info("🐕 Fast Puppy: Rust toolchain found but no crates built yet")

        # Additional status if code_puppy_core specifically is available
        if RUST_AVAILABLE and not is_rust_enabled():
            emit_info(
                "🐕💤 Fast Puppy: Rust installed but disabled (/fast_puppy enable to activate)"
            )

    except Exception as e:
        logger.warning("Fast Puppy startup error: %s", e)
        # Never let build failures crash the REPL


def _custom_help():
    return [
        ("fast_puppy", "Toggle Rust acceleration (enable / disable / status / build)"),
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
        crate_dir = _find_crate_dir()
        if crate_dir is None:
            emit_info("🐕 Fast Puppy: Rust crate not found in project")
            return True
        if not _has_rust_toolchain():
            emit_info(
                "🐕 Fast Puppy: Rust toolchain not found\n"
                "   Install: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
            )
            return True
        emit_info("🐕⚡ Fast Puppy: Building all Rust modules...")

        results = _try_auto_build_all()
        active_count = sum(1 for v in results.values() if v)
        total_count = len(CRATES)

        if active_count == total_count:
            emit_info(f"🐕⚡ Fast Puppy: All {total_count} modules built successfully!")
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
    status = get_rust_status()
    saved = _read_persisted_preference()
    crate_dir = _find_crate_dir()

    # Check all crates
    repo_root = _find_repo_root()
    crate_statuses = []
    for crate_spec in CRATES:
        from code_puppy.plugins.fast_puppy.builder import _is_crate_installed

        crate_name = crate_spec["name"]
        probe = crate_spec["probe"]
        is_installed = _is_crate_installed(probe)
        crate_statuses.append((crate_name, is_installed))

    if status["active"]:
        emoji = "⚡"
        state = "ACTIVE — Rust acceleration is speeding things up!"
    elif status["installed"] and not status["enabled"]:
        emoji = "💤"
        state = "PAUSED — Rust installed but disabled. Use /fast_puppy enable"
    elif crate_dir and _has_rust_toolchain():
        emoji = "🔧"
        state = "READY TO BUILD — Run /fast_puppy build or /fast_puppy enable"
    else:
        emoji = "🐍"
        state = "PURE PYTHON — Rust toolchain not found"

    saved_str = {
        True: "enabled",
        False: "disabled",
        None: "not set (default: enabled)",
    }[saved]

    emit_info(f"🐕{emoji} Fast Puppy Status:")
    emit_info(f"   Rust module installed: {'✅' if status['installed'] else '❌'}")
    emit_info(f"   Rust toolchain found:  {'✅' if _has_rust_toolchain() else '❌'}")
    emit_info(f"   Crate source found:    {'✅' if crate_dir else '❌'}")
    emit_info(f"   User enabled:          {'✅' if status['enabled'] else '❌'}")
    emit_info(f"   Currently active:      {'✅' if status['active'] else '❌'}")
    emit_info(f"   puppy.cfg setting:     {saved_str}")
    emit_info(f"   → {state}")

    # Show per-crate status
    emit_info("")
    emit_info("   Rust Crate Status:")
    for name, installed in crate_statuses:
        status_icon = "✅" if installed else "❌"
        emit_info(f"     {status_icon} {name}")

    return True


register_callback("startup", _on_startup)
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_fast_puppy)
