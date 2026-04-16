"""Tests for agent_model_pinning module.

Covers the mixed-source pinning bug fix where JSON agents could have stale
config pins that weren't cleared when the JSON model was unpinned.

Test cases:
- get_effective_agent_pinned_model() with JSON and built-in agents
- apply_agent_pinned_model() for pin/unpin with both agent types
- Stale config pin cleanup when working with JSON agents
- JSON model precedence over config pin
"""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from code_puppy.agent_model_pinning import (
    _get_json_agent_path,
    _is_json_agent,
    _load_json_agent_config,
    _save_json_agent_config,
    apply_agent_pinned_model,
    get_effective_agent_pinned_model,
)


# ============================================================================
# Helper tests
# ============================================================================


class TestGetJsonAgentPath:
    """Test _get_json_agent_path helper."""

    @patch("code_puppy.agents.json_agent.discover_json_agents")
    def test_returns_path_for_json_agent(self, mock_discover):
        mock_discover.return_value = {
            "test_agent": "/path/to/test_agent.json",
            "other_agent": "/path/to/other_agent.json",
        }

        result = _get_json_agent_path("test_agent")

        assert result == "/path/to/test_agent.json"

    @patch("code_puppy.agents.json_agent.discover_json_agents")
    def test_returns_none_for_builtin_agent(self, mock_discover):
        mock_discover.return_value = {"test_agent": "/path/to/test_agent.json"}

        result = _get_json_agent_path("builtin_agent")

        assert result is None

    @patch("code_puppy.agents.json_agent.discover_json_agents")
    def test_handles_discovery_error(self, mock_discover):
        mock_discover.side_effect = Exception("Discovery failed")

        result = _get_json_agent_path("test_agent")

        assert result is None


class TestIsJsonAgent:
    """Test _is_json_agent helper."""

    @patch("code_puppy.agents.json_agent.discover_json_agents")
    def test_returns_true_for_json_agent(self, mock_discover):
        mock_discover.return_value = {"test_agent": "/path/to/test_agent.json"}

        result = _is_json_agent("test_agent")

        assert result is True

    @patch("code_puppy.agents.json_agent.discover_json_agents")
    def test_returns_false_for_builtin_agent(self, mock_discover):
        mock_discover.return_value = {"test_agent": "/path/to/test_agent.json"}

        result = _is_json_agent("builtin_agent")

        assert result is False


class TestLoadSaveJsonAgentConfig:
    """Test _load_json_agent_config and _save_json_agent_config helpers."""

    def test_load_valid_config(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"name": "test", "model": "gpt-4"}, f)
            path = f.name

        try:
            cfg = _load_json_agent_config(path)
            assert cfg["name"] == "test"
            assert cfg["model"] == "gpt-4"
        finally:
            os.unlink(path)

    def test_load_missing_file_raises_error(self):
        with pytest.raises(Exception):
            _load_json_agent_config("/nonexistent/file.json")

    def test_save_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "subdir1", "subdir2", "test_agent.json")
            cfg = {"name": "test", "model": "gpt-4"}

            _save_json_agent_config(path, cfg)

            assert os.path.exists(path)
            loaded = _load_json_agent_config(path)
            assert loaded["name"] == "test"
            assert loaded["model"] == "gpt-4"


# ============================================================================
# get_effective_agent_pinned_model tests
# ============================================================================


