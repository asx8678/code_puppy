"""Consolidated tests for code_puppy.model_factory.

Merged from the former test_model_factory_{basics,coverage,errors,providers}.py
files. Repetitive trivial cases are collapsed via @pytest.mark.parametrize and
exact/near-duplicate tests across files have been removed.
"""

from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

import httpx
import pytest

from code_puppy.model_factory import ModelFactory, get_custom_config

TEST_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../code_puppy/models.json")


@pytest.fixture(scope="session", autouse=True)
def _warm_ssl_context():
    """Build a real OpenAI provider once, in a clean (un-mocked) environment.

    The first lazy initialization of the SSL/HTTP machinery must happen while
    builtins.open / pathlib.Path are real. Several load_config tests mock those
    globally; if the very first provider build lands inside that mock window the
    SSL context is initialized against bogus cert data and stays poisoned for the
    rest of the session. Warming it up here makes the suite order-independent.
    """
    with patch.dict(os.environ, {"OPENAI_API_KEY": "warmup-key"}):
        try:
            ModelFactory.get_model(
                "gpt-4", {"gpt-4": {"type": "openai", "name": "gpt-4"}}
            )
        except Exception:
            pass
    yield


@pytest.fixture(autouse=True)
def _clear_load_config_cache():
    """Drop the memoized load_config() result so tests that mock file I/O don't
    leak a bogus cached config into later tests that build real models."""
    from code_puppy.model_factory import clear_load_config_cache

    clear_load_config_cache()
    yield
    clear_load_config_cache()


# ---------------------------------------------------------------------------
# load_config()
# ---------------------------------------------------------------------------
class TestLoadConfig:
    @patch("code_puppy.model_factory.pathlib.Path.exists", return_value=False)
    @patch("code_puppy.model_factory.callbacks.get_callbacks", return_value=[])
    def test_load_config_basic(self, mock_callbacks, mock_exists):
        test_config = {
            "claude-3-5-sonnet": {
                "type": "anthropic",
                "name": "claude-3-5-sonnet-20241022",
            },
            "gpt-4": {"type": "openai", "name": "gpt-4"},
        }
        with patch("builtins.open", mock_open(read_data=json.dumps(test_config))):
            config = ModelFactory.load_config()
            assert isinstance(config, dict)
            assert config["claude-3-5-sonnet"]["type"] == "anthropic"
            assert "gpt-4" in config

    @patch(
        "code_puppy.plugins.claude_code_oauth.utils.load_claude_models_filtered",
        return_value={},
    )
    @patch("code_puppy.model_factory.pathlib.Path")
    @patch("code_puppy.model_factory.callbacks.get_callbacks", return_value=[])
    def test_load_config_with_extra_models(
        self, mock_callbacks, mock_path_class, mock_load_claude
    ):
        base_config = {
            "claude-3-5-sonnet": {
                "type": "anthropic",
                "name": "claude-3-5-sonnet-20241022",
            }
        }
        extra_config = {
            "custom-model": {"type": "custom_openai", "name": "custom-gpt-4"}
        }

        mock_main_path = MagicMock()
        mock_extra_path = MagicMock()
        mock_other_path = MagicMock()
        mock_main_path.exists.return_value = True
        mock_extra_path.exists.return_value = True
        mock_other_path.exists.return_value = False

        def path_side_effect(path_arg):
            path_str = str(path_arg)
            if "extra_models.json" in path_str:
                return mock_extra_path
            elif (
                "models.json" in path_str
                and "extra" not in path_str
                and "chatgpt" not in path_str
                and "claude" not in path_str
                and "gemini" not in path_str
            ):
                return mock_main_path
            elif any(x in path_str for x in ["chatgpt", "claude", "gemini"]):
                return mock_other_path
            return mock_main_path

        mock_path_class.side_effect = path_side_effect

        with patch("builtins.open", mock_open()) as mock_file:
            mock_file.return_value.read.side_effect = [
                json.dumps(base_config),
                json.dumps(base_config),
            ]
            with patch("json.load", side_effect=[base_config, extra_config]):
                config = ModelFactory.load_config()
        assert "claude-3-5-sonnet" in config
        assert "custom-model" in config

    @patch(
        "code_puppy.plugins.claude_code_oauth.utils.load_claude_models_filtered",
        return_value={},
    )
    @patch("code_puppy.model_factory.pathlib.Path")
    @patch("code_puppy.model_factory.callbacks.get_callbacks", return_value=[])
    def test_load_config_invalid_extra_json(
        self, mock_callbacks, mock_path_class, mock_load_claude
    ):
        base_config = {
            "claude-3-5-sonnet": {
                "type": "anthropic",
                "name": "claude-3-5-sonnet-20241022",
            }
        }
        mock_main_path = MagicMock()
        mock_extra_path = MagicMock()
        mock_other_path = MagicMock()
        mock_main_path.exists.return_value = True
        mock_extra_path.exists.return_value = True
        mock_other_path.exists.return_value = False

        def path_side_effect(path_arg):
            path_str = str(path_arg)
            if "extra_models.json" in path_str:
                return mock_extra_path
            elif (
                "models.json" in path_str
                and "extra" not in path_str
                and "chatgpt" not in path_str
                and "claude" not in path_str
                and "gemini" not in path_str
            ):
                return mock_main_path
            elif any(x in path_str for x in ["chatgpt", "claude", "gemini"]):
                return mock_other_path
            return mock_main_path

        mock_path_class.side_effect = path_side_effect

        with patch("builtins.open", mock_open()) as mock_file:
            mock_file.return_value.read.side_effect = [
                json.dumps(base_config),
                json.dumps(base_config),
            ]
            with patch(
                "json.load",
                side_effect=[
                    base_config,
                    json.JSONDecodeError("Invalid JSON", "doc", 0),
                ],
            ):
                config = ModelFactory.load_config()
                assert "claude-3-5-sonnet" in config

    @patch(
        "code_puppy.model_factory.callbacks.get_callbacks",
        return_value=["test_callback"],
    )
    @patch(
        "code_puppy.model_factory.callbacks.on_load_model_config",
        return_value=[{"test": "config"}],
    )
    @patch(
        "code_puppy.model_factory.callbacks.on_load_models_config",
        return_value=[],
    )
    @patch("builtins.open", new_callable=mock_open, read_data="{}")
    @patch("code_puppy.model_factory.pathlib.Path.exists", return_value=False)
    def test_load_config_with_callbacks(
        self,
        mock_exists,
        mock_file,
        mock_on_load_models,
        mock_on_load,
        mock_get_callbacks,
    ):
        config = ModelFactory.load_config()
        assert config == {"test": "config"}
        mock_get_callbacks.assert_any_call("load_model_config")
        mock_on_load.assert_called_once()

    def test_load_config_multiple_callbacks_warning(self):
        with patch(
            "code_puppy.model_factory.callbacks.get_callbacks",
            return_value=["callback1", "callback2"],
        ):
            with patch(
                "code_puppy.model_factory.callbacks.on_load_model_config",
                return_value=[{"test": "config"}],
            ):
                with patch("logging.getLogger") as mock_logger:
                    ModelFactory.load_config()
                    mock_logger.return_value.warning.assert_called_once()
                    warning_msg = mock_logger.return_value.warning.call_args[0][0]
                    assert "Multiple load_model_config callbacks" in warning_msg

    def test_load_config_filtered_claude_models(self):
        base_config = {"base-model": {"type": "openai", "name": "gpt-4"}}
        filtered_claude_config = {
            "claude-oauth": {"type": "claude_code", "name": "claude-3-opus"}
        }
        with patch("code_puppy.model_factory.callbacks.get_callbacks", return_value=[]):
            with patch(
                "builtins.open",
                MagicMock(
                    return_value=MagicMock(
                        __enter__=MagicMock(
                            return_value=MagicMock(
                                read=MagicMock(
                                    return_value='{"base-model": {"type": "openai", "name": "gpt-4"}}'
                                )
                            )
                        ),
                        __exit__=MagicMock(return_value=False),
                    )
                ),
            ):
                with patch("code_puppy.model_factory.pathlib.Path") as mock_path_class:
                    mock_main = MagicMock()
                    mock_main.__truediv__ = MagicMock(return_value=mock_main)
                    mock_main.exists.return_value = False
                    mock_main.parent = mock_main
                    mock_claude = MagicMock()
                    mock_claude.exists.return_value = True

                    def path_side_effect(arg):
                        if "claude" in str(arg).lower():
                            return mock_claude
                        return mock_main

                    mock_path_class.side_effect = path_side_effect
                    with patch(
                        "code_puppy.plugins.claude_code_oauth.utils.load_claude_models_filtered",
                        return_value=filtered_claude_config,
                    ) as mock_filtered:
                        with patch("json.load", return_value=base_config):
                            ModelFactory.load_config()
                            mock_filtered.assert_called_once()

    def test_load_config_filtered_loading_import_error(self):
        base_config = {"base-model": {"type": "openai", "name": "gpt-4"}}
        plain_claude_config = {"claude-model": {"type": "anthropic", "name": "claude"}}
        with patch("code_puppy.model_factory.callbacks.get_callbacks", return_value=[]):
            with patch("builtins.open", MagicMock()) as mock_open_:
                mock_open_.return_value.__enter__.return_value.read.return_value = (
                    '{"base-model": {"type": "openai"}}'
                )
                with patch("code_puppy.model_factory.pathlib.Path") as mock_path_class:
                    mock_main = MagicMock()
                    mock_main.__truediv__ = MagicMock(return_value=mock_main)
                    mock_main.exists.return_value = False
                    mock_main.parent = mock_main
                    mock_claude = MagicMock()
                    mock_claude.exists.return_value = True

                    def path_side_effect(arg):
                        if "claude" in str(arg).lower():
                            return mock_claude
                        return mock_main

                    mock_path_class.side_effect = path_side_effect
                    with patch.dict(
                        "sys.modules",
                        {"code_puppy.plugins.claude_code_oauth.utils": None},
                    ):
                        with patch(
                            "code_puppy.plugins.claude_code_oauth.utils.load_claude_models_filtered",
                            side_effect=ImportError("Module not found"),
                        ):
                            with patch(
                                "json.load",
                                side_effect=[base_config, plain_claude_config],
                            ):
                                with patch("logging.getLogger"):
                                    config = ModelFactory.load_config()
                                    assert isinstance(config, dict)

    def test_extra_models_json_decode_error(self, tmp_path, monkeypatch):
        extra_models_file = tmp_path / "extra_models.json"
        extra_models_file.write_text("{ invalid json content }")
        monkeypatch.setattr(
            "code_puppy.model_factory.EXTRA_MODELS_FILE", str(extra_models_file)
        )
        config = ModelFactory.load_config()
        assert isinstance(config, dict)
        assert len(config) > 0

    def test_extra_models_exception_handling(self, tmp_path, monkeypatch, caplog):
        extra_models_file = tmp_path / "extra_models.json"
        extra_models_file.mkdir()
        monkeypatch.setattr(
            "code_puppy.model_factory.EXTRA_MODELS_FILE", str(extra_models_file)
        )
        with caplog.at_level("WARNING"):
            config = ModelFactory.load_config()
        assert isinstance(config, dict)
        assert len(config) > 0
        assert "Failed to load extra models config" in caplog.text

    def test_load_config_general_exception_handling(self):
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp.write("not valid json")
            bad_extra = tmp.name
        try:
            with patch("code_puppy.config.EXTRA_MODELS_FILE", bad_extra):
                config = ModelFactory.load_config()
                assert isinstance(config, dict)
                assert len(config) > 0
        finally:
            os.unlink(bad_extra)

    def test_missing_bundled_models_file(self):
        with patch("builtins.open", side_effect=FileNotFoundError("No such file")):
            with pytest.raises(FileNotFoundError):
                ModelFactory.load_config()

    def test_malformed_json_models_file(self):
        with patch("builtins.open", mock_open(read_data="{ invalid json content }")):
            with pytest.raises(json.JSONDecodeError):
                ModelFactory.load_config()

    def test_load_config_file_permission_error(self):
        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            with pytest.raises(PermissionError):
                ModelFactory.load_config()

    def test_config_callback_exception_handling(self):
        with patch(
            "code_puppy.model_factory.callbacks.get_callbacks",
            return_value=[lambda: None],
        ):
            with patch(
                "code_puppy.model_factory.callbacks.on_load_model_config",
                side_effect=Exception("Callback error"),
            ):
                with pytest.raises(Exception, match="Callback error"):
                    ModelFactory.load_config()


