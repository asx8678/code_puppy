import json
import logging
import os
import pathlib
from typing import Any, Callable

# Light pydantic-ai imports needed at module scope for make_model_settings()
from pydantic_ai.models.anthropic import AnthropicModelSettings
from pydantic_ai.models.openai import OpenAIChatModelSettings
from pydantic_ai.settings import ModelSettings

from code_puppy.messaging import emit_warning

from . import callbacks
from .config import EXTRA_MODELS_FILE, get_value, get_yolo_mode
from .http_utils import create_async_client, get_cert_bundle_path, get_http2
from .provider_identity import resolve_provider_identity

# Heavy SDK imports are deferred to builder functions to reduce startup time.
# See _build_anthropic(), _build_openai(), etc.

# Token calculation constants
_OUTPUT_TOKEN_RATIO = 0.15
_MIN_OUTPUT_TOKENS = 2048
_MAX_OUTPUT_TOKENS = 65536

logger = logging.getLogger(__name__)

# Registry for custom model provider classes from plugins
_CUSTOM_MODEL_PROVIDERS: dict[str, type] = {}


_providers_loaded = False


def _load_plugin_model_providers():
    """Load custom model providers from plugins (lazy, called on first use)."""
    global _CUSTOM_MODEL_PROVIDERS, _providers_loaded
    if _providers_loaded:
        return
    _providers_loaded = True
    try:
        from code_puppy.callbacks import on_register_model_providers

        results = on_register_model_providers()
        for result in results:
            if isinstance(result, dict):
                _CUSTOM_MODEL_PROVIDERS.update(result)
    except Exception as e:
        logger.warning("Failed to load plugin model providers: %s", e)


# Registry for model builder functions: model_type -> builder callable
# Signature: builder(model_name: str, model_config: dict, config: dict) -> Any
_MODEL_BUILDERS: dict[str, Callable] = {}


def register_model_builder(type_name: str, builder: Callable) -> None:
    """Register a builder function for a model type.

    The builder must have the signature:
        builder(model_name: str, model_config: dict, config: dict) -> Any

    Built-in model types are registered at module load. Plugins can call this
    function to add or override builders for additional model types.

    Args:
        type_name: The model type string (e.g. "openai", "anthropic").
        builder: Callable that constructs and returns the model instance.
    """
    _MODEL_BUILDERS[type_name] = builder


# Anthropic beta header required for 1M context window support.
CONTEXT_1M_BETA = "context-1m-2025-08-07"


def _build_anthropic_beta_header(
    model_config: dict,
    *,
    interleaved_thinking: bool = False) -> str | None:
    """Build the anthropic-beta header value for an Anthropic model.

    Combines beta flags based on model capabilities:
    - interleaved-thinking-2025-05-14  (when interleaved_thinking is enabled)
    - context-1m-2025-08-07            (when context_length >= 1_000_000)

    Returns None if no beta flags are needed.
    """
    parts: list[str] = []
    if interleaved_thinking:
        parts.append("interleaved-thinking-2025-05-14")
    if model_config.get("context_length", 0) >= 1_000_000:
        parts.append(CONTEXT_1M_BETA)
    return ",".join(parts) if parts else None


def get_api_key(env_var_name: str) -> str | None:
    """Get an API key from config first, then fall back to environment variable.

    This allows users to set API keys via `/set KIMI_API_KEY=xxx` in addition to
    setting them as environment variables.

    Args:
        env_var_name: The name of the environment variable (e.g., "OPENAI_API_KEY")

    Returns:
        The API key value, or None if not found in either config or environment.
    """
    # First check config (case-insensitive key lookup)
    config_value = get_value(env_var_name.lower())
    if config_value:
        return config_value

    # Fall back to environment variable
    return os.environ.get(env_var_name)


