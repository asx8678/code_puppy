import configparser
import json
import os
import pathlib
import threading
import time
from dataclasses import dataclass, field
from functools import cache, lru_cache
from typing import Callable

from code_puppy.session_storage import save_session_async
from code_puppy import runtime_state


@dataclass
class ConfigState:
    """Encapsulates all mutable module-level state for config.py.

    Replaces the nine process-global variables that previously scattered
    mutable state across the module, making the state easier to inspect,
    reset in tests, and reason about.
    """

    # Config caching (eliminates repeated disk reads)
    config_cache: configparser.ConfigParser | None = None
    config_mtime: float = 0.0

    # mtime check debouncing (reduces stat syscall cost)
    last_mtime_check: float = 0.0
    cached_mtime: float | None = None

    # Thread-safe lock for config cache access
    config_lock: threading.Lock = field(default_factory=threading.Lock)

    # Model validation and defaults caching
    model_validation_cache: dict = field(default_factory=dict)
    default_model_cache: str | None = None
    default_vision_model_cache: str | None = None
    supported_settings_cache: Callable | None = None

    # Model context length cache
    model_context_length_cache: dict[str, int] = field(default_factory=dict)


# Module-level singleton – all functions reference _state.<field> instead of
# bare module globals so the state is fully encapsulated.
_state = ConfigState()


@lru_cache(maxsize=4)
def _get_xdg_dir_cached(env_var: str, fallback: str) -> str:
    """
    Get directory for code_puppy files (lru_cached - computed once per unique args).

    Uses @lru_cache(maxsize=4) to cache results for each unique (env_var, fallback)
    combination. Cached values persist for the lifetime of the process.

    XDG paths are only used when the corresponding environment variable
    is explicitly set by the user. Otherwise, we use the legacy ~/.code_puppy
    directory for all file types (config, data, cache, state).

    Args:
        env_var: XDG environment variable name (e.g., "XDG_CONFIG_HOME")
        fallback: Fallback path relative to home (e.g., ".config") - unused unless XDG var is set

    Returns:
        Path to the directory for code_puppy files
    """
    # Use XDG directory ONLY if environment variable is explicitly set
    xdg_base = os.getenv(env_var)
    if xdg_base:
        return os.path.join(xdg_base, "code_puppy")

    # Default to legacy ~/.code_puppy for all file types
    return os.path.join(os.path.expanduser("~"), ".code_puppy")


def _get_xdg_dir(env_var: str, fallback: str) -> str:
    """Get XDG directory (uncached: always reads current env var).

    Deliberately bypasses `_get_xdg_dir_cached` so that callers who change
    XDG_* env vars at runtime (notably tests using `patch.dict(os.environ)`)
    always get fresh results. The cached variant is still used for the
    module-level path constants computed once at import time.
    """
    xdg_base = os.getenv(env_var)
    if xdg_base:
        return os.path.join(xdg_base, "code_puppy")
    return os.path.join(os.path.expanduser("~"), ".code_puppy")


def _get_config() -> configparser.ConfigParser:
    """Return a cached ConfigParser, re-reading only when the file changes."""
    now = time.time()

    # Only re-check mtime after TTL expires (1 second debounce)
    if now - _state.last_mtime_check > 1.0:
        try:
            _state.cached_mtime = os.path.getmtime(CONFIG_FILE)
        except OSError:
            # File doesn't exist — return a fresh (uncached) parser each time
            # so that tests which mock ConfigParser or CONFIG_FILE work correctly.
            cfg = configparser.ConfigParser()
            cfg.read(CONFIG_FILE)
            return cfg
        _state.last_mtime_check = now

    with _state.config_lock:
        if _state.config_cache is None or _state.cached_mtime != _state.config_mtime:
            _state.config_cache = configparser.ConfigParser()
            _state.config_cache.read(CONFIG_FILE)
            _state.config_mtime = _state.cached_mtime
        return _state.config_cache


def _invalidate_config() -> None:
    """Force next _get_config() call to re-read from disk.

    Also resets the TTL-debounce state (_state.last_mtime_check, _state.cached_mtime) so
    the next _get_config() call performs a fresh mtime check rather than
    trusting stale values from before invalidation. This is essential for
    test isolation when CONFIG_FILE is swapped between tests.
    """
    with _state.config_lock:
        _state.config_cache = None
        _state.last_mtime_check = 0.0
        _state.cached_mtime = None
    # Also invalidate the protected token count cache
    get_protected_token_count.cache_clear()
    # Clear model context length cache since config changes
    # may affect model resolution
    _state.model_context_length_cache.clear()
    # Clear all cached config getter functions
    get_use_dbos.cache_clear()
    get_subagent_verbose.cache_clear()
    get_pack_agents_enabled.cache_clear()
    get_universal_constructor_enabled.cache_clear()
    get_enable_streaming.cache_clear()
    get_puppy_name.cache_clear()
    get_owner_name.cache_clear()
    get_allow_recursion.cache_clear()
    get_puppy_token.cache_clear()
    get_openai_reasoning_effort.cache_clear()
    get_openai_reasoning_summary.cache_clear()
    get_openai_verbosity.cache_clear()
    get_temperature.cache_clear()
    get_yolo_mode.cache_clear()
    get_safety_permission_level.cache_clear()
    get_mcp_disabled.cache_clear()
    get_grep_output_verbose.cache_clear()
    get_resume_message_count.cache_clear()
    get_compaction_threshold.cache_clear()
    get_compaction_strategy.cache_clear()
    get_http2.cache_clear()
    get_message_limit.cache_clear()
    get_auto_save_session.cache_clear()
    get_max_saved_sessions.cache_clear()
    get_diff_addition_color.cache_clear()
    get_diff_deletion_color.cache_clear()
    get_diff_context_lines.cache_clear()
    get_suppress_thinking_messages.cache_clear()


# Truthy string values recognized by _is_truthy() — module-level to avoid
# recreating the set on every call (used by 20+ config getter functions).
_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})


def _is_truthy(val: str | None, default: bool = False) -> bool:
    """Parse a config value as boolean. Recognizes 1/true/yes/on as True."""
    if val is None:
        return default
    return str(val).strip().lower() in _TRUTHY_VALUES


def _make_bool_getter(key: str, default: bool = False, doc: str | None = None):
    """Factory for simple boolean config getter functions.

    Creates a cached getter that reads a config key and converts it to bool
    using _is_truthy(). Generated getters are automatically registered
    for cache invalidation in _invalidate_config().

    Args:
        key: The config key to read (section is always 'puppy')
        default: Default value if key is not set
        doc: Optional docstring for the generated function

    Returns:
        A cached getter function: () -> bool
    """
    getter_name = f"get_{key}"

    def getter() -> bool:
        return _is_truthy(get_value(key), default=default)

    getter.__name__ = getter_name
    getter.__doc__ = doc or f"Return True if '{key}' is enabled (default {default})."
    return cache(getter)


def _make_int_getter(
    key: str,
    default: int,
    min_val: int | None = None,
    max_val: int | None = None,
    doc: str | None = None,
):
    """Factory for simple int config getter functions.

    Creates a cached getter that reads a config key and converts it to int
    with optional min/max bounds. Generated getters are automatically registered
    for cache invalidation in _invalidate_config().

    Args:
        key: The config key to read (section is always 'puppy')
        default: Default value if key is not set or invalid
        min_val: Optional minimum value (inclusive)
        max_val: Optional maximum value (inclusive)
        doc: Optional docstring for the generated function

    Returns:
        A cached getter function: () -> int
    """
    getter_name = f"get_{key}"

    def getter() -> int:
        val = get_value(key)
        try:
            result = int(val) if val is not None else default
            if min_val is not None:
                result = max(min_val, result)
            if max_val is not None:
                result = min(max_val, result)
            return result
        except (ValueError, TypeError):
            return default

    getter.__name__ = getter_name
    getter.__doc__ = (
        doc or f"Return the configured value for '{key}' as int (default {default})."
    )
    return cache(getter)


