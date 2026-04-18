"""Tests for runtime_state.py Elixir routing (bd-117).

This module tests the optional Elixir routing layer in runtime_state.py,
ensuring:
1. Elixir path works when transport is available
2. Python fallback works when transport raises or is unavailable
3. Existing behavior remains unchanged when transport is unavailable
"""

from unittest.mock import MagicMock, patch

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
            "runtime_get_autosave_session_name": {"session_name": "auto_session_20250115_120000"},
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
    # Reset before
    runtime_state._CURRENT_AUTOSAVE_ID = None
    runtime_state._SESSION_MODEL = None
    yield
    # Reset after
    runtime_state._CURRENT_AUTOSAVE_ID = None
    runtime_state._SESSION_MODEL = None


class TestElixirPath:
    """Tests for the Elixir routing path."""

    def test_get_current_autosave_id_elixir(self, reset_state):
        """Test get_current_autosave_id uses Elixir when available."""
        mock = MockTransport()

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            result = runtime_state.get_current_autosave_id()

        assert result == "20250115_120000"
        assert mock.call_history == [("runtime_get_autosave_id", {})]

    def test_get_autosave_session_name_elixir(self, reset_state):
        """Test get_current_autosave_session_name uses Elixir when available."""
        mock = MockTransport()

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            result = runtime_state.get_current_autosave_session_name()

        assert result == "auto_session_20250115_120000"
        assert ("runtime_get_autosave_session_name", {}) in mock.call_history

    def test_rotate_autosave_id_elixir(self, reset_state):
        """Test rotate_autosave_id uses Elixir when available."""
        mock = MockTransport()

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            result = runtime_state.rotate_autosave_id()

        assert result == "20250115_120001"
        assert ("runtime_rotate_autosave_id", {}) in mock.call_history
        # Should update Python cache to stay in sync
        assert runtime_state._CURRENT_AUTOSAVE_ID == "20250115_120001"

    def test_set_autosave_from_session_name_elixir(self, reset_state):
        """Test set_current_autosave_from_session_name uses Elixir when available."""
        mock = MockTransport()

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            result = runtime_state.set_current_autosave_from_session_name(
                "auto_session_20250115_120000"
            )

        assert result == "extracted_id"
        assert ("runtime_set_autosave_from_session", {"session_name": "auto_session_20250115_120000"}) in mock.call_history
        # Should update Python cache to stay in sync
        assert runtime_state._CURRENT_AUTOSAVE_ID == "extracted_id"

    def test_reset_autosave_id_elixir(self, reset_state):
        """Test reset_autosave_id uses Elixir when available."""
        runtime_state._CURRENT_AUTOSAVE_ID = "some_id"
        mock = MockTransport()

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            runtime_state.reset_autosave_id()

        assert ("runtime_reset_autosave_id", {}) in mock.call_history
        # Should update Python cache to stay in sync
        assert runtime_state._CURRENT_AUTOSAVE_ID is None

    def test_get_session_model_elixir(self, reset_state):
        """Test get_session_model uses Elixir when available."""
        mock = MockTransport()

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            result = runtime_state.get_session_model()

        assert result == "claude-3-5-sonnet"
        assert mock.call_history == [("runtime_get_session_model", {})]

    def test_set_session_model_elixir(self, reset_state):
        """Test set_session_model uses Elixir when available."""
        mock = MockTransport()

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            runtime_state.set_session_model("claude-3-5-sonnet")

        assert ("runtime_set_session_model", {"model": "claude-3-5-sonnet"}) in mock.call_history
        # Should update Python cache to stay in sync
        assert runtime_state._SESSION_MODEL == "claude-3-5-sonnet"

    def test_set_session_model_none_elixir(self, reset_state):
        """Test set_session_model with None uses Elixir when available."""
        mock = MockTransport()

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            runtime_state.set_session_model(None)

        assert ("runtime_set_session_model", {"model": None}) in mock.call_history
        assert runtime_state._SESSION_MODEL is None

    def test_reset_session_model_elixir(self, reset_state):
        """Test reset_session_model uses Elixir when available."""
        runtime_state._SESSION_MODEL = "some_model"
        mock = MockTransport()

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            runtime_state.reset_session_model()

        assert ("runtime_reset_session_model", {}) in mock.call_history
        # Should update Python cache to stay in sync
        assert runtime_state._SESSION_MODEL is None

    def test_get_state_elixir(self, reset_state):
        """Test get_state uses Elixir when available."""
        mock = MockTransport()

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            result = runtime_state.get_state()

        assert result["autosave_id"] == "20250115_120000"
        assert result["session_model"] == "claude-3-5-sonnet"
        assert result["session_start_time"] == "2025-01-15T12:00:00Z"
        assert ("runtime_get_state", {}) in mock.call_history

    def test_is_using_elixir_true(self, reset_state):
        """Test is_using_elixir returns True when transport works."""
        mock = MockTransport()

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            result = runtime_state.is_using_elixir()

        assert result is True


