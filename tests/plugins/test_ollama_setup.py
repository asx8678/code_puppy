"""Tests for the ollama_setup plugin (code_puppy/plugins/ollama_setup)."""

import json
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def _mock_config(tmp_path):
    """Patch EXTRA_MODELS_FILE to a temp path."""
    extra = tmp_path / "extra_models.json"
    with patch(
        "code_puppy.plugins.ollama_setup.register_callbacks.EXTRA_MODELS_FILE",
        str(extra),
    ):
        yield extra


# ---------------------------------------------------------------------------
# _model_key
# ---------------------------------------------------------------------------


class TestModelKey:
    def test_basic_cloud_tag(self):
        from code_puppy.plugins.ollama_setup.register_callbacks import _model_key

        assert _model_key("glm-5:cloud") == "ollama-glm-5-cloud"

    def test_slash_in_tag(self):
        from code_puppy.plugins.ollama_setup.register_callbacks import _model_key

        assert _model_key("library/model:tag") == "ollama-library-model-tag"


# ---------------------------------------------------------------------------
# _ollama_available
# ---------------------------------------------------------------------------


class TestOllamaAvailable:
    @patch("shutil.which", return_value="/usr/bin/ollama")
    def test_returns_true_when_on_path(self, mock_which):
        from code_puppy.plugins.ollama_setup.register_callbacks import (
            _ollama_available,
        )

        assert _ollama_available() is True

    @patch("shutil.which", return_value=None)
    def test_returns_false_when_missing(self, mock_which):
        from code_puppy.plugins.ollama_setup.register_callbacks import (
            _ollama_available,
        )

        assert _ollama_available() is False


# ---------------------------------------------------------------------------
# _pull_model
# ---------------------------------------------------------------------------


class TestPullModel:
    @patch("code_puppy.plugins.ollama_setup.register_callbacks.emit_info")
    @patch("subprocess.run")
    def test_success(self, mock_run, mock_emit):
        from code_puppy.plugins.ollama_setup.register_callbacks import _pull_model

        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        assert _pull_model("glm-5:cloud") is True

    @patch("code_puppy.plugins.ollama_setup.register_callbacks.emit_info")
    @patch("code_puppy.plugins.ollama_setup.register_callbacks.emit_error")
    @patch("subprocess.run")
    def test_failure(self, mock_run, mock_error, mock_info):
        from code_puppy.plugins.ollama_setup.register_callbacks import _pull_model

        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
        assert _pull_model("bad:model") is False
        mock_error.assert_called_once()

    @patch("code_puppy.plugins.ollama_setup.register_callbacks.emit_info")
    @patch("code_puppy.plugins.ollama_setup.register_callbacks.emit_error")
    @patch("subprocess.run", side_effect=Exception("broken"))
    def test_exception(self, mock_run, mock_error, mock_info):
        from code_puppy.plugins.ollama_setup.register_callbacks import _pull_model

        assert _pull_model("glm-5:cloud") is False
        mock_error.assert_called_once()


# ---------------------------------------------------------------------------
# _register_model
# ---------------------------------------------------------------------------


class TestRegisterModel:
    @patch("code_puppy.plugins.ollama_setup.register_callbacks.emit_success")
    @patch("code_puppy.plugins.ollama_setup.register_callbacks.emit_info")
    def test_creates_new_entry(self, mock_info, mock_success, _mock_config):
        from code_puppy.plugins.ollama_setup.register_callbacks import _register_model

        assert _register_model("glm-5:cloud") is True

        data = json.loads(_mock_config.read_text())
        assert "ollama-glm-5-cloud" in data
        entry = data["ollama-glm-5-cloud"]
        assert entry["type"] == "custom_openai"
        assert entry["context_length"] == 131072

    @patch("code_puppy.plugins.ollama_setup.register_callbacks.emit_success")
    @patch("code_puppy.plugins.ollama_setup.register_callbacks.emit_info")
    def test_updates_existing_entry(self, mock_info, mock_success, _mock_config):
        from code_puppy.plugins.ollama_setup.register_callbacks import _register_model

        _mock_config.write_text(json.dumps({"ollama-glm-5-cloud": {"old": True}}))
        assert _register_model("glm-5:cloud") is True

        data = json.loads(_mock_config.read_text())
        assert "old" not in data["ollama-glm-5-cloud"]
        assert data["ollama-glm-5-cloud"]["type"] == "custom_openai"


# ---------------------------------------------------------------------------
# CLOUD_MODELS catalogue
# ---------------------------------------------------------------------------


class TestCloudModels:
    def test_expected_models_present(self):
        from code_puppy.plugins.ollama_setup.register_callbacks import CLOUD_MODELS

        expected = {
            "kimi-k2.5:cloud",
            "glm-5:cloud",
            "minimax-m2.7:cloud",
            "qwen3.5:cloud",
        }
        assert set(CLOUD_MODELS.keys()) == expected

    def test_all_have_context_length(self):
        from code_puppy.plugins.ollama_setup.register_callbacks import CLOUD_MODELS

        for tag, meta in CLOUD_MODELS.items():
            assert "context_length" in meta, f"{tag} missing context_length"
            assert isinstance(meta["context_length"], int)


# ---------------------------------------------------------------------------
# /ollama-setup command handler
# ---------------------------------------------------------------------------


class TestOllamaSetupCommand:
    def test_returns_none_for_other_commands(self):
        from code_puppy.plugins.ollama_setup.register_callbacks import (
            _handle_ollama_setup,
        )

        result = _handle_ollama_setup("/help", "help")
        assert result is None

    @patch("code_puppy.plugins.ollama_setup.register_callbacks.emit_info")
    def test_no_args_lists_models(self, mock_emit):
        from code_puppy.plugins.ollama_setup.register_callbacks import (
            _handle_ollama_setup,
        )

        result = _handle_ollama_setup("/ollama-setup", "ollama-setup")
        assert result is True
        # Should have printed available models
        combined = " ".join(str(c) for c in mock_emit.call_args_list)
        assert "cloud" in combined.lower()


# ---------------------------------------------------------------------------
# Help callback
# ---------------------------------------------------------------------------


class TestHelpCallback:
    def test_returns_help_tuple(self):
        from code_puppy.plugins.ollama_setup.register_callbacks import _custom_help

        result = _custom_help()
        assert isinstance(result, list)
        assert len(result) >= 1
        name, desc = result[0]
        assert "ollama" in name
