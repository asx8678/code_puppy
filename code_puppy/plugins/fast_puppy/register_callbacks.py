"""Fast Puppy — toggle Rust acceleration on/off at runtime.

Persists the setting to puppy.cfg so it survives restarts.

Usage:
    /fast_puppy           → show current status
    /fast_puppy enable    → turn Rust acceleration ON  (saved to puppy.cfg)
    /fast_puppy disable   → turn Rust acceleration OFF (saved to puppy.cfg)
    /fast_puppy status    → detailed diagnostics
"""

from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_info

CONFIG_KEY = "enable_fast_puppy"


def _read_persisted_preference() -> bool | None:
    """Read the saved preference from puppy.cfg.

    Returns True/False if explicitly set, None if not configured (default ON).
    """
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
        pass


def _on_startup():
    """Load persisted preference on app boot."""
    from code_puppy._core_bridge import RUST_AVAILABLE, set_rust_enabled

    saved = _read_persisted_preference()
    if saved is None:
        # Not configured — default is ON (if Rust is installed)
        return
    set_rust_enabled(saved)
    if RUST_AVAILABLE:
        state = "enabled" if saved else "disabled"
        emit_info(f"🐕⚡ Fast Puppy: Rust acceleration {state} (from puppy.cfg)")


def _custom_help():
    return [
        ("fast_puppy", "Toggle Rust acceleration (enable / disable / status)"),
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

    if subcommand == "enable":
        if not RUST_AVAILABLE:
            emit_info(
                "🐕 Fast Puppy: Rust module is not installed!\n"
                "   Run: cd code_puppy_core && maturin develop --release"
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
    if status["active"]:
        emoji = "⚡"
        state = "ACTIVE — Rust acceleration is speeding things up!"
    elif status["installed"] and not status["enabled"]:
        emoji = "💤"
        state = "PAUSED — Rust installed but disabled. Use /fast_puppy enable"
    else:
        emoji = "🐍"
        state = "PURE PYTHON — Rust module not installed"

    saved_str = {True: "enabled", False: "disabled", None: "not set (default: enabled)"}[saved]

    emit_info(f"🐕{emoji} Fast Puppy Status:")
    emit_info(f"   Rust module installed: {'✅' if status['installed'] else '❌'}")
    emit_info(f"   User enabled:          {'✅' if status['enabled'] else '❌'}")
    emit_info(f"   Currently active:      {'✅' if status['active'] else '❌'}")
    emit_info(f"   puppy.cfg setting:     {saved_str}")
    emit_info(f"   → {state}")
    return True


register_callback("startup", _on_startup)
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_fast_puppy)
