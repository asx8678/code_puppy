"""Unit tests for the pack_parallelism plugin."""

import builtins
import importlib
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

        with patch("code_puppy.messaging.emit_info") as mock_info:
            with patch(
                "code_puppy.agents.agent_manager.get_current_agent",
                return_value=mock_agent,
            ):
                result = plugin._handle_command("/pack-parallel 4", "pack-parallel")

        # Should return True (command handled) despite cache error
        assert result is True
        # Value should still be set
        assert plugin._session_max == 4
        # Success message should be emitted
        mock_info.assert_called()
