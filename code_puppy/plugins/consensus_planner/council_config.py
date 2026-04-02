"""Configuration helpers for Council Consensus.

Provides functions to get/set council consensus configuration and usage stats.
"""

from __future__ import annotations

from typing import Any

from code_puppy.config import get_value, set_config_value


def get_council_consensus_enabled() -> bool:
    """Check if council consensus is enabled.

    Returns:
        True if enabled, False otherwise.
    """
    val = get_value("consensus_council_enabled")
    return val is None or val.lower() in ("1", "true", "yes", "on")


def set_council_leader_model(model_name: str) -> None:
    """Set the leader model for council consensus.

    Args:
        model_name: The model name to use as leader.
    """
    set_config_value("consensus_council_leader", model_name)


def get_council_usage_stats() -> dict[str, Any]:
    """Get council consensus usage statistics.

    Returns:
        Dict with session_count, hour_count, total_tokens_estimate, etc.
    """
    from code_puppy.plugins.consensus_planner.council_safeguards import (
        get_council_usage_stats as _get_stats,
    )
    return _get_stats()


def reset_council_usage_stats() -> None:
    """Reset council consensus usage statistics (for testing)."""
    from code_puppy.plugins.consensus_planner.council_safeguards import (
        reset_council_stats,
    )
    reset_council_stats()


def get_council_safeguard_config() -> dict[str, Any]:
    """Get current council safeguard configuration.

    Returns:
        Dict with all safeguard configuration values.
    """
    return {
        "council_threshold": float(get_value("council_threshold") or "0.65"),
        "council_max_per_session": int(get_value("council_max_per_session") or "10"),
        "council_max_per_hour": int(get_value("council_max_per_hour") or "20"),
        "council_min_interval_seconds": int(
            get_value("council_min_interval_seconds") or "30"
        ),
        "council_preflight_model": get_value("council_preflight_model")
        or "(active model)",
        "council_confirm": get_value("council_confirm") or "ask",
    }


def set_council_safeguard_config(
    threshold: float | None = None,
    max_per_session: int | None = None,
    max_per_hour: int | None = None,
    min_interval_seconds: int | None = None,
    preflight_model: str | None = None,
    confirm: str | None = None,
) -> None:
    """Set council safeguard configuration values.

    Args:
        threshold: Minimum score to run (0.0-1.0)
        max_per_session: Max runs per session
        max_per_hour: Max runs per hour
        min_interval_seconds: Min seconds between runs
        preflight_model: Model for confidence check
        confirm: Confirmation behavior (ask/always/never)
    """
    if threshold is not None:
        set_config_value("council_threshold", str(threshold))
    if max_per_session is not None:
        set_config_value("council_max_per_session", str(max_per_session))
    if max_per_hour is not None:
        set_config_value("council_max_per_hour", str(max_per_hour))
    if min_interval_seconds is not None:
        set_config_value("council_min_interval_seconds", str(min_interval_seconds))
    if preflight_model is not None:
        set_config_value("council_preflight_model", preflight_model)
    if confirm is not None:
        set_config_value("council_confirm", confirm)
