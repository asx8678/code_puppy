"""Tests for runtime_state.py Elixir routing (bd-133).

This module tests the pure Elixir thin wrapper in runtime_state.py,
ensuring all runtime state operations route to the Elixir RuntimeState GenServer.

Migration Note (bd-133):
- All state is stored exclusively in Elixir GenServer (no Python-side caching)
- No Python fallback - if Elixir is unavailable, functions will raise exceptions
- The _CURRENT_AUTOSAVE_ID and _SESSION_MODEL module variables are retained
  for backward compatibility but are no longer functionally used
"""

import os
from unittest.mock import patch

import pytest

# Import AFTER patching to ensure clean state
import code_puppy.runtime_state as runtime_state


class MockTransport:
    """Mock ElixirTransport for testing."""

    def __init__(self, responses: dict | None = None, raise_on_call: bool = False):
        self.responses = responses or {}
        self.raise_on_call = raise_on_call
        self.call_history: list[tuple[str, dict]] = []

    def _send_request(self, method: str, params: dict) -> dict:
        self.call_history.append((method, params))

        if self.raise_on_call:
            raise RuntimeError("Transport unavailable")

        if method in self.responses:
            return self.responses[method]

        # Default responses for common methods
        defaults = {
            "runtime_get_autosave_id": {"autosave_id": "20250115_120000"},
            "runtime_get_autosave_session_name": {
                "session_name": "auto_session_20250115_120000"
            },
            "runtime_rotate_autosave_id": {"autosave_id": "20250115_120001"},
            "runtime_set_autosave_from_session": {"autosave_id": "extracted_id"},
            "runtime_reset_autosave_id": {"reset": True},
            "runtime_get_session_model": {"session_model": "claude-3-5-sonnet"},
            "runtime_set_session_model": {"session_model": "claude-3-5-sonnet"},
            "runtime_reset_session_model": {"reset": True},
            "runtime_get_state": {
                "autosave_id": "20250115_120000",
                "session_model": "claude-3-5-sonnet",
                "session_start_time": "2025-01-15T12:00:00Z",
            },
            "ping": {"pong": True},
        }
        return defaults.get(method, {})


@pytest.fixture
def reset_state():
    """Reset runtime state before and after each test."""
    # Reset module-level variables for test isolation
    runtime_state._CURRENT_AUTOSAVE_ID = None
    runtime_state._SESSION_MODEL = None
    yield
    # Reset after
    runtime_state._CURRENT_AUTOSAVE_ID = None
    runtime_state._SESSION_MODEL = None


