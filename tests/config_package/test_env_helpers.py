"""Tests for typed environment variable helpers.

These tests verify the behavior of get_first_env, env_bool, env_int, and env_path
functions, including multi-name fallback and edge cases.
"""

from pathlib import Path

import pytest

from code_puppy.config_package import env_bool, env_int, env_path, get_first_env


class TestGetFirstEnv:
    """Tests for get_first_env function."""

    def test_first_non_empty_wins(self, monkeypatch):
        """First non-empty value should be returned when multiple vars set."""
        monkeypatch.setenv("VAR_A", "value_a")
        monkeypatch.setenv("VAR_B", "value_b")
        result = get_first_env("VAR_A", "VAR_B")
        assert result == "value_a"

    def test_skips_empty_to_next(self, monkeypatch):
        """Empty strings should be skipped, falling through to next var."""
        monkeypatch.setenv("EMPTY_VAR", "")
        monkeypatch.setenv("SET_VAR", "actual_value")
        result = get_first_env("EMPTY_VAR", "SET_VAR")
        assert result == "actual_value"

    def test_all_empty_returns_none(self, monkeypatch):
        """Should return None when all vars are empty."""
        monkeypatch.setenv("EMPTY_1", "")
        monkeypatch.setenv("EMPTY_2", "")
        result = get_first_env("EMPTY_1", "EMPTY_2")
        assert result is None

    def test_all_unset_returns_none(self):
        """Should return None when no vars are set."""
        result = get_first_env("UNSET_VAR_1", "UNSET_VAR_2")
        assert result is None

    def test_single_arg_case(self, monkeypatch):
        """Should work with a single argument."""
        monkeypatch.setenv("SINGLE_VAR", "single_value")
        result = get_first_env("SINGLE_VAR")
        assert result == "single_value"

    def test_legacy_name_fallback(self, monkeypatch):
        """Legacy name should be used when primary is not set."""
        monkeypatch.setenv("LEGACY_VAR", "legacy_value")
        result = get_first_env("NEW_VAR", "LEGACY_VAR")
        assert result == "legacy_value"

    def test_new_var_wins_over_legacy(self, monkeypatch):
        """New var should win when both are set."""
        monkeypatch.setenv("NEW_VAR", "new_value")
        monkeypatch.setenv("LEGACY_VAR", "legacy_value")
        result = get_first_env("NEW_VAR", "LEGACY_VAR")
        assert result == "new_value"

    def test_whitespace_is_not_empty(self, monkeypatch):
        """Whitespace-only values should NOT be considered empty."""
        monkeypatch.setenv("SPACE_VAR", "   ")
        result = get_first_env("SPACE_VAR")
        assert result == "   "


class TestEnvBool:
    """Tests for env_bool function."""

    @pytest.mark.parametrize(
        "truthy_value",
        ["1", "true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON"],
    )
    def test_truthy_values(self, monkeypatch, truthy_value):
        """Various truthy strings should return True."""
        monkeypatch.setenv("BOOL_VAR", truthy_value)
        result = env_bool("BOOL_VAR", default=False)
        assert result is True

    @pytest.mark.parametrize(
        "falsy_value",
        [
            "0",
            "false",
            "False",
            "FALSE",
            "no",
            "No",
            "NO",
            "off",
            "Off",
            "OFF",
            "maybe",
            "2",
            "random",
        ],
    )
    def test_falsy_values_return_false(self, monkeypatch, falsy_value):
        """Non-truthy strings should return False (not default) - explicit values beat default."""
        monkeypatch.setenv("BOOL_VAR", falsy_value)
        result = env_bool(
            "BOOL_VAR", default=True
        )  # Even with True default, explicit false wins
        assert result is False

    def test_unset_uses_default(self):
        """Should return default when env var is not set."""
        result = env_bool("UNSET_BOOL", default=True)
        assert result is True

    def test_explicit_false_beats_default_true(self, monkeypatch):
        """Explicit '0' should return False, not the True default."""
        monkeypatch.setenv("BOOL_VAR", "0")
        result = env_bool("BOOL_VAR", default=True)
        # Explicit falsy value "0" should be respected, not fall back to default
        assert result is False

    def test_multi_name_fallback_truthy(self, monkeypatch):
        """Should find truthy value in fallback chain."""
        monkeypatch.setenv("BOOL_LEGACY", "yes")
        result = env_bool("BOOL_NEW", "BOOL_LEGACY", default=False)
        assert result is True

    def test_empty_string_uses_default(self, monkeypatch):
        """Empty string falls back to default (same as unset)."""
        monkeypatch.setenv("BOOL_VAR", "")
        result = env_bool("BOOL_VAR", default=False)
        assert result is False