class TestGetEffectiveAgentPinnedModelJsonAgents:
    """Test get_effective_agent_pinned_model for JSON agents."""

    def test_json_model_takes_precedence_over_config_pin(self):
        """JSON model should take precedence over config pin (THE KEY FIX)."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"name": "migration-analyst", "model": "json-model"}, f)
            json_path = f.name

        try:
            with patch(
                "code_puppy.agents.json_agent.discover_json_agents"
            ) as mock_discover:
                mock_discover.return_value = {"migration-analyst": json_path}

                with patch(
                    "code_puppy.config.get_agent_pinned_model"
                ) as mock_get_pin:
                    mock_get_pin.return_value = "config-model"

                    result = get_effective_agent_pinned_model("migration-analyst")

                    # JSON model should take precedence
                    assert result == "json-model"
        finally:
            os.unlink(json_path)

    def test_fallback_to_config_when_json_has_no_model(self):
        """When JSON has no model, fall back to config pin."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"name": "migration-analyst"}, f)
            json_path = f.name

        try:
            with patch(
                "code_puppy.agents.json_agent.discover_json_agents"
            ) as mock_discover:
                mock_discover.return_value = {"migration-analyst": json_path}

                with patch(
                    "code_puppy.config.get_agent_pinned_model"
                ) as mock_get_pin:
                    mock_get_pin.return_value = "config-model"

                    result = get_effective_agent_pinned_model("migration-analyst")

                    # Should fall back to config
                    assert result == "config-model"
        finally:
            os.unlink(json_path)

    def test_returns_none_when_no_json_model_and_no_config_pin(self):
        """When neither JSON nor config has a model, return None."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"name": "migration-analyst"}, f)
            json_path = f.name

        try:
            with patch(
                "code_puppy.agents.json_agent.discover_json_agents"
            ) as mock_discover:
                mock_discover.return_value = {"migration-analyst": json_path}

                with patch(
                    "code_puppy.config.get_agent_pinned_model"
                ) as mock_get_pin:
                    mock_get_pin.return_value = None

                    result = get_effective_agent_pinned_model("migration-analyst")

                    assert result is None
        finally:
            os.unlink(json_path)


class TestGetEffectiveAgentPinnedModelBuiltinAgents:
    """Test get_effective_agent_pinned_model for built-in agents."""

    @patch("code_puppy.agents.json_agent.discover_json_agents")
    @patch("code_puppy.config.get_agent_pinned_model")
    def test_returns_config_pin_for_builtin_agent(self, mock_get_pin, mock_discover):
        mock_discover.return_value = {}  # No JSON agents
        mock_get_pin.return_value = "gpt-4"

        result = get_effective_agent_pinned_model("code_puppy")

        assert result == "gpt-4"

    @patch("code_puppy.agents.json_agent.discover_json_agents")
    @patch("code_puppy.config.get_agent_pinned_model")
    def test_returns_none_for_unpinned_builtin(self, mock_get_pin, mock_discover):
        mock_discover.return_value = {}
        mock_get_pin.return_value = None

        result = get_effective_agent_pinned_model("code_puppy")

        assert result is None


# ============================================================================
# apply_agent_pinned_model tests - PINNING
# ============================================================================


class TestApplyPinnedModelPinJsonAgents:
    """Test pinning models to JSON agents."""

    def test_pin_json_agent_sets_model_in_json(self):
        """Pinning should set model in JSON file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"name": "migration-analyst"}, f)
            json_path = f.name

        try:
            with patch(
                "code_puppy.agents.json_agent.discover_json_agents"
            ) as mock_discover:
                mock_discover.return_value = {"migration-analyst": json_path}

                result = apply_agent_pinned_model("migration-analyst", "claude-3-opus")

                assert result == "claude-3-opus"

                # Verify JSON file was updated
                with open(json_path, "r") as f:
                    cfg = json.load(f)
                assert cfg["model"] == "claude-3-opus"
        finally:
            os.unlink(json_path)

    def test_pin_json_agent_clears_stale_config_pin(self):
        """Pinning a JSON agent should clear any stale config pin (THE BUG FIX)."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"name": "migration-analyst"}, f)
            json_path = f.name

        try:
            with patch(
                "code_puppy.agents.json_agent.discover_json_agents"
            ) as mock_discover:
                mock_discover.return_value = {"migration-analyst": json_path}

                with patch(
                    "code_puppy.config.clear_agent_pinned_model"
                ) as mock_clear:
                    apply_agent_pinned_model("migration-analyst", "claude-3-opus")

                    # Should clear stale config pin
                    mock_clear.assert_called_once_with("migration-analyst")
        finally:
            os.unlink(json_path)

    def test_pin_updates_existing_json_model(self):
        """Pinning should update existing model in JSON."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"name": "migration-analyst", "model": "old-model"}, f)
            json_path = f.name

        try:
            with patch(
                "code_puppy.agents.json_agent.discover_json_agents"
            ) as mock_discover:
                mock_discover.return_value = {"migration-analyst": json_path}

                apply_agent_pinned_model("migration-analyst", "new-model")

                with open(json_path, "r") as f:
                    cfg = json.load(f)
                assert cfg["model"] == "new-model"
        finally:
            os.unlink(json_path)


class TestApplyPinnedModelPinBuiltinAgents:
    """Test pinning models to built-in agents."""

    @patch("code_puppy.agents.json_agent.discover_json_agents")
    @patch("code_puppy.config.set_agent_pinned_model")
    def test_pin_builtin_agent_uses_config(self, mock_set, mock_discover):
        mock_discover.return_value = {}

        result = apply_agent_pinned_model("code_puppy", "gpt-4")

        assert result == "gpt-4"
        mock_set.assert_called_once_with("code_puppy", "gpt-4")


# ============================================================================
# apply_agent_pinned_model tests - UNPINNING (THE BUG FIX)
# ============================================================================