class TestElixirPath:
    """Tests for the pure Elixir routing path (bd-133)."""

    def test_get_current_autosave_id_elixir(self, reset_state):
        """Test get_current_autosave_id routes to Elixir."""
        mock = MockTransport()

        with patch.object(runtime_state, "_get_transport", return_value=mock):
            result = runtime_state.get_current_autosave_id()

        assert result == "20250115_120000"
        assert mock.call_history == [("runtime_get_autosave_id", {})]

    def test_get_autosave_session_name_elixir(self, reset_state):
        """Test get_current_autosave_session_name routes to Elixir."""
        mock = MockTransport()

        with patch.object(runtime_state, "_get_transport", return_value=mock):
            result = runtime_state.get_current_autosave_session_name()

        assert result == "auto_session_20250115_120000"
        assert ("runtime_get_autosave_session_name", {}) in mock.call_history

    def test_rotate_autosave_id_elixir(self, reset_state):
        """Test rotate_autosave_id routes to Elixir and returns new ID."""
        mock = MockTransport()

        with patch.object(runtime_state, "_get_transport", return_value=mock):
            result = runtime_state.rotate_autosave_id()

        assert result == "20250115_120001"
        assert ("runtime_rotate_autosave_id", {}) in mock.call_history

    def test_set_autosave_from_session_name_elixir(self, reset_state):
        """Test set_current_autosave_from_session_name routes to Elixir."""
        mock = MockTransport()

        with patch.object(runtime_state, "_get_transport", return_value=mock):
            result = runtime_state.set_current_autosave_from_session_name(
                "auto_session_20250115_120000"
            )

        assert result == "extracted_id"
        assert (
            "runtime_set_autosave_from_session",
            {"session_name": "auto_session_20250115_120000"},
        ) in mock.call_history

    def test_set_autosave_from_session_name_non_standard(self, reset_state):
        """Test set_current_autosave_from_session_name handles non-standard names."""
        mock = MockTransport()
        mock.responses["runtime_set_autosave_from_session"] = {
            "autosave_id": "custom_session_name"
        }

        with patch.object(runtime_state, "_get_transport", return_value=mock):
            result = runtime_state.set_current_autosave_from_session_name(
                "custom_session_name"
            )

        # Should use the whole name as ID when no prefix match
        assert result == "custom_session_name"

    def test_reset_autosave_id_elixir(self, reset_state):
        """Test reset_autosave_id routes to Elixir."""
        mock = MockTransport()

        with patch.object(runtime_state, "_get_transport", return_value=mock):
            runtime_state.reset_autosave_id()

        assert ("runtime_reset_autosave_id", {}) in mock.call_history

    def test_get_session_model_elixir(self, reset_state):
        """Test get_session_model routes to Elixir."""
        mock = MockTransport()

        with patch.object(runtime_state, "_get_transport", return_value=mock):
            result = runtime_state.get_session_model()

        assert result == "claude-3-5-sonnet"
        assert mock.call_history == [("runtime_get_session_model", {})]

    def test_set_session_model_elixir(self, reset_state):
        """Test set_session_model routes to Elixir."""
        mock = MockTransport()

        with patch.object(runtime_state, "_get_transport", return_value=mock):
            runtime_state.set_session_model("claude-3-5-sonnet")

        assert (
            "runtime_set_session_model",
            {"model": "claude-3-5-sonnet"},
        ) in mock.call_history

    def test_set_session_model_none_elixir(self, reset_state):
        """Test set_session_model with None routes to Elixir."""
        mock = MockTransport()

        with patch.object(runtime_state, "_get_transport", return_value=mock):
            runtime_state.set_session_model(None)

        assert ("runtime_set_session_model", {"model": None}) in mock.call_history

    def test_reset_session_model_elixir(self, reset_state):
        """Test reset_session_model routes to Elixir."""
        mock = MockTransport()

        with patch.object(runtime_state, "_get_transport", return_value=mock):
            runtime_state.reset_session_model()

        assert ("runtime_reset_session_model", {}) in mock.call_history

    def test_get_state_elixir(self, reset_state):
        """Test get_state routes to Elixir and returns state dict."""
        mock = MockTransport()

        with patch.object(runtime_state, "_get_transport", return_value=mock):
            result = runtime_state.get_state()

        assert result["autosave_id"] == "20250115_120000"
        assert result["session_model"] == "claude-3-5-sonnet"
        assert result["session_start_time"] == "2025-01-15T12:00:00Z"
        assert ("runtime_get_state", {}) in mock.call_history

    def test_is_using_elixir_true(self, reset_state):
        """Test is_using_elixir returns True when transport works."""
        mock = MockTransport()

        with patch.object(runtime_state, "_get_transport", return_value=mock):
            result = runtime_state.is_using_elixir()

        assert result is True

    def test_is_using_elixir_false(self, reset_state):
        """Test is_using_elixir returns False when transport fails."""
        mock = MockTransport(raise_on_call=True)

        with patch.object(runtime_state, "_get_transport", return_value=mock):
            result = runtime_state.is_using_elixir()

        assert result is False


