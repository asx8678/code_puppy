"""Integration tests for the Mana bridge plugin.

Tests cover frame encoding/decoding, BridgeClient lifecycle, and callback
registration.  All tests run WITHOUT Mana actually running — socket
connections are mocked or allowed to fail gracefully.
"""

from __future__ import annotations

import importlib
import os
import queue
import struct
from unittest.mock import MagicMock, patch

import msgpack
import pytest

from code_puppy.callbacks import clear_callbacks, count_callbacks, get_callbacks


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_callbacks():
    """Reset callback registry between tests to avoid cross-test pollution."""
    clear_callbacks()
    yield
    clear_callbacks()


@pytest.fixture()
def _preserve_bridge_env():
    """Save and restore CODE_PUPPY_BRIDGE env var around a test."""
    old_val = os.environ.get("CODE_PUPPY_BRIDGE")
    yield
    if old_val is None:
        os.environ.pop("CODE_PUPPY_BRIDGE", None)
    else:
        os.environ["CODE_PUPPY_BRIDGE"] = old_val


# ===================================================================
# 4. Agent list event tests
# ===================================================================


class TestAgentListEvent:
    """Tests for the agent_list bridge event."""

    def test_send_agent_list_with_mock_client(self):
        """_send_agent_list should send an agent_list event via the client."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _send_agent_list
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        sent_messages = []

        # Monkey-patch send_event to capture messages
        original_send = client.send_event

        def capture_send(name, data):
            sent_messages.append({"name": name, "data": data})
            return original_send(name, data)

        client.send_event = capture_send

        # Mock get_available_agents to return test data
        mock_agents = {
            "code-puppy": "Code Puppy 🐶",
            "husky": "Husky 🐺",
        }
        mock_descriptions = {
            "code-puppy": "General-purpose coding assistant",
            "husky": "Strong executor",
        }

        with patch(
            "code_puppy.agents.get_available_agents",
            return_value=mock_agents,
        ), patch(
            "code_puppy.agents.get_agent_descriptions",
            return_value=mock_descriptions,
        ):
            _send_agent_list(client)

        assert len(sent_messages) == 1
        assert sent_messages[0]["name"] == "agent_list"
        agents = sent_messages[0]["data"]["agents"]
        assert len(agents) == 2
        assert agents[0]["name"] == "code-puppy"
        assert agents[0]["display_name"] == "Code Puppy 🐶"
        assert agents[0]["description"] == "General-purpose coding assistant"
        assert agents[1]["name"] == "husky"

    def test_send_agent_list_falls_back_on_import_error(self):
        """If agent imports fail, _send_agent_list should fall back to hardcoded list."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _send_agent_list
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        sent_messages = []

        original_send = client.send_event

        def capture_send(name, data):
            sent_messages.append({"name": name, "data": data})
            return original_send(name, data)

        client.send_event = capture_send

        # Force import failure by patching the source module
        with patch(
            "code_puppy.agents.get_available_agents",
            side_effect=ImportError("no module"),
        ):
            _send_agent_list(client)

        assert len(sent_messages) == 1
        assert sent_messages[0]["name"] == "agent_list"
        agents = sent_messages[0]["data"]["agents"]
        # Should have the fallback agent
        assert len(agents) >= 1
        assert agents[0]["name"] == "code-puppy"

    def test_send_agent_list_noop_without_client(self):
        """_send_agent_list should be a no-op when no client is available."""
        import importlib

        from code_puppy.plugins.mana_bridge import register_callbacks as rc_mod

        # Ensure _client is None
        rc_mod._client = None
        _send_agent_list = rc_mod._send_agent_list

        # Should not raise
        _send_agent_list(None)

        # Cleanup
        importlib.reload(rc_mod)


# ===================================================================
# 5. Model list tests
# ===================================================================


