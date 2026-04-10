"""Tests for config resolvers.

These tests verify the pure resolver functions that extract configuration
values from environment variables, legacy config, and defaults.
"""

import pytest
from pathlib import Path

from code_puppy.config_package._resolvers import (
    resolve_str,
    resolve_bool,
    resolve_int,
    resolve_float,
    resolve_path,
)


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────


@pytest.fixture
def dummy_legacy_config():
    """Return a dummy legacy config object."""
    class DummyConfig:
        def get_value(self, key):
            values = {
                "test_key": "legacy_value",
                "test_bool": "true",
                "test_int": "42",
                "test_float": "3.14",
            }
            return values.get(key)

    return DummyConfig()


@pytest.fixture
def resolver_ctx(dummy_legacy_config):
    """Return a resolver context with legacy config."""
    def _get_legacy_value(legacy_config, key, default=None):
        if hasattr(legacy_config, "get_value"):
            return legacy_config.get_value(key) or default
        return default

    return {
        "_legacy_ok": True,
        "_legacy_config": dummy_legacy_config,
        "_get_legacy_value": _get_legacy_value,
    }


@pytest.fixture
def no_legacy_ctx():
    """Return a resolver context without legacy config."""
    return {
        "_legacy_ok": False,
        "_legacy_config": None,
        "_get_legacy_value": lambda lc, key, default=None: default,
    }


# ─────────────────────────────────────────────────────────────
# resolve_str Tests
# ─────────────────────────────────────────────────────────────


class TestResolveStr:
    """Tests for resolve_str function."""

    def test_env_var_wins_over_legacy(self, monkeypatch, resolver_ctx):
        """Environment variable should take precedence over legacy config."""
        monkeypatch.setenv("TEST_VAR", "env_value")
        result = resolve_str(
            ("TEST_VAR",),
            "test_key",
            "default_value",
            **resolver_ctx,
        )
        assert result == "env_value"

    def test_legacy_used_when_env_unset(self, resolver_ctx):
        """Legacy config should be used when env var is not set."""
        result = resolve_str(
            ("UNSET_VAR",),
            "test_key",
            "default_value",
            **resolver_ctx,
        )
        assert result == "legacy_value"

    def test_default_used_when_nothing_set(self, no_legacy_ctx):
        """Default should be used when neither env nor legacy has value."""
        result = resolve_str(
            ("UNSET_VAR",),
            "unset_key",
            "default_value",
            **no_legacy_ctx,
        )
        assert result == "default_value"

    def test_legacy_fallback_names(self, monkeypatch, resolver_ctx):
        """Fallback legacy keys should be tried if primary fails."""
        monkeypatch.setenv("TEST_VAR", "env_value")
        result = resolve_str(
            ("UNSET_VAR",),
            "primary_key",
            "default_value",
            legacy_fallback_names=("fallback_key", "test_key"),
            **resolver_ctx,
        )
        # Should use env since it's set, but let's test fallback
        monkeypatch.delenv("TEST_VAR", raising=False)
        result = resolve_str(
            ("UNSET_VAR",),
            "primary_key",
            "default_value",
            legacy_fallback_names=("fallback_key", "test_key"),
            **resolver_ctx,
        )
        assert result == "legacy_value"  # From test_key fallback

    def test_multi_env_names_first_wins(self, monkeypatch, no_legacy_ctx):
        """First set env var in tuple should win."""
        monkeypatch.setenv("SECOND_VAR", "second_value")
        result = resolve_str(
            ("FIRST_VAR", "SECOND_VAR"),
            "legacy_key",
            "default",
            **no_legacy_ctx,
        )
        assert result == "second_value"

        monkeypatch.setenv("FIRST_VAR", "first_value")
        result = resolve_str(
            ("FIRST_VAR", "SECOND_VAR"),
            "legacy_key",
            "default",
            **no_legacy_ctx,
        )
        assert result == "first_value"


# ─────────────────────────────────────────────────────────────
# resolve_bool Tests
# ─────────────────────────────────────────────────────────────


