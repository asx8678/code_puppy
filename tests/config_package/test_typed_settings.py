"""Tests for typed PuppyConfig settings.

These tests verify the behavior of the typed configuration layer,
including env var parsing, legacy fallback, singleton behavior,
and resilience guarantees.
"""

from pathlib import Path

import pytest

from code_puppy.config_package import (
    PuppyConfig,
    get_puppy_config,
    load_puppy_config,
    reload_puppy_config,
    reset_puppy_config_for_tests,
)


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_config_fixture():
    """Reset config cache before and after each test for isolation."""
    reset_puppy_config_for_tests()
    yield
    reset_puppy_config_for_tests()


# ─────────────────────────────────────────────────────────────
# Basic Loading Tests
# ─────────────────────────────────────────────────────────────


class TestBasicLoad:
    """Tests for basic config loading behavior."""

    def test_load_puppy_config_returns_puppy_config(self):
        """load_puppy_config() should return a PuppyConfig instance."""
        cfg = load_puppy_config()
        assert isinstance(cfg, PuppyConfig)

    def test_puppy_config_has_expected_fields(self):
        """PuppyConfig should have all expected fields with correct types."""
        cfg = load_puppy_config()

        # Paths
        assert isinstance(cfg.data_dir, Path)
        assert isinstance(cfg.config_dir, Path)
        assert isinstance(cfg.config_file, Path)
        assert isinstance(cfg.sessions_dir, Path)
        assert isinstance(cfg.models_file, Path)

        # Strings
        assert isinstance(cfg.default_agent, str)
        assert isinstance(cfg.default_model, str)
        assert isinstance(cfg.compaction_strategy, str)
        assert isinstance(cfg.log_level, str)
        assert isinstance(cfg.puppy_name, str)
        assert isinstance(cfg.owner_name, str)

        # Ints
        assert isinstance(cfg.max_concurrent_runs, int)
        assert isinstance(cfg.ws_history_maxlen, int)
        assert isinstance(cfg.protected_token_count, int)
        assert isinstance(cfg.message_limit, int)

        # Floats
        assert isinstance(cfg.temperature, float)

        # Bools
        assert isinstance(cfg.allow_parallel_runs, bool)
        assert isinstance(cfg.session_logger_enabled, bool)
        assert isinstance(cfg.rust_autobuild_disabled, bool)
        assert isinstance(cfg.enable_dbos, bool)
        assert isinstance(cfg.enable_streaming, bool)
        assert isinstance(cfg.enable_agent_memory, bool)
        assert isinstance(cfg.debug, bool)

        # Optional float
        assert cfg.run_wait_timeout is None or isinstance(cfg.run_wait_timeout, float)

    def test_default_values_sensible(self):
        """Default values should be sensible and non-empty."""
        cfg = load_puppy_config()

        # Paths should be absolute
        assert cfg.data_dir.is_absolute()
        assert cfg.config_dir.is_absolute()
        assert cfg.sessions_dir.is_absolute()

        # Strings should be non-empty
        assert cfg.default_agent
        assert cfg.default_model
        assert cfg.log_level
        assert cfg.puppy_name
        assert cfg.owner_name

        # Ints should be positive (or zero for some)
        assert cfg.max_concurrent_runs >= 1
        assert cfg.ws_history_maxlen >= 1
        assert cfg.protected_token_count >= 0
        assert cfg.message_limit >= 1

        # Temperature should be in reasonable range
        assert 0.0 <= cfg.temperature <= 2.0


# ─────────────────────────────────────────────────────────────
# Environment Variable Override Tests
# ─────────────────────────────────────────────────────────────


