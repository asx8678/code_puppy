"""Tests for agent_pinning_transport module (bd-120).

These tests verify the Python wrappers for Elixir agent_pinning RPC methods.
They use mocking and do NOT require the Elixir StdioService to be running.
"""

from unittest.mock import MagicMock, patch
import pytest

# Skip tests if module isn't available
try:
    from code_puppy import agent_pinning_transport as pinning
    MODULE_AVAILABLE = True
except ImportError:
    MODULE_AVAILABLE = False
    pinning = None  # type: ignore

pytestmark = [
    pytest.mark.skipif(not MODULE_AVAILABLE, reason="agent_pinning_transport not available"),
]


@pytest.fixture
def mock_transport():
    """Fixture providing a mock transport for testing."""
    mock = MagicMock()
    mock._send_request = MagicMock()
    return mock


@pytest.fixture
def patched_transport(mock_transport):
    """Fixture that patches _get_transport to return the mock."""
    with patch.object(pinning, "_get_transport", return_value=mock_transport):
        yield mock_transport


class TestGetPinnedModel:
    """Tests for get_pinned_model function."""

    def test_get_returns_model_when_pinned(self, patched_transport):
        """Should return model name when agent has a pin."""
        patched_transport._send_request.return_value = {
            "agent_name": "turbo-executor",
            "model": "claude-sonnet-4",
        }

        result = pinning.get_pinned_model("turbo-executor")

        patched_transport._send_request.assert_called_once_with(
            "agent_pinning.get",
            {"agent_name": "turbo-executor"},
        )
        assert result["agent_name"] == "turbo-executor"
        assert result["model"] == "claude-sonnet-4"

    def test_get_returns_none_when_not_pinned(self, patched_transport):
        """Should return None model when agent has no pin."""
        patched_transport._send_request.return_value = {
            "agent_name": "unknown-agent",
            "model": None,
        }

        result = pinning.get_pinned_model("unknown-agent")

        assert result["agent_name"] == "unknown-agent"
        assert result["model"] is None

    def test_passes_correct_agent_name(self, patched_transport):
        """Should pass the exact agent name to RPC."""
        patched_transport._send_request.return_value = {
            "agent_name": "my-special-agent",
            "model": "gpt-4",
        }

        pinning.get_pinned_model("my-special-agent")

        patched_transport._send_request.assert_called_once_with(
            "agent_pinning.get",
            {"agent_name": "my-special-agent"},
        )


class TestSetPinnedModel:
    """Tests for set_pinned_model function."""

    def test_set_pinned_model_success(self, patched_transport):
        """Should successfully set a model pin."""
        patched_transport._send_request.return_value = {
            "agent_name": "turbo-executor",
            "model": "claude-opus-4",
        }

        result = pinning.set_pinned_model("turbo-executor", "claude-opus-4")

        patched_transport._send_request.assert_called_once_with(
            "agent_pinning.set",
            {"agent_name": "turbo-executor", "model": "claude-opus-4"},
        )
        assert result["agent_name"] == "turbo-executor"
        assert result["model"] == "claude-opus-4"

    def test_set_overwrites_existing_pin(self, patched_transport):
        """Should overwrite existing pin when setting new model."""
        patched_transport._send_request.return_value = {
            "agent_name": "agent-1",
            "model": "new-model",
        }

        result = pinning.set_pinned_model("agent-1", "new-model")

        assert result["model"] == "new-model"
        patched_transport._send_request.assert_called_once_with(
            "agent_pinning.set",
            {"agent_name": "agent-1", "model": "new-model"},
        )

    def test_passes_correct_params(self, patched_transport):
        """Should pass correct agent_name and model params."""
        patched_transport._send_request.return_value = {
            "agent_name": "test-agent",
            "model": "test-model",
        }

        pinning.set_pinned_model("test-agent", "test-model")

        patched_transport._send_request.assert_called_once_with(
            "agent_pinning.set",
            {"agent_name": "test-agent", "model": "test-model"},
        )


class TestClearPinnedModel:
    """Tests for clear_pinned_model function."""

    def test_clear_returns_success(self, patched_transport):
        """Should return cleared=True on successful clear."""
        patched_transport._send_request.return_value = {
            "agent_name": "turbo-executor",
            "cleared": True,
        }

        result = pinning.clear_pinned_model("turbo-executor")

        patched_transport._send_request.assert_called_once_with(
            "agent_pinning.clear",
            {"agent_name": "turbo-executor"},
        )
        assert result["agent_name"] == "turbo-executor"
        assert result["cleared"] is True

    def test_clear_returns_success_even_if_no_pin(self, patched_transport):
        """Should return cleared=True even if agent wasn't pinned."""
        patched_transport._send_request.return_value = {
            "agent_name": "unpinned-agent",
            "cleared": True,
        }

        result = pinning.clear_pinned_model("unpinned-agent")

        assert result["cleared"] is True
        patched_transport._send_request.assert_called_once_with(
            "agent_pinning.clear",
            {"agent_name": "unpinned-agent"},
        )


