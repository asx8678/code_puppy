"""Tests for the Model Router plugin.

Tests complexity scoring, model selection, configuration loading,
run_with_mcp patching, and custom command handling.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from code_puppy.plugins.model_router.register_callbacks import (
    _CONFIG_KEYS,
    _handle_command,
    _make_run_with_mcp_wrapper,
    _on_startup,
    _original_run_with_mcp,
    calculate_complexity,
    select_model,
    _load_config,
    _custom_help,
)


# ── Reset module-level state between tests ──────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_patch_state(monkeypatch):
    """Ensure _original_run_with_mcp is reset so startup patching works per test."""
    import code_puppy.plugins.model_router.register_callbacks as mod

    orig = mod._original_run_with_mcp
    mod._original_run_with_mcp = None
    yield
    mod._original_run_with_mcp = orig


# ═══════════════════════════════════════════════════════════════════════════
# Complexity scoring
# ═══════════════════════════════════════════════════════════════════════════

class TestCalculateComplexity:
    """Test the prompt complexity scoring function."""

    def test_empty_prompt(self):
        score, reason = calculate_complexity("")
        assert score == 0.0
        assert "empty" in reason.lower()

    def test_none_like_prompt(self):
        score, _ = calculate_complexity("   ")
        assert score == 0.0

    def test_simple_greeting(self):
        score, reason = calculate_complexity("hello")
        assert score < 0.3

    def test_simple_question(self):
        score, _ = calculate_complexity("what time is it?")
        assert score < 0.3

    def test_status_check(self):
        score, _ = calculate_complexity("status")
        assert score < 0.3

    def test_refactor_keyword(self):
        score, reason = calculate_complexity("please refactor this code")
        assert score > 0.1  # short prompt + 1 keyword ≈ 0.155
        assert "refactor" in reason

    def test_analyze_keyword(self):
        score, reason = calculate_complexity("analyze the architecture of this module")
        assert score > 0.1
        assert "analyze" in reason

    def test_debug_keyword(self):
        score, _ = calculate_complexity("debug this error in the code")
        assert score > 0.1

    def test_test_keyword(self):
        score, _ = calculate_complexity("write tests for this function")
        assert score > 0.1

    def test_multiple_complexity_keywords(self):
        score, reason = calculate_complexity(
            "refactor and analyze this code, then debug and test it"
        )
        assert score > 0.25
        assert "kw=" in reason

    def test_file_tool_reference(self):
        score, reason = calculate_complexity("read the file and grep for patterns")
        assert score > 0.05
        assert "tools=" in reason

    def test_long_prompt_is_more_complex(self):
        short = "hi"
        long = "please analyze and refactor the entire codebase, reading each file, running tests, and debugging any issues found" * 5
        short_score, _ = calculate_complexity(short)
        long_score, _ = calculate_complexity(long)
        assert long_score > short_score

    def test_score_bounds(self):
        """Score should always be in [0, 1]."""
        prompts = [
            "",
            "hi",
            "hello world",
            "refactor analyze debug test implement " * 100,
            "read file grep tool function class module package directory " * 50,
        ]
        for p in prompts:
            score, _ = calculate_complexity(p)
            assert 0.0 <= score <= 1.0, f"score {score} out of bounds for: {p[:40]}"

    def test_complex_code_request(self):
        score, _ = calculate_complexity(
            "Refactor the authentication module across all files. "
            "Analyze the security vulnerabilities, implement fixes, "
            "and write comprehensive tests for each file in src/."
        )
        assert score > 0.3


# ═══════════════════════════════════════════════════════════════════════════
# Model selection
# ═══════════════════════════════════════════════════════════════════════════

class TestSelectModel:
    """Test the model selection logic."""

    def test_simple_prompt_uses_simple_model(self):
        config = {"simple_model": "gpt-4o-mini", "complexity_threshold": 0.3}
        with patch(
            "code_puppy.config.get_global_model_name",
            return_value="gpt-4o",
        ):
            model, score, reason = select_model("hello", config)
        assert model == "gpt-4o-mini"
        assert score < 0.3

    def test_complex_prompt_uses_default_model(self):
        config = {"simple_model": "gpt-4o-mini", "complexity_threshold": 0.3}
        with patch(
            "code_puppy.config.get_global_model_name",
            return_value="gpt-4o",
        ):
            model, score, _ = select_model(
                "refactor and analyze the entire architecture across all files, "
                "debug issues in each module, and test every package thoroughly",
                config,
            )
        assert model == "gpt-4o"
        assert score >= 0.3

    def test_threshold_boundary(self):
        config = {"simple_model": "cheap", "complexity_threshold": 0.1}
        with patch(
            "code_puppy.config.get_global_model_name",
            return_value="expensive",
        ):
            model_simple, score_s, _ = select_model("hi", config)
            model_complex, score_c, _ = select_model(
                "refactor analyze debug test each file module package", config
            )
        assert model_simple == "cheap"
        assert score_s < 0.1
        assert model_complex == "expensive"
        assert score_c >= 0.1


# ═══════════════════════════════════════════════════════════════════════════
# Configuration loading
# ═══════════════════════════════════════════════════════════════════════════

class TestLoadConfig:
    """Test configuration loading from puppy.cfg."""

    def test_defaults_when_no_config(self):
        with patch(
            "code_puppy.config.get_value",
            return_value=None,
        ), patch(
            "code_puppy.config._is_truthy",
            return_value=True,
        ):
            cfg = _load_config()
        assert cfg["routing_enabled"] is True
        assert cfg["simple_model"] == "gpt-4o-mini"
        assert cfg["complexity_threshold"] == 0.5

    def test_reads_config_values(self):
        vals = {
            "routing_enabled": "false",
            "simple_model": "claude-3-haiku",
            "complexity_threshold": "0.7",
        }

        def fake_get_value(key):
            return vals.get(key)

        def fake_is_truthy(val, default=True):
            return str(val).strip().lower() in {"1", "true", "yes", "on"}

        with patch(
            "code_puppy.config.get_value",
            side_effect=fake_get_value,
        ), patch(
            "code_puppy.config._is_truthy",
            side_effect=fake_is_truthy,
        ):
            cfg = _load_config()
        assert cfg["routing_enabled"] is False
        assert cfg["simple_model"] == "claude-3-haiku"
        assert cfg["complexity_threshold"] == pytest.approx(0.7)

    def test_invalid_threshold_falls_back(self):
        with patch(
            "code_puppy.config.get_value",
            side_effect=lambda k: "not_a_number" if k == "complexity_threshold" else None,
        ), patch(
            "code_puppy.config._is_truthy",
            return_value=True,
        ):
            cfg = _load_config()
        assert cfg["complexity_threshold"] == 0.5


# ═══════════════════════════════════════════════════════════════════════════
# run_with_mcp wrapper
# ═══════════════════════════════════════════════════════════════════════════

class TestRunWithMcpWrapper:
    """Test the monkey-patched run_with_mcp wrapper."""

    @pytest.fixture
    def mock_agent(self):
        agent = MagicMock()
        agent.reload_code_generation_agent = MagicMock()
        return agent

    def _run_wrapper(self, mock_agent, prompt, config_overrides=None):
        """Helper: create wrapper, call it synchronously via asyncio."""
        original = AsyncMock(return_value="ok")
        wrapper = _make_run_with_mcp_wrapper(original)

        cfg = {
            "routing_enabled": True,
            "simple_model": "gpt-4o-mini",
            "complexity_threshold": 0.3,
        }
        if config_overrides:
            cfg.update(config_overrides)

        async def _run():
            with patch(
                "code_puppy.plugins.model_router.register_callbacks._load_config",
                return_value=cfg,
            ):
                return await wrapper(mock_agent, prompt)

        result = asyncio.run(_run())
        return result, original

    def test_simple_prompt_switches_model(self, mock_agent):
        with patch(
            "code_puppy.config.get_global_model_name",
            return_value="gpt-4o",
        ), patch(
            "code_puppy.config.set_model_name"
        ) as mock_set:
            result, original = self._run_wrapper(mock_agent, "hello")
        assert result == "ok"
        original.assert_called_once()
        mock_set.assert_called_once_with("gpt-4o-mini")
        mock_agent.reload_code_generation_agent.assert_called_once()

    def test_complex_prompt_keeps_model(self, mock_agent):
        with patch(
            "code_puppy.config.get_global_model_name",
            return_value="gpt-4o",
        ), patch(
            "code_puppy.config.set_model_name"
        ) as mock_set:
            result, _ = self._run_wrapper(
                mock_agent,
                "refactor and analyze the entire architecture across all files, "
                "debug issues in each module, and test every package thoroughly",
            )
        assert result == "ok"
        mock_set.assert_not_called()
        mock_agent.reload_code_generation_agent.assert_not_called()

    def test_routing_disabled_skips_switch(self, mock_agent):
        with patch(
            "code_puppy.config.get_global_model_name",
            return_value="gpt-4o",
        ), patch(
            "code_puppy.config.set_model_name"
        ) as mock_set:
            result, _ = self._run_wrapper(
                mock_agent, "hello", config_overrides={"routing_enabled": False}
            )
        assert result == "ok"
        mock_set.assert_not_called()

    def test_same_model_no_switch(self, mock_agent):
        """When the target model is already current, don't reload."""
        with patch(
            "code_puppy.config.get_global_model_name",
            return_value="gpt-4o-mini",
        ), patch(
            "code_puppy.config.set_model_name"
        ) as mock_set:
            result, _ = self._run_wrapper(mock_agent, "hello")
        assert result == "ok"
        mock_set.assert_not_called()
        mock_agent.reload_code_generation_agent.assert_not_called()

    def test_empty_prompt_no_routing(self, mock_agent):
        with patch(
            "code_puppy.config.get_global_model_name",
            return_value="gpt-4o",
        ), patch(
            "code_puppy.config.set_model_name"
        ) as mock_set:
            result, _ = self._run_wrapper(mock_agent, "")
        assert result == "ok"
        mock_set.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# Startup patching
