"""Tests for make_model_settings() GPT-5 / OpenAI Responses API alignment (bd-145).

Covers:
- _is_chatgpt_oauth / _uses_responses_api helpers
- max_tokens skipped for chatgpt_oauth but resolved for budgeting
- openai_reasoning_summary gated by model_supports_setting
- openai_text_verbosity gated by model_supports_setting (Responses path)
- Chat-completions extra_body verbosity preserves existing entries
- gpt-5-codex openai+codex Responses path behavior
"""

from unittest.mock import patch

from code_puppy.model_factory import (
    _is_chatgpt_oauth,
    _uses_responses_api,
    make_model_settings,
)


# ── Helper function tests ────────────────────────────────────────────


class TestIsChatgptOauth:
    """Tests for the _is_chatgpt_oauth helper."""

    def test_true_for_chatgpt_oauth_type(self):
        assert _is_chatgpt_oauth({"type": "chatgpt_oauth"}) is True

    def test_false_for_openai_type(self):
        assert _is_chatgpt_oauth({"type": "openai"}) is False

    def test_false_for_custom_openai_type(self):
        assert _is_chatgpt_oauth({"type": "custom_openai"}) is False

    def test_false_for_missing_type(self):
        assert _is_chatgpt_oauth({}) is False

    def test_false_for_none_type(self):
        assert _is_chatgpt_oauth({"type": None}) is False


class TestUsesResponsesApi:
    """Tests for the _uses_responses_api helper."""

    def test_true_for_chatgpt_oauth(self):
        assert _uses_responses_api("gpt-5.2", {"type": "chatgpt_oauth"}) is True

    def test_true_for_openai_codex(self):
        assert _uses_responses_api("gpt-5-codex", {"type": "openai"}) is True

    def test_true_for_custom_openai_codex(self):
        assert _uses_responses_api("gpt-5-codex", {"type": "custom_openai"}) is True

    def test_false_for_plain_openai(self):
        assert _uses_responses_api("gpt-5.2", {"type": "openai"}) is False

    def test_false_for_custom_openai_no_codex(self):
        assert _uses_responses_api("gpt-5.2", {"type": "custom_openai"}) is False


# ── Patch targets for make_model_settings isolation ───────────────────

_LOAD_CONFIG = "code_puppy.model_factory.ModelFactory.load_config"
_GET_EFFECTIVE = "code_puppy.model_factory._config_module.get_effective_model_settings"
_GET_YOLO = "code_puppy.model_factory.get_yolo_mode"
_SUPPORTS = "code_puppy.model_factory._config_module.model_supports_setting"
_REASONING_EFFORT = (
    "code_puppy.model_factory._config_module.get_openai_reasoning_effort"
)
_REASONING_SUMMARY = (
    "code_puppy.model_factory._config_module.get_openai_reasoning_summary"
)
_VERBOSITY = "code_puppy.model_factory._config_module.get_openai_verbosity"

# pydantic-ai settings classes are TypedDicts; make_model_settings returns plain dicts.
# We check dict keys/values directly instead of using isinstance.


def _supports_summary_only(model_name, setting):
    """side_effect: only 'summary' is supported."""
    return setting == "summary"


def _supports_summary_and_verbosity(model_name, setting):
    """side_effect: 'summary' and 'verbosity' are both supported."""
    return setting in ("summary", "verbosity")


def _supports_nothing(model_name, setting):
    """side_effect: no setting is supported."""
    return False


def _supports_verbosity_only(model_name, setting):
    """side_effect: only 'verbosity' is supported."""
    return setting == "verbosity"


# ── chatgpt_oauth (Codex OAuth backend) ──────────────────────────────


