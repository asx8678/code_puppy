"""Unit tests for the pack_parallelism plugin."""

import builtins
import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch


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
            assert plugin._read_config_max() == 6

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
            assert plugin._read_config_max() == 6

    def test_malformed_toml_returns_default(self, tmp_path):
        config = tmp_path / "pack_parallelism.toml"
        config.write_text("not valid toml ][[\n")
        plugin = _reload_plugin()
        with patch.object(plugin, "_CONFIG_PATH", config):
            plugin._cached_config = None
            assert plugin._read_config_max() == 6

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

    def test_unknown_args_rejected(self):
        """Unknown trailing arguments should produce an error."""
        with patch.object(self.plugin, "_write_config_max") as mock_write:
            with patch("code_puppy.messaging.emit_error") as mock_err:
                result = self.plugin._handle_command(
                    "/pack-parallel 4 banana", "pack-parallel"
                )
        assert result is True
        mock_err.assert_called_once()
        mock_write.assert_not_called()
        # Value should NOT have been set
        assert self.plugin._session_max is None
        assert self.plugin._cached_config == 2  # unchanged

    def test_fallback_to_session_on_write_failure(self):
        """When disk write fails, fall back to session-only and warn user."""
        with patch.object(self.plugin, "_write_config_max", return_value=False):
            with patch("code_puppy.messaging.emit_info") as mock_info:
                result = self.plugin._handle_command(
                    "/pack-parallel 4", "pack-parallel"
                )
        assert result is True
        # Should fall back to session-only
        assert self.plugin._session_max == 4
        # Should NOT have updated the config cache
        assert self.plugin._cached_config == 2  # unchanged from setup_method
        # Message should mention failure
        call_text = " ".join(str(c) for c in mock_info.call_args_list)
        assert "failed" in call_text.lower() or "could not" in call_text.lower()

    def test_valid_int_persists_to_config(self):
        with patch.object(self.plugin, "_write_config_max", return_value=True) as mock_write:
            with patch("code_puppy.messaging.emit_info"):
                self.plugin._handle_command("/pack-parallel 4", "pack-parallel")
        # Default behavior: persists to config, clears session override
        assert self.plugin._session_max is None
        assert self.plugin._cached_config == 4
        mock_write.assert_called_once_with(4)

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
        with patch.object(self.plugin, "_write_config_max", return_value=True) as mock_write:
            with patch("code_puppy.messaging.emit_info"):
                result = self.plugin._handle_command("/pack-par 3", "pack-par")
        assert result is True
        assert self.plugin._cached_config == 3
        assert self.plugin._session_max is None
        mock_write.assert_called_once_with(3)

    def test_cap_at_32(self):
        """Values above 32 should be capped with a warning."""
        with patch.object(self.plugin, "_write_config_max", return_value=True) as mock_write:
            with patch("code_puppy.messaging.emit_info") as mock_info:
                self.plugin._handle_command("/pack-parallel 50", "pack-parallel")
        # Should persist the capped value
        assert self.plugin._cached_config == 32
        assert self.plugin._session_max is None
        mock_write.assert_called_once_with(32)
        # Warning message should mention the cap
        warning_text = " ".join(str(c) for c in mock_info.call_args_list)
        assert "32" in warning_text

    def test_exactly_32_is_accepted(self):
        with patch.object(self.plugin, "_write_config_max", return_value=True) as mock_write:
            with patch("code_puppy.messaging.emit_info"):
                self.plugin._handle_command("/pack-parallel 32", "pack-parallel")
        assert self.plugin._cached_config == 32
        assert self.plugin._session_max is None
        mock_write.assert_called_once_with(32)

    def test_session_flag_sets_session_max(self):
        """--session flag should set _session_max without writing to disk."""
        with patch.object(self.plugin, "_write_config_max", return_value=True) as mock_write:
            with patch("code_puppy.messaging.emit_info"):
                self.plugin._handle_command(
                    "/pack-parallel 4 --session", "pack-parallel"
                )
        assert self.plugin._session_max == 4
        mock_write.assert_not_called()

    def test_session_flag_message_mentions_session(self):
        """--session flag should produce message with session-only wording."""
        with patch.object(self.plugin, "_write_config_max"):
            with patch("code_puppy.messaging.emit_info") as mock_info:
                self.plugin._handle_command(
                    "/pack-parallel 4 --session", "pack-parallel"
                )
        call_texts = " ".join(str(c) for c in mock_info.call_args_list)
        assert "session only" in call_texts.lower()


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