# ═══════════════════════════════════════════════════════════════════════════

class TestOnStartup:
    """Test the startup hook that patches BaseAgent."""

    def test_patches_base_agent(self):
        import code_puppy.plugins.model_router.register_callbacks as mod

        mock_base = MagicMock()
        original_method = MagicMock()
        mock_base.BaseAgent.run_with_mcp = original_method

        with patch.dict(
            "sys.modules",
            {"code_puppy.agents.base_agent": mock_base},
        ), patch(
            "code_puppy.plugins.model_router.register_callbacks._load_config",
            return_value={
                "routing_enabled": True,
                "simple_model": "gpt-4o-mini",
                "complexity_threshold": 0.5,
            },
        ):
            _on_startup()

        # The class method should have been replaced
        assert mock_base.BaseAgent.run_with_mcp is not original_method
        assert mod._original_run_with_mcp is original_method

    def test_idempotent(self):
        """Calling _on_startup twice should not double-patch."""
        import code_puppy.plugins.model_router.register_callbacks as mod

        mock_base = MagicMock()
        original_method = MagicMock()
        mock_base.BaseAgent.run_with_mcp = original_method

        with patch.dict(
            "sys.modules",
            {"code_puppy.agents.base_agent": mock_base},
        ), patch(
            "code_puppy.plugins.model_router.register_callbacks._load_config",
            return_value={
                "routing_enabled": True,
                "simple_model": "gpt-4o-mini",
                "complexity_threshold": 0.5,
            },
        ):
            _on_startup()
            first_patched = mock_base.BaseAgent.run_with_mcp
            _on_startup()  # second call
            second_patched = mock_base.BaseAgent.run_with_mcp

        assert first_patched is second_patched


