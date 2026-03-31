"""Unit tests for the pack_parallelism plugin."""

import builtins
import importlib
from unittest.mock import patch


def _reload_plugin():
    """Import plugin fresh, resetting module globals."""
    import code_puppy.plugins.pack_parallelism.register_callbacks as m

    importlib.reload(m)
    # Reset session override and cache
    m._session_max = None
    m._cached_config = None
    return m


class TestReadConfigMax:
    def test_no_config_file_returns_default(self, tmp_path):
        plugin = _reload_plugin()
        with patch.object(plugin, "_CONFIG_PATH", tmp_path / "nonexistent.toml"):
            plugin._cached_config = None
            assert plugin._read_config_max() == 2

    def test_reads_value_from_toml(self, tmp_path):
        config = tmp_path / "pack_parallelism.toml"
        config.write_text("[pack_leader]\nmax_parallelism = 5\n")
        plugin = _reload_plugin()
        with patch.object(plugin, "_CONFIG_PATH", config):
            plugin._cached_config = None
            assert plugin._read_config_max() == 5

    def test_missing_key_returns_default(self, tmp_path):
        config = tmp_path / "pack_parallelism.toml"
        config.write_text("[pack_leader]\nsome_other_key = 99\n")
        plugin = _reload_plugin()
        with patch.object(plugin, "_CONFIG_PATH", config):
            plugin._cached_config = None
            assert plugin._read_config_max() == 2

    def test_malformed_toml_returns_default(self, tmp_path):
        config = tmp_path / "pack_parallelism.toml"
        config.write_text("not valid toml ][[\n")
        plugin = _reload_plugin()
        with patch.object(plugin, "_CONFIG_PATH", config):
            plugin._cached_config = None
            assert plugin._read_config_max() == 2

    def test_manual_parser_exact_key_match(self, tmp_path):
        """Verify the manual parser doesn't match max_parallelism_extra."""
        config = tmp_path / "pack_parallelism.toml"
        config.write_text(
            "[pack_leader]\nmax_parallelism_extra = 99\nmax_parallelism = 4\n"
        )
        plugin = _reload_plugin()

        original_import = builtins.__import__

        def no_toml(name, *args, **kwargs):
            if name in ("tomllib", "tomli"):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        with patch.object(plugin, "_CONFIG_PATH", config):
            with patch("builtins.__import__", side_effect=no_toml):
                plugin._cached_config = None
                result = plugin._read_config_max()

        # Should return 4, not 99
        assert result == 4

    def test_result_is_cached(self, tmp_path):
        """Second call should return the same cached value without re-reading."""
        config = tmp_path / "pack_parallelism.toml"
        config.write_text("[pack_leader]\nmax_parallelism = 3\n")
        plugin = _reload_plugin()
        with patch.object(plugin, "_CONFIG_PATH", config):
            plugin._cached_config = None
            first = plugin._read_config_max()
            # Overwrite file — result should still come from cache
            config.write_text("[pack_leader]\nmax_parallelism = 99\n")
            second = plugin._read_config_max()
        assert first == 3
        assert second == 3  # cached, file change not visible


class TestEffectiveMax:
    def test_no_session_override_uses_config(self):
        plugin = _reload_plugin()
        plugin._session_max = None
        plugin._cached_config = 3
        assert plugin._effective_max() == 3

    def test_session_override_takes_precedence(self):
        plugin = _reload_plugin()
        plugin._session_max = 7
        plugin._cached_config = 3
        assert plugin._effective_max() == 7


class TestPromptAddition:
    def test_returns_string_with_max_parallel_agents(self):
        plugin = _reload_plugin()
        plugin._cached_config = 2
        result = plugin._prompt_addition()
        assert result is not None
        assert "MAX_PARALLEL_AGENTS" in result
        assert "2" in result

    def test_reflects_session_override(self):
        plugin = _reload_plugin()
        plugin._session_max = 4
        result = plugin._prompt_addition()
        assert result is not None
        assert "4" in result


class TestHandleCommand:
    def setup_method(self):
        self.plugin = _reload_plugin()
        self.plugin._session_max = None
        self.plugin._cached_config = 2

    def test_unrecognized_command_returns_none(self):
        assert self.plugin._handle_command("/foo", "foo") is None

    def test_hidden_alias_removed(self):
        """pack-parallelism should no longer be recognised (YAGNI)."""
        assert (
            self.plugin._handle_command("/pack-parallelism", "pack-parallelism") is None
        )

    def test_no_args_returns_true(self):
        with patch("code_puppy.messaging.emit_info"):
            result = self.plugin._handle_command("/pack-parallel", "pack-parallel")
        assert result is True

    def test_valid_int_sets_session_max(self):
        with patch("code_puppy.messaging.emit_info"):
            self.plugin._handle_command("/pack-parallel 4", "pack-parallel")
        assert self.plugin._session_max == 4

    def test_invalid_string_returns_true_with_error(self):
        with patch("code_puppy.messaging.emit_error") as mock_err:
            result = self.plugin._handle_command("/pack-parallel abc", "pack-parallel")
        assert result is True
        mock_err.assert_called_once()

    def test_zero_returns_true_with_error(self):
        with patch("code_puppy.messaging.emit_error") as mock_err:
            result = self.plugin._handle_command("/pack-parallel 0", "pack-parallel")
        assert result is True
        mock_err.assert_called_once()

    def test_negative_returns_true_with_error(self):
        with patch("code_puppy.messaging.emit_error") as mock_err:
            result = self.plugin._handle_command("/pack-parallel -1", "pack-parallel")
        assert result is True
        mock_err.assert_called_once()

    def test_pack_par_alias_works(self):
        with patch("code_puppy.messaging.emit_info"):
            result = self.plugin._handle_command("/pack-par 3", "pack-par")
        assert result is True
        assert self.plugin._session_max == 3

    def test_cap_at_32(self):
        """Values above 32 should be capped with a warning."""
        with patch("code_puppy.messaging.emit_info") as mock_info:
            self.plugin._handle_command("/pack-parallel 50", "pack-parallel")
        assert self.plugin._session_max == 32
        # Warning message should mention the cap
        warning_text = " ".join(str(c) for c in mock_info.call_args_list)
        assert "32" in warning_text

    def test_exactly_32_is_accepted(self):
        with patch("code_puppy.messaging.emit_info"):
            self.plugin._handle_command("/pack-parallel 32", "pack-parallel")
        assert self.plugin._session_max == 32


class TestCommandHelp:
    def test_returns_list_of_tuples(self):
        plugin = _reload_plugin()
        result = plugin._command_help()
        assert isinstance(result, list)
        assert len(result) >= 1
        names = [entry[0] for entry in result]
        assert "pack-parallel" in names

    def test_shows_current_value(self):
        plugin = _reload_plugin()
        plugin._session_max = 5
        result = plugin._command_help()
        help_text = " ".join(desc for _, desc in result)
        assert "5" in help_text

    def test_no_hidden_alias_in_help(self):
        """pack-parallelism was removed; it should not appear in help either."""
        plugin = _reload_plugin()
        result = plugin._command_help()
        names = [entry[0] for entry in result]
        assert "pack-parallelism" not in names