class TestResolveBool:
    """Tests for resolve_bool function."""

    @pytest.mark.parametrize("truthy", ["1", "true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON"])
    def test_env_truthy_values(self, monkeypatch, no_legacy_ctx, truthy):
        """Various truthy env strings should resolve to True."""
        monkeypatch.setenv("TEST_BOOL", truthy)
        result = resolve_bool(
            ("TEST_BOOL",),
            "legacy_key",
            False,
            **no_legacy_ctx,
        )
        assert result is True

    @pytest.mark.parametrize("falsy", ["0", "false", "False", "FALSE", "no", "No", "NO", "off", "Off", "OFF", "maybe"])
    def test_env_falsy_values_use_default(self, monkeypatch, no_legacy_ctx, falsy):
        """Various falsy env strings should fall through to default."""
        monkeypatch.setenv("TEST_BOOL", falsy)
        result = resolve_bool(
            ("TEST_BOOL",),
            "legacy_key",
            False,
            **no_legacy_ctx,
        )
        # Falsy values fall through to default (False)
        assert result is False

    def test_legacy_bool_parsing(self, resolver_ctx):
        """Legacy config should parse bool strings correctly."""
        result = resolve_bool(
            ("UNSET_VAR",),
            "test_bool",
            False,
            **resolver_ctx,
        )
        assert result is True

    def test_default_when_nothing_set(self, no_legacy_ctx):
        """Default should be used when nothing is set."""
        result = resolve_bool(
            ("UNSET_VAR",),
            "unset_key",
            True,
            **no_legacy_ctx,
        )
        assert result is True


# ─────────────────────────────────────────────────────────────
# resolve_int Tests
# ─────────────────────────────────────────────────────────────


class TestResolveInt:
    """Tests for resolve_int function."""

    def test_env_int_parsing(self, monkeypatch, no_legacy_ctx):
        """Env var should be parsed as int."""
        monkeypatch.setenv("TEST_INT", "42")
        result = resolve_int(
            ("TEST_INT",),
            "legacy_key",
            10,
            **no_legacy_ctx,
        )
        assert result == 42

    def test_env_invalid_int_uses_default(self, monkeypatch, no_legacy_ctx):
        """Invalid env int should fall back to default."""
        monkeypatch.setenv("TEST_INT", "not_an_int")
        result = resolve_int(
            ("TEST_INT",),
            "legacy_key",
            10,
            **no_legacy_ctx,
        )
        assert result == 10

    def test_legacy_int_parsing(self, resolver_ctx):
        """Legacy config should be parsed as int."""
        result = resolve_int(
            ("UNSET_VAR",),
            "test_int",
            10,
            **resolver_ctx,
        )
        assert result == 42

    def test_min_max_clamping(self, monkeypatch, no_legacy_ctx):
        """Min and max values should be respected."""
        monkeypatch.setenv("TEST_INT", "1000")
        result = resolve_int(
            ("TEST_INT",),
            "legacy_key",
            50,
            min_val=0,
            max_val=100,
            **no_legacy_ctx,
        )
        assert result == 100  # Clamped to max

        monkeypatch.setenv("TEST_INT", "-50")
        result = resolve_int(
            ("TEST_INT",),
            "legacy_key",
            50,
            min_val=0,
            max_val=100,
            **no_legacy_ctx,
        )
        assert result == 0  # Clamped to min


# ─────────────────────────────────────────────────────────────
# resolve_float Tests
# ─────────────────────────────────────────────────────────────