def make_model_settings(
    model_name: str, max_tokens: int | None = None
) -> ModelSettings:
    """Create appropriate ModelSettings for a given model.

    This handles model-specific settings:
    - GPT-5 models: reasoning_effort and verbosity (non-codex only)
    - Claude/Anthropic models: extended_thinking and budget_tokens
    - Automatic max_tokens calculation based on model context length

    Args:
        model_name: The name of the model to create settings for.
        max_tokens: Optional max tokens limit. If None, automatically calculated
            as: max(2048, min(15% of context_length, 65536))

    Returns:
        Appropriate ModelSettings subclass instance for the model.
    """
    from code_puppy.config import (
        get_effective_model_settings,
        get_openai_reasoning_effort,
        get_openai_reasoning_summary,
        get_openai_verbosity,
        model_supports_setting)

    model_settings_dict: dict = {}

    # Calculate max_tokens if not explicitly provided
    model_config: dict[str, Any] = {}
    if max_tokens is None:
        # Load model config to get context length
        try:
            models_config = ModelFactory.load_config()
            model_config = models_config.get(model_name, {})
            context_length = model_config.get("context_length", 128000)
        except Exception:
            # Fallback if config loading fails (e.g., in CI environments)
            context_length = 128000
        # min _MIN_OUTPUT_TOKENS, _OUTPUT_TOKEN_RATIO of context, max _MAX_OUTPUT_TOKENS
        max_tokens = max(
            _MIN_OUTPUT_TOKENS,
            min(int(_OUTPUT_TOKEN_RATIO * context_length), _MAX_OUTPUT_TOKENS))

    model_settings_dict["max_tokens"] = max_tokens
    effective_settings = get_effective_model_settings(model_name)
    model_settings_dict.update(effective_settings)

    # Disable parallel tool calls when yolo_mode is off (sequential so user can review each call)
    if not get_yolo_mode():
        model_settings_dict["parallel_tool_calls"] = False

    # Default to clear_thinking=False for GLM-4.7 and GLM-5 models (preserved thinking)
    if "glm-4.7" in model_name.lower() or "glm-5" in model_name.lower():
        clear_thinking = effective_settings.get("clear_thinking", False)
        model_settings_dict["thinking"] = {
            "type": "enabled",
            "clear_thinking": clear_thinking,
        }

    model_settings: ModelSettings = ModelSettings(**model_settings_dict)

    if "gpt-5" in model_name:
        model_settings_dict["openai_reasoning_effort"] = get_openai_reasoning_effort()

        model_type = model_config.get("type")
        uses_responses_api = (
            model_type == "chatgpt_oauth"
            or (model_type == "openai" and "codex" in model_name)
            or (model_type == "custom_openai" and "codex" in model_name)
        )

        if uses_responses_api:
            model_settings_dict["openai_reasoning_summary"] = (
                get_openai_reasoning_summary()
            )
            if "codex" not in model_name:
                model_settings_dict["openai_text_verbosity"] = get_openai_verbosity()
            model_settings = OpenAIResponsesModelSettings(**model_settings_dict)
        else:
            # Chat Completions models don't support configurable reasoning summaries.
            # Keep the old verbosity injection path for non-Responses GPT-5 models.
            if "codex" not in model_name:
                verbosity = get_openai_verbosity()
                model_settings_dict["extra_body"] = {"verbosity": verbosity}
            model_settings = OpenAIChatModelSettings(**model_settings_dict)
    elif model_name.startswith("claude-") or model_name.startswith("anthropic-"):
        # Handle Anthropic extended thinking settings
        # Remove top_p as Anthropic doesn't support it with extended thinking
        model_settings_dict.pop("top_p", None)

        # Claude extended thinking requires temperature=1.0 (API restriction)
        # Default to 1.0 if not explicitly set by user
        if model_settings_dict.get("temperature") is None:
            model_settings_dict["temperature"] = 1.0

        from code_puppy.model_utils import get_default_extended_thinking

        default_thinking = get_default_extended_thinking(model_name)
        extended_thinking = effective_settings.get(
            "extended_thinking", default_thinking
        )
        # Backwards compat: handle legacy boolean values
        if extended_thinking is True:
            extended_thinking = "enabled"
        elif extended_thinking is False:
            extended_thinking = "off"

        budget_tokens = effective_settings.get("budget_tokens", 10000)
        if extended_thinking in ("enabled", "adaptive"):
            model_settings_dict["anthropic_thinking"] = {
                "type": extended_thinking,
            }
            # Only send budget_tokens for classic "enabled" mode
            if extended_thinking == "enabled" and budget_tokens:
                model_settings_dict["anthropic_thinking"]["budget_tokens"] = (
                    budget_tokens
                )

        # Opus 4-6 models support the `effort` setting via output_config.
        # pydantic-ai doesn't have a native field for output_config yet,
        # so we inject it through extra_body which gets merged into the
        # HTTP request body.
        if model_supports_setting(model_name, "effort"):
            effort = effective_settings.get("effort", "high")
            if "anthropic_thinking" in model_settings_dict:
                extra_body = model_settings_dict.get("extra_body") or {}
                extra_body["output_config"] = {"effort": effort}
                model_settings_dict["extra_body"] = extra_body

        model_settings = AnthropicModelSettings(**model_settings_dict)

    # Handle Gemini thinking models (Gemini-3)
    # Check if model supports thinking settings and apply defaults
    if model_supports_setting(model_name, "thinking_level"):
        # Apply defaults if not explicitly set by user
        # Default: thinking_enabled=True, thinking_level="low"
        if "thinking_enabled" not in model_settings_dict:
            model_settings_dict["thinking_enabled"] = True
        if "thinking_level" not in model_settings_dict:
            model_settings_dict["thinking_level"] = "low"
        # Recreate settings with Gemini thinking config
        model_settings = ModelSettings(**model_settings_dict)

    return model_settings