class TestMakeModelSettingsChatgptOauth:
    """Tests for chatgpt_oauth-specific behavior in make_model_settings."""

    @patch(_VERBOSITY, return_value="medium")
    @patch(_REASONING_SUMMARY, return_value="auto")
    @patch(_REASONING_EFFORT, return_value="medium")
    @patch(_SUPPORTS, side_effect=_supports_summary_and_verbosity)
    @patch(_GET_YOLO, return_value=True)
    @patch(_GET_EFFECTIVE, return_value={})
    @patch(
        _LOAD_CONFIG,
        return_value={
            "chatgpt-gpt-5.2": {
                "type": "chatgpt_oauth",
                "name": "gpt-5.2",
                "context_length": 200000,
            }
        },
    )
    def test_max_tokens_not_in_settings_for_chatgpt_oauth(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_effort, mock_summary, mock_verb
    ):
        """chatgpt_oauth models should NOT have max_tokens in their settings dict."""
        settings = make_model_settings("chatgpt-gpt-5.2")
        assert "max_tokens" not in settings

    @patch(_VERBOSITY, return_value="medium")
    @patch(_REASONING_SUMMARY, return_value="auto")
    @patch(_REASONING_EFFORT, return_value="medium")
    @patch(_SUPPORTS, side_effect=_supports_summary_and_verbosity)
    @patch(_GET_YOLO, return_value=True)
    @patch(_GET_EFFECTIVE, return_value={})
    @patch(
        _LOAD_CONFIG,
        return_value={
            "chatgpt-gpt-5.2": {
                "type": "chatgpt_oauth",
                "name": "gpt-5.2",
                "context_length": 200000,
            }
        },
    )
    def test_reasoning_effort_present_for_chatgpt_oauth(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_effort, mock_summary, mock_verb
    ):
        """chatgpt_oauth models should have openai_reasoning_effort."""
        settings = make_model_settings("chatgpt-gpt-5.2")
        assert settings.get("openai_reasoning_effort") == "medium"

    @patch(_VERBOSITY, return_value="medium")
    @patch(_REASONING_SUMMARY, return_value="auto")
    @patch(_REASONING_EFFORT, return_value="medium")
    @patch(_SUPPORTS, side_effect=_supports_summary_and_verbosity)
    @patch(_GET_YOLO, return_value=True)
    @patch(_GET_EFFECTIVE, return_value={})
    @patch(
        _LOAD_CONFIG,
        return_value={
            "chatgpt-gpt-5.2": {
                "type": "chatgpt_oauth",
                "name": "gpt-5.2",
                "context_length": 200000,
            }
        },
    )
    def test_reasoning_summary_included_when_supported(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_effort, mock_summary, mock_verb
    ):
        """openai_reasoning_summary should be set when model_supports_setting('summary') is True."""
        settings = make_model_settings("chatgpt-gpt-5.2")
        assert settings.get("openai_reasoning_summary") == "auto"
        mock_supports.assert_any_call("chatgpt-gpt-5.2", "summary")

    @patch(_VERBOSITY, return_value="medium")
    @patch(_REASONING_SUMMARY, return_value="auto")
    @patch(_REASONING_EFFORT, return_value="medium")
    @patch(_SUPPORTS, side_effect=_supports_nothing)
    @patch(_GET_YOLO, return_value=True)
    @patch(_GET_EFFECTIVE, return_value={})
    @patch(
        _LOAD_CONFIG,
        return_value={
            "chatgpt-gpt-5.2": {
                "type": "chatgpt_oauth",
                "name": "gpt-5.2",
                "context_length": 200000,
            }
        },
    )
    def test_reasoning_summary_excluded_when_not_supported(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_effort, mock_summary, mock_verb
    ):
        """openai_reasoning_summary should NOT be set when model_supports_setting('summary') is False."""
        settings = make_model_settings("chatgpt-gpt-5.2")
        assert "openai_reasoning_summary" not in settings

    @patch(_VERBOSITY, return_value="medium")
    @patch(_REASONING_SUMMARY, return_value="auto")
    @patch(_REASONING_EFFORT, return_value="medium")
    @patch(_SUPPORTS, side_effect=_supports_summary_and_verbosity)
    @patch(_GET_YOLO, return_value=True)
    @patch(_GET_EFFECTIVE, return_value={})
    @patch(
        _LOAD_CONFIG,
        return_value={
            "chatgpt-gpt-5.2": {
                "type": "chatgpt_oauth",
                "name": "gpt-5.2",
                "context_length": 200000,
            }
        },
    )
    def test_text_verbosity_present_when_supported(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_effort, mock_summary, mock_verb
    ):
        """Responses path: openai_text_verbosity set when model_supports_setting('verbosity') is True."""
        settings = make_model_settings("chatgpt-gpt-5.2")
        assert settings.get("openai_text_verbosity") == "medium"
        mock_supports.assert_any_call("chatgpt-gpt-5.2", "verbosity")

    @patch(_VERBOSITY, return_value="medium")
    @patch(_REASONING_SUMMARY, return_value="auto")
    @patch(_REASONING_EFFORT, return_value="medium")
    @patch(_SUPPORTS, side_effect=_supports_summary_only)
    @patch(_GET_YOLO, return_value=True)
    @patch(_GET_EFFECTIVE, return_value={})
    @patch(
        _LOAD_CONFIG,
        return_value={
            "chatgpt-gpt-5.2": {
                "type": "chatgpt_oauth",
                "name": "gpt-5.2",
                "context_length": 200000,
            }
        },
    )
    def test_text_verbosity_absent_when_not_supported(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_effort, mock_summary, mock_verb
    ):
        """Responses path: openai_text_verbosity NOT set when model_supports_setting('verbosity') is False."""
        settings = make_model_settings("chatgpt-gpt-5.2")
        assert "openai_text_verbosity" not in settings


