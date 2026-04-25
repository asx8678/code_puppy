"""Runtime API authentication for Code Puppy dashboard.

Generates a random bearer token at first launch and persists it in a
user-private file under STATE_DIR.  All ``/api/runtime/*`` routes and
the ``/ws/events`` WebSocket require this token — either via the
``X-Code-Puppy-Runtime-Token`` header or an ``HttpOnly; SameSite=Strict``
cookie named ``code_puppy_runtime_token``.

The cookie is set automatically on dashboard / root / app page responses
so same-origin browser fetches work without JavaScript needing to read
the token.
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
from pathlib import Path
from typing import Optional

from fastapi import Cookie, Header, HTTPException, Request, status
from fastapi.responses import Response

logger = logging.getLogger(__name__)

_TOKEN_FILE_NAME = "runtime_token"
_COOKIE_NAME = "code_puppy_runtime_token"
_HEADER_NAME = "X-Code-Puppy-Runtime-Token"

# Allowed localhost origins for same-origin dashboard (CORS + origin check).
_LOCALHOST_ORIGINS = frozenset(
    {
        "http://127.0.0.1",
        "http://localhost",
        "http://[::1]",
    }
)


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------


def _token_path() -> Path:
    """Return the path to the runtime-token file under STATE_DIR."""
    from code_puppy.config import STATE_DIR

    state = Path(STATE_DIR)
    state.mkdir(parents=True, exist_ok=True)
    return state / _TOKEN_FILE_NAME


def _generate_token() -> str:
    """Generate a cryptographically random hex token (256 bits)."""
    return secrets.token_hex(32)


def get_or_create_runtime_token() -> str:
    """Load the persisted runtime token, creating one if necessary.

    The token file is created with mode 0o600 (owner-read/write only).
    """
    path = _token_path()
    if path.exists():
        try:
            token = path.read_text().strip()
            if token and len(token) >= 32:
                return token
        except OSError:
            pass

    token = _generate_token()
    path.write_text(token)
    try:
        os.chmod(path, 0o600)
    except OSError:
        logger.warning("Could not set permissions on runtime token file")
    logger.info("Generated new runtime API token at %s", path)
    return token


def verify_token(provided: Optional[str]) -> bool:
    """Constant-time comparison of a provided token against the stored one."""
    if not provided:
        return False
    expected = get_or_create_runtime_token()
    return hmac.compare_digest(provided, expected)


# ---------------------------------------------------------------------------
# Origin / host validation (CSRF protection)
# ---------------------------------------------------------------------------


def is_localhost_origin(origin: Optional[str]) -> bool:
    """Return True if *origin* is a localhost origin or absent.

    An absent Origin header means same-origin (typical for direct API
    calls from the dashboard).  Only cross-site browser requests with a
    non-localhost Origin are rejected.
    """
    if not origin:
        return True
    # Strip trailing slash for comparison
    origin_clean = origin.rstrip("/")
    if origin_clean in _LOCALHOST_ORIGINS:
        return True
    # Allow any port on localhost / 127.0.0.1 / [::1]
    for base in _LOCALHOST_ORIGINS:
        if origin_clean.startswith(base + ":"):
            return True
    return False


def check_origin(request: Request) -> None:
    """Raise 403 if the request has a cross-site Origin header."""
    origin = request.headers.get("origin")
    if not is_localhost_origin(origin):
        logger.warning("Rejected cross-site request from Origin: %s", origin)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-site requests are not allowed",
        )


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


async def require_runtime_auth(
    request: Request,
    x_code_puppy_runtime_token: Optional[str] = Header(
        None, alias=_HEADER_NAME, include_in_schema=False
    ),
    code_puppy_runtime_token: Optional[str] = Cookie(None, alias=_COOKIE_NAME),
) -> None:
    """FastAPI dependency: require valid runtime token via header or cookie.

    Also rejects cross-site browser requests (Origin check).
    """
    check_origin(request)
    provided = x_code_puppy_runtime_token or code_puppy_runtime_token
    if not verify_token(provided):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing runtime token",
        )


async def require_runtime_auth_optional(
    request: Request,
    x_code_puppy_runtime_token: Optional[str] = Header(
        None, alias=_HEADER_NAME, include_in_schema=False
    ),
    code_puppy_runtime_token: Optional[str] = Cookie(None, alias=_COOKIE_NAME),
) -> bool:
    """Soft auth check — returns True if authenticated, False otherwise.

    Used for WebSocket connections where we want to reject unauthenticated
    connections but not raise an HTTPException before the WS handshake.
    """
    check_origin(request)
    provided = x_code_puppy_runtime_token or code_puppy_runtime_token
    return verify_token(provided)


# ---------------------------------------------------------------------------
# Cookie helper
# ---------------------------------------------------------------------------


def set_runtime_token_cookie(response: Response, token: str) -> Response:
    """Set the ``HttpOnly; SameSite=Strict`` auth cookie on *response*.

    This allows same-origin dashboard JavaScript ``fetch()`` calls to
    include the cookie automatically, so the token never needs to be
    read by client-side JS.
    """
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="strict",
        path="/",
        max_age=86400 * 30,  # 30 days
    )
    return response


def attach_token_cookie_to_response(response: Response) -> Response:
    """Convenience: fetch the runtime token and set it on *response*."""
    token = get_or_create_runtime_token()
    return set_runtime_token_cookie(response, token)


# ---------------------------------------------------------------------------
# WebSocket auth helpers
# ---------------------------------------------------------------------------


def extract_ws_token(
    cookie_header: Optional[str] = None,
    protocol_headers: Optional[list[tuple[str, str]]] = None,
) -> Optional[str]:
    """Extract the runtime token from WebSocket handshake headers.

    WebSocket connections don't support custom headers easily from the
    browser, so we primarily rely on the cookie.  As a fallback, accept
    the token as a protocol-level header (e.g. from non-browser clients).
    """
    # Check cookie first
    if cookie_header:
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith(f"{_COOKIE_NAME}="):
                return part.split("=", 1)[1].strip()

    # Check protocol headers (non-browser clients)
    if protocol_headers:
        for key, value in protocol_headers:
            if key.lower() == _HEADER_NAME.lower():
                return value

    return None


def validate_ws_origin(origin: Optional[str]) -> bool:
    """Validate a WebSocket Origin header for same-origin policy."""
    return is_localhost_origin(origin)
