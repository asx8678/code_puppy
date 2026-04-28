"""Code Puppy configuration package — split-by-concern facade.

This package replaces the monolithic ``config.py`` (2694 lines) with
focused sub-modules that each stay under 600 lines. The ``__init__.py``
re-exports all public names for **full backward compatibility** — existing
imports like ``from code_puppy.config import get_value`` continue to work.

Module layout (mirrors ``CodePuppyControl.Config.*`` in Elixir):

| Module        | Elixir counterpart              | Responsibility                            |
|---------------|----------------------------------|--------------------------------------------|
| ``loader``    | ``Config.Loader`` + ``Config.Writer`` | INI parser, cache, get/set/reset      |
| ``paths``     | ``Config.Paths`` + ``Config.Isolation`` | XDG paths, isolation guards         |
| ``models``    | ``Config.Models``               | Model name, per-model settings, pinning   |
| ``agents``    | ``Config.Agents``               | Default agent, personalization, dirs       |
| ``tui``       | ``Config.TUI``                  | Banner/diff colors, display flags          |
| ``limits``    | ``Config.Limits``               | Compaction, token budgets, timeouts        |
| ``debug``     | ``Config.Debug``                | Feature toggles, YOLO, API keys           |
| ``cache``     | ``Config.Cache``                | Auto-save, WS history, command history     |
| ``mcp``       | (partial Config facade)         | MCP server config loading                  |

ADR-003 Dual-Home Isolation
----------------------------

When running as pup-ex (``PUP_EX_HOME`` set), all writes go to
``~/.code_puppy_ex/`` and NEVER to ``~/.code_puppy/``. This is enforced
by ``code_puppy.config_paths.assert_write_allowed`` — every setter in
this package calls it before writing.

The Elixir runtime (``CodePuppyControl.Config.Isolation``) enforces the
same guard on its side. Python code that needs Elixir config data should
use the bridge access pattern::

    from code_puppy.plugins.elixir_bridge import is_connected, call_method
    if is_connected():
        result = call_method('code_context.explore_file', {'file_path': path})
"""

# ruff: noqa: F401 — re-export facade; all imports are re-exported for backward compatibility

from __future__ import annotations

# ---------------------------------------------------------------------------
# Core loader (foundation — must be first)
# ---------------------------------------------------------------------------
from code_puppy.config.loader import (
    ConfigState,
    get_config_state,
    DEFAULT_SECTION,
    REQUIRED_KEYS,
    get_value,
    set_value,
    set_config_value,
    reset_value,
    get_config_keys,
    get_default_config_keys,
    ensure_config_exists,
    _get_config,
    _invalidate_config,
    _is_truthy,
    _registered_cache,
    _make_bool_getter,
    _make_int_getter,
    _make_float_getter,
    _get_xdg_dir,
    _TRUTHY_VALUES,
    _CACHED_GETTERS,
)

# ---------------------------------------------------------------------------
# Paths (lazy path constants + isolation guards)
# ---------------------------------------------------------------------------
from code_puppy.config.paths import (
    _path_config_file,
    _path_mcp_servers_file,
    _path_agents_dir,
    _path_skills_dir,
    _path_autosave_dir,
    _path_command_history_file,
    _path_default_sqlite_file,
    _xdg_config_dir,
    _xdg_data_dir,
    _xdg_cache_dir,
    _xdg_state_dir,
    _LAZY_PATH_FACTORIES,
    _LAZY_PATH_OVERRIDES,
    ConfigIsolationViolation,
    safe_write,
    safe_mkdir_p,
    safe_rm,
    safe_rm_rf,
    safe_atomic_write,
    safe_append,
    with_sandbox,
    resolve_path,
)