# ---------------------------------------------------------------------------
# get_model() — happy paths
# ---------------------------------------------------------------------------
class TestGetModelHappyPaths:
    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_get_model_openai(self):
        config = {"gpt-4": {"type": "openai", "name": "gpt-4"}}
        model = ModelFactory.get_model("gpt-4", config)
        assert model is not None
        assert hasattr(model, "_provider")
        assert model.model_name == "gpt-4"

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    def test_get_model_anthropic(self):
        config = {
            "claude-3-5-sonnet": {
                "type": "anthropic",
                "name": "claude-3-5-sonnet-20241022",
            }
        }
        model = ModelFactory.get_model("claude-3-5-sonnet", config)
        assert model is not None
        assert model.model_name == "claude-3-5-sonnet-20241022"

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    def test_get_model_gemini(self):
        config = {"gemini-pro": {"type": "gemini", "name": "gemini-pro"}}
        model = ModelFactory.get_model("gemini-pro", config)
        assert model is not None
        assert model.model_name == "gemini-pro"
        assert model.system == "google"

    @patch.dict(os.environ, {"ZAI_API_KEY": "test-key"})
    def test_get_model_zai_coding(self):
        config = {"zai-coding": {"type": "zai_coding", "name": "zai-coding-model"}}
        model = ModelFactory.get_model("zai-coding", config)
        assert model is not None
        assert hasattr(model, "_provider")
        assert model.model_name == "zai-coding-model"

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"})
    def test_get_model_openrouter(self):
        config = {
            "openrouter-model": {
                "type": "openrouter",
                "name": "anthropic/claude-3.5-sonnet",
            }
        }
        model = ModelFactory.get_model("openrouter-model", config)
        assert model is not None
        assert hasattr(model, "_provider")
        assert model.model_name == "anthropic/claude-3.5-sonnet"

    def test_get_model_openrouter_config_api_key(self):
        config = {
            "openrouter-model": {
                "type": "openrouter",
                "name": "anthropic/claude-3.5-sonnet",
                "api_key": "config-api-key",
            }
        }
        model = ModelFactory.get_model("openrouter-model", config)
        assert model is not None
        assert model.model_name == "anthropic/claude-3.5-sonnet"

    def test_get_model_openrouter_env_var_api_key(self):
        config = {
            "openrouter-model": {
                "type": "openrouter",
                "name": "anthropic/claude-3.5-sonnet",
                "api_key": "$ROUTER_API_KEY",
            }
        }
        with patch.dict(os.environ, {"ROUTER_API_KEY": "env-api-key"}):
            model = ModelFactory.get_model("openrouter-model", config)
            assert model is not None
            assert model.model_name == "anthropic/claude-3.5-sonnet"

    def test_gemini_load_model(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "dummy-value")
        config = {"gemini": {"type": "gemini", "name": "gemini-pro"}}
        model = ModelFactory.get_model("gemini", config)
        assert model is not None
        assert model.model_name == "gemini-pro"

    def test_ollama_load_model(self):
        config = ModelFactory.load_config()
        if "ollama-llama2" not in config:
            pytest.skip("Model 'ollama-llama2' not found in configuration.")
        model = ModelFactory.get_model("ollama-llama2", config)
        assert hasattr(model, "_provider")
        assert model.model_name == "llama2"
        assert "chat" in dir(model), "OllamaModel must have a .chat method!"

    def test_anthropic_load_model(self):
        config = ModelFactory.load_config()
        if "anthropic-test" not in config:
            pytest.skip("Model 'anthropic-test' not found in configuration.")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set in environment.")
        model = ModelFactory.get_model("anthropic-test", config)
        assert hasattr(model, "_provider")
        assert hasattr(model._provider, "_client")

    def test_model_not_cached(self):
        config = {"gpt-4": {"type": "openai", "name": "gpt-4"}}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            model1 = ModelFactory.get_model("gpt-4", config)
            model2 = ModelFactory.get_model("gpt-4", config)
            assert model1 is not model2
            assert model1.model_name == model2.model_name

    def test_env_var_reference_azure(self, monkeypatch):
        monkeypatch.setenv("AZ_URL", "https://mock-endpoint.openai.azure.com")
        monkeypatch.setenv("AZ_VERSION", "2023-05-15")
        monkeypatch.setenv("AZ_KEY", "supersecretkey")
        config = {
            "azmodel": {
                "type": "azure_openai",
                "name": "az",
                "azure_endpoint": "$AZ_URL",
                "api_version": "$AZ_VERSION",
                "api_key": "$AZ_KEY",
            }
        }
        model = ModelFactory.get_model("azmodel", config)
        assert model.client is not None


# ---------------------------------------------------------------------------
# get_model() — error paths
# ---------------------------------------------------------------------------
class TestGetModelErrors:
    @pytest.mark.parametrize(
        "name",
        ["nonexistent-model", "", None],
    )
    def test_model_not_found(self, name):
        config = {"valid-model": {"type": "openai", "name": "gpt-4"}}
        with pytest.raises(
            ValueError, match=f"Model '{name}' not found in configuration"
        ):
            ModelFactory.get_model(name, config)

    @pytest.mark.parametrize("cfg", [{"bad-model": None}, {"bad-model": {}}])
    def test_invalid_model_config_structure(self, cfg):
        with pytest.raises(
            ValueError, match="Model 'bad-model' not found in configuration"
        ):
            ModelFactory.get_model("bad-model", cfg)

    def test_unsupported_type(self):
        config = {"bad-model": {"type": "unsupported-type", "name": "fake-model"}}
        with pytest.raises(
            ValueError, match="Unsupported model type: unsupported-type"
        ):
            ModelFactory.get_model("bad-model", config)

    @pytest.mark.parametrize(
        "model_type,api_env",
        [
            ("openai", "OPENAI_API_KEY"),
            ("anthropic", "ANTHROPIC_API_KEY"),
        ],
    )
    def test_missing_required_name_field(self, model_type, api_env):
        with patch.dict(os.environ, {api_env: "test-key"}):
            config = {"bad": {"type": model_type}}
            with pytest.raises(KeyError):
                ModelFactory.get_model("bad", config)

    @pytest.mark.parametrize(
        "model_type,name,warn_substr",
        [
            ("openai", "gpt-4", "OPENAI_API_KEY is not set"),
            ("anthropic", "claude-3", "ANTHROPIC_API_KEY is not set"),
            ("gemini", "gemini-pro", "GEMINI_API_KEY is not set"),
            ("zai_coding", "zai-model", "ZAI_API_KEY is not set"),
            ("openrouter", "anthropic/claude-3", "OPENROUTER_API_KEY is not set"),
        ],
    )
    def test_missing_api_key_returns_none(self, model_type, name, warn_substr):
        config = {"m": {"type": model_type, "name": name}}
        with patch("code_puppy.model_factory.get_api_key", return_value=None):
            with patch("code_puppy.model_factory.emit_warning") as mock_warn:
                result = ModelFactory.get_model("m", config)
                assert result is None
                assert warn_substr in mock_warn.call_args[0][0]

    def test_get_model_missing_api_key_emits_warning(self):
        config = {"gpt-4": {"type": "openai", "name": "gpt-4"}}
        with patch("code_puppy.model_factory.get_api_key", return_value=None):
            with patch("code_puppy.model_factory.emit_warning") as mock_warn:
                model = ModelFactory.get_model("gpt-4", config)
                assert model is None
                mock_warn.assert_called_once()