def _make_float_getter(
    key: str,
    default: float,
    min_val: float | None = None,
    max_val: float | None = None,
    doc: str | None = None,
):
    """Factory for simple float config getter functions.

    Creates a cached getter that reads a config key and converts it to float
    with optional min/max bounds. Generated getters are automatically registered
    for cache invalidation in _invalidate_config().

    Args:
        key: The config key to read (section is always 'puppy')
        default: Default value if key is not set or invalid
        min_val: Optional minimum value (inclusive)
        max_val: Optional maximum value (inclusive)
        doc: Optional docstring for the generated function

    Returns:
        A cached getter function: () -> float
    """
    getter_name = f"get_{key}"

    def getter() -> float:
        val = get_value(key)
        try:
            result = float(val) if val is not None else default
            if min_val is not None:
                result = max(min_val, result)
            if max_val is not None:
                result = min(max_val, result)
            return result
        except (ValueError, TypeError):
            return default

    getter.__name__ = getter_name
    getter.__doc__ = (
        doc or f"Return the configured value for '{key}' as float (default {default})."
    )
    return cache(getter)


# --- Module-level path constants (eager, computed once at import time) ---
# Previously these were lazy-evaluated via a module-level __getattr__ for a
# microscopic startup perf win. That broke horribly: PEP 562 module __getattr__
# only intercepts *external* `module.ATTR` access. It does NOT resolve bare-name
# lookups inside the module's own functions, so every `CONFIG_FILE` reference
# inside config.py raised NameError at runtime (see issue code_puppy-9tcr).
# _get_xdg_dir_cached() already has @lru_cache, so these are effectively free.

# XDG Base Directory paths
CONFIG_DIR = _get_xdg_dir_cached("XDG_CONFIG_HOME", ".config")
DATA_DIR = _get_xdg_dir_cached("XDG_DATA_HOME", ".local/share")
CACHE_DIR = _get_xdg_dir_cached("XDG_CACHE_HOME", ".cache")
STATE_DIR = _get_xdg_dir_cached("XDG_STATE_HOME", ".local/state")

# Configuration files (XDG_CONFIG_HOME)
CONFIG_FILE = pathlib.Path(CONFIG_DIR) / "puppy.cfg"
MCP_SERVERS_FILE = pathlib.Path(CONFIG_DIR) / "mcp_servers.json"

# Data files (XDG_DATA_HOME)
MODELS_FILE = pathlib.Path(DATA_DIR) / "models.json"
EXTRA_MODELS_FILE = pathlib.Path(DATA_DIR) / "extra_models.json"
AGENTS_DIR = pathlib.Path(DATA_DIR) / "agents"
SKILLS_DIR = pathlib.Path(DATA_DIR) / "skills"
CONTEXTS_DIR = pathlib.Path(DATA_DIR) / "contexts"
_DEFAULT_SQLITE_FILE = pathlib.Path(DATA_DIR) / "dbos_store.sqlite"

# OAuth plugin model files (XDG_DATA_HOME)
GEMINI_MODELS_FILE = pathlib.Path(DATA_DIR) / "gemini_models.json"
CHATGPT_MODELS_FILE = pathlib.Path(DATA_DIR) / "chatgpt_models.json"
CLAUDE_MODELS_FILE = pathlib.Path(DATA_DIR) / "claude_models.json"
ANTIGRAVITY_MODELS_FILE = pathlib.Path(DATA_DIR) / "antigravity_models.json"

# Cache files (XDG_CACHE_HOME)
AUTOSAVE_DIR = pathlib.Path(CACHE_DIR) / "autosaves"

# State files (XDG_STATE_HOME)
COMMAND_HISTORY_FILE = pathlib.Path(STATE_DIR) / "command_history.txt"

# Database URL (depends on _DEFAULT_SQLITE_FILE)
DBOS_DATABASE_URL = os.environ.get(
    "DBOS_SYSTEM_DATABASE_URL", f"sqlite:///{_DEFAULT_SQLITE_FILE}"
)
# DBOS enable switch is controlled solely via puppy.cfg using key 'enable_dbos'.
# Default: True (DBOS enabled) unless explicitly disabled.


# Boolean config getters generated via factory
get_use_dbos = _make_bool_getter(
    "enable_dbos",
    default=True,
    doc="""Return True if DBOS should be used based on 'enable_dbos' (default True).""",
)

get_subagent_verbose = _make_bool_getter(
    "subagent_verbose",
    default=False,
    doc="""Return True if sub-agent verbose output is enabled (default False).

    When False (default), sub-agents produce quiet, sparse output suitable
    for parallel execution. When True, sub-agents produce full verbose output
    like the main agent (useful for debugging).
    """,
)


# Pack agents - the specialized sub-agents coordinated by Pack Leader
PACK_AGENT_NAMES = frozenset(
    [
        "pack-leader",
        "bloodhound",
        "husky",
        "shepherd",
        "terrier",
        "watchdog",
        "retriever",
    ]
)

# Agents that require Universal Constructor to be enabled
UC_AGENT_NAMES = frozenset(["helios"])


get_pack_agents_enabled = _make_bool_getter(
    "enable_pack_agents",
    default=False,
    doc="""Return True if pack agents are enabled (default False).

    When False (default), pack agents (pack-leader, bloodhound, husky, shepherd,
    terrier, watchdog, retriever) are hidden from `list_agents` tool and `/agents`
    command. They cannot be invoked by other agents or selected by users.

    When True, pack agents are available for use.
    """,
)

get_universal_constructor_enabled = _make_bool_getter(
    "enable_universal_constructor",
    default=True,
    doc="""Return True if the Universal Constructor is enabled (default True).

    The Universal Constructor allows agents to dynamically create, manage,
    and execute custom tools at runtime. When enabled, agents can extend
    their capabilities by writing Python code that becomes callable tools.

    When False, the universal_constructor tool is not registered with agents.
    """,
)


def set_universal_constructor_enabled(enabled: bool) -> None:
    """Enable or disable the Universal Constructor.

    Args:
        enabled: True to enable, False to disable
    """
    set_value("enable_universal_constructor", "true" if enabled else "false")


get_enable_streaming = _make_bool_getter(
    "enable_streaming",
    default=True,
    doc="""Get the enable_streaming configuration value.
    Controls whether streaming (SSE) is used for model responses.
    Returns True if streaming is enabled, False otherwise.
    Defaults to True.
    """,
)


DEFAULT_SECTION = "puppy"
REQUIRED_KEYS = ["puppy_name", "owner_name"]

# Note: Runtime-only state variables moved to runtime_state.py:
# - _CURRENT_AUTOSAVE_ID -> runtime_state._CURRENT_AUTOSAVE_ID
# - _SESSION_MODEL -> runtime_state._SESSION_MODEL


