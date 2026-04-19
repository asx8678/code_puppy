"""Wiggum loop state management.

This module tracks the state for the /wiggum command, which causes
the agent to automatically re-run the same prompt after completing,
like Chief Wiggum chasing donuts in circles. 🍩

Usage:
    /wiggum <prompt>  - Start looping with the given prompt
    Ctrl+C            - Stop the wiggum loop
"""

from dataclasses import dataclass


@dataclass
class WiggumState:
    """State container for wiggum loop mode."""

    active: bool = False
    prompt: str | None = None
    loop_count: int = 0

    def start(self, prompt: str) -> None:
        """Start wiggum mode with the given prompt."""
        self.active = True
        self.prompt = prompt
        self.loop_count = 0

    def stop(self) -> None:
        """Stop wiggum mode."""
        self.active = False
        self.prompt = None
        self.loop_count = 0

    def increment(self) -> int:
        """Increment and return the loop count."""
        self.loop_count += 1
        return self.loop_count


# Global singleton for wiggum state
_wiggum_state = WiggumState()


def get_wiggum_state() -> WiggumState:
    """Get the global wiggum state."""
    return _wiggum_state


def is_wiggum_active() -> bool:
    """Check if wiggum mode is currently active."""
    return _wiggum_state.active


def get_wiggum_prompt() -> str | None:
    """Get the current wiggum prompt, if active."""
    return _wiggum_state.prompt if _wiggum_state.active else None


def start_wiggum(prompt: str) -> None:
    """Start wiggum mode with the given prompt."""
    _wiggum_state.start(prompt)


def stop_wiggum() -> None:
    """Stop wiggum mode."""
    _wiggum_state.stop()


def increment_wiggum_count() -> int:
    """Increment wiggum loop count and return the new value."""
    return _wiggum_state.increment()


def get_wiggum_count() -> int:
    """Get the current wiggum loop count."""
    return _wiggum_state.loop_count


def has_ready_bd_work() -> bool:
    """Return True if `bd ready --json` reports at least one ready issue.

    Fail-open: if bd is not installed, times out, returns non-zero, or
    outputs malformed JSON, this returns True and emits a warning so
    the running wiggum loop is not killed due to a flaky tracker.
    """
    import json
    import subprocess

    try:
        proc = subprocess.run(
            ["bd", "ready", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        try:
            from code_puppy.messaging import emit_warning
            emit_warning("wiggum: `bd` CLI not found; cannot auto-stop on empty queue.")
        except Exception:
            pass
        return True
    except subprocess.TimeoutExpired:
        try:
            from code_puppy.messaging import emit_warning
            emit_warning("wiggum: `bd ready` timed out; continuing loop.")
        except Exception:
            pass
        return True

    if proc.returncode != 0:
        try:
            from code_puppy.messaging import emit_warning
            emit_warning(
                f"wiggum: `bd ready` exited {proc.returncode}; continuing loop."
            )
        except Exception:
            pass
        return True

    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        try:
            from code_puppy.messaging import emit_warning
            emit_warning("wiggum: could not parse `bd ready --json` output; continuing loop.")
        except Exception:
            pass
        return True

    # bd ready may return a list, or a dict with an "issues" key. Handle both.
    if isinstance(data, list):
        return len(data) > 0
    if isinstance(data, dict):
        issues = data.get("issues")
        if isinstance(issues, list):
            return len(issues) > 0
        # unknown shape, fail-open
        return True
    return True