# ---------------------------------------------------------------------------
# custom_openai model
# ---------------------------------------------------------------------------
class TestCustomOpenAI:
    def test_basic(self):
        config = {
            "custom-model": {
                "type": "custom_openai",
                "name": "custom-gpt-4",
                "custom_endpoint": {
                    "url": "https://api.custom.com/v1",
                    "headers": {"Authorization": "Bearer test-key"},
                },
            }
        }
        model = ModelFactory.get_model("custom-model", config)
        assert model is not None
        assert hasattr(model, "_provider")
        assert model.model_name == "custom-gpt-4"
        assert hasattr(model._provider, "base_url")

    def test_env_var_resolution(self):
        config = {
            "custom-model": {
                "type": "custom_openai",
                "name": "custom-gpt-4",
                "custom_endpoint": {
                    "url": "https://api.custom.com/v1",
                    "headers": {"Authorization": "Bearer $CUSTOM_API_KEY"},
                    "api_key": "$CUSTOM_API_KEY",
                },
            }
        }
        with patch.dict(os.environ, {"CUSTOM_API_KEY": "resolved-key"}):
            model = ModelFactory.get_model("custom-model", config)
            assert model is not None
            assert model.model_name == "custom-gpt-4"

    def test_missing_env_var(self):
        config = {
            "custom-model": {
                "type": "custom_openai",
                "name": "custom-gpt-4",
                "custom_endpoint": {
                    "url": "https://api.custom.com/v1",
                    "headers": {"Authorization": "Bearer $MISSING_API_KEY"},
                },
            }
        }
        with patch.dict(os.environ, {}, clear=True):
            with patch("code_puppy.model_factory.emit_warning") as mock_warn:
                model = ModelFactory.get_model("custom-model", config)
                assert model is not None
                mock_warn.assert_called()

    def test_missing_url(self):
        config = {
            "custom-model": {
                "type": "custom_openai",
                "name": "custom-gpt-4",
                "custom_endpoint": {"headers": {"Authorization": "Bearer test-key"}},
            }
        }
        with pytest.raises(ValueError, match="Custom endpoint requires 'url' field"):
            ModelFactory.get_model("custom-model", config)

    def test_missing_custom_endpoint(self):
        config = {"custom-model": {"type": "custom_openai", "name": "custom-gpt-4"}}
        with pytest.raises(
            ValueError, match="Custom model requires 'custom_endpoint' configuration"
        ):
            ModelFactory.get_model("custom-model", config)

    def test_provider_name_uses_resolved_identity(self):
        from code_puppy.provider_identity import AliasedOpenAIProvider

        config = {
            "minimax-openai": {
                "type": "custom_openai",
                "provider": "minimax",
                "name": "minimax-text-01",
                "custom_endpoint": {
                    "url": "https://api.minimax.io/openai/v1",
                    "api_key": "custom-api-key",
                },
            }
        }
        with patch("code_puppy.model_factory.create_async_client"):
            model = ModelFactory.get_model("minimax-openai", config)
        assert isinstance(model._provider, AliasedOpenAIProvider)
        assert model._provider.name == "minimax"


# ---------------------------------------------------------------------------
# Timeout handling
# ---------------------------------------------------------------------------
class TestTimeout:
    @pytest.mark.parametrize(
        "model_type,name,extra_headers",
        [
            ("custom_openai", "cust", {}),
            ("custom_gemini", "gemini", {}),
            (
                "cerebras",
                "cerebras",
                {"X-Cerebras-3rd-Party-Integration": "code-puppy"},
            ),
        ],
    )
    def test_timeout_passed_to_async_client(
        self, monkeypatch, model_type, name, extra_headers
    ):
        monkeypatch.setenv("CUSTOM_API_KEY", "ok")
        monkeypatch.setenv("OPENAI_API_KEY", "ok")
        config = {
            "custom": {
                "type": model_type,
                "name": name,
                "custom_endpoint": {
                    "url": "https://fake.url",
                    "headers": {"X-Api-Key": "$CUSTOM_API_KEY"},
                    "ca_certs_path": False,
                    "api_key": "$CUSTOM_API_KEY",
                },
                "timeout": 600,
            }
        }
        with patch("code_puppy.model_factory.create_async_client") as mock_client:
            mock_client.return_value = httpx.AsyncClient(timeout=600)
            model = ModelFactory.get_model("custom", config)

        expected_headers = {"X-Api-Key": "ok", **extra_headers}
        expected_kwargs = dict(headers=expected_headers, verify=False, timeout=600)
        if model_type == "cerebras":
            expected_kwargs["model_name"] = "cerebras"
        mock_client.assert_called_once_with(**expected_kwargs)
        assert model is not None

    def test_custom_anthropic_timeout(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "ok")
        config = {
            "custom": {
                "type": "custom_anthropic",
                "name": "claude",
                "custom_endpoint": {
                    "url": "https://fake.url",
                    "headers": {"X-Api-Key": "$OPENAI_API_KEY"},
                    "ca_certs_path": False,
                    "api_key": "$OPENAI_API_KEY",
                },
                "timeout": 600,
            }
        }
        with (
            patch("code_puppy.model_factory.ClaudeCacheAsyncClient") as mock_client,
            patch("code_puppy.model_factory.make_anthropic_provider") as mock_provider,
            patch("code_puppy.model_factory.AsyncAnthropic") as mock_anthropic,
            patch("code_puppy.model_factory.get_http2", return_value=False),
        ):
            mock_client.return_value = MagicMock()
            mock_provider.return_value = MagicMock()
            mock_anthropic.return_value = MagicMock()
            model = ModelFactory.get_model("custom", config)
        mock_client.assert_called_once_with(
            headers={"X-Api-Key": "ok"},
            verify=False,
            timeout=600,
            http2=False,
        )
        assert model is not None

    def test_timeout_precedence(self, monkeypatch):
        """Top-level timeout takes precedence over custom_endpoint.timeout."""
        monkeypatch.setenv("OPENAI_API_KEY", "ok")
        config = {
            "custom": {
                "type": "custom_openai",
                "name": "gpt-4",
                "timeout": 300,
                "custom_endpoint": {
                    "url": "https://api.example.com/v1",
                    "api_key": "$OPENAI_API_KEY",
                    "timeout": 600,
                },
            }
        }
        with patch("code_puppy.model_factory.create_async_client") as mock_client:
            mock_client.return_value = httpx.AsyncClient(timeout=300)
            model = ModelFactory.get_model("custom", config)
        mock_client.assert_called_once_with(headers={}, verify=None, timeout=300)
        assert model is not None

    @pytest.mark.parametrize(
        "timeout,match",
        [
            ("abc", "Custom endpoint timeout must be a number"),
            (True, "Custom endpoint timeout must be a number"),
            (0, "Custom endpoint timeout must be greater than zero"),
            (-1, "Custom endpoint timeout must be greater than zero"),
        ],
    )
    def test_invalid_timeout_values(self, timeout, match):
        config = {
            "custom": {
                "type": "custom_openai",
                "name": "gpt-4",
                "custom_endpoint": {
                    "url": "https://api.example.com/v1",
                    "api_key": "$API_KEY",
                    "timeout": timeout,
                },
            }
        }
        with pytest.raises(ValueError, match=match):
            ModelFactory.get_model("custom", config)


# ---------------------------------------------------------------------------
# get_api_key()
# ---------------------------------------------------------------------------
class TestGetApiKey:
    def test_from_config_first(self):
        from code_puppy.model_factory import get_api_key

        with patch("code_puppy.model_factory.get_value", return_value="config-key"):
            with patch.dict(os.environ, {"TEST_API_KEY": "env-key"}):
                assert get_api_key("TEST_API_KEY") == "config-key"

    def test_falls_back_to_env(self):
        from code_puppy.model_factory import get_api_key

        with patch("code_puppy.model_factory.get_value", return_value=None):
            with patch.dict(os.environ, {"TEST_API_KEY": "env-key"}):
                assert get_api_key("TEST_API_KEY") == "env-key"

    def test_returns_none_when_missing(self):
        from code_puppy.model_factory import get_api_key

        with patch("code_puppy.model_factory.get_value", return_value=None):
            with patch.dict(os.environ, {}, clear=True):
                os.environ.pop("MISSING_KEY", None)
                assert get_api_key("MISSING_KEY") is None

    def test_case_insensitive_config_lookup(self):
        from code_puppy.model_factory import get_api_key

        with patch("code_puppy.model_factory.get_value") as mock_get_value:
            mock_get_value.return_value = "config-value"
            result = get_api_key("MY_API_KEY")
            mock_get_value.assert_called_once_with("my_api_key")
            assert result == "config-value"