from pydantic_ai.models.openai import OpenAIChatModel as _OpenAIChatModel


class ZaiChatModel(_OpenAIChatModel):
    def _process_response(self, response):
        response.object = "chat.completion"
        return super()._process_response(response)


def get_custom_config(model_config):
    custom_config = model_config.get("custom_endpoint", {})
    if not custom_config:
        raise ValueError("Custom model requires 'custom_endpoint' configuration")

    url = custom_config.get("url")
    if not url:
        raise ValueError("Custom endpoint requires 'url' field")

    headers = {}
    for key, value in custom_config.get("headers", {}).items():
        if value.startswith("$"):
            env_var_name = value[1:]
            resolved_value = get_api_key(env_var_name)
            if resolved_value is None:
                emit_warning(
                    f"'{env_var_name}' is not set (check config or environment) for custom endpoint header '{key}'. Proceeding with empty value."
                )
                resolved_value = ""
            value = resolved_value
        elif "$" in value:
            tokens = value.split(" ")
            resolved_values = []
            for token in tokens:
                if token.startswith("$"):
                    env_var = token[1:]
                    resolved_value = get_api_key(env_var)
                    if resolved_value is None:
                        emit_warning(
                            f"'{env_var}' is not set (check config or environment) for custom endpoint header '{key}'. Proceeding with empty value."
                        )
                        resolved_values.append("")
                    else:
                        resolved_values.append(resolved_value)
                else:
                    resolved_values.append(token)
            value = " ".join(resolved_values)
        headers[key] = value
    api_key = None
    if "api_key" in custom_config:
        if custom_config["api_key"].startswith("$"):
            env_var_name = custom_config["api_key"][1:]
            api_key = get_api_key(env_var_name)
            if api_key is None:
                emit_warning(
                    f"API key '{env_var_name}' is not set (checked config and environment); proceeding without API key."
                )
        else:
            api_key = custom_config["api_key"]
    if "ca_certs_path" in custom_config:
        verify = custom_config["ca_certs_path"]
    else:
        verify = None
    return url, headers, verify, api_key


# ---------------------------------------------------------------------------
# Built-in model builder functions
# Each function has the signature:
#   builder(model_name: str, model_config: dict, config: dict) -> Any
# ---------------------------------------------------------------------------


def _require_api_key(env_var: str, model_config: dict) -> str | None:
    """Get an API key, emitting a warning and returning None if not found.

    This DRYs up the repeated pattern across 10+ model builder functions.
    """
    key = get_api_key(env_var)
    if not key:
        emit_warning(
            f"{env_var} is not set (check config or environment); "
            f"skipping model '{model_config.get('name')}'."
        )
    return key


def _build_gemini(model_name: str, model_config: dict, config: dict) -> Any:
    from code_puppy.gemini_model import GeminiModel

    api_key = _require_api_key("GEMINI_API_KEY", model_config)
    if not api_key:
        return None
    return GeminiModel(model_name=model_config["name"], api_key=api_key)


def _build_openai(model_name: str, model_config: dict, config: dict) -> Any:
    from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
    from pydantic_ai.providers.openai import OpenAIProvider

    api_key = _require_api_key("OPENAI_API_KEY", model_config)
    if not api_key:
        return None
    provider = OpenAIProvider(api_key=api_key)
    if "codex" in model_name:
        model = OpenAIResponsesModel(model_name=model_config["name"], provider=provider)
    else:
        model = OpenAIChatModel(model_name=model_config["name"], provider=provider)
    model.provider = provider
    return model


def _build_anthropic(model_name: str, model_config: dict, config: dict) -> Any:
    from anthropic import AsyncAnthropic
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider
    from code_puppy.claude_cache_client import ClaudeCacheAsyncClient, patch_anthropic_client_messages

    api_key = _require_api_key("ANTHROPIC_API_KEY", model_config)
    if not api_key:
        return None

    verify = get_cert_bundle_path()
    http2_enabled = get_http2()

    client = ClaudeCacheAsyncClient(
        verify=verify,
        timeout=180,
        http2=http2_enabled)

    from code_puppy.config import get_effective_model_settings

    effective_settings = get_effective_model_settings(model_name)
    interleaved_thinking = effective_settings.get("interleaved_thinking", False)

    beta_header = _build_anthropic_beta_header(
        model_config, interleaved_thinking=interleaved_thinking
    )
    default_headers = {}
    if beta_header:
        default_headers["anthropic-beta"] = beta_header

    anthropic_client = AsyncAnthropic(
        api_key=api_key,
        http_client=client,
        default_headers=default_headers if default_headers else None)

    patch_anthropic_client_messages(anthropic_client)

    provider = AnthropicProvider(anthropic_client=anthropic_client)
    return AnthropicModel(model_name=model_config["name"], provider=provider)