class TestEnvInt:
    """Tests for env_int function."""

    def test_valid_int_parsed(self, monkeypatch):
        """Valid integer string should be parsed correctly."""
        monkeypatch.setenv("INT_VAR", "42")
        result = env_int("INT_VAR", default=0)
        assert result == 42

    def test_negative_int_parsed(self, monkeypatch):
        """Negative integers should be parsed correctly."""
        monkeypatch.setenv("INT_VAR", "-5")
        result = env_int("INT_VAR", default=0)
        assert result == -5

    def test_zero_parsed(self, monkeypatch):
        """Zero should be parsed correctly."""
        monkeypatch.setenv("INT_VAR", "0")
        result = env_int("INT_VAR", default=100)
        assert result == 0

    def test_invalid_int_uses_default(self, monkeypatch):
        """Invalid integer strings should fall back to default."""
        monkeypatch.setenv("INT_VAR", "not_a_number")
        result = env_int("INT_VAR", default=42)
        assert result == 42

    def test_empty_string_uses_default(self, monkeypatch):
        """Empty string should fall back to default."""
        monkeypatch.setenv("INT_VAR", "")
        result = env_int("INT_VAR", default=99)
        assert result == 99

    def test_unset_uses_default(self):
        """Should return default when env var is not set."""
        result = env_int("UNSET_INT", default=7)
        assert result == 7

    def test_multi_name_fallback(self, monkeypatch):
        """Should find and parse int in fallback chain."""
        monkeypatch.setenv("INT_LEGACY", "123")
        result = env_int("INT_NEW", "INT_LEGACY", default=0)
        assert result == 123

    def test_invalid_int_uses_default_not_next_name(self, monkeypatch):
        """Invalid int from first name uses default, doesn't fall through to next name.

        This is by design - get_first_env returns the first non-empty string,
        and if that string is invalid for int parsing, we use default rather
        than trying other names. This prevents silent misconfigurations.
        """
        monkeypatch.setenv("INT_FIRST", "invalid")
        monkeypatch.setenv("INT_SECOND", "456")
        # "invalid" is a non-empty value from INT_FIRST, so we try to parse it
        # and fall back to default since it's not a valid int
        result = env_int("INT_FIRST", "INT_SECOND", default=999)
        assert result == 999

    def test_float_string_uses_default(self, monkeypatch):
        """Float strings (with decimal) should fall back to default."""
        monkeypatch.setenv("INT_VAR", "3.14")
        result = env_int("INT_VAR", default=0)
        assert result == 0