# ---------------------------------------------------------------------------
# make_model_settings()
# ---------------------------------------------------------------------------
class TestMakeModelSettings:
    def test_returns_dict_with_explicit_max_tokens(self):
        from code_puppy.model_factory import make_model_settings

        settings = make_model_settings("some-model", max_tokens=5000)
        assert isinstance(settings, dict)
        assert settings["max_tokens"] == 5000

    def test_explicit_max_tokens(self):
        from code_puppy.model_factory import make_model_settings

        assert make_model_settings("any-model", max_tokens=1234)["max_tokens"] == 1234

    def test_gpt5_has_reasoning_effort(self):
        from code_puppy.model_factory import make_model_settings

        settings = make_model_settings("gpt-5-test", max_tokens=4096)
        assert "openai_reasoning_effort" in settings

    def test_gpt5_codex_no_verbosity(self):
        from code_puppy.model_factory import make_model_settings

        settings = make_model_settings("gpt-5-codex-test", max_tokens=4096)
        assert settings.get("extra_body") is None

    def test_foundry_gpt5_uses_responses_fields(self):
        from code_puppy.model_factory import make_model_settings

        with patch(
            "code_puppy.model_factory.ModelFactory.load_config",
            return_value={
                "foundry-gpt-5-4": {
                    "type": "azure_foundry_openai",
                    "name": "gpt-5-4",
                    "context_length": 1_000_000,
                }
            },
        ):
            with patch(
                "code_puppy.config.get_openai_reasoning_effort", return_value="medium"
            ):
                with patch(
                    "code_puppy.config.get_openai_reasoning_summary",
                    return_value="auto",
                ):
                    with patch(
                        "code_puppy.config.get_openai_verbosity", return_value="medium"
                    ):
                        settings = make_model_settings(
                            "foundry-gpt-5-4", max_tokens=4096
                        )
        assert settings["openai_reasoning_effort"] == "medium"
        assert settings["openai_reasoning_summary"] == "auto"
        assert settings["openai_text_verbosity"] == "medium"
        assert settings.get("extra_body") is None

    @pytest.mark.parametrize("model_name", ["claude-3-sonnet", "anthropic-claude-opus"])
    def test_claude_has_temperature_and_no_top_p(self, model_name):
        from code_puppy.model_factory import make_model_settings

        settings = make_model_settings(model_name, max_tokens=4096)
        assert settings.get("temperature") == 1.0
        assert "top_p" not in settings

    def test_fallback_context_length(self):
        from code_puppy.model_factory import make_model_settings

        with patch(
            "code_puppy.model_factory.ModelFactory.load_config",
            side_effect=Exception("Config error"),
        ):
            settings = make_model_settings("unknown-model")
            assert settings["max_tokens"] == 19200

    def test_auto_calculation_min_boundary(self):
        from code_puppy.model_factory import make_model_settings

        with patch(
            "code_puppy.model_factory.ModelFactory.load_config",
            return_value={"test-model": {"context_length": 1000}},
        ):
            assert make_model_settings("test-model")["max_tokens"] >= 2048

    def test_large_context_capped(self):
        from code_puppy.model_factory import make_model_settings

        with patch(
            "code_puppy.model_factory.ModelFactory.load_config",
            return_value={"huge-model": {"context_length": 1000000}},
        ):
            assert make_model_settings("huge-model")["max_tokens"] <= 65536

    @pytest.mark.parametrize(
        "yolo,expect_key_present,expect_value",
        [(False, True, False), (True, False, None)],
    )
    def test_parallel_tool_calls_depends_on_yolo(
        self, yolo, expect_key_present, expect_value
    ):
        from code_puppy.model_factory import make_model_settings

        with patch("code_puppy.model_factory.get_yolo_mode", return_value=yolo):
            settings = make_model_settings("gpt-4o", max_tokens=5000)
            if expect_key_present:
                assert settings["parallel_tool_calls"] is expect_value
            else:
                assert "parallel_tool_calls" not in settings


class TestOpus46EffortSetting:
    """The Anthropic API expects effort as output_config; injected via extra_body."""

    @pytest.mark.parametrize("model_name", ["claude-opus-4-6", "claude-4-6-opus"])
    def test_opus_46_gets_effort_in_extra_body(self, model_name):
        from code_puppy.model_factory import make_model_settings

        settings = make_model_settings(model_name, max_tokens=4096)
        extra_body = settings.get("extra_body", {})
        assert "output_config" in extra_body
        assert "effort" in extra_body["output_config"]

    def test_opus_46_effort_default_is_high(self):
        from code_puppy.model_factory import make_model_settings

        settings = make_model_settings("claude-opus-4-6", max_tokens=4096)
        assert settings["extra_body"]["output_config"]["effort"] == "high"

    def test_opus_46_effort_user_override(self):
        from code_puppy.model_factory import make_model_settings

        with patch(
            "code_puppy.config.get_effective_model_settings",
            return_value={"effort": "low", "extended_thinking": "adaptive"},
        ):
            settings = make_model_settings("claude-opus-4-6", max_tokens=4096)
            assert settings["extra_body"]["output_config"]["effort"] == "low"

    @pytest.mark.parametrize(
        "model_name", ["claude-sonnet-4-20250514", "claude-opus-4-5"]
    )
    def test_non_opus_46_does_not_get_effort(self, model_name):
        from code_puppy.model_factory import make_model_settings

        settings = make_model_settings(model_name, max_tokens=4096)
        assert "output_config" not in settings.get("extra_body", {})

    def test_opus_46_thinking_type_is_adaptive_by_default(self):
        from code_puppy.model_factory import make_model_settings

        settings = make_model_settings("claude-opus-4-6", max_tokens=4096)
        assert settings["anthropic_thinking"]["type"] == "adaptive"

    def test_opus_46_effort_not_in_anthropic_thinking(self):
        from code_puppy.model_factory import make_model_settings

        settings = make_model_settings("claude-opus-4-6", max_tokens=4096)
        assert "effort" not in settings.get("anthropic_thinking", {})

    def test_opus_4_7_adaptive_thinking_adds_summary_display(self):
        from code_puppy.model_factory import make_model_settings

        with patch(
            "code_puppy.config.get_effective_model_settings",
            return_value={"extended_thinking": "adaptive"},
        ):
            settings = make_model_settings("claude-opus-4-7", max_tokens=4096)
        assert settings["anthropic_thinking"]["type"] == "adaptive"
        assert settings["anthropic_thinking"]["display"] == "summarized"

    def test_non_opus_4_7_adaptive_thinking_does_not_add_summary_display(self):
        from code_puppy.model_factory import make_model_settings

        with patch(
            "code_puppy.config.get_effective_model_settings",
            return_value={"extended_thinking": "adaptive"},
        ):
            settings = make_model_settings("claude-opus-4-6", max_tokens=4096)
        assert settings["anthropic_thinking"]["type"] == "adaptive"
        assert "display" not in settings["anthropic_thinking"]


# ---------------------------------------------------------------------------
# ZaiChatModel
# ---------------------------------------------------------------------------
class TestZaiChatModel:
    def test_process_response_sets_object(self):
        from code_puppy.model_factory import ZaiChatModel

        mock_response = MagicMock()
        mock_response.object = "some_other_object"
        model = ZaiChatModel(model_name="test-zai", provider=MagicMock())
        with patch.object(
            ZaiChatModel.__bases__[0], "_process_response", return_value=mock_response
        ):
            model._process_response(mock_response)
            assert mock_response.object == "chat.completion"


