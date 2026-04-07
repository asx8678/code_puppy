"""Bridge to turbo_parse Rust extension module with Python fallback.

Provides graceful degradation when the Rust extension is not available.
"""

from typing import Any

try:
    from turbo_parse import (
        health_check,
        stats,
        get_language,
        is_language_supported,
        supported_languages,
        parse_file,
        parse_source,
        parse_files_batch,
        extract_symbols,
        extract_symbols_from_file,
        extract_syntax_diagnostics,
        get_folds,
        get_folds_from_file,
        get_highlights,
        get_highlights_from_file,
    )

    TURBO_PARSE_AVAILABLE = True
except ImportError:
    TURBO_PARSE_AVAILABLE = False

    # Provide stub functions that return fallback values
    def health_check() -> dict[str, Any]:
        """Return health status when Rust module is unavailable."""
        return {
            "available": False,
            "version": None,
            "languages": [],
            "cache_available": False,
        }

    def stats() -> dict[str, Any]:
        """Return empty stats when Rust module is unavailable."""
        return {
            "total_parses": 0,
            "average_parse_time_ms": 0.0,
            "languages_used": {},
            "cache_hits": 0,
            "cache_misses": 0,
            "cache_evictions": 0,
            "cache_hit_ratio": 0.0,
        }

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

    def parse_source(source: str, language: str) -> dict[str, Any]:
        """Fallback for parse_source when Rust module is unavailable.
        
        Returns an error dict indicating the Rust module is not available.
        """
        return {
            "language": language,
            "tree": None,
            "parse_time_ms": 0.0,
            "success": False,
            "errors": [{
                "message": "turbo_parse module not available - parsing disabled",
                "severity": "error",
            }],
        }

    def parse_file(path: str, language: str | None = None) -> dict[str, Any]:
        """Fallback for parse_file when Rust module is unavailable.
        
        Returns an error dict indicating the Rust module is not available.
        """
        return {
            "language": language or "unknown",
            "tree": None,
            "parse_time_ms": 0.0,
            "success": False,
            "errors": [{
                "message": "turbo_parse module not available - parsing disabled",
                "severity": "error",
            }],
        }

    def extract_syntax_diagnostics(source: str, language: str) -> dict[str, Any]:  # noqa: ARG001
        """Fallback for extract_syntax_diagnostics when Rust module is unavailable.
        
        Returns an error dict indicating the Rust module is not available.
        """
        return {
            "diagnostics": [],
            "error_count": 0,
            "warning_count": 0,
            "error": "turbo_parse module not available - syntax diagnostics disabled",
        }

    def parse_files_batch(paths, max_workers=None, timeout_ms=None):
        return {
            "results": [{"file_path": p, "success": False, "errors": [{"message": "turbo_parse not available"}]} for p in paths],
            "total_time_ms": 0.0,
            "files_processed": len(paths),
            "success_count": 0,
            "error_count": len(paths),
            "all_succeeded": len(paths) == 0,
        }

    def extract_symbols(source, language):
        return {"success": False, "symbols": [], "error": "turbo_parse not available", "extraction_time_ms": 0.0}

    def extract_symbols_from_file(path, language=None):
        return {"success": False, "symbols": [], "error": "turbo_parse not available", "extraction_time_ms": 0.0}

    def get_folds(source, language):
        return {"success": False, "folds": [], "error": "turbo_parse not available", "extraction_time_ms": 0.0}

    def get_folds_from_file(path, language=None):
        return {"success": False, "folds": [], "error": "turbo_parse not available", "extraction_time_ms": 0.0}

    def get_highlights(source, language):
        return {"success": False, "captures": [], "error": "turbo_parse not available", "extraction_time_ms": 0.0}

    def get_highlights_from_file(path, language=None):
        return {"success": False, "captures": [], "error": "turbo_parse not available", "extraction_time_ms": 0.0}


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


__all__ = [
    "health_check",
    "stats",
    "get_language",
    "is_language_supported",
    "supported_languages",
    "parse_file",
    "parse_source",
    "parse_files_batch",
    "extract_symbols",
    "extract_symbols_from_file",
    "extract_syntax_diagnostics",
    "get_folds",
    "get_folds_from_file",
    "get_highlights",
    "get_highlights_from_file",
    "is_turbo_parse_enabled",
    "set_turbo_parse_enabled",
    "get_turbo_parse_status",
    "TURBO_PARSE_AVAILABLE",
]
