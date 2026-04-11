"""Security helpers for the Code Puppy local API.

The API exposes a REST command executor and PTY WebSocket that together form
a local command/shell surface. Even though the server is intended for
localhost-only use, a browser visiting an untrusted site while the server is
running would otherwise be able to drive those endpoints via CORS-permissive
XHR or cross-origin WebSocket upgrades (WebSocket upgrades are not subject to
the same-origin policy).

This module centralises the allow-list used by:
- the FastAPI CORS middleware
- the /ws/events and /ws/terminal origin enforcement
"""

import logging
import os
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Default localhost ports we trust. Kept intentionally narrow: these are the
# dev-server / browser ports that a user is likely to hit the API from.
_DEFAULT_PORTS = (
    "8765",  # Code Puppy API default
    "3000",  # common React dev
    "5173",  # common Vite dev
    "8000",
    "8080",
)

_DEFAULT_HOSTS = ("localhost", "127.0.0.1", "[::1]")


def _build_default_origins() -> list[str]:
    origins: list[str] = []
    for scheme in ("http", "https"):
        for host in _DEFAULT_HOSTS:
            # Host without a port (covers same-origin on default 80/443)
            origins.append(f"{scheme}://{host}")
            for port in _DEFAULT_PORTS:
                origins.append(f"{scheme}://{host}:{port}")
    return origins


def get_allowed_origins() -> list[str]:
    """Return the list of origins allowed to access the local API.

    Honours the ``CODE_PUPPY_ALLOWED_ORIGINS`` environment variable (comma
    separated) so users running the UI on a non-default port can opt in
    without code changes. Falls back to a set of localhost origins on the
    handful of dev ports we commonly see.
    """
    override = os.environ.get("CODE_PUPPY_ALLOWED_ORIGINS")
    if override:
        parts = [o.strip() for o in override.split(",") if o.strip()]
        if parts:
            return parts
    return _build_default_origins()


def is_trusted_origin(origin: str | None) -> bool:
    """Check whether a WebSocket ``Origin`` header is in the allow-list.

    An explicit ``None`` / missing header is rejected: modern browsers always
    send ``Origin`` on WebSocket upgrades, so its absence indicates either a
    non-browser client (which should authenticate through another channel) or
    a stripped header we don't want to trust. Non-browser tooling that wants
    to connect can set ``CODE_PUPPY_ALLOWED_ORIGINS`` or add an explicit
    loopback origin.
    """
    if not origin:
        return False

    # Allow a literal match against the configured list.
    allowed = get_allowed_origins()
    if origin in allowed:
        return True

    # Fall back to a structural check: any http(s) origin pointing at a
    # loopback host is trusted regardless of port. This keeps ad-hoc dev on
    # random high ports working without forcing users to touch env vars.
    try:
        parsed = urlparse(origin)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    return False


__all__ = ["get_allowed_origins", "is_trusted_origin"]
