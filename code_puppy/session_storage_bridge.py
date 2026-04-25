"""Bridge to Elixir session storage.

This module provides the bridge between Python session_storage.py and
Elixir Ecto-backed session storage. It uses ElixirTransport when available
and falls back to the legacy file-based implementation.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Global transport instance (lazy-loaded)
_transport = None
_transport_available: bool | None = None


def _get_transport():
    """Get or create the ElixirTransport instance."""
    global _transport, _transport_available

    if _transport_available is None:
        try:
            from code_puppy.elixir_transport import ElixirTransport

            _transport = ElixirTransport()
            _transport.start()
            _transport_available = True
            logger.info("Session storage bridge initialized (Elixir transport)")
        except Exception as exc:
            _transport_available = False
            _transport = None
            logger.warning(
                "Elixir transport unavailable for session storage: %s. "
                "Falling back to file-based storage.",
                exc
            )

    return _transport


def is_available() -> bool:
    """Check if the Elixir bridge is available."""
    transport = _get_transport()
    return transport is not None


def shutdown():
    """Shutdown the transport connection."""
    global _transport, _transport_available

    if _transport is not None:
        try:
            _transport.stop()
        except Exception as exc:
            logger.warning("Error stopping session storage bridge: %s", exc)
        finally:
            _transport = None
            _transport_available = None


def save_session(
    name: str,
    history: list[dict[str, Any]],
    compacted_hashes: list[str] | None = None,
    total_tokens: int = 0,
    auto_saved: bool = False,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Save session via Elixir bridge."""
    transport = _get_transport()
    if transport is None:
        raise RuntimeError("Elixir transport not available")

    return transport.session_save(
        name=name,
        history=history,
        compacted_hashes=compacted_hashes,
        total_tokens=total_tokens,
        auto_saved=auto_saved,
        timestamp=timestamp,
    )


def load_session(name: str) -> dict[str, Any]:
    """Load session via Elixir bridge."""
    transport = _get_transport()
    if transport is None:
        raise RuntimeError("Elixir transport not available")

    return transport.session_load(name=name)


def load_session_full(name: str) -> dict[str, Any]:
    """Load session with metadata via Elixir bridge."""
    transport = _get_transport()
    if transport is None:
        raise RuntimeError("Elixir transport not available")

    return transport.session_load_full(name=name)


def list_sessions() -> list[str]:
    """List sessions via Elixir bridge."""
    transport = _get_transport()
    if transport is None:
        raise RuntimeError("Elixir transport not available")

    return transport.session_list()


def list_sessions_with_metadata() -> list[dict[str, Any]]:
    """List sessions with metadata via Elixir bridge."""
    transport = _get_transport()
    if transport is None:
        raise RuntimeError("Elixir transport not available")

    return transport.session_list_with_metadata()


def delete_session(name: str) -> bool:
    """Delete session via Elixir bridge."""
    transport = _get_transport()
    if transport is None:
        raise RuntimeError("Elixir transport not available")

    return transport.session_delete(name=name)


def cleanup_sessions(max_sessions: int = 10) -> list[str]:
    """Cleanup sessions via Elixir bridge."""
    transport = _get_transport()
    if transport is None:
        raise RuntimeError("Elixir transport not available")

    return transport.session_cleanup(max_sessions=max_sessions)


def session_exists(name: str) -> bool:
    """Check session exists via Elixir bridge."""
    transport = _get_transport()
    if transport is None:
        raise RuntimeError("Elixir transport not available")

    return transport.session_exists(name=name)


def session_count() -> int:
    """Get session count via Elixir bridge."""
    transport = _get_transport()
    if transport is None:
        raise RuntimeError("Elixir transport not available")

    return transport.session_count()
