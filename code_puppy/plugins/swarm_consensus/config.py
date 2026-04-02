"""
Configuration management for Agent Swarm Consensus.

Handles reading and writing swarm settings from/to puppy.cfg,
with sensible defaults and validation.
"""

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default configuration values
DEFAULT_SWARM_ENABLED = False
DEFAULT_SWARM_SIZE = 3
DEFAULT_CONSENSUS_THRESHOLD = 0.7
DEFAULT_SWARM_TIMEOUT = 300

# Config file section and keys
CONFIG_SECTION = "swarm_consensus"

# In-memory cache for config values
_config_cache: dict[str, Any] = {}


def get_config_path() -> Path:
    """Get the path to the puppy.cfg file.

    Checks for puppy.cfg in the current directory first,
    then falls back to ~/.code_puppy/puppy.cfg
    """
    local_config = Path("puppy.cfg")
    if local_config.exists():
        return local_config

    home_config = Path.home() / ".code_puppy" / "puppy.cfg"
    home_config.parent.mkdir(parents=True, exist_ok=True)
    return home_config


def _read_config_file() -> dict[str, dict[str, str]]:
    """Read and parse the config file into sections."""
    config_path = get_config_path()
    sections: dict[str, dict[str, str]] = {}

    if not config_path.exists():
        return sections

    try:
        current_section = None
        with open(config_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    current_section = line[1:-1]
                    sections[current_section] = {}
                elif current_section and "=" in line:
                    key, value = line.split("=", 1)
                    sections[current_section][key.strip()] = value.strip()
    except Exception as e:
        logger.warning(f"Failed to read config file: {e}")

    return sections


def _write_config_file(sections: dict[str, dict[str, str]]) -> None:
    """Write sections back to the config file."""
    config_path = get_config_path()

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            for section_name, keys in sections.items():
                f.write(f"[{section_name}]\n")
                for key, value in keys.items():
                    f.write(f"{key} = {value}\n")
                f.write("\n")
    except Exception as e:
        logger.warning(f"Failed to write config file: {e}")


def _get_config_value(key: str, default: Any, type_func: type) -> Any:
    """Get a config value from cache or config file."""
    cache_key = f"{CONFIG_SECTION}.{key}"
    if cache_key in _config_cache:
        return _config_cache[cache_key]

    # Check environment variable first
    env_key = f"CODE_PUPPY_SWARM_{key.upper()}"
    env_value = os.environ.get(env_key)
    if env_value is not None:
        try:
            value = type_func(env_value)
            _config_cache[cache_key] = value
            return value
        except ValueError:
            pass

    # Then check config file
    sections = _read_config_file()
    if CONFIG_SECTION in sections and key in sections[CONFIG_SECTION]:
        try:
            value = type_func(sections[CONFIG_SECTION][key])
            _config_cache[cache_key] = value
            return value
        except ValueError:
            pass

    return default


def _set_config_value(key: str, value: Any) -> None:
    """Set a config value in the config file."""
    cache_key = f"{CONFIG_SECTION}.{key}"
    _config_cache[cache_key] = value

    sections = _read_config_file()
    if CONFIG_SECTION not in sections:
        sections[CONFIG_SECTION] = {}
    sections[CONFIG_SECTION][key] = str(value)
    _write_config_file(sections)


def get_swarm_enabled() -> bool:
    """Check if swarm consensus is enabled.

    Returns:
        bool: True if swarm mode is enabled (default: False)
    """
    return _get_config_value("enabled", DEFAULT_SWARM_ENABLED, lambda x: x.lower() == "true")


def get_default_swarm_size() -> int:
    """Get the default number of agents in a swarm.

    Returns:
        int: Default swarm size (default: 3, minimum: 2)
    """
    value = _get_config_value("swarm_size", DEFAULT_SWARM_SIZE, int)
    return max(2, value)


def get_consensus_threshold() -> float:
    """Get the confidence threshold for declaring consensus.

    Returns:
        float: Threshold between 0.0 and 1.0 (default: 0.7)
    """
    value = _get_config_value("consensus_threshold", DEFAULT_CONSENSUS_THRESHOLD, float)
    return max(0.0, min(1.0, value))


def get_swarm_timeout_seconds() -> int:
    """Get the timeout for swarm execution.

    Returns:
        int: Timeout in seconds (default: 300, minimum: 10)
    """
    value = _get_config_value("timeout", DEFAULT_SWARM_TIMEOUT, int)
    return max(10, value)


def set_swarm_enabled(enabled: bool) -> None:
    """Enable or disable swarm consensus mode.

    Args:
        enabled: True to enable swarm mode
    """
    _set_config_value("enabled", "true" if enabled else "false")
    logger.info(f"Swarm consensus {'enabled' if enabled else 'disabled'}")


def set_swarm_size(size: int) -> None:
    """Set the default swarm size.

    Args:
        size: Number of agents (must be >= 2)
    """
    _set_config_value("swarm_size", max(2, size))


def set_consensus_threshold(threshold: float) -> None:
    """Set the consensus threshold.

    Args:
        threshold: Value between 0.0 and 1.0
    """
    _set_config_value("consensus_threshold", max(0.0, min(1.0, threshold)))


def set_swarm_timeout_seconds(seconds: int) -> None:
    """Set the swarm timeout.

    Args:
        seconds: Timeout in seconds (minimum 10)
    """
    _set_config_value("timeout", max(10, seconds))


def clear_config_cache() -> None:
    """Clear the in-memory config cache.

    Call this if you need to force re-reading from the config file.
    """
    global _config_cache
    _config_cache = {}


def get_full_config() -> dict[str, Any]:
    """Get all swarm configuration as a dictionary.

    Returns:
        dict: All configuration values
    """
    return {
        "enabled": get_swarm_enabled(),
        "swarm_size": get_default_swarm_size(),
        "consensus_threshold": get_consensus_threshold(),
        "timeout_seconds": get_swarm_timeout_seconds(),
    }