# Also re-export config_paths top-level functions that config.py used to expose
from code_puppy.config_paths import (
    is_pup_ex,
    home_dir,
    legacy_home_dir,
    python_home_dir,
    config_dir,
    data_dir,
    cache_dir,
    state_dir,
    assert_write_allowed,
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
from code_puppy.config.models import (
    set_model_name,
    get_global_model_name,
    model_supports_setting,
    clear_model_cache,
    reset_session_model,
    get_model_context_length,
    get_openai_reasoning_effort,
    set_openai_reasoning_effort,
    get_openai_reasoning_summary,
    set_openai_reasoning_summary,
    get_openai_verbosity,
    set_openai_verbosity,
    get_temperature,
    set_temperature,
    get_effective_temperature,
    get_effective_model_settings,
    get_model_setting,
    set_model_setting,
    get_all_model_settings,
    clear_model_settings,
    get_agent_pinned_model,
    set_agent_pinned_model,
    clear_agent_pinned_model,
    get_agents_pinned_to_model,
    get_all_agent_pinned_models,
    get_effective_top_p,
    get_effective_seed,
    _validate_model_exists,
)

# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
from code_puppy.config.agents import (
    get_default_agent,
    set_default_agent,
    get_puppy_name,
    get_owner_name,
    get_user_agents_directory,
    get_project_agents_directory,
    get_puppy_token,
    set_puppy_token,
)

# ---------------------------------------------------------------------------
# TUI
# ---------------------------------------------------------------------------
from code_puppy.config.tui import (
    DEFAULT_BANNER_COLORS,
    get_banner_color,
    set_banner_color,
    get_all_banner_colors,
    reset_banner_color,
    reset_all_banner_colors,
    get_diff_addition_color,
    set_diff_addition_color,
    get_diff_deletion_color,
    set_diff_deletion_color,
    get_diff_context_lines,
    get_suppress_thinking_messages,
    set_suppress_thinking_messages,
    get_suppress_informational_messages,
    set_suppress_informational_messages,
    get_grep_output_verbose,
)

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
from code_puppy.config.limits import (
    get_protected_token_count,
    get_compaction_threshold,
    get_compaction_strategy,
    get_resume_message_count,
    get_message_limit,
    get_bus_request_timeout_seconds,
    get_max_session_tokens,
    get_max_run_tokens,
    get_summarization_trigger_fraction,
    get_summarization_keep_fraction,
    get_summarization_pretruncate_enabled,
    get_summarization_arg_max_length,
    get_summarization_return_max_length,
    get_summarization_return_head_chars,
    get_summarization_return_tail_chars,
    get_summarization_history_offload_enabled,
    get_summarization_history_dir,
)

# ---------------------------------------------------------------------------
# Debug / Feature toggles
# ---------------------------------------------------------------------------
from code_puppy.config.debug import (
    get_yolo_mode,
    get_allow_recursion,
    get_use_dbos,
    set_enable_dbos,
    get_pack_agents_enabled,
    PACK_AGENT_NAMES,
    UC_AGENT_NAMES,
    get_universal_constructor_enabled,
    set_universal_constructor_enabled,
    get_enable_streaming,
    get_enable_agent_memory,
    get_adaptive_rendering_enabled,
    get_post_edit_validation_enabled,
    get_subagent_verbose,
    get_http2,
    set_http2,
    get_mcp_disabled,
    get_safety_permission_level,
    get_enable_user_plugins,
    get_allowed_user_plugins,
    load_api_keys_to_environment,
    get_api_key,
    set_api_key,
    get_memory_debounce_seconds,
    get_memory_max_facts,
    get_memory_token_budget,
    get_memory_extraction_model,
    get_elixir_message_shadow_mode_enabled,
    get_enable_gitignore_filtering,
)

# ---------------------------------------------------------------------------
# Cache / Session
# ---------------------------------------------------------------------------
from code_puppy.config.cache import (
    get_auto_save_session,
    set_auto_save_session,
    get_max_saved_sessions,
    set_max_saved_sessions,
    get_ws_history_maxlen,
    get_ws_history_ttl_seconds,
    get_frontend_emitter_enabled,
    get_frontend_emitter_max_recent_events,
    get_frontend_emitter_queue_size,
    save_command_to_history,
    initialize_command_history_file,
    get_current_autosave_id,
    rotate_autosave_id,
    get_current_autosave_session_name,
    set_current_autosave_from_session_name,
    auto_save_session_if_enabled,
    finalize_autosave_session,
)

# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------
from code_puppy.config.mcp import load_mcp_server_configs

# ---------------------------------------------------------------------------
# Diff highlight style (no-op legacy)
# ---------------------------------------------------------------------------


def set_diff_highlight_style(style: str) -> None:
    """Set the diff highlight style. No-op — always uses 'highlight' mode."""
    pass


# ---------------------------------------------------------------------------
# Lazy path constant access via __getattr__ (PEP 562)
# ---------------------------------------------------------------------------

# These names are expected by external code doing:
#   from code_puppy.config import CONFIG_FILE
#   config.CONFIG_FILE
# They resolve lazily to respect pup-ex isolation.

_LAZY_EXPORTS = set(_LAZY_PATH_FACTORIES.keys()) | {
    "STATE_DIR", "CONFIG_DIR", "CACHE_DIR", "AUTOSAVE_DIR", "EXTRA_MODELS_FILE",
}


def __getattr__(name: str):
    """Lazy path resolution for external attribute access (PEP 562)."""
    if name in _LAZY_PATH_FACTORIES:
        return _LAZY_PATH_FACTORIES[name]()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# Public API exports
# ---------------------------------------------------------------------------

__all__ = [
    # Path constants (lazy)
    "STATE_DIR", "CONFIG_DIR", "CACHE_DIR", "AUTOSAVE_DIR", "EXTRA_MODELS_FILE",
    # Core config access
    "get_value", "set_value", "get_config_keys", "set_config_value",
    # Model management
    "set_model_name", "get_global_model_name", "get_all_model_settings",
    "model_supports_setting", "set_model_setting",
    "_validate_model_exists",
    # OpenAI reasoning/verbosity
    "get_openai_reasoning_effort", "set_openai_reasoning_effort",
    "get_openai_reasoning_summary", "set_openai_reasoning_summary",
    "get_openai_verbosity", "set_openai_verbosity",
    # Temperature
    "get_temperature", "set_temperature",
    # Agent pinned models
    "get_agent_pinned_model", "set_agent_pinned_model",
    "clear_agent_pinned_model", "get_agents_pinned_to_model",
    "get_all_agent_pinned_models",
    # Feature toggles
    "get_use_dbos", "get_yolo_mode", "get_auto_save_session",
    "get_elixir_message_shadow_mode_enabled",
    "get_enable_gitignore_filtering",
    # Personalization
    "get_puppy_name", "get_owner_name", "get_default_agent",
    # Session/compaction
    "get_resume_message_count", "get_compaction_threshold",
    "get_compaction_strategy", "get_protected_token_count",
    "get_summarization_return_head_chars",
    # Temperature
    "get_effective_temperature",
    # UI colors
    "set_diff_addition_color", "set_diff_deletion_color", "set_banner_color",
    # Agents directory
    "get_user_agents_directory",
    # Environment
    "load_api_keys_to_environment",
    # Isolation
    "ConfigIsolationViolation", "assert_write_allowed",
    "safe_write", "safe_mkdir_p", "safe_atomic_write",
    "with_sandbox", "resolve_path",
    "is_pup_ex", "home_dir",
]