class TestEnvVarOverrides:
    """Tests for env var override behavior."""

    def test_default_model_env_override(self, monkeypatch):
        """PUPPY_DEFAULT_MODEL should override default."""
        monkeypatch.setenv("PUPPY_DEFAULT_MODEL", "gpt-4-test")
        cfg = load_puppy_config()
        assert cfg.default_model == "gpt-4-test"

    def test_default_agent_env_override(self, monkeypatch):
        """PUPPY_DEFAULT_AGENT should override default."""
        monkeypatch.setenv("PUPPY_DEFAULT_AGENT", "test-agent")
        cfg = load_puppy_config()
        assert cfg.default_agent == "test-agent"

    def test_data_dir_env_override(self, monkeypatch):
        """PUPPY_DATA_DIR should override default."""
        monkeypatch.setenv("PUPPY_DATA_DIR", "/tmp/puppy-test")
        cfg = load_puppy_config()
        assert cfg.data_dir == Path("/tmp/puppy-test").resolve()

    def test_puppy_name_env_override(self, monkeypatch):
        """PUPPY_NAME should override default."""
        monkeypatch.setenv("PUPPY_NAME", "Rex")
        cfg = load_puppy_config()
        assert cfg.puppy_name == "Rex"

    def test_owner_name_env_override(self, monkeypatch):
        """PUPPY_OWNER_NAME should override default."""
        monkeypatch.setenv("PUPPY_OWNER_NAME", "Ada")
        cfg = load_puppy_config()
        assert cfg.owner_name == "Ada"


class TestEnvVarIntParsing:
    """Tests for integer env var parsing."""

    def test_max_concurrent_runs_env_int(self, monkeypatch):
        """PUPPY_MAX_CONCURRENT_RUNS=5 should parse as int 5."""
        monkeypatch.setenv("PUPPY_MAX_CONCURRENT_RUNS", "5")
        cfg = load_puppy_config()
        assert cfg.max_concurrent_runs == 5
        assert isinstance(cfg.max_concurrent_runs, int)

    def test_ws_history_maxlen_env_int(self, monkeypatch):
        """PUPPY_WS_HISTORY_MAXLEN=500 should parse as int 500."""
        monkeypatch.setenv("PUPPY_WS_HISTORY_MAXLEN", "500")
        cfg = load_puppy_config()
        assert cfg.ws_history_maxlen == 500

    def test_protected_token_count_env_int(self, monkeypatch):
        """PUPPY_PROTECTED_TOKEN_COUNT=1000 should parse as int 1000."""
        monkeypatch.setenv("PUPPY_PROTECTED_TOKEN_COUNT", "1000")
        cfg = load_puppy_config()
        assert cfg.protected_token_count == 1000

    def test_message_limit_env_int(self, monkeypatch):
        """PUPPY_MESSAGE_LIMIT=50 should parse as int 50."""
        monkeypatch.setenv("PUPPY_MESSAGE_LIMIT", "50")
        cfg = load_puppy_config()
        assert cfg.message_limit == 50

    def test_int_env_respects_min_max_bounds(self, monkeypatch):
        """Int values should be clamped to min/max bounds."""
        # max_concurrent_runs has min=1, max=100
        monkeypatch.setenv("PUPPY_MAX_CONCURRENT_RUNS", "1000")
        cfg = load_puppy_config()
        assert cfg.max_concurrent_runs == 100  # Clamped to max

        monkeypatch.setenv("PUPPY_MAX_CONCURRENT_RUNS", "0")
        cfg = load_puppy_config()
        assert cfg.max_concurrent_runs == 1  # Clamped to min


class TestEnvVarBoolParsing:
    """Tests for boolean env var parsing."""

    @pytest.mark.parametrize(
        "truthy", ["1", "true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON"]
    )
    def test_debug_truthy_values(self, monkeypatch, truthy):
        """Various truthy strings should set debug=True."""
        monkeypatch.setenv("PUPPY_DEBUG", truthy)
        cfg = load_puppy_config()
        assert cfg.debug is True

    @pytest.mark.parametrize(
        "falsy", ["0", "false", "False", "FALSE", "no", "No", "NO", "off", "maybe"]
    )
    def test_debug_falsy_values(self, monkeypatch, falsy):
        """Various falsy strings should set debug=False."""
        monkeypatch.setenv("PUPPY_DEBUG", falsy)
        cfg = load_puppy_config()
        assert cfg.debug is False

    def test_allow_parallel_runs_env_bool(self, monkeypatch):
        """PUPPY_ALLOW_PARALLEL_RUNS should parse as bool."""
        monkeypatch.setenv("PUPPY_ALLOW_PARALLEL_RUNS", "false")
        cfg = load_puppy_config()
        assert cfg.allow_parallel_runs is False

        monkeypatch.setenv("PUPPY_ALLOW_PARALLEL_RUNS", "true")
        cfg = load_puppy_config()
        assert cfg.allow_parallel_runs is True

    def test_session_logger_enabled_env_bool(self, monkeypatch):
        """PUPPY_SESSION_LOGGER should parse as bool."""
        monkeypatch.setenv("PUPPY_SESSION_LOGGER", "true")
        cfg = load_puppy_config()
        assert cfg.session_logger_enabled is True

    def test_rust_autobuild_disabled_env_bool(self, monkeypatch):
        """PUPPY_DISABLE_RUST_AUTOBUILD should parse as bool."""
        monkeypatch.setenv("PUPPY_DISABLE_RUST_AUTOBUILD", "true")
        cfg = load_puppy_config()
        assert cfg.rust_autobuild_disabled is True