class TestPythonFallback:
    """Tests for the Python fallback path when Elixir fails."""

    def test_get_current_autosave_id_fallback(self, reset_state):
        """Test get_current_autosave_id falls back to Python on transport error."""
        mock = MockTransport(raise_on_call=True)

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            result = runtime_state.get_current_autosave_id()

        # Should return a timestamp-based ID (Python fallback)
        assert len(result) == 15  # YYYYMMDD_HHMMSS format
        assert result == runtime_state._CURRENT_AUTOSAVE_ID

    def test_get_autosave_session_name_fallback(self, reset_state):
        """Test get_current_autosave_session_name falls back to Python."""
        mock = MockTransport(raise_on_call=True)
        runtime_state._CURRENT_AUTOSAVE_ID = "20250115_120000"

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            result = runtime_state.get_current_autosave_session_name()

        assert result == "auto_session_20250115_120000"

    def test_rotate_autosave_id_fallback(self, reset_state):
        """Test rotate_autosave_id falls back to Python on transport error."""
        mock = MockTransport(raise_on_call=True)
        old_id = runtime_state._CURRENT_AUTOSAVE_ID = "old_id"

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            result = runtime_state.rotate_autosave_id()

        # Should return a new timestamp-based ID
        assert result != old_id
        assert len(result) == 15

    def test_set_autosave_from_session_name_fallback(self, reset_state):
        """Test set_current_autosave_from_session_name falls back to Python."""
        mock = MockTransport(raise_on_call=True)

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            result = runtime_state.set_current_autosave_from_session_name(
                "auto_session_20250115_120000"
            )

        assert result == "20250115_120000"
        assert runtime_state._CURRENT_AUTOSAVE_ID == "20250115_120000"

    def test_set_autosave_from_session_name_non_standard_fallback(self, reset_state):
        """Test set_current_autosave_from_session_name with non-standard name."""
        mock = MockTransport(raise_on_call=True)

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            result = runtime_state.set_current_autosave_from_session_name(
                "custom_session_name"
            )

        # Should use the whole name as ID when no prefix match
        assert result == "custom_session_name"
        assert runtime_state._CURRENT_AUTOSAVE_ID == "custom_session_name"

    def test_reset_autosave_id_fallback(self, reset_state):
        """Test reset_autosave_id falls back to Python on transport error."""
        mock = MockTransport(raise_on_call=True)
        runtime_state._CURRENT_AUTOSAVE_ID = "some_id"

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            runtime_state.reset_autosave_id()

        assert runtime_state._CURRENT_AUTOSAVE_ID is None

    def test_get_session_model_fallback(self, reset_state):
        """Test get_session_model falls back to Python on transport error."""
        mock = MockTransport(raise_on_call=True)
        runtime_state._SESSION_MODEL = "cached-model"

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            result = runtime_state.get_session_model()

        assert result == "cached-model"

    def test_set_session_model_fallback(self, reset_state):
        """Test set_session_model falls back to Python on transport error."""
        mock = MockTransport(raise_on_call=True)

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            runtime_state.set_session_model("new-model")

        assert runtime_state._SESSION_MODEL == "new-model"

    def test_reset_session_model_fallback(self, reset_state):
        """Test reset_session_model falls back to Python on transport error."""
        mock = MockTransport(raise_on_call=True)
        runtime_state._SESSION_MODEL = "old-model"

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            runtime_state.reset_session_model()

        assert runtime_state._SESSION_MODEL is None

    def test_get_state_fallback(self, reset_state):
        """Test get_state falls back to Python on transport error."""
        mock = MockTransport(raise_on_call=True)
        runtime_state._CURRENT_AUTOSAVE_ID = "test_id"
        runtime_state._SESSION_MODEL = "test_model"

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            result = runtime_state.get_state()

        assert result["autosave_id"] == "test_id"
        assert result["session_model"] == "test_model"
        assert "session_start_time" in result

    def test_is_using_elixir_false(self, reset_state):
        """Test is_using_elixir returns False when transport fails."""
        mock = MockTransport(raise_on_call=True)

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            result = runtime_state.is_using_elixir()

        assert result is False


