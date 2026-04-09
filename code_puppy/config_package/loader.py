"""Configuration loader for code_puppy typed settings.

This module provides the loading logic for `PuppyConfig`, reading from
multiple sources in priority order:

1. Environment variables (highest priority)
2. puppy.cfg file (via legacy config module)
3. Built-in defaults (lowest priority)

Examples:
    >>> # Load fresh config (not cached)
    >>> from code_puppy.config_package.loader import load_puppy_config
    >>> cfg = load_puppy_config()

    >>> # Use singleton cache
    >>> from code_puppy.config_package import get_puppy_config
    >>> cfg = get_puppy_config()  # Same instance on subsequent calls

    >>> # Reload after config changes
    >>> cfg = reload_puppy_config()
"""

import threading
from pathlib import Path
from typing import Any

from code_puppy.config_package.env_helpers import (
    env_bool,
    env_int,
    env_path,
    get_first_env,
)
from code_puppy.config_package.models import PuppyConfig


# Singleton cache
_cached_config: PuppyConfig | None = None
_cache_lock = threading.Lock()


def _env_optional_float(*names: str, default: float | None) -> float | None:
    """Parse an optional float env var. Returns default if unset or invalid.

    Args:
        *names: One or more environment variable names to check.
        default: The default value to return if no valid env var is found.

    Returns:
        The parsed float value, or default if parsing fails or no var is set.
    """
    raw = get_first_env(*names)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_legacy_config() -> tuple[bool, Any]:
    """Safely import and return the legacy config module.

    Returns:
        Tuple of (success: bool, config_module: Any).
        If import fails, returns (False, None).
    """
    try:
        from code_puppy import config as legacy_config

        return True, legacy_config
    except Exception:
        return False, None


def _get_legacy_value(
    legacy_config: Any, key: str, default: str | None = None
) -> str | None:
    """Safely get a value from legacy config.

    Args:
        legacy_config: The legacy config module.
        key: Config key to look up.
        default: Default value if lookup fails.

    Returns:
        The config value or default.
    """
    try:
        if hasattr(legacy_config, "get_value"):
            return legacy_config.get_value(key) or default
    except Exception:
        pass
    return default


