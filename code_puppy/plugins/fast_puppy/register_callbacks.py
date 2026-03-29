"""Fast Puppy — toggle Rust acceleration on/off at runtime.

Usage:
    /fast_puppy           → show current status
    /fast_puppy enable    → turn Rust acceleration ON
    /fast_puppy disable   → turn Rust acceleration OFF
    /fast_puppy status    → detailed diagnostics
"""

from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_info


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
        is_rust_enabled,
        set_rust_enabled,
    )

    parts = command.strip().split()
    subcommand = parts[1] if len(parts) > 1 else "status"

    if subcommand == "enable":
        if not RUST_AVAILABLE:
            emit_info(
                "🐕 Fast Puppy: Rust module is not installed! "
                "Run `cd code_puppy_core && maturin develop --release` first."
            )
            return True
        set_rust_enabled(True)
        emit_info("🐕⚡ Fast Puppy: Rust acceleration ENABLED — zoom zoom!")
        return True

    if subcommand == "disable":
        set_rust_enabled(False)
        emit_info("🐕 Fast Puppy: Rust acceleration DISABLED — pure Python mode")
        return True

    # status (default)
    status = get_rust_status()
    if status["active"]:
        emoji = "⚡"
        state = "ACTIVE — Rust acceleration is speeding things up!"
    elif status["installed"] and not status["enabled"]:
        emoji = "💤"
        state = "PAUSED — Rust is installed but disabled. Use /fast_puppy enable"
    else:
        emoji = "🐍"
        state = "PURE PYTHON — Rust module not installed"

    emit_info(f"🐕{emoji} Fast Puppy Status:")
    emit_info(f"   Rust module installed: {'✅' if status['installed'] else '❌'}")
    emit_info(f"   User enabled:          {'✅' if status['enabled'] else '❌'}")
    emit_info(f"   Currently active:      {'✅' if status['active'] else '❌'}")
    emit_info(f"   → {state}")
    return True


register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_fast_puppy)