# ── openai+codex (Responses path via OpenAI codex model) ─────────────


class TestMakeModelSettingsOpenAICodex:
    """Tests for openai-type GPT-5 codex model (Responses API path).

    The key distinction: 'codex' is in the model name but type is 'openai',
    so it uses the Responses path rather than Chat Completions. Summary and
    text verbosity remain capability-gated via model_supports_setting().
    """

    @patch(_VERBOSITY, return_value="high")
    @patch(_REASONING_SUMMARY, return_value="auto")
    @patch(_REASONING_EFFORT, return_value="medium")
    @patch(_SUPPORTS, side_effect=_supports_summary_and_verbosity)
    @patch(_GET_YOLO, return_value=True)
    @patch(_GET_EFFECTIVE, return_value={})
    @patch(
        _LOAD_CONFIG,
        return_value={
            "gpt-5-codex": {
                "type": "openai",
                "name": "gpt-5-codex",
                "context_length": 200000,
            }
        },
    )
    def test_codex_summary_set_when_supported(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_effort, mock_summary, mock_verb
    ):
        """Codex model: summary is set when model_supports_setting('summary') is True."""
        settings = make_model_settings("gpt-5-codex")
        assert settings.get("openai_reasoning_summary") == "auto"
        mock_supports.assert_any_call("gpt-5-codex", "summary")

    @patch(_VERBOSITY, return_value="high")
    @patch(_REASONING_SUMMARY, return_value="auto")
    @patch(_REASONING_EFFORT, return_value="medium")
    @patch(_SUPPORTS, side_effect=_supports_nothing)
    @patch(_GET_YOLO, return_value=True)
    @patch(_GET_EFFECTIVE, return_value={})
    @patch(
        _LOAD_CONFIG,
        return_value={
            "gpt-5-codex": {
                "type": "openai",
                "name": "gpt-5-codex",
                "context_length": 200000,
            }
        },
    )
    def test_codex_summary_absent_when_not_supported(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_effort, mock_summary, mock_verb
    ):
        """Codex model: summary is NOT set when model_supports_setting('summary') is False."""
        settings = make_model_settings("gpt-5-codex")
        assert "openai_reasoning_summary" not in settings

    @patch(_VERBOSITY, return_value="high")
    @patch(_REASONING_SUMMARY, return_value="auto")
    @patch(_REASONING_EFFORT, return_value="medium")
    @patch(_SUPPORTS, side_effect=_supports_summary_and_verbosity)
    @patch(_GET_YOLO, return_value=True)
    @patch(_GET_EFFECTIVE, return_value={})
    @patch(
        _LOAD_CONFIG,
        return_value={
            "gpt-5-codex": {
                "type": "openai",
                "name": "gpt-5-codex",
                "context_length": 200000,
            }
        },
    )
    def test_codex_no_extra_body_verbosity(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_effort, mock_summary, mock_verb
    ):
        """Codex model: Responses path should NOT use extra_body['verbosity']."""
        settings = make_model_settings("gpt-5-codex")
        assert "extra_body" not in settings

    @patch(_VERBOSITY, return_value="high")
    @patch(_REASONING_SUMMARY, return_value="auto")
    @patch(_REASONING_EFFORT, return_value="medium")
    @patch(_SUPPORTS, side_effect=_supports_summary_and_verbosity)
    @patch(_GET_YOLO, return_value=True)
    @patch(_GET_EFFECTIVE, return_value={})
    @patch(
        _LOAD_CONFIG,
        return_value={
            "gpt-5-codex": {
                "type": "openai",
                "name": "gpt-5-codex",
                "context_length": 200000,
            }
        },
    )
    def test_codex_max_tokens_present(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_effort, mock_summary, mock_verb
    ):
        """Codex openai model (non-chatgpt_oauth) should still have max_tokens."""
        settings = make_model_settings("gpt-5-codex")
        assert "max_tokens" in settings
        assert settings["max_tokens"] > 0

    @patch(_VERBOSITY, return_value="high")
    @patch(_REASONING_SUMMARY, return_value="auto")
    @patch(_REASONING_EFFORT, return_value="medium")
    @patch(_SUPPORTS, side_effect=_supports_summary_and_verbosity)
    @patch(_GET_YOLO, return_value=True)
    @patch(_GET_EFFECTIVE, return_value={})
    @patch(
        _LOAD_CONFIG,
        return_value={
            "gpt-5-codex": {
                "type": "openai",
                "name": "gpt-5-codex",
                "context_length": 200000,
            }
        },
    )
    def test_codex_text_verbosity_present_when_supported(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_effort, mock_summary, mock_verb
    ):
        """Codex Responses path: openai_text_verbosity is set when supported."""
        settings = make_model_settings("gpt-5-codex")
        assert settings.get("openai_text_verbosity") == "high"
        mock_supports.assert_any_call("gpt-5-codex", "verbosity")


