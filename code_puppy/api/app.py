"""FastAPI application factory for Code Puppy API."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Default request timeout (seconds) - fail fast!
REQUEST_TIMEOUT = 30.0


class TimeoutMiddleware:
    """ASGI middleware to enforce request timeouts and prevent hanging requests."""

    def __init__(self, app: ASGIApp, timeout: float = REQUEST_TIMEOUT):
        self.app = app
        self.timeout = timeout

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Only wrap HTTP requests. WebSocket connections and /ws/* endpoints must be
        # allowed to stay open, otherwise event streams and terminals would be cut off.
        if scope.get("type") != "http" or str(scope.get("path", "")).startswith("/ws/"):
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_with_tracking(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await asyncio.wait_for(
                self.app(scope, receive, send_with_tracking),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            if response_started:
                # The response headers are already out, so a fresh JSON 504 cannot be
                # sent. Close the response body cleanly instead.
                await send(
                    {"type": "http.response.body", "body": b"", "more_body": False}
                )
                return

            response = JSONResponse(
                status_code=504,
                content={
                    "detail": f"Request timed out after {self.timeout}s",
                    "error": "timeout",
                },
            )
            await response(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for startup and shutdown events.

    Handles graceful cleanup of resources when the server shuts down.
    """
    logger.info("🐶 Code Puppy API starting up...")
    try:
        from code_puppy import plugins
        from code_puppy.config import CONFIG_FILE, load_api_keys_to_environment

        if Path(CONFIG_FILE).exists():
            load_api_keys_to_environment()
            plugins.load_plugin_callbacks()
            logger.info("✓ Code Puppy config and plugins loaded")
        else:
            logger.warning(
                "Code Puppy config file was not found; skipping interactive setup "
                "during API startup"
            )
    except Exception as e:
        logger.error(f"Error during API startup initialization: {e}")
    yield
    # Shutdown: clean up all the things!
    logger.info("🐶 Code Puppy API shutting down, cleaning up...")

    # 1. Close all PTY sessions
    try:
        from code_puppy.api.pty_manager import get_pty_manager

        pty_manager = get_pty_manager()
        await pty_manager.close_all()
        logger.info("✓ All PTY sessions closed")
    except Exception as e:
        logger.error(f"Error closing PTY sessions: {e}")

    # 2. Remove PID file so /api status knows we're gone
    try:
        from code_puppy.config import STATE_DIR

        pid_file = Path(STATE_DIR) / "api_server.pid"
        if pid_file.exists():
            pid_file.unlink()
            logger.info("✓ PID file removed")
    except Exception as e:
        logger.error(f"Error removing PID file: {e}")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        lifespan=lifespan,
        title="Code Puppy API",
        description="REST API and Interactive Terminal for Code Puppy",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Timeout middleware - added first so it wraps everything
    app.add_middleware(TimeoutMiddleware, timeout=REQUEST_TIMEOUT)

    # CORS middleware for frontend access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Local/trusted
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    from code_puppy.api.routers import agents, commands, config, runtime, sessions

    app.include_router(config.router, prefix="/api/config", tags=["config"])
    app.include_router(commands.router, prefix="/api/commands", tags=["commands"])
    app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
    app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
    app.include_router(runtime.router, prefix="/api/runtime", tags=["runtime"])

    # WebSocket endpoints (events + terminal)
    from code_puppy.api.websocket import setup_websocket

    setup_websocket(app)

    # Templates directory
    templates_dir = Path(__file__).parent / "templates"

    @app.get("/")
    async def root():
        """Landing page with links to terminal and docs."""
        return HTMLResponse(
            content="""
<!DOCTYPE html>
<html>
<head>
    <title>Code Puppy 🐶</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-white min-h-screen flex items-center justify-center">
    <div class="text-center">
        <h1 class="text-6xl mb-4">🐶</h1>
        <h2 class="text-3xl font-bold mb-8">Code Puppy</h2>
        <div class="space-x-4">
            <a href="/dashboard" class="px-6 py-3 bg-emerald-600 hover:bg-emerald-700 rounded-lg text-lg font-semibold">
                Open Dashboard
            </a>
            <a href="/terminal" class="px-6 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg text-lg font-semibold">
                Open Terminal
            </a>
            <a href="/docs" class="px-6 py-3 bg-gray-700 hover:bg-gray-600 rounded-lg text-lg">
                API Docs
            </a>
        </div>
        <p class="mt-8 text-gray-400">
            WebSocket: ws://localhost:8765/ws/terminal
        </p>
    </div>
</body>
</html>
        """
        )

    @app.get("/dashboard")
    async def dashboard_page():
        """Serve the integrated Code Puppy dashboard."""
        html_file = templates_dir / "dashboard.html"
        if html_file.exists():
            return FileResponse(html_file, media_type="text/html")
        return HTMLResponse(
            content="<h1>Dashboard template not found</h1>",
            status_code=404,
        )

    @app.get("/app")
    async def app_page():
        """Backward-friendly alias for the dashboard."""
        return RedirectResponse(url="/dashboard")

    @app.get("/terminal")
    async def terminal_page():
        """Serve the interactive terminal page."""
        html_file = templates_dir / "terminal.html"
        if html_file.exists():
            return FileResponse(html_file, media_type="text/html")
        return HTMLResponse(
            content="<h1>Terminal template not found</h1>",
            status_code=404,
        )

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    return app