def _build_custom_anthropic(model_name: str, model_config: dict, config: dict) -> Any:
    from anthropic import AsyncAnthropic
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider
    from code_puppy.claude_cache_client import ClaudeCacheAsyncClient, patch_anthropic_client_messages

    url, headers, verify, api_key = get_custom_config(model_config)
    if not api_key:
        emit_warning(
            f"API key is not set for custom Anthropic endpoint; skipping model '{model_config.get('name')}'."
        )
        return None

    if verify is None:
        verify = get_cert_bundle_path()

    http2_enabled = get_http2()

    client = ClaudeCacheAsyncClient(
        headers=headers,
        verify=verify,
        timeout=180,
        http2=http2_enabled)

    from code_puppy.config import get_effective_model_settings

    effective_settings = get_effective_model_settings(model_name)
    interleaved_thinking = effective_settings.get("interleaved_thinking", False)

    beta_header = _build_anthropic_beta_header(
        model_config, interleaved_thinking=interleaved_thinking
    )
    default_headers: dict = {}
    if beta_header:
        default_headers["anthropic-beta"] = beta_header

    anthropic_client = AsyncAnthropic(
        base_url=url,
        http_client=client,
        api_key=api_key,
        default_headers=default_headers if default_headers else None)

    patch_anthropic_client_messages(anthropic_client)

    provider = AnthropicProvider(anthropic_client=anthropic_client)
    return AnthropicModel(model_name=model_config["name"], provider=provider)


# NOTE: 'claude_code' model type is now handled by the claude_code_oauth plugin
# via the register_model_type callback. See plugins/claude_code_oauth/register_callbacks.py


def _build_azure_openai(model_name: str, model_config: dict, config: dict) -> Any:
    from openai import AsyncAzureOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    azure_endpoint_config = model_config.get("azure_endpoint")
    if not azure_endpoint_config:
        raise ValueError(
            "Azure OpenAI model type requires 'azure_endpoint' in its configuration."
        )
    azure_endpoint = azure_endpoint_config
    if azure_endpoint_config.startswith("$"):
        azure_endpoint = get_api_key(azure_endpoint_config[1:])
    if not azure_endpoint:
        emit_warning(
            f"Azure OpenAI endpoint '{azure_endpoint_config[1:] if azure_endpoint_config.startswith('$') else azure_endpoint_config}' not found (check config or environment); skipping model '{model_config.get('name')}'."
        )
        return None

    api_version_config = model_config.get("api_version")
    if not api_version_config:
        raise ValueError(
            "Azure OpenAI model type requires 'api_version' in its configuration."
        )
    api_version = api_version_config
    if api_version_config.startswith("$"):
        api_version = get_api_key(api_version_config[1:])
    if not api_version:
        emit_warning(
            f"Azure OpenAI API version '{api_version_config[1:] if api_version_config.startswith('$') else api_version_config}' not found (check config or environment); skipping model '{model_config.get('name')}'."
        )
        return None

    api_key_config = model_config.get("api_key")
    if not api_key_config:
        raise ValueError(
            "Azure OpenAI model type requires 'api_key' in its configuration."
        )
    api_key = api_key_config
    if api_key_config.startswith("$"):
        api_key = get_api_key(api_key_config[1:])
    if not api_key:
        emit_warning(
            f"Azure OpenAI API key '{api_key_config[1:] if api_key_config.startswith('$') else api_key_config}' not found (check config or environment); skipping model '{model_config.get('name')}'."
        )
        return None

    azure_max_retries = model_config.get("max_retries", 2)

    azure_client = AsyncAzureOpenAI(
        azure_endpoint=azure_endpoint,
        api_version=api_version,
        api_key=api_key,
        max_retries=azure_max_retries)
    provider = OpenAIProvider(openai_client=azure_client)
    model = OpenAIChatModel(model_name=model_config["name"], provider=provider)
    model.provider = provider
    return model


