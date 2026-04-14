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
- the bearer token authentication for mutating operations
"""

import logging
import os
import secrets
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

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


# =============================================================================
# Bearer Token Authentication for Mutating Operations
# =============================================================================

_bearer = HTTPBearer(auto_error=False)

# Local hosts that are allowed by default without authentication
_LOCAL_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})


def require_api_access(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> None:
    """Require authentication for mutating API operations.

    Security model (defense-in-depth):
    - Loopback clients (127.0.0.1, ::1, localhost) are allowed by default
    - If CODE_PUPPY_REQUIRE_TOKEN=1, even loopback clients need a token
    - Non-loopback clients always need a valid token
    - Token is validated against CODE_PUPPY_API_TOKEN env var using
      constant-time comparison to prevent timing attacks

    This dependency should be applied to all endpoints that perform
    destructive or state-mutating operations (execute commands,
    modify config, delete sessions, etc.).

    Args:
        request: The incoming HTTP request (for client IP extraction).
        creds: Bearer token credentials from the Authorization header.

    Raises:
        HTTPException: 403 if token not configured, 401 if auth required/invalid.

    Example:
        >>> @router.post("/dangerous")
        ... async def dangerous_op(_auth: None = Depends(require_api_access)):
        ...     pass
    """
    client_host = request.client.host if request.client else None

    # Check if we require token even for loopback (strict mode)
    strict_mode = os.getenv("CODE_PUPPY_REQUIRE_TOKEN", "").lower() in (
        "1",
        "true",
        "yes",
    )

    # Loopback access without explicit token requirement
    if client_host in _LOCAL_HOSTS and not strict_mode:
        return

    # Token required - validate it
    expected_token = os.getenv("CODE_PUPPY_API_TOKEN")
    if not expected_token:
        raise HTTPException(
            status_code=403,
            detail="API token not configured. Set CODE_PUPPY_API_TOKEN env var.",
        )

    if not creds:
        raise HTTPException(
            status_code=401,
            detail="Authorization header required (Bearer token)",
        )

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(creds.credentials, expected_token):
        raise HTTPException(status_code=401, detail="Invalid API token")


__all__ = [
    "get_allowed_origins",
    "is_trusted_origin",
    "require_api_access",
]
