"""Test model factory bridge integration (bd-96).

Tests for ModelFactory integration with the Elixir bridge for config loading.
"""

import json
from unittest.mock import MagicMock, mock_open, patch

import pytest

from code_puppy.model_factory import (
    ModelFactory,
    _call_elixir_model_registry,
    invalidate_model_config_cache,
)


class TestModelFactoryBridgeIntegration:
    """Test ModelFactory bridge integration (bd-96)."""

    @pytest.fixture(autouse=True)
    def invalidate_cache(self):
        """Invalidate model config cache before each test to ensure isolation."""
        invalidate_model_config_cache()

    def test_call_elixir_model_registry_connected(self):
        """Test bridge call when connected."""
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ) as mock_connected:
            with patch(
                "code_puppy.plugins.elixir_bridge.call_method",
                return_value={"configs": {"model1": {"type": "test"}}},
            ) as mock_call:
                result = _call_elixir_model_registry("get_all_configs")

                assert result == {"configs": {"model1": {"type": "test"}}}
                mock_connected.assert_called_once()
                mock_call.assert_called_once_with(
                    "model_registry.get_all_configs", {}, timeout=5.0
                )

    def test_call_elixir_model_registry_not_connected(self):
        """Test bridge call when not connected."""
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=False
        ) as mock_connected:
            result = _call_elixir_model_registry("get_all_configs")

            assert result is None
            mock_connected.assert_called_once()

    def test_call_elixir_model_registry_call_fails(self):
        """Test bridge call when call_method raises an exception."""
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge.call_method",
                side_effect=ConnectionError("Test error"),
            ):
                result = _call_elixir_model_registry("get_all_configs")

                assert result is None

    def test_call_elixir_model_registry_with_params(self):
        """Test bridge call with parameters."""
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge.call_method",
                return_value={"model_name": "test", "config": {"type": "test"}},
            ) as mock_call:
                result = _call_elixir_model_registry(
                    "get_config", {"model_name": "test-model"}
                )

                assert result == {"model_name": "test", "config": {"type": "test"}}
                mock_call.assert_called_once_with(
                    "model_registry.get_config",
                    {"model_name": "test-model"},
                    timeout=5.0,
                )

    @patch("code_puppy.model_factory.callbacks.get_callbacks", return_value=[])
    def test_load_config_uses_bridge_when_available(self, mock_callbacks):
        """Test load_config uses bridge when available."""
        bridge_config = {"bridge-model": {"type": "bridge", "enabled": True}}

        with patch(
            "code_puppy.model_factory._call_elixir_model_registry",
            return_value={"configs": bridge_config},
        ) as mock_bridge:
            with patch("builtins.open", mock_open(read_data="{}")):
                config = ModelFactory.load_config()

                mock_bridge.assert_called_once_with("get_all_configs")
                assert "bridge-model" in config
                assert config["bridge-model"]["type"] == "bridge"

    @patch("code_puppy.model_factory.callbacks.get_callbacks", return_value=[])
    def test_load_config_falls_back_to_file_when_bridge_fails(self, mock_callbacks):
        """Test load_config falls back to file when bridge unavailable."""
        file_config = {"file-model": {"type": "file", "enabled": True}}

        with patch(
            "code_puppy.model_factory._call_elixir_model_registry",
            return_value=None,  # Bridge not available
        ) as mock_bridge:
            with patch("builtins.open", mock_open(read_data=json.dumps(file_config))):
                with patch("pathlib.Path.exists", return_value=False):
                    config = ModelFactory.load_config()

                    mock_bridge.assert_called_once_with("get_all_configs")
                    assert "file-model" in config

    def test_get_config_from_bridge_success(self):
        """Test get_config_from_bridge returns config when available."""
        model_config = {"type": "test", "name": "Test Model"}

        with patch(
            "code_puppy.model_factory._call_elixir_model_registry",
            return_value={"model_name": "test-model", "config": model_config},
        ) as mock_bridge:
            result = ModelFactory.get_config_from_bridge("test-model")

            mock_bridge.assert_called_once_with("get_config", {"model_name": "test-model"})
            assert result == model_config

    def test_get_config_from_bridge_no_config(self):
        """Test get_config_from_bridge returns None when config not found."""
        with patch(
            "code_puppy.model_factory._call_elixir_model_registry",
            return_value={"model_name": "unknown", "config": None},
        ):
            result = ModelFactory.get_config_from_bridge("unknown-model")

            assert result is None

    def test_get_config_from_bridge_bridge_unavailable(self):
        """Test get_config_from_bridge returns None when bridge unavailable."""
        with patch(
            "code_puppy.model_factory._call_elixir_model_registry",
            return_value=None,
        ):
            result = ModelFactory.get_config_from_bridge("test-model")

            assert result is None

    @patch("code_puppy.model_factory.callbacks.get_callbacks", return_value=[])
    def test_get_model_uses_bridge_for_missing_config(self, mock_callbacks):
        """Test get_model uses bridge when config not in local cache."""
        model_config = {"type": "openai", "name": "gpt-4"}

        with patch(
            "code_puppy.model_factory.ModelFactory.get_config_from_bridge",
            return_value=model_config,
        ) as mock_bridge:
            with patch(
                "code_puppy.model_factory._MODEL_BUILDERS",
                {"openai": MagicMock(return_value=MagicMock())},
            ):
                with patch(
                    "code_puppy.model_factory._load_plugin_model_providers"
                ):
                    with pytest.raises(Exception):
                        # get_model will raise ValueError for API key but that's expected
                        # the point is it should try to get config from bridge first
                        ModelFactory.get_model("missing-model", {})

                    mock_bridge.assert_called_once_with("missing-model")