def _build_custom_openai(model_name: str, model_config: dict, config: dict) -> Any:
    from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
    from pydantic_ai.providers.openai import OpenAIProvider

    url, headers, verify, api_key = get_custom_config(model_config)
    client = create_async_client(headers=headers, verify=verify)
    provider_args: dict = dict(
        base_url=url,
        http_client=client)
    if api_key:
        provider_args["api_key"] = api_key
    provider = OpenAIProvider(**provider_args)
    if model_name == "chatgpt-gpt-5-codex":
        model = OpenAIResponsesModel(model_config["name"], provider=provider)
    else:
        model = OpenAIChatModel(model_name=model_config["name"], provider=provider)
    model.provider = provider
    return model


def _build_zai_coding(model_name: str, model_config: dict, config: dict) -> Any:
    from pydantic_ai.providers.openai import OpenAIProvider

    api_key = _require_api_key("ZAI_API_KEY", model_config)
    if not api_key:
        return None
    provider = OpenAIProvider(
        api_key=api_key,
        base_url="https://api.z.ai/api/coding/paas/v4")
    zai_model = ZaiChatModel(
        model_name=model_config["name"],
        provider=provider)
    zai_model.provider = provider
    return zai_model


def _build_zai_api(model_name: str, model_config: dict, config: dict) -> Any:
    from pydantic_ai.providers.openai import OpenAIProvider

    api_key = _require_api_key("ZAI_API_KEY", model_config)
    if not api_key:
        return None
    provider = OpenAIProvider(
        api_key=api_key,
        base_url="https://api.z.ai/api/paas/v4/")
    zai_model = ZaiChatModel(
        model_name=model_config["name"],
        provider=provider)
    zai_model.provider = provider
    return zai_model


# NOTE: 'antigravity' model type is now handled by the antigravity_oauth plugin
# via the register_model_type callback. See plugins/antigravity_oauth/register_callbacks.py


def _build_custom_gemini(model_name: str, model_config: dict, config: dict) -> Any:
    from code_puppy.gemini_model import GeminiModel

    # Backwards compatibility: delegate to antigravity plugin if antigravity flag is set
    # New configs use type="antigravity" directly, but old configs may have
    # type="custom_gemini" with antigravity=True
    if model_config.get("antigravity"):
        registered_handlers = callbacks.on_register_model_types()
        for handler_info in registered_handlers:
            handlers = (
                handler_info
                if isinstance(handler_info, list)
                else [handler_info]
                if handler_info
                else []
            )
            for handler_entry in handlers:
                if (
                    isinstance(handler_entry, dict)
                    and handler_entry.get("type") == "antigravity"
                ):
                    handler = handler_entry.get("handler")
                    if callable(handler):
                        try:
                            return handler(model_name, model_config, config)
                        except Exception as e:
                            logger.error(f"Antigravity handler failed: {e}")
                            return None
        # If no antigravity handler found, warn and return None
        emit_warning(
            f"Model '{model_config.get('name')}' has antigravity=True but antigravity plugin not loaded."
        )
        return None

    url, headers, verify, api_key = get_custom_config(model_config)
    if not api_key:
        emit_warning(
            f"API key is not set for custom Gemini endpoint; skipping model '{model_config.get('name')}'."
        )
        return None

    client = create_async_client(headers=headers, verify=verify)
    return GeminiModel(
        model_name=model_config["name"],
        api_key=api_key,
        base_url=url,
        http_client=client)


def _build_cerebras(model_name: str, model_config: dict, config: dict) -> Any:
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.profiles import ModelProfile
    from pydantic_ai.providers.cerebras import CerebrasProvider
    from pydantic_ai.providers.openai import OpenAIProvider

    # Define the provider subclass inline so that mocking CerebrasProvider in
    # tests still works correctly (matches original behaviour).
    class ZaiCerebrasProvider(CerebrasProvider):
        def model_profile(self, mn: str) -> ModelProfile | None:
            profile = super().model_profile(mn)
            if mn.startswith("zai"):
                from pydantic_ai.profiles.qwen import qwen_model_profile

                profile = profile.update(qwen_model_profile("qwen-3-coder"))
            return profile

    url, headers, verify, api_key = get_custom_config(model_config)
    if not api_key:
        emit_warning(
            f"API key is not set for Cerebras endpoint; skipping model '{model_config.get('name')}'."
        )
        return None
    # Add Cerebras 3rd party integration header
    headers["X-Cerebras-3rd-Party-Integration"] = "code-puppy"
    # Pass "cerebras" so RetryingAsyncClient knows to ignore Cerebras's
    # absurdly aggressive Retry-After headers (they send 60s!)
    client = create_async_client(headers=headers, verify=verify, model_name="cerebras")
    provider = ZaiCerebrasProvider(
        api_key=api_key,
        http_client=client)
    model = OpenAIChatModel(model_name=model_config["name"], provider=provider)
    model.provider = provider
    return model