def _get_supported_settings_cache():
    """Return the LRU cache function for supported settings, creating it if needed."""
    if _state.supported_settings_cache is None:

        @lru_cache(maxsize=128)
        def _cached_supported_settings(model_name: str) -> frozenset:
            """Get supported settings for a model - cached to avoid repeated config loads."""
            from code_puppy.model_factory import ModelFactory

            models_config = ModelFactory.load_config()
            model_config = models_config.get(model_name, {})
            supported_settings = model_config.get("supported_settings")

            if supported_settings is None:
                # Default: assume common settings are supported for backwards compatibility
                # For Anthropic/Claude models, include extended thinking settings
                if model_name.startswith("claude-") or model_name.startswith(
                    "anthropic-"
                ):
                    base = ["temperature", "extended_thinking", "budget_tokens"]
                    # Opus 4-6 models also support the effort setting
                    lower = model_name.lower()
                    if "opus-4-6" in lower or "4-6-opus" in lower:
                        base.append("effort")
                    return frozenset(base)
                return frozenset(["temperature", "seed"])

            return frozenset(supported_settings)

        _state.supported_settings_cache = _cached_supported_settings
    return _state.supported_settings_cache


def ensure_config_exists():
    """
    Ensure that XDG directories and puppy.cfg exist, prompting if needed.
    Returns configparser.ConfigParser for reading.
    """
    # Create all XDG directories with 0700 permissions per XDG spec
    for directory in [CONFIG_DIR, DATA_DIR, CACHE_DIR, STATE_DIR, SKILLS_DIR]:
        if not os.path.exists(directory):
            os.makedirs(directory, mode=0o700, exist_ok=True)
    exists = os.path.isfile(CONFIG_FILE)
    config = configparser.ConfigParser()
    if exists:
        config.read(CONFIG_FILE)
    missing = []
    if DEFAULT_SECTION not in config:
        config[DEFAULT_SECTION] = {}
    for key in REQUIRED_KEYS:
        if not config[DEFAULT_SECTION].get(key):
            missing.append(key)
    if missing:
        # Note: Using sys.stdout here for initial setup before messaging system is available
        import sys

        sys.stdout.write("🐾 Let's get your Puppy ready!\n")
        sys.stdout.flush()
        for key in missing:
            if key == "puppy_name":
                val = input("What should we name the puppy? ").strip()
            elif key == "owner_name":
                val = input(
                    "What's your name (so Code Puppy knows its owner)? "
                ).strip()
            else:
                val = input(f"Enter {key}: ").strip()
            config[DEFAULT_SECTION][key] = val

    # Set default values for important config keys if they don't exist
    if not config[DEFAULT_SECTION].get("auto_save_session"):
        config[DEFAULT_SECTION]["auto_save_session"] = "true"

    # Write the config if we made any changes
    if missing or not exists:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            config.write(f)
        _invalidate_config()
    return config


def get_value(key: str):
    config = _get_config()
    return config.get(DEFAULT_SECTION, key, fallback=None)


@cache
def get_puppy_name():
    return get_value("puppy_name") or "Puppy"


@cache
def get_owner_name():
    return get_value("owner_name") or "Master"


# Legacy function removed - message history limit is no longer used
# Message history is now managed by token-based compaction system
# using get_protected_token_count() and get_summarization_threshold()


get_allow_recursion = _make_bool_getter(
    "allow_recursion",
    default=True,
    doc="""Get the allow_recursion configuration value.
    Returns True if recursion is allowed, False otherwise.
    """,
)


def _get_model_context_length(model_name: str) -> int:
    """
    Get context length for a model, with caching.
    Cache is cleared when _invalidate_config() is called.
    """
    # Check cache first
    if model_name in _state.model_context_length_cache:
        return _state.model_context_length_cache[model_name]

    # Lookup in config
    try:
        from code_puppy.model_factory import ModelFactory

        model_configs = ModelFactory.load_config()
        model_config = model_configs.get(model_name, {})
        context_length = model_config.get("context_length", 128000)
        result = int(context_length)
    except Exception:
        result = 128000

    # Store in cache
    _state.model_context_length_cache[model_name] = result
    return result


def get_model_context_length(model_name: str | None = None) -> int:
    """
    Get the context length for the currently configured model from models.json.
    Results are cached per-model to avoid repeated config lookups.

    Args:
        model_name: Optional model name to look up. If not provided, uses global model.

    Returns:
        Model context length in tokens.
    """
    try:
        if model_name is None:
            model_name = get_global_model_name()
        return _get_model_context_length(model_name)
    except Exception:
        # Fallback to default context length if anything goes wrong
        return 128000


# --- CONFIG SETTER STARTS HERE ---
def get_default_config_keys():
    """
    Returns the list of all known/preset config keys.
    This is the source of truth for default configuration keys.
    """
    default_keys = [
        "yolo_mode",
        "model",
        "compaction_strategy",
        "protected_token_count",
        "compaction_threshold",
        "message_limit",
        "allow_recursion",
        "openai_reasoning_effort",
        "openai_reasoning_summary",
        "openai_verbosity",
        "auto_save_session",
        "max_saved_sessions",
        "http2",
        "diff_context_lines",
        "default_agent",
        "temperature",
        "frontend_emitter_enabled",
        "frontend_emitter_max_recent_events",
        "frontend_emitter_queue_size",
    ]
    # Add DBOS control key
    default_keys.append("enable_dbos")
    # Add pack agents control key
    default_keys.append("enable_pack_agents")
    # Add universal constructor control key
    default_keys.append("enable_universal_constructor")
    # Add streaming control key
    default_keys.append("enable_streaming")
    # Add cancel agent key configuration
    default_keys.append("cancel_agent_key")
    # Add banner color keys
    for banner_name in DEFAULT_BANNER_COLORS:
        default_keys.append(f"banner_color_{banner_name}")
    # Add resume message count configuration
    default_keys.append("resume_message_count")
    # Add fast puppy (Rust acceleration) control key
    default_keys.append("enable_fast_puppy")

    # SECURITY FIX c9z0: User plugin security settings
    default_keys.append("enable_user_plugins")
    default_keys.append("allowed_user_plugins")

    return default_keys


def get_config_keys():
    """
    Returns the list of all config keys currently in puppy.cfg,
    plus certain preset expected keys (e.g. "yolo_mode", "model", "compaction_strategy", "message_limit", "allow_recursion").
    """
    default_keys = get_default_config_keys()

    config = _get_config()
    keys = set(config[DEFAULT_SECTION].keys()) if DEFAULT_SECTION in config else set()
    keys.update(default_keys)
    return sorted(keys)


def set_config_value(key: str, value: str):
    """
    Sets a config value in the persistent config file.
    """
    config = _get_config()  # Use cached version
    if DEFAULT_SECTION not in config:
        config[DEFAULT_SECTION] = {}
    config[DEFAULT_SECTION][key] = value
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        config.write(f)
    _invalidate_config()  # Invalidate cache after write


# Alias for API compatibility
def set_value(key: str, value: str) -> None:
    """Set a config value. Alias for set_config_value."""
    set_config_value(key, value)


def reset_value(key: str) -> None:
    """Remove a key from the config file, resetting it to default."""
    config = _get_config()  # Use cached version
    if DEFAULT_SECTION in config and key in config[DEFAULT_SECTION]:
        del config[DEFAULT_SECTION][key]
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            config.write(f)
    _invalidate_config()  # Invalidate cache after write


# --- MODEL STICKY EXTENSION STARTS HERE ---
def load_mcp_server_configs():
    """
    Loads the MCP server configurations from XDG_CONFIG_HOME/code_puppy/mcp_servers.json.
    Returns a dict mapping names to their URL or config dict.
    If file does not exist, returns an empty dict.
    """
    from code_puppy.messaging.message_queue import emit_error

    try:
        if not pathlib.Path(MCP_SERVERS_FILE).exists():
            return {}
        with open(MCP_SERVERS_FILE, "r", encoding="utf-8") as f:
            conf = json.loads(f.read())
            return conf["mcp_servers"]
    except Exception as e:
        emit_error(f"Failed to load MCP servers - {str(e)}")
        return {}