class TestApplyPinnedModelUnpinJsonAgents:
    """Test unpinning models from JSON agents — the core bug fix."""

    def test_unpin_json_agent_removes_model_from_json(self):
        """Unpinning should remove model from JSON file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"name": "migration-analyst", "model": "claude-3-opus"}, f)
            json_path = f.name

        try:
            with patch(
                "code_puppy.agents.json_agent.discover_json_agents"
            ) as mock_discover:
                mock_discover.return_value = {"migration-analyst": json_path}

                result = apply_agent_pinned_model("migration-analyst", "(unpin)")

                assert result is None

                # Verify model was removed from JSON
                with open(json_path, "r") as f:
                    cfg = json.load(f)
                assert "model" not in cfg
        finally:
            os.unlink(json_path)

    def test_unpin_json_agent_clears_config_pin(self):
        """THE BUG FIX: Unpinning a JSON agent must also clear config pin."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"name": "migration-analyst", "model": "claude-3-opus"}, f)
            json_path = f.name

        try:
            with patch(
                "code_puppy.agents.json_agent.discover_json_agents"
            ) as mock_discover:
                mock_discover.return_value = {"migration-analyst": json_path}

                with patch(
                    "code_puppy.config.clear_agent_pinned_model"
                ) as mock_clear:
                    apply_agent_pinned_model("migration-analyst", "(unpin)")

                    # THE KEY FIX: Must also clear config pin
                    mock_clear.assert_called_once_with("migration-analyst")
        finally:
            os.unlink(json_path)

    def test_unpin_works_when_json_has_no_model(self):
        """Unpinning should be safe when JSON already has no model."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"name": "migration-analyst"}, f)
            json_path = f.name

        try:
            with patch(
                "code_puppy.agents.json_agent.discover_json_agents"
            ) as mock_discover:
                mock_discover.return_value = {"migration-analyst": json_path}

                with patch(
                    "code_puppy.config.clear_agent_pinned_model"
                ) as mock_clear:
                    result = apply_agent_pinned_model(
                        "migration-analyst", "(unpin)"
                    )

                    assert result is None
                    # Should still try to clear config (idempotent)
                    mock_clear.assert_called_once_with("migration-analyst")
        finally:
            os.unlink(json_path)


class TestApplyPinnedModelUnpinBuiltinAgents:
    """Test unpinning models from built-in agents."""

    @patch("code_puppy.agents.json_agent.discover_json_agents")
    @patch("code_puppy.config.clear_agent_pinned_model")
    def test_unpin_builtin_uses_config(self, mock_clear, mock_discover):
        mock_discover.return_value = {}

        result = apply_agent_pinned_model("code_puppy", "(unpin)")

        assert result is None
        mock_clear.assert_called_once_with("code_puppy")


# ============================================================================
# Regression tests for migration-analyst case
# ============================================================================


class TestMigrationAnalystRegression:
    """Regression tests for the migration-analyst unpin bug."""

    def test_migration_analyst_full_scenario(self):
        """Full regression test for the bug scenario:

        1. JSON agent exists with no top-level model key
        2. Config has a stale pin: agent_model_migration-analyst = claude-code-claude-opus-4-6
        3. User unpins via /agents menu
        4. Bug: Only JSON model removed (wasn't there anyway), config pin remains
        5. Fix: Unpin clears BOTH JSON model AND config pin
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            # No model key — the JSON file has no pin
            json.dump({"name": "migration-analyst", "description": "Test"}, f)
            json_path = f.name

        try:
            # Config has the stale pin (simulated via mock)
            with patch(
                "code_puppy.agents.json_agent.discover_json_agents"
            ) as mock_discover:
                mock_discover.return_value = {"migration-analyst": json_path}

                with patch(
                    "code_puppy.config.get_agent_pinned_model"
                ) as mock_get_pin:
                    # Config thinks it has a pin
                    mock_get_pin.return_value = "claude-code-claude-opus-4-6"

                    with patch(
                        "code_puppy.config.clear_agent_pinned_model"
                    ) as mock_clear:
                        # THE FIX: Unpin clears the stale config pin
                        apply_agent_pinned_model("migration-analyst", "(unpin)")
                        mock_clear.assert_called_once_with("migration-analyst")

                # After unpin, reading the pin should return None
                with patch(
                    "code_puppy.config.clear_agent_pinned_model"
                ):
                    with patch(
                        "code_puppy.config.get_agent_pinned_model"
                    ) as mock_get_pin:
                        mock_get_pin.return_value = None

                        result = get_effective_agent_pinned_model(
                            "migration-analyst"
                        )
                        # Now fully unpinned
                        assert result is None
        finally:
            os.unlink(json_path)

    def test_mixed_source_precedence(self):
        """When both JSON and config have pins, JSON should win."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(
                {"name": "migration-analyst", "model": "json-pinned-model"}, f
            )
            json_path = f.name

        try:
            with patch(
                "code_puppy.agents.json_agent.discover_json_agents"
            ) as mock_discover:
                mock_discover.return_value = {"migration-analyst": json_path}

                with patch(
                    "code_puppy.config.get_agent_pinned_model"
                ) as mock_get_pin:
                    mock_get_pin.return_value = "config-pinned-model"

                    # JSON model takes precedence
                    result = get_effective_agent_pinned_model(
                        "migration-analyst"
                    )
                    assert result == "json-pinned-model"
        finally:
            os.unlink(json_path)