class TestExistingBehaviorUnchanged:
    """Tests ensuring existing Python-only behavior is unchanged."""

    def test_get_current_autosave_id_creates_if_not_set(self, reset_state):
        """Test that get_current_autosave_id creates a new ID when none exists."""
        assert runtime_state._CURRENT_AUTOSAVE_ID is None

        result = runtime_state.get_current_autosave_id()

        assert result is not None
        assert len(result) == 15  # YYYYMMDD_HHMMSS
        assert result == runtime_state._CURRENT_AUTOSAVE_ID

    def test_get_current_autosave_id_returns_existing(self, reset_state):
        """Test that get_current_autosave_id returns existing ID if set."""
        runtime_state._CURRENT_AUTOSAVE_ID = "existing_id"

        result = runtime_state.get_current_autosave_id()

        assert result == "existing_id"

    def test_rotate_creates_new_id(self, reset_state):
        """Test that rotate_autosave_id creates a different ID."""
        # Set a known ID first to avoid timing issues
        runtime_state._CURRENT_AUTOSAVE_ID = "20250115_120000"
        first = runtime_state.get_current_autosave_id()
        assert first == "20250115_120000"

        # Rotate should create a new ID
        second = runtime_state.rotate_autosave_id()

        # Should be different and follow the timestamp format
        assert first != second
        assert len(second) == 15  # YYYYMMDD_HHMMSS format

    def test_session_model_roundtrip(self, reset_state):
        """Test that session model can be set and retrieved."""
        assert runtime_state.get_session_model() is None

        runtime_state.set_session_model("test-model")
        assert runtime_state.get_session_model() == "test-model"

        runtime_state.set_session_model(None)
        assert runtime_state.get_session_model() is None

    def test_get_state_structure(self, reset_state):
        """Test that get_state returns expected structure."""
        runtime_state._CURRENT_AUTOSAVE_ID = "test_id"
        runtime_state._SESSION_MODEL = "test_model"

        result = runtime_state.get_state()

        assert "autosave_id" in result
        assert "session_model" in result
        assert "session_start_time" in result
        assert result["autosave_id"] == "test_id"
        assert result["session_model"] == "test_model"


class TestIntegration:
    """Integration-style tests for mixed usage patterns."""

    def test_elixir_then_python_maintains_sync(self, reset_state):
        """Test that write operations keep Python cache in sync with Elixir.

        Note: Read operations (get) don't sync cache - they return Elixir
        value directly. Only write operations (rotate, set, reset) update cache.
        """
        mock = MockTransport()

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            # Rotate via Elixir updates the cache
            elixir_id = runtime_state.rotate_autosave_id()
            assert elixir_id == "20250115_120001"
            assert runtime_state._CURRENT_AUTOSAVE_ID == "20250115_120001"

            # If transport fails, fallback uses Python cache
            mock.raise_on_call = True
            fallback_id = runtime_state.get_current_autosave_id()
            # Falls back to Python cache which has the rotated value
            assert fallback_id == "20250115_120001"

    def test_elixir_rotate_updates_cache(self, reset_state):
        """Test that rotate via Elixir updates Python cache."""
        mock = MockTransport()
        runtime_state._CURRENT_AUTOSAVE_ID = "old_id"

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            new_id = runtime_state.rotate_autosave_id()

        # Cache should be updated
        assert runtime_state._CURRENT_AUTOSAVE_ID == new_id
        assert new_id == "20250115_120001"

    def test_elixir_set_session_updates_cache(self, reset_state):
        """Test that set_session_model via Elixir updates Python cache."""
        mock = MockTransport()

        with patch.object(runtime_state, '_get_transport', return_value=mock):
            runtime_state.set_session_model("new-model")

        # Cache should be updated
        assert runtime_state._SESSION_MODEL == "new-model"
