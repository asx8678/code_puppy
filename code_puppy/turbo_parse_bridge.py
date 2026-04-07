"""Bridge to turbo_parse Rust extension module with Python fallback.

Provides graceful degradation when the Rust extension is not available.
"""

from typing import Any

try:
    from turbo_parse import (
        health_check,
        get_language,
        is_language_supported,
        supported_languages,
    )

    TURBO_PARSE_AVAILABLE = True
except ImportError:
    TURBO_PARSE_AVAILABLE = False

    # Provide stub functions that return fallback values
    def health_check() -> dict[str, Any]:
        """Return health status when Rust module is unavailable."""
        return {"available": False, "version": None}

    def get_language(name: str) -> dict[str, Any]:
        """Return unsupported status when Rust module is unavailable."""
        return {
            "name": name,
            "supported": False,
            "error": f"Unsupported language: '{name}' (turbo_parse module not available)",
        }

    def is_language_supported(name: str) -> bool:
        """Always returns False when Rust module is unavailable."""
        return False

    def supported_languages() -> dict[str, Any]:
        """Return empty list when Rust module is unavailable."""
        return {"languages": [], "count": 0}


# --- Turbo Parse toggle -----------------------------------------------------
# When True (default), Rust acceleration is used at runtime if the module
# is installed. Can be disabled to fall through to Python path.
_turbo_parse_user_enabled: bool = True


def is_turbo_parse_enabled() -> bool:
    """Check if turbo_parse is both available AND enabled by the user."""
    return TURBO_PARSE_AVAILABLE and _turbo_parse_user_enabled


def set_turbo_parse_enabled(enabled: bool) -> None:
    """Toggle turbo_parse on or off at runtime."""
    global _turbo_parse_user_enabled
    _turbo_parse_user_enabled = enabled


def get_turbo_parse_status() -> dict:
    """Return diagnostic info for turbo_parse status."""
    return {
        "installed": TURBO_PARSE_AVAILABLE,
        "enabled": _turbo_parse_user_enabled,
        "active": is_turbo_parse_enabled(),
    }
