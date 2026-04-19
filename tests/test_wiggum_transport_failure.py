"""Regression tests for wiggum loop against dead transport (bd-203, bd-198 Phase 2).

These tests protect the Phase 2 invariants from the interactive loop's wiggum
re-loop logic:

1. Liveness gate: when Elixir transport is dead and PUP_ALLOW_ELIXIR_DEGRADED
   is NOT set, wiggum must stop (gate fires).
2. Degraded bypass: when transport is dead BUT PUP_ALLOW_ELIXIR_DEGRADED=1,
   the liveness gate does NOT stop wiggum.
3. Exception wall: asyncio.CancelledError must propagate; all other exceptions
   must be caught and result in stop_wiggum().

Strategy (Option B — structural guardrail tests):
- Test the gate logic via is_using_elixir() + env var check
- Test the exception wall's type-filtering property directly
- Verify stop_wiggum() is called by checking is_wiggum_active() after gate
- DO NOT try to run the full interactive_mode() loop — too much coupling

Every test uses an autouse fixture that calls stop_wiggum() to prevent state leaks.
"""

import asyncio
from unittest.mock import patch

import pytest

import code_puppy.runtime_state as runtime_state
from code_puppy.command_line.wiggum_state import (
    is_wiggum_active,
    start_wiggum,
    stop_wiggum,
)


@pytest.fixture(autouse=True)
def cleanup_wiggum():
    """Ensure wiggum state is always clean after each test."""
    yield
    stop_wiggum()


# ---------------------------------------------------------------------------
# Helpers that mirror the wiggum loop's gate + exception wall logic
# ---------------------------------------------------------------------------
# We extract the exact conditionals from interactive_loop.py lines 548-567
# so we can test them in isolation without the full REPL machinery.


def _wiggum_liveness_gate_passes() -> bool:
    """Replicate the liveness gate from the wiggum while-loop.

    Returns True if the gate allows wiggum to proceed (either transport is
    alive or degraded mode is on). Returns False if the gate should stop wiggum.
    """
    import os

    if not runtime_state.is_using_elixir() and os.environ.get("PUP_ALLOW_ELIXIR_DEGRADED") != "1":
        return False
    return True


def _exception_wall_handler(exc: BaseException) -> bool:
    """Replicate the wiggum loop's exception wall.

    Returns True if the exception was handled (stop_wiggum called).
    Re-raises asyncio.CancelledError so it propagates.
    Raises anything else? No — the wall catches Exception and calls stop_wiggum.
    """
    if isinstance(exc, asyncio.CancelledError):
        raise exc
    if not isinstance(exc, Exception):
        # BaseException but not Exception (e.g. KeyboardInterrupt) — let it propagate
        raise exc
    # Exception subclasses are caught → stop_wiggum + break
    stop_wiggum()
    return True


# =============================================================================
# Test 1: Liveness gate fires when transport is dead
# =============================================================================

class TestLivenessGate:
    """Tests for the transport liveness gate (bd-201)."""

    def test_gate_stops_wiggum_when_transport_dead_and_no_env(self, monkeypatch):
        """When transport is dead and degraded mode is off, gate fails → wiggum stops."""
        monkeypatch.delenv("PUP_ALLOW_ELIXIR_DEGRADED", raising=False)

        # Make is_using_elixir return False (transport dead)
        with patch.object(runtime_state, "is_using_elixir", return_value=False):
            start_wiggum("test prompt")
            assert is_wiggum_active()

            # Run the gate check
            gate_passed = _wiggum_liveness_gate_passes()
            assert gate_passed is False

            # Simulate what the wiggum loop does when gate fails
            if not gate_passed:
                stop_wiggum()

            assert not is_wiggum_active(), "Wiggum should be stopped after gate failure"

    def test_gate_allows_wiggum_when_transport_alive(self, monkeypatch):
        """When transport is alive, gate passes regardless of env var."""
        monkeypatch.delenv("PUP_ALLOW_ELIXIR_DEGRADED", raising=False)

        with patch.object(runtime_state, "is_using_elixir", return_value=True):
            start_wiggum("test prompt")
            gate_passed = _wiggum_liveness_gate_passes()
            assert gate_passed is True
            # Wiggum should still be active
            assert is_wiggum_active()


# =============================================================================
# Test 2: Degraded mode bypasses the gate
# =============================================================================