class TestListPinnedModels:
    """Tests for list_pinned_models function."""

    def test_list_returns_empty_when_no_pins(self, patched_transport):
        """Should return empty list when no agents are pinned."""
        patched_transport._send_request.return_value = {
            "pins": [],
            "count": 0,
        }

        result = pinning.list_pinned_models()

        patched_transport._send_request.assert_called_once_with(
            "agent_pinning.list",
            {},
        )
        assert result["pins"] == []
        assert result["count"] == 0

    def test_list_returns_multiple_pins(self, patched_transport):
        """Should return all pinned agents and their models."""
        patched_transport._send_request.return_value = {
            "pins": [
                {"agent_name": "agent-1", "model": "model-a"},
                {"agent_name": "agent-2", "model": "model-b"},
                {"agent_name": "agent-3", "model": "model-c"},
            ],
            "count": 3,
        }

        result = pinning.list_pinned_models()

        assert len(result["pins"]) == 3
        assert result["count"] == 3
        assert result["pins"][0]["agent_name"] == "agent-1"
        assert result["pins"][0]["model"] == "model-a"
        assert result["pins"][1]["agent_name"] == "agent-2"
        assert result["pins"][1]["model"] == "model-b"

    def test_list_returns_single_pin(self, patched_transport):
        """Should return single pin correctly."""
        patched_transport._send_request.return_value = {
            "pins": [
                {"agent_name": "solo-agent", "model": "solo-model"},
            ],
            "count": 1,
        }

        result = pinning.list_pinned_models()

        assert len(result["pins"]) == 1
        assert result["count"] == 1
        assert result["pins"][0]["agent_name"] == "solo-agent"
        assert result["pins"][0]["model"] == "solo-model"


class TestErrorHandling:
    """Tests for error handling across all functions."""

    def test_get_raises_on_transport_error(self, patched_transport):
        """Should propagate transport errors from get_pinned_model."""
        from code_puppy.elixir_transport import ElixirTransportError
        patched_transport._send_request.side_effect = ElixirTransportError(
            "Connection failed"
        )

        with pytest.raises(ElixirTransportError, match="Connection failed"):
            pinning.get_pinned_model("any-agent")

    def test_set_raises_on_transport_error(self, patched_transport):
        """Should propagate transport errors from set_pinned_model."""
        from code_puppy.elixir_transport import ElixirTransportError
        patched_transport._send_request.side_effect = ElixirTransportError(
            "RPC timeout"
        )

        with pytest.raises(ElixirTransportError, match="RPC timeout"):
            pinning.set_pinned_model("agent", "model")

    def test_clear_raises_on_transport_error(self, patched_transport):
        """Should propagate transport errors from clear_pinned_model."""
        from code_puppy.elixir_transport import ElixirTransportError
        patched_transport._send_request.side_effect = ElixirTransportError(
            "Service unavailable"
        )

        with pytest.raises(ElixirTransportError, match="Service unavailable"):
            pinning.clear_pinned_model("agent")

    def test_list_raises_on_transport_error(self, patched_transport):
        """Should propagate transport errors from list_pinned_models."""
        from code_puppy.elixir_transport import ElixirTransportError
        patched_transport._send_request.side_effect = ElixirTransportError(
            "Backend error"
        )

        with pytest.raises(ElixirTransportError, match="Backend error"):
            pinning.list_pinned_models()


class TestTransportIntegration:
    """Tests verifying the transport integration pattern."""

    def test_get_transport_called_each_time(self):
        """Each function call should invoke _get_transport."""
        with patch.object(pinning, "_get_transport") as mock_get_transport:
            mock_transport = MagicMock()
            mock_transport._send_request.return_value = {"pins": [], "count": 0}
            mock_get_transport.return_value = mock_transport

            pinning.list_pinned_models()
            pinning.list_pinned_models()

            assert mock_get_transport.call_count == 2

    def test_lazy_transport_initialization(self):
        """Transport should be obtained fresh on each call (lazy pattern)."""
        with patch.object(pinning, "_get_transport") as mock_get_transport:
            mock_transport = MagicMock()
            mock_transport._send_request.return_value = {
                "agent_name": "x",
                "model": "y",
            }
            mock_get_transport.return_value = mock_transport

            pinning.get_pinned_model("test-agent")

            mock_get_transport.assert_called_once()
            mock_transport._send_request.assert_called_once()


class TestRpcMethodNames:
    """Tests verifying correct RPC method names are used."""

    def test_get_uses_correct_method(self, patched_transport):
        """Should call agent_pinning.get RPC method."""
        patched_transport._send_request.return_value = {"agent_name": "x", "model": None}

        pinning.get_pinned_model("x")

        call_args = patched_transport._send_request.call_args
        assert call_args[0][0] == "agent_pinning.get"

    def test_set_uses_correct_method(self, patched_transport):
        """Should call agent_pinning.set RPC method."""
        patched_transport._send_request.return_value = {"agent_name": "x", "model": "y"}

        pinning.set_pinned_model("x", "y")

        call_args = patched_transport._send_request.call_args
        assert call_args[0][0] == "agent_pinning.set"

    def test_clear_uses_correct_method(self, patched_transport):
        """Should call agent_pinning.clear RPC method."""
        patched_transport._send_request.return_value = {"agent_name": "x", "cleared": True}

        pinning.clear_pinned_model("x")

        call_args = patched_transport._send_request.call_args
        assert call_args[0][0] == "agent_pinning.clear"

    def test_list_uses_correct_method(self, patched_transport):
        """Should call agent_pinning.list RPC method."""
        patched_transport._send_request.return_value = {"pins": [], "count": 0}

        pinning.list_pinned_models()

        call_args = patched_transport._send_request.call_args
        assert call_args[0][0] == "agent_pinning.list"
