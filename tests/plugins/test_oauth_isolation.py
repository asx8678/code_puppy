"""Tests for OAuth plugin isolation per ADR-003.

Ensures that ChatGPT and Claude Code OAuth plugins respect pup-ex
isolation guards, and that config_package._default_home() routes
correctly based on runtime mode.

Note: Both OAuth plugins' save_tokens() catch ConfigIsolationViolation
under a broad ``except Exception`` and return False.  Therefore we test
the *observable* behaviour (returns False, file not created) rather than
asserting the exception propagates.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from code_puppy.config_paths import ConfigIsolationViolation, assert_write_allowed, home_dir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_pup_ex(monkeypatch, tmp_path, ex_home_name="pup_ex_home"):
    """Configure environment for pup-ex mode and return the ex-home Path."""
    ex_home = tmp_path / ex_home_name
    ex_home.mkdir()
    monkeypatch.setenv("PUP_EX_HOME", str(ex_home))
    monkeypatch.setenv("PUP_RUNTIME", "elixir")
    return ex_home


def _clear_pup_ex(monkeypatch):
    """Remove pup-ex env vars so is_pup_ex() returns False."""
    monkeypatch.delenv("PUP_EX_HOME", raising=False)
    monkeypatch.delenv("PUP_RUNTIME", raising=False)


# ---------------------------------------------------------------------------
# ChatGPT OAuth
# ---------------------------------------------------------------------------


class TestChatGPTOAuthIsolation:
    """Test chatgpt_oauth save_tokens respects isolation guards."""

    def test_save_tokens_blocked_in_pup_ex_mode(self, tmp_path, monkeypatch):
        """save_tokens() should return False when the resolved token path
        falls outside the pup-ex home (guard blocks the write)."""
        ex_home = _setup_pup_ex(monkeypatch, tmp_path)
        legacy_home = tmp_path / "legacy_home"
        legacy_home.mkdir()
        legacy_token_path = legacy_home / "chatgpt_oauth.json"

        with patch(
            "code_puppy.plugins.chatgpt_oauth.utils.get_token_storage_path",
            return_value=legacy_token_path,
        ):
            from code_puppy.plugins.chatgpt_oauth.utils import save_tokens

            result = save_tokens({"access_token": "test"})
            assert result is False
            # File must NOT have been created at legacy path
            assert not legacy_token_path.exists()

    def test_save_tokens_allowed_in_pup_ex_home(self, tmp_path, monkeypatch):
        """save_tokens() should succeed when the token path is under pup-ex home."""
        ex_home = _setup_pup_ex(monkeypatch, tmp_path)
        ex_home.mkdir(parents=True, exist_ok=True)
        token_path = ex_home / "chatgpt_oauth.json"

        with patch(
            "code_puppy.plugins.chatgpt_oauth.utils.get_token_storage_path",
            return_value=token_path,
        ):
            from code_puppy.plugins.chatgpt_oauth.utils import save_tokens

            result = save_tokens({"access_token": "test_token_123"})
            assert result is True
            assert token_path.exists()
            data = json.loads(token_path.read_text())
            assert data["access_token"] == "test_token_123"

    def test_save_chatgpt_models_blocked_in_pup_ex_mode(self, tmp_path, monkeypatch):
        """save_chatgpt_models() should return False when targeting legacy path."""
        _setup_pup_ex(monkeypatch, tmp_path)
        legacy_home = tmp_path / "legacy_home"
        legacy_home.mkdir()
        legacy_models_path = legacy_home / "chatgpt_models.json"

        with patch(
            "code_puppy.plugins.chatgpt_oauth.utils.get_chatgpt_models_path",
            return_value=legacy_models_path,
        ):
            from code_puppy.plugins.chatgpt_oauth.utils import save_chatgpt_models

            result = save_chatgpt_models({"models": []})
            assert result is False
            assert not legacy_models_path.exists()

    def test_assert_write_allowed_raises_for_legacy_path(self, tmp_path, monkeypatch):
        """Directly verify assert_write_allowed raises ConfigIsolationViolation
        for a legacy-home token path in pup-ex mode."""
        ex_home = _setup_pup_ex(monkeypatch, tmp_path)
        legacy_home = tmp_path / "legacy_home"
        legacy_home.mkdir()
        legacy_token_path = legacy_home / "chatgpt_oauth.json"

        with pytest.raises(ConfigIsolationViolation):
            assert_write_allowed(legacy_token_path, "save_chatgpt_oauth_tokens")


# ---------------------------------------------------------------------------
# Claude Code OAuth
# ---------------------------------------------------------------------------


class TestClaudeCodeOAuthIsolation:
    """Test claude_code_oauth save_tokens respects isolation guards."""

    def test_save_tokens_blocked_in_pup_ex_mode(self, tmp_path, monkeypatch):
        """save_tokens() should return False when targeting legacy home in
        pup-ex mode (guard blocks the write)."""
        _setup_pup_ex(monkeypatch, tmp_path)
        legacy_home = tmp_path / "legacy_home"
        legacy_home.mkdir()
        legacy_token_path = legacy_home / "claude_code_oauth.json"

        with patch(
            "code_puppy.plugins.claude_code_oauth.utils.get_token_storage_path",
            return_value=legacy_token_path,
        ):
            from code_puppy.plugins.claude_code_oauth.utils import save_tokens

            result = save_tokens({"access_token": "test"})
            assert result is False
            assert not legacy_token_path.exists()

    def test_save_tokens_allowed_in_pup_ex_home(self, tmp_path, monkeypatch):
        """save_tokens() should succeed when the token path is under pup-ex home."""
        ex_home = _setup_pup_ex(monkeypatch, tmp_path)
        ex_home.mkdir(parents=True, exist_ok=True)
        token_path = ex_home / "claude_code_oauth.json"

        with patch(
            "code_puppy.plugins.claude_code_oauth.utils.get_token_storage_path",
            return_value=token_path,
        ):
            from code_puppy.plugins.claude_code_oauth.utils import save_tokens

            result = save_tokens({"access_token": "test_claude_token"})
            assert result is True
            assert token_path.exists()
            data = json.loads(token_path.read_text())
            assert data["access_token"] == "test_claude_token"

    def test_save_claude_models_blocked_in_pup_ex_mode(self, tmp_path, monkeypatch):
        """save_claude_models() should return False when targeting legacy path."""
        _setup_pup_ex(monkeypatch, tmp_path)
        legacy_home = tmp_path / "legacy_home"
        legacy_home.mkdir()
        legacy_models_path = legacy_home / "claude_code_models.json"

        with patch(
            "code_puppy.plugins.claude_code_oauth.utils.get_claude_models_path",
            return_value=legacy_models_path,
        ):
            from code_puppy.plugins.claude_code_oauth.utils import save_claude_models

            result = save_claude_models({"models": []})
            assert result is False
            assert not legacy_models_path.exists()

    def test_assert_write_allowed_raises_for_legacy_path(self, tmp_path, monkeypatch):
        """Directly verify assert_write_allowed raises ConfigIsolationViolation
        for a legacy-home token path in pup-ex mode."""
        _setup_pup_ex(monkeypatch, tmp_path)
        legacy_home = tmp_path / "legacy_home"
        legacy_home.mkdir()
        legacy_token_path = legacy_home / "claude_code_oauth.json"

        with pytest.raises(ConfigIsolationViolation):
            assert_write_allowed(legacy_token_path, "save_claude_oauth_tokens")


# ---------------------------------------------------------------------------
# config_package._default_home()
# ---------------------------------------------------------------------------


class TestConfigPackageIsolation:
    """Test config_package._default_home respects pup-ex isolation."""

    def test_default_home_respects_pup_ex(self, tmp_path, monkeypatch):
        """_default_home() should return pup-ex home when in pup-ex mode."""
        ex_home = _setup_pup_ex(monkeypatch, tmp_path)

        from code_puppy.config_package.loader import _default_home

        result = _default_home()
        # Result should contain the pup-ex home path
        assert str(ex_home) in result or result == str(ex_home)

    def test_default_home_standard_mode(self, monkeypatch, tmp_path):
        """_default_home() should return ~/.code_puppy in standard pup mode."""
        _clear_pup_ex(monkeypatch)
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        from code_puppy.config_package.loader import _default_home

        result = _default_home()
        assert ".code_puppy" in result

    def test_default_home_consistent_with_home_dir(self, tmp_path, monkeypatch):
        """_default_home() should return the same as config_paths.home_dir()."""
        ex_home = _setup_pup_ex(monkeypatch, tmp_path)

        from code_puppy.config_package.loader import _default_home

        result = _default_home()
        assert result == str(home_dir())