class TestTransportFailureBehavior:
    """Tests for behavior when Elixir transport is unavailable (bd-133)."""

    def test_get_current_autosave_id_raises_on_transport_error(self, reset_state):
        """With pure Elixir routing, transport errors propagate."""
        mock = MockTransport(raise_on_call=True)

        with patch.object(runtime_state, "_get_transport", return_value=mock):
            with pytest.raises(RuntimeError, match="Transport unavailable"):
                runtime_state.get_current_autosave_id()

    def test_get_session_model_raises_on_transport_error(self, reset_state):
        """With pure Elixir routing, transport errors propagate."""
        mock = MockTransport(raise_on_call=True)

        with patch.object(runtime_state, "_get_transport", return_value=mock):
            with pytest.raises(RuntimeError, match="Transport unavailable"):
                runtime_state.get_session_model()


class TestDegradedModeSymmetry:
    """Tests for _degraded() fallback symmetry across all runtime_state functions (bd-206).

    Every function that talks to the Elixir transport should either:
    - Have a _degraded() fallback that runs when PUP_ALLOW_ELIXIR_DEGRADED=1
    - Or explicitly document why it doesn't need one
    """

    def test_reset_session_model_degraded_fallback(self, reset_state):
        """reset_session_model should use degraded fallback when transport is dead."""
        from code_puppy.elixir_transport import ElixirTransportError

        mock = MockTransport()
        mock._send_request = lambda m, p: (_ for _ in ()).throw(
            ElixirTransportError("Elixir process died (exit code 1)")
        )

        with patch.object(runtime_state, "_get_transport", return_value=mock), \
             patch.dict(os.environ, {"PUP_ALLOW_ELIXIR_DEGRADED": "1"}):
            # Should not raise — should fall back to Python-local reset
            runtime_state.reset_session_model()

        # _SESSION_MODEL should be None after reset
        assert runtime_state._SESSION_MODEL is None

    def test_reset_session_model_raises_without_degraded(self, reset_state):
        """reset_session_model should raise when transport is dead and degraded is off."""
        from code_puppy.elixir_transport import ElixirTransportError

        mock = MockTransport()
        mock._send_request = lambda m, p: (_ for _ in ()).throw(
            ElixirTransportError("Elixir process died (exit code 1)")
        )

        with patch.object(runtime_state, "_get_transport", return_value=mock), \
             patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ElixirTransportError, match="process died"):
                runtime_state.reset_session_model()

    def test_get_state_degraded_fallback(self, reset_state):
        """get_state should use degraded fallback when transport is dead."""
        from code_puppy.elixir_transport import ElixirTransportError

        mock = MockTransport()
        mock._send_request = lambda m, p: (_ for _ in ()).throw(
            ElixirTransportError("Elixir process died (exit code 1)")
        )

        with patch.object(runtime_state, "_get_transport", return_value=mock), \
             patch.dict(os.environ, {"PUP_ALLOW_ELIXIR_DEGRADED": "1"}):
            result = runtime_state.get_state()

        # Should return a dict with the expected keys
        assert "autosave_id" in result
        assert "session_model" in result
        assert "session_start_time" in result

    def test_get_state_raises_without_degraded(self, reset_state):
        """get_state should raise when transport is dead and degraded is off."""
        from code_puppy.elixir_transport import ElixirTransportError

        mock = MockTransport()
        mock._send_request = lambda m, p: (_ for _ in ()).throw(
            ElixirTransportError("Elixir process died (exit code 1)")
        )

        with patch.object(runtime_state, "_get_transport", return_value=mock), \
             patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ElixirTransportError, match="process died"):
                runtime_state.get_state()


class TestBackwardCompatibility:
    """Tests ensuring module-level variables exist for backward compatibility."""

    def test_module_variables_exist(self):
        """Test that _CURRENT_AUTOSAVE_ID and _SESSION_MODEL exist (bd-133)."""
        # These module variables are retained for test backward compatibility
        # even though they're no longer functionally used (state is in Elixir)
        assert hasattr(runtime_state, "_CURRENT_AUTOSAVE_ID")
        assert hasattr(runtime_state, "_SESSION_MODEL")
