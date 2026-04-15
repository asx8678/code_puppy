"""Register completion-notification callbacks.

Modes
-----
* ``off``    — no notification (default)
* ``bell``   — terminal BEL (``\\a``)
* ``system`` — best-effort OS-native sound, falling back to BEL

Slash commands
~~~~~~~~~~~~~~
``/notify status | off | bell | system | test``
"""

from __future__ import annotations

import platform
import subprocess
import sys
from typing import Any

from code_puppy.callbacks import register_callback

# ---------------------------------------------------------------------------
# Config helpers (lazy-imported to avoid cycles at plugin load time)
# ---------------------------------------------------------------------------

_CONFIG_KEY = "completion_notification"
_VALID_MODES = {"off", "bell", "system"}


def _get_mode() -> str:
    """Read the persisted mode; default to *off*."""
    try:
        from code_puppy.config import get_value

        raw = get_value(_CONFIG_KEY)
        if raw and raw.strip().lower() in _VALID_MODES:
            return raw.strip().lower()
    except Exception:
        pass
    return "off"


def _set_mode(mode: str) -> None:
    """Persist *mode* (must be a valid mode string)."""
    from code_puppy.config import set_value

    set_value(_CONFIG_KEY, mode)


# ---------------------------------------------------------------------------
# Sound emission
# ---------------------------------------------------------------------------


def _emit_bell() -> None:
    """Write BEL to *stderr* and flush — stderr avoids polluting captured
    stdout while still triggering the terminal bell."""
    try:
        sys.stderr.write("\a")
        sys.stderr.flush()
    except Exception:
        # Absolutely never crash on a bell.
        pass


def _play_system_sound() -> None:
    """Best-effort OS-native notification sound.

    Falls back to BEL on any failure.
    """
    system = platform.system()
    try:
        if system == "Darwin":
            # afplay with a fixed built-in sound — no shell interpolation.
            subprocess.Popen(
                ["afplay", "/System/Library/Sounds/Glass.aiff"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        if system == "Windows":
            import winsound  # type: ignore[import-not-found]

            winsound.MessageBeep(winsound.MB_ICONASTERISK)  # type: ignore[attr-defined]
            return
        # Linux / other — try paplay with a freedesktop sound if available,
        # otherwise fall through to BEL.
        if system == "Linux":
            try:
                subprocess.Popen(
                    [
                        "paplay",
                        "/usr/share/sounds/freedesktop/stereo/complete.oga",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            except FileNotFoundError:
                pass  # paplay not installed
    except Exception:
        pass  # any OS-level failure → fall through

    # Ultimate fallback
    _emit_bell()


def _notify(mode: str | None = None) -> None:
    """Run the notification for *mode* (or read from config)."""
    effective = mode or _get_mode()
    if effective == "off":
        return
    if effective == "bell":
        _emit_bell()
        return
    if effective == "system":
        _play_system_sound()
        return
    # Unknown mode — silently ignore.


# ---------------------------------------------------------------------------
# agent_run_end — fires on every completed top-level run
# ---------------------------------------------------------------------------


def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Any | None = None,
    response_text: str | None = None,
    metadata: dict[str, Any] | None = None,
    run_context: Any | None = None,
) -> None:
    """Emit a completion sound for *top-level* runs only."""
    try:
        # Suppress child / sub-agent completions.
        if run_context is not None and getattr(run_context, "parent_run_id", None):
            return
        _notify()
    except Exception:
        # Never, ever crash the app because of a sound effect.
        pass


# ---------------------------------------------------------------------------
# Slash-command UX: /notify status | off | bell | system | test
# ---------------------------------------------------------------------------


def _custom_help() -> list[tuple[str, str]]:
    return [("notify", "Manage completion notifications (off|bell|system)")]  # noqa: E501


def _handle_custom_command(command: str, name: str) -> bool | str | None:
    if name != "notify":
        return None  # Not ours — pass through.

    try:
        from code_puppy.messaging import emit_info
    except Exception:
        return True  # Can't emit — silently bail.

    parts = command.strip().split(maxsplit=1)
    sub = parts[1].strip().lower() if len(parts) == 2 else "status"

    if sub == "status":
        mode = _get_mode()
        emit_info(f"Completion notification mode: {mode}")
        return True

    if sub in _VALID_MODES:
        _set_mode(sub)
        emit_info(f"Completion notification set to: {sub}")
        return True

    if sub == "test":
        mode = _get_mode()
        if mode == "off":
            _emit_bell()
            emit_info(
                "Saved mode is 'off' — no sound on completion. "
                "Run /notify bell or /notify system to enable."
            )
        else:
            emit_info("Playing completion notification sound…")
            _notify()
        return True

    emit_info(f"Unknown /notify subcommand: {sub!r}  (try status|off|bell|system|test)")
    return True


# ---------------------------------------------------------------------------
# Registration — module scope, as required by plugin loader
# ---------------------------------------------------------------------------

register_callback("agent_run_end", _on_agent_run_end)
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_custom_command)