def _build_openrouter(model_name: str, model_config: dict, config: dict) -> Any:
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openrouter import OpenRouterProvider

    api_key_config = model_config.get("api_key")
    api_key = None

    if api_key_config:
        if api_key_config.startswith("$"):
            env_var_name = api_key_config[1:]
            api_key = get_api_key(env_var_name)
            if api_key is None:
                emit_warning(
                    f"OpenRouter API key '{env_var_name}' not found (check config or environment); skipping model '{model_config.get('name')}'."
                )
                return None
        else:
            api_key = api_key_config
    else:
        api_key = get_api_key("OPENROUTER_API_KEY")
        if api_key is None:
            emit_warning(
                f"OPENROUTER_API_KEY is not set (check config or environment); skipping OpenRouter model '{model_config.get('name')}'."
            )
            return None

    provider = OpenRouterProvider(api_key=api_key)
    model = OpenAIChatModel(model_name=model_config["name"], provider=provider)
    model.provider = provider
    return model


def _build_gemini_oauth(model_name: str, model_config: dict, config: dict) -> Any:
    # Gemini OAuth models use the Code Assist API (cloudcode-pa.googleapis.com)
    try:
        try:
            from gemini_oauth.config import GEMINI_OAUTH_CONFIG
            from gemini_oauth.utils import (
                get_project_id,
                get_valid_access_token)
        except ImportError:
            from code_puppy.plugins.gemini_oauth.config import (
                GEMINI_OAUTH_CONFIG)
            from code_puppy.plugins.gemini_oauth.utils import (
                get_project_id,
                get_valid_access_token)
    except ImportError as exc:
        emit_warning(
            f"Gemini OAuth plugin not available; skipping model '{model_config.get('name')}'. "
            f"Error: {exc}"
        )
        return None

    access_token = get_valid_access_token()
    if not access_token:
        emit_warning(
            f"Failed to get valid Gemini OAuth token; skipping model '{model_config.get('name')}'. "
            "Run /gemini-auth to re-authenticate."
        )
        return None

    project_id = get_project_id()
    if not project_id:
        emit_warning(
            f"No Code Assist project ID found; skipping model '{model_config.get('name')}'. "
            "Run /gemini-auth to re-authenticate."
        )
        return None

    from code_puppy.gemini_code_assist import GeminiCodeAssistModel

    return GeminiCodeAssistModel(
        model_name=model_config["name"],
        access_token=access_token,
        project_id=project_id,
        api_base_url=GEMINI_OAUTH_CONFIG["api_base_url"],
        api_version=GEMINI_OAUTH_CONFIG["api_version"])


# NOTE: 'chatgpt_oauth' model type is now handled by the chatgpt_oauth plugin
# via the register_model_type callback. See plugins/chatgpt_oauth/register_callbacks.py


def _build_round_robin(model_name: str, model_config: dict, config: dict) -> Any:
    from code_puppy.round_robin_model import RoundRobinModel

    model_names = model_config.get("models")
    if not model_names or not isinstance(model_names, list):
        raise ValueError(
            f"Round-robin model '{model_name}' requires a 'models' list in its configuration."
        )

    rotate_every = model_config.get("rotate_every", 1)

    models = [ModelFactory.get_model(name, config) for name in model_names]
    return RoundRobinModel(*models, rotate_every=rotate_every)


# ---------------------------------------------------------------------------
# Register all built-in builders at module load
# ---------------------------------------------------------------------------
register_model_builder("gemini", _build_gemini)
register_model_builder("openai", _build_openai)
register_model_builder("anthropic", _build_anthropic)
register_model_builder("custom_anthropic", _build_custom_anthropic)
register_model_builder("azure_openai", _build_azure_openai)
register_model_builder("custom_openai", _build_custom_openai)
register_model_builder("zai_coding", _build_zai_coding)
register_model_builder("zai_api", _build_zai_api)
register_model_builder("custom_gemini", _build_custom_gemini)
register_model_builder("cerebras", _build_cerebras)
register_model_builder("openrouter", _build_openrouter)
register_model_builder("gemini_oauth", _build_gemini_oauth)
register_model_builder("round_robin", _build_round_robin)


# ---------------------------------------------------------------------------
# Quota / availability exception helpers
# ---------------------------------------------------------------------------

# HTTP status codes that indicate exhausted quota (terminal failure).
_TERMINAL_STATUS_CODES: frozenset[int] = frozenset({402, 429})

# Keywords that hint at capacity / quota exhaustion in exception messages.
_TERMINAL_KEYWORDS: tuple[str, ...] = (
    "quota",
    "rate limit",
    "ratelimit",
    "resource_exhausted",
    "resourceexhausted",
    "too many requests",
    "capacity",
    "insufficient_quota",
)