def _default_model_from_models_json():
    """Load the default model name from models.json.

    Returns the first model in models.json as the default.
    Falls back to ``gpt-5`` if the file cannot be read.
    """
    if _state.default_model_cache is not None:
        return _state.default_model_cache

    try:
        from code_puppy.model_factory import ModelFactory

        models_config = ModelFactory.load_config()
        if models_config:
            # Use first model in models.json as default
            first_key = next(iter(models_config))
            _state.default_model_cache = first_key
            return first_key
        _state.default_model_cache = "gpt-5"
        return "gpt-5"
    except Exception:
        _state.default_model_cache = "gpt-5"
        return "gpt-5"


def _default_vision_model_from_models_json() -> str:
    """Select a default vision-capable model from models.json with caching."""
    if _state.default_vision_model_cache is not None:
        return _state.default_vision_model_cache

    try:
        from code_puppy.model_factory import ModelFactory

        models_config = ModelFactory.load_config()
        if models_config:
            # Prefer explicitly tagged vision models
            for name, config in models_config.items():
                if config.get("supports_vision"):
                    _state.default_vision_model_cache = name
                    return name

            # Fallback heuristic: common multimodal models
            preferred_candidates = (
                "gpt-4.1",
                "gpt-4.1-mini",
                "gpt-4.1-nano",
                "claude-4-0-sonnet",
                "gemini-2.5-flash-preview-05-20",
            )
            for candidate in preferred_candidates:
                if candidate in models_config:
                    _state.default_vision_model_cache = candidate
                    return candidate

            # Last resort: use the general default model
            _state.default_vision_model_cache = _default_model_from_models_json()
            return _state.default_vision_model_cache

        _state.default_vision_model_cache = "gpt-4.1"
        return "gpt-4.1"
    except Exception:
        _state.default_vision_model_cache = "gpt-4.1"
        return "gpt-4.1"


def _validate_model_exists(model_name: str) -> bool:
    """Check if a model exists in models.json with caching to avoid redundant calls."""
    # Check cache first
    if model_name in _state.model_validation_cache:
        return _state.model_validation_cache[model_name]

    try:
        from code_puppy.model_factory import ModelFactory

        models_config = ModelFactory.load_config()
        exists = model_name in models_config

        # Cache the result
        _state.model_validation_cache[model_name] = exists
        return exists
    except Exception:
        # If we can't validate, assume it exists to avoid breaking things
        _state.model_validation_cache[model_name] = True
        return True


def clear_model_cache():
    """Clear the model validation cache. Call this when models.json changes."""
    _state.model_validation_cache.clear()
    _state.default_model_cache = None
    _state.default_vision_model_cache = None
    # Clear the lru_cache for supported settings
    if _state.supported_settings_cache is not None:
        _state.supported_settings_cache.cache_clear()
        _state.supported_settings_cache = None


def reset_session_model():
    """Reset the session-local model cache.

    This is primarily for testing purposes. In normal operation, the session
    model is set once at startup and only changes via set_model_name().
    """
    runtime_state.reset_session_model()


def model_supports_setting(model_name: str, setting: str) -> bool:
    """Check if a model supports a particular setting (e.g., 'temperature', 'seed').

    Args:
        model_name: The name of the model to check.
        setting: The setting name to check for (e.g., 'temperature', 'seed', 'top_p').

    Returns:
        True if the model supports the setting, False otherwise.
        Defaults to True for backwards compatibility if model config doesn't specify.
    """
    # GLM-4.7 and GLM-5 models always support clear_thinking setting
    if setting == "clear_thinking" and (
        "glm-4.7" in model_name.lower() or "glm-5" in model_name.lower()
    ):
        return True

    try:
        cache_func = _get_supported_settings_cache()
        supported_settings = cache_func(model_name)
        return setting in supported_settings
    except Exception:
        # If we can't check, assume supported for safety
        return True


def get_global_model_name():
    """Return a valid model name for Code Puppy to use.

    Uses session-local caching so that model changes in other terminals
    don't affect this running instance. The file is only read once at startup.

    1. If session model is cached in runtime_state, return it (session cache)
    2. Otherwise, look at ``model`` in *puppy.cfg*
    3. If that value exists **and** is present in *models.json*, use it
    4. Otherwise return the first model listed in *models.json*
    5. As a last resort fall back to ``claude-4-0-sonnet``

    The result is cached in runtime_state for subsequent calls.
    """
    # Return cached session model if already initialized
    cached_model = runtime_state.get_session_model()
    if cached_model is not None:
        return cached_model

    # First access - initialize from file
    stored_model = get_value("model")

    if stored_model:
        # Use cached validation to avoid hitting ModelFactory every time
        if _validate_model_exists(stored_model):
            runtime_state.set_session_model(stored_model)
            return stored_model

    # Either no stored model or it's not valid – choose default from models.json
    default_model = _default_model_from_models_json()
    runtime_state.set_session_model(default_model)
    return default_model


def set_model_name(model: str):
    """Sets the model name in both the session cache and persistent config file.

    Updates runtime_state immediately for this process, and writes to the
    config file so new terminals will pick up this model as their default.
    """
    # Update session cache immediately (runtime state, not config)
    runtime_state.set_session_model(model)

    # Also persist to file for new terminal sessions (this is config)
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    if DEFAULT_SECTION not in config:
        config[DEFAULT_SECTION] = {}
    config[DEFAULT_SECTION]["model"] = model or ""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        config.write(f)
    _invalidate_config()

    # Clear model cache when switching models to ensure fresh validation
    clear_model_cache()


@cache
def get_puppy_token():
    """Returns the puppy_token from config, or None if not set."""
    return get_value("puppy_token")


def set_puppy_token(token: str):
    """Sets the puppy_token in the persistent config file."""
    set_config_value("puppy_token", token)


@cache
def get_openai_reasoning_effort() -> str:
    """Return the configured OpenAI reasoning effort (minimal, low, medium, high, xhigh)."""
    allowed_values = {"minimal", "low", "medium", "high", "xhigh"}
    configured = (get_value("openai_reasoning_effort") or "medium").strip().lower()
    if configured not in allowed_values:
        return "medium"
    return configured


def set_openai_reasoning_effort(value: str) -> None:
    """Persist the OpenAI reasoning effort ensuring it remains within allowed values."""
    allowed_values = {"minimal", "low", "medium", "high", "xhigh"}
    normalized = (value or "").strip().lower()
    if normalized not in allowed_values:
        raise ValueError(
            f"Invalid reasoning effort '{value}'. Allowed: {', '.join(sorted(allowed_values))}"
        )
    set_config_value("openai_reasoning_effort", normalized)


@cache
def get_openai_reasoning_summary() -> str:
    """Return the configured OpenAI reasoning summary mode.

    Supported values:
    - auto: let the provider decide the best summary style
    - concise: shorter reasoning summaries
    - detailed: fuller reasoning summaries
    """
    allowed_values = {"auto", "concise", "detailed"}
    configured = (get_value("openai_reasoning_summary") or "auto").strip().lower()
    if configured not in allowed_values:
        return "auto"
    return configured


def set_openai_reasoning_summary(value: str) -> None:
    """Persist the OpenAI reasoning summary mode ensuring it remains valid."""
    allowed_values = {"auto", "concise", "detailed"}
    normalized = (value or "").strip().lower()
    if normalized not in allowed_values:
        raise ValueError(
            f"Invalid reasoning summary '{value}'. Allowed: {', '.join(sorted(allowed_values))}"
        )
    set_config_value("openai_reasoning_summary", normalized)