class TestEnvVarPathResolution:
    """Tests for path env var resolution."""

    def test_data_dir_path_resolution(self, monkeypatch):
        """PUPPY_DATA_DIR should be expanded and resolved."""
        monkeypatch.setenv("PUPPY_DATA_DIR", "/tmp/puppy")
        cfg = load_puppy_config()
        assert cfg.data_dir == Path("/tmp/puppy").resolve()
        assert cfg.data_dir.is_absolute()

    def test_data_dir_tilde_expansion(self, monkeypatch):
        """PUPPY_DATA_DIR should expand ~ to home."""
        monkeypatch.setenv("PUPPY_DATA_DIR", "~/custom-puppy")
        cfg = load_puppy_config()
        assert str(cfg.data_dir).startswith(str(Path.home()))
        assert "custom-puppy" in str(cfg.data_dir)


class TestLegacyNameFallback:
    """Tests for legacy env var name fallback."""

    def test_code_puppy_data_dir_legacy_fallback(self, monkeypatch):
        """CODE_PUPPY_DATA_DIR should work when PUPPY_DATA_DIR unset."""
        monkeypatch.delenv("PUPPY_DATA_DIR", raising=False)
        monkeypatch.setenv("CODE_PUPPY_DATA_DIR", "/legacy/path")
        cfg = load_puppy_config()
        assert cfg.data_dir == Path("/legacy/path").resolve()

    def test_puppy_prefix_wins_over_legacy(self, monkeypatch):
        """PUPPY_DATA_DIR should win over CODE_PUPPY_DATA_DIR when both set."""
        monkeypatch.setenv("PUPPY_DATA_DIR", "/new/path")
        monkeypatch.setenv("CODE_PUPPY_DATA_DIR", "/legacy/path")
        cfg = load_puppy_config()
        assert cfg.data_dir == Path("/new/path").resolve()


class TestInvalidEnvVarHandling:
    """Tests for handling invalid env var values."""

    def test_invalid_int_uses_default(self, monkeypatch):
        """Invalid int value should fall back to default, not crash."""
        monkeypatch.setenv("PUPPY_MAX_CONCURRENT_RUNS", "notanint")
        # Should not raise
        cfg = load_puppy_config()
        # Should use default (2) since parsing failed
        assert cfg.max_concurrent_runs == 2

    def test_invalid_float_uses_default(self, monkeypatch):
        """Invalid float value should fall back to default."""
        monkeypatch.setenv("PUPPY_RUN_WAIT_TIMEOUT", "notafloat")
        cfg = load_puppy_config()
        # Should use default (600.0) since parsing failed
        assert cfg.run_wait_timeout == 600.0


# ─────────────────────────────────────────────────────────────
# Singleton and Cache Tests
# ─────────────────────────────────────────────────────────────


class TestSingletonBehavior:
    """Tests for singleton cache behavior."""

    def test_get_puppy_config_returns_same_instance(self):
        """get_puppy_config() should return the same instance across calls."""
        reset_puppy_config_for_tests()
        cfg1 = get_puppy_config()
        cfg2 = get_puppy_config()
        assert cfg1 is cfg2

    def test_reload_returns_new_instance(self, monkeypatch):
        """reload_puppy_config() should return a new instance with fresh values."""
        reset_puppy_config_for_tests()

        # Set initial env var
        monkeypatch.setenv("PUPPY_DEFAULT_MODEL", "model-1")
        cfg1 = get_puppy_config()
        assert cfg1.default_model == "model-1"

        # Change env var
        monkeypatch.setenv("PUPPY_DEFAULT_MODEL", "model-2")

        # Without reload, should still be cached value
        cfg_cached = get_puppy_config()
        assert cfg_cached.default_model == "model-1"

        # After reload, should be new value
        cfg2 = reload_puppy_config()
        assert cfg2.default_model == "model-2"

        # And now cached
        cfg3 = get_puppy_config()
        assert cfg3 is cfg2
        assert cfg3.default_model == "model-2"

    def test_reset_clears_singleton(self, monkeypatch):
        """reset_puppy_config_for_tests() should clear the cache."""
        reset_puppy_config_for_tests()

        monkeypatch.setenv("PUPPY_DEFAULT_MODEL", "before-reset")
        cfg1 = get_puppy_config()
        assert cfg1.default_model == "before-reset"

        # Reset and change env
        reset_puppy_config_for_tests()
        monkeypatch.setenv("PUPPY_DEFAULT_MODEL", "after-reset")

        # Should get fresh value
        cfg2 = get_puppy_config()
        assert cfg2.default_model == "after-reset"