def load_puppy_config() -> PuppyConfig:
    """Load the typed PuppyConfig from env vars, puppy.cfg, and defaults.

    Priority order (highest first):
        1. Environment variables (via env_helpers)
        2. puppy.cfg file (via legacy config module)
        3. Hardcoded defaults (lowest priority)

    This function is additive — does NOT replace code_puppy.config.
    Both APIs coexist. Use whichever fits your call site better.

    Returns:
        A fully populated PuppyConfig instance.

    Raises:
        Never raises — all failures fall back to hardcoded defaults.
        Config loading must never crash the app.

    Example:
        >>> cfg = load_puppy_config()
        >>> print(f"Using model: {cfg.default_model}")
        >>> print(f"Data dir: {cfg.data_dir}")
    """
    # Attempt to import legacy config (graceful fallback if it fails)
    legacy_ok, legacy_config = _get_legacy_config()

    # Helper to get values with fallback chain: env -> legacy -> default
    def _get_str(
        env_names: tuple[str, ...],
        legacy_key: str,
        hardcoded_default: str,
        legacy_fallback_names: tuple[str, ...] = (),
    ) -> str:
        """Get string value from env, legacy config, or default."""
        # Try env vars first
        env_val = get_first_env(*env_names)
        if env_val is not None:
            return env_val

        # Try legacy config if available
        if legacy_ok:
            # First try the primary legacy key
            legacy_val = _get_legacy_value(legacy_config, legacy_key)
            if legacy_val:
                return legacy_val

            # Try legacy fallback names (for compatibility)
            for fallback_key in legacy_fallback_names:
                legacy_val = _get_legacy_value(legacy_config, fallback_key)
                if legacy_val:
                    return legacy_val

        return hardcoded_default

    def _get_bool(
        env_names: tuple[str, ...],
        legacy_key: str,
        hardcoded_default: bool,
    ) -> bool:
        """Get boolean value from env, legacy config, or default."""
        # Check env vars first (these already have default handling)
        env_result = env_bool(*env_names, default=hardcoded_default)

        # If env vars were set, use that value
        if get_first_env(*env_names) is not None:
            return env_result

        # Try legacy config
        if legacy_ok:
            legacy_val = _get_legacy_value(legacy_config, legacy_key)
            if legacy_val is not None:
                # Parse legacy value as bool
                return legacy_val.strip().lower() in {"1", "true", "yes", "on"}

        return hardcoded_default

    def _get_int(
        env_names: tuple[str, ...],
        legacy_key: str,
        hardcoded_default: int,
        min_val: int | None = None,
        max_val: int | None = None,
    ) -> int:
        """Get integer value from env, legacy config, or default."""
        # Check env vars first
        env_result = env_int(*env_names, default=hardcoded_default)

        # If env vars were set, use that value (already validated)
        if get_first_env(*env_names) is not None:
            if min_val is not None:
                env_result = max(min_val, env_result)
            if max_val is not None:
                env_result = min(max_val, env_result)
            return env_result

        # Try legacy config
        if legacy_ok:
            legacy_val = _get_legacy_value(legacy_config, legacy_key)
            if legacy_val is not None:
                try:
                    result = int(legacy_val)
                    if min_val is not None:
                        result = max(min_val, result)
                    if max_val is not None:
                        result = min(max_val, result)
                    return result
                except (ValueError, TypeError):
                    pass

        return hardcoded_default

    def _get_float(
        env_names: tuple[str, ...],
        legacy_key: str,
        hardcoded_default: float,
        min_val: float | None = None,
        max_val: float | None = None,
    ) -> float:
        """Get float value from env, legacy config, or default."""
        # Check env vars first
        env_result = _env_optional_float(*env_names, default=hardcoded_default)

        if min_val is not None:
            env_result = (
                max(min_val, env_result)
                if env_result is not None
                else hardcoded_default
            )
        if max_val is not None:
            env_result = (
                min(max_val, env_result)
                if env_result is not None
                else hardcoded_default
            )

        # Try legacy config
        if legacy_ok and env_result == hardcoded_default:
            legacy_val = _get_legacy_value(legacy_config, legacy_key)
            if legacy_val is not None:
                try:
                    result = float(legacy_val)
                    if min_val is not None:
                        result = max(min_val, result)
                    if max_val is not None:
                        result = min(max_val, result)
                    return result
                except (ValueError, TypeError):
                    pass

        return env_result if env_result is not None else hardcoded_default

    # ─────────────────────────────────────────────────────────────
    # Build paths (using legacy constants or env vars)
    # ─────────────────────────────────────────────────────────────

    # Get base paths from legacy config or env vars
    data_dir: Path
    config_dir: Path

    if legacy_ok:
        # Use legacy constants if available
        try:
            data_dir = env_path(
                "PUPPY_DATA_DIR", "CODE_PUPPY_DATA_DIR", default=legacy_config.DATA_DIR
            )
        except Exception:
            data_dir = env_path(
                "PUPPY_DATA_DIR", "CODE_PUPPY_DATA_DIR", default="~/.code_puppy"
            )

        try:
            config_dir = env_path(
                "PUPPY_CONFIG_DIR",
                "CODE_PUPPY_CONFIG_DIR",
                default=legacy_config.CONFIG_DIR,
            )
        except Exception:
            config_dir = env_path(
                "PUPPY_CONFIG_DIR", "CODE_PUPPY_CONFIG_DIR", default="~/.code_puppy"
            )

        try:
            config_file = Path(legacy_config.CONFIG_FILE)
        except Exception:
            config_file = config_dir / "puppy.cfg"

        try:
            models_file = Path(legacy_config.MODELS_FILE)
        except Exception:
            models_file = data_dir / "models.json"
    else:
        # No legacy config — use env vars with hardcoded defaults
        data_dir = env_path(
            "PUPPY_DATA_DIR", "CODE_PUPPY_DATA_DIR", default="~/.code_puppy"
        )
        config_dir = env_path(
            "PUPPY_CONFIG_DIR", "CODE_PUPPY_CONFIG_DIR", default="~/.code_puppy"
        )
        config_file = config_dir / "puppy.cfg"
        models_file = data_dir / "models.json"

    # Sessions dir is derived from data_dir
    sessions_dir = env_path("PUPPY_SESSIONS_DIR", default=data_dir / "sessions")

    # ─────────────────────────────────────────────────────────────
    # Build and return PuppyConfig
    # ─────────────────────────────────────────────────────────────

    return PuppyConfig(
        # Paths
        data_dir=data_dir,
        config_dir=config_dir,
        config_file=config_file,
        sessions_dir=sessions_dir,
        models_file=models_file,
        # Agent / Model
        default_agent=_get_str(("PUPPY_DEFAULT_AGENT",), "default_agent", "code-puppy"),
        default_model=_get_str(
            ("PUPPY_DEFAULT_MODEL", "CODE_PUPPY_DEFAULT_MODEL"),
            "model",
            "claude-opus-4-6",
        ),
        # Concurrency (from parallel task)
        max_concurrent_runs=_get_int(
            ("PUPPY_MAX_CONCURRENT_RUNS", "CODE_PUPPY_MAX_CONCURRENT_RUNS"),
            "max_concurrent_runs",
            2,
            min_val=1,
            max_val=100,
        ),
        allow_parallel_runs=_get_bool(
            ("PUPPY_ALLOW_PARALLEL_RUNS", "CODE_PUPPY_ALLOW_PARALLEL_RUNS"),
            "allow_parallel_runs",
            True,
        ),
        run_wait_timeout=_env_optional_float(
            "PUPPY_RUN_WAIT_TIMEOUT",
            "CODE_PUPPY_RUN_WAIT_TIMEOUT",
            default=None,
        ),
        # Messaging / UI
        ws_history_maxlen=_get_int(
            ("PUPPY_WS_HISTORY_MAXLEN",),
            "ws_history_maxlen",
            200,
            min_val=10,
            max_val=10000,
        ),
        # Feature flags
        session_logger_enabled=_get_bool(
            ("PUPPY_SESSION_LOGGER", "CODE_PUPPY_SESSION_LOGGER"),
            "session_logger_enabled",
            False,
        ),
        rust_autobuild_disabled=_get_bool(
            ("PUPPY_DISABLE_RUST_AUTOBUILD", "CODE_PUPPY_DISABLE_RUST_AUTOBUILD"),
            "disable_rust_autobuild",
            False,
        ),
        enable_dbos=_get_bool(
            ("PUPPY_ENABLE_DBOS", "CODE_PUPPY_ENABLE_DBOS"),
            "enable_dbos",
            True,
        ),
        enable_streaming=_get_bool(
            ("PUPPY_ENABLE_STREAMING",),
            "enable_streaming",
            True,
        ),
        enable_agent_memory=_get_bool(
            ("PUPPY_ENABLE_AGENT_MEMORY",),
            "enable_agent_memory",
            False,
        ),
        # UI / Behavior
        temperature=_get_float(
            ("PUPPY_TEMPERATURE",),
            "temperature",
            0.0,
            min_val=0.0,
            max_val=2.0,
        ),
        protected_token_count=_get_int(
            ("PUPPY_PROTECTED_TOKEN_COUNT",),
            "protected_token_count",
            4000,
            min_val=0,
            max_val=100000,
        ),
        message_limit=_get_int(
            ("PUPPY_MESSAGE_LIMIT",),
            "message_limit",
            100,
            min_val=10,
            max_val=10000,
        ),
        compaction_strategy=_get_str(
            ("PUPPY_COMPACTION_STRATEGY",), "compaction_strategy", "summarize"
        ),
        # Debug / Logging
        debug=_get_bool(
            ("PUPPY_DEBUG", "CODE_PUPPY_DEBUG", "DEBUG"),
            "debug",
            False,
        ),
        log_level=_get_str(
            ("PUPPY_LOG_LEVEL", "CODE_PUPPY_LOG_LEVEL", "LOG_LEVEL"),
            "log_level",
            "INFO",
        ),
        # Identity
        puppy_name=_get_str(("PUPPY_NAME",), "puppy_name", "Puppy"),
        owner_name=_get_str(
            ("PUPPY_OWNER_NAME", "CODE_PUPPY_OWNER"), "owner_name", "Master"
        ),
    )