class TestInvalidateAgentCaches:
    def test_skips_reload_when_value_unchanged(self):
        """If previous == new, skip cache invalidation entirely."""
        plugin = _reload_plugin()
        with patch("code_puppy.agents.agent_manager.get_current_agent") as mock_get:
            plugin._invalidate_agent_caches(previous_val=4, new_val=4)
            mock_get.assert_not_called()

    def test_busts_cached_system_prompt_and_reloads_agent(self):
        """When value changes, both caches should be invalidated."""
        plugin = _reload_plugin()

        # Create a mock agent with the expected attributes
        mock_agent = MagicMock()
        mock_state = MagicMock()
        mock_state.cached_system_prompt = "old cached prompt"
        mock_agent._state = mock_state
        mock_agent.reload_code_generation_agent = MagicMock()

        with patch(
            "code_puppy.agents.agent_manager.get_current_agent", return_value=mock_agent
        ):
            plugin._invalidate_agent_caches(previous_val=2, new_val=4)

        # Verify cache was busted
        assert mock_state.cached_system_prompt is None
        # Verify agent was reloaded
        mock_agent.reload_code_generation_agent.assert_called_once()

    def test_handles_missing_agent_state_gracefully(self):
        """Agent without _state attribute should not crash."""
        plugin = _reload_plugin()

        mock_agent = MagicMock()
        # No _state attribute
        del mock_agent._state

        with patch(
            "code_puppy.agents.agent_manager.get_current_agent", return_value=mock_agent
        ):
            # Should not raise
            plugin._invalidate_agent_caches(previous_val=2, new_val=4)

    def test_handles_missing_reload_method_gracefully(self):
        """Agent without reload_code_generation_agent should not crash."""
        plugin = _reload_plugin()

        mock_agent = MagicMock()
        mock_state = MagicMock()
        mock_state.cached_system_prompt = "old prompt"
        mock_agent._state = mock_state
        # No reload_code_generation_agent method
        del mock_agent.reload_code_generation_agent

        with patch(
            "code_puppy.agents.agent_manager.get_current_agent", return_value=mock_agent
        ):
            # Should not raise - cache busted but no reload
            plugin._invalidate_agent_caches(previous_val=2, new_val=4)
            # Cache should still be busted
            assert mock_state.cached_system_prompt is None


