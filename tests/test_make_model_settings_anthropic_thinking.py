"""Tests for make_model_settings() Anthropic extended-thinking temperature coercion.

Covers:
- Temperature forced to 1.0 when extended_thinking is "enabled"
- Temperature forced to 1.0 when extended_thinking is "adaptive"
- Temperature preserved when extended_thinking is "off"
- claude-code-* model names also get temperature coercion (default thinking)
- Warning emitted when a user-specified non-1.0 temperature is overridden
- No warning when temperature is already 1.0 or not set
"""

from unittest.mock import patch

from code_puppy.model_factory import make_model_settings


# ── Patch targets (same pattern as test_make_model_settings_gpt5.py) ──

_LOAD_CONFIG = "code_puppy.model_factory.ModelFactory.load_config"
_GET_EFFECTIVE = "code_puppy.model_factory._config_module.get_effective_model_settings"
_GET_YOLO = "code_puppy.model_factory.get_yolo_mode"
_SUPPORTS = "code_puppy.model_factory._config_module.model_supports_setting"


def _claude_config(model_name: str = "claude-sonnet-4-20250514") -> dict:
    """Return a minimal Anthropic model config dict for testing."""
    return {
        model_name: {
            "type": "anthropic",
            "name": model_name,
            "context_length": 200000,
        }
    }


# ── Temperature coercion when thinking is active ──────────────────────


class TestAnthropicThinkingTemperatureCoercion:
    """Tests that temperature is forced to 1.0 when extended thinking is active."""

    @patch(_SUPPORTS, return_value=False)
    @patch(_GET_YOLO, return_value=True)
    @patch(
        _GET_EFFECTIVE,
        return_value={"temperature": 0.7, "extended_thinking": "enabled"},
    )
    @patch(_LOAD_CONFIG, return_value=_claude_config())
    def test_thinking_enabled_temp_coerced_to_1(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports
    ):
        """When extended_thinking='enabled', temperature=0.7 must become 1.0."""
        settings = make_model_settings("claude-sonnet-4-20250514")
        assert settings["temperature"] == 1.0

    @patch(_SUPPORTS, return_value=False)
    @patch(_GET_YOLO, return_value=True)
    @patch(
        _GET_EFFECTIVE,
        return_value={"temperature": 0.5, "extended_thinking": "adaptive"},
    )
    @patch(_LOAD_CONFIG, return_value=_claude_config())
    def test_thinking_adaptive_temp_coerced_to_1(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports
    ):
        """When extended_thinking='adaptive', temperature=0.5 must become 1.0."""
        settings = make_model_settings("claude-sonnet-4-20250514")
        assert settings["temperature"] == 1.0

    @patch(_SUPPORTS, return_value=False)
    @patch(_GET_YOLO, return_value=True)
    @patch(
        _GET_EFFECTIVE,
        return_value={"temperature": 0.5, "extended_thinking": "off"},
    )
    @patch(_LOAD_CONFIG, return_value=_claude_config())
    def test_thinking_off_temp_preserved(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports
    ):
        """When extended_thinking='off', the user's temperature=0.5 is preserved."""
        settings = make_model_settings("claude-sonnet-4-20250514")
        assert settings["temperature"] == 0.5

    @patch(_SUPPORTS, return_value=False)
    @patch(_GET_YOLO, return_value=True)
    @patch(
        _GET_EFFECTIVE,
        return_value={"extended_thinking": "off"},
    )
    @patch(_LOAD_CONFIG, return_value=_claude_config())
    def test_thinking_off_no_temp_defaults_to_1(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports
    ):
        """When extended_thinking='off' and no temperature set, default to 1.0."""
        settings = make_model_settings("claude-sonnet-4-20250514")
        assert settings["temperature"] == 1.0


# ── claude-code model names ───────────────────────────────────────────


class TestClaudeCodeModelThinking:
    """Tests that claude-code-* model names also get temperature coercion.

    claude-code models start with "claude-code" rather than "claude-", but the
    model name embedded after the prefix (e.g. claude-code-claude-opus-4-5-20251101)
    triggers default thinking behavior, which should coerce temperature to 1.0.
    """

    @patch(_SUPPORTS, return_value=False)
    @patch(_GET_YOLO, return_value=True)
    @patch(
        _GET_EFFECTIVE,
        return_value={"temperature": 0.3, "extended_thinking": "enabled"},
    )
    @patch(
        _LOAD_CONFIG,
        return_value={
            "claude-code-claude-opus-4-5-20251101": {
                "type": "anthropic",
                "name": "claude-opus-4-5-20251101",
                "context_length": 200000,
            }
        },
    )
    def test_claude_code_model_temp_coerced(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports
    ):
        """claude-code-* model with thinking enabled coerces temperature to 1.0."""
        settings = make_model_settings("claude-code-claude-opus-4-5-20251101")
        assert settings["temperature"] == 1.0