# ---------------------------------------------------------------------------
# get_custom_config()
# ---------------------------------------------------------------------------
class TestGetCustomConfig:
    @pytest.mark.parametrize(
        "config",
        [
            {},
            {"some_field": "value"},
            {"custom_endpoint": {}},
        ],
    )
    def test_missing_custom_endpoint(self, config):
        with pytest.raises(
            ValueError, match="Custom model requires 'custom_endpoint' configuration"
        ):
            get_custom_config(config)

    @pytest.mark.parametrize(
        "config",
        [
            {"custom_endpoint": {"headers": {}}},
            {"custom_endpoint": {"url": ""}},
        ],
    )
    def test_missing_url(self, config):
        with pytest.raises(ValueError, match="Custom endpoint requires 'url' field"):
            get_custom_config(config)

    def test_env_var_in_header(self):
        config = {
            "custom_endpoint": {
                "url": "https://api.test.com",
                "headers": {"Authorization": "$MY_TOKEN"},
            }
        }
        with patch(
            "code_puppy.model_factory.get_api_key", return_value="resolved-token"
        ):
            _, headers, _, _, _ = get_custom_config(config)
            assert headers["Authorization"] == "resolved-token"

    def test_inline_env_vars_with_spaces(self):
        config = {
            "custom_endpoint": {
                "url": "https://api.test.com",
                "headers": {"Authorization": "Bearer $TOKEN part2 $EXTRA"},
            }
        }

        def mock_get_api_key(key):
            return {"TOKEN": "my-token", "EXTRA": "extra-value"}.get(key)

        with patch(
            "code_puppy.model_factory.get_api_key", side_effect=mock_get_api_key
        ):
            with patch("code_puppy.model_factory.emit_warning"):
                _, headers, _, _, _ = get_custom_config(config)
                assert headers["Authorization"] == "Bearer my-token part2 extra-value"

    def test_inline_env_var_missing(self):
        config = {
            "custom_endpoint": {
                "url": "https://api.test.com",
                "headers": {"Auth": "prefix $MISSING_VAR suffix"},
            }
        }
        with patch("code_puppy.model_factory.get_api_key", return_value=None):
            with patch("code_puppy.model_factory.emit_warning") as mock_warn:
                _, headers, _, _, _ = get_custom_config(config)
                assert headers["Auth"] == "prefix  suffix"
                mock_warn.assert_called()

    def test_api_key_from_env(self):
        config = {
            "custom_endpoint": {
                "url": "https://api.test.com",
                "api_key": "$MY_API_KEY",
            }
        }
        with patch(
            "code_puppy.model_factory.get_api_key", return_value="resolved-api-key"
        ):
            _, _, _, api_key, _ = get_custom_config(config)
            assert api_key == "resolved-api-key"

    def test_api_key_missing_env(self):
        config = {
            "custom_endpoint": {
                "url": "https://api.test.com",
                "api_key": "$MISSING_KEY",
            }
        }
        with patch("code_puppy.model_factory.get_api_key", return_value=None):
            with patch("code_puppy.model_factory.emit_warning") as mock_warn:
                _, _, _, api_key, _ = get_custom_config(config)
                assert api_key is None
                mock_warn.assert_called()

    def test_raw_api_key(self):
        config = {
            "custom_endpoint": {
                "url": "https://api.test.com",
                "api_key": "raw-api-key-value",
            }
        }
        _, _, _, api_key, _ = get_custom_config(config)
        assert api_key == "raw-api-key-value"

    def test_ca_certs_path(self):
        config = {
            "custom_endpoint": {
                "url": "https://api.test.com",
                "ca_certs_path": "/path/to/certs.pem",
            }
        }
        _, _, verify, _, _ = get_custom_config(config)
        assert verify == "/path/to/certs.pem"


# ---------------------------------------------------------------------------
# Provider identity resolution
# ---------------------------------------------------------------------------
class TestProviderIdentityResolution:
    def test_resolve_provider_identity_precedence(self):
        from code_puppy.provider_identity import resolve_provider_identity

        assert (
            resolve_provider_identity(
                "custom-model", {"type": "custom_anthropic", "provider": "minimax"}
            )
            == "minimax"
        )
        assert (
            resolve_provider_identity("whatever", {"type": "claude_code"})
            == "claude_code"
        )
        assert resolve_provider_identity("openrouter-foo", {}) == "openrouter"
        assert resolve_provider_identity("chatgpt-gpt-5", {}) == "chatgpt"
        assert (
            resolve_provider_identity("custom-model", {"type": "custom_openai"})
            == "custom_openai"
        )

    def test_minimax_and_claude_code_differ(self):
        from code_puppy.provider_identity import resolve_provider_identity

        minimax_provider = resolve_provider_identity(
            "minimax-text-01", {"type": "custom_anthropic", "provider": "minimax"}
        )
        claude_code_provider = resolve_provider_identity(
            "claude-code-sonnet", {"type": "claude_code"}
        )
        assert minimax_provider == "minimax"
        assert claude_code_provider == "claude_code"
        assert minimax_provider != claude_code_provider


# ---------------------------------------------------------------------------
# claude_code model type (plugin-based)
# ---------------------------------------------------------------------------
def _claude_code_handler_patch():
    from code_puppy.plugins.claude_code_oauth.register_callbacks import (
        _create_claude_code_model,
    )

    return patch(
        "code_puppy.model_factory.callbacks.on_register_model_types",
        return_value=[{"type": "claude_code", "handler": _create_claude_code_model}],
    )


class TestClaudeCodeModel:
    def test_basic(self):
        config = {
            "claude-code-test": {
                "type": "claude_code",
                "name": "claude-3-opus",
                "custom_endpoint": {
                    "url": "https://api.anthropic.com",
                    "api_key": "test-key",
                },
            }
        }
        with _claude_code_handler_patch():
            with patch("code_puppy.http_utils.get_cert_bundle_path", return_value=None):
                with patch("code_puppy.http_utils.get_http2", return_value=True):
                    with patch("code_puppy.claude_cache_client.ClaudeCacheAsyncClient"):
                        with patch("anthropic.AsyncAnthropic"):
                            with patch(
                                "code_puppy.claude_cache_client.patch_anthropic_client_messages"
                            ):
                                with patch(
                                    "code_puppy.plugins.claude_code_oauth.register_callbacks.make_anthropic_provider"
                                ):
                                    with patch(
                                        "pydantic_ai.models.anthropic.AnthropicModel"
                                    ) as mock_model:
                                        with patch(
                                            "code_puppy.config.get_effective_model_settings",
                                            return_value={"interleaved_thinking": True},
                                        ):
                                            ModelFactory.get_model(
                                                "claude-code-test", config
                                            )
                                            mock_model.assert_called_once()

    def test_provider_name_is_distinct(self):
        from code_puppy.provider_identity import AliasedAnthropicProvider

        config = {
            "claude-code-test": {
                "type": "claude_code",
                "provider": "claude_code",
                "name": "claude-3-opus",
                "custom_endpoint": {
                    "url": "https://api.anthropic.com",
                    "api_key": "test-key",
                },
            }
        }
        created_provider = None

        def fake_model(*, model_name, provider):
            nonlocal created_provider
            created_provider = provider
            return SimpleNamespace(model_name=model_name, provider=provider)

        with _claude_code_handler_patch():
            with patch("code_puppy.http_utils.get_cert_bundle_path", return_value=None):
                with patch("code_puppy.http_utils.get_http2", return_value=True):
                    with patch("code_puppy.claude_cache_client.ClaudeCacheAsyncClient"):
                        with patch("anthropic.AsyncAnthropic"):
                            with patch(
                                "code_puppy.claude_cache_client.patch_anthropic_client_messages"
                            ):
                                with patch(
                                    "pydantic_ai.models.anthropic.AnthropicModel",
                                    side_effect=fake_model,
                                ):
                                    with patch(
                                        "code_puppy.config.get_effective_model_settings",
                                        return_value={"interleaved_thinking": True},
                                    ):
                                        model = ModelFactory.get_model(
                                            "claude-code-test", config
                                        )
        assert isinstance(created_provider, AliasedAnthropicProvider)
        assert created_provider.name == "claude_code"
        assert model.provider.name == "claude_code"

    def test_interleaved_thinking_header_added(self):
        config = {
            "claude-code-test": {
                "type": "claude_code",
                "name": "claude-4-opus",
                "custom_endpoint": {
                    "url": "https://api.anthropic.com",
                    "api_key": "test-key",
                    "headers": {"anthropic-beta": "existing-feature"},
                },
            }
        }
        with _claude_code_handler_patch():
            with patch("code_puppy.http_utils.get_cert_bundle_path", return_value=None):
                with patch("code_puppy.http_utils.get_http2", return_value=True):
                    with patch(
                        "code_puppy.claude_cache_client.ClaudeCacheAsyncClient"
                    ) as mock_client:
                        with patch("anthropic.AsyncAnthropic"):
                            with patch(
                                "code_puppy.claude_cache_client.patch_anthropic_client_messages"
                            ):
                                with patch(
                                    "code_puppy.plugins.claude_code_oauth.register_callbacks.make_anthropic_provider"
                                ):
                                    with patch(
                                        "pydantic_ai.models.anthropic.AnthropicModel"
                                    ):
                                        with patch(
                                            "code_puppy.config.get_effective_model_settings",
                                            return_value={"interleaved_thinking": True},
                                        ):
                                            ModelFactory.get_model(
                                                "claude-code-test", config
                                            )
                                            headers = mock_client.call_args[1][
                                                "headers"
                                            ]
                                            assert (
                                                "interleaved-thinking-2025-05-14"
                                                in headers.get("anthropic-beta", "")
                                            )

    def test_disable_interleaved_thinking_removes_header(self):
        config = {
            "claude-code-test": {
                "type": "claude_code",
                "name": "claude-3-opus",
                "custom_endpoint": {
                    "url": "https://api.anthropic.com",
                    "api_key": "test-key",
                    "headers": {
                        "anthropic-beta": "interleaved-thinking-2025-05-14,other-feature"
                    },
                },
            }
        }
        with _claude_code_handler_patch():
            with patch("code_puppy.http_utils.get_cert_bundle_path", return_value=None):
                with patch("code_puppy.http_utils.get_http2", return_value=True):
                    with patch(
                        "code_puppy.claude_cache_client.ClaudeCacheAsyncClient"
                    ) as mock_client:
                        with patch("anthropic.AsyncAnthropic"):
                            with patch(
                                "code_puppy.claude_cache_client.patch_anthropic_client_messages"
                            ):
                                with patch(
                                    "code_puppy.plugins.claude_code_oauth.register_callbacks.make_anthropic_provider"
                                ):
                                    with patch(
                                        "pydantic_ai.models.anthropic.AnthropicModel"
                                    ):
                                        with patch(
                                            "code_puppy.config.get_all_model_settings",
                                            return_value={
                                                "interleaved_thinking": False
                                            },
                                        ):
                                            ModelFactory.get_model(
                                                "claude-code-test", config
                                            )
                                            headers = mock_client.call_args[1][
                                                "headers"
                                            ]
                                            beta = headers.get("anthropic-beta", "")
                                            assert "interleaved-thinking" not in beta

    def test_oauth_refresh(self):
        config = {
            "claude-oauth": {
                "type": "claude_code",
                "name": "claude-3-opus",
                "oauth_source": "claude-code-plugin",
                "custom_endpoint": {
                    "url": "https://api.anthropic.com",
                    "api_key": "old-token",
                },
            }
        }
        with _claude_code_handler_patch():
            with patch(
                "code_puppy.plugins.claude_code_oauth.register_callbacks.get_valid_access_token",
                return_value="new-refreshed-token",
            ):
                with patch(
                    "code_puppy.http_utils.get_cert_bundle_path", return_value=None
                ):
                    with patch("code_puppy.http_utils.get_http2", return_value=True):
                        with patch(
                            "code_puppy.claude_cache_client.ClaudeCacheAsyncClient"
                        ):
                            with patch("anthropic.AsyncAnthropic") as mock_anthropic:
                                with patch(
                                    "code_puppy.claude_cache_client.patch_anthropic_client_messages"
                                ):
                                    with patch(
                                        "code_puppy.plugins.claude_code_oauth.register_callbacks.make_anthropic_provider"
                                    ):
                                        with patch(
                                            "pydantic_ai.models.anthropic.AnthropicModel"
                                        ):
                                            with patch(
                                                "code_puppy.config.get_effective_model_settings",
                                                return_value={},
                                            ):
                                                ModelFactory.get_model(
                                                    "claude-oauth", config
                                                )
                                                assert (
                                                    mock_anthropic.call_args[1][
                                                        "auth_token"
                                                    ]
                                                    == "new-refreshed-token"
                                                )

    def test_missing_api_key(self):
        config = {
            "claude-code-test": {
                "type": "claude_code",
                "name": "claude-3-opus",
                "custom_endpoint": {"url": "https://api.anthropic.com"},
            }
        }
        with _claude_code_handler_patch():
            with patch(
                "code_puppy.plugins.claude_code_oauth.register_callbacks.emit_warning"
            ) as mock_warn:
                with patch(
                    "code_puppy.config.get_effective_model_settings", return_value={}
                ):
                    model = ModelFactory.get_model("claude-code-test", config)
                    assert model is None
                    mock_warn.assert_called()