# ═══════════════════════════════════════════════════════════════════════════
# Custom command
# ═══════════════════════════════════════════════════════════════════════════

class TestHandleCommand:
    """Test the /model_router slash command."""

    def test_wrong_command_returns_none(self):
        assert _handle_command("/other", "other") is None

    def test_status_command(self):
        with patch(
            "code_puppy.plugins.model_router.register_callbacks._load_config",
            return_value={
                "routing_enabled": True,
                "simple_model": "gpt-4o-mini",
                "complexity_threshold": 0.5,
            },
        ), patch(
            "code_puppy.config.get_global_model_name",
            return_value="gpt-4o",
        ), patch(
            "code_puppy.messaging.emit_info"
        ) as mock_info:
            result = _handle_command("/model_router", "model_router")
        assert result is True
        mock_info.assert_called_once()
        body = mock_info.call_args[0][0]
        assert "gpt-4o-mini" in body
        assert "gpt-4o" in body

    def test_enable_command(self):
        with patch(
            "code_puppy.config.set_config_value"
        ) as mock_set, patch(
            "code_puppy.messaging.emit_info"
        ):
            result = _handle_command("/model_router enable", "model_router")
        assert result is True
        mock_set.assert_called_with("routing_enabled", "true")

    def test_disable_command(self):
        with patch(
            "code_puppy.config.set_config_value"
        ) as mock_set, patch(
            "code_puppy.messaging.emit_info"
        ):
            result = _handle_command("/model_router disable", "model_router")
        assert result is True
        mock_set.assert_called_with("routing_enabled", "false")

    def test_threshold_command(self):
        with patch(
            "code_puppy.config.set_config_value"
        ) as mock_set, patch(
            "code_puppy.messaging.emit_info"
        ):
            result = _handle_command("/model_router threshold 0.7", "model_router")
        assert result is True
        mock_set.assert_called_with("complexity_threshold", "0.7")

    def test_threshold_invalid(self):
        with patch(
            "code_puppy.messaging.emit_warning"
        ) as mock_warn:
            result = _handle_command("/model_router threshold abc", "model_router")
        assert result is True
        mock_warn.assert_called_once()

    def test_threshold_out_of_range(self):
        with patch(
            "code_puppy.messaging.emit_warning"
        ) as mock_warn:
            result = _handle_command("/model_router threshold 1.5", "model_router")
        assert result is True
        mock_warn.assert_called_once()

    def test_simple_model_command(self):
        with patch(
            "code_puppy.config.set_config_value"
        ) as mock_set, patch(
            "code_puppy.messaging.emit_info"
        ):
            result = _handle_command(
                "/model_router simple-model claude-3-haiku", "model_router"
            )
        assert result is True
        mock_set.assert_called_with("simple_model", "claude-3-haiku")

    def test_help_text_shown_for_unknown_subcommand(self):
        with patch(
            "code_puppy.messaging.emit_info"
        ) as mock_info:
            _handle_command("/model_router foobar", "model_router")
        mock_info.assert_called_once()
        assert "Usage:" in mock_info.call_args[0][0]


# ═══════════════════════════════════════════════════════════════════════════
# Help
# ═══════════════════════════════════════════════════════════════════════════

class TestCustomHelp:
    def test_help_has_model_router(self):
        entries = dict(_custom_help())
        assert "model_router" in entries