@cache
def get_openai_verbosity() -> str:
    """Return the configured OpenAI verbosity (low, medium, high).

    Controls how concise vs. verbose the model's responses are:
    - low: more concise responses
    - medium: balanced (default)
    - high: more verbose responses
    """
    allowed_values = {"low", "medium", "high"}
    configured = (get_value("openai_verbosity") or "medium").strip().lower()
    if configured not in allowed_values:
        return "medium"
    return configured


def set_openai_verbosity(value: str) -> None:
    """Persist the OpenAI verbosity ensuring it remains within allowed values."""
    allowed_values = {"low", "medium", "high"}
    normalized = (value or "").strip().lower()
    if normalized not in allowed_values:
        raise ValueError(
            f"Invalid verbosity '{value}'. Allowed: {', '.join(sorted(allowed_values))}"
        )
    set_config_value("openai_verbosity", normalized)


@cache
def get_temperature() -> float | None:
    """Return the configured model temperature (0.0 to 2.0).

    Returns:
        Float between 0.0 and 2.0 if set, None if not configured.
        This allows each model to use its own default when not overridden.
    """
    val = get_value("temperature")
    if val is None or val.strip() == "":
        return None
    try:
        temp = float(val)
        # Clamp to valid range (most APIs accept 0-2)
        return max(0.0, min(2.0, temp))
    except (ValueError, TypeError):
        return None


def set_temperature(value: float | None) -> None:
    """Set the global model temperature in config.

    Args:
        value: Temperature between 0.0 and 2.0, or None to clear.
               Lower values = more deterministic, higher = more creative.

    Note: Consider using set_model_setting() for per-model temperature.
    """
    if value is None:
        set_config_value("temperature", "")
    else:
        # Validate and clamp
        temp = max(0.0, min(2.0, float(value)))
        set_config_value("temperature", str(temp))


# --- PER-MODEL SETTINGS ---


def _sanitize_model_name_for_key(model_name: str) -> str:
    """Sanitize model name for use in config keys.

    Replaces characters that might cause issues in config keys.
    """
    # Replace problematic characters with underscores
    sanitized = model_name.replace(".", "_").replace("-", "_").replace("/", "_")
    return sanitized.lower()


def get_model_setting(
    model_name: str, setting: str, default: float | None = None
) -> float | None:
    """Get a specific setting for a model.

    Args:
        model_name: The model name (e.g., 'gpt-5', 'claude-4-5-sonnet')
        setting: The setting name (e.g., 'temperature', 'top_p', 'seed')
        default: Default value if not set

    Returns:
        The setting value as a float, or default if not set.
    """
    sanitized_name = _sanitize_model_name_for_key(model_name)
    key = f"model_settings_{sanitized_name}_{setting}"
    val = get_value(key)

    if val is None or val.strip() == "":
        return default

    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def set_model_setting(model_name: str, setting: str, value: float | None) -> None:
    """Set a specific setting for a model.

    Args:
        model_name: The model name (e.g., 'gpt-5', 'claude-4-5-sonnet')
        setting: The setting name (e.g., 'temperature', 'seed')
        value: The value to set, or None to clear
    """
    sanitized_name = _sanitize_model_name_for_key(model_name)
    key = f"model_settings_{sanitized_name}_{setting}"

    if value is None:
        set_config_value(key, "")
    elif isinstance(value, float):
        # Round floats to nearest hundredth to avoid floating point weirdness
        # (allows 0.05 step increments for temperature/top_p)
        set_config_value(key, str(round(value, 2)))
    else:
        set_config_value(key, str(value))


def get_all_model_settings(model_name: str) -> dict:
    """Get all settings for a specific model.

    Args:
        model_name: The model name

    Returns:
        Dictionary of setting_name -> value for all configured settings.
    """
    sanitized_name = _sanitize_model_name_for_key(model_name)
    prefix = f"model_settings_{sanitized_name}_"

    config = _get_config()

    settings = {}
    if DEFAULT_SECTION in config:
        for key, val in config[DEFAULT_SECTION].items():
            if key.startswith(prefix) and val.strip():
                setting_name = key[len(prefix) :]
                # Handle different value types
                val_stripped = val.strip()
                # Check for boolean values first
                if val_stripped.lower() in ("true", "false"):
                    settings[setting_name] = val_stripped.lower() == "true"
                else:
                    # Try to parse as number (int first, then float)
                    try:
                        # Try int first for cleaner values like budget_tokens
                        if "." not in val_stripped:
                            settings[setting_name] = int(val_stripped)
                        else:
                            settings[setting_name] = float(val_stripped)
                    except (ValueError, TypeError):
                        # Keep as string if not a number
                        settings[setting_name] = val_stripped

    return settings


def clear_model_settings(model_name: str) -> None:
    """Clear all settings for a specific model.

    Args:
        model_name: The model name
    """
    sanitized_name = _sanitize_model_name_for_key(model_name)
    prefix = f"model_settings_{sanitized_name}_"

    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)

    if DEFAULT_SECTION in config:
        keys_to_remove = [
            key for key in config[DEFAULT_SECTION] if key.startswith(prefix)
        ]
        for key in keys_to_remove:
            del config[DEFAULT_SECTION][key]

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            config.write(f)
        _invalidate_config()


def get_effective_model_settings(model_name: str | None = None) -> dict:
    """Get all effective settings for a model, filtered by what the model supports.

    This is the generalized way to get model settings. It:
    1. Gets all per-model settings from config
    2. Falls back to global temperature if not set per-model
    3. Filters to only include settings the model actually supports
    4. Converts seed to int (other settings stay as float)

    Args:
        model_name: The model name. If None, uses the current global model.

    Returns:
        Dictionary of setting_name -> value for all applicable settings.
        Ready to be unpacked into ModelSettings.
    """
    if model_name is None:
        model_name = get_global_model_name()

    # Start with all per-model settings
    settings = get_all_model_settings(model_name)

    # Fall back to global temperature if not set per-model
    if "temperature" not in settings:
        global_temp = get_temperature()
        if global_temp is not None:
            settings["temperature"] = global_temp

    # Filter to only settings the model supports
    effective_settings = {}
    for setting_name, value in settings.items():
        if model_supports_setting(model_name, setting_name):
            # Convert seed to int, keep others as float
            if setting_name == "seed" and value is not None:
                effective_settings[setting_name] = int(value)
            else:
                effective_settings[setting_name] = value

    return effective_settings


# Legacy functions for backward compatibility
def get_effective_temperature(model_name: str | None = None) -> float | None:
    """Get the effective temperature for a model.

    Checks per-model settings first, then falls back to global temperature.

    Args:
        model_name: The model name. If None, uses the current global model.

    Returns:
        Temperature value, or None if not configured.
    """
    settings = get_effective_model_settings(model_name)
    return settings.get("temperature")


def get_effective_top_p(model_name: str | None = None) -> float | None:
    """Get the effective top_p for a model.

    Args:
        model_name: The model name. If None, uses the current global model.

    Returns:
        top_p value, or None if not configured.
    """
    settings = get_effective_model_settings(model_name)
    return settings.get("top_p")


def get_effective_seed(model_name: str | None = None) -> int | None:
    """Get the effective seed for a model.

    Args:
        model_name: The model name. If None, uses the current global model.

    Returns:
        seed value as int, or None if not configured.
    """
    settings = get_effective_model_settings(model_name)
    seed = settings.get("seed")
    return int(seed) if seed is not None else None


