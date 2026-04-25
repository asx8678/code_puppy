"""Tests for code_puppy/api/app.py - FastAPI application factory."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from pathlib import Path

from code_puppy.api.app import REQUEST_TIMEOUT, TimeoutMiddleware, create_app, lifespan


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"origin": "http://127.0.0.1"},
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_root(client: AsyncClient) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Code Puppy" in resp.text
    assert "Open Dashboard" in resp.text
    # Root page should set the auth cookie
    cookie_headers = [v for k, v in resp.headers.items() if k.lower() == "set-cookie"]
    assert any("code_puppy_runtime_token" in h for h in cookie_headers)
    assert "Open Terminal" in resp.text


@pytest.mark.asyncio
async def test_terminal_page_exists(client: AsyncClient) -> None:
    resp = await client.get("/terminal")
    # Template file exists in the source tree
    assert resp.status_code == 200
    # Terminal page should set the auth cookie (same as /, /dashboard, /app)
    cookie_headers = [v for k, v in resp.headers.items() if k.lower() == "set-cookie"]
    assert any("code_puppy_runtime_token" in h for h in cookie_headers)


@pytest.mark.asyncio
async def test_terminal_page_not_found(app: FastAPI) -> None:
    """When template file doesn't exist, returns 404 HTML."""
    with patch("pathlib.Path.exists", return_value=False):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/terminal")
            assert resp.status_code == 404
            assert "not found" in resp.text.lower()


def test_create_app_returns_fastapi() -> None:
    app = create_app()
    assert isinstance(app, FastAPI)
    assert app.title == "Code Puppy API"


@pytest.mark.asyncio
async def test_timeout_middleware_allows_normal_requests() -> None:
    """Normal requests pass through without timeout."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/health")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_lifespan_startup_shutdown() -> None:
    """Test lifespan context manager runs startup and shutdown."""
    app = FastAPI()

    mock_manager = MagicMock()
    mock_manager.close_all = AsyncMock()

    with patch(
        "code_puppy.api.app.get_pty_manager", return_value=mock_manager, create=True
    ):
        with patch("code_puppy.api.app.Path") as mock_path_cls:
            mock_pid = MagicMock()
            mock_pid.exists.return_value = True
            mock_path_cls.return_value.__truediv__ = MagicMock(return_value=mock_pid)

            # Patch the imports inside lifespan
            with patch.dict(
                "sys.modules",
                {
                    "code_puppy.api.pty_manager": MagicMock(
                        get_pty_manager=MagicMock(return_value=mock_manager)
                    ),
                    "code_puppy.config": MagicMock(STATE_DIR="/tmp/test_state"),
                },
            ):
                async with lifespan(app):
                    pass  # startup done
                # shutdown done


@pytest.mark.asyncio
async def test_lifespan_shutdown_handles_errors() -> None:
    """Lifespan shutdown handles exceptions gracefully."""
    app = FastAPI()

    with patch.dict(
        "sys.modules",
        {
            "code_puppy.api.pty_manager": MagicMock(
                get_pty_manager=MagicMock(side_effect=Exception("boom"))
            ),
            "code_puppy.config": MagicMock(STATE_DIR="/nonexistent"),
        },
    ):
        async with lifespan(app):
            pass
        # Should not raise


def test_request_timeout_constant() -> None:
    assert REQUEST_TIMEOUT == 30.0


@pytest.mark.asyncio
async def test_timeout_middleware_returns_504() -> None:
    """Slow endpoint triggers 504 from timeout middleware."""
    from starlette.responses import PlainTextResponse

    app = FastAPI()
    app.add_middleware(TimeoutMiddleware, timeout=0.01)

    @app.get("/slow")
    async def slow():
        await asyncio.sleep(10)
        return PlainTextResponse("done")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/slow")
        assert resp.status_code == 504
        assert "timed out" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_timeout_middleware_skips_ws_path() -> None:
    """Requests to /ws/ path skip timeout middleware (ASGI-level check)."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # A regular request to /ws/ path should skip timeout
        resp = await c.get("/ws/nonexistent")
        # Will 404 but won't 504
        assert resp.status_code != 504


@pytest.mark.asyncio
async def test_dashboard_page_returns_template(client: AsyncClient) -> None:
    """Dashboard page returns HTML template with key UI markers."""
    resp = await client.get("/dashboard")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    # Core UI elements
    assert "Code Puppy Dashboard" in resp.text
    assert 'id="prompt-form"' in resp.text
    assert 'id="decision-panel"' in resp.text
    assert 'id="feed"' in resp.text
    # Auth cookie is set on dashboard responses
    cookie_headers = [v for k, v in resp.headers.items() if k.lower() == "set-cookie"]
    assert any("code_puppy_runtime_token" in h for h in cookie_headers)