# ---------------------------------------------------------------------------
# custom_anthropic model type
# ---------------------------------------------------------------------------
class TestCustomAnthropicModel:
    def test_with_api_key(self):
        config = {
            "custom-claude": {
                "type": "custom_anthropic",
                "name": "claude-3-opus",
                "custom_endpoint": {
                    "url": "https://custom.anthropic.proxy.com",
                    "api_key": "custom-api-key",
                },
            }
        }
        with patch("code_puppy.model_factory.get_cert_bundle_path", return_value=None):
            with patch("code_puppy.model_factory.get_http2", return_value=True):
                with patch("code_puppy.model_factory.ClaudeCacheAsyncClient"):
                    with patch("code_puppy.model_factory.AsyncAnthropic"):
                        with patch(
                            "code_puppy.model_factory.patch_anthropic_client_messages"
                        ):
                            with patch(
                                "code_puppy.model_factory.make_anthropic_provider"
                            ):
                                with patch(
                                    "code_puppy.model_factory.AnthropicModel"
                                ) as mock_model:
                                    with patch(
                                        "code_puppy.config.get_effective_model_settings",
                                        return_value={},
                                    ):
                                        ModelFactory.get_model("custom-claude", config)
                                        mock_model.assert_called_once()
                                        provider_args = mock_model.call_args.kwargs[
                                            "provider"
                                        ]
                                        assert provider_args is not None

    def test_provider_name_uses_resolved_identity(self):
        from code_puppy.provider_identity import AliasedAnthropicProvider

        config = {
            "minimax-claude": {
                "type": "custom_anthropic",
                "provider": "minimax",
                "name": "claude-3-opus",
                "custom_endpoint": {
                    "url": "https://api.minimax.io/anthropic",
                    "api_key": "custom-api-key",
                },
            }
        }
        created_provider = None

        def fake_model(*, model_name, provider):
            nonlocal created_provider
            created_provider = provider
            return SimpleNamespace(model_name=model_name, provider=provider)

        with patch("code_puppy.model_factory.get_cert_bundle_path", return_value=None):
            with patch("code_puppy.model_factory.get_http2", return_value=True):
                with patch("code_puppy.model_factory.ClaudeCacheAsyncClient"):
                    with patch("code_puppy.model_factory.AsyncAnthropic"):
                        with patch(
                            "code_puppy.model_factory.patch_anthropic_client_messages"
                        ):
                            with patch(
                                "code_puppy.model_factory.AnthropicModel",
                                side_effect=fake_model,
                            ):
                                with patch(
                                    "code_puppy.config.get_effective_model_settings",
                                    return_value={},
                                ):
                                    model = ModelFactory.get_model(
                                        "minimax-claude", config
                                    )
        assert isinstance(created_provider, AliasedAnthropicProvider)
        assert created_provider.name == "minimax"
        assert model.provider.name == "minimax"

    def test_interleaved_thinking(self):
        config = {
            "custom-claude": {
                "type": "custom_anthropic",
                "name": "claude-4-opus",
                "custom_endpoint": {
                    "url": "https://custom.anthropic.proxy.com",
                    "api_key": "custom-api-key",
                },
            }
        }
        with patch("code_puppy.model_factory.get_cert_bundle_path", return_value=None):
            with patch("code_puppy.model_factory.get_http2", return_value=True):
                with patch("code_puppy.model_factory.ClaudeCacheAsyncClient"):
                    with patch(
                        "code_puppy.model_factory.AsyncAnthropic"
                    ) as mock_anthropic:
                        with patch(
                            "code_puppy.model_factory.patch_anthropic_client_messages"
                        ):
                            with patch(
                                "code_puppy.model_factory.make_anthropic_provider"
                            ):
                                with patch("code_puppy.model_factory.AnthropicModel"):
                                    with patch(
                                        "code_puppy.config.get_effective_model_settings",
                                        return_value={"interleaved_thinking": True},
                                    ):
                                        ModelFactory.get_model("custom-claude", config)
                                        headers = mock_anthropic.call_args[1].get(
                                            "default_headers", {}
                                        )
                                        assert (
                                            "anthropic-beta" in headers
                                            or headers is None
                                        )

    def test_missing_api_key(self):
        config = {
            "custom-claude": {
                "type": "custom_anthropic",
                "name": "claude-3-opus",
                "custom_endpoint": {"url": "https://custom.anthropic.proxy.com"},
            }
        }
        with patch("code_puppy.model_factory.emit_warning") as mock_warn:
            with patch(
                "code_puppy.config.get_effective_model_settings", return_value={}
            ):
                model = ModelFactory.get_model("custom-claude", config)
                assert model is None
                mock_warn.assert_called()

    def test_missing_url(self):
        config = {
            "x": {
                "type": "custom_anthropic",
                "name": "ya",
                "custom_endpoint": {"headers": {}},
            }
        }
        with pytest.raises(ValueError):
            ModelFactory.get_model("x", config)


# ---------------------------------------------------------------------------
# custom_gemini / cerebras / zai_api
# ---------------------------------------------------------------------------
class TestCustomGeminiModel:
    def test_basic(self):
        config = {
            "custom-gemini": {
                "type": "custom_gemini",
                "name": "gemini-pro",
                "custom_endpoint": {
                    "url": "https://custom.gemini.proxy.com",
                    "api_key": "custom-api-key",
                },
            }
        }
        with patch("code_puppy.model_factory.create_async_client"):
            with patch("code_puppy.model_factory.GeminiModel") as mock_model:
                ModelFactory.get_model("custom-gemini", config)
                mock_model.assert_called_once()

    def test_missing_api_key(self):
        config = {
            "custom-gemini": {
                "type": "custom_gemini",
                "name": "gemini-pro",
                "custom_endpoint": {"url": "https://custom.gemini.proxy.com"},
            }
        }
        with patch("code_puppy.model_factory.emit_warning") as mock_warn:
            model = ModelFactory.get_model("custom-gemini", config)
            assert model is None
            mock_warn.assert_called()


