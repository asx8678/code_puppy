"""Turbo Parse Plugin — Callback Registration.

Registers the turbo_parse parsing system with code_puppy's callback hooks:
- startup: Check turbo_parse Rust module availability and log status
- register_tools: Placeholder for future parse_code tool registration
"""

import logging
from typing import Any, List, Dict

from code_puppy.callbacks import register_callback

logger = logging.getLogger(__name__)

# Global flag tracking turbo_parse availability
_turbo_parse_available: bool = False
_turbo_parse_version: str | None = None


def _on_startup():
    """Initialize the turbo_parse plugin on startup.
    
    Attempts to import the turbo_parse Rust module and logs availability status.
    Gracefully falls back to pure Python if the Rust module is not available.
    """
    global _turbo_parse_available, _turbo_parse_version
    
    try:
        import turbo_parse
        _turbo_parse_available = True
        _turbo_parse_version = getattr(turbo_parse, "__version__", "unknown")
        
        # Try to call health_check if available
        try:
            health = turbo_parse.health_check()
            logger.info(
                f"🚀 Turbo Parse: Rust module available (version: {health.get('version', 'unknown')})"
            )
        except AttributeError:
            logger.info(
                f"🚀 Turbo Parse: Rust module available (version: {_turbo_parse_version})"
            )
        except Exception as e:
            logger.warning(
                f"🚀 Turbo Parse: Rust module available but health check failed: {e}"
            )
            
    except ImportError:
        _turbo_parse_available = False
        _turbo_parse_version = None
        logger.info(
            "🐍 Turbo Parse: Rust module not available, using pure Python fallback"
        )
    except Exception as e:
        _turbo_parse_available = False
        _turbo_parse_version = None
        logger.warning(
            f"⚠️ Turbo Parse: Unexpected error loading Rust module: {e}. "
            f"Using pure Python fallback."
        )


def _register_tools() -> List[Dict[str, Any]]:
    """Register turbo_parse tools.
    
    This callback will be used in the future to add the parse_code tool
    for high-performance code parsing operations.
    
    Returns:
        List of tool definitions. Currently empty (placeholder for future use).
    """
    # Placeholder for future parse_code tool registration
    # When implemented, this will return:
    # [
    #     {
    #         "name": "parse_code",
    #         "register_func": _register_parse_code_tool,
    #     }
    # ]
    return []


# Register all callbacks
register_callback("startup", _on_startup)
register_callback("register_tools", _register_tools)

logger.debug("Turbo Parse plugin callbacks registered")
