"""Fast Puppy plugin — backend status (bd-50: Rust support removed).

This module previously provided Rust crate discovery and building.
With bd-50, all Rust integration has been removed.

bd-50: Retained only get_available_backends() for backward compatibility.
"""

import logging

logger = logging.getLogger(__name__)


def get_available_backends() -> dict[str, bool]:
    """Return backend availability status.

    bd-50: Rust integration removed. Returns Python-only status.

    Returns:
        Dict with python_fallback=True, all others False
    """
    return {
        "elixir_available": False,
        "rust_installed": False,
        "python_fallback": True,
    }