class TestCerebrasModel:
    def test_basic_adds_3rd_party_header(self):
        config = {
            "cerebras-test": {
                "type": "cerebras",
                "name": "llama-3-70b",
                "custom_endpoint": {
                    "url": "https://api.cerebras.ai",
                    "api_key": "cerebras-key",
                },
            }
        }
        with patch(
            "code_puppy.model_factory.create_async_client"
        ) as mock_create_client:
            with patch("code_puppy.model_factory.CerebrasProvider"):
                with patch("code_puppy.model_factory.OpenAIChatModel") as mock_model:
                    ModelFactory.get_model("cerebras-test", config)
                    mock_model.assert_called_once()
                    headers = mock_create_client.call_args[1]["headers"]
                    assert (
                        headers.get("X-Cerebras-3rd-Party-Integration") == "code-puppy"
                    )

    def test_missing_api_key(self):
        config = {
            "cerebras-test": {
                "type": "cerebras",
                "name": "llama-3-70b",
                "custom_endpoint": {"url": "https://api.cerebras.ai"},
            }
        }
        with patch("code_puppy.model_factory.emit_warning") as mock_warn:
            model = ModelFactory.get_model("cerebras-test", config)
            assert model is None
            mock_warn.assert_called()

    def test_no_custom_endpoint_uses_env_key(self):
        config = {"cerebras-direct": {"type": "cerebras", "name": "llama-4-scout-17b"}}
        with patch.dict(os.environ, {"CEREBRAS_API_KEY": "test-key"}):
            with patch(
                "code_puppy.model_factory.create_async_client"
            ) as mock_create_client:
                with patch("code_puppy.model_factory.CerebrasProvider"):
                    with patch(
                        "code_puppy.model_factory.OpenAIChatModel"
                    ) as mock_model:
                        ModelFactory.get_model("cerebras-direct", config)
                        mock_model.assert_called_once()
                        headers = mock_create_client.call_args[1]["headers"]
                        assert (
                            headers.get("X-Cerebras-3rd-Party-Integration")
                            == "code-puppy"
                        )


class TestZaiApiModel:
    def test_basic(self):
        config = {"zai-api-test": {"type": "zai_api", "name": "zai-model"}}
        with patch.dict(os.environ, {"ZAI_API_KEY": "test-zai-key"}):
            with patch(
                "code_puppy.model_factory.make_openai_provider"
            ) as mock_provider:
                model = ModelFactory.get_model("zai-api-test", config)
                assert model is not None
                base_url = mock_provider.call_args[1]["base_url"]
                assert "api.z.ai" in base_url
                assert "paas/v4" in base_url

    def test_missing_api_key(self):
        config = {"zai-api-test": {"type": "zai_api", "name": "zai-model"}}
        with patch("code_puppy.model_factory.get_api_key", return_value=None):
            with patch("code_puppy.model_factory.emit_warning") as mock_warn:
                model = ModelFactory.get_model("zai-api-test", config)
                assert model is None
                assert "ZAI_API_KEY" in mock_warn.call_args[0][0]


# ---------------------------------------------------------------------------
# OpenAI codex models
# ---------------------------------------------------------------------------
class TestOpenAICodexModels:
    def test_codex_uses_responses_model(self):
        config = {"codex-test": {"type": "openai", "name": "gpt-5-codex"}}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            with patch("code_puppy.model_factory.make_openai_provider"):
                with patch(
                    "code_puppy.model_factory.OpenAIResponsesModel"
                ) as mock_responses:
                    with patch("code_puppy.model_factory.OpenAIChatModel"):
                        ModelFactory.get_model("codex-test", config)
                        mock_responses.assert_called_once()

    def test_custom_openai_chatgpt_codex(self):
        config = {
            "chatgpt-gpt-5-codex": {
                "type": "custom_openai",
                "name": "gpt-5-codex",
                "custom_endpoint": {"url": "https://api.openai.com"},
            }
        }
        with patch("code_puppy.model_factory.create_async_client"):
            with patch("code_puppy.model_factory.make_openai_provider"):
                with patch(
                    "code_puppy.model_factory.OpenAIResponsesModel"
                ) as mock_responses:
                    ModelFactory.get_model("chatgpt-gpt-5-codex", config)
                    mock_responses.assert_called_once()


# ---------------------------------------------------------------------------
# Azure OpenAI
# ---------------------------------------------------------------------------
class TestAzureOpenAI:
    @pytest.mark.parametrize(
        "drop_field,match",
        [
            ("azure_endpoint", "Azure OpenAI model type requires 'azure_endpoint'"),
            ("api_version", "Azure OpenAI model type requires 'api_version'"),
            ("api_key", "Azure OpenAI model type requires 'api_key'"),
        ],
    )
    def test_missing_required_config(self, drop_field, match):
        base = {
            "type": "azure_openai",
            "name": "gpt-4",
            "azure_endpoint": "https://test.openai.azure.com",
            "api_version": "2023-05-15",
            "api_key": "key",
        }
        del base[drop_field]
        config = {"azure-bad": base}
        with pytest.raises(ValueError, match=match):
            ModelFactory.get_model("azure-bad", config)

    def test_with_max_retries(self):
        config = {
            "azure-test": {
                "type": "azure_openai",
                "name": "gpt-4",
                "azure_endpoint": "https://test.openai.azure.com",
                "api_version": "2024-02-15-preview",
                "api_key": "azure-key",
                "max_retries": 5,
            }
        }
        with patch("code_puppy.model_factory.AsyncAzureOpenAI") as mock_azure:
            with patch("code_puppy.model_factory.make_openai_provider"):
                with patch("code_puppy.model_factory.OpenAIChatModel"):
                    ModelFactory.get_model("azure-test", config)
                    assert mock_azure.call_args[1]["max_retries"] == 5

    def test_env_var_api_version(self):
        config = {
            "azure-test": {
                "type": "azure_openai",
                "name": "gpt-4",
                "azure_endpoint": "https://test.openai.azure.com",
                "api_version": "$AZURE_API_VERSION",
                "api_key": "azure-key",
            }
        }
        with patch.dict(os.environ, {"AZURE_API_VERSION": "2024-02-15-preview"}):
            with patch("code_puppy.model_factory.AsyncAzureOpenAI") as mock_azure:
                with patch("code_puppy.model_factory.make_openai_provider"):
                    with patch("code_puppy.model_factory.OpenAIChatModel"):
                        ModelFactory.get_model("azure-test", config)
                        assert (
                            mock_azure.call_args[1]["api_version"]
                            == "2024-02-15-preview"
                        )

    def test_missing_env_var_api_version(self):
        config = {
            "azure-test": {
                "type": "azure_openai",
                "name": "gpt-4",
                "azure_endpoint": "https://test.openai.azure.com",
                "api_version": "$MISSING_API_VERSION",
                "api_key": "azure-key",
            }
        }
        with patch("code_puppy.model_factory.get_api_key", return_value=None):
            with patch("code_puppy.model_factory.emit_warning") as mock_warn:
                model = ModelFactory.get_model("azure-test", config)
                assert model is None
                mock_warn.assert_called()


# ---------------------------------------------------------------------------
# round_robin
# ---------------------------------------------------------------------------
class TestRoundRobin:
    def test_with_rotate_every(self):
        config = {
            "model-1": {"type": "openai", "name": "gpt-4"},
            "model-2": {"type": "openai", "name": "gpt-4-turbo"},
            "rr-test": {
                "type": "round_robin",
                "models": ["model-1", "model-2"],
                "rotate_every": 3,
            },
        }
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            with patch("code_puppy.model_factory.RoundRobinModel") as mock_rr:
                ModelFactory.get_model("rr-test", config)
                assert mock_rr.call_args[1]["rotate_every"] == 3

    @pytest.mark.parametrize("models", [None, [], "not-a-list"])
    def test_invalid_models_list(self, models):
        config = {"rr-bad": {"type": "round_robin", "models": models}}
        with pytest.raises(
            ValueError, match="Round-robin model 'rr-bad' requires a 'models' list"
        ):
            ModelFactory.get_model("rr-bad", config)


# ---------------------------------------------------------------------------
# Environment variable resolution failures
# ---------------------------------------------------------------------------
class TestEnvVarResolutionErrors:
    def test_azure_missing_env_var(self):
        config = {
            "azure-env-bad": {
                "type": "azure_openai",
                "name": "gpt-4",
                "azure_endpoint": "$NONEXISTENT_VAR",
                "api_version": "2023-05-15",
                "api_key": "key",
            }
        }
        with patch("code_puppy.model_factory.emit_warning") as mock_warn:
            result = ModelFactory.get_model("azure-env-bad", config)
            assert result is None
            warning_msg = mock_warn.call_args[0][0]
            assert "not found (check config or environment)" in warning_msg
            assert "NONEXISTENT_VAR" in warning_msg

    def test_custom_endpoint_missing_header_env_var(self):
        config = {
            "custom-env-bad": {
                "type": "custom_openai",
                "name": "model",
                "custom_endpoint": {
                    "url": "https://test.com",
                    "headers": {"X-Api-Key": "$NONEXISTENT_KEY"},
                },
            }
        }
        with patch("code_puppy.model_factory.emit_warning") as mock_warn:
            with patch("code_puppy.model_factory.create_async_client") as mock_client:
                mock_client.return_value = None
                ModelFactory.get_model("custom-env-bad", config)
                assert "NONEXISTENT_KEY" in mock_warn.call_args[0][0]