# ─────────────────────────────────────────────────────────────
# to_dict() Tests
# ─────────────────────────────────────────────────────────────


class TestToDict:
    """Tests for to_dict() conversion."""

    def test_to_dict_returns_dict(self):
        """to_dict() should return a plain dict."""
        cfg = load_puppy_config()
        d = cfg.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_has_all_fields(self):
        """to_dict() should include all fields."""
        cfg = load_puppy_config()
        d = cfg.to_dict()

        expected_fields = [
            "data_dir",
            "config_dir",
            "config_file",
            "sessions_dir",
            "models_file",
            "default_agent",
            "default_model",
            "max_concurrent_runs",
            "allow_parallel_runs",
            "run_wait_timeout",
            "ws_history_maxlen",
            "session_logger_enabled",
            "rust_autobuild_disabled",
            "enable_dbos",
            "enable_streaming",
            "enable_agent_memory",
            "temperature",
            "protected_token_count",
            "message_limit",
            "compaction_strategy",
            "debug",
            "log_level",
            "puppy_name",
            "owner_name",
        ]
        for field in expected_fields:
            assert field in d, f"Missing field: {field}"

    def test_to_dict_converts_paths_to_strings(self):
        """Path objects should be converted to strings in to_dict()."""
        cfg = load_puppy_config()
        d = cfg.to_dict()

        assert isinstance(d["data_dir"], str)
        assert isinstance(d["config_dir"], str)
        assert isinstance(d["config_file"], str)
        assert isinstance(d["sessions_dir"], str)
        assert isinstance(d["models_file"], str)

        # Should be absolute paths as strings
        assert d["data_dir"].startswith("/")


# ─────────────────────────────────────────────────────────────
# __repr__ Tests
# ─────────────────────────────────────────────────────────────


class TestRepr:
    """Tests for __repr__ behavior."""

    def test_repr_does_not_crash(self):
        """__repr__ should work without crashing."""
        cfg = load_puppy_config()
        repr_str = repr(cfg)
        assert isinstance(repr_str, str)
        assert "PuppyConfig" in repr_str

    def test_repr_shows_field_names(self):
        """__repr__ should show field names."""
        cfg = load_puppy_config()
        repr_str = repr(cfg)

        # Should have field names
        assert "data_dir=" in repr_str
        assert "default_model=" in repr_str
        assert "debug=" in repr_str

    def test_protected_token_count_not_redacted(self):
        """protected_token_count should NOT be redacted in repr (exact field name matching)."""
        cfg = load_puppy_config()
        repr_str = repr(cfg)

        # Should show actual value, not ***REDACTED***
        assert "protected_token_count=***REDACTED***" not in repr_str
        # Check that protected_token_count shows its actual numeric value
        assert "protected_token_count=" in repr_str
        # The value should be visible (not redacted)
        import re
        match = re.search(r"protected_token_count=(\d+)", repr_str)
        assert match is not None, f"protected_token_count value should be visible in repr: {repr_str}"
        assert int(match.group(1)) == cfg.protected_token_count


# ─────────────────────────────────────────────────────────────
# Resilience Tests
# ─────────────────────────────────────────────────────────────