class TestEnvPath:
    """Tests for env_path function."""

    def test_returns_path_object(self, monkeypatch, tmp_path):
        """Should return a Path object."""
        existing_path = tmp_path / "test_dir"
        existing_path.mkdir()
        monkeypatch.setenv("PATH_VAR", str(existing_path))
        result = env_path("PATH_VAR", default="/tmp/default")
        assert isinstance(result, Path)

    def test_expands_tilde(self, monkeypatch):
        """Should expand ~ to home directory."""
        monkeypatch.setenv("PATH_VAR", "~/test_subdir")
        result = env_path("PATH_VAR", default="/tmp/default")
        assert "~" not in str(result)
        assert result.is_absolute()

    def test_resolves_relative_paths(self, monkeypatch, tmp_path):
        """Should resolve relative paths to absolute."""
        existing_path = tmp_path / "relative_test"
        existing_path.mkdir()
        monkeypatch.setenv("PATH_VAR", str(existing_path))
        result = env_path("PATH_VAR", default="/tmp/default")
        assert result.is_absolute()
        assert result.exists()

    def test_default_as_string(self):
        """Should work with string default."""
        result = env_path("UNSET_PATH", default="/tmp/test_default")
        assert isinstance(result, Path)
        assert result.is_absolute()

    def test_default_as_path(self):
        """Should work with Path default."""
        result = env_path("UNSET_PATH", default=Path("/tmp/test_default"))
        assert isinstance(result, Path)
        assert result.is_absolute()

    def test_multi_name_fallback(self, monkeypatch, tmp_path):
        """Should find path in fallback chain."""
        existing_path = tmp_path / "legacy_dir"
        existing_path.mkdir()
        monkeypatch.setenv("PATH_LEGACY", str(existing_path))
        result = env_path("PATH_NEW", "PATH_LEGACY", default="/tmp/default")
        assert result.exists()
        assert result.name == "legacy_dir"

    def test_default_with_tilde_expansion(self):
        """Default with ~ should be expanded."""
        result = env_path("UNSET_PATH", default="~/.code_puppy")
        assert "~" not in str(result)
        assert result.is_absolute()

    def test_env_var_with_tilde(self, monkeypatch):
        """Env var with ~ should be expanded."""
        monkeypatch.setenv("PATH_VAR", "~/.test_config")
        result = env_path("PATH_VAR", default="/tmp/default")
        assert "~" not in str(result)
        assert ".test_config" in str(result)


class TestLegacyNameFallback:
    """Comprehensive tests for the legacy name fallback pattern."""

    def test_first_wins_over_second(self, monkeypatch):
        """When both legacy and new vars set, first (new) should win."""
        monkeypatch.setenv("PUPPY_DEBUG", "true")
        monkeypatch.setenv("CODE_PUPPY_DEBUG", "false")
        # PUPPY_DEBUG is checked first, so it should win
        result = env_bool("PUPPY_DEBUG", "CODE_PUPPY_DEBUG", default=False)
        assert result is True

    def test_only_second_set_uses_second(self, monkeypatch):
        """When only legacy (second) var set, it should be used."""
        monkeypatch.delenv("PUPPY_DEBUG", raising=False)
        monkeypatch.setenv("CODE_PUPPY_DEBUG", "true")
        result = env_bool("PUPPY_DEBUG", "CODE_PUPPY_DEBUG", default=False)
        assert result is True

    def test_three_name_chain(self, monkeypatch):
        """Should work with three names in the chain."""
        monkeypatch.setenv("V3", "value_v3")
        result = get_first_env("V1", "V2", "V3")
        assert result == "value_v3"

    def test_empty_in_middle_skipped(self, monkeypatch):
        """Empty values in the middle should be skipped."""
        monkeypatch.setenv("FIRST", "")
        monkeypatch.setenv("MIDDLE", "")
        monkeypatch.setenv("LAST", "actual")
        result = get_first_env("FIRST", "MIDDLE", "LAST")
        assert result == "actual"


class TestEdgeCases:
    """Edge case and boundary tests."""

    def test_whitespace_trimmed_for_bool(self, monkeypatch):
        """Whitespace should be trimmed for bool parsing."""
        monkeypatch.setenv("BOOL_VAR", "  true  ")
        result = env_bool("BOOL_VAR", default=False)
        assert result is True

    def test_whitespace_trimmed_for_int(self, monkeypatch):
        """Whitespace should be trimmed for int parsing."""
        monkeypatch.setenv("INT_VAR", "  42  ")
        result = env_int("INT_VAR", default=0)
        assert result == 42

    def test_whitespace_preserved_in_get_first_env(self, monkeypatch):
        """Whitespace should be preserved in get_first_env."""
        monkeypatch.setenv("VAR", "  value  ")
        result = get_first_env("VAR")
        assert result == "  value  "

    def test_env_path_with_whitespace(self, monkeypatch, tmp_path):
        """Whitespace in path should be handled correctly."""
        path_with_space = tmp_path / "path with spaces"
        path_with_space.mkdir()
        monkeypatch.setenv("PATH_VAR", str(path_with_space))
        result = env_path("PATH_VAR", default="/tmp/default")
        assert result.exists()
        assert " " in str(result)
