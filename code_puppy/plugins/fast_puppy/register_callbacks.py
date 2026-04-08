"""Fast Puppy — toggle Rust acceleration on/off at runtime.

Auto-builds the Rust module on first startup if toolchain is available.
Persists the setting to puppy.cfg so it survives restarts.

Usage:
    /fast_puppy           → show current status
    /fast_puppy enable    → turn Rust acceleration ON  (saved to puppy.cfg)
    /fast_puppy disable   → turn Rust acceleration OFF (saved to puppy.cfg)
    /fast_puppy status    → detailed diagnostics
    /fast_puppy build     → force rebuild the Rust module
"""

import logging
import shutil
import subprocess
import sys
from pathlib import Path

from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_info

logger = logging.getLogger(__name__)

CONFIG_KEY = "enable_fast_puppy"


def _find_crate_dir() -> Path | None:
    """Find the code_puppy_core crate directory."""
    # Check relative to the code_puppy package
    pkg_dir = Path(__file__).resolve().parent.parent.parent
    candidates = [
        pkg_dir.parent / "code_puppy_core",  # repo root / code_puppy_core
        pkg_dir / "code_puppy_core",  # inside package (unlikely)
    ]
    for candidate in candidates:
        if (candidate / "Cargo.toml").exists():
            return candidate
    return None


def _has_rust_toolchain() -> bool:
    """Check if Rust compiler is available."""
    return shutil.which("rustc") is not None


def _has_maturin() -> bool:
    """Check if maturin is available (in PATH or as Python module)."""
    if shutil.which("maturin") is not None:
        return True
    # Try as Python module
    try:
        result = subprocess.run(
            [sys.executable, "-m", "maturin", "--version"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _build_rust_module(crate_dir: Path) -> bool:
    """Build and install the Rust module into the current environment."""
    try:
        # Try maturin from PATH first, then as Python module
        if shutil.which("maturin"):
            cmd = [
                "maturin",
                "develop",
                "--release",
                "--manifest-path",
                str(crate_dir / "Cargo.toml"),
            ]
        else:
            cmd = [
                sys.executable,
                "-m",
                "maturin",
                "develop",
                "--release",
                "--manifest-path",
                str(crate_dir / "Cargo.toml"),
            ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min max for compilation
            cwd=str(crate_dir),
        )
        if result.returncode == 0:
            return True
        logger.debug("Rust build failed: %s", result.stderr)
        return False
    except subprocess.TimeoutExpired:
        logger.debug("Rust build timed out")
        return False
    except Exception as e:
        logger.debug("Rust build error: %s", e)
        return False


def _try_auto_build() -> bool:
    """Attempt to auto-build the Rust module if not installed."""
    from code_puppy._core_bridge import RUST_AVAILABLE

    if RUST_AVAILABLE:
        return True  # Already installed

    crate_dir = _find_crate_dir()
    if crate_dir is None:
        logger.debug("Rust crate directory not found")
        return False

    if not _has_rust_toolchain():
        logger.debug("Rust toolchain not found")
        return False

    if not _has_maturin():
        # Try to install maturin
        try:
            install_result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "maturin"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if install_result.returncode != 0:
                stderr = install_result.stderr.strip() if install_result.stderr else ""
                logger.debug(
                    "pip install maturin failed (rc=%d): %s",
                    install_result.returncode,
                    stderr,
                )
                return False
        except Exception as exc:
            logger.debug("Could not install maturin: %s", exc)
            return False

    emit_info("🐕⚡ Fast Puppy: Building Rust acceleration module (first time only)...")
    success = _build_rust_module(crate_dir)

    if success:
        # Reload the bridge module to pick up the newly built extension
        import importlib
        import code_puppy._core_bridge as bridge

        importlib.reload(bridge)

        # Also patch the module-level RUST_AVAILABLE that other modules
        # already copied at import time (e.g., base_agent.py line 43)
        import code_puppy.agents.base_agent as _ba

        if hasattr(_ba, "RUST_AVAILABLE"):
            _ba.RUST_AVAILABLE = bridge.RUST_AVAILABLE
        # Re-import the Rust functions into base_agent's namespace
        if bridge.RUST_AVAILABLE:
            try:
                _ba.process_messages_batch = bridge.process_messages_batch
                _ba.prune_and_filter = bridge.prune_and_filter
                _ba.rust_truncation_indices = bridge.truncation_indices
                _ba.serialize_messages_for_rust = bridge.serialize_messages_for_rust
                _ba.is_rust_enabled = bridge.is_rust_enabled
            except Exception as exc:
                logger.warning(
                    "Failed to re-export Rust symbols into base_agent: %s", exc
                )

        if bridge.RUST_AVAILABLE:
            emit_info("🐕⚡ Fast Puppy: Rust module compiled and ready — Zoom! Zoom!")
            return True
        else:
            emit_info("🐕 Fast Puppy: Build succeeded but module not loadable")
            return False
    else:
        emit_info(
            "🐕 Fast Puppy: Could not build Rust module — running in pure Python mode\n"
            "   To build manually: cd code_puppy_core && maturin develop --release"
        )
        return False


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
    """Auto-build Rust module if needed, then force Rust enabled."""
    _ = _read_persisted_preference()  # Read but don't use (force enable regardless)

    # Always try to auto-build (removed guard)
    _try_auto_build()

    # Now apply the persisted preference
    from code_puppy._core_bridge import (
        RUST_AVAILABLE,
        is_rust_enabled,
        set_rust_enabled,
    )

    # Force Rust enabled after successful build
    set_rust_enabled(True)
    _write_persisted_preference(True)  # Persist True back to puppy.cfg

    # Always announce Rust status on startup
    if is_rust_enabled():
        emit_info("🐕⚡ Fast Puppy: Rust acceleration active — Zoom! Zoom!")
    elif RUST_AVAILABLE and not is_rust_enabled():
        emit_info(
            "🐕💤 Fast Puppy: Rust installed but disabled (/fast_puppy enable to activate)"
        )


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
        emit_info("🐕⚡ Fast Puppy: Building Rust module...")
        if _try_auto_build():
            # Reload status
            import importlib
            import code_puppy._core_bridge as bridge

            importlib.reload(bridge)
            set_rust_enabled(True)
            _write_persisted_preference(True)
            emit_info("🐕⚡ Fast Puppy: Build complete! Rust acceleration is ON.")
        else:
            emit_info("🐕 Fast Puppy: Build failed. Check logs for details.")
        return True

    if subcommand == "enable":
        if not RUST_AVAILABLE:
            # Try to build first
            if _try_auto_build():
                import importlib
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
    return True


register_callback("startup", _on_startup)
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_fast_puppy)
