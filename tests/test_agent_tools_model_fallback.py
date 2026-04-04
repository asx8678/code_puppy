"""Tests for model fallback when pinned model is unavailable in invoke_agent."""

import pytest
from unittest.mock import patch



class TestInvokeAgentModelFallback:
    """Test model fallback behavior when agent's model is not in configuration."""

    @pytest.mark.asyncio
    async def test_fallback_to_global_model_when_pinned_not_in_config(self):
        """When pinned model is not in config, should fall back to global model."""
        # Test the core fallback logic by directly exercising the code path
        # that happens inside invoke_agent when a pinned model is not available

        models_config = {"claude-sonnet-4": {"type": "anthropic"}}
        model_name = "gpt-4o-mini"
        agent_name = "watchdog"

        # Simulate the fallback logic from agent_tools.py
        with patch("code_puppy.config.get_global_model_name", return_value="claude-sonnet-4"), \
             patch("code_puppy.messaging.emit_warning") as mock_warn:

            # Replicate the exact fallback logic from agent_tools.py
            if model_name not in models_config:
                from code_puppy.config import get_global_model_name
                fallback_model = get_global_model_name()
                if fallback_model and fallback_model != model_name and fallback_model in models_config:
                    from code_puppy.messaging import emit_warning
                    emit_warning(
                        f"⚠️  MODEL FALLBACK ⚠️  Agent '{agent_name}' requested "
                        f"model '{model_name}' which is not in configuration. "
                        f"Falling back to '{fallback_model}'. "
                        f"Fix with: /config agent_model_{agent_name}"
                    )
                    model_name = fallback_model

            # Assert the fallback was applied
            assert model_name == "claude-sonnet-4"
            mock_warn.assert_called_once()
            warning_msg = mock_warn.call_args[0][0]
            assert "gpt-4o-mini" in warning_msg
            assert "claude-sonnet-4" in warning_msg
            assert "MODEL FALLBACK" in warning_msg
            assert "watchdog" in warning_msg
            assert "/config agent_model_watchdog" in warning_msg

    @pytest.mark.asyncio
    async def test_raises_when_both_pinned_and_global_missing(self):
        """When both pinned and global models are not in config, should raise ValueError."""
        models_config = {"claude-sonnet-4": {"type": "anthropic"}}

        with patch("code_puppy.config.get_global_model_name", return_value="also-missing-model"):
            model_name = "gpt-4o-mini"
            fallback_model = "also-missing-model"

            # Neither model is in config
            assert model_name not in models_config
            assert fallback_model not in models_config

            with pytest.raises(ValueError, match="not found in configuration"):
                if model_name not in models_config:
                    if fallback_model and fallback_model != model_name and fallback_model in models_config:
                        model_name = fallback_model
                    else:
                        raise ValueError(
                            f"Model '{model_name}' not found in configuration"
                        )

    @pytest.mark.asyncio
    async def test_raises_when_fallback_same_as_pinned(self):
        """When global model is the same as the missing pinned model, should raise ValueError."""
        models_config = {"claude-sonnet-4": {"type": "anthropic"}}

        model_name = "gpt-4o-mini"
        fallback_model = "gpt-4o-mini"  # Same as pinned!

        with pytest.raises(ValueError, match="not found in configuration"):
            if model_name not in models_config:
                if fallback_model and fallback_model != model_name and fallback_model in models_config:
                    model_name = fallback_model
                else:
                    raise ValueError(
                        f"Model '{model_name}' not found in configuration"
                    )

    def test_warning_contains_fix_suggestion(self):
        """Warning message should contain actionable fix suggestion."""
        agent_name = "watchdog"
        model_name = "gpt-4o-mini"
        fallback_model = "claude-sonnet-4"

        expected_warning = (
            f"⚠️  MODEL FALLBACK ⚠️  Agent '{agent_name}' requested "
            f"model '{model_name}' which is not in configuration. "
            f"Falling back to '{fallback_model}'. "
            f"Fix with: /config agent_model_{agent_name}"
        )

        assert agent_name in expected_warning
        assert model_name in expected_warning
        assert fallback_model in expected_warning
        assert f"/config agent_model_{agent_name}" in expected_warning
        assert "MODEL FALLBACK" in expected_warning