def get_user_agents_directory() -> str:
    """Get the user's agents directory path.

    Returns:
        Path to the user's Code Puppy agents directory.
    """
    # Ensure the agents directory exists
    os.makedirs(AGENTS_DIR, exist_ok=True)
    return AGENTS_DIR


def get_project_agents_directory() -> str | None:
    """Get the project-local agents directory path.

    Looks for a .code_puppy/agents/ directory in the current working directory.
    Unlike get_user_agents_directory(), this does NOT create the directory
    if it doesn't exist -- the team must create it intentionally.

    Returns:
        Path to the project's agents directory if it exists, or None.
    """
    project_agents_dir = os.path.join(os.getcwd(), ".code_puppy", "agents")
    if os.path.isdir(project_agents_dir):
        return project_agents_dir
    return None


def initialize_command_history_file():
    """Create the command history file if it doesn't exist.
    Handles migration from the old history file location for backward compatibility.
    """
    from pathlib import Path

    # Ensure the state directory exists before trying to create the history file
    if not os.path.exists(STATE_DIR):
        os.makedirs(STATE_DIR, exist_ok=True)

    command_history_exists = os.path.isfile(COMMAND_HISTORY_FILE)
    if not command_history_exists:
        try:
            Path(COMMAND_HISTORY_FILE).touch()

            # For backwards compatibility, copy the old history file, then remove it
            old_history_file = os.path.join(
                os.path.expanduser("~"), ".code_puppy_history.txt"
            )
            old_history_exists = os.path.isfile(old_history_file)
            if old_history_exists:
                import shutil

                shutil.copy2(Path(old_history_file), Path(COMMAND_HISTORY_FILE))
                Path(old_history_file).unlink(missing_ok=True)
        except Exception as e:
            from code_puppy.messaging import emit_error

            emit_error(
                f"An unexpected error occurred while trying to initialize history file: {str(e)}"
            )


get_yolo_mode = _make_bool_getter(
    "yolo_mode",
    default=True,
    doc="""Checks puppy.cfg for 'yolo_mode' (case-insensitive in value only).
    Defaults to True if not set.
    Allowed values for ON: 1, '1', 'true', 'yes', 'on' (all case-insensitive for value).
    """,
)


@cache
def get_safety_permission_level():
    """
    Checks puppy.cfg for 'safety_permission_level' (case-insensitive in value only).
    Defaults to 'medium' if not set.
    Allowed values: 'none', 'low', 'medium', 'high', 'critical' (all case-insensitive for value).
    Returns the normalized lowercase string.
    """
    valid_levels = {"none", "low", "medium", "high", "critical"}
    cfg_val = get_value("safety_permission_level")
    if cfg_val is not None:
        normalized = str(cfg_val).strip().lower()
        if normalized in valid_levels:
            return normalized
    return "medium"  # Default to medium risk threshold


get_mcp_disabled = _make_bool_getter(
    "disable_mcp",
    default=False,
    doc="""Checks puppy.cfg for 'disable_mcp' (case-insensitive in value only).
    Defaults to False if not set.
    Allowed values for ON: 1, '1', 'true', 'yes', 'on' (all case-insensitive for value).
    When enabled, Code Puppy will skip loading MCP servers entirely.
    """,
)

get_grep_output_verbose = _make_bool_getter(
    "grep_output_verbose",
    default=False,
    doc="""Checks puppy.cfg for 'grep_output_verbose' (case-insensitive in value only).
    Defaults to False (concise output) if not set.
    Allowed values for ON: 1, '1', 'true', 'yes', 'on' (all case-insensitive for value).

    When False (default): Shows only file names with match counts
    When True: Shows full output with line numbers and content
    """,
)


@lru_cache(maxsize=256)
def get_protected_token_count():
    """
    Returns the user-configured protected token count for message history compaction.
    This is the number of tokens in recent messages that won't be summarized.
    Defaults to 50000 if unset or misconfigured.
    Configurable by 'protected_token_count' key.
    Enforces that protected tokens don't exceed 75% of model context length.
    """
    val = get_value("protected_token_count")
    try:
        # Get the model context length to enforce the 75% limit
        model_context_length = get_model_context_length()
        max_protected_tokens = int(model_context_length * 0.75)

        # Parse the configured value
        configured_value = int(val) if val else 50000

        # Apply constraints: minimum 1000, maximum 75% of context length
        return max(1000, min(configured_value, max_protected_tokens))
    except (ValueError, TypeError):
        # If parsing fails, return a reasonable default that respects the 75% limit
        model_context_length = get_model_context_length()
        max_protected_tokens = int(model_context_length * 0.75)
        return min(50000, max_protected_tokens)


get_resume_message_count = _make_int_getter(
    "resume_message_count",
    default=50,
    min_val=1,
    max_val=100,
    doc="""Returns the number of messages to display when resuming a session.
    Defaults to 50 if unset or misconfigured.
    Configurable by 'resume_message_count' key via /set command.

    Example: /set resume_message_count=30
    """,
)


get_compaction_threshold = _make_float_getter(
    "compaction_threshold",
    default=0.85,
    min_val=0.5,
    max_val=0.95,
    doc="""Returns the user-configured compaction threshold as a float between 0.0 and 1.0.
    This is the proportion of model context that triggers compaction.
    Defaults to 0.85 (85%) if unset or misconfigured.
    Configurable by 'compaction_threshold' key.
    """,
)


@cache
def get_compaction_strategy() -> str:
    """
    Returns the user-configured compaction strategy.
    Options are 'summarization' or 'truncation'.
    Defaults to 'summarization' if not set or misconfigured.
    Configurable by 'compaction_strategy' key.
    """
    val = get_value("compaction_strategy")
    if val and val.lower() in ["summarization", "truncation"]:
        return val.lower()
    # Default to summarization
    return "truncation"


get_http2 = _make_bool_getter(
    "http2",
    default=False,
    doc="""Get the http2 configuration value.
    Returns False if not set (default).
    """,
)


def set_http2(enabled: bool) -> None:
    """
    Sets the http2 configuration value.

    Args:
        enabled: Whether to enable HTTP/2 for httpx clients
    """
    set_config_value("http2", "true" if enabled else "false")


def set_enable_dbos(enabled: bool) -> None:
    """Enable DBOS via config (true enables, default false)."""
    set_config_value("enable_dbos", "true" if enabled else "false")


@cache
def get_message_limit(default: int = 1000) -> int:
    """
    Returns the user-configured message/request limit for the agent.
    This controls how many steps/requests the agent can take.
    Defaults to 1000 if unset or misconfigured.
    Configurable by 'message_limit' key.
    """
    val = get_value("message_limit")
    try:
        return int(val) if val else default
    except (ValueError, TypeError):
        return default


def save_command_to_history(command: str):
    """Save a command to the history file with an ISO format timestamp.

    Args:
        command: The command to save
    """
    import datetime

    try:
        timestamp = datetime.datetime.now().isoformat(timespec="seconds")

        # Sanitize command to remove any invalid surrogate characters
        # that could cause encoding errors on Windows
        try:
            command = command.encode("utf-8", errors="surrogatepass").decode(
                "utf-8", errors="replace"
            )
        except (UnicodeEncodeError, UnicodeDecodeError):
            # If that fails, do a more aggressive cleanup
            command = "".join(
                char if ord(char) < 0xD800 or ord(char) > 0xDFFF else "\ufffd"
                for char in command
            )

        with open(
            COMMAND_HISTORY_FILE, "a", encoding="utf-8", errors="surrogateescape"
        ) as f:
            f.write(f"\n# {timestamp}\n{command}\n")
    except Exception as e:
        from code_puppy.messaging import emit_error

        emit_error(
            f"An unexpected error occurred while saving command history: {str(e)}"
        )