class TestCommandBustsCache:
    def test_command_busts_cached_system_prompt(self):
        """Test that slash command triggers cache invalidation."""
        plugin = _reload_plugin()
        plugin._session_max = None
        plugin._cached_config = 2

        # Create a mock agent
        mock_agent = MagicMock()
        mock_state = MagicMock()
        mock_state.cached_system_prompt = "old prompt"
        mock_agent._state = mock_state
        mock_agent.reload_code_generation_agent = MagicMock()

        with patch.object(plugin, "_write_config_max", return_value=True):
            with patch("code_puppy.messaging.emit_info"):
                with patch(
                    "code_puppy.agents.agent_manager.get_current_agent",
                    return_value=mock_agent,
                ):
                    plugin._handle_command("/pack-parallel 4", "pack-parallel")

        # Verify both caches were busted
        assert mock_state.cached_system_prompt is None
        mock_agent.reload_code_generation_agent.assert_called_once()

    def test_command_skips_reload_on_same_value(self):
        """Test that setting same value skips reload optimization."""
        plugin = _reload_plugin()
        plugin._session_max = 4  # Already 4
        plugin._cached_config = 2

        mock_agent = MagicMock()

        with patch.object(plugin, "_write_config_max", return_value=True):
            with patch("code_puppy.messaging.emit_info"):
                with patch(
                    "code_puppy.agents.agent_manager.get_current_agent",
                    return_value=mock_agent,
                ) as mock_get:
                    plugin._handle_command("/pack-parallel 4", "pack-parallel")

        # get_current_agent should NOT be called because optimization
        # skips invalidation when previous_val == new_val
        mock_get.assert_not_called()

    def test_command_survives_when_no_active_agent(self):
        """Slash command should succeed even when no agent is active."""
        plugin = _reload_plugin()
        plugin._session_max = None
        plugin._cached_config = 2

        with patch.object(plugin, "_write_config_max", return_value=True):
            with patch("code_puppy.messaging.emit_info") as mock_info:
                with patch(
                    "code_puppy.agents.agent_manager.get_current_agent",
                    side_effect=Exception("No agent available"),
                ):
                    result = plugin._handle_command("/pack-parallel 4", "pack-parallel")

        # Should return True (command handled) despite agent error
        assert result is True
        # Success message should still be emitted
        mock_info.assert_called()
        # Check that the success message mentions the new value
        call_texts = [str(c) for c in mock_info.call_args_list]
        assert any("4" in text for text in call_texts)

    def test_command_survives_when_get_current_agent_returns_none(self):
        """Slash command should succeed when get_current_agent returns None."""
        plugin = _reload_plugin()
        plugin._session_max = None
        plugin._cached_config = 2

        with patch.object(plugin, "_write_config_max", return_value=True):
            with patch("code_puppy.messaging.emit_info") as mock_info:
                with patch(
                    "code_puppy.agents.agent_manager.get_current_agent", return_value=None
                ):
                    result = plugin._handle_command("/pack-parallel 4", "pack-parallel")

        assert result is True
        mock_info.assert_called()
        call_texts = [str(c) for c in mock_info.call_args_list]
        assert any("4" in text for text in call_texts)

    def test_command_survives_cache_invalidation_exception(self):
        """Slash command should succeed even if cache invalidation raises."""
        plugin = _reload_plugin()
        plugin._session_max = None
        plugin._cached_config = 2

        mock_agent = MagicMock()
        # Make cache invalidation raise
        mock_agent._state.cached_system_prompt = "old"
        type(mock_agent._state).cached_system_prompt = property(
            lambda self: "old",
            lambda self, val: (_ for _ in ()).throw(Exception("Cannot set")),
        )

        with patch.object(plugin, "_write_config_max", return_value=True):
            with patch("code_puppy.messaging.emit_info") as mock_info:
                with patch(
                    "code_puppy.agents.agent_manager.get_current_agent",
                    return_value=mock_agent,
                ):
                    result = plugin._handle_command("/pack-parallel 4", "pack-parallel")

        # Should return True (command handled) despite cache error
        assert result is True
        # Value should still be persisted to config
        assert plugin._cached_config == 4
        assert plugin._session_max is None
        # Success message should be emitted
        mock_info.assert_called()


