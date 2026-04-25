"""Tests for code_puppy/api/auth.py — runtime token authentication."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from code_puppy.api.auth import (
    _COOKIE_NAME,
    _HEADER_NAME,
    extract_ws_token,
    get_or_create_runtime_token,
    is_localhost_origin,
    require_runtime_auth,
    set_runtime_token_cookie,
    validate_origin_against_host,
    validate_ws_origin,
    verify_token,
)


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------


class TestTokenManagement:
    """Tests for token generation, persistence, and verification."""

    def test_generate_and_load_token(self, tmp_path: Path) -> None:
        with patch("code_puppy.api.auth._token_path", return_value=tmp_path / "rt"):
            token = get_or_create_runtime_token()
            assert token and len(token) >= 32
            # Re-loading should return the same token
            assert get_or_create_runtime_token() == token

    def test_token_file_permissions(self, tmp_path: Path) -> None:
        token_path = tmp_path / "rt"
        with patch("code_puppy.api.auth._token_path", return_value=token_path):
            get_or_create_runtime_token()
            # On POSIX, mode should be 0o600
            if os.name != "nt":
                mode = token_path.stat().st_mode & 0o777
                assert mode == 0o600

    def test_verify_token_correct(self, tmp_path: Path) -> None:
        with patch("code_puppy.api.auth._token_path", return_value=tmp_path / "rt"):
            token = get_or_create_runtime_token()
            assert verify_token(token) is True

    def test_verify_token_wrong(self, tmp_path: Path) -> None:
        with patch("code_puppy.api.auth._token_path", return_value=tmp_path / "rt"):
            get_or_create_runtime_token()
            assert verify_token("wrong-token-value") is False

    def test_verify_token_empty(self, tmp_path: Path) -> None:
        with patch("code_puppy.api.auth._token_path", return_value=tmp_path / "rt"):
            get_or_create_runtime_token()
            assert verify_token("") is False
            assert verify_token(None) is False


# ---------------------------------------------------------------------------
# Origin validation — legacy is_localhost_origin
# ---------------------------------------------------------------------------


class TestOriginValidation:
    """Tests for localhost origin checks (legacy)."""

    def test_no_origin_is_allowed(self) -> None:
        assert is_localhost_origin(None) is True
        assert is_localhost_origin("") is True

    def test_localhost_origins_allowed(self) -> None:
        assert is_localhost_origin("http://127.0.0.1") is True
        assert is_localhost_origin("http://localhost") is True
        assert is_localhost_origin("http://[::1]") is True

    def test_localhost_with_port_allowed(self) -> None:
        assert is_localhost_origin("http://127.0.0.1:8765") is True
        assert is_localhost_origin("http://localhost:3000") is True

    def test_cross_site_origin_rejected(self) -> None:
        assert is_localhost_origin("https://evil.com") is False
        assert is_localhost_origin("http://192.168.1.1") is False

    def test_trailing_slash_normalised(self) -> None:
        assert is_localhost_origin("http://127.0.0.1/") is True


# ---------------------------------------------------------------------------
# Origin validation — strict host-matching
# ---------------------------------------------------------------------------


class TestValidateOriginAgainstHost:
    """Tests for strict Origin-Host comparison (prevents cross-port CSRF)."""

    def test_absent_origin_allowed(self) -> None:
        """No Origin header (non-browser client) is always allowed."""
        assert validate_origin_against_host(None, "127.0.0.1:8765") is True
        assert validate_origin_against_host("", "127.0.0.1:8765") is True

    def test_exact_host_match_allowed(self) -> None:
        """Origin host matches request Host exactly."""
        assert (
            validate_origin_against_host("http://127.0.0.1:8765", "127.0.0.1:8765")
            is True
        )
        assert (
            validate_origin_against_host("http://localhost:8765", "localhost:8765")
            is True
        )

    def test_different_port_rejected(self) -> None:
        """Cross-port localhost origin rejected when Host differs."""
        assert (
            validate_origin_against_host("http://127.0.0.1:3000", "127.0.0.1:8765")
            is False
        )
        assert (
            validate_origin_against_host("http://localhost:3000", "localhost:8765")
            is False
        )

    def test_cross_site_rejected(self) -> None:
        """Non-localhost origin rejected."""
        assert (
            validate_origin_against_host("https://evil.com", "127.0.0.1:8765") is False
        )

    def test_no_host_falls_back_to_localhost_check(self) -> None:
        """When Host is absent, falls back to is_localhost_origin."""
        assert validate_origin_against_host("http://127.0.0.1:8765", None) is True
        assert validate_origin_against_host("https://evil.com", None) is False

    def test_ipv6_matching(self) -> None:
        """IPv6 localhost origins match correctly."""
        assert validate_origin_against_host("http://[::1]:8765", "[::1]:8765") is True
        assert validate_origin_against_host("http://[::1]:3000", "[::1]:8765") is False

    def test_valid_token_absent_origin(self) -> None:
        """Non-browser clients with valid token and no Origin are OK."""
        assert validate_origin_against_host(None, "127.0.0.1:8765") is True


class TestValidateWSOrigin:
    """WebSocket origin validation mirrors the host-matching check."""

    def test_valid_with_host(self) -> None:
        assert validate_ws_origin("http://127.0.0.1:8765", "127.0.0.1:8765") is True

    def test_invalid_cross_site(self) -> None:
        assert validate_ws_origin("https://evil.com", "127.0.0.1:8765") is False

    def test_absent_origin(self) -> None:
        assert validate_ws_origin(None, "127.0.0.1:8765") is True

    def test_cross_port_rejected(self) -> None:
        assert validate_ws_origin("http://127.0.0.1:3000", "127.0.0.1:8765") is False

    def test_no_host_fallback(self) -> None:
        assert validate_ws_origin("http://127.0.0.1:8765", None) is True


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


class TestRequireRuntimeAuth:
    """Tests for the require_runtime_auth FastAPI dependency."""

    def _make_app(self) -> FastAPI:
        from fastapi import Depends

        app = FastAPI()

        @app.get("/protected")
        async def protected_route(_: None = Depends(require_runtime_auth)):
            return {"ok": True}

        return app

    @pytest.mark.asyncio
    async def test_no_token_returns_401(self, tmp_path: Path) -> None:
        token_path = tmp_path / "rt"
        with patch("code_puppy.api.auth._token_path", return_value=token_path):
            get_or_create_runtime_token()
            transport = ASGITransport(app=self._make_app())
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/protected")
                assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_header_token_succeeds(self, tmp_path: Path) -> None:
        token_path = tmp_path / "rt"
        with patch("code_puppy.api.auth._token_path", return_value=token_path):
            token = get_or_create_runtime_token()
            transport = ASGITransport(app=self._make_app())
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/protected", headers={_HEADER_NAME: token})
                assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_valid_cookie_token_succeeds(self, tmp_path: Path) -> None:
        token_path = tmp_path / "rt"
        with patch("code_puppy.api.auth._token_path", return_value=token_path):
            token = get_or_create_runtime_token()
            transport = ASGITransport(app=self._make_app())
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/protected", cookies={_COOKIE_NAME: token})
                assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_cross_origin_rejected_403(self, tmp_path: Path) -> None:
        token_path = tmp_path / "rt"
        with patch("code_puppy.api.auth._token_path", return_value=token_path):
            token = get_or_create_runtime_token()
            transport = ASGITransport(app=self._make_app())
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get(
                    "/protected",
                    headers={_HEADER_NAME: token, "origin": "https://evil.com"},
                )
                assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_cross_port_localhost_rejected_403(self, tmp_path: Path) -> None:
        """Origin on localhost but different port is rejected (host-matching)."""
        token_path = tmp_path / "rt"
        with patch("code_puppy.api.auth._token_path", return_value=token_path):
            token = get_or_create_runtime_token()
            transport = ASGITransport(app=self._make_app())
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get(
                    "/protected",
                    headers={
                        _HEADER_NAME: token,
                        "origin": "http://127.0.0.1:3000",
                        "host": "127.0.0.1:8765",
                    },
                )
                assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Cookie helper
# ---------------------------------------------------------------------------


class TestCookieHelper:
    """Tests for set_runtime_token_cookie and attach_token_cookie_to_response."""

    def test_cookie_set_on_response(self) -> None:
        from starlette.responses import JSONResponse

        response = JSONResponse({"ok": True})
        set_runtime_token_cookie(response, "test-token-value")
        # Check Set-Cookie header
        cookie_headers = [
            v for k, v in response.headers.items() if k.lower() == "set-cookie"
        ]
        assert any(_COOKIE_NAME in h for h in cookie_headers)
        # Check attributes
        cookie_str = next(h for h in cookie_headers if _COOKIE_NAME in h)
        assert "httponly" in cookie_str.lower()
        assert "samesite=strict" in cookie_str.lower()

    def test_attach_token_cookie(self, tmp_path: Path) -> None:
        from code_puppy.api.auth import attach_token_cookie_to_response
        from starlette.responses import JSONResponse

        token_path = tmp_path / "rt"
        with patch("code_puppy.api.auth._token_path", return_value=token_path):
            response = JSONResponse({"ok": True})
            result = attach_token_cookie_to_response(response)
            cookie_headers = [
                v for k, v in result.headers.items() if k.lower() == "set-cookie"
            ]
            assert any(_COOKIE_NAME in h for h in cookie_headers)


# ---------------------------------------------------------------------------
# WS token extraction
# ---------------------------------------------------------------------------


class TestExtractWSToken:
    """Tests for extract_ws_token from cookie / protocol headers."""

    def test_extract_from_cookie(self) -> None:
        token = extract_ws_token(cookie_header=f"{_COOKIE_NAME}=abc123")
        assert token == "abc123"

    def test_extract_from_cookie_multiple(self) -> None:
        token = extract_ws_token(
            cookie_header=f"other=val; {_COOKIE_NAME}=xyz789; foo=bar"
        )
        assert token == "xyz789"

    def test_extract_from_protocol_header(self) -> None:
        token = extract_ws_token(protocol_headers=[(_HEADER_NAME, "proto-token")])
        assert token == "proto-token"

    def test_no_token_returns_none(self) -> None:
        assert extract_ws_token(cookie_header=None) is None
        assert extract_ws_token(cookie_header="") is None