def get_puppy_config() -> PuppyConfig:
    """Return cached singleton (lazy init).

    The first call loads and caches the config. Subsequent calls return
    the same instance for efficiency.

    Returns:
        The cached PuppyConfig instance.

    Example:
        >>> cfg = get_puppy_config()  # Loads on first call
        >>> cfg2 = get_puppy_config()  # Same instance
        >>> assert cfg is cfg2
    """
    global _cached_config
    if _cached_config is None:
        with _cache_lock:
            if _cached_config is None:
                _cached_config = load_puppy_config()
    return _cached_config


def reload_puppy_config() -> PuppyConfig:
    """Force reload (for tests or after puppy.cfg edits).

    Clears the singleton cache and returns a fresh config loaded
    from current environment and puppy.cfg.

    Returns:
        A fresh PuppyConfig instance.

    Example:
        >>> # After editing puppy.cfg
        >>> cfg = reload_puppy_config()
    """
    global _cached_config
    with _cache_lock:
        _cached_config = load_puppy_config()
    return _cached_config


def reset_puppy_config_for_tests() -> None:
    """Clear the cache (test helper).

    Resets the singleton cache so that the next call to `get_puppy_config()`
    will load fresh. Use this in test fixtures for isolation.

    Example:
        >>> # In a pytest fixture
        >>> def setup_teardown():
        ...     reset_puppy_config_for_tests()
        ...     yield
        ...     reset_puppy_config_for_tests()
    """
    global _cached_config
    with _cache_lock:
        _cached_config = None