class TestWriteConfigMax:
    def test_creates_file_when_missing(self, tmp_path):
        """Writing to non-existent file creates it with proper content."""
        plugin = _reload_plugin()
        config = tmp_path / "pack_parallelism.toml"
        with patch.object(plugin, "_CONFIG_PATH", config):
            plugin._write_config_max(4)
        content = config.read_text()
        assert "[pack_leader]" in content
        assert "max_parallelism = 4" in content

    def test_creates_parent_directory(self, tmp_path):
        """Writing creates parent dir if it doesn't exist."""
        plugin = _reload_plugin()
        config = tmp_path / "subdir" / "pack_parallelism.toml"
        with patch.object(plugin, "_CONFIG_PATH", config):
            plugin._write_config_max(5)
        assert config.exists()
        content = config.read_text()
        assert "max_parallelism = 5" in content

    def test_updates_existing_value(self, tmp_path):
        """Updating existing max_parallelism replaces the line."""
        plugin = _reload_plugin()
        config = tmp_path / "pack_parallelism.toml"
        config.write_text("[pack_leader]\nmax_parallelism = 2\n")
        with patch.object(plugin, "_CONFIG_PATH", config):
            plugin._write_config_max(8)
        content = config.read_text()
        assert "max_parallelism = 8" in content
        assert "max_parallelism = 2" not in content

    def test_preserves_other_keys(self, tmp_path):
        """Other keys in [pack_leader] section are preserved."""
        plugin = _reload_plugin()
        config = tmp_path / "pack_parallelism.toml"
        config.write_text(
            "[pack_leader]\nallow_parallel = true\nmax_parallelism = 2\nrun_wait_timeout = 300\n"
        )
        with patch.object(plugin, "_CONFIG_PATH", config):
            plugin._write_config_max(10)
        content = config.read_text()
        assert "allow_parallel = true" in content
        assert "run_wait_timeout = 300" in content
        assert "max_parallelism = 10" in content

    def test_preserves_comments(self, tmp_path):
        """Comments in the config file are preserved."""
        plugin = _reload_plugin()
        config = tmp_path / "pack_parallelism.toml"
        config.write_text("# My comment\n[pack_leader]\nmax_parallelism = 2\n")
        with patch.object(plugin, "_CONFIG_PATH", config):
            plugin._write_config_max(7)
        content = config.read_text()
        assert "# My comment" in content
        assert "max_parallelism = 7" in content

    def test_inserts_key_when_section_exists_without_key(self, tmp_path):
        """If [pack_leader] exists but has no max_parallelism, insert the key."""
        plugin = _reload_plugin()
        config = tmp_path / "pack_parallelism.toml"
        config.write_text("[pack_leader]\nallow_parallel = true\n")
        with patch.object(plugin, "_CONFIG_PATH", config):
            plugin._write_config_max(3)
        content = config.read_text()
        assert "max_parallelism = 3" in content
        assert "allow_parallel = true" in content

    def test_appends_section_when_missing(self, tmp_path):
        """If file exists but has no [pack_leader] section, append it."""
        plugin = _reload_plugin()
        config = tmp_path / "pack_parallelism.toml"
        config.write_text("[other_section]\nfoo = bar\n")
        with patch.object(plugin, "_CONFIG_PATH", config):
            plugin._write_config_max(9)
        content = config.read_text()
        assert "[other_section]" in content
        assert "foo = bar" in content
        assert "[pack_leader]" in content
        assert "max_parallelism = 9" in content

    def test_invalidates_cached_config(self, tmp_path):
        """After writing, _cached_config should be None."""
        plugin = _reload_plugin()
        plugin._cached_config = 2
        config = tmp_path / "pack_parallelism.toml"
        with patch.object(plugin, "_CONFIG_PATH", config):
            plugin._write_config_max(5)
        assert plugin._cached_config is None

    def test_handles_inline_comment_on_section_header(self, tmp_path):
        """Section headers with inline comments should not cause duplicates."""
        plugin = _reload_plugin()
        config = tmp_path / "pack_parallelism.toml"
        config.write_text("[pack_leader] # my comment\nmax_parallelism = 2\n")
        with patch.object(plugin, "_CONFIG_PATH", config):
            plugin._write_config_max(8)
        content = config.read_text()
        # Should update in place, not append a duplicate section
        assert content.count("[pack_leader]") == 1
        assert "max_parallelism = 8" in content
        assert "max_parallelism = 2" not in content

    def test_graceful_failure_on_write_error(self, tmp_path):
        """Write failure should not crash, returns False and logs warning."""
        plugin = _reload_plugin()
        config = tmp_path / "pack_parallelism.toml"
        with patch.object(plugin, "_CONFIG_PATH", config):
            with patch("builtins.open", side_effect=OSError("Permission denied")):
                result = plugin._write_config_max(5)
        assert result is False

    def test_returns_true_on_success(self, tmp_path):
        """Successful write returns True."""
        plugin = _reload_plugin()
        config = tmp_path / "pack_parallelism.toml"
        with patch.object(plugin, "_CONFIG_PATH", config):
            result = plugin._write_config_max(4)
        assert result is True
        assert config.exists()

    def test_graceful_failure_on_read_only_dir(self, tmp_path):
        """Write failure should not crash, just log a warning."""
        plugin = _reload_plugin()
        # Point to a path that can't be written
        config = Path("/proc/nonexistent/pack_parallelism.toml")
        with patch.object(plugin, "_CONFIG_PATH", config):
            # Should not raise
            plugin._write_config_max(5)


class TestOnStartup:
    def test_emits_info_with_current_value(self):
        plugin = _reload_plugin()
        plugin._cached_config = 5
        with patch("code_puppy.messaging.emit_info") as mock_info:
            plugin._on_startup()
        mock_info.assert_called_once()
        call_text = str(mock_info.call_args)
        assert "5" in call_text
        assert "config" in call_text.lower()

    def test_shows_session_source_when_override_active(self):
        plugin = _reload_plugin()
        plugin._session_max = 3
        plugin._cached_config = 5
        with patch("code_puppy.messaging.emit_info") as mock_info:
            plugin._on_startup()
        call_text = str(mock_info.call_args)
        assert "3" in call_text
        assert "session" in call_text.lower()

    def test_survives_missing_messaging_module(self):
        """Should fall back to print if messaging is unavailable."""
        plugin = _reload_plugin()
        plugin._cached_config = 2
        with patch.dict("sys.modules", {"code_puppy.messaging": None}):
            with patch("builtins.print") as mock_print:
                plugin._on_startup()
        mock_print.assert_called_once()