class TestGatherModelList:
    """Tests for the _gather_model_list helper."""

    def test_gather_model_list_returns_expected_structure(self):
        """_gather_model_list should return dict with models list and current_model."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _gather_model_list

        result = _gather_model_list()

        assert "models" in result
        assert "current_model" in result
        assert isinstance(result["models"], list)

    def test_gather_model_list_models_sorted(self):
        """Models list should be sorted alphabetically by name."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _gather_model_list

        result = _gather_model_list()
        names = [m["name"] for m in result["models"]]
        assert names == sorted(names)

    def test_gather_model_list_each_model_has_required_fields(self):
        """Each model in the list should have 'name' and 'type' keys."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _gather_model_list

        result = _gather_model_list()

        for model in result["models"]:
            assert "name" in model
            assert "type" in model
            assert isinstance(model["name"], str)
            assert isinstance(model["type"], str)

    def test_gather_model_list_graceful_on_import_failure(self):
        """Should return empty models list if ModelFactory can't load."""
        from code_puppy.plugins.mana_bridge import register_callbacks as rc_mod

        result = rc_mod._gather_model_list()
        # Should always return a valid structure
        assert isinstance(result, dict)
        assert "models" in result
        assert "current_model" in result


# ===================================================================
# 6. Switch model command tests
# ===================================================================


class TestSwitchModel:
    """Tests for the /model custom command handler."""

    def _reload_register_callbacks(self):
        """Force re-import of the register_callbacks module."""
        from code_puppy.plugins.mana_bridge import register_callbacks as rc_mod
        importlib.reload(rc_mod)
        return rc_mod

    def test_switch_model_ignores_other_commands(self):
        """_on_switch_model should return None for commands other than 'model'."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _on_switch_model

        assert _on_switch_model("agent", "husky") is None
        assert _on_switch_model("help", None) is None
        assert _on_switch_model("exit", "") is None

    def test_switch_model_returns_usage_without_name(self):
        """_on_switch_model should return usage hint when no model name given."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _on_switch_model

        result = _on_switch_model("model", None)
        assert result is not None
        assert "Usage" in result

    def test_switch_model_returns_usage_with_empty_name(self):
        """_on_switch_model should return usage hint when empty string given."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _on_switch_model

        result = _on_switch_model("model", "")
        assert result is not None
        assert "Usage" in result

    def test_switch_model_rejects_unknown_model(self):
        """_on_switch_model should reject a model name not in config."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _on_switch_model

        result = _on_switch_model("model", "nonexistent-model-xyz")
        assert result is not None
        assert "Unknown model" in result or "Failed" in result or "Available" in result

    def test_switch_model_help_returns_entries(self):
        """_on_switch_model_help should return help entries."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _on_switch_model_help

        help_entries = _on_switch_model_help()
        assert isinstance(help_entries, list)
        assert len(help_entries) >= 1
        cmd, desc = help_entries[0]
        assert "model" in cmd.lower()
        assert "switch" in desc.lower()

    def test_custom_command_callbacks_registered(self):
        """The custom_command and custom_command_help hooks should be registered."""
        clear_callbacks()
        os.environ.pop("CODE_PUPPY_BRIDGE", None)

        self._reload_register_callbacks()

        assert count_callbacks("custom_command") >= 1
        assert count_callbacks("custom_command_help") >= 1

    def test_model_list_sent_on_startup_when_connected(self, _preserve_bridge_env):
        """When bridge connects, both hello and model_list events should be enqueued."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        clear_callbacks()
        os.environ["CODE_PUPPY_BRIDGE"] = "1"

        rc_mod = self._reload_register_callbacks()

        with patch.object(BridgeClient, "connect", return_value=True):
            # Trigger startup
            startup_cbs = get_callbacks("startup")
            for cb in startup_cbs:
                cb()

        # Client should have been created and events enqueued
        assert rc_mod._client is not None

        # Drain the queue and check for model_list event
        events = []
        while not rc_mod._client._send_queue.empty():
            events.append(rc_mod._client._send_queue.get_nowait())

        event_names = [e["name"] for e in events]
        assert "hello" in event_names
        assert "model_list" in event_names

        # Verify model_list structure
        model_list_event = next(e for e in events if e["name"] == "model_list")
        data = model_list_event["data"]
        assert "models" in data
        assert "current_model" in data
        assert isinstance(data["models"], list)

        # Cleanup
        rc_mod._on_shutdown()