@pytest.mark.asyncio
async def test_dashboard_contains_api_endpoints(client: AsyncClient) -> None:
    """Dashboard template references all expected API endpoints."""
    resp = await client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    # Runtime endpoints (web-l0a design)
    assert "/api/runtime/status" in html
    assert "/api/runtime/prompt" in html
    assert "/api/runtime/cancel" in html
    assert "/api/runtime/respond" in html
    assert "/api/runtime/approval" in html
    assert "/api/runtime/events" in html
    # Agents endpoint
    assert "/api/agents/" in html
    # WebSocket events endpoint
    assert "/ws/events" in html
    # Navigation links
    assert 'href="/terminal"' in html
    assert 'href="/docs"' in html


@pytest.mark.asyncio
async def test_dashboard_no_client_token_exposure(client: AsyncClient) -> None:
    """Dashboard JS should not read or expose auth tokens in client-side code."""
    resp = await client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    # The api() helper must not attach token headers — cookie-only auth
    assert "X-Code-Puppy-Runtime-Token" not in html
    assert "localStorage" not in html
    assert "sessionStorage" not in html


@pytest.mark.asyncio
async def test_dashboard_uses_existing_cdn_only(client: AsyncClient) -> None:
    """Dashboard should only use Tailwind CDN (already in landing page), no new CDNs."""
    resp = await client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    # Only CDN reference should be Tailwind (already used in root page)
    cdn_refs = [line for line in html.splitlines() if 'src="https://' in line or 'href="https://' in line]
    assert len(cdn_refs) >= 1, "Expected at least Tailwind CDN"
    for ref in cdn_refs:
        assert "cdn.tailwindcss.com" in ref, f"Unexpected CDN reference: {ref}"


def test_dashboard_template_file_exists() -> None:
    """The dashboard.html template file exists on disk."""
    templates_dir = Path(__file__).resolve().parent.parent.parent / "code_puppy" / "api" / "templates"
    assert (templates_dir / "dashboard.html").exists()


@pytest.mark.asyncio
async def test_dashboard_page_not_found() -> None:
    """When dashboard template doesn't exist, returns 404 HTML."""
    with patch("pathlib.Path.exists", return_value=False):
        transport = ASGITransport(app=create_app())
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/dashboard")
            assert resp.status_code == 404
            assert "not found" in resp.text.lower()


@pytest.mark.asyncio
async def test_app_page_redirects_to_dashboard() -> None:
    """The /app route redirects to /dashboard."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        follow_redirects=False,
        headers={"origin": "http://127.0.0.1"},
    ) as c:
        resp = await c.get("/app")
        assert resp.status_code in (307, 308)


@pytest.mark.asyncio
async def test_cors_rejects_wildcard_origin() -> None:
    """CORS should NOT allow wildcard / cross-site origins."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as c:
        # A cross-site origin should not get CORS access
        resp = await c.get(
            "/health",
            headers={"origin": "https://evil.com"},
        )
        # The response should NOT have a wildcard or evil.com CORS header
        allow_origin = resp.headers.get("access-control-allow-origin", "")
        assert allow_origin != "*"
        assert "evil.com" not in allow_origin


@pytest.mark.asyncio
async def test_cors_no_wildcard_in_config() -> None:
    """CORS allow_origins, allow_methods, allow_headers should not contain wildcards."""
    app = create_app()
    # Check the middleware stack for CORS configuration
    from starlette.middleware.cors import CORSMiddleware

    for layer in app.user_middleware:
        if hasattr(layer, "kwargs") and hasattr(layer, "cls"):
            if layer.cls is CORSMiddleware or (
                isinstance(getattr(layer, "cls", None), type)
                and issubclass(layer.cls, CORSMiddleware)
            ):
                origins = layer.kwargs.get("allow_origins", [])
                methods = layer.kwargs.get("allow_methods", [])
                headers = layer.kwargs.get("allow_headers", [])
                assert "*" not in origins, (
                    f"CORS allow_origins should not contain '*': {origins}"
                )
                assert "*" not in methods, (
                    f"CORS allow_methods should not contain '*': {methods}"
                )
                assert "*" not in headers, (
                    f"CORS allow_headers should not contain '*': {headers}"
                )
                # Verify the runtime token header is explicitly allowed
                assert "X-Code-Puppy-Runtime-Token" in headers, (
                    f"CORS allow_headers should include 'X-Code-Puppy-Runtime-Token': {headers}"
                )
                assert "Content-Type" in headers, (
                    f"CORS allow_headers should include 'Content-Type': {headers}"
                )
    # At least verify the app builds
    assert isinstance(app, FastAPI)


@pytest.mark.asyncio
async def test_lifespan_pid_file_cleanup() -> None:
    """Test PID file removal during shutdown."""
    import tempfile
    from pathlib import Path as RealPath

    with tempfile.TemporaryDirectory() as tmpdir:
        pid_file = RealPath(tmpdir) / "api_server.pid"
        pid_file.write_text("12345")

        mock_manager = MagicMock()
        mock_manager.close_all = AsyncMock()

        with patch.dict(
            "sys.modules",
            {
                "code_puppy.api.pty_manager": MagicMock(
                    get_pty_manager=MagicMock(return_value=mock_manager)
                ),
                "code_puppy.config": MagicMock(STATE_DIR=tmpdir),
            },
        ):
            app = FastAPI()
            async with lifespan(app):
                pass
            assert not pid_file.exists()