# ── Chat Completions GPT-5 (non-Responses) ───────────────────────────


class TestMakeModelSettingsChatCompletionsGpt5:
    """Tests for non-Responses GPT-5 models (Chat Completions path)."""

    @patch(_VERBOSITY, return_value="high")
    @patch(_REASONING_EFFORT, return_value="medium")
    @patch(_SUPPORTS, side_effect=_supports_verbosity_only)
    @patch(_GET_YOLO, return_value=True)
    @patch(_GET_EFFECTIVE, return_value={})
    @patch(
        _LOAD_CONFIG,
        return_value={
            "gpt-5.2": {
                "type": "openai",
                "name": "gpt-5.2",
                "context_length": 200000,
            }
        },
    )
    def test_extra_body_verbosity_injected(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_effort, mock_verb
    ):
        """Chat-completions GPT-5 should get verbosity in extra_body when supported."""
        settings = make_model_settings("gpt-5.2")
        extra_body = settings.get("extra_body")
        assert extra_body is not None
        assert extra_body.get("verbosity") == "high"
        mock_supports.assert_any_call("gpt-5.2", "verbosity")

    @patch(_VERBOSITY, return_value="high")
    @patch(_REASONING_EFFORT, return_value="medium")
    @patch(_SUPPORTS, side_effect=_supports_nothing)
    @patch(_GET_YOLO, return_value=True)
    @patch(_GET_EFFECTIVE, return_value={})
    @patch(
        _LOAD_CONFIG,
        return_value={
            "gpt-5.2": {
                "type": "openai",
                "name": "gpt-5.2",
                "context_length": 200000,
            }
        },
    )
    def test_extra_body_verbosity_gated_by_supports(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_effort, mock_verb
    ):
        """Chat-completions GPT-5 should NOT get verbosity when unsupported."""
        settings = make_model_settings("gpt-5.2")
        extra_body = settings.get("extra_body")
        assert extra_body is None or "verbosity" not in extra_body

    @patch(_VERBOSITY, return_value="high")
    @patch(_REASONING_EFFORT, return_value="medium")
    @patch(_SUPPORTS, side_effect=_supports_verbosity_only)
    @patch(_GET_YOLO, return_value=True)
    @patch(_GET_EFFECTIVE, return_value={"extra_body": {"existing_key": "kept"}})
    @patch(
        _LOAD_CONFIG,
        return_value={
            "gpt-5.2": {
                "type": "openai",
                "name": "gpt-5.2",
                "context_length": 200000,
            }
        },
    )
    def test_extra_body_preserves_existing_entries(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_effort, mock_verb
    ):
        """Chat-completions extra_body should preserve existing entries from effective_settings."""
        settings = make_model_settings("gpt-5.2")
        extra_body = settings.get("extra_body")
        assert extra_body is not None
        assert extra_body.get("existing_key") == "kept"
        assert extra_body.get("verbosity") == "high"

    @patch(_VERBOSITY, return_value="high")
    @patch(_REASONING_EFFORT, return_value="medium")
    @patch(_SUPPORTS, side_effect=_supports_verbosity_only)
    @patch(_GET_YOLO, return_value=True)
    @patch(_GET_EFFECTIVE, return_value={})
    @patch(
        _LOAD_CONFIG,
        return_value={
            "gpt-5.2": {
                "type": "openai",
                "name": "gpt-5.2",
                "context_length": 200000,
            }
        },
    )
    def test_max_tokens_present_for_non_oauth(
        self, mock_cfg, mock_eff, mock_yolo, mock_supports, mock_effort, mock_verb
    ):
        """Non-chatgpt_oauth models should still have max_tokens in settings."""
        settings = make_model_settings("gpt-5.2")
        assert "max_tokens" in settings
        assert settings["max_tokens"] > 0


class TestMakeModelSettingsNonGpt5:
    """Quick sanity check that non-GPT-5 models are unaffected."""

    @patch(_GET_YOLO, return_value=True)
    @patch(_GET_EFFECTIVE, return_value={})
    @patch(_LOAD_CONFIG, return_value={"some-model": {"context_length": 128000}})
    def test_generic_model_has_max_tokens(self, mock_cfg, mock_eff, mock_yolo):
        """Non-GPT-5 / non-Anthropic models still get max_tokens."""
        settings = make_model_settings("some-model")
        assert "max_tokens" in settings
        assert settings["max_tokens"] > 0
