"""Tests for agent memory CLI commands and config integration.

Tests the Phase 6 implementation: configuration support and /memory slash command.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from code_puppy.plugins.agent_memory.config import MemoryConfig, get_config, is_memory_enabled


class TestMemoryConfig:
    """Tests for memory configuration functions."""

    def test_is_memory_enabled_returns_false_by_default(self) -> None:
        """Memory should be OPT-IN and disabled by default."""
        from code_puppy.config import _invalidate_config

        _invalidate_config()

        with patch(
            "code_puppy.config.get_value",
            return_value=None,  # Not set = default = False
        ):
            result = is_memory_enabled()
            assert result is False

    def test_is_memory_enabled_returns_true_when_configured(self) -> None:
        """Memory should be enabled when config says so."""
        from code_puppy.config import _invalidate_config

        _invalidate_config()

        with patch(
            "code_puppy.config.get_value",
            return_value="true",
        ):
            result = is_memory_enabled()
            assert result is True

    def test_get_config_returns_defaults_when_not_set(self) -> None:
        """get_config should return default values."""
        from code_puppy.config import _invalidate_config

        _invalidate_config()  # Clear any cached values

        with patch(
            "code_puppy.config.get_value",
            return_value=None,
        ):
            config = get_config()
            assert config.enabled is False
            assert config.debounce_seconds == 30
            assert config.max_facts == 50
            assert config.token_budget == 500
            assert config.extraction_model is None

    def test_get_config_returns_custom_values(self) -> None:
        """get_config should read custom values from config."""
        from code_puppy.config import _invalidate_config

        _invalidate_config()  # Clear any cached values

        # Create a mock that returns different values based on key
        def mock_get_value(key):
            values = {
                "enable_agent_memory": "true",
                "memory_debounce_seconds": "60",
                "memory_max_facts": "100",
                "memory_token_budget": "1000",
                "memory_extraction_model": "gpt-4o",
            }
            return values.get(key)

        with patch(
            "code_puppy.config.get_value",
            side_effect=mock_get_value,
        ):
            config = get_config()
            assert config.enabled is True
            assert config.debounce_seconds == 60
            assert config.max_facts == 100
            assert config.token_budget == 1000
            assert config.extraction_model == "gpt-4o"

    def test_memory_config_is_immutable(self) -> None:
        """MemoryConfig should be frozen (immutable)."""
        config = MemoryConfig(enabled=True, max_facts=25)
        assert config.enabled is True
        assert config.max_facts == 25

        # Attempting to modify should raise
        with pytest.raises(AttributeError):
            config.enabled = False  # type: ignore[misc]


class TestMemoryCommandHelp:
    """Tests for /memory help integration."""

    def test_memory_help_returns_tuple_list(self) -> None:
        """_memory_help should return list of (command, description) tuples."""
        from code_puppy.plugins.agent_memory.register_callbacks import (
            _memory_help,
        )

        result = _memory_help()
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0][0] == "memory"
        assert "memor" in result[0][1].lower()


class TestMemoryCommandHandler:
    """Tests for /memory command handler."""

    def test_non_memory_command_returns_none(self) -> None:
        """Handler should return None for non-memory commands."""
        from code_puppy.plugins.agent_memory.register_callbacks import (
            _handle_memory_command,
        )

        result = _handle_memory_command("/plan", "plan")
        assert result is None

    def test_memory_command_disabled_shows_warning(self) -> None:
        """When memory is disabled, should warn and return True."""
        from code_puppy.plugins.agent_memory.register_callbacks import (
            _handle_memory_command,
            _memory_enabled,
        )

        with patch(
            "code_puppy.plugins.agent_memory.register_callbacks._memory_enabled",
            False,
        ), patch(
            "code_puppy.messaging.emit_warning"
        ) as mock_emit:
            result = _handle_memory_command("/memory show", "memory")
            assert result is True
            mock_emit.assert_called_once()
            warning_msg = str(mock_emit.call_args[0][0])
            assert "disabled" in warning_msg.lower() or "enable" in warning_msg.lower()

    @pytest.mark.parametrize("subcommand", ["show", "clear", "export"])
    def test_memory_subcommands_when_enabled(self, subcommand: str) -> None:
        """Each subcommand should be handled when memory is enabled."""
        from code_puppy.plugins.agent_memory.register_callbacks import (
            _handle_memory_command,
        )

        mock_agent = MagicMock()
        mock_agent.name = "test-agent"

        with patch(
            "code_puppy.plugins.agent_memory.register_callbacks._memory_enabled",
            True,
        ), patch(
            "code_puppy.agents.get_current_agent", return_value=mock_agent
        ), patch(
            "code_puppy.plugins.agent_memory.storage.FileMemoryStorage"
        ) as mock_storage_class:
            mock_storage = MagicMock()
            mock_storage.load.return_value = []
            mock_storage.fact_count.return_value = 0
            mock_storage_class.return_value = mock_storage

            result = _handle_memory_command(f"/memory {subcommand}", "memory")
            assert result is True

    def test_memory_help_subcommand(self) -> None:
        """Help subcommand should show detailed help."""
        from code_puppy.plugins.agent_memory.register_callbacks import (
            _handle_memory_command,
        )

        with patch(
            "code_puppy.plugins.agent_memory.register_callbacks._memory_enabled",
            True,
        ), patch(
            "code_puppy.messaging.emit_info"
        ) as mock_emit:
            result = _handle_memory_command("/memory help", "memory")
            assert result is True
            mock_emit.assert_called()

    def test_memory_unknown_subcommand_shows_help(self) -> None:
        """Unknown subcommand should show warning and help."""
        from code_puppy.plugins.agent_memory.register_callbacks import (
            _handle_memory_command,
        )

        with patch(
            "code_puppy.plugins.agent_memory.register_callbacks._memory_enabled",
            True,
        ), patch(
            "code_puppy.messaging.emit_warning"
        ) as mock_warning, patch(
            "code_puppy.plugins.agent_memory.register_callbacks._show_memory_help"
        ) as mock_help:
            result = _handle_memory_command("/memory foobar", "memory")
            assert result is True
            mock_warning.assert_called_once()
            mock_help.assert_called_once()

    def test_memory_no_subcommand_shows_help(self) -> None:
        """Bare /memory command should show help."""
        from code_puppy.plugins.agent_memory.register_callbacks import (
            _handle_memory_command,
        )

        with patch(
            "code_puppy.plugins.agent_memory.register_callbacks._memory_enabled",
            True,
        ), patch(
            "code_puppy.plugins.agent_memory.register_callbacks._show_memory_help"
        ) as mock_help:
            result = _handle_memory_command("/memory", "memory")
            assert result is True
            mock_help.assert_called_once()


class TestMemoryShowCommand:
    """Tests for /memory show subcommand."""

    def test_show_no_agent_emits_error(self) -> None:
        """Should emit error when no agent is active."""
        from code_puppy.plugins.agent_memory.register_callbacks import _show_memories

        with patch(
            "code_puppy.plugins.agent_memory.register_callbacks._get_current_agent_name",
            return_value=None,
        ), patch(
            "code_puppy.messaging.emit_error"
        ) as mock_emit:
            _show_memories()
            mock_emit.assert_called_once()
            assert "agent" in str(mock_emit.call_args[0][0]).lower()

    def test_show_empty_memories_informs_user(self) -> None:
        """Should inform user when no memories exist."""
        from code_puppy.plugins.agent_memory.register_callbacks import _show_memories

        with patch(
            "code_puppy.plugins.agent_memory.register_callbacks._get_current_agent_name",
            return_value="test-agent",
        ), patch(
            "code_puppy.plugins.agent_memory.register_callbacks._get_storage_for_current_agent"
        ) as mock_get_storage:
            mock_storage = MagicMock()
            mock_storage.load.return_value = []
            mock_get_storage.return_value = mock_storage

            with patch("code_puppy.messaging.emit_info") as mock_emit:
                _show_memories()
                mock_emit.assert_called_once()
                assert "no memories" in str(mock_emit.call_args[0][0]).lower()

    def test_show_memories_displays_table(self) -> None:
        """Should display a Rich table with memories."""
        from code_puppy.plugins.agent_memory.register_callbacks import _show_memories

        mock_facts = [
            {
                "text": "Python is fun",
                "confidence": 0.95,
                "created_at": "2026-04-09T10:00:00+00:00",
            },
            {
                "text": "Rust is fast",
                "confidence": 0.88,
                "created_at": "2026-04-09T11:00:00+00:00",
            },
        ]

        with patch(
            "code_puppy.plugins.agent_memory.register_callbacks._get_current_agent_name",
            return_value="test-agent",
        ), patch(
            "code_puppy.plugins.agent_memory.register_callbacks._get_storage_for_current_agent"
        ) as mock_get_storage:
            mock_storage = MagicMock()
            mock_storage.load.return_value = mock_facts
            mock_get_storage.return_value = mock_storage

            with patch("rich.console.Console.print") as mock_print:
                _show_memories()
                mock_print.assert_called_once()
                # Check that we got a Panel with a table
                panel = mock_print.call_args[0][0]
                assert panel.__class__.__name__ == "Panel"


class TestMemoryClearCommand:
    """Tests for /memory clear subcommand."""

    def test_clear_no_agent_emits_warning(self) -> None:
        """Should warn when no agent is active."""
        from code_puppy.plugins.agent_memory.register_callbacks import _clear_memories

        with patch(
            "code_puppy.plugins.agent_memory.register_callbacks._get_current_agent_name",
            return_value=None,
        ), patch(
            "code_puppy.messaging.emit_warning"
        ) as mock_emit:
            _clear_memories()
            mock_emit.assert_called_once()
            assert "agent" in str(mock_emit.call_args[0][0]).lower()

    def test_clear_empty_memories_informs_user(self) -> None:
        """Should inform user when nothing to clear."""
        from code_puppy.plugins.agent_memory.register_callbacks import _clear_memories

        with patch(
            "code_puppy.plugins.agent_memory.register_callbacks._get_current_agent_name",
            return_value="test-agent",
        ), patch(
            "code_puppy.plugins.agent_memory.register_callbacks._get_storage_for_current_agent"
        ) as mock_get_storage:
            mock_storage = MagicMock()
            mock_storage.fact_count.return_value = 0
            mock_get_storage.return_value = mock_storage

            with patch("code_puppy.messaging.emit_info") as mock_emit:
                _clear_memories()
                mock_emit.assert_called_once()
                assert "no memories" in str(mock_emit.call_args[0][0]).lower()

    def test_clear_memories_success(self) -> None:
        """Should clear memories and emit success message."""
        from code_puppy.plugins.agent_memory.register_callbacks import _clear_memories

        with patch(
            "code_puppy.plugins.agent_memory.register_callbacks._get_current_agent_name",
            return_value="test-agent",
        ), patch(
            "code_puppy.plugins.agent_memory.register_callbacks._get_storage_for_current_agent"
        ) as mock_get_storage:
            mock_storage = MagicMock()
            mock_storage.fact_count.return_value = 5
            mock_get_storage.return_value = mock_storage

            with patch("code_puppy.messaging.emit_success") as mock_emit:
                _clear_memories()
                mock_storage.clear.assert_called_once()
                mock_emit.assert_called_once()
                assert "cleared" in str(mock_emit.call_args[0][0]).lower()


class TestMemoryExportCommand:
    """Tests for /memory export subcommand."""

    def test_export_no_agent_emits_error(self) -> None:
        """Should emit error when no agent is active."""
        from code_puppy.plugins.agent_memory.register_callbacks import _export_memories

        with patch(
            "code_puppy.plugins.agent_memory.register_callbacks._get_current_agent_name",
            return_value=None,
        ), patch(
            "code_puppy.messaging.emit_error"
        ) as mock_emit:
            _export_memories()
            mock_emit.assert_called_once()
            assert "agent" in str(mock_emit.call_args[0][0]).lower()

    def test_export_empty_memories(self) -> None:
        """Should export empty memory structure."""
        from code_puppy.plugins.agent_memory.register_callbacks import _export_memories

        with patch(
            "code_puppy.plugins.agent_memory.register_callbacks._get_current_agent_name",
            return_value="test-agent",
        ), patch(
            "code_puppy.plugins.agent_memory.register_callbacks._get_storage_for_current_agent"
        ) as mock_get_storage:
            mock_storage = MagicMock()
            mock_storage.load.return_value = []
            mock_get_storage.return_value = mock_storage

            with patch("code_puppy.messaging.emit_info") as mock_emit:
                _export_memories()
                mock_emit.assert_called_once()
                # Check the syntax output
                syntax = mock_emit.call_args[0][0]
                assert syntax.__class__.__name__ == "Syntax"

    def test_export_with_memories(self) -> None:
        """Should export memories as JSON."""
        from code_puppy.plugins.agent_memory.register_callbacks import _export_memories

        mock_facts = [
            {
                "text": "Test fact",
                "confidence": 0.9,
                "created_at": "2026-04-09T10:00:00+00:00",
            }
        ]

        with patch(
            "code_puppy.plugins.agent_memory.register_callbacks._get_current_agent_name",
            return_value="test-agent",
        ), patch(
            "code_puppy.plugins.agent_memory.register_callbacks._get_storage_for_current_agent"
        ) as mock_get_storage:
            mock_storage = MagicMock()
            mock_storage.load.return_value = mock_facts
            mock_get_storage.return_value = mock_storage

            with patch("code_puppy.messaging.emit_info") as mock_emit:
                _export_memories()
                mock_emit.assert_called_once()
                syntax = mock_emit.call_args[0][0]
                assert syntax.__class__.__name__ == "Syntax"


class TestMemoryStartup:
    """Tests for memory plugin startup behavior."""

    def test_startup_checks_config(self) -> None:
        """Startup should check if memory is enabled."""
        from code_puppy.plugins.agent_memory.register_callbacks import _on_startup

        with patch(
            "code_puppy.plugins.agent_memory.config.is_memory_enabled",
            return_value=True,
        ):
            _on_startup()
            # If we get here without error, the config was checked

    def test_startup_logs_when_disabled(self) -> None:
        """Startup should log when memory is disabled."""
        from code_puppy.plugins.agent_memory.register_callbacks import _on_startup

        with patch(
            "code_puppy.plugins.agent_memory.config.is_memory_enabled",
            return_value=False,
        ), patch(
            "code_puppy.plugins.agent_memory.register_callbacks.logger"
        ) as mock_logger:
            _on_startup()
            mock_logger.debug.assert_called()
            log_msg = str(mock_logger.debug.call_args[0][0])
            assert "disabled" in log_msg.lower()

    def test_startup_logs_when_enabled(self) -> None:
        """Startup should log when memory is enabled."""
        from code_puppy.plugins.agent_memory.register_callbacks import _on_startup

        with patch(
            "code_puppy.plugins.agent_memory.config.is_memory_enabled",
            return_value=True,
        ), patch(
            "code_puppy.plugins.agent_memory.register_callbacks.logger"
        ) as mock_logger:
            _on_startup()
            mock_logger.debug.assert_called()
            log_msg = str(mock_logger.debug.call_args[0][0])
            assert "activated" in log_msg.lower()


class TestConfigMainModule:
    """Tests for config functions in main config module."""

    def test_get_enable_agent_memory_false_default(self) -> None:
        """get_enable_agent_memory should default to False."""
        from code_puppy.config import get_enable_agent_memory

        with patch(
            "code_puppy.config.get_value",
            return_value=None,
        ):
            result = get_enable_agent_memory()
            assert result is False

    def test_get_enable_agent_memory_respects_config(self) -> None:
        """get_enable_agent_memory should read from config."""
        from code_puppy.config import get_enable_agent_memory

        with patch(
            "code_puppy.config.get_value",
            return_value="true",
        ):
            result = get_enable_agent_memory()
            assert result is True

    def test_memory_debounce_seconds_defaults(self) -> None:
        """memory_debounce_seconds should default to 30."""
        from code_puppy.config import get_memory_debounce_seconds

        with patch(
            "code_puppy.config.get_value",
            return_value=None,
        ):
            result = get_memory_debounce_seconds()
            assert result == 30

    def test_memory_debounce_seconds_min_bound(self) -> None:
        """memory_debounce_seconds should respect minimum bound."""
        from code_puppy.config import _invalidate_config, get_memory_debounce_seconds

        # Test minimum bound
        with patch(
            "code_puppy.config.get_value",
            return_value="0",
        ):
            _invalidate_config()  # Clear cache
            result = get_memory_debounce_seconds()
            assert result == 1  # Min bound

    def test_memory_debounce_seconds_max_bound(self) -> None:
        """memory_debounce_seconds should respect maximum bound."""
        from code_puppy.config import _invalidate_config, get_memory_debounce_seconds

        # Test maximum bound
        with patch(
            "code_puppy.config.get_value",
            return_value="500",
        ):
            _invalidate_config()  # Clear cache
            result = get_memory_debounce_seconds()
            assert result == 300  # Max bound

    def test_memory_max_facts_defaults(self) -> None:
        """memory_max_facts should default to 50."""
        from code_puppy.config import get_memory_max_facts

        with patch(
            "code_puppy.config.get_value",
            return_value=None,
        ):
            result = get_memory_max_facts()
            assert result == 50

    def test_memory_token_budget_defaults(self) -> None:
        """memory_token_budget should default to 500."""
        from code_puppy.config import get_memory_token_budget

        with patch(
            "code_puppy.config.get_value",
            return_value=None,
        ):
            result = get_memory_token_budget()
            assert result == 500

    def test_memory_extraction_model_defaults(self) -> None:
        """memory_extraction_model should default to None."""
        from code_puppy.config import get_memory_extraction_model

        with patch(
            "code_puppy.config.get_value",
            return_value=None,
        ):
            result = get_memory_extraction_model()
            assert result is None

    def test_memory_extraction_model_returns_configured_value(self) -> None:
        """memory_extraction_model should return configured model."""
        from code_puppy.config import get_memory_extraction_model

        with patch(
            "code_puppy.config.get_value",
            return_value="gpt-4o",
        ):
            result = get_memory_extraction_model()
            assert result == "gpt-4o"