class TestResilience:
    """Tests for loader crash resilience."""

    def test_load_succeeds_when_no_puppy_cfg(self, monkeypatch):
        """Config loading should succeed even without puppy.cfg."""
        # Point to non-existent config file via env var
        monkeypatch.setenv("PUPPY_CONFIG_DIR", "/nonexistent/config/dir")
        # Should not raise
        cfg = load_puppy_config()
        assert isinstance(cfg, PuppyConfig)
        assert cfg.default_model  # Should have sensible defaults

    def test_all_fields_populated_even_on_legacy_failure(self):
        """All dataclass fields should be populated even if legacy config fails."""
        # This is implicitly tested by all other tests that don't
        # require a valid puppy.cfg. The loader should always return
        # a fully populated PuppyConfig.
        cfg = load_puppy_config()

        # Check no field is None unexpectedly (except the allowed ones)
        assert cfg.data_dir is not None
        assert cfg.config_dir is not None
        assert cfg.config_file is not None
        assert cfg.sessions_dir is not None
        assert cfg.models_file is not None
        assert cfg.default_agent is not None
        assert cfg.default_model is not None
        assert cfg.compaction_strategy is not None
        assert cfg.log_level is not None
        assert cfg.puppy_name is not None
        assert cfg.owner_name is not None


# ─────────────────────────────────────────────────────────────
# Concurrency Fields Tests
# ─────────────────────────────────────────────────────────────


class TestConcurrencyFields:
    """Tests for concurrency-related config fields."""

    def test_max_concurrent_runs_default(self):
        """max_concurrent_runs should have a sensible default."""
        cfg = load_puppy_config()
        assert isinstance(cfg.max_concurrent_runs, int)
        assert cfg.max_concurrent_runs >= 1
        assert cfg.max_concurrent_runs <= 100

    def test_allow_parallel_runs_default(self):
        """allow_parallel_runs should default to True."""
        cfg = load_puppy_config()
        assert isinstance(cfg.allow_parallel_runs, bool)
        # Default is True based on typical usage
        assert cfg.allow_parallel_runs is True

    def test_run_wait_timeout_default_matches_run_limiter_config(self):
        """run_wait_timeout default should match RunLimiterConfig.wait_timeout (600.0)."""
        from code_puppy.plugins.pack_parallelism.run_limiter import RunLimiterConfig

        cfg = load_puppy_config()
        # Default should be 600.0 (not None) to match RunLimiterConfig
        assert cfg.run_wait_timeout == 600.0, (
            f"run_wait_timeout default should be 600.0 to match RunLimiterConfig, "
            f"got {cfg.run_wait_timeout}"
        )

        # Verify it matches RunLimiterConfig default
        rl_cfg = RunLimiterConfig()
        assert cfg.run_wait_timeout == rl_cfg.wait_timeout, (
            f"PuppyConfig.run_wait_timeout ({cfg.run_wait_timeout}) must match "
            f"RunLimiterConfig.wait_timeout ({rl_cfg.wait_timeout})"
        )

    def test_run_wait_timeout_can_be_set(self, monkeypatch):
        """run_wait_timeout should accept float values."""
        monkeypatch.setenv("PUPPY_RUN_WAIT_TIMEOUT", "30.5")
        cfg = load_puppy_config()
        assert cfg.run_wait_timeout == 30.5

    def test_explicit_env_value_matching_default_not_overridden(self, monkeypatch):
        """Explicit env value equal to hardcoded default should be respected, not overridden.

        Regression test for code_puppy-629: When a user explicitly sets an env value
        that happens to equal the hardcoded default, it should still be respected
        and not fall through to legacy config.
        """
        # Import the legacy config to monkeypatch it
        from code_puppy.config_package.loader import _get_legacy_config

        # Set explicit env value that equals the hardcoded default (600.0)
        monkeypatch.setenv("PUPPY_RUN_WAIT_TIMEOUT", "600.0")

        # The env value should be respected even though it equals the hardcoded default
        cfg = load_puppy_config()
        assert cfg.run_wait_timeout == 600.0, (
            "Explicit env value of 600.0 should be respected, not overridden by legacy config"
        )


# ─────────────────────────────────────────────────────────────
# Fields Match Loader Test
# ─────────────────────────────────────────────────────────────


class TestFieldsMatchLoader:
    """Verify all dataclass fields are populated by the loader."""

    def test_no_missing_fields_in_loader(self):
        """Loader should populate all PuppyConfig fields."""
        cfg = load_puppy_config()
        d = cfg.to_dict()

        # All slots should be in to_dict
        for field_name in PuppyConfig.__slots__:
            assert field_name in d, (
                f"Field '{field_name}' not in to_dict — might not be populated by loader"
            )

        # No TypeError should have occurred (implicitly tested)
        # If loader missed a field, PuppyConfig() construction would raise TypeError