# ── Warning emission on coercion ───────────────────────────────────────


class TestAnthropicThinkingTemperatureWarning:
    """Tests that emit_warning is called when temperature is overridden."""

    @patch("code_puppy.model_factory.emit_warning")
    @patch(_SUPPORTS, return_value=False)
    @patch(_GET_YOLO, return_value=True)
    @patch(
        _GET_EFFECTIVE,
        return_value={"temperature": 0.7, "extended_thinking": "enabled"},
    )
    @patch(_LOAD_CONFIG, return_value=_claude_config())
    def test_warning_emitted_when_temp_overridden(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_warn
    ):
        """A warning must be emitted when the user's temperature is coerced."""
        settings = make_model_settings("claude-sonnet-4-20250514")
        assert settings["temperature"] == 1.0
        mock_warn.assert_called_once()
        warn_msg = mock_warn.call_args[0][0]
        assert "overriding temperature" in warn_msg.lower()
        assert "0.7" in warn_msg
        assert "1.0" in warn_msg

    @patch("code_puppy.model_factory.emit_warning")
    @patch(_SUPPORTS, return_value=False)
    @patch(_GET_YOLO, return_value=True)
    @patch(
        _GET_EFFECTIVE,
        return_value={"temperature": 1.0, "extended_thinking": "enabled"},
    )
    @patch(_LOAD_CONFIG, return_value=_claude_config())
    def test_no_warning_when_temp_already_1(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_warn
    ):
        """No warning when temperature is already 1.0 and thinking is active."""
        settings = make_model_settings("claude-sonnet-4-20250514")
        assert settings["temperature"] == 1.0
        # emit_warning may be called for other reasons; verify no coercion warning
        for call in mock_warn.call_args_list:
            msg = call[0][0]
            assert "overriding temperature" not in msg.lower()

    @patch("code_puppy.model_factory.emit_warning")
    @patch(_SUPPORTS, return_value=False)
    @patch(_GET_YOLO, return_value=True)
    @patch(
        _GET_EFFECTIVE,
        return_value={"extended_thinking": "enabled"},
    )
    @patch(_LOAD_CONFIG, return_value=_claude_config())
    def test_no_warning_when_no_temp_set(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_warn
    ):
        """No coercion warning when temperature is not explicitly set."""
        settings = make_model_settings("claude-sonnet-4-20250514")
        assert settings["temperature"] == 1.0
        for call in mock_warn.call_args_list:
            msg = call[0][0]
            assert "overriding temperature" not in msg.lower()


# ── Legacy boolean extended_thinking values ────────────────────────────


class TestAnthropicLegacyBooleanThinking:
    """Tests that legacy boolean extended_thinking values still work correctly."""

    @patch("code_puppy.model_factory.emit_warning")
    @patch(_SUPPORTS, return_value=False)
    @patch(_GET_YOLO, return_value=True)
    @patch(
        _GET_EFFECTIVE,
        return_value={"temperature": 0.5, "extended_thinking": True},
    )
    @patch(_LOAD_CONFIG, return_value=_claude_config())
    def test_legacy_true_coerces_temp(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_warn
    ):
        """Legacy extended_thinking=True should coerce temperature to 1.0."""
        settings = make_model_settings("claude-sonnet-4-20250514")
        assert settings["temperature"] == 1.0
        # Should emit coercion warning since 0.5 != 1.0
        coercion_warnings = [
            c for c in mock_warn.call_args_list if "overriding temperature" in c[0][0].lower()
        ]
        assert len(coercion_warnings) == 1

    @patch(_SUPPORTS, return_value=False)
    @patch(_GET_YOLO, return_value=True)
    @patch(
        _GET_EFFECTIVE,
        return_value={"temperature": 0.5, "extended_thinking": False},
    )
    @patch(_LOAD_CONFIG, return_value=_claude_config())
    def test_legacy_false_preserves_temp(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports
    ):
        """Legacy extended_thinking=False should preserve user temperature."""
        settings = make_model_settings("claude-sonnet-4-20250514")
        assert settings["temperature"] == 0.5


# ── top_p stripping still works ────────────────────────────────────────


class TestAnthropicTopPStripping:
    """Verify existing top_p stripping behavior is preserved."""

    @patch(_SUPPORTS, return_value=False)
    @patch(_GET_YOLO, return_value=True)
    @patch(
        _GET_EFFECTIVE,
        return_value={"top_p": 0.9, "extended_thinking": "enabled"},
    )
    @patch(_LOAD_CONFIG, return_value=_claude_config())
    def test_top_p_stripped_for_anthropic(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports
    ):
        """top_p should be removed from Anthropic model settings."""
        settings = make_model_settings("claude-sonnet-4-20250514")
        assert "top_p" not in settings