# ---------------------------------------------------------------------------
# gemini_oauth / chatgpt_oauth error paths
# ---------------------------------------------------------------------------
class TestGeminiOAuthErrorPaths:
    def test_plugin_not_available(self):
        config = {"gemini-oauth": {"type": "gemini_oauth", "name": "gemini-pro"}}
        original_modules = {}
        for mod_name in list(sys.modules.keys()):
            if "gemini_oauth" in mod_name:
                original_modules[mod_name] = sys.modules.pop(mod_name)
        try:
            with patch("code_puppy.model_factory.emit_warning") as mock_warn:
                model = ModelFactory.get_model("gemini-oauth", config)
                assert model is None
                mock_warn.assert_called()
        except ImportError:
            pass
        finally:
            sys.modules.update(original_modules)

    @pytest.mark.parametrize(
        "token,project_id",
        [
            (None, "test-project"),
            ("valid-token", None),
        ],
    )
    def test_missing_token_or_project_id(self, token, project_id):
        config = {"gemini-oauth": {"type": "gemini_oauth", "name": "gemini-pro"}}
        mock_utils = MagicMock()
        mock_utils.get_valid_access_token = MagicMock(return_value=token)
        mock_utils.get_project_id = MagicMock(return_value=project_id)
        mock_config = MagicMock()
        mock_config.GEMINI_OAUTH_CONFIG = {
            "api_base_url": "https://test.com",
            "api_version": "v1",
        }
        with patch.dict(
            sys.modules,
            {
                "code_puppy.plugins.gemini_oauth": MagicMock(),
                "code_puppy.plugins.gemini_oauth.utils": mock_utils,
                "code_puppy.plugins.gemini_oauth.config": mock_config,
            },
        ):
            with patch("code_puppy.model_factory.emit_warning") as mock_warn:
                model = ModelFactory.get_model("gemini-oauth", config)
                assert model is None
                mock_warn.assert_called()


class TestChatGPTOAuthErrorPaths:
    def test_plugin_not_available(self):
        config = {"chatgpt-oauth": {"type": "chatgpt_oauth", "name": "gpt-4"}}
        with patch(
            "code_puppy.model_factory.callbacks.on_register_model_types",
            return_value=[],
        ):
            with pytest.raises(
                ValueError, match="Unsupported model type: chatgpt_oauth"
            ):
                ModelFactory.get_model("chatgpt-oauth", config)

    def test_missing_token(self):
        from code_puppy.plugins.chatgpt_oauth.register_callbacks import (
            _create_chatgpt_oauth_model,
        )

        config = {"chatgpt-oauth": {"type": "chatgpt_oauth", "name": "gpt-4"}}
        mock_handlers = [
            {"type": "chatgpt_oauth", "handler": _create_chatgpt_oauth_model}
        ]
        with patch(
            "code_puppy.model_factory.callbacks.on_register_model_types",
            return_value=[mock_handlers],
        ):
            with patch(
                "code_puppy.plugins.chatgpt_oauth.register_callbacks.get_valid_access_token",
                return_value=None,
            ):
                with patch(
                    "code_puppy.plugins.chatgpt_oauth.register_callbacks.emit_warning"
                ) as mock_warn:
                    model = ModelFactory.get_model("chatgpt-oauth", config)
                    assert model is None
                    mock_warn.assert_called()

    def test_missing_account_id(self):
        from code_puppy.plugins.chatgpt_oauth.register_callbacks import (
            _create_chatgpt_oauth_model,
        )

        config = {"chatgpt-oauth": {"type": "chatgpt_oauth", "name": "gpt-4"}}
        mock_handlers = [
            {"type": "chatgpt_oauth", "handler": _create_chatgpt_oauth_model}
        ]
        with patch(
            "code_puppy.model_factory.callbacks.on_register_model_types",
            return_value=[mock_handlers],
        ):
            with patch(
                "code_puppy.plugins.chatgpt_oauth.register_callbacks.get_valid_access_token",
                return_value="valid-token",
            ):
                with patch(
                    "code_puppy.plugins.chatgpt_oauth.register_callbacks.load_stored_tokens",
                    return_value={},
                ):
                    with patch(
                        "code_puppy.plugins.chatgpt_oauth.register_callbacks.emit_warning"
                    ) as mock_warn:
                        model = ModelFactory.get_model("chatgpt-oauth", config)
                        assert model is None
                        mock_warn.assert_called()


# ---------------------------------------------------------------------------
# Anthropic interleaved thinking (direct anthropic type)
# ---------------------------------------------------------------------------
class TestAnthropicInterleaved:
    def test_interleaved_thinking_header(self):
        config = {"claude-test": {"type": "anthropic", "name": "claude-4-opus"}}
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch(
                "code_puppy.model_factory.get_cert_bundle_path", return_value=None
            ):
                with patch("code_puppy.model_factory.get_http2", return_value=True):
                    with patch("code_puppy.model_factory.ClaudeCacheAsyncClient"):
                        with patch(
                            "code_puppy.model_factory.AsyncAnthropic"
                        ) as mock_anthropic:
                            with patch(
                                "code_puppy.model_factory.patch_anthropic_client_messages"
                            ):
                                with patch(
                                    "code_puppy.model_factory.make_anthropic_provider"
                                ):
                                    with patch(
                                        "code_puppy.model_factory.AnthropicModel"
                                    ):
                                        with patch(
                                            "code_puppy.config.get_effective_model_settings",
                                            return_value={"interleaved_thinking": True},
                                        ):
                                            ModelFactory.get_model(
                                                "claude-test", config
                                            )
                                            headers = mock_anthropic.call_args[1].get(
                                                "default_headers"
                                            )
                                            assert headers is not None
                                            assert "anthropic-beta" in headers
                                            assert (
                                                "interleaved-thinking-2025-05-14"
                                                in headers["anthropic-beta"]
                                            )

    def test_no_interleaved_thinking(self):
        config = {"claude-test": {"type": "anthropic", "name": "claude-3-sonnet"}}
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch(
                "code_puppy.model_factory.get_cert_bundle_path", return_value=None
            ):
                with patch("code_puppy.model_factory.get_http2", return_value=True):
                    with patch("code_puppy.model_factory.ClaudeCacheAsyncClient"):
                        with patch(
                            "code_puppy.model_factory.AsyncAnthropic"
                        ) as mock_anthropic:
                            with patch(
                                "code_puppy.model_factory.patch_anthropic_client_messages"
                            ):
                                with patch(
                                    "code_puppy.model_factory.make_anthropic_provider"
                                ):
                                    with patch(
                                        "code_puppy.model_factory.AnthropicModel"
                                    ):
                                        with patch(
                                            "code_puppy.config.get_effective_model_settings",
                                            return_value={
                                                "interleaved_thinking": False
                                            },
                                        ):
                                            ModelFactory.get_model(
                                                "claude-test", config
                                            )
                                            headers = mock_anthropic.call_args[1].get(
                                                "default_headers"
                                            )
                                            assert headers is None

    def test_missing_api_key(self, monkeypatch):
        config = {"anthropic": {"type": "anthropic", "name": "claude-v2"}}
        if "ANTHROPIC_API_KEY" in os.environ:
            monkeypatch.delenv("ANTHROPIC_API_KEY")
        with patch("code_puppy.model_factory.emit_warning") as mock_warn:
            model = ModelFactory.get_model("anthropic", config)
            assert model is None
            mock_warn.assert_called_once()


# ---------------------------------------------------------------------------
# _build_anthropic_beta_header
# ---------------------------------------------------------------------------
class TestContext1MBetaHeader:
    def test_1m_context_adds_beta(self):
        from code_puppy.model_factory import (
            CONTEXT_1M_BETA,
            _build_anthropic_beta_header,
        )

        header = _build_anthropic_beta_header({"context_length": 1_000_000})
        assert header is not None
        assert CONTEXT_1M_BETA in header

    def test_200k_context_no_beta(self):
        from code_puppy.model_factory import _build_anthropic_beta_header

        assert _build_anthropic_beta_header({"context_length": 200_000}) is None

    def test_interleaved_and_1m_combined(self):
        from code_puppy.model_factory import (
            CONTEXT_1M_BETA,
            _build_anthropic_beta_header,
        )

        header = _build_anthropic_beta_header(
            {"context_length": 1_000_000}, interleaved_thinking=True
        )
        assert "interleaved-thinking-2025-05-14" in header
        assert CONTEXT_1M_BETA in header

    def test_interleaved_only_no_1m(self):
        from code_puppy.model_factory import (
            CONTEXT_1M_BETA,
            _build_anthropic_beta_header,
        )

        header = _build_anthropic_beta_header(
            {"context_length": 200_000}, interleaved_thinking=True
        )
        assert "interleaved-thinking-2025-05-14" in header
        assert CONTEXT_1M_BETA not in header

    def test_no_context_length_key(self):
        from code_puppy.model_factory import _build_anthropic_beta_header

        assert _build_anthropic_beta_header({}) is None

    def test_returns_none_when_nothing_needed(self):
        from code_puppy.model_factory import _build_anthropic_beta_header

        assert (
            _build_anthropic_beta_header(
                {"context_length": 100_000}, interleaved_thinking=False
            )
            is None
        )


# ---------------------------------------------------------------------------
# OpenRouter missing env var
# ---------------------------------------------------------------------------
class TestOpenRouterEnvVarMissing:
    def test_env_var_missing(self):
        config = {
            "openrouter-test": {
                "type": "openrouter",
                "name": "anthropic/claude-3",
                "api_key": "$MISSING_OPENROUTER_KEY",
            }
        }
        with patch("code_puppy.model_factory.get_api_key", return_value=None):
            with patch("code_puppy.model_factory.emit_warning") as mock_warn:
                model = ModelFactory.get_model("openrouter-test", config)
                assert model is None
                assert "MISSING_OPENROUTER_KEY" in mock_warn.call_args[0][0]