def get_agent_pinned_model(agent_name: str) -> str:
    """Get the pinned model for a specific agent.

    Args:
        agent_name: Name of the agent to get the pinned model for.

    Returns:
        Pinned model name, or None if no model is pinned for this agent.
    """
    return get_value(f"agent_model_{agent_name}")


def set_agent_pinned_model(agent_name: str, model_name: str):
    """Set the pinned model for a specific agent.

    Args:
        agent_name: Name of the agent to pin the model for.
        model_name: Model name to pin to this agent.
    """
    set_config_value(f"agent_model_{agent_name}", model_name)


def clear_agent_pinned_model(agent_name: str):
    """Clear the pinned model for a specific agent.

    Args:
        agent_name: Name of the agent to clear the pinned model for.
    """
    # We can't easily delete keys from configparser, so set to empty string
    # which will be treated as None by get_agent_pinned_model
    set_config_value(f"agent_model_{agent_name}", "")


def get_all_agent_pinned_models() -> dict:
    """Get all agent-to-model pinnings from config.

    Returns:
        Dict mapping agent names to their pinned model names.
        Only includes agents that have a pinned model (non-empty value).
    """
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)

    pinnings = {}
    if DEFAULT_SECTION in config:
        for key, value in config[DEFAULT_SECTION].items():
            if key.startswith("agent_model_") and value:
                agent_name = key[len("agent_model_") :]
                pinnings[agent_name] = value
    return pinnings


def get_agents_pinned_to_model(model_name: str) -> list:
    """Get all agents that are pinned to a specific model.

    Args:
        model_name: The model name to look up.

    Returns:
        List of agent names pinned to this model.
    """
    all_pinnings = get_all_agent_pinned_models()
    return [agent for agent, model in all_pinnings.items() if model == model_name]


get_auto_save_session = _make_bool_getter(
    "auto_save_session",
    default=True,
    doc="""Checks puppy.cfg for 'auto_save_session' (case-insensitive in value only).
    Defaults to True if not set.
    Allowed values for ON: 1, '1', 'true', 'yes', 'on' (all case-insensitive for value).
    """,
)


def set_auto_save_session(enabled: bool):
    """Sets the auto_save_session configuration value.

    Args:
        enabled: Whether to enable auto-saving of sessions
    """
    set_config_value("auto_save_session", "true" if enabled else "false")


get_max_saved_sessions = _make_int_getter(
    "max_saved_sessions",
    default=20,
    min_val=0,
    doc="""Gets the maximum number of sessions to keep.
    Defaults to 20 if not set.
    """,
)


def set_max_saved_sessions(max_sessions: int):
    """Sets the max_saved_sessions configuration value.

    Args:
        max_sessions: Maximum number of sessions to keep (0 for unlimited)
    """
    set_config_value("max_saved_sessions", str(max_sessions))


def set_diff_highlight_style(style: str):
    """Set the diff highlight style.

    Note: Text mode has been removed. This function is kept for backwards compatibility
    but does nothing. All diffs use beautiful syntax highlighting now!

    Args:
        style: Ignored (always uses 'highlight' mode)
    """
    # Do nothing - we always use highlight mode now!
    pass


@cache
def get_diff_addition_color() -> str:
    """
    Get the base color for diff additions.
    Default: darker green
    """
    val = get_value("highlight_addition_color")
    if val:
        return val
    return "#0b1f0b"  # Default to darker green


def set_diff_addition_color(color: str):
    """Set the color for diff additions.

    Args:
        color: Rich color markup (e.g., 'green', 'on_green', 'bright_green')
    """
    set_config_value("highlight_addition_color", color)


@cache
def get_diff_deletion_color() -> str:
    """
    Get the base color for diff deletions.
    Default: wine
    """
    val = get_value("highlight_deletion_color")
    if val:
        return val
    return "#390e1a"  # Default to wine


def set_diff_deletion_color(color: str):
    """Set the color for diff deletions.

    Args:
        color: Rich color markup (e.g., 'orange1', 'on_bright_yellow', 'red')
    """
    set_config_value("highlight_deletion_color", color)


# =============================================================================
# Banner Color Configuration
# =============================================================================

# Default banner colors (Rich color names)
# A beautiful jewel-tone palette with semantic meaning:
#   - Blues/Teals: Reading & navigation (calm, informational)
#   - Warm tones: Actions & changes (edits, shell commands)
#   - Purples: AI thinking & reasoning (the "brain" colors)
#   - Greens: Completions & success
#   - Neutrals: Search & listings
DEFAULT_BANNER_COLORS = {
    "thinking": "deep_sky_blue4",  # Sapphire - contemplation
    "agent_response": "medium_purple4",  # Amethyst - main AI output
    "shell_command": "dark_orange3",  # Amber - system commands
    "read_file": "steel_blue",  # Steel - reading files
    "edit_file": "dark_goldenrod",  # Gold - modifications (legacy)
    "create_file": "dark_goldenrod",  # Gold - file creation
    "replace_in_file": "dark_goldenrod",  # Gold - file modifications
    "delete_snippet": "dark_goldenrod",  # Gold - snippet removal
    "grep": "grey37",  # Silver - search results
    "directory_listing": "dodger_blue2",  # Sky - navigation
    "agent_reasoning": "dark_violet",  # Violet - deep thought
    "invoke_agent": "deep_pink4",  # Ruby - agent invocation
    "subagent_response": "sea_green3",  # Emerald - sub-agent success
    "list_agents": "dark_slate_gray3",  # Slate - neutral listing
    "universal_constructor": "dark_cyan",  # Teal - constructing tools
    # Browser/Terminal tools - same color as edit_file (gold)
    "terminal_tool": "dark_goldenrod",  # Gold - browser terminal operations
    # MCP tools - distinct from builtin tools
    "mcp_tool_call": "dark_cyan",  # Teal - external MCP tool calls
    # User-initiated shell pass-through (! prefix) - distinct from agent's shell_command
    "shell_passthrough": "medium_sea_green",  # Green - user's own shell commands
}


def get_banner_color(banner_name: str) -> str:
    """Get the background color for a specific banner.

    Args:
        banner_name: The banner identifier (e.g., 'thinking', 'agent_response')

    Returns:
        Rich color name or hex code for the banner background
    """
    config_key = f"banner_color_{banner_name}"
    val = get_value(config_key)
    if val:
        return val
    return DEFAULT_BANNER_COLORS.get(banner_name, "blue")


def set_banner_color(banner_name: str, color: str):
    """Set the background color for a specific banner.

    Args:
        banner_name: The banner identifier (e.g., 'thinking', 'agent_response')
        color: Rich color name or hex code
    """
    config_key = f"banner_color_{banner_name}"
    set_config_value(config_key, color)


def get_all_banner_colors() -> dict:
    """Get all banner colors (configured or default).

    Returns:
        Dict mapping banner names to their colors
    """
    return {name: get_banner_color(name) for name in DEFAULT_BANNER_COLORS}


def reset_banner_color(banner_name: str):
    """Reset a banner color to its default.

    Args:
        banner_name: The banner identifier to reset
    """
    default_color = DEFAULT_BANNER_COLORS.get(banner_name, "blue")
    set_banner_color(banner_name, default_color)


def reset_all_banner_colors():
    """Reset all banner colors to their defaults."""
    for name, color in DEFAULT_BANNER_COLORS.items():
        set_banner_color(name, color)