class TestResolveFloat:
    """Tests for resolve_float function."""

    def test_env_float_parsing(self, monkeypatch, no_legacy_ctx):
        """Env var should be parsed as float."""
        monkeypatch.setenv("TEST_FLOAT", "3.14")
        result = resolve_float(
            ("TEST_FLOAT",),
            "legacy_key",
            1.0,
            **no_legacy_ctx,
        )
        assert result == 3.14

    def test_env_invalid_float_uses_default(self, monkeypatch, no_legacy_ctx):
        """Invalid env float should fall back to default."""
        monkeypatch.setenv("TEST_FLOAT", "not_a_float")
        result = resolve_float(
            ("TEST_FLOAT",),
            "legacy_key",
            1.0,
            **no_legacy_ctx,
        )
        assert result == 1.0

    def test_legacy_float_parsing(self, resolver_ctx):
        """Legacy config should be parsed as float."""
        result = resolve_float(
            ("UNSET_VAR",),
            "test_float",
            1.0,
            **resolver_ctx,
        )
        assert result == 3.14

    def test_min_max_clamping(self, monkeypatch, no_legacy_ctx):
        """Min and max values should be respected for floats."""
        monkeypatch.setenv("TEST_FLOAT", "100.0")
        result = resolve_float(
            ("TEST_FLOAT",),
            "legacy_key",
            50.0,
            min_val=0.0,
            max_val=1.0,
            **no_legacy_ctx,
        )
        assert result == 1.0  # Clamped to max


# ─────────────────────────────────────────────────────────────
# resolve_path Tests
# ─────────────────────────────────────────────────────────────


class TestResolvePath:
    """Tests for resolve_path function."""

    def test_env_path_used_when_set(self, monkeypatch):
        """Env path should be used when set."""
        monkeypatch.setenv("TEST_PATH", "/tmp/test")
        result = resolve_path(
            ("TEST_PATH",),
            "~/.default",
        )
        assert result == Path("/tmp/test").resolve()

    def test_default_path_expanded(self, monkeypatch):
        """Default path should expand ~."""
        monkeypatch.delenv("TEST_PATH", raising=False)
        result = resolve_path(
            ("TEST_PATH",),
            "~/.code_puppy",
        )
        assert str(result).startswith(str(Path.home()))

    def test_path_is_absolute(self, monkeypatch):
        """Result should always be an absolute path."""
        monkeypatch.setenv("TEST_PATH", "/tmp/relative")
        result = resolve_path(
            ("TEST_PATH",),
            "~/.default",
        )
        assert result.is_absolute()


# ─────────────────────────────────────────────────────────────
# Edge Cases
# ─────────────────────────────────────────────────────────────


class TestResolverEdgeCases:
    """Tests for edge cases in resolvers."""

    def test_empty_env_var_uses_next_source(self, monkeypatch, resolver_ctx):
        """Empty env var should fall through to next source."""
        monkeypatch.setenv("TEST_VAR", "")
        result = resolve_str(
            ("TEST_VAR",),
            "test_key",
            "default",
            **resolver_ctx,
        )
        # Empty string is falsy, should fall through to legacy
        assert result == "legacy_value"

    def test_whitespace_env_var_is_truthy(self, monkeypatch, no_legacy_ctx):
        """Whitespace-only env var should be considered set for strings."""
        monkeypatch.setenv("TEST_VAR", "   ")
        result = resolve_str(
            ("TEST_VAR",),
            "legacy_key",
            "default",
            **no_legacy_ctx,
        )
        # Whitespace is not empty for strings
        assert result == "   "

    def test_no_legacy_config_uses_defaults(self, monkeypatch, no_legacy_ctx):
        """When legacy config is unavailable, defaults should be used."""
        monkeypatch.delenv("UNSET_VAR", raising=False)
        result_str = resolve_str(
            ("UNSET_VAR",),
            "unset_key",
            "default_str",
            **no_legacy_ctx,
        )
        result_bool = resolve_bool(
            ("UNSET_VAR",),
            "unset_key",
            True,
            **no_legacy_ctx,
        )
        result_int = resolve_int(
            ("UNSET_VAR",),
            "unset_key",
            42,
            **no_legacy_ctx,
        )
        result_float = resolve_float(
            ("UNSET_VAR",),
            "unset_key",
            3.14,
            **no_legacy_ctx,
        )

        assert result_str == "default_str"
        assert result_bool is True
        assert result_int == 42
        assert result_float == 3.14