def is_quota_exception(exc: BaseException) -> bool:
    """Return True when *exc* looks like a terminal quota / rate-limit error.

    Inspects:
    * ``response.status_code`` / ``status_code`` attributes on the exception.
    * The stringified exception message for well-known quota keywords.

    This avoids hard dependencies on any specific SDK exception hierarchy and
    therefore works across OpenAI, Anthropic, Gemini, and custom providers.
    """
    # Check for a status_code attribute (httpx, requests, pydantic-ai, openai ...)
    for attr in ("status_code", "status"):
        code = getattr(exc, attr, None)
        if code is None:
            # Some SDKs nest the response: exc.response.status_code
            response_obj = getattr(exc, "response", None)
            code = getattr(response_obj, "status_code", None) or getattr(
                response_obj, "status", None
            )
        if isinstance(code, int) and code in _TERMINAL_STATUS_CODES:
            return True

    # Keyword scan on the string representation (covers gRPC ResourceExhausted etc.)
    msg = str(exc).lower()
    return any(kw in msg for kw in _TERMINAL_KEYWORDS)


# --- Model config caching (eliminates repeated disk reads) ---
_model_config_cache: dict[str, Any] | None = None
_model_config_mtimes: dict[str, float] = {}


def invalidate_model_config_cache() -> None:
    """Force next ModelFactory.load_config() call to re-read from disk."""
    global _model_config_cache
    _model_config_cache = None