def get_current_autosave_id() -> str:
    """Get or create the current autosave session ID for this process.

    This is a convenience wrapper that delegates to runtime_state.
    The autosave ID is runtime-only state, not persisted to config.
    """
    return runtime_state.get_current_autosave_id()


def rotate_autosave_id() -> str:
    """Force a new autosave session ID and return it.

    This is a convenience wrapper that delegates to runtime_state.
    """
    return runtime_state.rotate_autosave_id()


def get_current_autosave_session_name() -> str:
    """Return the full session name used for autosaves (no file extension).

    This is a convenience wrapper that delegates to runtime_state.
    """
    return runtime_state.get_current_autosave_session_name()


def set_current_autosave_from_session_name(session_name: str) -> str:
    """Set the current autosave ID based on a full session name.

    Accepts names like 'auto_session_YYYYMMDD_HHMMSS' and extracts the ID part.
    Returns the ID that was set.

    This is a convenience wrapper that delegates to runtime_state.
    """
    return runtime_state.set_current_autosave_from_session_name(session_name)


def auto_save_session_if_enabled() -> bool:
    """Automatically save the current session if auto_save_session is enabled.

    This function is non-blocking - the actual save operation happens in a
    background thread to avoid blocking the main execution flow during file I/O.
    Token counting is done once on the main thread and passed to the background
    thread to avoid redundant computation.
    """
    import datetime  # Local import since this is only used here

    if not get_auto_save_session():
        return False

    try:
        import pathlib

        from code_puppy.agents.agent_manager import get_current_agent
        from code_puppy.messaging import emit_info

        current_agent = get_current_agent()
        history = current_agent.get_message_history()
        if not history:
            return False

        now = datetime.datetime.now()
        session_name = get_current_autosave_session_name()
        autosave_dir = pathlib.Path(AUTOSAVE_DIR)

        # Precompute total tokens once on the main thread - this is the only
        # token computation on the user-facing path. The background thread
        # will reuse this precomputed value instead of recomputing.
        total_tokens = sum(
            current_agent.estimate_tokens_for_message(msg) for msg in history
        )

        # Submit to background thread - non-blocking
        # Pass precomputed_total so the save operation doesn't recompute tokens
        save_session_async(
            history=history,
            session_name=session_name,
            base_dir=autosave_dir,
            timestamp=now.isoformat(),
            token_estimator=current_agent.estimate_tokens_for_message,
            auto_saved=True,
            compacted_hashes=list(current_agent.get_compacted_message_hashes()),
            precomputed_total=total_tokens,
        )

        emit_info(
            f"🐾 Auto-saved session: {len(history)} messages ({total_tokens} tokens)"
        )

        return True

    except Exception as exc:  # pragma: no cover - defensive logging
        from code_puppy.messaging import emit_error

        emit_error(f"Failed to auto-save session: {exc}")
        return False


get_diff_context_lines = _make_int_getter(
    "diff_context_lines",
    default=6,
    min_val=0,
    max_val=50,
    doc="""Returns the user-configured number of context lines for diff display.
    This controls how many lines of surrounding context are shown in diffs.
    Defaults to 6 if unset or misconfigured.
    Configurable by 'diff_context_lines' key.
    """,
)


def finalize_autosave_session() -> str:
    """Persist the current autosave snapshot and rotate to a fresh session."""
    auto_save_session_if_enabled()
    return rotate_autosave_id()


get_suppress_thinking_messages = _make_bool_getter(
    "suppress_thinking_messages",
    default=False,
    doc="""Checks puppy.cfg for 'suppress_thinking_messages' (case-insensitive in value only).
    Defaults to False if not set.
    Allowed values for ON: 1, '1', 'true', 'yes', 'on' (all case-insensitive for value).
    When enabled, thinking messages (agent_reasoning, planned_next_steps) will be hidden.
    """,
)


def set_suppress_thinking_messages(enabled: bool):
    """Sets the suppress_thinking_messages configuration value.

    Args:
        enabled: Whether to suppress thinking messages
    """
    set_config_value("suppress_thinking_messages", "true" if enabled else "false")


def get_suppress_informational_messages() -> bool:
    """
    Checks puppy.cfg for 'suppress_informational_messages' (case-insensitive in value only).
    Defaults to False if not set.
    Allowed values for ON: 1, '1', 'true', 'yes', 'on' (all case-insensitive for value).
    When enabled, informational messages (info, success, warning) will be hidden.
    """
    return _is_truthy(get_value("suppress_informational_messages"), default=False)


def set_suppress_informational_messages(enabled: bool):
    """Sets the suppress_informational_messages configuration value.

    Args:
        enabled: Whether to suppress informational messages
    """
    set_config_value("suppress_informational_messages", "true" if enabled else "false")


# API Key management functions
def get_api_key(key_name: str) -> str:
    """Get an API key from puppy.cfg.

    Args:
        key_name: The name of the API key (e.g., 'OPENAI_API_KEY')

    Returns:
        The API key value, or empty string if not set
    """
    return get_value(key_name) or ""


def set_api_key(key_name: str, value: str):
    """Set an API key in puppy.cfg.

    Args:
        key_name: The name of the API key (e.g., 'OPENAI_API_KEY')
        value: The API key value (empty string to remove)
    """
    set_config_value(key_name, value)


def load_api_keys_to_environment():
    """Load all API keys from .env and puppy.cfg into environment variables.

    Priority order:
    1. .env file (highest priority) - if present in current directory
    2. puppy.cfg - fallback if not in .env
    3. Existing environment variables - preserved if already set

    This should be called on startup to ensure API keys are available.
    """
    from pathlib import Path

    api_key_names = [
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
        "CEREBRAS_API_KEY",
        "SYN_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "OPENROUTER_API_KEY",
        "ZAI_API_KEY",
    ]

    # Step 1: Load from .env file if it exists (highest priority)
    # Look for .env in current working directory
    env_file = Path.cwd() / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv

            # override=False: .env should not override system env vars which may contain security settings
            load_dotenv(env_file, override=False)
        except ImportError:
            # python-dotenv not installed, skip .env loading
            pass

    # Step 2: Load from puppy.cfg, but only if not already set
    # This ensures .env has priority over puppy.cfg
    for key_name in api_key_names:
        # Only load from config if not already in environment
        if key_name not in os.environ or not os.environ[key_name]:
            value = get_api_key(key_name)
            if value:
                os.environ[key_name] = value


def get_default_agent() -> str:
    """
    Get the default agent name from puppy.cfg.

    Returns:
        str: The default agent name, or "code-puppy" if not set.
    """
    return get_value("default_agent") or "code-puppy"


def set_default_agent(agent_name: str) -> None:
    """
    Set the default agent name in puppy.cfg.

    Args:
        agent_name: The name of the agent to set as default.
    """
    set_config_value("default_agent", agent_name)


# --- FRONTEND EMITTER CONFIGURATION ---
def get_frontend_emitter_enabled() -> bool:
    """Check if frontend emitter is enabled."""
    return _is_truthy(get_value("frontend_emitter_enabled"), default=True)


def get_frontend_emitter_max_recent_events() -> int:
    """Get max number of recent events to buffer."""
    val = get_value("frontend_emitter_max_recent_events")
    if val is None:
        return 100
    try:
        return int(val)
    except ValueError:
        return 100


def get_frontend_emitter_queue_size() -> int:
    """Get max subscriber queue size."""
    val = get_value("frontend_emitter_queue_size")
    if val is None:
        return 100
    try:
        return int(val)
    except ValueError:
        return 100