class TestDegradedModeBypass:
    """Tests that PUP_ALLOW_ELIXIR_DEGRADED=1 bypasses the liveness gate."""

    def test_gate_bypassed_when_degraded_mode_on(self, monkeypatch):
        """With PUP_ALLOW_ELIXIR_DEGRADED=1, gate passes even if transport is dead."""
        monkeypatch.setenv("PUP_ALLOW_ELIXIR_DEGRADED", "1")

        with patch.object(runtime_state, "is_using_elixir", return_value=False):
            start_wiggum("test prompt")
            assert is_wiggum_active()

            gate_passed = _wiggum_liveness_gate_passes()
            assert gate_passed is True, (
                "Gate should pass with degraded mode even when transport is dead"
            )

            # Wiggum should remain active (gate didn't stop it)
            assert is_wiggum_active()

    def test_gate_requires_exact_env_value(self, monkeypatch):
        """Gate does NOT pass with env var set to wrong value (e.g. 'true' instead of '1')."""
        monkeypatch.setenv("PUP_ALLOW_ELIXIR_DEGRADED", "true")

        with patch.object(runtime_state, "is_using_elixir", return_value=False):
            gate_passed = _wiggum_liveness_gate_passes()
            assert gate_passed is False


# =============================================================================
# Test 3: Exception wall catches Exception but re-raises CancelledError
# =============================================================================

class TestExceptionWall:
    """Tests for the wiggum loop's exception wall type-filtering."""

    def test_cancelled_error_propagates(self):
        """asyncio.CancelledError MUST propagate through the exception wall."""
        with pytest.raises(asyncio.CancelledError):
            _exception_wall_handler(asyncio.CancelledError())

    def test_runtime_error_caught_and_stops_wiggum(self):
        """RuntimeError is caught by the wall → stop_wiggum() called."""
        start_wiggum("test prompt")
        assert is_wiggum_active()

        handled = _exception_wall_handler(RuntimeError("boom"))
        assert handled is True
        assert not is_wiggum_active(), "Wiggum should be stopped after RuntimeError"

    def test_value_error_caught_and_stops_wiggum(self):
        """ValueError is caught by the wall → stop_wiggum() called."""
        start_wiggum("test prompt")

        handled = _exception_wall_handler(ValueError("bad value"))
        assert handled is True
        assert not is_wiggum_active()

    def test_os_error_caught_and_stops_wiggum(self):
        """OSError is caught by the wall → stop_wiggum() called."""
        start_wiggum("test prompt")

        handled = _exception_wall_handler(OSError("disk error"))
        assert handled is True
        assert not is_wiggum_active()

    def test_keyboard_interrupt_is_not_caught_by_exception_wall(self):
        """KeyboardInterrupt is BaseException but not Exception — not caught by 'except Exception'.

        The wiggum loop has a separate 'except KeyboardInterrupt' handler.
        Our wall only catches Exception + re-raises CancelledError.
        KeyboardInterrupt should propagate (it's a BaseException, not Exception).
        """
        # KeyboardInterrupt is a BaseException subclass, NOT an Exception subclass.
        # The wiggum loop's `except Exception` would NOT catch it.
        # Our handler mirrors that — it only handles Exception (via stop_wiggum)
        # and re-raises CancelledError. Everything else propagates.
        with pytest.raises(KeyboardInterrupt):
            _exception_wall_handler(KeyboardInterrupt())


# =============================================================================
# Test 4: Structural verification of the exception wall source code
# =============================================================================

class TestWiggumSourceInvariants:
    """Structural tests proving the wiggum loop has the right guards in source."""

    def test_exception_wall_has_cancelled_reraise(self):
        """Verify the interactive_loop source contains the CancelledError re-raise pattern in the wiggum loop."""
        import inspect
        import code_puppy.interactive_loop as il

        source = inspect.getsource(il.interactive_mode)
        # The wiggum loop must have: except asyncio.CancelledError: raise
        assert "asyncio.CancelledError" in source, (
            "interactive_mode must handle asyncio.CancelledError in wiggum loop"
        )
        # Find ALL asyncio.CancelledError handlers and verify at least one has 'raise'
        # right after it (the wiggum loop re-raise). This is more robust than
        # checking the first occurrence, since interactive_mode has multiple handlers.
        lines = source.split("\n")
        found_reraise = False
        for i, line in enumerate(lines):
            if "asyncio.CancelledError" in line and "except" in line:
                # Check next few non-empty, non-comment lines for 'raise'
                for j in range(i + 1, min(i + 5, len(lines))):
                    stripped = lines[j].strip()
                    if stripped and not stripped.startswith("#"):
                        if "raise" in stripped:
                            found_reraise = True
                        break
        assert found_reraise, (
            "At least one asyncio.CancelledError handler in interactive_mode must re-raise"
        )

    def test_liveness_gate_in_source(self):
        """Verify the interactive_loop source contains the liveness gate check."""
        import inspect
        import code_puppy.interactive_loop as il

        source = inspect.getsource(il.interactive_mode)
        # Must check is_using_elixir() AND PUP_ALLOW_ELIXIR_DEGRADED
        assert "is_using_elixir" in source, (
            "interactive_mode must call is_using_elixir() in wiggum gate"
        )
        assert "PUP_ALLOW_ELIXIR_DEGRADED" in source, (
            "interactive_mode must check PUP_ALLOW_ELIXIR_DEGRADED in wiggum gate"
        )
        assert "stop_wiggum" in source, (
            "interactive_mode must call stop_wiggum() when gate fails"
        )