class ModelFactory:
    """A factory for creating and managing different AI models."""

    @staticmethod
    def load_config() -> dict[str, Any]:
        global _model_config_cache, _model_config_mtimes

        # Check if any source file has changed since last cache
        # Use module-level imports for EXTRA_MODELS_FILE etc. (line 26)
        # so that monkeypatch in tests can override them
        from code_puppy.config import (
            ANTIGRAVITY_MODELS_FILE,
            CHATGPT_MODELS_FILE,
            CLAUDE_MODELS_FILE,
            GEMINI_MODELS_FILE)

        source_files = [
            pathlib.Path(__file__).parent / "models.json",
            pathlib.Path(EXTRA_MODELS_FILE),
            pathlib.Path(CHATGPT_MODELS_FILE),
            pathlib.Path(CLAUDE_MODELS_FILE),
            pathlib.Path(GEMINI_MODELS_FILE),
            pathlib.Path(ANTIGRAVITY_MODELS_FILE),
        ]

        # Build current mtimes for existing files
        current_mtimes: dict[str, float] = {}
        for p in source_files:
            try:
                current_mtimes[str(p)] = p.stat().st_mtime
            except OSError:
                pass  # File doesn't exist

        # Return cache if valid
        if _model_config_cache is not None and current_mtimes == _model_config_mtimes:
            return _model_config_cache.copy()

        load_model_config_callbacks = callbacks.get_callbacks("load_model_config")
        if len(load_model_config_callbacks) > 0:
            if len(load_model_config_callbacks) > 1:
                logging.getLogger(__name__).warning(
                    "Multiple load_model_config callbacks registered, using the first"
                )
            config = callbacks.on_load_model_config()[0]
        else:
            # Always load from the bundled models.json so upstream
            # updates propagate automatically.  User additions belong
            # in extra_models.json (overlay loaded below).
            bundled_models = pathlib.Path(__file__).parent / "models.json"
            with open(bundled_models, "r") as f:
                config = json.load(f)

        # Build list of extra model sources
        extra_sources: list[tuple[pathlib.Path, str, bool]] = [
            (pathlib.Path(EXTRA_MODELS_FILE), "extra models", False),
            (pathlib.Path(CHATGPT_MODELS_FILE), "ChatGPT OAuth models", False),
            (pathlib.Path(CLAUDE_MODELS_FILE), "Claude Code OAuth models", True),
            (pathlib.Path(GEMINI_MODELS_FILE), "Gemini OAuth models", False),
            (pathlib.Path(ANTIGRAVITY_MODELS_FILE), "Antigravity OAuth models", False),
        ]

        for source_path, label, use_filtered in extra_sources:
            if not source_path.exists():
                continue
            try:
                # Use filtered loading for Claude Code OAuth models to show only latest versions
                if use_filtered:
                    try:
                        from code_puppy.plugins.claude_code_oauth.utils import (
                            load_claude_models_filtered)

                        extra_config = load_claude_models_filtered()
                    except ImportError:
                        # Plugin not available, fall back to standard JSON loading
                        logging.getLogger(__name__).debug(
                            f"claude_code_oauth plugin not available, loading {label} as plain JSON"
                        )
                        with open(source_path, "r") as f:
                            extra_config = json.load(f)
                else:
                    with open(source_path, "r") as f:
                        extra_config = json.load(f)
                config.update(extra_config)
            except json.JSONDecodeError as exc:
                logging.getLogger(__name__).warning(
                    f"Failed to load {label} config from {source_path}: Invalid JSON - {exc}"
                )
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    f"Failed to load {label} config from {source_path}: {exc}"
                )

        # Let plugins add/override models via load_models_config hook
        try:
            from code_puppy.callbacks import on_load_models_config

            results = on_load_models_config()
            for result in results:
                if isinstance(result, dict):
                    config.update(result)  # Plugin models override built-in
        except Exception as exc:
            logging.getLogger(__name__).debug(
                f"Failed to load plugin models config: {exc}"
            )

        # Populate cache
        _model_config_cache = config.copy()
        _model_config_mtimes.clear()
        _model_config_mtimes.update(current_mtimes)

        return config

    @staticmethod
    def get_model(model_name: str, config: dict[str, Any]) -> Any:
        """Returns a configured model instance based on the provided name and config.

        Raises ValueError if the model cannot be initialized (e.g. missing API
        keys, bad configuration, or unsupported model type).  Callers such as
        ``_load_model_with_fallback`` already catch ``ValueError`` and attempt
        a fallback, so raising here enables automatic recovery.
        """
        model_config = config.get(model_name)
        if not model_config:
            raise ValueError(f"Model '{model_name}' not found in configuration.")

        model_type = model_config.get("type")
        provider_identity = resolve_provider_identity(model_name, model_config)

        def _check_result(result: Any, source: str) -> Any:
            """Raise if a builder / provider returned None."""
            if result is None:
                raise ValueError(
                    f"Model '{model_name}' (type='{model_type}') could not be "
                    f"initialized by {source}. Check that required API keys and "
                    f"configuration are set."
                )
            return result

        # Ensure plugin model providers are loaded (lazy initialization)
        _load_plugin_model_providers()

        # Check for plugin-registered model provider classes first
        if model_type in _CUSTOM_MODEL_PROVIDERS:
            provider_class = _CUSTOM_MODEL_PROVIDERS[model_type]
            try:
                result = provider_class(
                    model_name=model_name, model_config=model_config, config=config
                )
                return _check_result(result, f"custom provider '{model_type}'")
            except ValueError:
                raise  # Re-raise ValueError from _check_result
            except Exception as e:
                raise ValueError(
                    f"Model '{model_name}': custom provider '{model_type}' "
                    f"failed: {e}"
                ) from e

        # Look up the builder in the registry
        builder = _MODEL_BUILDERS.get(model_type)
        if builder is not None:
            result = builder(model_name, model_config, config)
            return _check_result(result, f"builder '{model_type}'")

        # Fall back to plugin-registered model type handlers
        registered_handlers = callbacks.on_register_model_types()
        for handler_info in registered_handlers:
            handlers = (
                handler_info
                if isinstance(handler_info, list)
                else [handler_info]
                if handler_info
                else []
            )
            for handler_entry in handlers:
                if not isinstance(handler_entry, dict):
                    continue
                if handler_entry.get("type") == model_type:
                    handler = handler_entry.get("handler")
                    if callable(handler):
                        try:
                            result = handler(model_name, model_config, config)
                            return _check_result(
                                result, f"plugin handler '{model_type}'"
                            )
                        except ValueError:
                            raise  # Re-raise ValueError from _check_result
                        except Exception as e:
                            raise ValueError(
                                f"Model '{model_name}': plugin handler "
                                f"'{model_type}' failed: {e}"
                            ) from e

        raise ValueError(f"Unsupported model type: {model_type}")


# ── Routing Integration (Foundation — not yet wired into production) ────
def route_model(model_name: str, config: dict) -> tuple:
    """Route a model request through the composite strategy chain.

    .. note:: **Foundation only** — this function is not yet called by any
       production code path.  ``ModelFactory.get_model()`` remains the
       active entry point.  Wire this in when the routing system is
       ready for production use.

    Consults the availability circuit breaker and plugin strategies
    before falling back to the default builder registry.

    Args:
        model_name: Requested model name.
        config: Full models configuration dict.

    Returns:
        Tuple of (model_instance, resolved_model_name, metadata).

    Raises:
        ValueError: If no strategy could produce a model.
    """
    from code_puppy.routing.router import create_default_router
    from code_puppy.routing.strategy import RoutingContext

    router = create_default_router()
    ctx = RoutingContext(model_name=model_name, config=config)

    decision = router.route(ctx)
    return decision.model, decision.model_name, decision.metadata
